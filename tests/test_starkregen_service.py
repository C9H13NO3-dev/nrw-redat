"""Starkregen (pluvial flood) service — hermetic: `_get_tile` is replaced with
synthetic PIL tiles, so no WMS call is made."""
import pytest
from PIL import Image

from redat.sources import starkregen as srg

WHITE = (255, 255, 255, 0)      # < 10 cm (transparent white)
BUILDING = (0, 0, 0, 0)         # building / no-data (transparent black)
C10 = (204, 236, 255, 255)
C30 = (153, 204, 255, 255)
C50 = (110, 153, 255, 255)
C100 = (61, 102, 255, 255)
V05 = (254, 204, 92, 255)       # velocity 0.5–1 m/s


def tile(pixels: list[tuple], size: int = 10) -> Image.Image:
    """A size×size RGBA tile filled row-major from `pixels`, WHITE for the rest."""
    img = Image.new("RGBA", (size, size), WHITE)
    img.putdata(pixels + [WHITE] * (size * size - len(pixels)))
    return img


def patch_tiles(monkeypatch, tiles: dict):
    calls = []

    def fake(layer, lat, lon, half_m, px):
        calls.append((layer, lat, lon, half_m, px))
        return tiles[layer]

    monkeypatch.setattr(srg, "_get_tile", fake)
    return calls


def test_count_classes_by_exact_colour():
    img = tile([C10] * 20 + [C30] * 5 + [BUILDING] * 25)  # 50 white remain
    counts, buildings, ignored = srg._count_classes(img, srg.DEPTH_CLASSES)
    assert buildings == 25 and ignored == 0
    assert counts == {"< 10 cm": 50, "10–30 cm": 20, "30–50 cm": 5}


def test_count_classes_ignores_unknown_colours():
    img = tile([(1, 2, 3, 255)] * 3)
    counts, buildings, ignored = srg._count_classes(img, srg.DEPTH_CLASSES)
    assert ignored == 3 and counts == {"< 10 cm": 97}


def test_scenario_summary_max_and_shares():
    img = tile([C10] * 20 + [C50] * 5 + [BUILDING] * 25)
    s = srg._summarize(img, None)
    assert s["max"] == {"label": "50–100 cm", "cm": 50}
    assert s["shares"] == {"< 10 cm": 0.667, "10–30 cm": 0.267, "50–100 cm": 0.067}
    assert s["wet_share"] == 0.333
    assert s["velocity_max"] is None


def test_max_class_needs_minimum_area():
    # 2 of 1024 open pixels at 50–100 cm is a gully, not the site's exposure
    img = tile([C50] * 2 + [C10] * 100, size=32)  # 1024 px, all open
    s = srg._summarize(img, None)
    assert s["max"] == {"label": "10–30 cm", "cm": 10}
    assert s["shares"]["50–100 cm"] == 0.002  # still listed
    # but 25 pixels (2.4 %) do count
    s = srg._summarize(tile([C50] * 25 + [C10] * 100, size=32), None)
    assert s["max"]["cm"] == 50


def test_max_class_is_cumulative():
    # 12 px at 1–2 m + 12 px at 50–100 cm: neither alone reaches 2 %, together they do
    s = srg._summarize(tile([C100] * 12 + [C50] * 12, size=32), None)
    assert s["max"]["cm"] == 50


def test_outside_nrw_is_none_without_fetching(monkeypatch):
    calls = patch_tiles(monkeypatch, {})
    assert srg.get_starkregen(52.52, 13.40) is None
    assert calls == []


def test_scenario_summary_with_velocity():
    s = srg._summarize(tile([C10] * 3), tile([V05] * 3 + [BUILDING]))
    assert s["velocity_max"] == {"label": "0,5–1 m/s", "mps": 0.5}


def test_all_building_scenario_is_none():
    assert srg._summarize(tile([BUILDING] * 100), None) is None


def test_get_starkregen_fetches_four_layers_and_rates(monkeypatch):
    calls = patch_tiles(monkeypatch, {
        "nw_tiefe_agw": tile([C30] * 10 + [BUILDING] * 20),
        "nw_tiefe_extrem": tile([C100] * 10 + [BUILDING] * 20),
        "nw_geschw_agw": tile([]),
        "nw_geschw_extrem": tile([V05] * 3),
    })
    r = srg.get_starkregen(51.44, 7.01)
    assert sorted(c[0] for c in calls) == ["nw_geschw_agw", "nw_geschw_extrem", "nw_tiefe_agw", "nw_tiefe_extrem"]
    assert all(c[1:] == (51.44, 7.01, 50, 100) for c in calls)
    assert r["radius_m"] == 50
    assert r["building_share"] == 0.2
    assert r["scenarios"]["agw"]["max"]["cm"] == 30
    assert r["scenarios"]["extrem"]["max"]["cm"] == 100
    assert r["scenarios"]["extrem"]["velocity_max"]["mps"] == 0.5
    assert (r["rating"], r["rating_color"]) == ("Hoch", "red")


@pytest.mark.parametrize("agw_cm,extrem_cm,expected", [
    (0, 0, ("Gering", "green")),
    (0, 10, ("Gering", "green")),
    (10, 10, ("Mäßig", "yellow")),
    (0, 30, ("Mäßig", "yellow")),
    (30, 30, ("Erhöht", "orange")),
    (0, 50, ("Erhöht", "orange")),
    (50, 50, ("Hoch", "red")),
    (10, 100, ("Hoch", "red")),
])
def test_rating_thresholds(agw_cm, extrem_cm, expected):
    assert srg._rate(agw_cm, extrem_cm) == expected


def test_rating_with_missing_scenario():
    assert srg._rate(None, 30) == ("Mäßig", "yellow")
    assert srg._rate(None, None) == ("unbekannt", "gray")


def test_all_building_everywhere_is_none(monkeypatch):
    patch_tiles(monkeypatch, {
        "nw_tiefe_agw": tile([BUILDING] * 100), "nw_tiefe_extrem": tile([BUILDING] * 100),
        "nw_geschw_agw": tile([BUILDING] * 100), "nw_geschw_extrem": tile([BUILDING] * 100),
    })
    assert srg.get_starkregen(51.44, 7.01) is None


def test_velocity_failure_does_not_blank_depth(monkeypatch):
    def fake(layer, lat, lon, half_m, px):
        if layer.startswith("nw_geschw"):
            raise RuntimeError("boom")
        return tile([C10] * 3)

    monkeypatch.setattr(srg, "_get_tile", fake)
    r = srg.get_starkregen(51.44, 7.01)
    assert r["scenarios"]["agw"]["max"]["cm"] == 10
    assert r["scenarios"]["agw"]["velocity_max"] is None
    assert set(r["errors"]) == {"nw_geschw_agw", "nw_geschw_extrem"}


def test_depth_failure_propagates(monkeypatch):
    def fake(layer, lat, lon, half_m, px):
        raise RuntimeError("wms down")

    monkeypatch.setattr(srg, "_get_tile", fake)
    with pytest.raises(RuntimeError, match="wms down"):
        srg.get_starkregen(51.44, 7.01)


def test_bbox_is_wms13_lat_lon_order():
    params = srg._getmap_params("nw_tiefe_agw", 51.0, 7.0, half_m=50, px=100)
    lat0, lon0, lat1, lon1 = (float(v) for v in params["BBOX"].split(","))
    assert lat0 < 51.0 < lat1 and lon0 < 7.0 < lon1
    assert abs((lat1 - lat0) * 111_320 - 100) < 0.5
    assert params["CRS"] == "EPSG:4326" and params["TRANSPARENT"] == "TRUE"
    assert params["WIDTH"] == params["HEIGHT"] == 100
