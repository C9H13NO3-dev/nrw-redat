"""redat/store/events.py — append-only usage events and the dashboard statistics."""
from datetime import datetime, timedelta, timezone

import pytest

from redat.store.events import EventStore
from redat.store.users import UserStore


@pytest.fixture
def stores(tmp_path):
    db = tmp_path / "redat.db"
    u, e = UserStore(db), EventStore(db)
    u.init(); e.init(); e.init()
    return u, e


def _backdate(e: EventStore, event_id: int, days: int) -> None:
    ts = (datetime.now(timezone.utc) - timedelta(days=days)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    with e._connect() as con:
        con.execute("UPDATE events SET ts = ? WHERE id = ?", (ts, event_id))


def test_record_and_recent(stores):
    u, e = stores
    admin = u.create("admin", "test123!", role="admin")
    i = e.record("analyze", user_id=admin["id"], via="session", address="Am Käferberg 12, Bonn", lat=50.716, lon=7.075,
                 run_id="abc", extra={"ok": 26, "error": 0, "empty": 2}, ip="10.0.0.1")
    e.record("login_failed", extra={"username": "nobody"}, ip="10.0.0.2")
    r = e.recent(limit=10)
    assert [x["kind"] for x in r] == ["login_failed", "analyze"]              # newest first
    assert r[1]["id"] == i and r[1]["username"] == "admin" and r[1]["extra"] == {"ok": 26, "error": 0, "empty": 2}
    assert r[0]["username"] is None and r[0]["extra"] == {"username": "nobody"}


def test_stats_counts_windows_users_and_days(stores):
    u, e = stores
    a = u.create("admin", "test123!", role="admin")
    b = u.create("bob", "test123!")
    e.record("analyze", user_id=a["id"], address="x")
    old = e.record("analyze", user_id=a["id"], address="y")
    _backdate(e, old, 10)
    older = e.record("analyze", user_id=b["id"], address="z")
    _backdate(e, older, 40)
    e.record("pdf", user_id=b["id"], run_id="r1")
    e.record("permalink_view", run_id="r1")
    e.record("login", user_id=b["id"])
    s = e.stats(days=30)
    assert s["users_total"] == 2 and s["users_active_30d"] == 2
    assert s["analyses"] == {"7d": 1, "30d": 2, "total": 3}
    assert s["pdf_30d"] == 1 and s["views_30d"] == 1
    assert len(s["per_day"]) == 30 and s["per_day"][-1]["analyses"] == 1 and sum(d["analyses"] for d in s["per_day"]) == 2
    assert all(set(d) == {"date", "analyses"} for d in s["per_day"])
    by = {r["username"]: r for r in s["per_user"]}
    assert by["admin"]["analyses_total"] == 2 and by["admin"]["analyses_30d"] == 2 and by["admin"]["pdf_total"] == 0
    assert by["bob"]["analyses_total"] == 1 and by["bob"]["analyses_30d"] == 0 and by["bob"]["pdf_total"] == 1
    assert by["bob"]["last_active"] is not None and by["bob"]["role"] == "user" and by["bob"]["disabled"] is False


def test_prune(stores):
    u, e = stores
    keep = e.record("login")
    old = e.record("login")
    _backdate(e, old, 400)
    assert e.prune(days=365) == 1
    assert [x["id"] for x in e.recent()] == [keep]
