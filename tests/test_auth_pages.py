"""Login / logout / invite / account pages — hermetic TestClient flows."""
import pytest
from fastapi.testclient import TestClient

from redat.auth.principal import CSRF_COOKIE, SESSION_COOKIE
from tests.helpers_auth import csrf, login


@pytest.fixture
def client():
    from redat.app import create_app
    with TestClient(create_app(), follow_redirects=False) as c:
        yield c


def _admin(client):
    return client.app.state.users.create("admin", "test123!", role="admin")


def test_login_page_sets_csrf_cookie_and_states_the_recording(client):
    r = client.get("/login")
    assert r.status_code == 200 and 'name="csrf"' in r.text and "aufgezeichnet" in r.text
    assert CSRF_COOKIE in r.cookies and r.headers["cache-control"] == "no-store"


def test_login_needs_matching_csrf(client):
    _admin(client)
    client.get("/login")
    r = client.post("/login", data={"username": "admin", "password": "test123!", "csrf": "wrong"})
    assert r.status_code == 403


def test_wrong_password_is_401_and_recorded(client):
    _admin(client)
    r = client.post("/login", data={"username": "admin", "password": "nope", "csrf": csrf(client)})
    assert r.status_code == 401 and "Benutzername oder Passwort falsch" in r.text
    ev = client.app.state.events.recent(5)
    assert ev[0]["kind"] == "login_failed" and ev[0]["extra"] == {"username": "admin"}


def test_login_sets_session_cookie_and_redirects_to_next(client):
    _admin(client)
    r = client.post("/login", data={"username": "Admin", "password": "test123!", "csrf": csrf(client), "next": "/a/xyz"})
    assert r.status_code == 303 and r.headers["location"] == "/a/xyz"
    cookie = r.headers.get("set-cookie", "")
    assert SESSION_COOKIE in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie.replace("SameSite=Lax", "SameSite=lax")
    assert client.get("/api/v1/sections").status_code == 200
    assert client.app.state.events.recent(1)[0]["kind"] == "login"
    assert client.app.state.users.get_by_username("admin")["last_login_at"] is not None


def test_open_redirects_are_neutralised(client):
    _admin(client)
    r = client.post("/login", data={"username": "admin", "password": "test123!", "csrf": csrf(client), "next": "https://evil.example"})
    assert r.headers["location"] == "/"


def test_disabled_user_cannot_log_in(client):
    u = _admin(client)
    client.app.state.users.set_disabled(u["id"], True)
    r = client.post("/login", data={"username": "admin", "password": "test123!", "csrf": csrf(client)})
    # Correct password, disabled account: same 401 and the same message as a wrong password — no
    # separate wording that would let an attacker distinguish "wrong password" from "disabled".
    assert r.status_code == 401 and "Benutzername oder Passwort falsch" in r.text


def test_five_failures_lock_the_account_for_a_minute(client):
    from redat.auth import throttle as th
    th.login_throttle.__init__()                      # fresh throttle for this test
    _admin(client)
    for _ in range(5):
        client.post("/login", data={"username": "admin", "password": "nope", "csrf": csrf(client)})
    r = client.post("/login", data={"username": "admin", "password": "test123!", "csrf": csrf(client)})
    assert r.status_code == 429 and "Zu viele Fehlversuche" in r.text
    th.login_throttle.__init__()


def test_logout_deletes_the_session(client):
    u = login(client)
    r = client.post("/logout", data={"csrf": csrf(client)})
    assert r.status_code == 303 and r.headers["location"] == "/login"
    assert client.app.state.users.list_sessions(u["id"]) == []
    assert client.get("/api/v1/sections").status_code == 401


def test_invite_flow_creates_user_and_logs_in(client):
    admin = _admin(client)
    tok = client.app.state.users.create_invite(admin["id"], note="Anna", role="user")
    r = client.get(f"/invite/{tok}")
    assert r.status_code == 200 and 'name="username"' in r.text and "Anna" in r.text
    r = client.post(f"/invite/{tok}", data={"username": "anna", "password": "test123!", "password2": "test123!", "csrf": csrf(client)})
    assert r.status_code == 303 and r.headers["location"] == "/" and SESSION_COOKIE in r.headers.get("set-cookie", "")
    anna = client.app.state.users.get_by_username("anna")
    assert anna["role"] == "user" and anna["invited_by"] == admin["id"]
    assert client.app.state.users.get_invite(tok) is None
    assert client.get(f"/invite/{tok}").status_code == 404
    assert client.app.state.events.recent(1)[0]["kind"] == "invite_accepted"


def test_invite_validation_errors_stay_on_the_form(client):
    admin = _admin(client)
    tok = client.app.state.users.create_invite(admin["id"])
    r = client.post(f"/invite/{tok}", data={"username": "ok", "password": "test123!", "password2": "test123!", "csrf": csrf(client)})
    assert r.status_code == 400 and "Benutzername" in r.text
    r = client.post(f"/invite/{tok}", data={"username": "anna", "password": "test123!", "password2": "anders123", "csrf": csrf(client)})
    assert r.status_code == 400 and "stimmen nicht überein" in r.text
    r = client.post(f"/invite/{tok}", data={"username": "admin", "password": "test123!", "password2": "test123!", "csrf": csrf(client)})
    assert r.status_code == 400 and "bereits vergeben" in r.text
    assert client.app.state.users.get_invite(tok) is not None          # still usable


def test_invite_submit_surfaces_any_value_error_from_create_instead_of_500(client):
    admin = _admin(client)
    # create() raises a bare ValueError for an unknown role — unreachable through the admin form
    # (which validates role) but not through a hand-built invite row; invite_submit must catch it.
    tok = client.app.state.users.create_invite(admin["id"], role="bogus")
    r = client.post(f"/invite/{tok}", data={"username": "anna", "password": "test123!", "password2": "test123!", "csrf": csrf(client)})
    assert r.status_code == 400 and "role" in r.text
    assert client.app.state.users.get_by_username("anna") is None
    assert client.app.state.users.get_invite(tok) is not None          # not consumed


def test_reset_invite_for_a_disabled_user_is_refused(client):
    admin = _admin(client)
    bob = client.app.state.users.create("bob", "test123!")
    client.app.state.users.set_disabled(bob["id"], True)
    old_hash = client.app.state.users.get_by_username("bob")["password_hash"]
    tok = client.app.state.users.create_invite(admin["id"], note="Reset bob", reset_user_id=bob["id"])
    r = client.post(f"/invite/{tok}", data={"password": "neuesPasswort9", "password2": "neuesPasswort9", "csrf": csrf(client)})
    assert r.status_code == 403 and "deaktiviert" in r.text
    assert SESSION_COOKIE not in r.headers.get("set-cookie", "")
    assert client.app.state.users.get_by_username("bob")["password_hash"] == old_hash
    assert client.app.state.users.get_invite(tok) is not None          # still usable


def test_reset_invite_sets_password_and_ends_other_sessions(client):
    admin = _admin(client)
    bob = client.app.state.users.create("bob", "test123!")
    old = client.app.state.users.create_session(bob["id"])
    tok = client.app.state.users.create_invite(admin["id"], note="Reset bob", reset_user_id=bob["id"])
    r = client.get(f"/invite/{tok}")
    assert r.status_code == 200 and 'name="username"' not in r.text and "bob" in r.text
    r = client.post(f"/invite/{tok}", data={"password": "neuesPasswort9", "password2": "neuesPasswort9", "csrf": csrf(client)})
    assert r.status_code == 303
    from redat.auth.passwords import verify_password
    assert verify_password("neuesPasswort9", client.app.state.users.get_by_username("bob")["password_hash"])
    assert client.app.state.users.resolve_session(old) is None
    assert client.app.state.events.recent(1)[0]["kind"] == "password_reset"


def test_konto_password_change_and_logout_others(client):
    u = login(client, username="carla")
    other = client.app.state.users.create_session(u["id"])
    r = client.get("/konto")
    assert r.status_code == 200 and "carla" in r.text and r.text.count("pytest") >= 1
    r = client.post("/konto/password", data={"current": "falsch", "password": "neuesPasswort9", "password2": "neuesPasswort9", "csrf": csrf(client)})
    assert r.status_code == 400 and "aktuelle Passwort" in r.text
    r = client.post("/konto/password", data={"current": "test123!", "password": "neuesPasswort9", "password2": "neuesPasswort9", "csrf": csrf(client)})
    assert r.status_code == 303 and r.headers["location"] == "/konto?ok=passwort"
    assert client.app.state.users.resolve_session(other) is None            # other devices signed out
    assert client.get("/konto").status_code == 200                           # this session survives
    other2 = client.app.state.users.create_session(u["id"])
    r = client.post("/konto/logout-others", data={"csrf": csrf(client)})
    assert r.status_code == 303 and client.app.state.users.resolve_session(other2) is None


def test_navigation_reflects_login_state(client):
    r = client.get("/quellen")
    assert "Anmelden" in r.text and "Abmelden" not in r.text
    login(client, username="root", role="admin")
    r = client.get("/quellen")
    assert "root" in r.text and "Abmelden" in r.text and 'href="/admin"' in r.text and 'href="/konto"' in r.text
