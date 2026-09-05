"""Hochspannung, Leitungen & Industrie card — technical infrastructure around the plot.

Sources:
- OpenStreetMap via Overpass (https://overpass-api.de, mirror overpass.private.coffee):
  `power=line|minor_line|cable` (with `voltage`, e.g. "380000;220000;110000"),
  `power=substation`, `generator:source=wind`, communication masts only
  (`man_made=mast|tower` + `tower:type=communication`, or `man_made=communications_tower`
  — church bell towers and lighting masts are not "Sendemasten"), `man_made=pipeline`
  (with `substance`), `landuse=industrial`. Overpass wants a `User-Agent` (406 without),
  answers bursts with 429 and stalls under load — `_overpass` uses a short per-request
  timeout, retries the primary once after a pause, then tries the mirror. Distances are
  shapely metres in EPSG:25832 to the nearest edge; OSM completeness varies.
- EEA Industrial Emissions Portal (IED/E-PRTR) via discodata SQL
  (https://discodata.eea.europa.eu/sql), table `[IED].[latest].[SiteMap]` — one row
  per site and reporting year; the latest year per `InspireSiteId` is kept.

Störfallbetriebe (Seveso III): NRW publishes no geodata (checked open.nrw, GDI-DE,
RVR CSW, wms.nrw.de, both city ArcGIS servers; the EEA `seveso` field is empty for
NRW). The card states that instead of pretending — see SEVESO_NOTE.
"""
from __future__ import annotations

import logging
import math
import re
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import httpx
from pyproj import Transformer
from shapely.geometry import LineString, Point, Polygon

from redat.http import headers

logger = logging.getLogger(__name__)

OVERPASS_URLS = ("https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter")
DISCODATA_URL = "https://discodata.eea.europa.eu/sql"
R_LINES, R_SUBSTATION, R_WIND, R_MAST, R_PIPELINE, R_INDUSTRIAL, R_IED = 500, 500, 1500, 300, 300, 300, 2000
HV_MIN_V = 110_000
PIPELINE_HAZARD = {"gas", "oil", "hydrogen", "ethylene", "propylene", "oxygen", "chlorine", "ammonia", "fuel",
                   "petroleum", "natural_gas", "crude_oil", "lpg", "kerosene"}
SEVESO_NOTE = ("NRW veröffentlicht keine Geodaten zu Störfallbetrieben (Seveso III). "
               "Auskunft: Bezirksregierung Düsseldorf (Essen) bzw. Arnsberg (Bochum).")
_MAX_IED = 10
_IED_STALE_YEARS = 5  # latest report older than this → listed as "evtl. stillgelegt", not rated
_TIMEOUT_S = 18
_RETRY_SLEEP_S = 2

_TO_25832 = Transformer.from_crs("EPSG:4326", "EPSG:25832", always_xy=True)
_INT_RE = re.compile(r"\d+")


def _overpass(query: str) -> dict:
    """POST an Overpass QL query — HTTP/monkeypatch point.

    Attempt order: primary → (pause) → primary → mirror. A 429/5xx or a timeout/transport
    error moves on to the next attempt; any other status raises immediately. Worst case
    stays under the section timeout (3 × _TIMEOUT_S + _RETRY_SLEEP_S).
    """
    attempts = (OVERPASS_URLS[0], OVERPASS_URLS[0]) + tuple(OVERPASS_URLS[1:])
    last = None
    for i, url in enumerate(attempts):
        if i == 1:
            time.sleep(_RETRY_SLEEP_S)
        try:
            resp = httpx.post(url, data={"data": query}, headers=headers(), timeout=_TIMEOUT_S)
        except (httpx.TimeoutException, httpx.TransportError) as ex:
            last = f"{url} → {type(ex).__name__}"
            continue
        if resp.status_code == 200:
            return resp.json()
        last = f"{url} → HTTP {resp.status_code}"
        if resp.status_code in (429, 502, 503, 504):
            continue
        raise RuntimeError(f"Overpass: {last}: {getattr(resp, 'text', '')[:200]}")
    raise RuntimeError(f"Overpass nicht erreichbar ({last})")


def _discodata(sql: str) -> list[dict]:
    """Run one discodata SQL query — HTTP/monkeypatch point."""
    resp = httpx.get(DISCODATA_URL, params={"query": sql, "p": 1, "nrOfHits": 2000}, timeout=_TIMEOUT_S,
                     headers=headers())
    resp.raise_for_status()
    data = resp.json()
    if data.get("errors"):
        raise RuntimeError(f"discodata: {data['errors']}")
    return data.get("results", []) or []


def _parse_voltages(raw: Optional[str]) -> list[int]:
    """'380000;220000;110000' → [380, 220, 110] (kV); non-numeric parts dropped."""
    if not raw:
        return []
    return [int(m.group(0)) // 1000 for part in str(raw).split(";") for m in [_INT_RE.search(part)] if m]


def _query(lat: float, lon: float) -> str:
    return (
        f"[out:json][timeout:{_TIMEOUT_S - 2}];("
        f'way["power"~"^(line|minor_line|cable)$"](around:{R_LINES},{lat},{lon});'
        f'nwr["power"="substation"](around:{R_SUBSTATION},{lat},{lon});'
        f'nwr["generator:source"="wind"](around:{R_WIND},{lat},{lon});'
        f'nwr["man_made"~"^(mast|tower)$"]["tower:type"~"communication"](around:{R_MAST},{lat},{lon});'
        f'nwr["man_made"="communications_tower"](around:{R_MAST},{lat},{lon});'
        f'way["man_made"="pipeline"](around:{R_PIPELINE},{lat},{lon});'
        f'way["landuse"="industrial"](around:{R_INDUSTRIAL},{lat},{lon});'
        ");out tags geom;"
    )


def _geom(el: dict):
    """Shapely geometry in EPSG:25832 for an Overpass element (`out geom`), or None."""
    kind = el.get("type")
    if kind == "node":
        return Point(_TO_25832.transform(el["lon"], el["lat"])) if "lat" in el else None
    if kind == "way":
        pts = [_TO_25832.transform(g["lon"], g["lat"]) for g in el.get("geometry") or [] if "lat" in g]
        if len(pts) < 2:
            return None  # degenerate / geometry missing
        if len(pts) >= 4 and pts[0] == pts[-1]:
            return Polygon(pts)
        return LineString(pts)
    # relation: `out geom` gives bounds; fall back to a centre point
    b = el.get("bounds") or el.get("center")
    if b and "minlat" in b:
        return Point(_TO_25832.transform((b["minlon"] + b["maxlon"]) / 2, (b["minlat"] + b["maxlat"]) / 2))
    if b and "lat" in b:
        return Point(_TO_25832.transform(b["lon"], b["lat"]))
    return None


def _dist(geom, p: Point) -> float:
    if geom.geom_type == "Polygon" and geom.contains(p):
        return 0.0
    return round(geom.distance(p), 1)


def _osm_part(lat: float, lon: float) -> dict:
    p = Point(_TO_25832.transform(lon, lat))
    out = {"power_lines": [], "substations": [], "trafo_count": 0, "wind": [], "masts": [], "pipelines": [],
           "industrial_landuse_m": None}
    for el in _overpass(_query(lat, lon)).get("elements", []) or []:
        tags = el.get("tags") or {}
        geom = _geom(el)
        if geom is None:
            continue
        d = _dist(geom, p)
        power = tags.get("power")
        if power in ("line", "minor_line", "cable"):
            if d > R_LINES:
                continue
            volts = _parse_voltages(tags.get("voltage"))
            vmax = max(volts) if volts else None
            out["power_lines"].append({
                "name": tags.get("name"), "voltage_kv": vmax, "voltages": volts,
                "kind": "hochspannung" if vmax is not None and vmax * 1000 >= HV_MIN_V else "mittelspannung",
                "underground": power == "cable" or tags.get("location") == "underground", "distance_m": d})
        elif power == "substation":
            if d > R_SUBSTATION:
                continue
            volts = _parse_voltages(tags.get("voltage"))
            vmax = max(volts) if volts else None
            if vmax is not None and vmax * 1000 >= HV_MIN_V:
                out["substations"].append({"name": tags.get("name") or "Umspannwerk", "voltage_kv": vmax, "distance_m": d})
            else:
                out["trafo_count"] += 1
        elif tags.get("generator:source") == "wind":
            if d <= R_WIND:
                out["wind"].append({"name": tags.get("name"), "distance_m": d})
        elif tags.get("man_made") in ("mast", "tower", "communications_tower"):
            if d <= R_MAST:
                out["masts"].append({"name": tags.get("name"), "kind": "mast" if tags["man_made"] == "mast" else "tower",
                                     "distance_m": d})
        elif tags.get("man_made") == "pipeline":
            if d > R_PIPELINE:
                continue
            substance = tags.get("substance") or None
            out["pipelines"].append({"name": tags.get("name"), "substance": substance,
                                     "hazardous": substance in PIPELINE_HAZARD, "location": tags.get("location") or None,
                                     "distance_m": d})
        elif tags.get("landuse") == "industrial":
            if d <= R_INDUSTRIAL and (out["industrial_landuse_m"] is None or d < out["industrial_landuse_m"]):
                out["industrial_landuse_m"] = d
    for key in ("power_lines", "substations", "wind", "masts", "pipelines"):
        out[key].sort(key=lambda x: x["distance_m"])
    return out


def _haversine_m(lat1, lon1, lat2, lon2) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _ied_part(lat: float, lon: float) -> list[dict]:
    sql = ("SELECT InspireSiteId, siteName, cities, eea_activities, Site_reporting_year, x_4258, y_4258 "
           "FROM [IED].[latest].[SiteMap] WHERE countryCode='DE' "
           f"AND x_4258 BETWEEN {lon - 0.03:.4f} AND {lon + 0.03:.4f} "
           f"AND y_4258 BETWEEN {lat - 0.02:.4f} AND {lat + 0.02:.4f}")
    latest: dict[str, dict] = {}
    for row in _discodata(sql):
        sid = row.get("InspireSiteId") or row.get("siteName")
        year = int(row.get("Site_reporting_year") or 0)
        if sid not in latest or year > int(latest[sid].get("Site_reporting_year") or 0):
            latest[sid] = row
    sites = []
    for row in latest.values():
        try:
            slat, slon = float(row["y_4258"]), float(row["x_4258"])
        except (KeyError, TypeError, ValueError):
            continue
        d = round(_haversine_m(lat, lon, slat, slon), 1)
        if d > R_IED:
            continue
        sectors = []
        for s in str(row.get("eea_activities") or "").split(","):
            s = s.strip()
            if s and s not in sectors:
                sectors.append(s)
        year = int(row.get("Site_reporting_year") or 0) or None
        sites.append({"name": row.get("siteName"), "city": row.get("cities") or None, "sectors": sectors,
                      "year": year, "distance_m": d,
                      # the EEA table keeps legacy E-PRTR sites whose last report is 10+ years old
                      # (closed plants) — shown, but flagged and left out of the rating
                      "stale": year is None or year < datetime.now().year - _IED_STALE_YEARS})
    sites.sort(key=lambda s: (s["stale"], s["distance_m"]))
    return sites[:_MAX_IED]


def _rate(d: dict) -> tuple[str, str]:
    def nearest(items, **cond):
        return min((i["distance_m"] for i in items if all(i.get(k) == v for k, v in cond.items())), default=None)

    hv = nearest(d["power_lines"], kind="hochspannung", underground=False)
    sub = nearest(d["substations"])
    wind = nearest(d["wind"])
    mast = nearest(d["masts"])
    pipe = nearest(d["pipelines"], hazardous=True)
    ied = nearest(d["ied_sites"], stale=False)
    ind = d["industrial_landuse_m"]

    def within(v, m):
        return v is not None and v <= m

    if within(hv, 50) or within(wind, 500) or within(ied, 300):
        return "Belastung", "red"
    if (within(hv, 200) or within(sub, 200) or within(pipe, 50) or within(mast, 100) or within(wind, 1000)
            or within(ied, 1000) or ind == 0.0):
        return "Erhöht", "orange"
    if any(d[k] for k in ("power_lines", "substations", "wind", "masts", "pipelines")) \
            or ied is not None or ind is not None or d["trafo_count"]:
        return "Hinweise", "yellow"
    return "Unauffällig", "green"


def get_infrastruktur(lat: float, lon: float) -> dict:
    """Infrastructure inventory around the point — always rated (OSM coverage is global); raises only if both parts fail."""
    errors: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=2) as pool:
        osm_f = pool.submit(_osm_part, lat, lon)
        ied_f = pool.submit(_ied_part, lat, lon)
        try:
            osm = osm_f.result()
        except Exception as exc:  # noqa: BLE001
            logger.warning("infrastruktur osm failed: %s", exc)
            errors["osm"] = str(exc)
            osm = {"power_lines": [], "substations": [], "trafo_count": 0, "wind": [], "masts": [], "pipelines": [],
                   "industrial_landuse_m": None}
        try:
            ied = ied_f.result()
        except Exception as exc:  # noqa: BLE001
            logger.warning("infrastruktur ied failed: %s", exc)
            errors["ied"] = str(exc)
            ied = []
    if len(errors) == 2:
        raise RuntimeError(f"Overpass und EEA nicht erreichbar: {errors['osm']} / {errors['ied']}")
    d = {**osm, "ied_sites": ied, "seveso_note": SEVESO_NOTE, "errors": errors}
    d["rating"], d["rating_color"] = _rate(d)
    return d
