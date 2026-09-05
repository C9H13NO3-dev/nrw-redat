"""Noise levels from the NRW Umgebungslärmkartierung 2022 WMS, sampled over a small window.

Why a window and not the point (fixed 2026-09-05): the Lärmkartierung raster leaves
building footprints unrendered, so a GetFeatureInfo at a geocoded address regularly
lands on the house itself and reports NoData/"class 0" while the ≥ 75 dB street band
sits a few metres away (Brückstraße 12, Essen-Werden was the live case). A single
pixel also mislabelled class 0 (`50113000;0`, "< 55 dB" for L_DEN) as a 50–54 band
the day legend does not have. So instead we fetch one GetMap tile per source layer
and period — WINDOW_M × WINDOW_M metres at 1 m/px around the point, EPSG:25832 —
and take the **worst legend band present anywhere in the tile**: the loudest
mapped level within ~12 m of the address, which is what reaches the façade.
Unrendered (transparent) pixels are below the mapping threshold (< 55 dB L_DEN /
< 50 dB L_night) or a building.

Legend colours captured 2026-09-04 via GetLegendGraphic (identical for all five
sources; L_night starts one class lower with the 50–54 band). Verified against a
live tile at Werden: 117 of 625 px in the ≥ 75 band by day, 65–69 by night, centre
transparent.
"""
from __future__ import annotations

import io
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import httpx
from PIL import Image, UnidentifiedImageError
from pyproj import Transformer

from redat.http import headers

WMS_URL = "https://www.wms.nrw.de/umwelt/laerm"
SOURCES = ("str", "scb", "scs", "ind", "flg")
SOURCE_LABELS = {"str": "Straße", "scb": "Schiene (Bund)", "scs": "Schiene (Stadt)", "ind": "Industrie", "flg": "Flughafen"}
_PERIOD_CODE = {"day": "DEN", "night": "NGT"}
_TOP_BAND = {"day": 75, "night": 70}

WINDOW_M = 25.0      # tile edge in metres, centred on the point → ±12.5 m
TILE_PX = 25         # 1 m/px; the raster itself is coarser, so this only avoids aliasing
_TIMEOUT_S = 15.0
_WORKERS = 5         # 10 tiles per call, fetched concurrently

# legend RGB → band lower edge in dB(A)
_BAND_COLOURS = {
    (184, 214, 209): 50,   # L_night only
    (226, 242, 191): 55,
    (243, 198, 131): 60,
    (205, 70, 62): 65,
    (117, 8, 92): 70,
    (67, 10, 74): 75,
}
_COLOUR_TOLERANCE_SQ = 12 ** 2   # squared euclidean RGB distance; anything farther is not a band
_MIN_ALPHA = 128

_TO_UTM = Transformer.from_crs("EPSG:4326", "EPSG:25832", always_xy=True)


def _fetch_png(params: dict) -> bytes:
    """The single HTTP call — monkeypatched in tests."""
    resp = httpx.get(WMS_URL, params=params, timeout=_TIMEOUT_S, headers=headers())
    resp.raise_for_status()
    return resp.content


def _getmap_params(lat: float, lon: float, layer: str) -> dict:
    x, y = _TO_UTM.transform(lon, lat)
    h = WINDOW_M / 2
    return {
        "SERVICE": "WMS", "VERSION": "1.3.0", "REQUEST": "GetMap",
        "LAYERS": layer, "STYLES": "",  # STYLES is mandatory for this server
        "CRS": "EPSG:25832", "BBOX": f"{x - h:.2f},{y - h:.2f},{x + h:.2f},{y + h:.2f}",
        "WIDTH": TILE_PX, "HEIGHT": TILE_PX,
        "FORMAT": "image/png", "TRANSPARENT": "TRUE",
    }


def _band_of(rgba: tuple) -> Optional[int]:
    r, g, b, a = rgba
    if a < _MIN_ALPHA:
        return None
    best, best_d = None, _COLOUR_TOLERANCE_SQ + 1
    for (cr, cg, cb), db in _BAND_COLOURS.items():
        d = (r - cr) ** 2 + (g - cg) ** 2 + (b - cb) ** 2
        if d < best_d:
            best, best_d = db, d
    return best


def parse_tile(png: bytes) -> Optional[int]:
    """Worst legend band (dB lower edge) present in a GetMap tile, None if nothing is mapped.

    Raises ValueError when the body is not an image (WMS ServiceException etc.).
    """
    try:
        im = Image.open(io.BytesIO(png)).convert("RGBA")
    except (UnidentifiedImageError, OSError) as e:
        raise ValueError(f"WMS did not return an image: {png[:80]!r}") from e
    worst = None
    for _count, rgba in im.getcolors(maxcolors=im.width * im.height) or []:
        band = _band_of(rgba)
        if band is not None and (worst is None or band > worst):
            worst = band
    return worst


def band_label(db_min: int, period: str) -> str:
    if db_min >= _TOP_BAND[period]:
        return f"ab {db_min} dB(A)"
    return f"ab {db_min} bis {db_min + 4} dB(A)"


def get_noise_levels(lat: float, lon: float) -> dict:
    """{"day", "night", "sources", "below_threshold", "window_m"} — see module docstring."""
    jobs = [(src, period, f"{src.upper()}_{code}") for src in SOURCES for period, code in _PERIOD_CODE.items()]
    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        bands = list(pool.map(lambda j: parse_tile(_fetch_png(_getmap_params(lat, lon, j[2]))), jobs))
    sources = {s: {p: None for p in _PERIOD_CODE} for s in SOURCES}
    for (src, period, _layer), band in zip(jobs, bands):
        sources[src][period] = band

    def loudest(period: str) -> Optional[dict]:
        hits = [(v[period], s) for s, v in sources.items() if v[period] is not None]
        if not hits:
            return None
        db_min, src = max(hits)
        return {"db_min": db_min, "label": band_label(db_min, period), "source": src}

    day, night = loudest("day"), loudest("night")
    return {
        "day": day,
        "night": night,
        "sources": sources,
        "below_threshold": day is None and night is None,
        "window_m": WINDOW_M,
    }
