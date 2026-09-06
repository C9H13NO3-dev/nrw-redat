import pytest

from redat.sources import bodenbewegung as bb
from pyproj import Transformer

T = Transformer.from_crs("EPSG:4326", "EPSG:3035", always_xy=True)
X, Y = T.transform(7.0050, 51.4300)
CX, CY = int(X // 100) * 100 + 50, int(Y // 100) * 100 + 50


def grid(centre=-6.0, ring=-1.0, far=3.0):
    cells = {f"{CX + dx * 100}_{CY + dy * 100}": (centre if dx == dy == 0 else ring) for dx in (-1, 0, 1) for dy in (-1, 0, 1)}
    cells[f"{CX + 400}_{CY}"] = far
    return {"years": "2019-2023", "cell_m": 100, "cells": cells}


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
    monkeypatch.setattr(bb, "_load", lambda: {"years": "x", "cell_m": 100, "cells": {}})
    assert bb.lookup(51.4300, 7.0050) is None
    monkeypatch.setattr(bb, "_load", lambda: None)
    assert bb.lookup(51.4300, 7.0050) is None
