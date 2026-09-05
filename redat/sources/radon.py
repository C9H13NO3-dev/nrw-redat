"""Radon — the BfS soil-air prognosis and geogenic radon potential for the point.

Source: Bundesamt für Strahlenschutz open-data WFS https://www.imis.bfs.de/ogc/opendata/ows (WFS 2.0.0,
GeoJSON, dl-de/by-2-0). Types: `opendata:radon222_boden_rfv_risikokommunikation` — ~3 km cells with
`rn_max` = 90th percentile of the radon activity concentration in soil air at 1 m depth in kBq/m³,
`geo_unit` ("Karbon", "Kreide", "Quartär"), `descript` cell id; `opendata:radonpotential` — ~10 km cells
with `grp_pb_`, the geogenic radon potential (radon concentration combined with gas permeability,
dimensionless). The bbox parameter must be **lon,lat** order (lat,lon returns nothing — verified
2026-09-05); geometries are WGS84 lon/lat, so shapely works on them directly.

Classes — Bodenluft per the BfS map legend: < 20 gering, 20–40 mittel, 40–100 erhöht, > 100 hoch
(kBq/m³). Potenzial per the Neznal classification the BfS uses: < 10 gering, 10–35 mittel, > 35 hoch.
Both are regional prognoses, never a measurement at the house; NRW has designated no
Radonvorsorgegebiete. `_wfs_features` is the single HTTP call and monkeypatch point.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import httpx
from shapely.geometry import Point, shape

from redat.http import headers

logger = logging.getLogger(__name__)

BFS_WFS_URL = "https://www.imis.bfs.de/ogc/opendata/ows"
TYPE_BODEN = "opendata:radon222_boden_rfv_risikokommunikation"
TYPE_POTENZIAL = "opendata:radonpotential"
_BBOX_DEG = 0.01
_TIMEOUT_S = 20
_COLOR_RANK = {"green": 0, "yellow": 1, "orange": 2, "red": 3}


def _wfs_features(typename: str, lat: float, lon: float) -> list[dict]:
    """GeoJSON features of one type around the point — HTTP/monkeypatch point (bbox is lon,lat!)."""
    params = {
        "service": "WFS", "version": "2.0.0", "request": "GetFeature", "typeNames": typename,
        "outputFormat": "application/json", "srsName": "EPSG:4326",
        "bbox": f"{lon - _BBOX_DEG},{lat - _BBOX_DEG},{lon + _BBOX_DEG},{lat + _BBOX_DEG},EPSG:4326", "count": 20,
    }
    resp = httpx.get(BFS_WFS_URL, params=params, timeout=_TIMEOUT_S, headers=headers())
    resp.raise_for_status()
    return resp.json().get("features", [])


def classify_bodenluft(kbq: float) -> tuple[str, str]:
    if kbq > 100:
        return "hoch", "red"
    if kbq > 40:
        return "erhöht", "orange"
    if kbq >= 20:
        return "mittel", "yellow"
    return "gering", "green"


def classify_potenzial(value: float) -> tuple[str, str]:
    if value > 35:
        return "hoch", "orange"
    if value >= 10:
        return "mittel", "yellow"
    return "gering", "green"


def _cell_at(features: list[dict], pt: Point) -> Optional[dict]:
    for f in features:
        try:
            if shape(f["geometry"]).contains(pt):
                return f.get("properties") or {}
        except (KeyError, TypeError, ValueError):
            continue
    return None


def get_radon(lat: float, lon: float) -> Optional[dict]:
    """Soil-air radon and radon potential at the point; None when neither dataset covers it."""
    pt = Point(lon, lat)
    out: dict = {"bodenluft": None, "potenzial": None, "errors": {}}
    types = (("bodenluft", TYPE_BODEN), ("potenzial", TYPE_POTENZIAL))
    with ThreadPoolExecutor(max_workers=len(types)) as ex:   # two independent WFS calls, one round-trip
        futures = {key: ex.submit(_wfs_features, typename, lat, lon) for key, typename in types}
    for key, typename in types:                              # fixed order → stable errors/result order
        try:
            props = _cell_at(futures[key].result(), pt)
        except Exception as exc:  # noqa: BLE001 — one type failing must not blank the other
            logger.warning("BfS %s: %s", typename, exc)
            out["errors"][key] = str(exc)
            continue
        if props is None:
            continue
        if key == "bodenluft" and props.get("rn_max") is not None:
            kbq = float(props["rn_max"])
            label, color = classify_bodenluft(kbq)
            out["bodenluft"] = {"kbq_m3": kbq, "klasse": label, "klasse_color": color, "geologie": props.get("geo_unit"), "zelle": props.get("descript")}
        elif key == "potenzial" and props.get("grp_pb_") is not None:
            val = float(props["grp_pb_"])
            label, color = classify_potenzial(val)
            out["potenzial"] = {"wert": val, "klasse": label, "klasse_color": color}
    if out["bodenluft"] is None and out["potenzial"] is None:
        # Nothing to show *and* a request failed → an outage, not "no data here": let the envelope say so.
        if out["errors"]:
            raise RuntimeError("BfS-WFS nicht erreichbar: " + "; ".join(out["errors"].values()))
        return None
    colors = [b["klasse_color"] for b in (out["bodenluft"], out["potenzial"]) if b]
    worst = max(colors, key=_COLOR_RANK.get)
    out["rating"] = {"green": "Geringes Radonpotenzial", "yellow": "Mittleres Radonpotenzial",
                     "orange": "Erhöhtes Radonpotenzial", "red": "Hohes Radonpotenzial"}[worst]
    out["rating_color"] = worst
    return out
