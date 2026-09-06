"""Fluglärm and Ruhige Gebiete — what the state Umgebungslärm map does not show.

Sources (ArcGIS REST point queries, verified 2026-09-06):
- Essen Lärmkarte https://geo.essen.de/arcgis/rest/services/essen/Laermkarte_aktuell/MapServer: layer 5 Flugverkehr
  DUS (L_DEN; two polygons, 20 km² in Kettwig/Werden, classes Lden5559/Lden6064), 11 Flugverkehr DUS (L_night),
  4 Flugverkehr EMH (Essen/Mülheim, L_DEN). Fields CATEGORY, PEGEL, TEXT ("ab 55 bis 59 dB(A)").
- Ruhige Gebiete (§ 47d BImSchG, Lärmaktionsplan): Essen .../Ruhige_Gebiete/MapServer/26 (NAME, BESCHREIBU),
  Bochum https://geoservicekkm.bochum.de/arcgis/rest/services/maponline/Laermkartierung_Stufe4/MapServer/20
  (NAME, ART, BEZIRK; the server rejects resultRecordCount — never send it).
Queries are city-gated by bbox; every layer is isolated (`errors[<key>]`). `_query` is the HTTP/monkeypatch point.
"""
from __future__ import annotations

import logging
from typing import Optional

import httpx

from redat.http import headers

logger = logging.getLogger(__name__)

ESSEN_FLUG_DUS_DAY = "https://geo.essen.de/arcgis/rest/services/essen/Laermkarte_aktuell/MapServer/5/query"
ESSEN_FLUG_DUS_NIGHT = "https://geo.essen.de/arcgis/rest/services/essen/Laermkarte_aktuell/MapServer/11/query"
ESSEN_FLUG_EMH_DAY = "https://geo.essen.de/arcgis/rest/services/essen/Laermkarte_aktuell/MapServer/4/query"
ESSEN_RUHIG = "https://geo.essen.de/arcgis/rest/services/essen/Ruhige_Gebiete/MapServer/26/query"
BOCHUM_RUHIG = "https://geoservicekkm.bochum.de/arcgis/rest/services/maponline/Laermkartierung_Stufe4/MapServer/20/query"
ESSEN_BBOX = (6.89, 51.35, 7.14, 51.53)
BOCHUM_BBOX = (7.10, 51.40, 7.35, 51.53)
_TIMEOUT_S = 15


def _in(bbox, lat, lon) -> bool:
    lon_min, lat_min, lon_max, lat_max = bbox
    return lon_min <= lon <= lon_max and lat_min <= lat <= lat_max


def _query(url: str, lat: float, lon: float, out_fields: str) -> dict:
    params = {"f": "json", "where": "1=1", "geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint", "inSR": 4326,
              "spatialRel": "esriSpatialRelIntersects", "outFields": out_fields, "returnGeometry": "false"}
    resp = httpx.get(url, params=params, timeout=_TIMEOUT_S, headers=headers())
    resp.raise_for_status()
    return resp.json()


def _first(url: str, lat: float, lon: float, out_fields: str, errors: dict, key: str) -> Optional[dict]:
    try:
        feats = _query(url, lat, lon, out_fields).get("features") or []
    except Exception as exc:  # noqa: BLE001
        logger.warning("noise_extra %s: %s", key, exc)
        errors[key] = str(exc)
        return None
    return (feats[0].get("attributes") or {}) if feats else None


def get_noise_extra(lat: float, lon: float) -> dict:
    out: dict = {"flug": None, "ruhiges_gebiet": None, "errors": {}}
    if _in(ESSEN_BBOX, lat, lon):
        dus = _first(ESSEN_FLUG_DUS_DAY, lat, lon, "CATEGORY,PEGEL,TEXT", out["errors"], "flug_dus_day")
        if dus:
            night = _first(ESSEN_FLUG_DUS_NIGHT, lat, lon, "CATEGORY,PEGEL,TEXT", out["errors"], "flug_dus_night")
            out["flug"] = {"airport": "DUS", "day": dus.get("TEXT"), "night": night.get("TEXT") if night else None}
        else:
            emh = _first(ESSEN_FLUG_EMH_DAY, lat, lon, "CATEGORY,PEGEL,TEXT", out["errors"], "flug_emh_day")
            if emh:
                out["flug"] = {"airport": "EMH", "day": emh.get("TEXT"), "night": None}
        rg = _first(ESSEN_RUHIG, lat, lon, "NAME,BESCHREIBU", out["errors"], "ruhig_essen")
        if rg:
            out["ruhiges_gebiet"] = {"name": rg.get("NAME") or rg.get("BESCHREIBU") or "Ruhiges Gebiet", "stadt": "Essen"}
    elif _in(BOCHUM_BBOX, lat, lon):
        rg = _first(BOCHUM_RUHIG, lat, lon, "NAME,ART,BEZIRK", out["errors"], "ruhig_bochum")
        if rg:
            out["ruhiges_gebiet"] = {"name": rg.get("NAME") or "Ruhiges Gebiet", "stadt": "Bochum"}
    return out
