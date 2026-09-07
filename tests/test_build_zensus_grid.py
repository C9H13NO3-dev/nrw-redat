"""scripts/build_zensus_grid.py — parser/cropper unit tests on tiny inline CSVs."""
import importlib.util
import io
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "build_zensus_grid", Path(__file__).resolve().parent.parent / "scripts" / "build_zensus_grid.py")
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


def test_parse_value():
    assert mod.parse_value("11") == 11
    assert mod.parse_value("36,75") == 36.75
    assert mod.parse_value("–") is None            # Destatis suppression dash (UTF-8)
    assert mod.parse_value("�") is None       # the same dash read from a cp1252 file
    assert mod.parse_value("") is None
    assert mod.parse_value("(3)") is None


def test_ingest_crops_and_maps_columns():
    csv = (
        "GITTER_ID_100m;x_mp_100m;y_mp_100m;Durchschnittsalter;werterlaeuternde_Zeichen\n"
        "CRS3035RES100mN2689100E4337000;4337050;2689150;36,75;\n"
        "CRS3035RES100mN2689100E4341100;4341150;2689150;39,78;KLAMMERN\n"   # low reliability, keep value
        "CRS3035RES100mN2689100E4341100;4341150;2689250;–;\n"
        "CRS3035RES100mN2689100E4341100;4399950;2689150;50,00;\n"            # outside bbox
    )
    cells = {}
    n = mod.ingest(io.StringIO(csv), {"Durchschnittsalter": "alter"}, (4337000, 2689000, 4342000, 2690000), cells)
    assert n == 3
    assert cells["4337050_2689150"] == {"alter": 36.75}
    assert cells["4341150_2689150"] == {"alter": 39.78}
    assert cells["4341150_2689250"] == {"alter": None}


def test_ingest_multi_column_and_uppercase_header():
    csv = (
        "GITTER_ID_100M;x_mp_100m;y_mp_100m;Insgesamt_Gebaeude;Vor1919;a2016undspaeter\n"
        "X;4341150;2691750;3;–;3\n"
    )
    cells = {"4341150_2691750": {"alter": 40.0}}
    mod.ingest(io.StringIO(csv), {"Insgesamt_Gebaeude": "geb", "Vor1919": "bj_vor1919", "a2016undspaeter": "bj_2016plus"},
               (4300000, 2600000, 4400000, 2700000), cells)
    assert cells["4341150_2691750"] == {"alter": 40.0, "geb": 3, "bj_vor1919": None, "bj_2016plus": 3}


def test_to_rows_uses_field_order_and_drops_empty_cells():
    cells = {"1_2": {"alter": 40.0, "geb": 3}, "3_4": {"alter": None, "geb": None}}
    rows = mod.to_rows(cells, ["einwohner", "alter", "geb"])
    assert rows == {"1_2": [None, 40.0, 3]}


def test_sources_cover_every_field():
    from redat.sources import zensus as zg
    mapped = {f for _, cols in mod.SOURCES for f in cols.values()}
    assert mapped == set(zg.FIELDS)


def test_to_arrays_sorts_keys_and_encodes():
    rows = {"4110250_3150250": [12, 40.0, None], "4110150_3150250": [3, None, 7.5]}
    keys, values = mod.to_arrays(rows, ["einwohner", "alter", "miete_qm"])
    assert keys.tolist() == [41101 * 1_000_000 + 31502, 41102 * 1_000_000 + 31502]
    assert values.tolist() == [[3, -32768, 750], [12, 400, -32768]]


def test_build_bbox_is_statewide():
    xmin, ymin, xmax, ymax = mod.bbox_3035()
    assert xmax - xmin > 250_000 and ymax - ymin > 250_000   # NRW, not the 40 km Essen/Bochum window
