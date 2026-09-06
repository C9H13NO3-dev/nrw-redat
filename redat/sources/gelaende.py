"""Gelände — height, Lage and slope from the 1 m digital terrain model, for the Starkregen card.

Source: Geobasis NRW WCS 2.0.1 https://www.wcs.nrw.de/geobasis/wcs_nw_dgm, coverage `nw_dgm`
(dl-de/zero-2-0). `GetCoverage&COVERAGEID=nw_dgm&SUBSET=x(<xmin>,<xmax>)&SUBSET=y(<ymin>,<ymax>)&FORMAT=image/tiff`
returns a float32 GeoTIFF, 1 px = 1 m, row 0 = north (verified 2026-09-06: 100 m box at Essen-Rüttenscheid →
100×100 px, 108.4–112.8 m NHN). The Geländeneigung WCS only serves styled RGB, so slope is derived here.
Window: HALF_M = 100 → 200×200 px (~70 KB). `_get_coverage` is the single HTTP call and monkeypatch point.
"""
from __future__ import annotations

import io
from typing import Optional

import httpx
import numpy as np
from PIL import Image
from pyproj import Transformer

from redat.http import headers

WCS_URL = "https://www.wcs.nrw.de/geobasis/wcs_nw_dgm"
COVERAGE = "nw_dgm"
HALF_M = 100
_NEAR_M = 25
_SLOPE_STEP_PX = 5
_SLOPE_STEPS_PX = (_SLOPE_STEP_PX, 2 * _SLOPE_STEP_PX, _NEAR_M)  # widen the sample if a step hits nodata
_NODATA_BELOW = -100.0
# _fetch_starkregen (redat/core/sections.py) runs this concurrently with get_starkregen's own up to
# 20 s budget, both under the "starkregen" section's 25 s run_section() timeout — kept below both so
# a slow WCS response can never by itself blank the whole card via the outer timeout.
_TIMEOUT_S = 15
_TO_25832 = Transformer.from_crs("EPSG:4326", "EPSG:25832", always_xy=True)


def _get_coverage(bbox: tuple[float, float, float, float]) -> bytes:
    """GeoTIFF bytes of the DGM inside the EPSG:25832 bbox — HTTP/monkeypatch point."""
    xmin, ymin, xmax, ymax = bbox
    params = [("SERVICE", "WCS"), ("VERSION", "2.0.1"), ("REQUEST", "GetCoverage"), ("COVERAGEID", COVERAGE),
              ("SUBSET", f"x({xmin:.0f},{xmax:.0f})"), ("SUBSET", f"y({ymin:.0f},{ymax:.0f})"), ("FORMAT", "image/tiff")]
    resp = httpx.get(WCS_URL, params=params, timeout=_TIMEOUT_S, headers=headers())
    resp.raise_for_status()
    if not resp.headers.get("content-type", "").startswith("image/tiff"):
        raise RuntimeError(f"WCS lieferte {resp.headers.get('content-type')} statt GeoTIFF: {resp.text[:160]}")
    return resp.content


def parse_dgm(tiff_bytes: bytes) -> np.ndarray:
    im = Image.open(io.BytesIO(tiff_bytes))
    im.load()
    return np.asarray(im, dtype=np.float32)


def _valid(a: np.ndarray) -> np.ndarray:
    return a[a > _NODATA_BELOW]


def _slope_pct(arr: np.ndarray, cy: int, cx: int, h: int, w: int) -> Optional[float]:
    """East/west/north/south difference quotient, widening the step when a sample hits nodata.

    Returns None (never a garbage figure) when even the widest candidate step is blocked."""
    for s in _SLOPE_STEPS_PX:
        east, west = arr[cy, min(w - 1, cx + s)], arr[cy, max(0, cx - s)]
        north, south = arr[max(0, cy - s), cx], arr[min(h - 1, cy + s), cx]
        if min(east, west, north, south) <= _NODATA_BELOW:
            continue
        dzdx = (float(east) - float(west)) / (2 * s)
        dzdy = (float(north) - float(south)) / (2 * s)
        return round(100 * float(np.hypot(dzdx, dzdy)), 1)
    return None


def analyse(arr: np.ndarray) -> dict:
    """Terrain figures for a tile whose centre pixel is the point (row 0 = north)."""
    h, w = arr.shape
    cy, cx = h // 2, w // 2
    hoehe = float(arr[cy, cx])
    if hoehe <= _NODATA_BELOW:
        raise RuntimeError("Kein Höhenwert am Standort (Nodata im DGM)")
    near = arr[max(0, cy - _NEAR_M):cy + _NEAR_M, max(0, cx - _NEAR_M):cx + _NEAR_M]
    neigung = _slope_pct(arr, cy, cx, h, w)
    all_v, near_v = _valid(arr), _valid(near)
    min100, max100 = float(all_v.min()), float(all_v.max())
    min25, max25 = float(near_v.min()), float(near_v.max())
    if neigung is not None and neigung >= 10:
        lage = "Hanglage"
    elif hoehe - min25 <= 0.3 and max100 - hoehe >= 1.5:
        lage = "Tieflage"
    elif hoehe - min100 >= 1.5 and max100 - hoehe <= 0.3:
        lage = "Kuppenlage"
    else:
        lage = "eben"
    return {
        "hoehe_m": round(hoehe, 1), "min_25m": round(min25, 1), "max_25m": round(max25, 1),
        "min_100m": round(min100, 1), "max_100m": round(max100, 1),
        "ueber_tiefstem_100m": round(hoehe - min100, 1), "unter_hoechstem_100m": round(max100 - hoehe, 1),
        "neigung_pct": neigung, "lage": lage, "radius_m": HALF_M,
    }


def get_gelaende(lat: float, lon: float) -> dict:
    x, y = _TO_25832.transform(lon, lat)
    bbox = (x - HALF_M, y - HALF_M, x + HALF_M, y + HALF_M)
    return analyse(parse_dgm(_get_coverage(bbox)))
