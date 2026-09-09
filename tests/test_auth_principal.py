"""Gating: session cookie or X-Api-Key for the API, 303 → /login for pages, public permalinks, admin role."""
import pytest
from fastapi.testclient import TestClient

from redat.auth.principal import SESSION_COOKIE, safe_next
from tests.helpers_auth import login


@pytest.fixture
def client():
    from redat.app import create_app
    with TestClient(create_app(), follow_redirects=False) as c:
        yield c


def test_api_requires_a_principal(client):
    r = client.get("/api/v1/sections")
    assert r.status_code == 401 and r.json()["detail"] == "Anmeldung erforderlich"


def test_session_cookie_grants_access(client):
    login(client)
    assert client.get("/api/v1/sections").status_code == 200


def test_api_key_is_still_a_credential(client, monkeypatch):
    from redat import settings as s
    monkeypatch.setenv("REDAT_API_KEY", "geheim-123")
    s.reset_settings()
    assert client.get("/api/v1/sections", headers={"X-Api-Key": "geheim-123"}).status_code == 200
    assert client.get("/api/v1/sections", headers={"X-Api-Key": "falsch"}).status_code == 401
    assert client.get("/api/v1/sections").status_code == 401


def test_unknown_expired_or_disabled_session_is_rejected(client):
    client.cookies.set(SESSION_COOKIE, "not-a-session")
    assert client.get("/api/v1/sections").status_code == 401
    u = login(client, username="anna")
    client.app.state.users.set_disabled(u["id"], True)
    assert client.get("/api/v1/sections").status_code == 401
    assert client.app.state.users.list_sessions(u["id"]) == []


def test_pages_redirect_to_login_with_next(client):
    r = client.get("/?address=Musterstr")
    assert r.status_code == 303 and r.headers["location"] == "/login?next=%2F%3Faddress%3DMusterstr"
    assert client.get("/docs").status_code in (303, 401)
    login(client)
    assert client.get("/").status_code == 200


def test_public_routes_need_no_login(client):
    assert client.get("/healthz").status_code == 200
    assert client.get("/quellen").status_code == 200
    assert client.get("/a/nope").status_code == 404
    assert client.get("/api/v1/run/nope").status_code == 404           # public: 404, not 401
    assert client.get("/api/v1/run/nope/report.pdf").status_code == 404
    assert client.get("/login").status_code in (200, 404)


def test_admin_routes_need_the_admin_role(client):
    # /admin is not routed until Task 4 (see admin_pages.py there), so every call 404s in this task —
    # loosened here per the brief's note and tightened to 303/403/200 in Task 4.
    assert client.get("/admin").status_code != 200
    login(client, username="bob")
    assert client.get("/admin").status_code != 200
    login(client, username="root", role="admin")
    assert client.get("/admin").status_code != 403


def test_safe_next():
    assert safe_next("/a/xyz?x=1") == "/a/xyz?x=1"
    for bad in ("", None, "https://evil.example", "//evil.example", "javascript:alert(1)", "/login"):
        assert safe_next(bad) == "/"
