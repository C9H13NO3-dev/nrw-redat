import numpy as np
import pytest

from redat.sources import bodenbewegung as bb
from pyproj import Transformer

T = Transformer.from_crs("EPSG:4326", "EPSG:3035", always_xy=True)
X, Y = T.transform(7.0050, 51.4300)
CELL = 100
X0 = int(X // CELL) * CELL - 6 * CELL          # raster west edge: 6 cells left of the point's cell
Y1 = int(Y // CELL) * CELL + 7 * CELL          # raster north edge: 6 cells above (row 6 = the point's row)


def grid(centre=-6.0, ring=-1.0, far=3.0):
    v = np.full((13, 13), bb.NODATA, dtype=np.int16)

    def put(dx, dy, val):
        v[6 - dy, 6 + dx] = int(round(val * 100))
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            put(dx, dy, centre if dx == dy == 0 else ring)
    put(4, 0, far)
    return {"v": v, "x0": X0, "y1": Y1, "cell_m": CELL, "years": "2019-2023", "scale": 100}


def empty_grid():
    return {"v": np.full((13, 13), bb.NODATA, dtype=np.int16), "x0": X0, "y1": Y1, "cell_m": CELL, "years": "x", "scale": 100}


def test_classes():
    assert bb.classify(-0.5) == ("stabil", "green") and bb.classify(3.0) == ("leichte Bewegung", "yellow")
    assert bb.classify(-7.0) == ("deutliche Bewegung", "orange") and bb.classify(12.0) == ("starke Bewegung", "red")


def test_lookup_reports_cell_neighbourhood_and_direction(monkeypatch):
    monkeypatch.setattr(bb, "_load", grid)
    d = bb.lookup(51.4300, 7.0050)
    assert d["mm_a"] == -6.0 and d["klasse"] == "deutliche Bewegung" and d["richtung"] == "Senkung"
    assert d["mean_3x3"] == pytest.approx(-1.56, abs=0.01) and d["min_500m"] == -6.0 and d["max_500m"] == 3.0
    assert d["years"] == "2019-2023" and d["cell_m"] == 100


def test_uplift_and_missing(monkeypatch):
    monkeypatch.setattr(bb, "_load", lambda: grid(centre=4.0))
    assert bb.lookup(51.4300, 7.0050)["richtung"] == "Hebung"
    monkeypatch.setattr(bb, "_load", empty_grid)
    assert bb.lookup(51.4300, 7.0050) is None
    monkeypatch.setattr(bb, "_load", lambda: None)
    assert bb.lookup(51.4300, 7.0050) is None


def test_point_outside_raster_is_none(monkeypatch):
    monkeypatch.setattr(bb, "_load", grid)
    assert bb.lookup(52.37, 4.90) is None


def test_real_raster_covers_essen_and_bonn():
    bb._load.cache_clear()
    try:
        essen, bonn = bb.lookup(51.4556, 7.0116), bb.lookup(50.7160, 7.0748)
        assert essen and essen["mm_a"] == -0.96 and essen["years"] == "2020-2024"
        assert bonn and -5 < bonn["mm_a"] < 5
    finally:
        bb._load.cache_clear()
