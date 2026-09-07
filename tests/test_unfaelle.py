import numpy as np
import pytest

from redat.sources import unfaelle

F = ["lat", "lon", "jahr", "kat", "typ", "licht", "rad", "pkw", "fuss", "krad", "gkfz"]
# Point 51.4300, 7.0050. 0.001° lat ≈ 111 m; 0.001° lon ≈ 69 m.
ROWS = [
    [51.4305, 7.0050, 2020, 3, 6, 0, 0, 1, 0, 0, 0],   #  56 m, Leichtverletzte, Längsverkehr, PKW
    [51.4310, 7.0050, 2021, 2, 4, 2, 0, 1, 1, 0, 0],   # 111 m, Schwerverletzte, Überschreiten, nachts, Fuß+PKW
    [51.4300, 7.0080, 2022, 3, 1, 0, 1, 0, 0, 0, 0],   # 208 m, Rad, Fahrunfall
    [51.4300, 7.0090, 2023, 1, 3, 1, 0, 1, 0, 0, 1],   # 277 m, Getötete, Einbiegen/Kreuzen, Gkfz
    [51.4340, 7.0050, 2024, 3, 6, 0, 0, 1, 0, 1, 0],   # 445 m → outside
]

YEARS = [2020, 2021, 2022, 2023, 2024, 2025]
BBOX = (5.753, 50.242, 9.589, 52.619)


def make_grid(rows, years=YEARS, bbox=BBOX) -> dict:
    arr = np.array(sorted(rows), dtype=np.float64).reshape(-1, len(F))   # sorted by lat (first column)
    return {"years": years, "bbox": bbox, "fields": F,
            "lat": arr[:, 0], "lon": arr[:, 1], "attrs": arr[:, 2:].astype(np.int16)}


GRID = make_grid(ROWS)


@pytest.fixture(autouse=True)
def grid(request, monkeypatch):
    if request.node.name != "test_real_grid_covers_essen_and_bonn":
        monkeypatch.setattr(unfaelle, "_load", lambda: GRID)


def test_lookup_counts():
    d = unfaelle.lookup(51.4300, 7.0050)
    assert d["radius_m"] == 300 and d["years"] == [2020, 2021, 2022, 2023, 2024, 2025] and d["total"] == 4
    assert d["per_year"] == {"2020": 1, "2021": 1, "2022": 1, "2023": 1, "2024": 0, "2025": 0}
    assert d["per_year_avg"] == 0.7
    assert d["by_severity"] == {"getoetete": 1, "schwerverletzte": 1, "leichtverletzte": 2}
    assert d["beteiligt"] == {"rad": 1, "fuss": 1, "pkw": 3, "krad": 0, "gkfz": 1}
    assert d["by_type"] == {"Fahrunfall": 1, "Einbiegen/Kreuzen": 1, "Überschreiten": 1, "Längsverkehr": 1}
    assert d["nachts"] == 1 and 50 < d["nearest_m"] < 60


def test_rating_bands(monkeypatch):
    d = unfaelle.lookup(51.4300, 7.0050)
    assert d["rating"] == "Viele Unfälle" and d["rating_color"] == "orange"      # 0.7/a is green, but a Getöteter lifts to orange
    no_fatal = make_grid([r for r in ROWS if r[3] != 1])
    monkeypatch.setattr(unfaelle, "_load", lambda: no_fatal)
    d = unfaelle.lookup(51.4300, 7.0050)
    assert d["rating"] == "Wenige Unfälle" and d["rating_color"] == "green"
    assert unfaelle._rate(4.0, 0) == ("Mäßig viele Unfälle", "yellow")
    assert unfaelle._rate(10.0, 0) == ("Viele Unfälle", "orange")
    assert unfaelle._rate(20.0, 0) == ("Unfallschwerpunkt", "red")


def test_outside_window_and_missing_grid(monkeypatch):
    d = unfaelle.lookup(52.37, 4.90)        # Amsterdam — outside NRW
    assert d is None
    monkeypatch.setattr(unfaelle, "_load", lambda: None)
    assert unfaelle.lookup(51.43, 7.0) is None


def test_zero_accidents_inside_window_is_data_not_empty(monkeypatch):
    monkeypatch.setattr(unfaelle, "_load", lambda: make_grid([]))
    d = unfaelle.lookup(51.4300, 7.0050)
    assert d["total"] == 0 and d["nearest_m"] is None and d["rating_color"] == "green"


def test_real_grid_covers_essen_and_bonn():
    unfaelle._load.cache_clear()
    try:
        for lat, lon in ((51.4300, 7.0050), (50.7160, 7.0748)):
            d = unfaelle.lookup(lat, lon)
            assert d and d["years"] == YEARS and d["total"] >= 0
    finally:
        unfaelle._load.cache_clear()
