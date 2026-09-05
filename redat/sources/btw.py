"""Bundestagswahl (BT) Wahlkreis political profile.

- Finds the Bundestagswahlkreis for a coordinate using Bundeswahlleiterin geometry
- Returns top parties (Zweitstimmen) for that Wahlkreis based on official OpenData CSV

Data sources (Open Data):
- Wahlkreis geometry downloads page:
  https://www.bundeswahlleiterin.de/bundestagswahlen/2025/wahlkreiseinteilung/downloads.html
- Ergebnisdaten (CSV):
  https://www.bundeswahlleiterin.de/bundestagswahlen/2025/ergebnisse/opendata.html

We use:
- kerg2.csv ("Ergebnisse nach Wahlkreisen")
- Shapefile in geographic coords (WGS84) for fast point-in-polygon

"""

from __future__ import annotations

import csv
import io
import logging
import zipfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

import httpx
import geopandas as gpd
from shapely.geometry import Point

from redat.http import headers
from redat.settings import get_settings

logger = logging.getLogger(__name__)


def data_dir() -> Path:
    return get_settings().source_dir / "elections" / "btw25"


def shp_path() -> Path:
    # Real filename as shipped in the Bundeswahlleiterin zip; ensure_wahlkreis_shapefile()'s
    # rglob fallback covers a future release renaming it (an earlier version of this module
    # named a stale "Wahlkreise_WGS84.shp" here and only worked via that fallback).
    return data_dir() / "wahlkreise_shp_geo" / "btw25_geometrie_wahlkreise_vg250_shp_geo.shp"


# --- Sources ---

BTW25_WAHLKREISE_SHP_GEO_ZIP = "https://www.bundeswahlleiterin.de/dam/jcr/a3b60aa9-8fa5-4223-9fb4-0a3a3cebd7d1/btw25_geometrie_wahlkreise_vg250_shp_geo.zip"
BTW25_KERG2_CSV = "https://www.bundeswahlleiterin.de/bundestagswahlen/2025/ergebnisse/opendata/btw25/csv/kerg2.csv"


PARTY_COLORS = {
    "SPD": "#E3000F",
    "CDU": "#000000",
    "CSU": "#008AC5",
    "GRÜNE": "#64A12D",
    "BÜNDNIS 90/DIE GRÜNEN": "#64A12D",
    "FDP": "#FFED00",
    "AfD": "#009EE0",
    "Die Linke": "#BE3075",
    "FREIE WÄHLER": "#F18A00",
    "BSW": "#7D3C98",
}


@dataclass
class Wahlkreis:
    nr: int
    name: str


def _download(url: str) -> bytes:
    with httpx.Client(timeout=60.0, follow_redirects=True, headers=headers()) as client:
        r = client.get(url)
        r.raise_for_status()
        return r.content


def ensure_wahlkreis_shapefile() -> Path:
    """Ensure the BTW25 Wahlkreis shapefile is available locally."""
    data_dir().mkdir(parents=True, exist_ok=True)
    shp = shp_path()
    if shp.exists():
        return shp

    logger.info("Downloading BTW25 Wahlkreis shapefile (geo)...")
    blob = _download(BTW25_WAHLKREISE_SHP_GEO_ZIP)

    shp_folder = data_dir() / "wahlkreise_shp_geo"
    shp_folder.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        zf.extractall(shp_folder)

    # Try to locate shp if naming differs
    if shp.exists():
        return shp

    candidates = list(shp_folder.rglob("*.shp"))
    if not candidates:
        raise RuntimeError("Could not find extracted shapefile")

    return candidates[0]


@lru_cache(maxsize=1)
def _load_wahlkreise_gdf() -> gpd.GeoDataFrame:
    shp = ensure_wahlkreis_shapefile()
    logger.info(f"Loading Wahlkreise shapefile: {shp}")
    gdf = gpd.read_file(shp)
    return gdf


def find_wahlkreis(lat: float, lon: float) -> Optional[Wahlkreis]:
    """Find Wahlkreis for coordinate (WGS84)."""
    gdf = _load_wahlkreise_gdf()

    pt = Point(lon, lat)

    try:
        matches = gdf[gdf.geometry.covers(pt)]
    except Exception:
        matches = gdf[gdf.geometry.contains(pt)]

    if matches.empty:
        # Try nearest within small tolerance (rare)
        try:
            dists = gdf.geometry.distance(pt)
            idx = dists.idxmin()
            if float(dists.loc[idx]) < 0.01:  # degrees ~1km-ish; very loose
                matches = gdf.loc[[idx]]
        except Exception:
            return None

    if matches.empty:
        return None

    row = matches.iloc[0]

    # Attribute names per downloads page
    nr = int(row.get("WKR_NR"))
    name = str(row.get("WKR_NAME"))

    return Wahlkreis(nr=nr, name=name)


@lru_cache(maxsize=1)
def _load_kerg2_index() -> dict[int, list[dict]]:
    """Load kerg2.csv and build index: wahlkreis_nr -> sorted party results (Zweitstimme)."""
    logger.info("Downloading/parsing BTW25 kerg2.csv...")
    text = _download(BTW25_KERG2_CSV).decode("utf-8", errors="ignore")

    # Find header line that starts with "Wahlart;"
    lines = text.splitlines()
    header_i = None
    for i, line in enumerate(lines):
        if line.startswith("Wahlart;"):
            header_i = i
            break
    if header_i is None:
        raise RuntimeError("kerg2.csv header not found")

    reader = csv.DictReader(lines[header_i:], delimiter=";")

    out: dict[int, list[dict]] = {}

    for row in reader:
        try:
            if row.get("Wahlart") != "BT":
                continue
            if row.get("Gebietsart") != "Wahlkreis":
                continue
            if row.get("Gruppenart") != "Partei":
                continue
            if row.get("Stimme") != "2":
                continue

            wk = int(row.get("Gebietsnummer") or 0)
            party = (row.get("Gruppenname") or "").strip()
            pct_s = (row.get("Prozent") or "").strip().replace(",", ".")
            pct = float(pct_s) if pct_s else 0.0

            out.setdefault(wk, []).append({
                "party": party,
                "percent": round(pct, 2),
                "color": PARTY_COLORS.get(party, "#6B7280"),
            })
        except Exception:
            continue

    # Sort each by percent desc
    for wk, arr in out.items():
        arr.sort(key=lambda x: x["percent"], reverse=True)

    return out


def get_btw_wahlkreis_profile(lat: float, lon: float, top_n: int = 5) -> dict:
    wk = find_wahlkreis(lat, lon)
    if not wk:
        return {"error": "Wahlkreis nicht gefunden"}

    idx = _load_kerg2_index()
    parties = idx.get(wk.nr, [])[:top_n]

    return {
        "election": "Bundestagswahl 2025",
        "wahlkreis": {"nr": wk.nr, "name": wk.name},
        "top_parties": parties,
        "source": "Die Bundeswahlleiterin (Open Data kerg2.csv, Zweitstimmen, Wahlkreise)"
    }
