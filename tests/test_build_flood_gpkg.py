"""scripts/build_flood_gpkg.py — HWRM shapefiles -> the three GeoPackages flood.py prefers."""
import importlib.util
from pathlib import Path

import geopandas as gpd
import pyogrio
from shapely.geometry import box

from redat.sources import flood

_spec = importlib.util.spec_from_file_location("build_flood_gpkg", Path(__file__).resolve().parent.parent / "scripts" / "build_flood_gpkg.py")
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)

LAT, LON = 51.4556, 7.0116


def _unpacked_zip_dirs(hwrm: Path, n: int = 3) -> None:
    """The three unpacked NRW zips with their real (awkward) shapefile names, n features each around the point."""
    x, y = flood.transformer.transform(LON, LAT)
    for hq, shp in flood._SCENARIOS_SHP().items():          # dir + file names exactly as NRW ships them
        shp = hwrm / shp.relative_to(flood.data_dir())
        shp.parent.mkdir(parents=True, exist_ok=True)
        geoms = [box(x - 50 + i * 1000, y - 50, x + 50 + i * 1000, y + 50) for i in range(n)]
        gpd.GeoDataFrame({"hq": [hq] * n}, geometry=geoms, crs="EPSG:25832").to_file(shp, driver="ESRI Shapefile")


def test_build_converts_each_scenario_in_chunks_and_is_idempotent(tmp_path):
    hwrm = tmp_path / "flood" / "hwrm"
    _unpacked_zip_dirs(hwrm, n=5)
    assert mod.build(hwrm, chunk=2) == ["HQhaeufig", "HQ100", "HQextrem"]
    for hq in ("HQhaeufig", "HQ100", "HQextrem"):
        info = pyogrio.read_info(hwrm / f"{hq}.gpkg")
        assert info["features"] == 5 and info["geometry_type"] == "MultiPolygon"
    assert mod.build(hwrm, chunk=2) == []                    # all present -> nothing rebuilt


def test_build_skips_a_scenario_without_shapefile_and_reports(tmp_path, caplog):
    hwrm = tmp_path / "flood" / "hwrm"
    _unpacked_zip_dirs(hwrm)
    import shutil; shutil.rmtree(hwrm / "HQ100-Ueberschwemmungsgrenzen_EPSG25832_Shape")
    assert mod.build(hwrm) == ["HQhaeufig", "HQextrem"]
    assert "HQ100" in caplog.text


def test_flood_lookup_prefers_the_built_gpkg(tmp_path):
    hwrm = flood.data_dir()
    _unpacked_zip_dirs(hwrm, n=1)
    mod.build(hwrm)
    hit = flood._hit_for_scenario(LAT, LON, "HQ100")
    assert hit.hit is True and hit.raw is not None
