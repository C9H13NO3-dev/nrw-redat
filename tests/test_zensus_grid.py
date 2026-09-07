"""Zensus 2022 100 m grid lookup — hermetic: `_load` is monkeypatched with a tiny
in-memory grid built around one Essen point."""
import numpy as np
import pytest

from redat.sources import zensus as zg

LAT, LON = 51.4378, 7.0053  # Essen-Rüttenscheid


def row(**vals) -> list:
    return [vals.get(f) for f in zg.FIELDS]


def grid_around(lat, lon, cells: dict) -> dict:
    """cells: {(dcol, drow): {field: value}} offsets in 100 m steps from the point's cell → the `_load()` shape."""
    cx, cy = zg._cell_centre(*zg._to_3035(lon, lat))
    items = sorted((zg.cell_key(cx + dc * 100, cy + dr * 100), row(**v)) for (dc, dr), v in cells.items())
    return {
        "year": 2022, "cell_m": 100, "fields": list(zg.FIELDS), "scales": zg.scales_for(zg.FIELDS),
        "keys": np.array([k for k, _ in items], dtype=np.int64),
        "values": zg.encode_values([r for _, r in items], zg.FIELDS),
    }


def test_fields_are_consistent():
    assert zg.FIELDS[:9] == list(zg.SCALARS)
    assert set(zg.POP_WEIGHTED) < set(zg.SCALARS)
    for keys in zg.GROUPS.values():
        assert all(k in zg.FIELDS for k, _ in keys)
    assert len(set(zg.FIELDS)) == len(zg.FIELDS)


def test_cell_centre_snaps_to_100m():
    assert zg._cell_centre(4110123.4, 3150299.9) == (4110150, 3150250)
    assert zg._cell_centre(4110150.0, 3150250.0) == (4110150, 3150250)


def test_lookup_cell_and_area(monkeypatch):
    g = grid_around(LAT, LON, {
        (0, 0): {"einwohner": 10, "alter": 40.0, "u18": 20.0, "eigentuemer": 50.0, "geb": 2,
                 "bj_vor1919": 1, "bj_1990_1999": 1, "hz_zentral": 2, "et_gas": 2, "gw_1": 2},
        (1, 0): {"einwohner": 30, "alter": 50.0, "u18": 10.0, "eigentuemer": 30.0, "leerstand": 4.0, "geb": 4,
                 "bj_2016plus": 4, "hz_fern": 4, "et_fern": 4, "gw_3_6": 4},
        (2, 2): {"einwohner": 5, "alter": 30.0},          # inside the 5×5 window
        (3, 0): {"einwohner": 999, "alter": 99.0},        # outside the window
    })
    monkeypatch.setattr(zg, "_load", lambda: g)
    r = zg.lookup(LAT, LON)
    assert r["year"] == 2022 and r["radius_m"] == 250 and r["area_cells"] == 3
    c = r["cell"]
    assert c["einwohner"] == 10 and c["alter"] == 40.0 and c["leerstand"] is None
    assert c["gebaeude"] == 2
    assert c["baujahr"] == {"vor 1919": 0.5, "1990–1999": 0.5}
    assert c["heizung"] == {"Zentralheizung": 1.0}
    assert c["gebaeudetyp"] == {"1 Wohnung": 1.0}
    a = r["area"]
    assert a["einwohner"] == 45
    assert a["alter"] == pytest.approx((10 * 40 + 30 * 50 + 5 * 30) / 45, abs=0.01)   # population-weighted
    assert a["u18"] == pytest.approx((10 * 20 + 30 * 10) / 40, abs=0.01)              # only cells with a value
    assert a["eigentuemer"] == 40.0                                                     # unweighted mean
    assert a["leerstand"] == 4.0
    assert a["miete_qm"] is None
    assert a["gebaeude"] == 6
    assert a["baujahr"] == {"vor 1919": 0.167, "1990–1999": 0.167, "2016 und später": 0.667}
    assert a["energietraeger"] == {"Gas": 0.333, "Fernwärme": 0.667}


def test_cell_missing_but_neighbours_present(monkeypatch):
    g = grid_around(LAT, LON, {(1, 1): {"einwohner": 7, "alter": 44.0}})
    monkeypatch.setattr(zg, "_load", lambda: g)
    r = zg.lookup(LAT, LON)
    assert r["cell"] is None
    assert r["area"]["einwohner"] == 7 and r["area_cells"] == 1


def test_no_cells_in_window_is_none(monkeypatch):
    g = grid_around(LAT, LON, {(3, 3): {"einwohner": 7}})
    monkeypatch.setattr(zg, "_load", lambda: g)
    assert zg.lookup(LAT, LON) is None


def test_missing_grid_file_is_none(monkeypatch):
    monkeypatch.setattr(zg, "_load", lambda: None)
    assert zg.lookup(LAT, LON) is None


def test_shares_ignore_all_suppressed(monkeypatch):
    g = grid_around(LAT, LON, {(0, 0): {"einwohner": 3, "geb": 1}})
    monkeypatch.setattr(zg, "_load", lambda: g)
    c = zg.lookup(LAT, LON)["cell"]
    assert c["gebaeude"] == 1 and c["baujahr"] == {} and c["heizung"] == {}


def test_cell_key_is_monotone_and_unique():
    assert zg.cell_key(4110150, 3150250) == 41101 * 1_000_000 + 31502
    assert zg.cell_key(4110150, 3150250) < zg.cell_key(4110250, 3150250)
    assert zg.cell_key(4110150, 3150250) < zg.cell_key(4110150, 3150350)


def test_encode_values_scales_and_marks_missing():
    vals = zg.encode_values([[None, 40.25, 7.5]], ["einwohner", "alter", "miete_qm"])
    assert vals.dtype == np.int16 and vals.tolist() == [[zg.NODATA, 402, 750]]
    assert zg.scales_for(["einwohner", "alter", "miete_qm"]) == [1, 10, 100]


def test_real_grid_covers_essen_and_bonn():
    zg._load.cache_clear()
    try:
        for lat, lon in ((51.4378, 7.0053), (50.7160, 7.0748)):
            r = zg.lookup(lat, lon)
            assert r and r["area"]["einwohner"] and r["area"]["einwohner"] > 0
    finally:
        zg._load.cache_clear()
