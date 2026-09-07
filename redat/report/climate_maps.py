"""Grün-und-Hitze panels for the PDF: two tree-canopy/heat pairs, picked by whether the point falls in the RVR.

Inside the Regionalverband Ruhr box (`RVR_BBOX_WGS84`) the panels are the RVR Umweltmonitoring pair
(`RVR_PANELS`): WMS https://services-rvr.geoportal.ruhr/umon/<service> (Regionalverband Ruhr,
"lizenzkostenfrei"; verified 2026-09-06) — `veg_schirm` layer `beschirmungsgrad` (10 m, share of area under
vegetation) and `oftemp` layer `Oberflaechentemperatur_1330` with STYLE `day` (MODIS 1 km, summer median
13:30 °C). GetFeatureInfo returns no values and the legends are continuous ramps, so the layers are shown
as images with their own legend PNGs (GetLegendGraphic needs SLD_VERSION=1.1.0). 2 km window because the
temperature pixels are 1 km.

Everywhere else in NRW the panels are `NRW_PANELS`: Copernicus HRL Tree Cover Density 2018 (10 m canopy
share, EEA ImageServer WMS) and the LANUV Klimaanalyse NRW PET layer (`54`, FITNAH-3D, typical-summer-day
thermal comfort, EPSG:25832, 276 × 126 px legend). The Copernicus service (verified 2026-09-07) serves only
EPSG:3857/4326 — a 3035/25832 GetMap request comes back an empty transparent tile — so its GetMap goes out
in Web Mercator via `bbox_2km_3857`, whose metres shrink by cos(lat) at this latitude (spec §2.2); its
GetLegendGraphic is a 236 × 2040 px ramp that doesn't fit the print layout, so that panel's `Panel.legend`
is False and no legend is fetched for it.

Both variants' GetMap and GetLegendGraphic requests run concurrently in a small `ThreadPoolExecutor` — one
future per request — so the whole figure costs about one `TIMEOUT_S` in the worst case instead of stacking
up sequential timeouts. `_get_png` is the HTTP/monkeypatch point. `WIDTH`, `HEIGHT`, `bbox_2km`, `decorate`
are also imported by `regionalplan_map.py` — their names and signatures are a stable seam.
"""
from __future__ import annotations

import base64
import io
import logging
import math
from concurrent.futures import ThreadPoolExecutor
from typing import NamedTuple, Optional

import httpx
from PIL import Image, ImageDraw
from pyproj import Transformer

from redat.core.nrw import RVR_BBOX_WGS84, in_bbox
from redat.http import headers
from redat.report.noise_map import title_font

logger = logging.getLogger(__name__)

WIDTH, HEIGHT = 480, 360
WINDOW_M = 2000.0
TIMEOUT_S = 10.0

RVR_BASE = "https://services-rvr.geoportal.ruhr/umon/"
HRL_URL = "https://image.discomap.eea.europa.eu/arcgis/services/GioLandPublic/HRL_TreeCoverDensity_2018/ImageServer/WMSServer"
KLIMA_URL = "https://www.wms.nrw.de/umwelt/klimaanpassung_klimaanalyse"


class Panel(NamedTuple):
    key: str
    title: str
    url: str
    layer: str
    style: str
    crs: str            # "EPSG:25832" (bbox_2km) or "EPSG:3857" (bbox_2km_3857)
    legend: bool        # False when the service's GetLegendGraphic is unusable in print (Copernicus: 236 × 2040 px ramp)


RVR_PANELS = (
    Panel("beschirmung", "Beschirmungsgrad (Baumkronen)", RVR_BASE + "veg_schirm", "beschirmungsgrad", "default", "EPSG:25832", True),
    Panel("oberflaechentemperatur", "Oberflächentemperatur 13:30 Uhr (Sommer)", RVR_BASE + "oftemp", "Oberflaechentemperatur_1330", "day", "EPSG:25832", True),
)
NRW_PANELS = (
    Panel("baumkronen", "Baumkronendichte 2018 (Copernicus, 10 m)", HRL_URL, "HRL_TreeCoverDensity_2018:TCD_MosaicSymbology", "", "EPSG:3857", False),
    Panel("pet", "Thermische Belastung (PET), typischer Sommertag", KLIMA_URL, "54", "", "EPSG:25832", True),
)
ATTRIBUTIONS = {
    "rvr": "© Regionalverband Ruhr, Umweltmonitoring (Beschirmungsgrad 10 m; Oberflächentemperatur MODIS 1 km, Sommer-Median)",
    "nrw": "© Copernicus Land Monitoring Service, HRL Tree Cover Density 2018 (10 m, Anteil Baumkronen 0–100 %, dunkler = dichter) · LANUV Klimaanalyse NRW 2026 (FITNAH-3D, PET tags, typischer Sommertag)",
}
_MAX_WORKERS = 4  # at most 2 panels × (GetMap + GetLegendGraphic) in flight; the NRW variant only submits 3 (no Copernicus legend)
_TO_UTM = Transformer.from_crs("EPSG:4326", "EPSG:25832", always_xy=True)
_TO_MERC = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)


def bbox_2km(lat: float, lon: float) -> tuple[float, float, float, float]:
    x, y = _TO_UTM.transform(lon, lat)
    hw, hh = WINDOW_M / 2, WINDOW_M * HEIGHT / WIDTH / 2
    return x - hw, y - hh, x + hw, y + hh


def bbox_2km_3857(lat: float, lon: float) -> tuple[float, float, float, float]:
    """The same 2 km × 1.5 km ground window in Web Mercator, whose metres shrink by cos(lat)."""
    x, y = _TO_MERC.transform(lon, lat)
    k = 1.0 / math.cos(math.radians(lat))
    hw, hh = WINDOW_M / 2 * k, WINDOW_M * HEIGHT / WIDTH / 2 * k
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


def _fetch_map(url: str, bbox, layer: str, style: str, crs: str = "EPSG:25832") -> Image.Image:
    raw = _get_png(url, {"SERVICE": "WMS", "VERSION": "1.3.0", "REQUEST": "GetMap", "CRS": crs,
                         "BBOX": ",".join(f"{v:.3f}" for v in bbox), "WIDTH": WIDTH, "HEIGHT": HEIGHT,
                         "FORMAT": "image/png", "LAYERS": layer, "STYLES": style, "TRANSPARENT": "TRUE"})
    im = Image.open(io.BytesIO(raw))
    im.load()
    return im.convert("RGBA").resize((WIDTH, HEIGHT))


def _fetch_legend(url: str, layer: str, style: str) -> bytes:
    return _get_png(url, {"SERVICE": "WMS", "VERSION": "1.3.0", "REQUEST": "GetLegendGraphic", "LAYER": layer,
                          "FORMAT": "image/png", "STYLE": style, "SLD_VERSION": "1.1.0"})


def render_climate_maps(lat: float, lon: float) -> dict:
    variant = "rvr" if in_bbox(lat, lon, RVR_BBOX_WGS84) else "nrw"
    panels_def = RVR_PANELS if variant == "rvr" else NRW_PANELS
    bboxes = {"EPSG:25832": bbox_2km(lat, lon), "EPSG:3857": bbox_2km_3857(lat, lon)}
    errors: list[str] = []

    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as ex:
        futures = {}
        for p in panels_def:
            futures[p.key, "map"] = ex.submit(_fetch_map, p.url, bboxes[p.crs], p.layer, p.style, p.crs)
            if p.legend:
                futures[p.key, "legend"] = ex.submit(_fetch_legend, p.url, p.layer, p.style)

        panels = []
        for p in panels_def:
            image: Optional[str] = None
            try:
                im = futures[p.key, "map"].result()
                buf = io.BytesIO()
                # WMS layers are transparent where they have no data (Copernicus outside tree cover); flatten onto
                # white so the print shows "no trees" as white, not black.
                white = Image.new("RGBA", im.size, (255, 255, 255, 255))
                Image.alpha_composite(white, decorate(im, p.title)).convert("RGB").save(buf, format="PNG", optimize=True)
                image = _b64(buf.getvalue())
            except Exception as e:  # noqa: BLE001 — a missing panel is a placeholder, never a failed PDF
                logger.warning("climate map %s failed: %s", p.key, e)
                errors.append(f"{p.title}: {e}")

            legend: Optional[str] = None
            if p.legend:
                try:
                    legend = _b64(futures[p.key, "legend"].result())
                except Exception as e:  # noqa: BLE001
                    logger.warning("climate legend %s failed: %s", p.key, e)
                    errors.append(f"Legende {p.title}: {e}")

            panels.append({"key": p.key, "title": p.title, "image": image, "legend": legend})

    return {"variant": variant, "panels": panels, "attribution": ATTRIBUTIONS[variant], "error": " · ".join(errors) or None}
