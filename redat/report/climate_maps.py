"""Two RVR Umweltmonitoring panels for the PDF: tree canopy (Beschirmungsgrad) and summer surface temperature.

WMS https://services-rvr.geoportal.ruhr/umon/<service> (Regionalverband Ruhr, "lizenzkostenfrei"; verified
2026-09-06): `veg_schirm` layer `beschirmungsgrad` (10 m, share of area under vegetation) and `oftemp` layer
`Oberflaechentemperatur_1330` with STYLE `day` (MODIS 1 km, summer median 13:30 °C). GetFeatureInfo returns no
values and the legends are continuous ramps, so the layers are shown as images with their own legend PNGs
(GetLegendGraphic needs SLD_VERSION=1.1.0). 2 km window because the temperature pixels are 1 km.

Both panels' GetMap and GetLegendGraphic requests (4 total) run concurrently in a small `ThreadPoolExecutor`
— one future per request — so the whole figure costs about one `TIMEOUT_S` in the worst case instead of
stacking up to four sequential timeouts. `_get_png` is the HTTP/monkeypatch point. The GetMap params are
built here rather than via `noise_map._getmap_params` (which hardcodes `STYLES: ""`) because the surface-
temperature layer needs `STYLES=day`.
"""
from __future__ import annotations

import base64
import io
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import httpx
from PIL import Image, ImageDraw
from pyproj import Transformer

from redat.http import headers
from redat.report.noise_map import title_font

logger = logging.getLogger(__name__)

WIDTH, HEIGHT = 480, 360
WINDOW_M = 2000.0
TIMEOUT_S = 10.0
BASE = "https://services-rvr.geoportal.ruhr/umon/"
PANELS = (
    ("beschirmung", "Beschirmungsgrad (Baumkronen)", "veg_schirm", "beschirmungsgrad", "default"),
    ("oberflaechentemperatur", "Oberflächentemperatur 13:30 Uhr (Sommer)", "oftemp", "Oberflaechentemperatur_1330", "day"),
)
ATTRIBUTION = "© Regionalverband Ruhr, Umweltmonitoring (Beschirmungsgrad 10 m; Oberflächentemperatur MODIS 1 km, Sommer-Median)"
_MAX_WORKERS = 4  # 2 panels × (GetMap + GetLegendGraphic), all in flight at once
_TO_UTM = Transformer.from_crs("EPSG:4326", "EPSG:25832", always_xy=True)


def bbox_2km(lat: float, lon: float) -> tuple[float, float, float, float]:
    x, y = _TO_UTM.transform(lon, lat)
    hw, hh = WINDOW_M / 2, WINDOW_M * HEIGHT / WIDTH / 2
    return x - hw, y - hh, x + hw, y + hh


def _get_png(url: str, params: dict) -> bytes:
    r = httpx.get(url, params=params, timeout=TIMEOUT_S, headers=headers())
    r.raise_for_status()
    if not r.headers.get("content-type", "").startswith("image/"):
        raise RuntimeError(f"WMS lieferte {r.headers.get('content-type') or 'keine'} statt eines Bildes")
    return r.content


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def decorate(im: Image.Image, title: str) -> Image.Image:
    draw = ImageDraw.Draw(im)
    font = title_font()
    cx, cy = WIDTH // 2, HEIGHT // 2
    draw.ellipse((cx - 9, cy - 9, cx + 9, cy + 9), fill=(255, 255, 255, 255))
    draw.ellipse((cx - 6, cy - 6, cx + 6, cy + 6), fill=(220, 38, 38, 255))
    bar = int(round(500 * WIDTH / WINDOW_M))
    x0, y0 = 12, HEIGHT - 16
    draw.rectangle((x0 - 4, y0 - 16, x0 + bar + 44, y0 + 8), fill=(255, 255, 255, 220))
    draw.rectangle((x0, y0, x0 + bar, y0 + 4), fill=(17, 24, 39, 255))
    draw.text((x0 + bar + 6, y0 - 7), "500 m", fill=(17, 24, 39, 255), font=font)
    tw = int(draw.textlength(title, font=font)) if hasattr(draw, "textlength") else 8 * len(title)
    draw.rectangle((8, 8, 8 + tw + 12, 26), fill=(255, 255, 255, 230))
    draw.text((14, 11), title, fill=(17, 24, 39, 255), font=font)
    return im


def _fetch_map(url: str, bbox, layer: str, style: str) -> Image.Image:
    raw = _get_png(url, {"SERVICE": "WMS", "VERSION": "1.3.0", "REQUEST": "GetMap", "CRS": "EPSG:25832",
                         "BBOX": ",".join(f"{v:.3f}" for v in bbox), "WIDTH": WIDTH, "HEIGHT": HEIGHT,
                         "FORMAT": "image/png", "LAYERS": layer, "STYLES": style, "TRANSPARENT": "TRUE"})
    im = Image.open(io.BytesIO(raw))
    im.load()
    return im.convert("RGBA").resize((WIDTH, HEIGHT))


def _fetch_legend(url: str, layer: str, style: str) -> bytes:
    return _get_png(url, {"SERVICE": "WMS", "VERSION": "1.3.0", "REQUEST": "GetLegendGraphic", "LAYER": layer,
                          "FORMAT": "image/png", "STYLE": style, "SLD_VERSION": "1.1.0"})


def render_climate_maps(lat: float, lon: float) -> dict:
    bbox = bbox_2km(lat, lon)
    errors: list[str] = []

    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as ex:
        futures = {}
        for key, title, service, layer, style in PANELS:
            url = BASE + service
            futures[key, "map"] = ex.submit(_fetch_map, url, bbox, layer, style)
            futures[key, "legend"] = ex.submit(_fetch_legend, url, layer, style)

        panels = []
        for key, title, service, layer, style in PANELS:
            image: Optional[str] = None
            try:
                im = futures[key, "map"].result()
                buf = io.BytesIO()
                decorate(im, title).convert("RGB").save(buf, format="PNG", optimize=True)
                image = _b64(buf.getvalue())
            except Exception as e:  # noqa: BLE001 — a missing panel is a placeholder, never a failed PDF
                logger.warning("climate map %s failed: %s", key, e)
                errors.append(f"{title}: {e}")

            legend: Optional[str] = None
            try:
                legend = _b64(futures[key, "legend"].result())
            except Exception as e:  # noqa: BLE001
                logger.warning("climate legend %s failed: %s", key, e)
                errors.append(f"Legende {title}: {e}")

            panels.append({"key": key, "title": title, "image": image, "legend": legend})

    return {"panels": panels, "attribution": ATTRIBUTION, "error": " · ".join(errors) or None}
