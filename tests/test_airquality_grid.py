import json

import pytest

from redat.sources import airquality_grid as G


@pytest.fixture
def tiny_grid(tmp_path, monkeypatch):
    # 2x2 window whose top-left corner is the EPSG:3035 position of (lon 7.0, lat 51.45)
    # snapped to the km grid; cell (0,0) = NW, (1,1) = SE.
    x0, y0 = G._to_3035(7.0, 51.45)
    x0, y0 = (x0 // 1000) * 1000, (y0 // 1000 + 1) * 1000
    data = {
        "source": "test", "year": 2023, "crs": "EPSG:3035", "cell_m": 1000,
        "x0": x0, "y0": y0, "ncols": 2, "nrows": 2,
        "layers": {"no2": [[20.0, 21.0], [22.0, None]], "pm25": [[9.0, 9.5], [10.0, 10.5]],
                   "pm10": [[15.0, 15.5], [16.0, 16.5]], "o3_peak": [[85.0, 86.0], [87.0, 88.0]]},
    }
    p = tmp_path / "grid.json"
    p.write_text(json.dumps(data))
    monkeypatch.setattr(G, "GRID_PATH", p)
    G._load.cache_clear()
    yield data
    G._load.cache_clear()


def test_lookup_returns_cell_values_with_reference_limits(tiny_grid):
    r = G.lookup(51.45, 7.0)
    assert r["year"] == 2023 and r["resolution_km"] == 1 and r["source"] == "test"
    assert r["values"]["NO2"] == {"value": 20.0, "unit": "µg/m³", "who": 10, "eu2030": 20}
    assert r["values"]["PM2.5"] == {"value": 9.0, "unit": "µg/m³", "who": 5, "eu2030": 10}
    assert r["values"]["PM10"] == {"value": 15.0, "unit": "µg/m³", "who": 15, "eu2030": 20}
    assert r["values"]["O3"] == {"value": 85.0, "unit": "µg/m³", "who": 60, "eu2030": None}


def test_lookup_outside_window_is_none(tiny_grid):
    assert G.lookup(52.5, 13.4) is None  # Berlin


def test_lookup_skips_nodata_cells(tiny_grid):
    # SE cell: NO2 is None there, the other layers are present.
    x, y = tiny_grid["x0"] + 1500, tiny_grid["y0"] - 1500
    lon, lat = G._from_3035(x, y)
    r = G.lookup(lat, lon)
    assert "NO2" not in r["values"] and r["values"]["PM2.5"]["value"] == 10.5


def test_lookup_all_nodata_is_none(tiny_grid):
    data = dict(tiny_grid)
    data["layers"] = {k: [[None, None], [None, None]] for k in tiny_grid["layers"]}
    G.GRID_PATH.write_text(json.dumps(data))
    G._load.cache_clear()
    assert G.lookup(51.45, 7.0) is None


def test_missing_grid_file_is_none(tmp_path, monkeypatch):
    monkeypatch.setattr(G, "GRID_PATH", tmp_path / "nope.json")
    G._load.cache_clear()
    assert G.lookup(51.45, 7.0) is None
    G._load.cache_clear()


def test_real_grid_covers_essen_and_bochum():
    G._load.cache_clear()
    for lat, lon in ((51.4378, 7.0053), (51.4818, 7.2162)):
        r = G.lookup(lat, lon)
        assert r and 5 < r["values"]["NO2"]["value"] < 40 and 5 < r["values"]["PM2.5"]["value"] < 15
