"""scripts/users.py — account admin CLI over UserStore/EventStore, run against redat.db."""
import importlib.util
import sqlite3
from pathlib import Path

from redat.auth.passwords import verify_password
from redat.store.events import EventStore
from redat.store.users import UserStore

_spec = importlib.util.spec_from_file_location("users_cli", Path(__file__).resolve().parent.parent / "scripts" / "users.py")
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


def _stores(tmp_path):
    db = tmp_path / "redat.db"
    users, events = UserStore(db), EventStore(db)
    users.init(); events.init()
    return db, users, events


def test_list_empty(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("REDAT_DATA_DIR", str(tmp_path))
    assert mod.main(["list"]) == 0
    assert "no users" in capsys.readouterr().out


def test_create_admin_via_password_env_then_list(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("REDAT_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("REDAT_TEST_PW", "test123!")
    assert mod.main(["create-admin", "--username", "admin", "--password-env", "REDAT_TEST_PW"]) == 0
    out = capsys.readouterr().out
    assert "admin" in out

    assert mod.main(["list"]) == 0
    out = capsys.readouterr().out
    assert "admin" in out and "admin" in out.split("\n")[1]  # role column
    assert "active" in out

    _, users, _ = _stores(tmp_path)
    row = users.get_by_username("admin")
    assert row["role"] == "admin"
    assert verify_password("test123!", row["password_hash"])


def test_create_admin_password_policy_error_is_exit_1(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("REDAT_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("REDAT_TEST_PW", "short")
    rc = mod.main(["create-admin", "--username", "admin", "--password-env", "REDAT_TEST_PW"])
    assert rc == 1
    assert capsys.readouterr().err.strip() != ""

    _, users, _ = _stores(tmp_path)
    assert users.get_by_username("admin") is None


def test_create_admin_via_getpass_prompts_twice(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("REDAT_DATA_DIR", str(tmp_path))
    answers = iter(["test123!", "test123!"])
    monkeypatch.setattr(mod.getpass, "getpass", lambda prompt="": next(answers))
    assert mod.main(["create-admin", "--username", "admin"]) == 0
    _, users, _ = _stores(tmp_path)
    assert verify_password("test123!", users.get_by_username("admin")["password_hash"])


def test_create_admin_via_getpass_mismatch_is_exit_1(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("REDAT_DATA_DIR", str(tmp_path))
    answers = iter(["test123!", "different!"])
    monkeypatch.setattr(mod.getpass, "getpass", lambda prompt="": next(answers))
    rc = mod.main(["create-admin", "--username", "admin"])
    assert rc == 1
    assert capsys.readouterr().err.strip() != ""
    _, users, _ = _stores(tmp_path)
    assert users.get_by_username("admin") is None


def test_reset_unknown_user_is_exit_1(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("REDAT_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("REDAT_TEST_PW", "test123!")
    rc = mod.main(["reset", "--username", "nope", "--password-env", "REDAT_TEST_PW"])
    assert rc == 1
    assert "nope" in capsys.readouterr().err


def test_reset_changes_password(tmp_path, monkeypatch, capsys):
    _, users, _ = _stores(tmp_path)
    users.create("anna", "old-password1")
    monkeypatch.setenv("REDAT_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("REDAT_TEST_PW", "new-password1")
    assert mod.main(["reset", "--username", "anna", "--password-env", "REDAT_TEST_PW"]) == 0
    row = users.get_by_username("anna")
    assert verify_password("new-password1", row["password_hash"])
    assert not verify_password("old-password1", row["password_hash"])


def test_disable_then_enable(tmp_path, monkeypatch, capsys):
    _, users, _ = _stores(tmp_path)
    users.create("anna", "test123!")
    monkeypatch.setenv("REDAT_DATA_DIR", str(tmp_path))

    assert mod.main(["disable", "--username", "anna"]) == 0
    row = users.get_by_username("anna")
    assert row["disabled_at"] is not None

    out = capsys.readouterr().out
    assert mod.main(["list"]) == 0
    out = capsys.readouterr().out
    assert "disabled" in out

    assert mod.main(["enable", "--username", "anna"]) == 0
    row = users.get_by_username("anna")
    assert row["disabled_at"] is None


def test_disable_unknown_user_is_exit_1(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("REDAT_DATA_DIR", str(tmp_path))
    rc = mod.main(["disable", "--username", "nope"])
    assert rc == 1
    assert "nope" in capsys.readouterr().err


def test_disabling_a_user_deletes_their_sessions(tmp_path, monkeypatch, capsys):
    db, users, _ = _stores(tmp_path)
    user = users.create("anna", "test123!")
    token = users.create_session(user["id"], user_agent="pytest", ip="test")
    monkeypatch.setenv("REDAT_DATA_DIR", str(tmp_path))
    assert mod.main(["disable", "--username", "anna"]) == 0
    assert users.resolve_session(token) is None


def test_prune_events(tmp_path, monkeypatch, capsys):
    db, users, events = _stores(tmp_path)
    events.record("login_failed", extra={"username": "x"})
    con = sqlite3.connect(db)
    con.execute("UPDATE events SET ts = '2000-01-01T00:00:00Z'")
    con.commit(); con.close()
    events.record("login_failed", extra={"username": "y"})

    monkeypatch.setenv("REDAT_DATA_DIR", str(tmp_path))
    assert mod.main(["prune-events", "--days", "30"]) == 0
    assert "removed 1" in capsys.readouterr().out
    assert len(events.recent(50)) == 1
