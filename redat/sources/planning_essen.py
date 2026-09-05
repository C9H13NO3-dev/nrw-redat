"""Bauleitplanung / aktuelle Planungen – Stadt Essen Geoportal.

We query the public ArcGIS REST services that power https://geoportal.essen.de/gfnp/

Primary service:
- https://geo.essen.de/arcgis/rest/services/essen/Planen_und_Bauen/MapServer

We do point queries (WGS84) against selected layers to extract useful, address-level
planning signals:
- Bebauungspläne (layer 87)
- Vorhabenbezogene Bebauungspläne (layer 10)
- Veränderungssperren (layer 4)
- Aufstellungsbeschlüsse (layer 7)
- Auslegungsbeschlüsse (layer 6)
- Aufhebungsbeschlüsse (layer 89)

This is an informational aid only.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import httpx

from redat.http import headers

logger = logging.getLogger(__name__)

PB_BASE = "https://geo.essen.de/arcgis/rest/services/essen/Planen_und_Bauen/MapServer"

# Key layers (from webmap config)
L_BPLAN = 87
L_VHBP = 10
L_VSPERRE = 4
L_AUFSTELLUNG = 7
L_AUSLEGUNG = 6
L_AUFHEBUNG = 89


def _query(layer: int, lat: float, lon: float, out_fields: str, record_count: int = 25) -> dict:
    url = f"{PB_BASE}/{layer}/query"
    params = {
        "f": "json",
        "where": "1=1",
        "geometry": f"{lon},{lat}",
        "geometryType": "esriGeometryPoint",
        "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": out_fields,
        "returnGeometry": "false",
        "resultRecordCount": record_count,
    }
    with httpx.Client(timeout=30.0, follow_redirects=True, headers=headers()) as client:
        r = client.get(url, params=params)
        r.raise_for_status()
        return r.json()


def _simplify_features(data: dict, mapping: dict[str, str]) -> list[dict[str, Any]]:
    feats = data.get("features") or []
    out: list[dict[str, Any]] = []
    for f in feats:
        attrs = f.get("attributes") or {}
        item: dict[str, Any] = {}
        for src, dst in mapping.items():
            v = attrs.get(src)
            if v is None or v == "":
                continue
            # ArcGIS dates can be millis
            if src.upper() == "DATUM" and isinstance(v, (int, float)) and v > 10_000_000_000:
                try:
                    v = datetime.utcfromtimestamp(v / 1000.0).date().isoformat()
                except Exception:
                    pass
            item[dst] = v
        if item:
            out.append(item)
    return out


ESSEN_API_KEY = "de43bbfe-b952-40e4-89ca-f46b69776e0f"


def _detail_links(kind: str, nr: Any) -> dict[str, str] | None:
    if not nr:
        return None
    nr_s = str(nr)
    if kind == "bauverfahren":
        return {
            "label": "Bauverfahren (Details)",
            "url": f"https://wapps.essen.de/BauleitplanungExt/Bauverfahren?ApiKey={ESSEN_API_KEY}&ordnr={nr_s}",
        }
    if kind == "veraenderungssperre":
        return {
            "label": "Veränderungssperre (Details)",
            "url": f"https://wapps.essen.de/BauleitplanungExt/Veraenderungssperren?ApiKey={ESSEN_API_KEY}&ordnr={nr_s}",
        }
    if kind == "aufstellung":
        return {
            "label": "Aufstellungsbeschluss (Details)",
            "url": f"https://wapps.essen.de/BauleitplanungExt/Aufstellungsbeschluesse?ApiKey={ESSEN_API_KEY}&ordnr={nr_s}",
        }
    if kind == "sonstige":
        return {
            "label": "Sonstige Satzung (Details)",
            "url": f"https://wapps.essen.de/BauleitplanungExt/SonstigeSatzungen?ApiKey={ESSEN_API_KEY}&ordnr={nr_s}",
        }
    return None


def _attach_links(items: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for it in items:
        it2 = dict(it)
        link = _detail_links(kind, it2.get("nr"))
        if link:
            it2["link"] = link
        out.append(it2)
    return out


def get_planning_signals(lat: float, lon: float) -> dict[str, Any]:
    """Return planning-related signals at the coordinate."""

    try:
        bplan = _simplify_features(
            _query(L_BPLAN, lat, lon, out_fields="NR,NAME,PLANART,STAND,PLANID"),
            {"NR": "nr", "NAME": "name", "PLANART": "plan_type", "STAND": "status", "PLANID": "plan_id"},
        )

        vhbp = _simplify_features(
            _query(L_VHBP, lat, lon, out_fields="NR,NAME"),
            {"NR": "nr", "NAME": "name"},
        )

        vsperre = _simplify_features(
            _query(L_VSPERRE, lat, lon, out_fields="NR,NAME"),
            {"NR": "nr", "NAME": "name"},
        )

        aufstellung = _simplify_features(
            _query(L_AUFSTELLUNG, lat, lon, out_fields="NR,NAME"),
            {"NR": "nr", "NAME": "name"},
        )

        auslegung = _simplify_features(
            _query(L_AUSLEGUNG, lat, lon, out_fields="NR,NAME"),
            {"NR": "nr", "NAME": "name"},
        )

        aufhebung = _simplify_features(
            _query(L_AUFHEBUNG, lat, lon, out_fields="NR,NAME"),
            {"NR": "nr", "NAME": "name"},
        )

        # Attach Essen detail links when possible
        bplan = _attach_links(bplan, "bauverfahren")
        vhbp = _attach_links(vhbp, "bauverfahren")
        vsperre = _attach_links(vsperre, "veraenderungssperre")
        aufstellung = _attach_links(aufstellung, "aufstellung")
        auslegung = _attach_links(auslegung, "bauverfahren")
        aufhebung = _attach_links(aufhebung, "bauverfahren")

        found = any([bplan, vhbp, vsperre, aufstellung, auslegung, aufhebung])

        return {
            "ok": True,
            "found": found,
            "bplan": bplan,
            "vhbplan": vhbp,
            "veraenderungssperre": vsperre,
            "aufstellungsbeschluss": aufstellung,
            "auslegungsbeschluss": auslegung,
            "aufhebungsbeschluss": aufhebung,
            "source": "geo.essen.de ArcGIS Planen_und_Bauen (MapServer point queries) + wapps.essen.de detail links",
        }

    except Exception as e:
        logger.exception("Planning signals query failed")
        return {"ok": False, "error": str(e)}
