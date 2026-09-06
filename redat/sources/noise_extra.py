"""Fluglärm and Ruhige Gebiete — what the state Umgebungslärm map does not show.

Sources (ArcGIS REST point queries, verified 2026-09-06):
- Essen Lärmkarte https://geo.essen.de/arcgis/rest/services/essen/Laermkarte_aktuell/MapServer: layer 5 Flugverkehr
  DUS (L_DEN; two polygons, 20 km² in Kettwig/Werden, classes Lden5559/Lden6064), 11 Flugverkehr DUS (L_night),
  4 Flugverkehr EMH (Essen/Mülheim, L_DEN). Fields CATEGORY, PEGEL, TEXT ("ab 55 bis 59 dB(A)").
- Ruhige Gebiete (§ 47d BImSchG, Lärmaktionsplan): Essen .../Ruhige_Gebiete/MapServer/26 (NAME, BESCHREIBU),
  Bochum https://geoservicekkm.bochum.de/arcgis/rest/services/maponline/Laermkartierung_Stufe4/MapServer/20
  (NAME, ART, BEZIRK; the server rejects resultRecordCount — never send it).

ESSEN_BBOX and BOCHUM_BBOX overlap on lon 7.10–7.14 / lat 51.40–51.53 (all of
Bochum-Wattenscheid sits in the strip): a point there is queried against *both*
cities' layer sets rather than picking one by an if/elif, or a genuine Ruhiges
Gebiet on the Bochum side of the overlap would be silently missed.

Every layer selected for a point is queried concurrently (one ThreadPoolExecutor
future per layer, `_TIMEOUT_S = 8`) so the worst case across up to four Essen
layers plus one Bochum layer stays close to a single round-trip, not their sum —
chaining them sequentially could reach ~45 s against the noise card's 20 s
section budget and get the whole card (including the successful state
Umgebungslärm data) discarded by `run_section()`'s timeout.

flug precedence: a DUS-day feature present → DUS (+ DUS-night if present), EMH
is ignored even if it also has a feature. Otherwise, an EMH-day feature present
→ EMH. Otherwise `flug` is None. Important: a DUS-day *failure* (HTTP/parse
error — recorded in `errors["flug_dus_day"]`, distinct from "no feature") also
leaves `flug` None and does **not** fall back to EMH: an EMH hit reported while
DUS-day's own status is unknown would misreport "kein Fluglärm" by omission in
the (unverified) case DUS-day would also have hit.

ruhiges_gebiet: the first feature among the queried Ruhig layers, Essen before
Bochum (both may be queried in the overlap strip; Essen wins if both hit).

Every layer is isolated (`errors[<key>]`); `_query` is the HTTP/monkeypatch point.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
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
_TIMEOUT_S = 8

# url -> (outFields, error key)
_LAYERS = {
    ESSEN_FLUG_DUS_DAY: ("CATEGORY,PEGEL,TEXT", "flug_dus_day"),
    ESSEN_FLUG_DUS_NIGHT: ("CATEGORY,PEGEL,TEXT", "flug_dus_night"),
    ESSEN_FLUG_EMH_DAY: ("CATEGORY,PEGEL,TEXT", "flug_emh_day"),
    ESSEN_RUHIG: ("NAME,BESCHREIBU", "ruhig_essen"),
    BOCHUM_RUHIG: ("NAME,ART,BEZIRK", "ruhig_bochum"),
}


def _in(bbox, lat, lon) -> bool:
    lon_min, lat_min, lon_max, lat_max = bbox
    return lon_min <= lon <= lon_max and lat_min <= lat <= lat_max


def _query(url: str, lat: float, lon: float, out_fields: str) -> dict:
    params = {"f": "json", "where": "1=1", "geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint", "inSR": 4326,
              "spatialRel": "esriSpatialRelIntersects", "outFields": out_fields, "returnGeometry": "false"}
    resp = httpx.get(url, params=params, timeout=_TIMEOUT_S, headers=headers())
    resp.raise_for_status()
    return resp.json()


def _first_feature(url: str, lat: float, lon: float) -> Optional[dict]:
    out_fields, _key = _LAYERS[url]
    feats = _query(url, lat, lon, out_fields).get("features") or []
    return (feats[0].get("attributes") or {}) if feats else None


def _layers_for(lat: float, lon: float) -> list[str]:
    urls: list[str] = []
    if _in(ESSEN_BBOX, lat, lon):
        urls += [ESSEN_FLUG_DUS_DAY, ESSEN_FLUG_DUS_NIGHT, ESSEN_FLUG_EMH_DAY, ESSEN_RUHIG]
    if _in(BOCHUM_BBOX, lat, lon):
        urls.append(BOCHUM_RUHIG)
    return urls


def get_noise_extra(lat: float, lon: float) -> dict:
    out: dict = {"flug": None, "ruhiges_gebiet": None, "errors": {}}
    urls = _layers_for(lat, lon)
    if not urls:
        return out

    results: dict[str, Optional[dict]] = {}
    with ThreadPoolExecutor(max_workers=len(urls), thread_name_prefix="noise-extra-layer") as pool:
        futures = {url: pool.submit(_first_feature, url, lat, lon) for url in urls}
        for url, fut in futures.items():
            _out_fields, key = _LAYERS[url]
            try:
                results[url] = fut.result()
            except Exception as exc:  # noqa: BLE001
                logger.warning("noise_extra %s: %s", key, exc)
                out["errors"][key] = str(exc)
                results[url] = None

    dus_day_errored = "flug_dus_day" in out["errors"]
    dus = results.get(ESSEN_FLUG_DUS_DAY)
    if dus:
        night = results.get(ESSEN_FLUG_DUS_NIGHT)
        out["flug"] = {"airport": "DUS", "day": dus.get("TEXT"), "night": night.get("TEXT") if night else None}
    elif not dus_day_errored:
        emh = results.get(ESSEN_FLUG_EMH_DAY)
        if emh:
            out["flug"] = {"airport": "EMH", "day": emh.get("TEXT"), "night": None}

    for url in (ESSEN_RUHIG, BOCHUM_RUHIG):
        rg = results.get(url)
        if rg:
            stadt = "Essen" if url == ESSEN_RUHIG else "Bochum"
            name = (rg.get("NAME") or rg.get("BESCHREIBU") or "Ruhiges Gebiet") if url == ESSEN_RUHIG else (rg.get("NAME") or "Ruhiges Gebiet")
            out["ruhiges_gebiet"] = {"name": name, "stadt": stadt}
            break

    return out
