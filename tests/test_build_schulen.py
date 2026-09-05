"""scripts/build_schulen.py — Sozialindex CSV + Schulen shapefile → schools list (unit tests, in-memory)."""
import importlib.util
import io
from pathlib import Path

import geopandas as gpd
from shapely.geometry import Point

_spec = importlib.util.spec_from_file_location("build_schulen", Path(__file__).resolve().parent.parent / "scripts" / "build_schulen.py")
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)

CSV = ("Schulnummer;Kurzbezeichnung;Bezirksregierung;Kreis;Gemeinde;Sozialindexstufe\n"
       "100011;Haan, GE Walder Straße;BR Düsseldorf;Kreis Mettmann;Haan;4\n"
       "102416;Essen, GG Käthe-Kollwitz;BR Düsseldorf;Stadt Essen;Essen;\n"
       "100000;Bochum, WBK KOL Studienkolleg;BR Arnsberg;Stadt Bochum;Bochum;9\n")


def test_read_sozialindex_skips_blank():
    assert mod.read_sozialindex(io.StringIO(CSV)) == {"100011": 4, "100000": 9}


def test_rows_from_gdf_reprojects_and_parses_schueler():
    gdf = gpd.GeoDataFrame(
        {"Schulnumme": ["102416", "100000"], "Schulform": ["Grundschule", "Weiterbildungskolleg"],
         "Name": ["Käthe-Kollwitz-Schule", "Studienkolleg"], "Kurzname": ["Essen, GG KKS", "Bochum, WBK"],
         "Adresse": ["Christinenstr. 4", "Girondelle 80"], "Postleitza": ["45131", "44799"], "Ort": ["Essen", "Bochum"],
         "Schueler": ["250", "0"]},
        geometry=[Point(361370.16, 5699486.35), Point(375000.0, 5702000.0)], crs="EPSG:25832")   # first = 7.0058 E, 51.4296 N
    rows = mod.rows_from_gdf(gdf)
    assert rows[0]["nr"] == "102416" and rows[0]["form"] == "Grundschule" and rows[0]["schueler"] == 250
    assert abs(rows[0]["lat"] - 51.4296) < 0.0001 and abs(rows[0]["lon"] - 7.0058) < 0.0001
    assert rows[1]["schueler"] is None       # "0" means "not reported"
    assert rows[0]["adresse"] == "Christinenstr. 4" and rows[0]["plz"] == "45131" and rows[0]["ort"] == "Essen"


def test_merge_attaches_index_or_none():
    rows = [{"nr": "100011", "name": "GE Haan"}, {"nr": "102416", "name": "KKS"}]
    out = mod.merge(rows, {"100011": 4})
    assert out[0]["sozialindex"] == 4 and out[1]["sozialindex"] is None
