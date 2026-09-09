"""redat/store/users.py — users, sessions, invites in a temp SQLite file."""
from datetime import datetime, timedelta, timezone

import pytest

from redat.auth.tokens import token_hash
from redat.store.users import InvalidUsernameError, UsernameTakenError, UserStore


@pytest.fixture
def store(tmp_path):
    s = UserStore(tmp_path / "redat.db")
    s.init()
    s.init()          # idempotent
    return s


def test_create_get_and_list(store):
    u = store.create("Mitja", "test123!", role="admin")
    assert u["username"] == "mitja" and u["role"] == "admin" and u["id"] == 1 and "password_hash" not in u
    assert store.count() == 1 and store.get(1)["username"] == "mitja" and store.get(99) is None
    assert store.get_by_username("MITJA")["password_hash"].startswith("scrypt$")
    assert [x["username"] for x in store.list_users()] == ["mitja"]


def test_username_rules(store):
    store.create("a.b-c_1", "test123!")
    for bad in ("ab", "x" * 33, "mit ja", "ümlaut", "admin!"):
        with pytest.raises(InvalidUsernameError):
            store.create(bad, "test123!")
    with pytest.raises(UsernameTakenError):
        store.create("A.B-C_1", "test123!")


def test_password_change_and_disable(store):
    u = store.create("mitja", "test123!")
    store.set_password(u["id"], "neuesPasswort9")
    from redat.auth.passwords import verify_password
    assert verify_password("neuesPasswort9", store.get_by_username("mitja")["password_hash"])
    store.set_disabled(u["id"], True)
    assert store.get(u["id"])["disabled_at"] is not None
    store.set_disabled(u["id"], False)
    assert store.get(u["id"])["disabled_at"] is None


def test_sessions_resolve_touch_expire_and_delete(store):
    u = store.create("mitja", "test123!")
    tok = store.create_session(u["id"], user_agent="pytest", ip="127.0.0.1", days=30)
    assert len(tok) >= 40
    row = store.resolve_session(tok)
    assert row["username"] == "mitja" and row["session_token_hash"] == token_hash(tok) and "password_hash" not in row
    assert store.resolve_session("nope") is None
    assert [s["user_agent"] for s in store.list_sessions(u["id"])] == ["pytest"]
    # expired sessions are rejected and removed
    with store._connect() as con:
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        con.execute("UPDATE sessions SET expires_at = ?", (past,))
    assert store.resolve_session(tok) is None and store.list_sessions(u["id"]) == []
    # a disabled user's session resolves to None and is deleted
    tok2 = store.create_session(u["id"])
    store.set_disabled(u["id"], True)
    assert store.resolve_session(tok2) is None and store.list_sessions(u["id"]) == []
    store.set_disabled(u["id"], False)
    t3, t4 = store.create_session(u["id"]), store.create_session(u["id"])
    assert store.delete_user_sessions(u["id"], keep_token=t3) == 1
    assert store.resolve_session(t3) and store.resolve_session(t4) is None
    store.delete_session(t3)
    assert store.resolve_session(t3) is None


def test_touch_session_slides_expiry_at_most_hourly(store):
    u = store.create("mitja", "test123!")
    tok = store.create_session(u["id"], days=30)
    with store._connect() as con:
        old = (datetime.now(timezone.utc) - timedelta(days=2)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        con.execute("UPDATE sessions SET last_seen_at = ?, expires_at = ?", (old, old))
    store.touch_session(tok, days=30)
    s = store.list_sessions(u["id"])[0]
    assert s["last_seen_at"] > old and s["expires_at"] > old
    seen = s["last_seen_at"]
    store.touch_session(tok, days=30)            # within the hour → unchanged
    assert store.list_sessions(u["id"])[0]["last_seen_at"] == seen


def test_delete_user_cascades_sessions(store):
    u = store.create("mitja", "test123!")
    tok = store.create_session(u["id"])
    store.delete(u["id"])
    assert store.get(u["id"]) is None and store.resolve_session(tok) is None


def test_invites_lifecycle(store):
    admin = store.create("admin", "test123!", role="admin")
    tok = store.create_invite(admin["id"], note="Anna", role="user", days=7)
    inv = store.get_invite(tok)
    assert inv["note"] == "Anna" and inv["role"] == "user" and inv["reset_user_id"] is None and inv["used_at"] is None
    assert store.get_invite("nope") is None
    anna = store.create("anna", "test123!", invited_by=admin["id"])
    store.use_invite(tok, anna["id"])
    assert store.get_invite(tok) is None                       # used → no longer valid
    rows = store.list_invites()
    assert rows[0]["used_by_username"] == "anna" and rows[0]["created_by_username"] == "admin"
    tok2 = store.create_invite(admin["id"], note="Bob")
    assert store.revoke_invite(token_hash(tok2)) is True and store.get_invite(tok2) is None
    assert store.revoke_invite("nope") is False
    tok3 = store.create_invite(admin["id"], note="alt", days=0)   # expires immediately
    assert store.get_invite(tok3) is None
    reset = store.create_invite(admin["id"], note="Reset anna", reset_user_id=anna["id"])
    assert store.get_invite(reset)["reset_user_id"] == anna["id"]
