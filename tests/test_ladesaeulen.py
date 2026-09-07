import pytest

from redat.sources import ladesaeulen as ls

F = ["lat", "lon", "betreiber", "schnell", "punkte", "kw", "adresse"]
ROWS = [
    [51.4300, 7.0110, "Fastned", 1, 4, 300.0, "A40, 45141 Essen"],                   # 416 m
    [51.4320, 7.0050, "E.ON", 0, 2, 22.0, "Rüttenscheider Str. 1, 45131 Essen"],    # 222 m
    [51.4380, 7.0050, "Stadtwerke", 0, 2, 11.0, "Weg 3, 45131 Essen"],               # 890 m
    [51.4420, 7.0050, "Fern", 0, 2, 11.0, "Fern 1"],                                  # 1334 m → outside 1 km
]
GRID = {"stand": "2026-09-01", "bbox": [5.753, 50.242, 9.589, 52.619], "fields": F, "rows": ROWS}


@pytest.fixture(autouse=True)
def grid(request, monkeypatch):
    if request.node.name != "test_real_grid_covers_essen_and_bonn":
        monkeypatch.setattr(ls, "_load", lambda: GRID)
        ls._lats.cache_clear()
    yield
    ls._lats.cache_clear()


def test_lookup_counts_and_nearest():
    d = ls.lookup(51.4300, 7.0050)
    assert d["radius_m"] == 1000 and d["stand"] == "2026-09-01"
    assert d["anzahl_500m"] == 2 and d["anzahl_1000m"] == 3 and d["ladepunkte_1000m"] == 8 and d["schnell_1000m"] == 1
    assert [n["betreiber"] for n in d["naechste"]] == ["E.ON", "Fastned", "Stadtwerke"]
    assert 200 < d["naechste"][0]["distance_m"] < 240 and d["naechste"][1]["schnell"] is True and d["naechste"][1]["kw"] == 300.0
    assert d["rating"] == "Ladepunkt in Gehweite" and d["rating_color"] == "green"


def test_rating_yellow_and_orange(monkeypatch):
    monkeypatch.setattr(ls, "_load", lambda: {**GRID, "rows": [r for r in ROWS if r[2] != "E.ON"]})
    ls._lats.cache_clear()
    assert ls.lookup(51.4300, 7.0050)["rating"] == "Ladepunkt im Umkreis"
    monkeypatch.setattr(ls, "_load", lambda: {**GRID, "rows": []})
    ls._lats.cache_clear()
    d = ls.lookup(51.4300, 7.0050)
    assert d["rating"] == "Kein öffentlicher Ladepunkt im Umkreis von 1 km" and d["rating_color"] == "orange" and d["naechste"] == []


def test_outside_window_and_missing_grid(monkeypatch):
    # Stub explicitly (rather than relying on the module-level `grid` autouse fixture) so this
    # test is self-contained and never falls through to the committed grid file / its lru_cache.
    monkeypatch.setattr(ls, "_load", lambda: GRID)  # bbox is NRW — excludes Amsterdam
    ls._lats.cache_clear()
    assert ls.lookup(52.37, 4.90) is None
    monkeypatch.setattr(ls, "_load", lambda: None)
    ls._lats.cache_clear()
    assert ls.lookup(51.43, 7.0) is None


def test_rows_must_be_sorted_by_latitude_for_the_band_search(monkeypatch):
    unsorted = {**GRID, "rows": list(reversed(ROWS))}
    monkeypatch.setattr(ls, "_load", lambda: unsorted)
    ls._lats.cache_clear()
    with pytest.raises(ValueError, match="sorted"):
        ls.lookup(51.4300, 7.0050)
    ls._lats.cache_clear()


def test_real_grid_covers_essen_and_bonn():
    ls._load.cache_clear(); ls._lats.cache_clear()
    try:
        for lat, lon in ((51.4300, 7.0050), (50.7160, 7.0748)):
            d = ls.lookup(lat, lon)
            assert d and d["anzahl_1000m"] >= 1
    finally:
        ls._load.cache_clear(); ls._lats.cache_clear()
