"""Bauleitplanung Bochum – best-effort extraction.

Bochum Geoportal (map.apps) includes a B-Plan outline layer via RVR INSPIRE WMS:
  https://geodaten.metropoleruhr.de/inspire/bodennutzung/metropoleruhr (layer: bplan)

We use WMS GetFeatureInfo with info_format=text/html and parse the returned HTML
for key fields (official name, plan-id, rechtsstand, plan link, metadata link).

Note: WMS 1.3.0 axis order for EPSG:4326 is lat,lon in BBOX.

No external deps: uses httpx.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from redat.http import headers

logger = logging.getLogger(__name__)

BPLAN_WMS = "https://geodaten.metropoleruhr.de/inspire/bodennutzung/metropoleruhr"
BPLAN_LAYER = "bplan"


def _wms_getfeatureinfo_html(lat: float, lon: float) -> str:
    half = 0.0003
    bbox = f"{lat-half},{lon-half},{lat+half},{lon+half}"  # EPSG:4326 axis order in WMS 1.3.0

    params = {
        "service": "WMS",
        "version": "1.3.0",
        "request": "GetFeatureInfo",
        "layers": BPLAN_LAYER,
        "query_layers": BPLAN_LAYER,
        "styles": "",
        "crs": "EPSG:4326",
        "bbox": bbox,
        "width": "101",
        "height": "101",
        "i": "50",
        "j": "50",
        "info_format": "text/html",
        "feature_count": "10",
    }

    with httpx.Client(timeout=30.0, follow_redirects=True, headers=headers()) as client:
        r = client.get(BPLAN_WMS, params=params)
        r.raise_for_status()
        return r.text


def _extract_blocks(html: str) -> list[dict[str, Any]]:
    names = re.findall(r"<td><b>offizieller Name:</b></td>\s*<td>(.*?)</td>", html, re.S)
    planids = re.findall(r"<td><b>Plan-ID:</b></td>\s*<td>(.*?)</td>", html, re.S)
    kommune = re.findall(r"<td><b>Kommune:</b></td>\s*<td>(.*?)</td>", html, re.S)
    plantyp = re.findall(r"<td><b>Plantyp:</b></td>\s*<td>(.*?)</td>", html, re.S)
    rechts = re.findall(r"<td><b>Rechtsstand:</b></td>\s*<td>(.*?)</td>", html, re.S)

    plan_links = re.findall(r"href='(https?://www\.o-sp\.de/[^']+)'", html)
    meta_links = re.findall(r"href='(https?://daten\.geoportal\.ruhr/[^']+)'", html)

    n = max(len(names), len(planids), len(rechts), len(plantyp), len(kommune))
    out: list[dict[str, Any]] = []
    for i in range(n):
        item: dict[str, Any] = {}
        if i < len(names):
            item["official_name"] = re.sub(r"\s+", " ", names[i]).strip()
        if i < len(planids):
            item["plan_id"] = re.sub(r"\s+", " ", planids[i]).strip()
        if i < len(kommune):
            item["commune"] = re.sub(r"\s+", " ", kommune[i]).strip()
        if i < len(plantyp):
            item["plan_type"] = re.sub(r"\s+", " ", plantyp[i]).strip()
        if i < len(rechts):
            item["legal_status"] = re.sub(r"\s+", " ", rechts[i]).strip()
        if i < len(plan_links):
            item["plan_link"] = plan_links[i]
        if i < len(meta_links):
            item["metadata_link"] = meta_links[i]
        if item:
            out.append(item)
    return out


def get_bochum_bplan_outline(lat: float, lon: float) -> dict[str, Any]:
    try:
        html = _wms_getfeatureinfo_html(lat, lon)
        items = _extract_blocks(html)
        return {
            "ok": True,
            "found": bool(items),
            "items": items,
            "source": "RVR INSPIRE bodennutzung/metropoleruhr (WMS GetFeatureInfo bplan, text/html)",
        }
    except Exception as e:
        logger.exception("Bochum B-Plan WMS GetFeatureInfo failed")
        return {"ok": False, "error": str(e)}
