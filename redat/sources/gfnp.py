"""Gemeinsamer Flächennutzungsplan (GFNP) – Essen/Bochum (Regionalverband Ruhr / Stadt Essen Geoportal).

We query the public ArcGIS REST service used by https://geoportal.essen.de/gfnp/

Service:
- https://geo.essen.de/arcgis/rest/services/essen/GFNP/MapServer

We use layer 13 ("Flächendarstellung") which contains the FLAECHENNU designation.

Approach:
- point query with spatialRel=Intersects in WGS84 (inSR=4326)

Note: this returns the designation at the coordinate. Interpretations/planning law
must be done by humans.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

import httpx

from redat.http import headers

logger = logging.getLogger(__name__)

GFNP_BASE = "https://geo.essen.de/arcgis/rest/services/essen/GFNP/MapServer"
GFNP_FLAECHEN_LAYER = 13


def _arcgis_query(layer: int, lat: float, lon: float, out_fields: str) -> dict:
    url = f"{GFNP_BASE}/{layer}/query"

    params = {
        "f": "json",
        "where": "1=1",
        "geometry": f"{lon},{lat}",
        "geometryType": "esriGeometryPoint",
        "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": out_fields,
        "returnGeometry": "false",
        "resultRecordCount": 5,
    }

    with httpx.Client(timeout=30.0, follow_redirects=True, headers=headers()) as client:
        r = client.get(url, params=params)
        r.raise_for_status()
        return r.json()


def get_gfnp_designation(lat: float, lon: float) -> dict[str, Any]:
    """Return the GFNP land-use designation + relevant overlays for a coordinate."""

    def _date_to_iso(v: Any) -> Optional[str]:
        try:
            if isinstance(v, (int, float)) and v > 10_000_000_000:
                return datetime.utcfromtimestamp(v / 1000.0).date().isoformat()
            if isinstance(v, str) and v:
                return v
        except Exception:
            return None
        return None

    try:
        # Main designation (Flächendarstellung)
        data = _arcgis_query(
            GFNP_FLAECHEN_LAYER,
            lat,
            lon,
            out_fields="FLAECHENNU,STADT,DATUM",
        )

        feats = data.get("features") or []
        found = bool(feats)

        designation = None
        city = None
        date_iso = None
        if found:
            attrs = feats[0].get("attributes") or {}
            designation = attrs.get("FLAECHENNU")
            city = attrs.get("STADT")
            date_iso = _date_to_iso(attrs.get("DATUM"))

        # Flood / water-related overlays present in the GFNP webmap
        overlays: list[dict[str, Any]] = []
        overlay_layers = [
            (4, "Festgesetztes Überschwemmungsgebiet"),
            (5, "Hochwasserrisikogebiet (HQ extrem)"),
            (7, "Vorläufig gesichertes Überschwemmungsgebiet"),
        ]
        for layer_id, label in overlay_layers:
            od = _arcgis_query(layer_id, lat, lon, out_fields="FLAECHENNU,FNP,STADT,DATUM,LEG")
            for f in (od.get("features") or []):
                a = f.get("attributes") or {}
                overlays.append(
                    {
                        "type": label,
                        "legend": a.get("LEG"),
                        "city": a.get("STADT"),
                        "date": _date_to_iso(a.get("DATUM")),
                        "fnp": a.get("FNP"),
                    }
                )

        return {
            "ok": True,
            "found": found,
            "designation": designation,
            "city": city,
            "date": date_iso,
            "overlays": overlays,
            "source": "geo.essen.de ArcGIS GFNP (MapServer queries)",
        }

    except Exception as e:
        logger.exception("GFNP query failed")
        return {"ok": False, "error": str(e)}
