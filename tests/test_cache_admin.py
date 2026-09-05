"""scripts/cache_admin.py — stats / purge for the persistent cache, run against redat.db."""
import importlib.util
from pathlib import Path

import pytest

import redat.store.cache as m
from redat.store.cache import SectionCache

_spec = importlib.util.spec_from_file_location("cache_admin", Path(__file__).resolve().parent.parent / "scripts" / "cache_admin.py")
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


def _env(key): return {"key": key, "status": "ok", "data": {"x": 1}}


def _seed(db):
    c = SectionCache(3600, db_path=db, ttl_overrides={"air_quality": 5})
    c.put(c.key("noise", 1, 1, None, False), _env("noise"))
    c.put(c.key("noise", 2, 2, None, False), _env("noise"))
    c.put(c.key("boris", 1, 1, None, False), _env("boris"))
    c.put(c.key("air_quality", 1, 1, None, False), _env("air_quality"))
    c.kv_put("geocode", "essen", {"lat": 1}, ttl_s=100)
    c.close()


def test_stats_lists_sections_and_namespaces(tmp_path, capsys):
    db = tmp_path / "redat.db"; _seed(db)
    assert mod.main(["--db", str(db), "stats"]) == 0
    out = capsys.readouterr().out
    assert "entries: 5" in out and "noise: 2" in out and "boris: 1" in out and "geocode: 1" in out


def test_purge_by_section_then_all(tmp_path, capsys):
    db = tmp_path / "redat.db"; _seed(db)
    assert mod.main(["--db", str(db), "purge", "--section", "noise"]) == 0
    assert "removed 2" in capsys.readouterr().out
    assert mod.main(["--db", str(db), "purge", "--all"]) == 0
    assert "removed 3" in capsys.readouterr().out
    c = SectionCache(3600, db_path=db); assert c.stats()["entries"] == 0; c.close()


def test_purge_expired_only(tmp_path, capsys, monkeypatch):
    now = [1e6]; monkeypatch.setattr(m.time, "time", lambda: now[0])
    db = tmp_path / "redat.db"; _seed(db)
    now[0] += 6                                              # only air_quality (ttl 5) has expired
    assert mod.main(["--db", str(db), "purge", "--expired"]) == 0
    assert "removed 1" in capsys.readouterr().out
    c = SectionCache(3600, db_path=db); assert c.stats()["by_section"] == {"boris": 1, "noise": 2}; c.close()


def test_purge_needs_a_scope(tmp_path):
    db = tmp_path / "redat.db"; _seed(db)
    with pytest.raises(SystemExit):
        mod.main(["--db", str(db), "purge"])
