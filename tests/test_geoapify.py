import httpx
import pytest

from redat.sources import geoapify as g


class _Resp:
    def __init__(self, payload, status=200):
        self._p, self.status_code = payload, status
    def json(self): return self._p
    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("boom", request=None, response=None)


def _client(monkeypatch, capture: dict, payload):
    class FakeClient:
        def __init__(self, *a, **kw):
            capture["headers"] = kw.get("headers")
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get(self, url, params=None, **kw):
            capture["url"], capture["params"] = url, params
            return _Resp(payload)
    monkeypatch.setattr(g.httpx, "Client", FakeClient)


def test_api_key_comes_from_settings_at_call_time(monkeypatch):
    cap = {}
    _client(monkeypatch, cap, {"features": []})
    assert g.geocode_address("Nirgendwo 1") is None
    assert cap["params"]["apiKey"] == "test-key"
    assert cap["headers"]["User-Agent"].startswith("nrw-redat/1.0 (+http://192.168.188.64:8200)")


def test_geocode_address_parses_feature(monkeypatch):
    feat = {"geometry": {"coordinates": [7.01, 51.45]},
            "properties": {"formatted": "Teststr. 1, 45127 Essen", "result_type": "building", "housenumber": "1",
                           "rank": {"confidence": 0.98}, "suburb": "Stadtkern"}}
    _client(monkeypatch, {}, {"features": [feat]})
    r = g.geocode_address("Teststr. 1, Essen")
    assert (r["lat"], r["lon"], r["precision"], r["housenumber"]) == (51.45, 7.01, "building", "1")


def test_autocomplete_maps_results_and_bias(monkeypatch):
    cap = {}
    _client(monkeypatch, cap, {"results": [{"formatted": "Kortumstraße 1, Bochum", "lat": 51.48, "lon": 7.22}]})
    out = g.autocomplete_address("Kortum", limit=3, bias_lat=51.5, bias_lon=7.1)
    assert cap["params"]["limit"] == 3 and cap["params"]["bias"] == "proximity:7.1,51.5"
    assert out and out[0]["lat"] == 51.48


def test_autocomplete_blank_is_empty():
    assert g.autocomplete_address("   ") == []


def test_geocode_address_reraises_transport_errors(monkeypatch):
    class FakeClient:
        def __init__(self, *a, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get(self, *a, **kw): raise httpx.ConnectError("no route")
    monkeypatch.setattr(g.httpx, "Client", FakeClient)
    with pytest.raises(httpx.HTTPError):
        g.geocode_address("X")
