"""Energie — solar yield of the house's roof, ground-source heat-pump suitability, municipal heat plan.

Sources (all verified live 2026-09-04)
- LANUK *Solarkataster NRW* (ArcGIS MapServer, 2020 aerial survey): layer 9
  building outlines (`geb_id`, `name` = ALKIS id, `Shape_Area`), layer 8 PV
  roof segments (`himmel_kat`, `neigung`, `radabs` kWh/m²·a, `modanetto_int`
  module m², `kw` kWp, `str` kWh/a, `dachtyp`, `jahr`). A point query on the
  segments layer returns nothing (segments don't cover the whole roof), so we
  first pick the building — the one containing the point, else the *nearest*
  outline ≥ `_MIN_BUILDING_M2` within `_NEAR_M` (geocodes land on the street;
  "largest nearby" would sum a neighbouring apartment block) — and then ask
  for the segments the building polygon `Contains` (`Intersects` pulls in the
  neighbours' segments, `Within` returns none).
- GD NRW *Geothermie* WMS `https://www.wms.nrw.de/gd/GT`, one GetFeatureInfo
  over layers 63/64/65/66 (mean thermal conductivity class for 100/80/60/40 m
  probes, `klasse_wlf*` + `klassen_wertebereich` "2,5 - 2,9" W/(m·K)), 69
  (collector suitability `ewk_wert`), 17 (hydrologically sensitive area) and
  67 (increased groundwater flow). Only the esri featureinfo XML is served.
- *Kommunale Wärmeplanung*: Essen (adopted, target 2045) layer 73 with
  `GEBIETSEINTEILUNG`/`PREFERENCE_AREA`/`HAS_HEAT_GRID_2024|2045`, queried with
  a 30 m tolerance because the block polygons leave gaps; Bochum (draft) via
  `identify` over layers 0–6, lowest layer id wins.
- A Wasserschutzgebiet hit (via `redat.sources.schutzgebiete`) is surfaced as a
  caveat on the Erdwärme block: zones I/II generally prohibit probes, zone
  III needs a permit.
"""
from __future__ import annotations

import json
import logging
import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import httpx
from pyproj import Transformer
from shapely.geometry import Point, Polygon
from shapely.ops import transform as shp_transform

from redat.http import headers

logger = logging.getLogger(__name__)

SOLAR_URL = "https://arcgis.energieatlas.nrw.de/arcgis/rest/services/Solarkataster/25_09_04_EnergieatlasNRW_Solarkataster/MapServer"
SOLAR_BUILDINGS_LAYER, SOLAR_PV_LAYER = 9, 8
SOLAR_LINK = "https://www.energieatlas.nrw.de/site/karte_solarkataster"
GT_WMS_URL = "https://www.wms.nrw.de/gd/GT"
GT_PROBE_LAYERS = {"63": "100 m", "64": "80 m", "65": "60 m", "66": "40 m"}
GT_COLLECTOR_LAYER, GT_HYDRO_LAYER, GT_FLOW_LAYER = "69", "17", "67"
GT_LINK = "https://www.geothermie.nrw.de/"
ESSEN_KWP_URL = "https://geo.essen.de/arcgis/rest/services/essen/Kommunale_Waermeplanung/MapServer/73"
ESSEN_KWP_LINK = "https://www.essen.de/waermeplanung"
BOCHUM_KWP_URL = "https://geoservicekkm.bochum.de/arcgis/rest/services/maponline/KommunaleWaermeplanung/MapServer"
BOCHUM_KWP_LINK = BOCHUM_KWP_URL  # no stable city web page found (2026-09-04); the map service is the published source

_TIMEOUT_S = 20
_NEAR_M = 20
_MIN_BUILDING_M2 = 40
_MAX_SEGMENTS = 12
_HOUSEHOLD_KWH_A = 4000  # rough 3-person household electricity use, for the "≈ n Haushalte" line

_TO_25832 = Transformer.from_crs("EPSG:4326", "EPSG:25832", always_xy=True)
_NS = {"w": "http://www.esri.com/wms"}

# Essen GEBIETSEINTEILUNG → (category, colour); Bochum layer id → (category, colour)
_ESSEN_CATEGORIES = {
    "Wärmenetzausbaugebiet": ("fernwaerme_ausbau", "green"),
    "Prüfgebiet Wärmenetze": ("pruefgebiet_waermenetz", "yellow"),
    "Prüfgebiet Wasserstoff": ("pruefgebiet_wasserstoff", "yellow"),
    "Dezentral": ("dezentral", "gray"),
}
_BOCHUM_CATEGORIES = {
    0: ("fernwaerme_bestand", "green"), 1: ("fernwaerme_ausbau", "green"), 2: ("pruefgebiet_waermenetz", "yellow"),
    3: ("fernwaerme_bestand", "green"), 4: ("dezentral", "gray"), 5: ("sonstiges", "gray"), 6: ("sonstiges", "gray"),
}
_CATEGORY_COLORS = {"fernwaerme_bestand": "green", "fernwaerme_ausbau": "green", "pruefgebiet_waermenetz": "yellow",
                    "pruefgebiet_wasserstoff": "yellow", "dezentral": "gray", "sonstiges": "gray"}


# ---------------------------------------------------------------- HTTP points

def _arcgis_query(url: str, params: dict) -> dict:
    resp = httpx.get(f"{url}/query", params={**params, "f": "json"}, timeout=_TIMEOUT_S, headers=headers())
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"ArcGIS error: {data['error']}")
    return data


def _arcgis_identify(url: str, params: dict) -> dict:
    resp = httpx.get(f"{url}/identify", params={**params, "f": "json"}, timeout=_TIMEOUT_S, headers=headers())
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"ArcGIS error: {data['error']}")
    return data


def _gt_featureinfo(lat: float, lon: float) -> str:
    d = 0.001
    layers = ",".join([*GT_PROBE_LAYERS, GT_HYDRO_LAYER, GT_FLOW_LAYER, GT_COLLECTOR_LAYER])
    params = {
        "SERVICE": "WMS", "VERSION": "1.3.0", "REQUEST": "GetFeatureInfo", "LAYERS": layers, "QUERY_LAYERS": layers,
        "STYLES": "", "CRS": "EPSG:4326", "BBOX": f"{lat - d},{lon - d},{lat + d},{lon + d}",
        "WIDTH": 101, "HEIGHT": 101, "I": 50, "J": 50, "FEATURE_COUNT": 10,
        "INFO_FORMAT": "application/vnd.esri.wms_featureinfo_xml",
    }
    resp = httpx.get(GT_WMS_URL, params=params, timeout=_TIMEOUT_S, headers=headers())
    resp.raise_for_status()
    return resp.text


def _wsg_zones(lat: float, lon: float) -> list[dict]:
    from redat.sources.schutzgebiete import _wsg_featureinfo, parse_wsg
    return parse_wsg(_wsg_featureinfo(lat, lon))


# ---------------------------------------------------------------- PV

def _rate_pv(kwh_a: float) -> tuple[str, str]:
    if kwh_a >= 8000:
        return "Sehr gut", "green"
    if kwh_a >= 4000:
        return "Gut", "green"
    if kwh_a >= 2000:
        return "Mäßig", "yellow"
    if kwh_a > 0:
        return "Gering", "orange"
    return "Keine geeigneten Dachflächen", "gray"


def _pick_building(lat: float, lon: float) -> Optional[tuple[dict, str]]:
    base = {"geometryType": "esriGeometryPoint", "inSR": 4326, "spatialRel": "esriSpatialRelIntersects",
            "outFields": "geb_id,name,Shape_Area", "returnGeometry": "true", "outSR": 4326}
    url = f"{SOLAR_URL}/{SOLAR_BUILDINGS_LAYER}"
    feats = _arcgis_query(url, {**base, "geometry": f"{lon},{lat}"}).get("features", [])
    if feats:
        return feats[0], "contains"
    feats = _arcgis_query(url, {**base, "geometry": f"{lon},{lat}", "distance": _NEAR_M,
                                "units": "esriSRUnit_Meter"}).get("features", [])
    point = Point(_TO_25832.transform(lon, lat))
    best, best_d = None, None
    for f in feats:
        if (f["attributes"].get("Shape_Area") or 0) < _MIN_BUILDING_M2 or not f.get("geometry", {}).get("rings"):
            continue
        outline = shp_transform(_TO_25832.transform, Polygon(f["geometry"]["rings"][0]))
        d = outline.distance(point)
        if best is None or d < best_d:
            best, best_d = f, d
    return (best, "nearest") if best else None


def _pv(lat: float, lon: float) -> Optional[dict]:
    picked = _pick_building(lat, lon)
    if not picked:
        return None
    building, how = picked
    geom = json.dumps({"rings": building["geometry"]["rings"], "spatialReference": {"wkid": 4326}})
    segs = _arcgis_query(f"{SOLAR_URL}/{SOLAR_PV_LAYER}", {
        "geometry": geom, "geometryType": "esriGeometryPolygon", "inSR": 4326, "spatialRel": "esriSpatialRelContains",
        "outFields": "mod_id,himmel_kat,neigung,radabs,modanetto_int,kw,str,dachtyp,jahr", "returnGeometry": "false",
    }).get("features", [])
    rows = []
    for s in segs:
        a = s["attributes"]
        rows.append({
            "orientation": a.get("himmel_kat"), "tilt_deg": a.get("neigung"), "area_m2": a.get("modanetto_int"),
            "kwp": round(a.get("kw") or 0, 1), "kwh_a": round(a.get("str") or 0),
            "radiation_kwh_m2": a.get("radabs"), "roof": a.get("dachtyp"),
        })
    rows.sort(key=lambda r: -r["kwh_a"])
    total_kwh = round(sum(s["attributes"].get("str") or 0 for s in segs))
    rating, color = _rate_pv(total_kwh)
    attrs = building["attributes"]
    return {
        "building": {"geb_id": attrs.get("geb_id"), "alkis_id": attrs.get("name"),
                     "area_m2": round(attrs.get("Shape_Area") or 0, 1), "picked": how},
        "segments": rows[:_MAX_SEGMENTS], "segment_count": len(rows),
        "total_kwp": round(sum(s["attributes"].get("kw") or 0 for s in segs), 1), "total_kwh_a": total_kwh,
        "module_area_m2": round(sum(s["attributes"].get("modanetto_int") or 0 for s in segs)),
        "best_orientation": rows[0]["orientation"] if rows else None,
        "household_equivalents": round(total_kwh / _HOUSEHOLD_KWH_A, 1),
        "survey_year": next((s["attributes"].get("jahr") for s in segs if s["attributes"].get("jahr")), None),
        "rating": rating, "rating_color": color, "link": SOLAR_LINK,
    }


# ---------------------------------------------------------------- Erdwärme

def _rate_erdwaerme(lower: Optional[float]) -> tuple[str, str]:
    if lower is None:
        return "Keine Bewertung", "gray"
    if lower >= 2.5:
        return "Gut", "green"
    if lower >= 2.0:
        return "Mittel", "yellow"
    return "Gering", "orange"


def parse_gt(xml_text: str) -> dict:
    root = ET.fromstring(xml_text)
    probes, collector, hydro, flow = [], None, False, False
    for coll in root.findall("w:FeatureInfoCollection", _NS):
        layer = coll.get("layername", "")
        fields = {}
        for fi in coll.findall("w:FeatureInfo", _NS):
            for field in fi.findall("w:Field", _NS):
                fields[field.findtext("w:FieldName", default="", namespaces=_NS)] = \
                    field.findtext("w:FieldValue", default="", namespaces=_NS)
        if "ewk_wert" in fields:
            collector = fields["ewk_wert"] or None
        elif "sensible" in layer.lower():
            hydro = True
        elif "fliessgeschwindigkeit" in layer.lower():
            flow = True
        else:
            m = re.match(r"(\d+) m Sondenlaenge", layer)
            klasse = next((v for k, v in fields.items() if k.startswith("klasse_wlf")), None)
            if m and klasse:
                rng = (fields.get("klassen_wertebereich") or "").strip()
                low = re.match(r"[<>]?\s*([\d,\.]+)", rng)
                probes.append({"depth": f"{m.group(1)} m", "class": int(klasse), "range": rng.replace(" - ", " – "),
                               "lower_w_mk": float(low.group(1).replace(",", ".")) if low else None})
    probes.sort(key=lambda p: -int(p["depth"].split()[0]))
    return {"probes": probes, "collector": collector, "hydro_sensitive": hydro, "high_groundwater_flow": flow}


def _zone_level(zone: Optional[str]) -> int:
    m = re.match(r"\s*(I{1,3})\b", zone or "")
    return len(m.group(1)) if m else 3


def _erdwaerme(lat: float, lon: float, wsg: list[dict]) -> Optional[dict]:
    data = parse_gt(_gt_featureinfo(lat, lon))
    if not data["probes"] and not data["collector"]:
        return None
    lower = data["probes"][0]["lower_w_mk"] if data["probes"] else None
    rating, color = _rate_erdwaerme(lower)
    note = None
    if wsg:
        worst = min(wsg, key=lambda z: _zone_level(z.get("zone")))
        level = _zone_level(worst.get("zone"))
        # The badge must not read "Gut" in red — the legal constraint
        # overrides the geological one, so the label changes with the colour.
        if level <= 2:
            note = f"Wasserschutzgebiet Zone {worst.get('zone')} ({worst.get('name')}): Erdwärmesonden generell unzulässig"
            rating, color = "Unzulässig (Wasserschutzgebiet)", "red"
        else:
            note = f"Wasserschutzgebiet Zone {worst.get('zone')} ({worst.get('name')}): Erdwärmesonden nur mit Genehmigung"
            if color in ("green", "yellow"):
                rating, color = f"{rating}, genehmigungspflichtig", "orange"
    return {**data, "rating": rating, "rating_color": color, "wsg_note": note, "link": GT_LINK}


# ---------------------------------------------------------------- Wärmeplanung

def _essen(lat: float, lon: float) -> Optional[dict]:
    feats = _arcgis_query(ESSEN_KWP_URL, {
        "geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint", "inSR": 4326, "distance": 30,
        "units": "esriSRUnit_Meter", "spatialRel": "esriSpatialRelIntersects", "outFields": "*", "returnGeometry": "false",
    }).get("features", [])
    if not feats:
        return None
    a = feats[0]["attributes"]
    label = a.get("GEBIETSEINTEILUNG") or "unbekannt"
    category, color = _ESSEN_CATEGORIES.get(label, ("sonstiges", "gray"))
    has24, has45 = a.get("HAS_HEAT_GRID_2024"), a.get("HAS_HEAT_GRID_2045")
    if category == "fernwaerme_ausbau" and has24 == 1:
        category = "fernwaerme_bestand"
    pref = a.get("PREFERENCE_AREA") or ""
    detail = pref.split(" - ", 1)[1].strip() if " - " in pref else None
    return {"city": "Essen", "status": "beschlossen", "target_year": 2045, "category": category, "color": color,
            "label": label, "detail": detail,
            "has_grid_2024": None if has24 is None else has24 == 1, "has_grid_2045": None if has45 is None else has45 == 1,
            "link": ESSEN_KWP_LINK}


def _bochum(lat: float, lon: float) -> Optional[dict]:
    results = _arcgis_identify(BOCHUM_KWP_URL, {
        "geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint", "sr": 4326, "layers": "all", "tolerance": 5,
        "mapExtent": "7.1,51.4,7.3,51.5", "imageDisplay": "2000,1000,96", "returnGeometry": "false",
    }).get("results", [])
    if not results:
        return None
    hit = min(results, key=lambda r: r.get("layerId", 99))
    category, color = _BOCHUM_CATEGORIES.get(hit.get("layerId"), ("sonstiges", "gray"))
    attrs = hit.get("attributes", {})
    detail = attrs.get("Name") if category == "sonstiges" else None
    return {"city": "Bochum", "status": "Entwurf", "target_year": 2045, "category": category, "color": color,
            "label": hit.get("layerName") or attrs.get("Zielbild") or "unbekannt", "detail": detail,
            "has_grid_2024": None, "has_grid_2045": None, "link": BOCHUM_KWP_LINK}


def _waermeplanung(lat: float, lon: float) -> Optional[dict]:
    return _essen(lat, lon) or _bochum(lat, lon)


# ---------------------------------------------------------------- entry point

def get_energie(lat: float, lon: float) -> Optional[dict]:
    """`{pv, erdwaerme, waermeplanung, errors}`; None when no part has data; raises when every part failed."""
    errors: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=4) as ex:
        wsg_fut = ex.submit(_wsg_zones, lat, lon)
        pv_fut = ex.submit(_pv, lat, lon)
        wp_fut = ex.submit(_waermeplanung, lat, lon)
        try:
            wsg = wsg_fut.result()
        except Exception as e:  # noqa: BLE001 — the caveat is optional
            logger.warning("WSG lookup for Erdwärme failed: %s", e)
            errors["wsg"] = str(e)
            wsg = []
        ew_fut = ex.submit(_erdwaerme, lat, lon, wsg)
        parts = {}
        for key, fut in (("pv", pv_fut), ("erdwaerme", ew_fut), ("waermeplanung", wp_fut)):
            try:
                parts[key] = fut.result()
            except Exception as e:  # noqa: BLE001 — one source must not blank the card
                logger.warning("energie part %s failed: %s", key, e)
                errors[key] = str(e)
                parts[key] = None
    if all(v is None for v in parts.values()):
        failed = [k for k in parts if k in errors]
        if failed:
            raise RuntimeError(f"Energiedaten nicht abrufbar ({', '.join(failed)}): {errors[failed[0]]}")
        return None
    return {**parts, "errors": errors}
