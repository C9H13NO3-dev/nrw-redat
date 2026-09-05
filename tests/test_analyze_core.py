import json
import pytest
from fastapi import HTTPException

import redat.core.analyze as A
from redat.core.geocoding import GeocodeResult, GeocoderUnavailable
from redat.settings import Destination
from redat.store.cache import SectionCache


def test_parse_destinations_none_is_empty():
    assert A.parse_destinations(None) == ()
    assert A.parse_destinations("") == ()


def test_parse_destinations_ok():
    raw = json.dumps([{"name": "Arbeit", "lat": 51.45, "lon": 7.01, "group": "work"},
                      {"name": "Oma", "lat": 51.5, "lon": 7.2}])
    ds = A.parse_destinations(raw)
    assert ds == (Destination("Arbeit", 51.45, 7.01, "work"), Destination("Oma", 51.5, 7.2, "custom"))


@pytest.mark.parametrize("raw", [
    "not json", "{}", json.dumps([{"name": "x"}]), json.dumps([{"name": "", "lat": 1, "lon": 2}]),
    json.dumps([{"name": "x", "lat": "a", "lon": 2}]), json.dumps([{"name": "x", "lat": 91, "lon": 2}]),
    json.dumps([{"name": "x", "lat": 1, "lon": 2}] * 11),
])
def test_parse_destinations_rejects(raw):
    with pytest.raises(ValueError):
        A.parse_destinations(raw)


def test_run_all_uses_pool_and_cache(monkeypatch):
    calls = []

    def fake_run_section(key, ctx, precision=None, force=False):
        calls.append(key)
        return {"key": key, "tier": "area", "status": "ok" if key != "boris" else "error",
                "data": {}, "message": None, "source": "x", "took_ms": 1}
    monkeypatch.setattr(A, "run_section", fake_run_section)
    cache = SectionCache(60)
    out = A.run_all(lat=51.45, lon=7.01, precision="house", plot_size_m2=None, force=False,
                    destinations=(), cache=cache)
    assert set(out) == set(A.SECTIONS) and sorted(calls) == sorted(A.SECTIONS)
    assert "cached" not in out["noise"]
    calls.clear()
    out2 = A.run_all(lat=51.45, lon=7.01, precision="house", plot_size_m2=None, force=False,
                     destinations=(), cache=cache)
    assert calls == ["boris"]  # only the error result was not cached
    assert out2["noise"]["cached"] is True


def test_run_all_passes_ctx(monkeypatch):
    seen = {}

    def fake_run_section(key, ctx, precision=None, force=False):
        seen[key] = (ctx, precision, force)
        return {"key": key, "status": "empty", "data": None}
    monkeypatch.setattr(A, "run_section", fake_run_section)
    d = (Destination("Arbeit", 51.45, 7.01, "work"),)
    A.run_all(lat=1.0, lon=2.0, precision="street", plot_size_m2=300, force=True, destinations=d,
              cache=SectionCache(0))
    ctx, precision, force = seen["commute"]
    assert (ctx.lat, ctx.lon, ctx.plot_size_m2, ctx.destinations) == (1.0, 2.0, 300, d)
    assert precision == "street" and force is True


def test_geocode_or_raise(monkeypatch):
    monkeypatch.setattr(A, "geocode_with_precision", lambda a: None)
    with pytest.raises(HTTPException) as e:
        A.geocode_or_raise("nirgendwo")
    assert e.value.status_code == 422

    def boom(a): raise GeocoderUnavailable("both down")
    monkeypatch.setattr(A, "geocode_with_precision", boom)
    with pytest.raises(HTTPException) as e:
        A.geocode_or_raise("x")
    assert e.value.status_code == 502

    ok = GeocodeResult(formatted_address="F", latitude=1.0, longitude=2.0, precision="house")
    monkeypatch.setattr(A, "geocode_with_precision", lambda a: ok)
    assert A.geocode_or_raise("x") is ok


def test_payload_run_roundtrip():
    payload = {"address": "A", "geocode": {"formatted_address": "F", "latitude": 1.0, "longitude": 2.0,
               "precision": "house"}, "plot_size_m2": 400, "living_space_m2": None, "sections": {"noise": {"status": "ok"}}}
    run = A.payload_to_run(payload)
    assert run == {"address": "A", "formatted_address": "F", "latitude": 1.0, "longitude": 2.0,
                   "precision": "house", "plot_size_m2": 400, "living_space_m2": None,
                   "sections": {"noise": {"status": "ok"}}}
    back = A.run_to_payload({**run, "id": "abc", "created_at": "2026-09-05T10:00:00Z"})
    assert back == payload


# --------------------------------------------------------------------------- geocode / autocomplete caching
def test_geocode_or_raise_caches_hits_and_misses_but_not_outages(monkeypatch):
    calls = []
    hit = GeocodeResult(latitude=51.45, longitude=7.01, precision="building", formatted_address="Kettwiger Str. 1, Essen")

    def fake(address):
        calls.append(address)
        if address == "down":
            raise GeocoderUnavailable("x")
        return hit if address.startswith("Kettwiger") else None

    monkeypatch.setattr(A, "geocode_with_precision", fake)
    cache = SectionCache(3600)
    assert A.geocode_or_raise("Kettwiger Str. 1, Essen", cache=cache) == hit
    assert A.geocode_or_raise("  kettwiger  str. 1,  ESSEN ", cache=cache) == hit    # normalised key: case + whitespace
    assert calls == ["Kettwiger Str. 1, Essen"]
    with pytest.raises(HTTPException) as e1:
        A.geocode_or_raise("nirgendwo", cache=cache)
    with pytest.raises(HTTPException) as e2:
        A.geocode_or_raise("nirgendwo", cache=cache)
    assert e1.value.status_code == e2.value.status_code == 422 and calls.count("nirgendwo") == 1   # negative result cached
    for _ in range(2):
        with pytest.raises(HTTPException) as e3:
            A.geocode_or_raise("down", cache=cache)
        assert e3.value.status_code == 502
    assert calls.count("down") == 2                      # outages are never cached
    assert cache.stats()["by_namespace"] == {"geocode": 2}


def test_geocode_cache_ttls(monkeypatch):
    import redat.store.cache as m
    now = [1e6]; monkeypatch.setattr(m.time, "time", lambda: now[0])
    calls = []
    hit = GeocodeResult(latitude=51.45, longitude=7.01, precision="building", formatted_address="x")
    monkeypatch.setattr(A, "geocode_with_precision", lambda a: (calls.append(a), hit if a == "hit" else None)[1])
    cache = SectionCache(3600)
    A.geocode_or_raise("hit", cache=cache)
    with pytest.raises(HTTPException):
        A.geocode_or_raise("miss", cache=cache)
    now[0] += A.GEOCODE_MISS_TTL_S + 1
    with pytest.raises(HTTPException):
        A.geocode_or_raise("miss", cache=cache)            # negative entries live only GEOCODE_MISS_TTL_S
    A.geocode_or_raise("hit", cache=cache)
    assert calls == ["hit", "miss", "miss"]
    now[0] += A.GEOCODE_TTL_S
    A.geocode_or_raise("hit", cache=cache)
    assert calls == ["hit", "miss", "miss", "hit"]


def test_autocomplete_cached(monkeypatch):
    calls = []
    monkeypatch.setattr(A, "autocomplete_address", lambda text, limit=8: (calls.append((text, limit)), [{"formatted": text}])[1])
    cache = SectionCache(3600)
    assert A.autocomplete_cached("Kettw", 8, cache=cache) == [{"formatted": "Kettw"}]
    assert A.autocomplete_cached("kettw ", 8, cache=cache) == [{"formatted": "Kettw"}]
    A.autocomplete_cached("Kettw", 5, cache=cache)
    assert calls == [("Kettw", 8), ("Kettw", 5)]
    assert A.autocomplete_cached("", 8, cache=cache) == [] and len(calls) == 2   # empty input never hits the API
