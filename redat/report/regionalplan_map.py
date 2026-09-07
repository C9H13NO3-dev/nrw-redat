"""Regionalplan panel for the PDF — the statewide counterpart of the RVR-only GFNP card.

WMS: https://www.wms.nrw.de/wms/wms_nw_regionalplan, one raster layer `regionalplan` (the six Regionalpläne
plus the RFNP of the Ruhr core, 1:50,000, unverbindlich). It is not queryable (no GetFeatureInfo) and its
GetLegendGraphic is a 959 × 1918 px poster with ~120 entries, so the figure is image-only and links the legend.
Same 2 km window / decoration as the climate panels; `_get_png` is the HTTP seam. Never raises.
"""
from __future__ import annotations

import base64
import io
import logging

import httpx
from PIL import Image

from redat.http import headers
from redat.report.climate_maps import HEIGHT, WIDTH, bbox_2km, decorate

logger = logging.getLogger(__name__)

WMS_URL = "https://www.wms.nrw.de/wms/wms_nw_regionalplan"
LAYER = "regionalplan"
TIMEOUT_S = 10.0
LEGEND_URL = (f"{WMS_URL}?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetLegendGraphic&LAYER={LAYER}"
              "&FORMAT=image/png&SLD_VERSION=1.1.0")
TITLE = "Regionalplan (1:50.000)"


def _get_png(url: str, params: dict) -> bytes:
    resp = httpx.get(url, params=params, timeout=TIMEOUT_S, headers=headers())
    resp.raise_for_status()
    if not resp.headers.get("content-type", "").startswith("image"):
        logger.warning("regionalplan WMS returned %s: %r", resp.headers.get("content-type"), resp.text[:120])
        raise ValueError("WMS lieferte kein Bild")
    return resp.content


def render_regionalplan_map(lat: float, lon: float) -> dict:
    bbox = bbox_2km(lat, lon)
    params = {"SERVICE": "WMS", "VERSION": "1.3.0", "REQUEST": "GetMap", "CRS": "EPSG:25832",
              "BBOX": ",".join(f"{v:.3f}" for v in bbox), "WIDTH": WIDTH, "HEIGHT": HEIGHT,
              "FORMAT": "image/png", "LAYERS": LAYER, "STYLES": "", "TRANSPARENT": "FALSE"}
    try:
        im = Image.open(io.BytesIO(_get_png(WMS_URL, params)))
        im.load()
        im = decorate(im.convert("RGBA").resize((WIDTH, HEIGHT)), TITLE).convert("RGB")
        buf = io.BytesIO()
        im.save(buf, format="PNG", optimize=True)
        return {"image": base64.b64encode(buf.getvalue()).decode("ascii"), "legend_url": LEGEND_URL, "error": None}
    except Exception as exc:  # noqa: BLE001 — a missing figure must never block the PDF
        logger.warning("regionalplan map failed: %s", exc)
        return {"image": None, "legend_url": LEGEND_URL, "error": f"Regionalplan-Ausschnitt nicht verfügbar ({exc})"}
