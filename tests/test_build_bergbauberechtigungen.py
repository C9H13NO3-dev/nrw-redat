import importlib.util
from pathlib import Path

import geopandas as gpd
from shapely.geometry import box

_spec = importlib.util.spec_from_file_location("build_bb", Path(__file__).resolve().parent.parent / "scripts" / "build_bergbauberechtigungen.py")
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


def _gdf():
    return gpd.GeoDataFrame(
        {"FELDESNUMM": ["4000138701", "1"], "BERECHTIGU": ["aufrechterhaltenes Bergwerkseigentum", "Bewilligung"],
         "BODENSCHAT": ["Eisenerz", "Steinkohle"], "FELDESNAME": ["Neu Essen", "Fern"], "FELDESGROE": ["140 110 991 m²", "1 m²"],
         "ENTSTEHUNG": ["23.01.1791", "-"], "LAUFZEIT_V": ["-", "-"], "LAUFZEIT_B": ["-", "-"], "ERLOSCHEN": ["nein", "ja"],
         "RECHTSINHA": ["TRATON SE", "X"], "SCHLUESSEL": ["Eisenerze", "Kohle"], "SCHLUESS00": ["4", "1"]},
        geometry=[box(360000, 5698000, 362000, 5700000), box(200000, 5500000, 201000, 5501000)], crs="EPSG:25832")


def test_crop_keeps_only_window_features_in_wgs84():
    out = mod.crop(_gdf(), mod.BBOX_WGS84)
    assert len(out) == 1 and out.crs.to_epsg() == 4326 and out.iloc[0]["FELDESNAME"] == "Neu Essen"


def test_to_features_maps_fields_and_booleans():
    feats = mod.to_features(mod.crop(_gdf(), mod.BBOX_WGS84))
    p = feats[0]["properties"]
    assert p == {"feld": "Neu Essen", "art": "aufrechterhaltenes Bergwerkseigentum", "bodenschatz": "Eisenerz", "inhaber": "TRATON SE",
                 "seit": "23.01.1791", "bis": None, "erloschen": False, "groesse": "140 110 991 m²", "nummer": "4000138701"}
    assert feats[0]["geometry"]["type"] in ("Polygon", "MultiPolygon")


def test_bbox_is_statewide():
    assert mod.BBOX_WGS84 == (5.753, 50.242, 9.589, 52.619)
