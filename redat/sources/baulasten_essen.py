"""Baulasten on and next to the parcel — Stadt Essen "Baulasteninformation" (Essen only).

Source: https://geo.essen.de/arcgis/rest/services/essen/Baulasteninformation/MapServer, layer 0
"Baulasten vorhanden" (21,410 Flurstück polygons) and layer 1 "Baulasten ggf. vorhanden" (207). Fields
(verified 2026-09-05): FSK "05314403900040" — the 14 significant characters of the ALKIS
Flurstückskennzeichen, so a parcel from redat.sources.alkis matches by string equality; ART
"BauOrdnungsrecht / Zufahrt" (Rechtsgrund " / " Art, Art may be empty); BAULAST "9 / 604 / 1" (Blatt).
The FSK is exactly 14 characters on all 21,410 rows (Gemarkung 6 + Flur 3 + Zähler 5; Essen has no
Nenner parcels, verified 2026-09-05) — so a parcel key that is missing or not 14 characters long cannot
be matched, and the card then reports status "unbekannt" with every hit under `nearby` instead of
claiming "keine". The city calls the data kostenlos, unverbindlich, ohne Gewähr, wöchentlich
aktualisiert — the card must say so; a binding Auskunft is a written request to the Bauaufsicht.
Layer 2 (Blatt/Vermerk per Flurstück, mostly blank) is not used. `_query` is the single HTTP call and
monkeypatch point.
"""
from __future__ import annotations

from typing import Optional

import httpx

from redat.http import headers

BL_URL = "https://geo.essen.de/arcgis/rest/services/essen/Baulasteninformation/MapServer"
# lon_min, lat_min, lon_max, lat_max — Essen city, coarse
from redat.core.nrw import ESSEN_BBOX_WGS84 as ESSEN_BBOX
RADIUS_M = 50
_LAYERS = ((0, "vorhanden"), (1, "moeglich"))
_FSK_LEN = 14                              # Essen FSK: Gemarkung 6 + Flur 3 + Zähler 5, no Nenner
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
    """Baulasten within RADIUS_M split into this parcel / neighbours, or None outside Essen.

    status: "vorhanden" / "moeglich" (hit on the parcel), "keine" (parcel key matched nothing) or
    "unbekannt" — the parcel key is unusable (missing or not _FSK_LEN characters), so nothing can be
    assigned to the parcel and every hit is reported as `nearby`.
    """
    if not in_essen(lat, lon):
        return None
    matchable = bool(kennzeichen) and len(kennzeichen) == _FSK_LEN
    on_parcel, nearby, seen = [], [], set()
    for layer, layer_status in _LAYERS:
        for f in _query(layer, lat, lon, RADIUS_M).get("features") or []:
            a = f.get("attributes") or {}
            fsk, blatt = str(a.get("FSK") or "").strip(), str(a.get("BAULAST") or "").strip() or None
            rechtsgrund, art = parse_art(a.get("ART"))
            if (fsk, blatt, rechtsgrund, art, layer_status) in seen:
                continue
            seen.add((fsk, blatt, rechtsgrund, art, layer_status))
            item = {"rechtsgrund": rechtsgrund, "art": art, "blatt": blatt, "kennzeichen": fsk or None, "status": layer_status}
            if matchable and fsk == kennzeichen:
                on_parcel.append(item)
            else:
                nearby.append(item)
    if not matchable:
        status = "unbekannt"
    elif any(i["status"] == "vorhanden" for i in on_parcel):
        status = "vorhanden"
    elif on_parcel:
        status = "moeglich"
    else:
        status = "keine"
    return {"status": status, "on_parcel": on_parcel, "nearby": nearby, "radius_m": RADIUS_M}
