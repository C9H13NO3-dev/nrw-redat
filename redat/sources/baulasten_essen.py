"""Baulasten on and next to the parcel — Stadt Essen "Baulasteninformation" (Essen only).

Source: https://geo.essen.de/arcgis/rest/services/essen/Baulasteninformation/MapServer, layer 0
"Baulasten vorhanden" (21,410 Flurstück polygons) and layer 1 "Baulasten ggf. vorhanden" (207). Fields
(verified 2026-09-05): FSK "05314403900040" — the 14 significant characters of the ALKIS
Flurstückskennzeichen, so a parcel from redat.sources.alkis matches by string equality; ART
"BauOrdnungsrecht / Zufahrt" (Rechtsgrund " / " Art, Art may be empty); BAULAST "9 / 604 / 1" (Blatt).
The city calls the data kostenlos, unverbindlich, ohne Gewähr, wöchentlich aktualisiert — the card must
say so; a binding Auskunft is a written request to the Bauaufsicht.
Layer 2 (Blatt/Vermerk per Flurstück, mostly blank) is not used. `_query` is the single HTTP call and
monkeypatch point.
"""
from __future__ import annotations

import logging
from typing import Optional

import httpx

from redat.http import headers

logger = logging.getLogger(__name__)

BL_URL = "https://geo.essen.de/arcgis/rest/services/essen/Baulasteninformation/MapServer"
ESSEN_BBOX = (6.89, 51.35, 7.14, 51.53)   # lon_min, lat_min, lon_max, lat_max — Essen city, coarse
RADIUS_M = 50
_LAYERS = ((0, "vorhanden"), (1, "moeglich"))
_TIMEOUT_S = 25


def in_essen(lat: float, lon: float) -> bool:
    lon_min, lat_min, lon_max, lat_max = ESSEN_BBOX
    return lon_min <= lon <= lon_max and lat_min <= lat <= lat_max


def _query(layer: int, lat: float, lon: float, distance_m: float) -> dict:
    """ArcGIS point query with a metre buffer — HTTP/monkeypatch point."""
    params = {
        "f": "json", "where": "1=1", "geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint", "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects", "distance": distance_m, "units": "esriSRUnit_Meter",
        "outFields": "ART,FSK,BAULAST,TYP_BL,ALKIS_AMTL_FLAECHE", "returnGeometry": "false", "resultRecordCount": 50,
    }
    resp = httpx.get(f"{BL_URL}/{layer}/query", params=params, timeout=_TIMEOUT_S, headers=headers())
    resp.raise_for_status()
    return resp.json()


def parse_art(text: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """'BauOrdnungsrecht / Zufahrt' → ('BauOrdnungsrecht', 'Zufahrt'); blanks → None."""
    rechtsgrund, _, art = (text or "").partition("/")
    return rechtsgrund.strip() or None, art.strip() or None


def get_baulasten(lat: float, lon: float, kennzeichen: Optional[str]) -> Optional[dict]:
    """Baulasten within RADIUS_M split into this parcel / neighbours, or None outside Essen."""
    if not in_essen(lat, lon):
        return None
    items, seen = [], set()
    for layer, status in _LAYERS:
        for f in _query(layer, lat, lon, RADIUS_M).get("features") or []:
            a = f.get("attributes") or {}
            fsk, blatt = str(a.get("FSK") or "").strip(), str(a.get("BAULAST") or "").strip() or None
            if (fsk, blatt, status) in seen:
                continue
            seen.add((fsk, blatt, status))
            rechtsgrund, art = parse_art(a.get("ART"))
            items.append({"rechtsgrund": rechtsgrund, "art": art, "blatt": blatt, "kennzeichen": fsk or None, "status": status})
    on_parcel = [i for i in items if kennzeichen and i["kennzeichen"] == kennzeichen]
    nearby = [i for i in items if i not in on_parcel]
    if any(i["status"] == "vorhanden" for i in on_parcel):
        status = "vorhanden"
    elif on_parcel:
        status = "moeglich"
    else:
        status = "keine"
    return {"status": status, "on_parcel": on_parcel, "nearby": nearby, "radius_m": RADIUS_M}
