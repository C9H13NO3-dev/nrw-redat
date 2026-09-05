from unittest.mock import patch

import pytest

from redat.core.geocoding import GeocodeResult, GeocoderUnavailable, geocode_with_precision, parse_coordinates


@pytest.mark.parametrize("text,expected", [
    ("51.45, 7.01", (51.45, 7.01)), ("  51.4501 ,7.0123  ", (51.4501, 7.0123)), ("-33.9,151.2", (-33.9, 151.2)), ("51,7", (51.0, 7.0)),
])
def test_parse_coordinates_accepts_lat_lon(text, expected):
    assert parse_coordinates(text) == expected


@pytest.mark.parametrize("text", ["Rüttenscheider Str. 100, 45131 Essen", "45131 Essen", "51.45", "91.0, 7.0", "51.0, 181.0", ""])
def test_parse_coordinates_rejects_non_coordinates(text):
    assert parse_coordinates(text) is None


def test_coordinates_short_circuit_geocoders():
    with patch("redat.core.geocoding.geocode_address", side_effect=AssertionError("must not geocode")), \
         patch("redat.core.geocoding._nominatim", side_effect=AssertionError("must not geocode")):
        r = geocode_with_precision("51.45, 7.01")
    assert r == GeocodeResult(51.45, 7.01, "coordinates", "51.450000, 7.010000")


def test_geoapify_hit():
    geo = {"lat": 51.5, "lon": 7.1, "precision": "building", "address": "Teststr. 1, Essen"}
    with patch("redat.core.geocoding.geocode_address", return_value=geo), \
         patch("redat.core.geocoding._nominatim", side_effect=AssertionError("no fallback")):
        assert geocode_with_precision("Teststr. 1, Essen") == GeocodeResult(51.5, 7.1, "building", "Teststr. 1, Essen")


def test_nominatim_fallback_has_no_precision():
    with patch("redat.core.geocoding.geocode_address", return_value=None), \
         patch("redat.core.geocoding._nominatim", return_value=(51.6, 7.2, "Fallbackstr., Bochum")):
        r = geocode_with_precision("Fallbackstr., Bochum")
    assert (r.latitude, r.longitude, r.precision, r.formatted_address) == (51.6, 7.2, None, "Fallbackstr., Bochum")


def test_both_miss_returns_none():
    with patch("redat.core.geocoding.geocode_address", return_value=None), \
         patch("redat.core.geocoding._nominatim", return_value=None):
        assert geocode_with_precision("nirgendwo") is None


def test_geoapify_error_then_nominatim_hit_is_a_hit():
    with patch("redat.core.geocoding.geocode_address", side_effect=RuntimeError("geoapify down")), \
         patch("redat.core.geocoding._nominatim", return_value=(51.6, 7.2, "X")):
        assert geocode_with_precision("X").precision is None


def test_both_error_raises_unavailable():
    with patch("redat.core.geocoding.geocode_address", side_effect=RuntimeError("down")), \
         patch("redat.core.geocoding._nominatim", side_effect=RuntimeError("down too")):
        with pytest.raises(GeocoderUnavailable):
            geocode_with_precision("X")


def test_nominatim_request_shape(monkeypatch):
    from redat.core import geocoding as gc
    cap = {}
    class R:
        def raise_for_status(self): pass
        def json(self): return [{"lat": "51.6", "lon": "7.2", "display_name": "Fallbackstr., Bochum"}]
    def fake_get(url, params=None, headers=None, timeout=None):
        cap.update(url=url, params=params, headers=headers)
        return R()
    monkeypatch.setattr(gc.httpx, "get", fake_get)
    assert gc._nominatim("Fallbackstr., Bochum") == (51.6, 7.2, "Fallbackstr., Bochum")
    assert cap["url"] == "https://nominatim.openstreetmap.org/search"
    assert cap["params"] == {"q": "Fallbackstr., Bochum", "format": "json", "addressdetails": 1, "limit": 1, "countrycodes": "de"}
    assert cap["headers"]["User-Agent"].startswith("nrw-redat/")
