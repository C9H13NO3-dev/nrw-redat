import pytest

from redat.sources import boris


def test_data_dir_follows_settings():
    from redat.settings import get_settings
    assert boris.data_dir() == get_settings().source_dir / "boris"


def test_find_shapefile_none_when_missing():
    assert boris._find_shapefile(2025) is None


def test_lookup_raises_missing_data_with_path():
    with pytest.raises(boris.MissingData, match="BORIS-Daten fehlen unter .*source/boris"):
        boris.lookup_bodenrichtwert(51.45, 7.01)


def test_get_boris_nrw_maps_result(monkeypatch):
    res = boris.BorisResult(bodenrichtwert=410.0, stichtag="2025-01-01", nutzung="W", zone_name="Z1", gemeinde="Essen", year=2025, raw={"a": 1})
    monkeypatch.setattr(boris, "_lookup_in_subprocess", lambda lat, lon: res)
    assert boris.get_boris_nrw(51.45, 7.01) == {"bodenrichtwert": 410.0, "date": "2025-01-01", "zone": "Z1", "nutzung": "W", "gemeinde": "Essen", "raw": {"a": 1}}


def test_get_boris_nrw_no_data(monkeypatch):
    monkeypatch.setattr(boris, "_lookup_in_subprocess", lambda lat, lon: None)
    assert boris.get_boris_nrw(51.45, 7.01) == {"error": "No BORIS data for this location"}


def test_get_boris_nrw_error_passthrough(monkeypatch):
    monkeypatch.setattr(boris, "_lookup_in_subprocess", lambda lat, lon: {"__error__": "BORIS-Daten fehlen unter /x"})
    assert boris.get_boris_nrw(51.45, 7.01) == {"error": "BORIS-Daten fehlen unter /x"}


def test_get_boris_nrw_timeout(monkeypatch):
    monkeypatch.setattr(boris, "_lookup_in_subprocess", lambda lat, lon: boris._TIMEOUT)
    assert boris.get_boris_nrw(51.45, 7.01) == {"error": "BORIS timeout"}


def test_subprocess_wrapper_returns_missing_data_error_for_real():
    # end-to-end through the real subprocess against the (empty) tmp source dir
    out = boris.get_boris_nrw(51.45, 7.01)
    assert out["error"].startswith("BORIS-Daten fehlen unter")
