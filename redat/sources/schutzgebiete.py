"""Schutzgebiete — nature/landscape reserves (LINFOS) and water-protection zones (WSG) around a point.

Sources
- LANUV LINFOS WFS 2.0, https://www.wfs.nrw.de/umwelt/linfos (dl-de/by-2-0):
  `nsg_polygon` Naturschutzgebiete, `lsg_polygon` Landschaftsschutzgebiete,
  `ffh_polygon` FFH-Gebiete, `vsg_polygon` Vogelschutzgebiete, `np_polygon`
  Naturparke, `gbt_polygon` gesetzlich geschützte Biotope. Properties used:
  `kennung`, `gebietsname`, `schutz_agg` ("NSG, bestehend"), `inkraft`,
  `hyperlink`. The BBOX filter must be in **EPSG:25832** — a WGS84 bbox
  silently returns nothing (verified 2026-09-04); `OUTPUTFORMAT=GEOJSON`
  returns WGS84 geometry.
- Wasserschutzgebiete NRW WMS, https://www.wms.nrw.de/umwelt/wasser/wsg, layers
  1–4 = Heilquellen geplant/festgesetzt, Trinkwasser geplant/festgesetzt, read
  by GetFeatureInfo (esri featureinfo XML: `zone_roemisch`, `name`, `status`
  P/F, `gueltig_seit`, `datum_verordnung`, `flaeche_km2`).

Geometry: every feature is transformed to EPSG:25832 so shapely's `contains`
and `distance` are in metres; only areas within `RADIUS_M` are reported.
"""
from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import httpx
from pyproj import Transformer
from shapely.geometry import Point, shape
from shapely.ops import transform as shp_transform

from redat.http import headers

logger = logging.getLogger(__name__)

LINFOS_WFS_URL = "https://www.wfs.nrw.de/umwelt/linfos"
WSG_WMS_URL = "https://www.wms.nrw.de/umwelt/wasser/wsg"
RADIUS_M = 500
_MAX_PER_KIND = 5
_TIMEOUT_S = 20

# (kind, WFS type name, label) — the strict ones first so the rating order below reads naturally.
LINFOS_TYPES = [
    ("nsg", "wfs_linfos:nsg_polygon", "Naturschutzgebiet"),
    ("ffh", "wfs_linfos:ffh_polygon", "FFH-Gebiet"),
    ("vsg", "wfs_linfos:vsg_polygon", "Vogelschutzgebiet"),
    ("gbt", "wfs_linfos:gbt_polygon", "Geschützter Biotop"),
    ("lsg", "wfs_linfos:lsg_polygon", "Landschaftsschutzgebiet"),
    ("np", "wfs_linfos:np_polygon", "Naturpark"),
]
_STRICT = {"nsg", "ffh", "vsg", "gbt"}     # inside → red
_LANDSCAPE = {"lsg", "np"}                 # inside → orange

_TO_25832 = Transformer.from_crs("EPSG:4326", "EPSG:25832", always_xy=True)
_NS = {"w": "http://www.esri.com/wms"}


def _bbox_25832(lat: float, lon: float, radius_m: float) -> tuple[float, float, float, float]:
    x, y = _TO_25832.transform(lon, lat)
    return x - radius_m, y - radius_m, x + radius_m, y + radius_m


def _wfs_features(typename: str, bbox: tuple[float, float, float, float]) -> list[dict]:
    """GeoJSON features of one LINFOS type inside the (EPSG:25832) bbox — HTTP/monkeypatch point."""
    xmin, ymin, xmax, ymax = bbox
    params = {
        "SERVICE": "WFS", "VERSION": "2.0.0", "REQUEST": "GetFeature", "TYPENAMES": typename,
        "BBOX": f"{xmin},{ymin},{xmax},{ymax},urn:ogc:def:crs:EPSG::25832", "OUTPUTFORMAT": "GEOJSON",
    }
    resp = httpx.get(LINFOS_WFS_URL, params=params, timeout=_TIMEOUT_S, headers=headers())
    resp.raise_for_status()
    return resp.json().get("features", [])


def _wsg_featureinfo(lat: float, lon: float) -> str:
    """Raw esri featureinfo XML for the WSG layers at the point — HTTP/monkeypatch point."""
    d = 0.001
    params = {
        "SERVICE": "WMS", "VERSION": "1.3.0", "REQUEST": "GetFeatureInfo", "LAYERS": "1,2,3,4",
        "QUERY_LAYERS": "1,2,3,4", "STYLES": "", "CRS": "EPSG:4326",
        "BBOX": f"{lat - d},{lon - d},{lat + d},{lon + d}", "WIDTH": 101, "HEIGHT": 101, "I": 50, "J": 50,
        "FEATURE_COUNT": 10, "INFO_FORMAT": "application/vnd.esri.wms_featureinfo_xml",
    }
    resp = httpx.get(WSG_WMS_URL, params=params, timeout=_TIMEOUT_S, headers=headers())
    resp.raise_for_status()
    return resp.text


def _null(v: Optional[str]) -> Optional[str]:
    v = (v or "").strip()
    return None if v in ("", "Null", "00:00:00") else v


def parse_wsg(xml_text: str) -> list[dict]:
    """`FeatureInfoCollection` blocks → one dict per zone the point lies in."""
    root = ET.fromstring(xml_text)
    out = []
    for coll in root.findall("w:FeatureInfoCollection", _NS):
        layer = coll.get("layername", "")
        kind = "Heilquellen" if "Heilquellen" in layer else "Trinkwasser"
        for fi in coll.findall("w:FeatureInfo", _NS):
            f = {}
            for field in fi.findall("w:Field", _NS):
                name = field.findtext("w:FieldName", default="", namespaces=_NS)
                f[name] = field.findtext("w:FieldValue", default="", namespaces=_NS)
            area = _null(f.get("flaeche_km2"))
            out.append({
                "name": _null(f.get("name")), "zone": _null(f.get("zone_roemisch")) or _null(f.get("zone_")),
                "status": "festgesetzt" if f.get("status") == "F" else "geplant", "kind": kind,
                "since": _null(f.get("gueltig_seit")), "ordinance": _null(f.get("datum_verordnung")),
                "area_km2": float(area.replace(",", ".")) if area else None,
            })
    return out


def _zone_level(zone: Optional[str]) -> int:
    """'I' → 1, 'II' → 2, 'III A' / 'III B' → 3; unknown → 3."""
    m = re.match(r"\s*(I{1,3})\b", zone or "")
    return len(m.group(1)) if m else 3


def _areas_for(kind: str, typename: str, label: str, bbox, point_m: Point) -> list[dict]:
    areas = []
    for feat in _wfs_features(typename, bbox):
        geom = shp_transform(_TO_25832.transform, shape(feat["geometry"]))
        p = feat.get("properties", {})
        dist = 0.0 if geom.contains(point_m) else geom.distance(point_m)
        if dist > RADIUS_M:
            continue
        since = p.get("inkraft")
        areas.append({
            "kind": kind, "kind_label": label, "name": p.get("gebietsname") or p.get("kennung") or label,
            "kennung": p.get("kennung"), "status": p.get("schutz_agg") or None,
            "distance_m": round(dist, 1), "inside": dist == 0.0, "link": p.get("hyperlink") or None,
            "since": int(since) if isinstance(since, (int, float)) and since else None,
        })
    return areas


def _rate(areas: list[dict], wsg: list[dict]) -> tuple[str, str]:
    inside = {a["kind"] for a in areas if a["inside"]}
    if inside & _STRICT:
        return "Im Naturschutzgebiet", "red"
    if wsg:
        level = min(_zone_level(z["zone"]) for z in wsg)
        if level <= 2:
            return f"Wasserschutzgebiet Zone {'I' * level}", "red"
        if inside & _LANDSCAPE:
            return "Im Landschaftsschutzgebiet", "orange"
        return "Wasserschutzgebiet Zone III", "orange"
    if inside & _LANDSCAPE:
        return "Im Landschaftsschutzgebiet", "orange"
    if areas:
        return "Schutzgebiet in der Nähe", "yellow"
    return "Keine Schutzgebiete", "green"


def get_schutzgebiete(lat: float, lon: float) -> dict:
    """Reserves within RADIUS_M (inside first, then by distance) plus the WSG zones at the point."""
    bbox = _bbox_25832(lat, lon, RADIUS_M)
    point_m = Point(_TO_25832.transform(lon, lat))
    areas, errors = [], {}
    with ThreadPoolExecutor(max_workers=len(LINFOS_TYPES) + 1) as ex:
        wsg_fut = ex.submit(_wsg_featureinfo, lat, lon)
        futs = [(kind, ex.submit(_areas_for, kind, tn, label, bbox, point_m)) for kind, tn, label in LINFOS_TYPES]
        for kind, fut in futs:
            try:
                areas.extend(fut.result())
            except Exception as e:  # noqa: BLE001 — one type must not blank the card
                logger.warning("LINFOS %s failed: %s", kind, e)
                errors[kind] = str(e)
        try:
            wsg = parse_wsg(wsg_fut.result())
        except Exception as e:  # noqa: BLE001
            logger.warning("WSG GetFeatureInfo failed: %s", e)
            errors["wsg"] = str(e)
            wsg = []
    if len([k for k in errors if k != "wsg"]) == len(LINFOS_TYPES):
        raise RuntimeError(f"LINFOS WFS nicht erreichbar: {errors[LINFOS_TYPES[0][0]]}")
    areas.sort(key=lambda a: (not a["inside"], a["distance_m"], a["kind"]))
    rating, color = _rate(areas, wsg)
    counts = {}
    for a in areas:
        counts[a["kind"]] = counts.get(a["kind"], 0) + 1
    shown, seen = [], {}
    for a in areas:  # protected biotopes come in dozens — list at most _MAX_PER_KIND per kind, keep the totals
        seen[a["kind"]] = seen.get(a["kind"], 0) + 1
        if seen[a["kind"]] <= _MAX_PER_KIND:
            shown.append(a)
    return {"radius_m": RADIUS_M, "areas": shown, "counts": counts, "wsg": wsg,
            "rating": rating, "rating_color": color, "errors": errors}
