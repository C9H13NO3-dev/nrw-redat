"""Schulen & Sozialindex — nearest schools per Schulform from the NRW school list.

Data: redat/data/schulen_nrw.json.gz, built by scripts/build_schulen.py from the open "Schulstandorte in
NRW" shapefile (coordinates, Schulform, Schülerzahl) and the Schulministerium's Schulliste with the
schulscharfe Sozialindex (Stufe 1 = geringe … 9 = hohe soziale Herausforderungen; explicitly *not* a
quality ranking — it steers resources). Bochum publishes Grundschulbezirke (Einzugsbereich + Kapazität)
on its ArcGIS server; Essen has none (freie Grundschulwahl). `_load` reads the grid (monkeypatch point),
`_bochum_grundschulbezirk` is the single HTTP call (monkeypatch point).
"""
from __future__ import annotations

import gzip
import json
import logging
import math
from functools import lru_cache
from pathlib import Path
from typing import Optional

import httpx

from redat.http import headers

logger = logging.getLogger(__name__)

GRID_PATH = Path(__file__).resolve().parent.parent / "data" / "schulen_nrw.json.gz"
RADIUS_M = 2000
PRIMAR_KEYWORDS = ("grundschule", "primus", "volksschule")   # matched case-insensitively: "Primus (Schulversuch)" is Klasse 1–10
SEK_FORMS = ("Gymnasium", "Gesamtschule", "Realschule", "Hauptschule", "Sekundarschule", "Gemeinschaftsschule", "Waldorfschule")
FOERDER_KEYWORD = "Förderschule"
_MAX_GRUNDSCHULEN = 3
_MAX_FOERDER = 2
# lon_min, lat_min, lon_max, lat_max
from redat.core.nrw import BOCHUM_BBOX_WGS84 as BOCHUM_BBOX
BOCHUM_GSB_URL = "https://geoservicekkm.bochum.de/arcgis/rest/services/maponline/Grundschulen/MapServer/3/query"
_TIMEOUT_S = 15


@lru_cache(maxsize=1)
def _load() -> Optional[dict]:
    try:
        with gzip.open(GRID_PATH, "rt", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _dist_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Equirectangular metres — fine for a 2 km radius."""
    k = math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot((lat2 - lat1) * 111_195, (lon2 - lon1) * 111_195 * k)


def sozialindex_label(stufe: Optional[int]) -> Optional[str]:
    if stufe is None:
        return None
    band = "geringe" if stufe <= 3 else "mittlere" if stufe <= 6 else "hohe"
    return f"Stufe {stufe} von 9 ({band} soziale Herausforderungen)"


def _group(form: str) -> Optional[str]:
    if any(k in form.lower() for k in PRIMAR_KEYWORDS):
        return "grundschulen"
    if FOERDER_KEYWORD in form:
        return "foerderschulen"
    if any(form.startswith(f) for f in SEK_FORMS):
        return "weiterfuehrend"
    return None


def _item(s: dict, dist: float) -> dict:
    return {"name": s.get("name") or s.get("kurzname") or "—", "form": s.get("form"), "distance_m": round(dist),
            "sozialindex": s.get("sozialindex"), "sozialindex_label": sozialindex_label(s.get("sozialindex")),
            "schueler": s.get("schueler"), "adresse": s.get("adresse"), "plz": s.get("plz"), "ort": s.get("ort")}


def _bochum_grundschulbezirk(lat: float, lon: float) -> Optional[dict]:
    """Bochum Grundschulbezirk containing the point — HTTP/monkeypatch point."""
    params = {"f": "json", "where": "1=1", "geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint", "inSR": 4326,
              "spatialRel": "esriSpatialRelIntersects", "outFields": "SCHULNAME,KAP_20_21", "returnGeometry": "false"}
    resp = httpx.get(BOCHUM_GSB_URL, params=params, timeout=_TIMEOUT_S, headers=headers())
    resp.raise_for_status()
    return parse_grundschulbezirk(resp.json())


def parse_grundschulbezirk(payload: dict) -> Optional[dict]:
    feats = payload.get("features") or []
    if not feats:
        return None
    a = feats[0].get("attributes") or {}
    return {"schule": a.get("SCHULNAME"), "kapazitaet": a.get("KAP_20_21")}


def _in_bochum(lat: float, lon: float) -> bool:
    lon_min, lat_min, lon_max, lat_max = BOCHUM_BBOX
    return lon_min <= lon <= lon_max and lat_min <= lat <= lat_max


def _rate(grundschulen: list[dict]) -> tuple[str, str]:
    if grundschulen and grundschulen[0]["distance_m"] <= 1000:
        return "Grundschule fußläufig", "green"
    if grundschulen:
        return "Grundschule im Umkreis von 2 km", "yellow"
    return "Keine Grundschule im Umkreis von 2 km", "orange"


def lookup(lat: float, lon: float) -> Optional[dict]:
    grid = _load()
    if not grid:
        return None
    groups: dict[str, list[tuple[float, dict]]] = {"grundschulen": [], "weiterfuehrend": [], "foerderschulen": []}
    for s in grid.get("schools") or []:
        g = _group(s.get("form") or "")
        if g is None:
            continue
        dist = _dist_m(lat, lon, s["lat"], s["lon"])
        if dist <= RADIUS_M:
            groups[g].append((dist, s))
    for g in groups.values():
        g.sort(key=lambda t: t[0])
    grundschulen = [_item(s, d) for d, s in groups["grundschulen"][:_MAX_GRUNDSCHULEN]]
    seen_forms, weiterfuehrend = set(), []
    for d, s in groups["weiterfuehrend"]:
        form = next((f for f in SEK_FORMS if (s.get("form") or "").startswith(f)), s.get("form"))
        if form in seen_forms:
            continue
        seen_forms.add(form)
        weiterfuehrend.append(_item(s, d))
    foerder = [_item(s, d) for d, s in groups["foerderschulen"][:_MAX_FOERDER]]

    bezirk, bezirk_error = None, None
    if _in_bochum(lat, lon):
        try:
            bezirk = _bochum_grundschulbezirk(lat, lon)
        except Exception as exc:  # noqa: BLE001 — Bochum down must not blank the card
            logger.warning("Bochum Grundschulbezirk: %s", exc)
            bezirk_error = str(exc)
    rating, color = _rate(grundschulen)
    return {
        "radius_m": RADIUS_M, "schuljahr": grid.get("schuljahr"),
        "grundschulen": grundschulen, "weiterfuehrend": weiterfuehrend, "foerderschulen": foerder,
        "counts": {k: len(v) for k, v in groups.items()},
        "grundschulbezirk": bezirk, "grundschulbezirk_error": bezirk_error,
        "rating": rating, "rating_color": color,
    }
