import re
import sqlite3
import pytest
from redat.store.runs import RunStore

PAYLOAD = {
    "address": "Brückstraße 1, Essen", "formatted_address": "Brückstraße 1, 45239 Essen",
    "latitude": 51.3878, "longitude": 7.0011, "precision": "house",
    "plot_size_m2": 400, "living_space_m2": 120,
    "sections": {"noise": {"key": "noise", "status": "ok", "data": {"day": None}}},
}


def _store(tmp_path):
    s = RunStore(tmp_path / "redat.db"); s.init(); return s


def test_new_run_id_shape(tmp_path):
    s = _store(tmp_path)
    ids = {s.new_run_id() for _ in range(50)}
    assert len(ids) == 50 and all(re.fullmatch(r"[a-z2-7]{10}", i) for i in ids)


def test_save_and_get_roundtrip(tmp_path):
    s = _store(tmp_path)
    rid = s.save(PAYLOAD)
    got = s.get(rid)
    assert got["id"] == rid and got["created_at"].endswith("Z")
    for k, v in PAYLOAD.items():
        assert got[k] == v


def test_get_unknown_is_none(tmp_path):
    assert _store(tmp_path).get("nope") is None


def test_init_is_idempotent_and_wal(tmp_path):
    s = _store(tmp_path); s.init()
    con = sqlite3.connect(s.db_path)
    assert con.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_save_requires_coordinates(tmp_path):
    with pytest.raises(ValueError):
        _store(tmp_path).save({**PAYLOAD, "latitude": None})


def test_connections_are_closed_after_use(tmp_path, monkeypatch):
    """Verify that connections are closed after each call to prevent fd leaks."""
    s = _store(tmp_path)
    tracked_connections = []

    original_connect = sqlite3.connect
    def tracked_connect(*args, **kwargs):
        con = original_connect(*args, **kwargs)
        tracked_connections.append(con)
        return con

    monkeypatch.setattr(sqlite3, "connect", tracked_connect)

    # Test save() closes its connection
    rid = s.save(PAYLOAD)

    # Test get() closes its connection
    got = s.get(rid)
    assert got is not None

    # Verify all tracked connections are closed by trying to execute on them
    for con in tracked_connections:
        with pytest.raises(sqlite3.ProgrammingError):
            con.execute("SELECT 1")
