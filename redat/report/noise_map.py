"""Static Lärm map composites for the PDF report — the one image the report carries.

Two 480×360 px images (Tag = L_DEN, Nacht = L_Night) over a 600 × 450 m window
centred on the point: basemap.de grey raster (BKG, dl-de/by-2-0) with the NRW
Umgebungslärm WMS layers alpha-blended on top, plus a pin, a 100 m scale bar and
a title box drawn with Pillow. Every HTTP call goes through `_get_png` (the test
seam). A failed overlay yields None for that map; a failed basemap draws the
overlay on white — neither ever blocks the PDF.
"""
from __future__ import annotations

import base64
import io
import logging
from typing import Optional

import httpx
from PIL import Image, ImageDraw
from pyproj import Transformer

from redat.http import headers

logger = logging.getLogger(__name__)

WIDTH, HEIGHT = 480, 360
WINDOW_M = 600.0  # metres across the image width → 1.25 m/px
TIMEOUT_S = 12.0
OVERLAY_ALPHA = 0.7

BASEMAP_URL = "https://sgx.geodatenzentrum.de/wms_basemapde"
BASEMAP_LAYER = "de_basemapde_web_raster_grau"
NOISE_URL = "https://www.wms.nrw.de/umwelt/laerm"
DAY_LAYERS = "STR_DEN,SCB_DEN,SCS_DEN,IND_DEN,FLG_DEN"
NIGHT_LAYERS = "STR_NGT,SCB_NGT,SCS_NGT,IND_NGT,FLG_NGT"

ATTRIBUTION = "© basemap.de / BKG (dl-de/by-2-0) · Lärmkartierung: Land NRW (LANUV), Umgebungslärm 2022"

# Colours from the WMS GetLegendGraphic (Straßenverkehr; identical for the other sources).
# Night bands start one class lower (50–54) — shown as one combined dB(A) legend.
LEGEND_BANDS = [
    {"label": "ab 50 bis 54 dB(A) (nur Nacht)", "color": "#b8d6d1"},
    {"label": "ab 55 bis 59 dB(A)", "color": "#e2f2bf"},
    {"label": "ab 60 bis 64 dB(A)", "color": "#f3c683"},
    {"label": "ab 65 bis 69 dB(A)", "color": "#cd463e"},
    {"label": "ab 70 bis 74 dB(A)", "color": "#75085c"},
    {"label": "ab 75 dB(A)", "color": "#430a4a"},
]

_TO_UTM = Transformer.from_crs("EPSG:4326", "EPSG:25832", always_xy=True)


def bbox_25832(lat: float, lon: float) -> tuple[float, float, float, float]:
    """(minx, miny, maxx, maxy) in EPSG:25832 for the WINDOW_M × (WINDOW_M·H/W) window."""
    x, y = _TO_UTM.transform(lon, lat)
    half_w = WINDOW_M / 2
    half_h = WINDOW_M * HEIGHT / WIDTH / 2
    return x - half_w, y - half_h, x + half_w, y + half_h


def _get_png(url: str, params: dict) -> bytes:
    """GET a WMS image; raises on transport errors, non-2xx and non-image bodies."""
    r = httpx.get(url, params=params, timeout=TIMEOUT_S, headers=headers())
    r.raise_for_status()
    ctype = r.headers.get("content-type", "")
    if not ctype.startswith("image/"):
        raise RuntimeError(f"WMS lieferte {ctype or 'keine'} statt eines Bildes: {r.text[:200]}")
    return r.content


def _getmap_params(bbox, layers: str, transparent: bool) -> dict:
    return {
        "SERVICE": "WMS", "VERSION": "1.3.0", "REQUEST": "GetMap",
        "CRS": "EPSG:25832", "BBOX": ",".join(f"{v:.3f}" for v in bbox),
        "WIDTH": WIDTH, "HEIGHT": HEIGHT, "FORMAT": "image/png",
        "LAYERS": layers, "STYLES": "", "TRANSPARENT": "TRUE" if transparent else "FALSE",
    }


def _fetch_image(url: str, params: dict) -> Image.Image:
    im = Image.open(io.BytesIO(_get_png(url, params)))
    im.load()
    return im.convert("RGBA").resize((WIDTH, HEIGHT))


def _decorate(im: Image.Image, title: str) -> Image.Image:
    draw = ImageDraw.Draw(im)
    cx, cy = WIDTH // 2, HEIGHT // 2
    # pin: white halo + red dot
    draw.ellipse((cx - 9, cy - 9, cx + 9, cy + 9), fill=(255, 255, 255, 255))
    draw.ellipse((cx - 6, cy - 6, cx + 6, cy + 6), fill=(220, 38, 38, 255))
    # scale bar (100 m) bottom-left
    px_per_m = WIDTH / WINDOW_M
    bar = int(round(100 * px_per_m))
    x0, y0 = 12, HEIGHT - 16
    draw.rectangle((x0 - 4, y0 - 16, x0 + bar + 44, y0 + 8), fill=(255, 255, 255, 220))
    draw.rectangle((x0, y0, x0 + bar, y0 + 4), fill=(17, 24, 39, 255))
    draw.text((x0 + bar + 6, y0 - 7), "100 m", fill=(17, 24, 39, 255))
    # title box top-left
    tw = int(draw.textlength(title)) if hasattr(draw, "textlength") else 8 * len(title)
    draw.rectangle((8, 8, 8 + tw + 12, 26), fill=(255, 255, 255, 230))
    draw.text((14, 11), title, fill=(17, 24, 39, 255))
    return im


def _to_b64(im: Image.Image) -> str:
    buf = io.BytesIO()
    im.convert("RGB").save(buf, format="PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def render_noise_maps(lat: float, lon: float) -> dict:
    """{'day': b64 | None, 'night': b64 | None, 'legend': [...], 'attribution': str, 'error': str | None}."""
    bbox = bbox_25832(lat, lon)
    errors: list[str] = []

    try:
        base = _fetch_image(BASEMAP_URL, _getmap_params(bbox, BASEMAP_LAYER, transparent=False))
    except Exception as e:  # noqa: BLE001 — basemap is decoration; overlay on white instead
        logger.warning("basemap fetch failed: %s", e)
        errors.append(f"Kartengrundlage: {e}")
        base = Image.new("RGBA", (WIDTH, HEIGHT), (255, 255, 255, 255))

    out: dict[str, Optional[str]] = {}
    for key, layers, title in (("day", DAY_LAYERS, "Tag (L_DEN)"), ("night", NIGHT_LAYERS, "Nacht (L_Night)")):
        try:
            overlay = _fetch_image(NOISE_URL, _getmap_params(bbox, layers, transparent=True))
        except Exception as e:  # noqa: BLE001 — placeholder in the template, never a failed PDF
            logger.warning("noise overlay %s failed: %s", key, e)
            errors.append(f"Lärmkarte {title}: {e}")
            out[key] = None
            continue
        alpha = overlay.getchannel("A").point(lambda a: int(a * OVERLAY_ALPHA))
        overlay.putalpha(alpha)
        composite = Image.alpha_composite(base.copy(), overlay)
        out[key] = _to_b64(_decorate(composite, title))

    return {
        "day": out.get("day"),
        "night": out.get("night"),
        "legend": LEGEND_BANDS,
        "attribution": ATTRIBUTION,
        "error": " · ".join(errors) or None,
    }
