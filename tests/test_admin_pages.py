"""/admin — dashboard, invites, user actions; admin only."""
import pytest
from fastapi.testclient import TestClient

from redat.auth.tokens import token_hash
from tests.helpers_auth import csrf, login


@pytest.fixture
def client():
    from redat.app import create_app
    with TestClient(create_app(), follow_redirects=False) as c:
        yield c


def test_dashboard_shows_stats_users_and_activity(client):
    admin = login(client, username="root", role="admin")
    bob = client.app.state.users.create("bob", "test123!")
    ev = client.app.state.events
    ev.record("analyze", user_id=bob["id"], via="session", address="Musterstraße 1, Essen", run_id="r1")
    ev.record("pdf", user_id=bob["id"], run_id="r1")
    r = client.get("/admin")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    assert "Musterstraße 1, Essen" in r.text and "bob" in r.text and 'id="usage-per-day"' in r.text
    assert "Analysen" in r.text and "Einladungslink" in r.text


def test_create_invite_shows_the_url_once_and_records(client):
    login(client, username="root", role="admin")
    r = client.post("/admin/invites", data={"note": "Anna", "role": "user", "csrf": csrf(client)})
    assert r.status_code == 200 and "/invite/" in r.text and "Anna" in r.text
    assert client.app.state.events.recent(1)[0]["kind"] == "invite_created"
    inv = client.app.state.users.list_invites()[0]
    assert inv["status"] == "offen" and inv["note"] == "Anna"
    r = client.post(f"/admin/invites/{inv['token_hash']}/revoke", data={"csrf": csrf(client)})
    assert r.status_code == 303 and client.app.state.users.list_invites() == []


def test_user_actions(client):
    admin = login(client, username="root", role="admin")
    bob = client.app.state.users.create("bob", "test123!")
    tok = client.app.state.users.create_session(bob["id"])
    assert client.post(f"/admin/users/{bob['id']}/disable", data={"csrf": csrf(client)}).status_code == 303
    assert client.app.state.users.get(bob["id"])["disabled_at"] and client.app.state.users.resolve_session(tok) is None
    assert client.post(f"/admin/users/{bob['id']}/enable", data={"csrf": csrf(client)}).status_code == 303
    r = client.post(f"/admin/users/{bob['id']}/reset", data={"csrf": csrf(client)})
    assert r.status_code == 200 and "/invite/" in r.text
    assert client.app.state.users.list_invites()[0]["reset_user_id"] == bob["id"]
    assert client.post(f"/admin/users/{bob['id']}/delete", data={"csrf": csrf(client)}).status_code == 303
    assert client.app.state.users.get(bob["id"]) is None
    for action in ("disable", "delete"):
        assert client.post(f"/admin/users/{admin['id']}/{action}", data={"csrf": csrf(client)}).status_code == 400
    assert client.post(f"/admin/users/{bob['id']}/explode", data={"csrf": csrf(client)}).status_code == 404
    assert client.post(f"/admin/users/{admin['id']}/disable", data={"csrf": "wrong"}).status_code == 403


def test_non_admin_is_forbidden(client):
    login(client, username="bob")
    assert client.get("/admin").status_code == 403
    assert client.post("/admin/invites", data={"note": "x", "role": "user", "csrf": csrf(client)}).status_code == 403
