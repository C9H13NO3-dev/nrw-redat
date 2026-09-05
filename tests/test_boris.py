import pytest

from redat.sources import boris


def test_data_dir_follows_settings():
    from redat.settings import get_settings
    assert boris.data_dir() == get_settings().source_dir / "boris"


def test_find_shapefile_none_when_missing():
    assert boris._find_shapefile(2025) is None


def test_lookup_raises_missing_data_with_path():
    with pytest.raises(boris.MissingData, match="BORIS-Daten fehlen unter .*source/boris"):
        boris.lookup_bodenrichtwert(51.45, 7.01)


def test_get_boris_nrw_maps_result(monkeypatch):
    res = boris.BorisResult(bodenrichtwert=410.0, stichtag="2025-01-01", nutzung="W", zone_name="Z1", gemeinde="Essen", year=2025, raw={"a": 1})
    monkeypatch.setattr(boris, "_lookup_in_subprocess", lambda lat, lon: res)
    assert boris.get_boris_nrw(51.45, 7.01) == {"bodenrichtwert": 410.0, "date": "2025-01-01", "zone": "Z1", "nutzung": "W", "gemeinde": "Essen", "raw": {"a": 1}}


def test_get_boris_nrw_no_data(monkeypatch):
    monkeypatch.setattr(boris, "_lookup_in_subprocess", lambda lat, lon: None)
    assert boris.get_boris_nrw(51.45, 7.01) == {"error": "No BORIS data for this location"}


def test_get_boris_nrw_error_passthrough(monkeypatch):
    monkeypatch.setattr(boris, "_lookup_in_subprocess", lambda lat, lon: {"__error__": "BORIS-Daten fehlen unter /x"})
    assert boris.get_boris_nrw(51.45, 7.01) == {"error": "BORIS-Daten fehlen unter /x"}


def test_get_boris_nrw_timeout(monkeypatch):
    monkeypatch.setattr(boris, "_lookup_in_subprocess", lambda lat, lon: boris._TIMEOUT)
    assert boris.get_boris_nrw(51.45, 7.01) == {"error": "BORIS timeout"}


def test_subprocess_wrapper_returns_missing_data_error_for_real():
    # end-to-end through the real subprocess against the (empty) tmp source dir
    out = boris.get_boris_nrw(51.45, 7.01)
    assert out["error"].startswith("BORIS-Daten fehlen unter")


# --------------------------------------------------------------------------- source discovery + lookup
# Synthetic geodata in the per-test tmp source dir: a box of +-`half` m around (LAT, LON) in EPSG:25832.
import geopandas as gpd
from shapely.geometry import box

LAT, LON = 51.4556, 7.0116


def _utm(lat=LAT, lon=LON):
    x, y = boris.transformer.transform(lon, lat)
    return x, y


def _zone(brw: str, half: float = 100.0, dx: float = 0.0, **cols) -> gpd.GeoDataFrame:
    x, y = _utm()
    attrs = {"BRW": [brw], "STAG": ["2025-01-01"], "NUTA": ["W"], "GENA": ["Z1"], "GEMNAME": ["Essen"], **{k: [v] for k, v in cols.items()}}
    return gpd.GeoDataFrame(attrs, geometry=[box(x - half + dx, y - half, x + half + dx, y + half)], crs="EPSG:25832")


def _write_shp(year: int, gdf: gpd.GeoDataFrame) -> None:
    d = boris.data_dir() / f"BRW_{year}"
    d.mkdir(parents=True)
    gdf.to_file(d / f"BRW_{year}_Polygon.shp", driver="ESRI Shapefile")


def _write_gpkg_layer(year: int, gdf: gpd.GeoDataFrame) -> None:
    boris.data_dir().mkdir(parents=True, exist_ok=True)
    gdf.to_file(boris.data_dir() / boris.GPKG_NAME, layer=f"brw_{year}", driver="GPKG", mode="a")


def test_find_source_prefers_gpkg_layer_over_shapefile():
    _write_shp(2025, _zone("100"))
    _write_gpkg_layer(2025, _zone("200"))
    src = boris._find_source(2025)
    assert src == boris.Source(boris.data_dir() / boris.GPKG_NAME, "brw_2025")


def test_find_source_falls_back_to_shapefile_when_year_not_in_gpkg():
    _write_shp(2024, _zone("100"))
    _write_gpkg_layer(2025, _zone("200"))
    assert boris._find_source(2024) == boris.Source(boris.data_dir() / "BRW_2024" / "BRW_2024_Polygon.shp", None)
    assert boris._find_source(2023) is None


def test_lookup_reads_the_requested_year_from_gpkg():
    _write_gpkg_layer(2020, _zone("300"))
    _write_gpkg_layer(2025, _zone("450"))
    assert boris.lookup_bodenrichtwert(LAT, LON, 2020).bodenrichtwert == 300.0
    r = boris.lookup_bodenrichtwert(LAT, LON, 2025)
    assert (r.bodenrichtwert, r.nutzung, r.zone_name, r.gemeinde, r.year) == (450.0, "W", "Z1", "Essen", 2025)
    assert r.raw["BRW"] == "450" and "geometry" not in r.raw


def test_lookup_from_shapefile_still_works():
    _write_shp(2025, _zone("275"))
    assert boris.lookup_bodenrichtwert(LAT, LON, 2025).bodenrichtwert == 275.0


def test_lookup_does_exactly_one_bbox_read_and_never_loads_the_whole_file(monkeypatch):
    # The polygon is 3 km away: the 1 km bbox read comes back empty.
    # Previously this fell through to a 5 km read and then a FULL shapefile load (the OOM/timeout bug).
    _write_shp(2025, _zone("999", dx=3000.0))
    calls = []
    real = gpd.read_file

    def counting(*a, **kw):
        calls.append(kw.get("bbox"))
        return real(*a, **kw)

    monkeypatch.setattr(boris.gpd, "read_file", counting)
    assert boris.lookup_bodenrichtwert(LAT, LON, 2025) is None
    assert len(calls) == 1 and calls[0] is not None      # one read, and it was bbox-limited


def test_lookup_snaps_to_a_zone_within_10m_but_not_further():
    _write_gpkg_layer(2025, _zone("500", dx=105.0))      # box edge 5 m east of the point
    assert boris.lookup_bodenrichtwert(LAT, LON, 2025).bodenrichtwert == 500.0
    _write_gpkg_layer(2024, _zone("500", dx=150.0))      # edge 50 m away -> gap too large
    assert boris.lookup_bodenrichtwert(LAT, LON, 2024) is None


def test_get_available_years_sees_gpkg_layers_and_shapefiles():
    _write_gpkg_layer(2011, _zone("1"))
    _write_shp(2025, _zone("2"))
    assert boris.get_available_years() == [2011, 2025]


def test_trend_across_gpkg_years():
    _write_gpkg_layer(2023, _zone("200"))
    _write_gpkg_layer(2024, _zone("250"))
    _write_gpkg_layer(2025, _zone("300"))
    t = boris.get_historical_trend(LAT, LON, years=[2023, 2024, 2025])
    assert [h["value"] for h in t.history] == [200.0, 250.0, 300.0]
    assert (t.oldest_year, t.current_year, t.total_change) == (2023, 2025, 50.0)
    assert t.history[1]["change_percent"] == 25.0


def test_lookup_survives_latin1_bytes_in_a_utf8_declared_shapefile():
    # The real 2022-2024 NRW shapefiles carry a few ISO-8859-1 rows under a UTF-8 .cpg; a plain read raises
    # UnicodeDecodeError and the card silently returned None for every address near such a row.
    gdf = _zone("640", GABE="Moers für")
    d = boris.data_dir() / "BRW_2023"
    d.mkdir(parents=True)
    shp = d / "BRW_2023_Polygon.shp"
    gdf.to_file(shp, driver="ESRI Shapefile", encoding="ISO-8859-1")
    shp.with_suffix(".cpg").write_text("UTF-8")
    r = boris.lookup_bodenrichtwert(LAT, LON, 2023)
    assert r is not None and r.bodenrichtwert == 640.0
    assert r.raw["GABE"] == "Moers für"
