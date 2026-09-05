"""Noise card sampling: one GetMap tile per source × period, worst legend band within the window.

Tiles are synthetic 25×25 RGBA PNGs painted with the real legend colours captured
2026-09-04 from wms.nrw.de/umwelt/laerm GetLegendGraphic.
"""
import io

import pytest
from PIL import Image

from redat.sources import noise as ns

TRANSPARENT = (255, 255, 255, 0)
C50, C55, C60 = (184, 214, 209, 255), (226, 242, 191, 255), (243, 198, 131, 255)
C65, C70, C75 = (205, 70, 62, 255), (117, 8, 92, 255), (67, 10, 74, 255)


def tile(*patches, size=ns.TILE_PX):
    """PNG bytes of a transparent tile with `(x0, y0, x1, y1, rgba)` rectangles painted on it."""
    im = Image.new("RGBA", (size, size), TRANSPARENT)
    for x0, y0, x1, y1, rgba in patches:
        for x in range(x0, x1):
            for y in range(y0, y1):
                im.putpixel((x, y), rgba)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


# --- parse_tile -----------------------------------------------------------------

def test_parse_tile_all_transparent_is_none():
    assert ns.parse_tile(tile()) is None


def test_parse_tile_takes_worst_band_in_window():
    # centre pixel transparent (building footprint), a 65 patch and a 75 street band at the edge
    png = tile((2, 2, 8, 8, C65), (20, 0, 25, 25, C75))
    assert ns.parse_tile(png) == 75


def test_parse_tile_ignores_unknown_colours():
    # basemap-ish grey and the legend's decoration colours never count as a band
    png = tile((0, 0, 25, 25, (200, 200, 200, 255)), (3, 3, 4, 4, C55))
    assert ns.parse_tile(png) == 55


def test_parse_tile_tolerates_slight_colour_drift():
    assert ns.parse_tile(tile((0, 0, 2, 2, (207, 72, 60, 255)))) == 65


def test_parse_tile_night_band_50():
    assert ns.parse_tile(tile((0, 0, 1, 1, C50))) == 50


def test_parse_tile_non_png_raises():
    with pytest.raises(ValueError):
        ns.parse_tile(b"<ServiceExceptionReport>boom</ServiceExceptionReport>")


@pytest.mark.parametrize("db,period,label", [
    (65, "day", "ab 65 bis 69 dB(A)"), (75, "day", "ab 75 dB(A)"),
    (55, "night", "ab 55 bis 59 dB(A)"), (70, "night", "ab 70 dB(A)"),
])
def test_band_label(db, period, label):
    assert ns.band_label(db, period) == label


# --- get_noise_levels -------------------------------------------------------------

def _stub(monkeypatch, tiles_by_layer, default=None):
    """tiles_by_layer: {"STR_DEN": png, ...}; every other layer gets `default` (transparent tile)."""
    calls = []
    blank = tile()

    def fake_fetch(params):
        calls.append(params)
        return tiles_by_layer.get(params["LAYERS"], default or blank)
    monkeypatch.setattr(ns, "_fetch_png", fake_fetch)
    return calls


def test_get_noise_levels_neighbourhood_max_and_loudest_source(monkeypatch):
    # Werden case: centre pixel unrendered, ≥75 street band a few metres away; night 65; city rail 55 by day
    calls = _stub(monkeypatch, {
        "STR_DEN": tile((20, 0, 25, 25, C75)),
        "STR_NGT": tile((20, 0, 25, 25, C65)),
        "SCS_DEN": tile((0, 0, 3, 3, C55)),
    })
    r = ns.get_noise_levels(51.38784, 7.00106)
    assert r["day"] == {"db_min": 75, "label": "ab 75 dB(A)", "source": "str"}
    assert r["night"] == {"db_min": 65, "label": "ab 65 bis 69 dB(A)", "source": "str"}
    assert r["sources"]["str"] == {"day": 75, "night": 65}
    assert r["sources"]["scs"] == {"day": 55, "night": None}
    assert r["sources"]["flg"] == {"day": None, "night": None}
    assert r["below_threshold"] is False
    assert r["window_m"] == ns.WINDOW_M
    assert len(calls) == 10
    assert sorted(c["LAYERS"] for c in calls) == sorted(
        f"{s.upper()}_{p}" for s in ns.SOURCES for p in ("DEN", "NGT"))


def test_get_noise_levels_request_params(monkeypatch):
    calls = _stub(monkeypatch, {})
    ns.get_noise_levels(51.45, 7.01)
    p = next(c for c in calls if c["LAYERS"] == "STR_DEN")
    assert p["SERVICE"] == "WMS" and p["VERSION"] == "1.3.0" and p["REQUEST"] == "GetMap"
    assert p["CRS"] == "EPSG:25832" and p["FORMAT"] == "image/png" and p["TRANSPARENT"] == "TRUE"
    assert p["STYLES"] == ""  # mandatory — the server rejects a GetMap without it
    assert p["WIDTH"] == p["HEIGHT"] == ns.TILE_PX
    minx, miny, maxx, maxy = (float(v) for v in p["BBOX"].split(","))
    assert maxx - minx == pytest.approx(ns.WINDOW_M) and maxy - miny == pytest.approx(ns.WINDOW_M)
    assert 360_000 < minx < 380_000 and 5_700_000 < miny < 5_710_000  # Essen in UTM 32N


def test_get_noise_levels_all_transparent_is_below_threshold(monkeypatch):
    _stub(monkeypatch, {})
    r = ns.get_noise_levels(51.45, 7.01)
    assert r["day"] is None and r["night"] is None and r["below_threshold"] is True
    assert all(v == {"day": None, "night": None} for v in r["sources"].values())


def test_get_noise_levels_propagates_bad_tile(monkeypatch):
    _stub(monkeypatch, {"IND_NGT": b"garbage"})
    with pytest.raises(ValueError):
        ns.get_noise_levels(51.45, 7.01)
