"""Flurstück & Gebäude — ALKIS (vereinfacht) from the Geobasis NRW WFS.

Source: https://www.wfs.nrw.de/geobasis/wfs_nw_alkis_vereinfacht (WFS 2.0.0, dl-de/zero-2-0), feature
types `ave:Flurstueck`, `ave:GebaeudeBauwerk`, `ave:Nutzung`. The service sits behind an "OGC Proxy"
that rejects OUTPUTFORMAT=json, CQL_FILTER and SRSNAME (verified 2026-09-05) — the only request that
works is TYPENAMES + BBOX in EPSG:25832, answered as GML 3.2. Geometry is
<geometrie><gml:MultiSurface><gml:surfaceMember><gml:Polygon>… with posList "x y x y" in EPSG:25832.

Properties used — Flurstueck: idflurst, flstkennz ("05314403900040______", 14 significant chars),
gemarkung, gemaschl, flur, flstnrzae (+ flstnrnen), gemeinde, aktualit ("2026-02-17Z"), flaeche (m²),
lagebeztxt ("Herthastr. 4"), tntxt ("Wohnbaufläche;538" — `|`-separated entries of "Nutzung;m²").
GebaeudeBauwerk: funktion ("Wohngebäude"), lagebeztxt. Nutzung: nutzart.

Lookup: the parcel that contains the point, else the nearest within _SNAP_M (geocodes land on the
street edge). Buildings are fetched with the parcel bounds; one is "on the parcel" when more than
_ON_PARCEL_SHARE of its footprint lies inside. `_wfs_gml` is the single HTTP call and monkeypatch point.
"""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from typing import Optional

import httpx
from pyproj import Transformer
from shapely.geometry import MultiPolygon, Point, Polygon
from shapely.geometry.base import BaseGeometry

from redat.http import headers

logger = logging.getLogger(__name__)

ALKIS_WFS_URL = "https://www.wfs.nrw.de/geobasis/wfs_nw_alkis_vereinfacht"
_NS = {
    "ave": "http://repository.gdi-de.org/schemas/adv/produkt/alkis-vereinfacht/2.0",
    "gml": "http://www.opengis.net/gml/3.2",
    "wfs": "http://www.opengis.net/wfs/2.0",
}
_TO_25832 = Transformer.from_crs("EPSG:4326", "EPSG:25832", always_xy=True)
_TIMEOUT_S = 25
_POINT_BUFFER_M = 1.0    # half-width of the bbox around the geocoded point
_SNAP_M = 5.0            # accept a parcel this far from a street-edge geocode
_ON_PARCEL_SHARE = 0.5   # footprint share inside the parcel that makes a building "on" it


def _wfs_gml(typename: str, bbox: tuple[float, float, float, float], count: int = 50) -> str:
    """Raw GML 3.2 of one feature type inside the EPSG:25832 bbox — HTTP/monkeypatch point."""
    xmin, ymin, xmax, ymax = bbox
    params = {
        "SERVICE": "WFS", "VERSION": "2.0.0", "REQUEST": "GetFeature", "TYPENAMES": typename,
        "BBOX": f"{xmin},{ymin},{xmax},{ymax},urn:ogc:def:crs:EPSG::25832", "COUNT": count,
    }
    resp = httpx.get(ALKIS_WFS_URL, params=params, timeout=_TIMEOUT_S, headers=headers())
    resp.raise_for_status()
    return resp.text


def _ring(elem) -> list[tuple[float, float]]:
    pos = elem.findtext("gml:LinearRing/gml:posList", default="", namespaces=_NS).split()
    return [(float(pos[i]), float(pos[i + 1])) for i in range(0, len(pos) - 1, 2)]


def _geom_from_gml(geometrie) -> Optional[BaseGeometry]:
    """<geometrie> holding a MultiSurface/Polygon (with holes) or a Point → shapely geometry (EPSG:25832)."""
    polys = []
    for poly in geometrie.iter(f"{{{_NS['gml']}}}Polygon"):
        ext = poly.find("gml:exterior", _NS)
        if ext is None:
            continue
        polys.append(Polygon(_ring(ext), [_ring(h) for h in poly.findall("gml:interior", _NS)]))
    if polys:
        return polys[0] if len(polys) == 1 else MultiPolygon(polys)
    pos = geometrie.findtext(".//gml:Point/gml:pos", default="", namespaces=_NS).split()
    return Point(float(pos[0]), float(pos[1])) if len(pos) >= 2 else None


def parse_members(gml_text: str) -> list[dict]:
    """Every wfs:member → {"props": {local tag: text}, "geom": shapely geometry | None}."""
    root = ET.fromstring(gml_text)
    out = []
    for member in root.findall("wfs:member", _NS):
        feat = next(iter(member), None)
        if feat is None:
            continue
        props, geom = {}, None
        for child in feat:
            tag = child.tag.split("}")[-1]
            if tag == "geometrie":
                geom = _geom_from_gml(child)
            elif len(child) == 0 and child.text is not None:
                props[tag] = child.text.strip()
        out.append({"props": props, "geom": geom})
    return out


def parse_tntxt(text: Optional[str]) -> list[dict]:
    """'Wohnbaufläche;380|Straßenverkehr;20' → [{"art": "Wohnbaufläche", "m2": 380}, …]."""
    out = []
    for part in (text or "").split("|"):
        art, _, m2 = part.partition(";")
        if not art.strip():
            continue
        try:
            m2_val: Optional[int] = int(round(float(m2.replace(",", "."))))
        except ValueError:
            m2_val = None
        out.append({"art": art.strip(), "m2": m2_val})
    return out


def _nummer(p: dict) -> str:
    zaehler, nenner = p.get("flstnrzae") or "", p.get("flstnrnen")
    return f"{zaehler}/{nenner}" if nenner else zaehler


def _pick_parcel(members: list[dict], point_m: Point) -> Optional[tuple[dict, float]]:
    best = None
    for m in members:
        g = m["geom"]
        if g is None:
            continue
        dist = 0.0 if g.contains(point_m) else g.distance(point_m)
        if dist <= _SNAP_M and (best is None or dist < best[1]):
            best = (m, dist)
    return best


def get_flurstueck(lat: float, lon: float) -> Optional[dict]:
    """Parcel at (lat, lon) with its buildings, or None when no parcel lies within _SNAP_M (outside NRW)."""
    x, y = _TO_25832.transform(lon, lat)
    point_m = Point(x, y)
    bbox = (x - _POINT_BUFFER_M, y - _POINT_BUFFER_M, x + _POINT_BUFFER_M, y + _POINT_BUFFER_M)
    picked = _pick_parcel(parse_members(_wfs_gml("ave:Flurstueck", bbox)), point_m)
    if picked is None:
        return None
    parcel, dist = picked
    p, geom = parcel["props"], parcel["geom"]
    flaeche = float(p["flaeche"]) if p.get("flaeche") else round(geom.area, 1)

    buildings, on_parcel_area = [], 0.0
    for b in parse_members(_wfs_gml("ave:GebaeudeBauwerk", geom.bounds)):
        bg = b["geom"]
        if bg is None or bg.area == 0:
            continue
        inside = bg.intersection(geom).area
        if inside < 1.0:
            continue
        on = inside / bg.area > _ON_PARCEL_SHARE
        if on:
            on_parcel_area += bg.area
        buildings.append({"funktion": b["props"].get("funktion") or "Gebäude", "lage": b["props"].get("lagebeztxt") or None,
                          "grundflaeche_m2": round(bg.area, 1), "on_parcel": on})
    buildings.sort(key=lambda b: (not b["on_parcel"], -b["grundflaeche_m2"]))

    nutzung_pt = None
    for n in parse_members(_wfs_gml("ave:Nutzung", bbox)):
        if n["geom"] is not None and n["geom"].contains(point_m):
            nutzung_pt = n["props"].get("nutzart") or None
            break

    flur = p.get("flur") or ""
    return {
        "flurstueck": {
            "id": p.get("idflurst"), "kennzeichen": (p.get("flstkennz") or "").replace("_", ""),
            "gemarkung": p.get("gemarkung"), "gemarkung_nr": p.get("gemaschl"),
            "flur": int(flur) if flur.isdigit() else (flur or None), "nummer": _nummer(p),
            "flaeche_m2": flaeche, "lage": p.get("lagebeztxt") or None, "gemeinde": p.get("gemeinde"),
            "stand": (p.get("aktualit") or "").rstrip("Z") or None, "nutzung": parse_tntxt(p.get("tntxt")),
            "distance_m": round(dist, 1),
        },
        "gebaeude": buildings,
        "grundflaeche_m2": round(on_parcel_area, 1),
        "ueberbauung_pct": round(100 * on_parcel_area / flaeche, 1) if flaeche else None,
        "nutzung_am_punkt": nutzung_pt,
    }
