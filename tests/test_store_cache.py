"""redat/store/cache.py — persistent, bounded, per-section-TTL cache for section envelopes (+ small KV namespaces)."""
import pytest

import redat.store.cache as m
from redat.store.cache import SectionCache


def _env(status, key="noise", size=0):
    return {"key": key, "status": status, "data": {"pad": "x" * size}}


@pytest.fixture
def clock(monkeypatch):
    now = [1_000_000.0]
    monkeypatch.setattr(m.time, "time", lambda: now[0])
    return now


# --------------------------------------------------------------------------- key
def test_key_rounds_coordinates_to_4_places():
    c = SectionCache(60)
    assert c.key("noise", 51.38784, 7.00106, None, False) == c.key("noise", 51.38781, 7.00109, None, False)
    assert c.key("noise", 51.3878, 7.0011, None, False) != c.key("noise", 51.3878, 7.0011, None, True)
    assert c.key("boris", 51.3878, 7.0011, 400, False) != c.key("boris", 51.3878, 7.0011, 500, False)


def test_key_includes_the_section_cache_version():
    c = SectionCache(60)
    assert c.key("noise", 1, 2, None, False, version=1) != c.key("noise", 1, 2, None, False, version=2)
    assert c.key("noise", 1, 2, None, False) == c.key("noise", 1, 2, None, False, version=1)   # default version 1


# --------------------------------------------------------------------------- put/get semantics
def test_put_get_only_ok_and_empty():
    c = SectionCache(60)
    k = c.key("noise", 51.3878, 7.0011, None, False)
    c.put(k, _env("error")); assert c.get(k) is None
    c.put(k, _env("gated")); assert c.get(k) is None
    c.put(k, _env("empty")); assert c.get(k)["status"] == "empty"
    c.put(k, _env("ok")); assert c.get(k)["status"] == "ok"


def test_get_returns_copy_marked_cached_with_timestamp(clock):
    c = SectionCache(60)
    k = c.key("noise", 1, 2, None, False)
    env = _env("ok"); c.put(k, env)
    got = c.get(k)
    assert got["cached"] is True and "cached" not in env
    assert got["cached_at"] == "1970-01-12T13:46:40Z"      # epoch 1_000_000 as ISO-8601 UTC
    got["data"]["pad"] = "mutated"
    assert c.get(k)["data"]["pad"] == ""                    # stored copy untouched


def test_expiry_uses_wall_clock(clock):
    c = SectionCache(10)
    k = c.key("noise", 1, 2, None, False); c.put(k, _env("ok"))
    clock[0] += 9; assert c.get(k) is not None
    clock[0] += 2; assert c.get(k) is None


def test_ttl_zero_disables():
    c = SectionCache(0)
    k = c.key("noise", 1, 2, None, False); c.put(k, _env("ok"))
    assert c.get(k) is None


# --------------------------------------------------------------------------- per-section TTL
def test_per_section_ttl_override(clock):
    c = SectionCache(3600, ttl_overrides={"air_quality": 60})
    ka = c.key("air_quality", 1, 2, None, False); kn = c.key("noise", 1, 2, None, False)
    c.put(ka, _env("ok", key="air_quality")); c.put(kn, _env("ok"))
    clock[0] += 61
    assert c.get(ka) is None and c.get(kn) is not None
    assert c.ttl_for("air_quality") == 60 and c.ttl_for("noise") == 3600


def test_section_ttl_zero_disables_only_that_section():
    c = SectionCache(3600, ttl_overrides={"air_quality": 0})
    ka = c.key("air_quality", 1, 2, None, False); kn = c.key("noise", 1, 2, None, False)
    c.put(ka, _env("ok", key="air_quality")); c.put(kn, _env("ok"))
    assert c.get(ka) is None and c.get(kn) is not None


# --------------------------------------------------------------------------- persistence
def test_persists_across_instances(tmp_path, clock):
    db = tmp_path / "redat.db"
    a = SectionCache(60, db_path=db)
    k = a.key("noise", 1, 2, None, False); a.put(k, _env("ok"))
    b = SectionCache(60, db_path=db)                 # "the container restarted"
    assert b.get(k)["status"] == "ok"
    clock[0] += 61
    assert SectionCache(60, db_path=db).get(k) is None   # expiry is absolute, not relative to process start


def test_shares_the_runs_database_file(tmp_path):
    from redat.store.runs import RunStore
    db = tmp_path / "redat.db"
    RunStore(db).init()
    c = SectionCache(60, db_path=db)
    k = c.key("noise", 1, 2, None, False); c.put(k, _env("ok"))
    assert c.get(k) is not None
    assert RunStore(db).get("nope") is None          # both tables live side by side


# --------------------------------------------------------------------------- bounds
def test_max_entries_evicts_least_recently_used(clock):
    c = SectionCache(3600, max_entries=2)
    ka, kb, kc = (c.key("noise", i, i, None, False) for i in (1, 2, 3))
    c.put(ka, _env("ok")); clock[0] += 1
    c.put(kb, _env("ok")); clock[0] += 1
    assert c.get(ka) is not None                     # touch a -> b is now the least recently used
    clock[0] += 1
    c.put(kc, _env("ok"))
    assert c.get(kb) is None and c.get(ka) is not None and c.get(kc) is not None
    assert c.stats()["entries"] == 2


def test_max_bytes_evicts_oldest_first(clock):
    c = SectionCache(3600, max_bytes=2_500)
    ks = [c.key("noise", i, i, None, False) for i in range(4)]
    for k in ks:
        c.put(k, _env("ok", size=900)); clock[0] += 1   # ~1 KB each -> only the two newest fit
    assert c.stats()["bytes"] <= 2_500
    assert c.get(ks[0]) is None and c.get(ks[1]) is None
    assert c.get(ks[2]) is not None and c.get(ks[3]) is not None


def test_expired_entries_are_evicted_before_live_ones(clock):
    c = SectionCache(3600, ttl_overrides={"air_quality": 5}, max_entries=2)
    ka = c.key("air_quality", 1, 1, None, False); kn = c.key("noise", 2, 2, None, False); k3 = c.key("noise", 3, 3, None, False)
    c.put(ka, _env("ok", key="air_quality")); clock[0] += 1
    c.put(kn, _env("ok")); clock[0] += 10             # air_quality is expired now, noise is the LRU
    c.put(k3, _env("ok"))
    assert c.get(kn) is not None and c.get(k3) is not None


# --------------------------------------------------------------------------- maintenance & introspection
def test_purge_expired_and_stats(clock):
    c = SectionCache(3600, ttl_overrides={"air_quality": 5})
    c.put(c.key("air_quality", 1, 1, None, False), _env("ok", key="air_quality", size=100))
    c.put(c.key("noise", 2, 2, None, False), _env("ok", size=100))
    c.put(c.key("noise", 3, 3, None, False), _env("ok", size=100))
    s = c.stats()
    assert s["entries"] == 3 and s["bytes"] > 300 and s["by_section"] == {"air_quality": 1, "noise": 2}
    clock[0] += 6
    assert c.purge_expired() == 1
    assert c.stats()["entries"] == 2 and c.stats()["by_section"] == {"noise": 2}


def test_invalidate_one_section_or_everything():
    c = SectionCache(3600)
    c.put(c.key("noise", 1, 1, None, False), _env("ok"))
    c.put(c.key("boris", 1, 1, None, False), _env("ok", key="boris"))
    assert c.invalidate("noise") == 1
    assert c.stats()["by_section"] == {"boris": 1}
    assert c.invalidate() == 1 and c.stats()["entries"] == 0


# --------------------------------------------------------------------------- KV namespaces (geocode / autocomplete)
MISS = object()


def test_kv_put_get_with_ttl_and_none_values(clock):
    c = SectionCache(3600)
    c.kv_put("geocode", "essen hbf", {"lat": 51.45, "lon": 7.01}, ttl_s=100)
    c.kv_put("geocode", "asdfgh", None, ttl_s=10)          # negative result is cacheable too
    assert c.kv_get("geocode", "essen hbf", MISS) == {"lat": 51.45, "lon": 7.01}
    assert c.kv_get("geocode", "asdfgh", MISS) is None
    assert c.kv_get("geocode", "unknown", MISS) is MISS
    assert c.kv_get("autocomplete", "essen hbf", MISS) is MISS   # namespaces do not leak into each other
    clock[0] += 11
    assert c.kv_get("geocode", "asdfgh", MISS) is MISS and c.kv_get("geocode", "essen hbf", MISS) is not MISS
    assert c.stats()["by_namespace"] == {"geocode": 1}


def test_kv_entries_count_against_the_same_bounds(clock):
    c = SectionCache(3600, max_entries=1)
    c.kv_put("geocode", "a", 1, ttl_s=100); clock[0] += 1
    c.put(c.key("noise", 1, 1, None, False), _env("ok"))
    assert c.kv_get("geocode", "a", MISS) is MISS and c.stats()["entries"] == 1
