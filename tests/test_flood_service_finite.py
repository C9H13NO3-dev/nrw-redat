"""flood must never emit float('inf') — FastAPI's JSON encoder rejects it (500)."""
import json

import pytest

from redat.sources import flood


def _empty_data_dir(tmp_path, monkeypatch):
    d = tmp_path / "hwrm"
    d.mkdir()
    monkeypatch.setattr(flood, "data_dir", lambda: d)
    return d


def test_hit_without_data_has_none_distance(tmp_path, monkeypatch):
    _empty_data_dir(tmp_path, monkeypatch)
    hit = flood._hit_for_scenario(51.45, 7.01, "HQ100")
    assert hit.hit is False and hit.min_distance_m is None


def test_flood_risk_is_json_serializable_without_files(tmp_path, monkeypatch):
    _empty_data_dir(tmp_path, monkeypatch)
    result = flood.flood_risk(51.45, 7.01)
    text = json.dumps(result, allow_nan=False)
    assert result["zone"] is None and result["risk_level"] == "low"
    for sc in ("HQhaeufig", "HQ100", "HQextrem"):
        assert result["hits"][sc]["min_distance_m"] is None
    assert "Infinity" not in text


def test_flood_risk_missing_dir_raises_precise_error(tmp_path, monkeypatch):
    monkeypatch.setattr(flood, "data_dir", lambda: tmp_path / "nope")
    with pytest.raises(RuntimeError, match="Hochwasser-Daten fehlen unter .*nope"):
        flood.flood_risk(51.45, 7.01)


def test_scenario_paths_follow_settings():
    from redat.settings import get_settings
    assert flood.SCENARIOS()["HQ100"] == get_settings().source_dir / "flood" / "hwrm" / "HQ100.gpkg"
