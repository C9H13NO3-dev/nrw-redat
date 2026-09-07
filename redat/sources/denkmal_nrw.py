"""Denkmalschutz statewide — INSPIRE Denkmal WFS des Landes (IT.NRW), used outside the RVR area.

Service: https://www.wfs.nrw.de/wfs/wfs_nw_inspire-denkmal (WFS 2.0, GML 3.2 only — `outputFormat=json` is
rejected). The capabilities advertise EPSG:4258 but the geometries and the only working BBOX filter are
EPSG:25832 (`BBOX=xmin,ymin,xmax,ymax,urn:ogc:def:crs:EPSG::25832`; a WGS84 bbox silently matches nothing —
verified 2026-09-07). Typenames `ps:ProtectedSites_Cultural_{Point,Multipoint,Line,Surface}` (Bau-/bewegliche
Denkmäler, Denkmalbereiche) and `ps:ProtectedSites_Archaeological_{…}` (Bodendenkmäler). Elements per member:
`ps:nummer` (`DE_<AGS>_<A|B|C|D>_<nr>`, the RVR id scheme), `ps:sitename`, `ps:designation`,
`ps:legalfoundationdate`, geometry under `ps:SHAPE`. Municipalities deliver voluntarily: Bonn is complete, Essen
ships surfaces only, Köln nothing — hence the `hinweis`. No links, no municipality name → `link`/`city`/`authority`
are None.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import httpx
from shapely.geometry import LineString, MultiLineString, MultiPoint, MultiPolygon, Point, Polygon
from shapely.geometry.base import BaseGeometry

from redat.http import headers
from redat.sources import denkmal as _dk

WFS_URL = "https://www.wfs.nrw.de/wfs/wfs_nw_inspire-denkmal"
CULTURAL = tuple(f"ps:ProtectedSites_Cultural_{g}" for g in ("Surface", "Point", "Multipoint", "Line"))
ARCHAEO = tuple(f"ps:ProtectedSites_Archaeological_{g}" for g in ("Surface", "Point", "Multipoint", "Line"))
HINWEIS = ("Landesweiter INSPIRE-Dienst (IT.NRW); die Kommunen liefern ihre Denkmallisten freiwillig — "
           "fehlende Einträge bedeuten nicht „kein Denkmal“. Verbindlich ist die Denkmalliste der Stadt/Gemeinde.")
_NS = {"wfs": "http://www.opengis.net/wfs/2.0", "gml": "http://www.opengis.net/gml/3.2", "ps": "http://inspire.ec.europa.eu/schemas/ps/4.0"}
_TIMEOUT_S = 15.0
_WORKERS = 8


def _wfs_gml(typename: str, bbox: tuple[float, float, float, float], count: int = 500) -> str:
    """GetFeature GML for one typename inside the EPSG:25832 bbox — the HTTP/monkeypatch point."""
    xmin, ymin, xmax, ymax = bbox
    params = {"SERVICE": "WFS", "VERSION": "2.0.0", "REQUEST": "GetFeature", "TYPENAMES": typename, "COUNT": count,
              "BBOX": f"{xmin:.1f},{ymin:.1f},{xmax:.1f},{ymax:.1f},urn:ogc:def:crs:EPSG::25832"}
    resp = httpx.get(WFS_URL, params=params, timeout=_TIMEOUT_S, headers=headers())
    resp.raise_for_status()
    return resp.text


def _coords(text: Optional[str]) -> list[tuple[float, float]]:
    nums = [float(v) for v in (text or "").split()]
    return [(nums[i], nums[i + 1]) for i in range(0, len(nums) - 1, 2)]


def _polygon(poly_el) -> Optional[Polygon]:
    ext = poly_el.find("gml:exterior/gml:LinearRing/gml:posList", _NS)
    ring = _coords(ext.text if ext is not None else None)
    if len(ring) < 4:
        return None
    holes = [_coords(h.text) for h in poly_el.findall("gml:interior/gml:LinearRing/gml:posList", _NS)]
    return Polygon(ring, [h for h in holes if len(h) >= 4])


def _geom(shape_el) -> Optional[BaseGeometry]:
    polys = [p for p in (_polygon(el) for el in shape_el.iter(f"{{{_NS['gml']}}}Polygon")) if p is not None]
    if polys:
        return polys[0] if len(polys) == 1 else MultiPolygon(polys)
    lines = [LineString(c) for c in (_coords(el.text) for el in shape_el.iter(f"{{{_NS['gml']}}}posList")) if len(c) >= 2]
    if lines:
        return lines[0] if len(lines) == 1 else MultiLineString(lines)
    pts = [Point(c[0]) for c in (_coords(el.text) for el in shape_el.iter(f"{{{_NS['gml']}}}pos")) if c]
    if pts:
        return pts[0] if len(pts) == 1 else MultiPoint(pts)
    return None


def parse_members(gml_text: str) -> list[dict]:
    """Every wfs:member with a usable geometry → {id, name, designation, date, geom (EPSG:25832)}.

    The feature namespace is taken from each member's own tag: the capabilities declare
    `http://inspire.ec.europa.eu/schemas/ps/4.0`, but GetFeature responses bind `ps` to the service URL
    (`https://www.wfs.nrw.de/wfs/wfs_nw_inspire-denkmal`) — verified 2026-09-07, a fixed namespace matched nothing.
    """
    root = ET.fromstring(gml_text)
    out = []
    for member in root.findall("wfs:member", _NS):
        feat = next(iter(member), None)
        if feat is None:
            continue
        ns = feat.tag[1:].split("}")[0] if feat.tag.startswith("{") else ""

        def txt(tag: str) -> str:
            el = feat.find(f"{{{ns}}}{tag}" if ns else tag)
            return (el.text or "").strip() if el is not None else ""
        shape_el = feat.find(f"{{{ns}}}SHAPE" if ns else "SHAPE")
        geom = _geom(shape_el) if shape_el is not None else None
        if geom is None or geom.is_empty:
            continue
        out.append({"id": txt("nummer") or txt("id_localid"), "name": txt("sitename"), "designation": txt("designation"),
                    "date": txt("legalfoundationdate")[:10], "geom": geom})
    return out


def _item(f: dict, point_m: Point, archaeological: bool) -> Optional[dict]:
    geom = f["geom"]
    is_area = geom.geom_type in ("Polygon", "MultiPolygon")
    dist = 0.0 if is_area and geom.contains(point_m) else geom.distance(point_m)
    if dist > _dk.RADIUS_M:
        return None
    on_site = dist == 0.0 if is_area else dist <= _dk._POINT_HIT_M
    m = _dk._ID_RE.match(f["id"])
    kind = "B" if archaeological else (m.group(2) if m else "A")
    date = f["date"]
    return {
        "id": m.group(1) if m else f["id"] or f["name"] or "?",
        "name": f["name"] or _dk.KIND_LABELS[kind],
        "kind": kind, "kind_label": _dk.KIND_LABELS[kind],
        "scope": "gebiet" if kind == "D" else "objekt",
        "city": None,
        "listed_since": date if re.match(r"\d{4}-\d{2}-\d{2}", date) else None,
        "distance_m": round(dist, 1), "on_site": on_site,
        "link": None,
        "_polygon": is_area,
    }


def get_denkmal_nrw(lat: float, lon: float) -> dict:
    """Same dict as denkmal.get_denkmal, from the state WFS; all eight typenames are queried concurrently."""
    bbox = _dk._bbox_25832(lat, lon, _dk.RADIUS_M)
    point_m = Point(_dk._TO_25832.transform(lon, lat))
    typenames = CULTURAL + ARCHAEO
    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        texts = list(pool.map(lambda tn: _wfs_gml(tn, bbox), typenames))
    by_id: dict[str, dict] = {}
    for typename, text in zip(typenames, texts):
        for f in parse_members(text):
            it = _item(f, point_m, typename in ARCHAEO)
            if it is None:
                continue
            prev = by_id.get(it["id"])
            if prev is None or (not prev["_polygon"] and it["_polygon"]):
                by_id[it["id"]] = it
    items = sorted(by_id.values(), key=lambda i: (not i["on_site"], i["distance_m"], i["name"]))
    counts = {k: 0 for k in _dk.KIND_LABELS}
    for i in items:
        counts[i["kind"]] += 1
        i.pop("_polygon")
    rating, color = _dk._rate(items)
    return {
        "radius_m": _dk.RADIUS_M, "items": items[:_dk._MAX_ITEMS], "counts": counts,
        "on_site": [i for i in items if i["on_site"]], "authority": None,
        "rating": rating, "rating_color": color, "source": "nrw", "hinweis": HINWEIS,
    }
