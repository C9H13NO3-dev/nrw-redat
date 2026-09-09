"""Gating: session cookie or X-Api-Key for the API, 303 → /login for pages, public permalinks, admin role."""
import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from redat.auth.principal import SESSION_COOKIE, client_ip, safe_next
from tests.helpers_auth import csrf, login


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
    assert client.get("/login").status_code == 200


def test_admin_routes_need_the_admin_role(client):
    assert client.get("/admin").status_code == 303
    login(client, username="bob")
    assert client.get("/admin").status_code == 403
    login(client, username="root", role="admin")
    assert client.get("/admin").status_code == 200


def test_safe_next():
    assert safe_next("/a/xyz?x=1") == "/a/xyz?x=1"
    for bad in ("", None, "https://evil.example", "//evil.example", "javascript:alert(1)", "/login", "/\\evil.example"):
        assert safe_next(bad) == "/"


def _bare_request(client_host: str, xff: str = None) -> Request:
    headers = [(b"x-forwarded-for", xff.encode())] if xff is not None else []
    return Request({"type": "http", "headers": headers, "client": (client_host, 12345)})


def test_client_ip_honours_xff_from_a_trusted_proxy():
    r = _bare_request("172.18.0.2", xff="203.0.113.9, 10.0.0.5")
    assert client_ip(r) == "203.0.113.9"


def test_client_ip_ignores_xff_from_an_untrusted_peer():
    r = _bare_request("203.0.113.9", xff="1.2.3.4")
    assert client_ip(r) == "203.0.113.9"


def test_client_ip_falls_back_to_the_peer_without_xff():
    assert client_ip(_bare_request("172.18.0.2")) == "172.18.0.2"


def test_client_ip_unparseable_peer_is_returned_unchanged_and_untrusted():
    r = _bare_request("testclient", xff="1.2.3.4")
    assert client_ip(r) == "testclient"


def test_client_ip_respects_a_custom_trusted_proxies_setting(monkeypatch):
    from redat import settings as s
    monkeypatch.setenv("REDAT_TRUSTED_PROXIES", "203.0.113.0/24")
    s.reset_settings()
    assert client_ip(_bare_request("203.0.113.9", xff="9.9.9.9")) == "9.9.9.9"
    # 172.18.0.2 was trusted by default (Docker network) but is not in the custom list:
    assert client_ip(_bare_request("172.18.0.2", xff="9.9.9.9")) == "172.18.0.2"


def test_login_throttle_survives_a_spoofed_xff_from_an_untrusted_peer(client):
    from redat.auth import throttle as th
    th.login_throttle.__init__()
    client.app.state.users.create("admin", "test123!", role="admin")
    for i in range(5):
        client.post("/login", data={"username": "admin", "password": "nope", "csrf": csrf(client)},
                    headers={"X-Forwarded-For": f"198.51.100.{i}"})
    r = client.post("/login", data={"username": "admin", "password": "test123!", "csrf": csrf(client)},
                    headers={"X-Forwarded-For": "198.51.100.99"})
    assert r.status_code == 429 and "Zu viele Fehlversuche" in r.text
    th.login_throttle.__init__()
