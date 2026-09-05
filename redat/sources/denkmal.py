"""Denkmalschutz card — listed monuments on and around the plot.

Source: RVR Geoportal Ruhr, INSPIRE "Schutzgebiete" WFS 2.0
(https://geodaten.metropoleruhr.de/inspire/schutzgebiete/metropoleruhr), typenames
`ms:denkmal_polygon` (Essen: every monument as an outline; Bochum: Siedlungen and
Denkmalbereichssatzungen) and `ms:denkmal_point_unclustered` (Bochum: one point per
Baudenkmal, roughly the building centroid). DefaultCRS is EPSG:25832, so the BBOX is
built in UTM32; `outputFormat=geojson&srsName=EPSG:4326` returns WGS84 rings.

Properties used: `inspire_id` (`DE_<AGS>_<A|B|C|D>_<nr>[_x_y]` — A Baudenkmal,
B Bodendenkmal, C bewegliches Denkmal, D Denkmalbereich; Bochum appends the
coordinate, hence the dedupe on the first four parts), `bezeichnun`, `gemeinde`,
`kategorie` (1000 Bau-/bewegliches Denkmal, 2000 Siedlung/Denkmalbereich,
4000 Bodendenkmal), `datum`, `merkmale` (Essen: Denkmalliste .htm, Bochum: photo),
`denkmal_ei` (Bochum: Begründung .pdf). Coverage is the RVR Verbandsgebiet only.
"""
from __future__ import annotations

import logging
import re
import time
from collections import Counter
from typing import Optional

import httpx
from pyproj import Transformer
from shapely.geometry import Point, shape
from shapely.ops import transform as shp_transform

from redat.http import headers

logger = logging.getLogger(__name__)

RVR_WFS_URL = "https://geodaten.metropoleruhr.de/inspire/schutzgebiete/metropoleruhr"
RVR_TYPES = ("ms:denkmal_polygon", "ms:denkmal_point_unclustered")
RVR_BBOX = (6.35, 51.25, 7.85, 51.85)  # lon_min, lat_min, lon_max, lat_max — RVR Verbandsgebiet (coarse)
RADIUS_M = 300
_POINT_HIT_M = 25     # Bochum points are building centroids: this close means "this building"
_NEIGHBOUR_M = 50     # Umgebungsschutz distance
_MAX_ITEMS = 12
_RETRY_SLEEP_S = 1.0
_TIMEOUT_S = 25

KIND_LABELS = {"A": "Baudenkmal", "B": "Bodendenkmal", "C": "Bewegliches Denkmal", "D": "Denkmalbereich"}
_KATEGORIE_KIND = {"1000": "A", "2000": "D", "4000": "B"}
AUTHORITY = {
    "Essen": ("Untere Denkmalbehörde Essen", "https://www.essen.de/leben/planen_und_bauen/denkmalschutz.de.html"),
    "Bochum": ("Untere Denkmalbehörde Bochum", "https://www.bochum.de/Denkmalschutz"),
}

_TO_25832 = Transformer.from_crs("EPSG:4326", "EPSG:25832", always_xy=True)
_ID_RE = re.compile(r"^(DE_\d+_([ABCD])_\d+)")


def _bbox_25832(lat: float, lon: float, radius_m: float) -> tuple[float, float, float, float]:
    x, y = _TO_25832.transform(lon, lat)
    return (x - radius_m, y - radius_m, x + radius_m, y + radius_m)


def _wfs_features(typename: str, bbox: tuple[float, float, float, float]) -> list[dict]:
    """GeoJSON features (WGS84 geometry) of one typename inside the EPSG:25832 bbox — HTTP/monkeypatch point."""
    xmin, ymin, xmax, ymax = bbox
    params = {
        "SERVICE": "WFS", "VERSION": "2.0.0", "REQUEST": "GetFeature", "TYPENAMES": typename,
        "BBOX": f"{xmin},{ymin},{xmax},{ymax},urn:ogc:def:crs:EPSG::25832",
        "outputFormat": "geojson", "srsName": "EPSG:4326", "count": 5000,
    }
    # The RVR server occasionally answers a first request with a transient "400 Internal
    # Server Error" and then serves the identical request fine — one retry after a pause.
    for attempt in range(2):
        resp = httpx.get(RVR_WFS_URL, params=params, timeout=_TIMEOUT_S, headers=headers())
        if resp.status_code == 200:
            return resp.json().get("features", [])
        if attempt == 0:
            time.sleep(_RETRY_SLEEP_S)
    resp.raise_for_status()
    return []


def _http(v) -> Optional[str]:
    v = (v or "").strip()
    return v if v.startswith("http") else None


def _item(feat: dict, point_m: Point) -> Optional[dict]:
    p = feat.get("properties", {})
    geom = shp_transform(_TO_25832.transform, shape(feat["geometry"]))
    is_point = geom.geom_type == "Point"
    dist = geom.distance(point_m) if is_point or not geom.contains(point_m) else 0.0
    if dist > RADIUS_M:
        return None
    on_site = dist <= _POINT_HIT_M if is_point else dist == 0.0
    inspire = str(p.get("inspire_id") or "")
    m = _ID_RE.match(inspire)
    kategorie = str(p.get("kategorie") or "")
    kind = m.group(2) if m else _KATEGORIE_KIND.get(kategorie, "A")
    datum = str(p.get("datum") or "")[:10]
    return {
        "id": m.group(1) if m else inspire or p.get("bezeichnun") or "?",
        "name": p.get("bezeichnun") or KIND_LABELS[kind],
        "kind": kind, "kind_label": KIND_LABELS[kind],
        "scope": "gebiet" if kategorie == "2000" or kind == "D" else "objekt",
        "city": p.get("gemeinde") or None,
        "listed_since": datum if re.match(r"\d{4}-\d{2}-\d{2}", datum) else None,
        "distance_m": round(dist, 1), "on_site": on_site,
        "link": _http(p.get("denkmal_ei")) or _http(p.get("merkmale")),
        "_polygon": not is_point,
    }


def _rate(items: list[dict]) -> tuple[str, str]:
    on_site = [i for i in items if i["on_site"]]
    if any(i["kind"] in ("A", "C") and i["scope"] == "objekt" for i in on_site):
        return "Baudenkmal", "orange"
    if any(i["kind"] == "B" for i in on_site):
        return "Bodendenkmal", "orange"
    if on_site:
        return "Im Denkmalbereich", "yellow"
    if any(i["distance_m"] <= _NEIGHBOUR_M for i in items):
        return "Denkmal in unmittelbarer Nachbarschaft", "yellow"
    if items:
        return "Denkmäler in der Nähe", "green"
    return "Kein Denkmalschutz", "green"


def get_denkmal(lat: float, lon: float) -> Optional[dict]:
    """Monuments within RADIUS_M, or None outside the RVR area (no data there, not "none")."""
    lon_min, lat_min, lon_max, lat_max = RVR_BBOX
    if not (lon_min <= lon <= lon_max and lat_min <= lat <= lat_max):
        return None
    bbox = _bbox_25832(lat, lon, RADIUS_M)
    point_m = Point(_TO_25832.transform(lon, lat))
    by_id: dict[str, dict] = {}
    for typename in RVR_TYPES:  # polygons first → they win the dedupe
        for feat in _wfs_features(typename, bbox):
            it = _item(feat, point_m)
            if it is None:
                continue
            prev = by_id.get(it["id"])
            if prev is None or (not prev["_polygon"] and it["_polygon"]):
                by_id[it["id"]] = it
    items = sorted(by_id.values(), key=lambda i: (not i["on_site"], i["distance_m"], i["name"]))
    counts = {k: 0 for k in KIND_LABELS}
    for i in items:
        counts[i["kind"]] += 1
    cities = Counter(i["city"] for i in items if i["city"] in AUTHORITY)
    authority = None
    if cities:
        name, link = AUTHORITY[cities.most_common(1)[0][0]]
        authority = {"name": name, "link": link}
    for i in items:
        i.pop("_polygon")
    rating, color = _rate(items)
    return {
        "radius_m": RADIUS_M,
        "items": items[:_MAX_ITEMS],
        "counts": counts,
        "on_site": [i for i in items if i["on_site"]],
        "authority": authority,
        "rating": rating, "rating_color": color,
    }
