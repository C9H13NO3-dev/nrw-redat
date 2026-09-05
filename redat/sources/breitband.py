"""Breitbandatlas (BNetzA) — fixed-line coverage and 5G per 100 m cell.

Source: Breitbandatlas WMS, https://breitbandatlas-wms.gigabit-grundbuch.online/WMS/Breitbandatlas
(Gigabit-Grundbuch, © BNetzA, Datenstand 12.2025). The service has no queryable
layers, so a GetFeatureInfo is impossible — instead we render a tiny GetMap
tile at the centre of the 100 m INSPIRE cell (EPSG:3035, the same grid the
Zensus uses) and read the legend colour, exactly like ``redat.sources.starkregen``.

Fixed-line layers show the share of households in the cell that can get the
named bandwidth (five legend classes, > 95 % … 0–10 %); the mobile layers are a
single colour for 5G and a lighter one for 5G via national roaming. Dark pixels
are the cell-border lines and are ignored; a fully transparent tile means "no
households / outside Germany".

TLS: the host serves a Let's Encrypt *YE2* leaf without its chain, and the 2026
*ISRG Root YE* is only cross-signed by ISRG Root X2, so the system store alone
cannot verify it. ``redat/data/certs/lencr_ye_chain.pem`` carries the two public
issuer certificates (fetched from LE's own AIA URLs) and is loaded on top of
the default context — never ``verify=False``.
"""
from __future__ import annotations

import io
import logging
import ssl
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path
from typing import Optional

import httpx
from PIL import Image
from pyproj import Transformer

from redat.http import headers

logger = logging.getLogger(__name__)

WMS_URL = "https://breitbandatlas-wms.gigabit-grundbuch.online/WMS/Breitbandatlas"
CA_BUNDLE = Path(__file__).resolve().parent.parent / "data" / "certs" / "lencr_ye_chain.pem"
DATENSTAND = "12.2025"
ATTRIBUTION = "© BNetzA, Breitbandatlas — Datenstand 12.2025"
_TIMEOUT_S = 20
_TILE_PX = 21
_HALF_DEG = 0.0001  # ± around the cell centre — well inside one 100 m cell

# Layer names are exact (numeric suffixes included) — verified against the capabilities 2026-09-04.
FIXED_LAYERS = {
    "ftth_1000": "Breitband_Festnetz__100m_Gitter__Glasfaser_(FTTB/H)_≥_1000_Mbit/s44392",
    "hh_1000": "Breitband_Festnetz__100m_Gitter__Privathaushalte_≥_1000_Mbit/s41271",
    "hh_400": "Breitband_Festnetz__100m_Gitter__Privathaushalte_≥_400_Mbit/s56938",
    "hh_100": "Breitband_Festnetz__100m_Gitter__Privathaushalte_≥_100_Mbit/s49615",
}
MOBILE_LAYERS = {
    "telekom": "Breitband_Mobilfunk__Fläche__100m_Gitter__Telekom_5G32661",
    "vodafone": "Breitband_Mobilfunk_Fläche__100m_Gitter__Vodafone_5G65414",
    "o2": "Breitband_Mobilfunk_Fläche__100m_Gitter__Telefónica_5G50216",
    "1u1": "Breitband_Mobilfunk__Fläche__100m_Gitter__1u1_5G51009",
}
# Legend "Breitbandverfügbarkeit in % der Haushalte": (rgb, label, lower bound %, step 5..1)
COVERAGE_CLASSES = [
    ((51, 111, 145), "> 95 %", 95, 5),
    ((102, 179, 185), "75 – 95 %", 75, 4),
    ((204, 230, 232), "50 – 75 %", 50, 3),
    ((252, 228, 177), "10 – 50 %", 10, 2),
    ((254, 249, 216), "0 – 10 %", 0, 1),
]
MOBILE_CLASSES = [
    ((247, 187, 61), "5G"),
    ((251, 221, 158), "5G-Roaming"),
]

_TO_3035 = Transformer.from_crs("EPSG:4326", "EPSG:3035", always_xy=True)
_TO_4326 = Transformer.from_crs("EPSG:3035", "EPSG:4326", always_xy=True)


def cell_center(lat: float, lon: float) -> tuple[float, float]:
    """Centre (lat, lon) of the 100 m EPSG:3035 grid cell containing the point."""
    x, y = _TO_3035.transform(lon, lat)
    cx, cy = (x // 100) * 100 + 50, (y // 100) * 100 + 50
    lon2, lat2 = _TO_4326.transform(cx, cy)
    return lat2, lon2


@lru_cache(maxsize=1)
def _ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.load_verify_locations(cafile=str(CA_BUNDLE))
    return ctx


def _get_tile(layer: str, lat: float, lon: float) -> Image.Image:
    """One GetMap tile around (lat, lon) — the single HTTP/monkeypatch point."""
    r = _HALF_DEG
    params = {
        "SERVICE": "WMS", "VERSION": "1.3.0", "REQUEST": "GetMap", "LAYERS": layer, "STYLES": "",
        "CRS": "EPSG:4326", "BBOX": f"{lat - r},{lon - r},{lat + r},{lon + r}",
        "WIDTH": _TILE_PX, "HEIGHT": _TILE_PX, "FORMAT": "image/png", "TRANSPARENT": "TRUE",
    }
    resp = httpx.get(WMS_URL, params=params, timeout=_TIMEOUT_S, verify=_ssl_context(),
                     headers=headers())
    resp.raise_for_status()
    return Image.open(io.BytesIO(resp.content)).convert("RGBA")


def _dominant(img: Image.Image, palette: list[tuple]) -> Optional[tuple]:
    """The palette entry (rgb first) with the most opaque pixels; None when no palette colour is present."""
    pixels = img.get_flattened_data() if hasattr(img, "get_flattened_data") else img.getdata()
    counts = Counter(px[:3] for px in pixels if px[3] > 0)
    best, best_n = None, 0
    for entry in palette:
        n = counts.get(entry[0], 0)
        if n > best_n:
            best, best_n = entry, n
    return best


def _rate(fixed: dict) -> tuple[str, str]:
    def pct(key):
        v = fixed.get(key)
        return v["min_pct"] if v else -1
    if pct("ftth_1000") >= 75:
        return "Glasfaser verfügbar", "green"
    if pct("ftth_1000") >= 10:
        return "Glasfaser teilweise", "yellow"
    if pct("hh_1000") >= 75:
        return "Gigabit (Kabel), kein Glasfaser", "yellow"
    if pct("hh_100") >= 75:
        return "≥ 100 Mbit/s, kein Gigabit", "orange"
    return "Unterversorgt", "red"


def get_breitband(lat: float, lon: float) -> Optional[dict]:
    """Coverage classes + 5G per operator for the 100 m cell; None when the atlas has no data there."""
    clat, clon = cell_center(lat, lon)
    jobs = {**{k: (layer, COVERAGE_CLASSES) for k, layer in FIXED_LAYERS.items()},
            **{k: (layer, MOBILE_CLASSES) for k, layer in MOBILE_LAYERS.items()}}

    def one(key):
        layer, palette = jobs[key]
        return key, _dominant(_get_tile(layer, clat, clon), palette)

    results, errors = {}, {}
    with ThreadPoolExecutor(max_workers=len(jobs)) as ex:
        for key, fut in [(k, ex.submit(one, k)) for k in jobs]:
            try:
                results[key] = fut.result()[1]
            except Exception as e:  # noqa: BLE001 — one layer must not blank the card
                logger.warning("breitband layer %s failed: %s", key, e)
                errors[key] = str(e)
                results[key] = None
    if len(errors) == len(jobs):
        raise RuntimeError(f"Breitbandatlas nicht erreichbar: {errors['ftth_1000']}")

    fixed = {k: ({"label": v[1], "min_pct": v[2], "step": v[3]} if v else None)
             for k, v in results.items() if k in FIXED_LAYERS}
    mobile = {k: (v[1] if v else None) for k, v in results.items() if k in MOBILE_LAYERS}
    if all(v is None for v in fixed.values()) and not errors:
        return None
    rating, color = _rate(fixed)
    return {
        "cell_m": 100, "datenstand": DATENSTAND, "attribution": ATTRIBUTION,
        "cell_center": {"lat": round(clat, 6), "lon": round(clon, 6)},
        "fixed": fixed, "mobile_5g": mobile,
        "rating": rating, "rating_color": color, "errors": errors,
    }
