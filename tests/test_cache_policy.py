"""Per-card cache policy: registry defaults -> settings.yaml `cache_ttls` -> global `cache_ttl_s`; the factory wires it."""
import dataclasses

import pytest

import redat.core.analyze as A
import redat.core.envelope as E
from redat.core import sections as S
from redat import settings as st


def test_registry_declares_volatility_only_for_live_cards():
    assert S.SECTIONS["air_quality"].cache_ttl_s == 3600          # live sensor readings
    assert S.SECTIONS["oepnv"].cache_ttl_s == 7 * 86400           # timetable, normalised to "next Tuesday 08:00"
    assert S.SECTIONS["noise"].cache_ttl_s is None                 # static geodata -> global default
    for sec in S.SECTIONS.values():
        assert isinstance(sec.cache_version, int) and sec.cache_version >= 1


def test_ttl_resolution_order(monkeypatch, tmp_path):
    assert E.cache_ttl_for(S.SECTIONS["noise"]) == st.get_settings().cache_ttl_s
    assert E.cache_ttl_for(S.SECTIONS["air_quality"]) == 3600
    y = tmp_path / "s.yaml"; y.write_text("cache_ttls: {air_quality: 10, noise: 20}\n")
    monkeypatch.setattr(st, "_cached", st.load_settings(yaml_path=y))
    assert E.cache_ttl_for(S.SECTIONS["air_quality"]) == 10 and E.cache_ttl_for(S.SECTIONS["noise"]) == 20


def test_build_cache_wires_settings(monkeypatch, tmp_path):
    y = tmp_path / "s.yaml"; y.write_text("cache_ttls: {air_quality: 10}\ncache_max_entries: 7\ncache_max_bytes: 4096\n")
    monkeypatch.setattr(st, "_cached", st.load_settings(yaml_path=y))
    cfg = st.get_settings()
    c = A.build_cache(cfg)
    assert c.db_path == cfg.db_path and c.max_entries == 7 and c.max_bytes == 4096
    assert c.ttl_for("air_quality") == 10 and c.ttl_for("oepnv") == 7 * 86400 and c.ttl_for("noise") == cfg.cache_ttl_s
    c.close()


def _fake_env(key, status="ok"):
    return {"key": key, "tier": "area", "status": status, "data": {}, "message": None, "source": "x", "took_ms": 1}


def test_cached_section_key_carries_the_section_version(monkeypatch):
    calls = []
    monkeypatch.setattr(A, "run_section", lambda key, ctx, precision=None, force=False: (calls.append(key), _fake_env(key))[1])
    cache = A.build_cache(st.get_settings())
    ctx = S.Ctx(lat=51.45, lon=7.01)
    A.cached_section("noise", ctx, precision="building", force=False, cache=cache)
    assert A.cached_section("noise", ctx, precision="building", force=False, cache=cache)["cached"] is True
    monkeypatch.setitem(S.SECTIONS, "noise", dataclasses.replace(S.SECTIONS["noise"], cache_version=2))   # "card output changed"
    out = A.cached_section("noise", ctx, precision="building", force=False, cache=cache)
    assert "cached" not in out and calls == ["noise", "noise"]
    cache.close()


def test_cached_section_fresh_bypasses_the_read_but_still_writes(monkeypatch):
    calls = []
    monkeypatch.setattr(A, "run_section", lambda key, ctx, precision=None, force=False: (calls.append(key), _fake_env(key))[1])
    cache = A.build_cache(st.get_settings())
    ctx = S.Ctx(lat=51.45, lon=7.01)
    A.cached_section("noise", ctx, precision="building", force=False, cache=cache)
    out = A.cached_section("noise", ctx, precision="building", force=False, cache=cache, fresh=True)
    assert "cached" not in out and calls == ["noise", "noise"]
    assert A.cached_section("noise", ctx, precision="building", force=False, cache=cache)["cached"] is True
    assert calls == ["noise", "noise"]                     # the fresh result replaced the cached one
    cache.close()
