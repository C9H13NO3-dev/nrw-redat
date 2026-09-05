"""scripts/build_boris_gpkg.py — turns the yearly BRW shapefiles into one R-tree-indexed GeoPackage."""
import importlib.util
from pathlib import Path

import geopandas as gpd
import pyogrio
from shapely.geometry import box

from redat.sources import boris

_spec = importlib.util.spec_from_file_location(
    "build_boris_gpkg", Path(__file__).resolve().parent.parent / "scripts" / "build_boris_gpkg.py")
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)

LAT, LON = 51.4556, 7.0116


def _shp(src: Path, year: int, n: int, brw: str) -> None:
    """n square zones in a row; the first one covers (LAT, LON)."""
    x, y = boris.transformer.transform(LON, LAT)
    geoms = [box(x - 50 + i * 1000, y - 50, x + 50 + i * 1000, y + 50) for i in range(n)]
    gdf = gpd.GeoDataFrame({"BRW": [brw] * n, "STAG": [f"{year}-01-01"] * n}, geometry=geoms, crs="EPSG:25832")
    d = src / f"BRW_{year}"
    d.mkdir(parents=True)
    gdf.to_file(d / f"BRW_{year}_Polygon.shp", driver="ESRI Shapefile")


def test_build_writes_one_indexed_layer_per_year_in_chunks(tmp_path):
    src = tmp_path / "boris"
    _shp(src, 2024, 5, "100")
    _shp(src, 2025, 3, "120")
    out = src / boris.GPKG_NAME
    built = mod.build(src, out, years=[2023, 2024, 2025], chunk=2)   # 2023 has no shapefile -> skipped
    assert built == [2024, 2025]
    layers = {name: geom for name, geom in pyogrio.list_layers(out).tolist()}
    assert set(layers) == {"brw_2024", "brw_2025"}
    assert layers["brw_2024"] == "MultiPolygon"                        # promoted, so mixed inputs never fail a chunk
    assert pyogrio.read_info(out, layer="brw_2024")["features"] == 5   # 2 + 2 + 1
    assert pyogrio.read_info(out, layer="brw_2025")["features"] == 3
    import sqlite3
    idx = sqlite3.connect(out).execute("select table_name from gpkg_extensions where extension_name='gpkg_rtree_index'").fetchall()
    assert sorted(t for (t,) in idx) == ["brw_2024", "brw_2025"]


def test_build_is_idempotent_and_skips_existing_layers(tmp_path):
    src = tmp_path / "boris"
    _shp(src, 2025, 2, "120")
    out = src / boris.GPKG_NAME
    assert mod.build(src, out, years=[2025], chunk=10) == [2025]
    assert mod.build(src, out, years=[2025], chunk=10) == []           # already there -> nothing rebuilt
    assert pyogrio.read_info(out, layer="brw_2025")["features"] == 2   # and not appended twice


def test_lookup_uses_the_built_gpkg(tmp_path, monkeypatch):
    src = boris.data_dir()
    _shp(src, 2025, 2, "777")
    mod.build(src, src / boris.GPKG_NAME, years=[2025], chunk=10)
    assert boris._find_source(2025).layer == "brw_2025"
    assert boris.lookup_bodenrichtwert(LAT, LON, 2025).bodenrichtwert == 777.0


def _mixed_encoding_shp(src: Path, year: int) -> Path:
    """Reproduce the real 2022-2024 NRW files: .cpg says UTF-8, most rows are UTF-8, a few are ISO-8859-1.

    Written as Latin-1 (so 'Moers für' holds the raw byte 0xFC), then one other row's fixed-width DBF
    field is byte-patched to genuine UTF-8 ('Kxln ' -> 'Köln', both 5 bytes) and the .cpg forced to UTF-8.
    """
    x, y = boris.transformer.transform(LON, LAT)
    gdf = gpd.GeoDataFrame({"BRW": ["100", "200"], "GABE": ["Moers für", "Kxln"]},
                           geometry=[box(x - 50, y - 50, x + 50, y + 50), box(x + 950, y - 50, x + 1050, y + 50)], crs="EPSG:25832")
    d = src / f"BRW_{year}"
    d.mkdir(parents=True)
    shp = d / f"BRW_{year}_Polygon.shp"
    gdf.to_file(shp, driver="ESRI Shapefile", encoding="ISO-8859-1")
    dbf = shp.with_suffix(".dbf")
    raw = dbf.read_bytes()
    assert raw.count(b"Kxln ") == 1 and b"Moers f\xfcr" in raw
    dbf.write_bytes(raw.replace(b"Kxln ", "Köln".encode("utf-8")))
    shp.with_suffix(".cpg").write_text("UTF-8")
    return shp


def test_build_repairs_rows_with_mixed_encodings(tmp_path):
    src = tmp_path / "boris"
    _mixed_encoding_shp(src, 2022)
    out = src / boris.GPKG_NAME
    assert mod.build(src, out, years=[2022], chunk=10) == [2022]
    got = gpd.read_file(out, layer="brw_2022").sort_values("BRW")["GABE"].tolist()
    assert got == ["Moers für", "Köln"]     # latin-1 row kept, utf-8 row not mangled into 'KÃ¶ln'


def test_build_rebuilds_a_half_written_layer(tmp_path):
    src = tmp_path / "boris"
    _shp(src, 2025, 4, "120")
    out = src / boris.GPKG_NAME
    # Simulate a crashed earlier run: the layer exists but holds only part of the shapefile.
    partial = gpd.read_file(src / "BRW_2025" / "BRW_2025_Polygon.shp").iloc[:1]
    pyogrio.write_dataframe(partial, out, layer="brw_2025", driver="GPKG", promote_to_multi=True)   # as the script writes it
    assert pyogrio.read_info(out, layer="brw_2025")["features"] == 1
    assert mod.build(src, out, years=[2025], chunk=3) == [2025]
    assert pyogrio.read_info(out, layer="brw_2025")["features"] == 4   # rebuilt in full, not appended to 5
