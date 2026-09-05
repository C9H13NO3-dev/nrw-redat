"""Pluvial-flood ("Starkregen") exposure for a point, from the BKG
Hinweiskarte Starkregengefahren WMS — https://sgx.geodatenzentrum.de/wms_starkregen
(WMS 1.3.0, licence dl-de/by-2-0).

The NRW layers are a 1 m hydraulic model of two rain events with buildings
blanked out: `nw_tiefe_agw` / `nw_geschw_agw` (water depth / flow velocity for
the "außergewöhnliches Ereignis", the 100-year KOSTRA rain, D = 60 min) and
`nw_tiefe_extrem` / `nw_geschw_extrem` (90 mm/h extreme event). The model has no
sewer network, so it is a hint map, not a prediction. The obsolete
`wasserhoehen_*` / `fliessgeschwindigkeiten_*` layers were switched off in 2026.

Rather than GetFeatureInfo on one pixel, we fetch a small GetMap tile around
the point and count pixels by legend colour: the question a buyer has is "what
is the worst depth within ~50 m and how much of the surroundings is wet",
including the street in front of the house. The colours below are the fixed
style of the service (extracted from GetLegendGraphic 2026-09-04); a
transparent white pixel is the lowest class, a transparent black one is a
building or no-data.

`_get_tile` is the single HTTP call and the monkeypatch point.
"""
from __future__ import annotations

import io
import logging
import math
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import httpx
from PIL import Image

from redat.http import headers

logger = logging.getLogger(__name__)

WMS_URL = "https://sgx.geodatenzentrum.de/wms_starkregen"
_TIMEOUT_S = 20.0

# (rgb, label, lower class edge) in legend order; index 0 is the transparent "nothing" colour
DEPTH_CLASSES = [
    ((255, 255, 255), "< 10 cm", 0),
    ((204, 236, 255), "10–30 cm", 10),
    ((153, 204, 255), "30–50 cm", 30),
    ((110, 153, 255), "50–100 cm", 50),
    ((61, 102, 255), "1–2 m", 100),
    ((0, 51, 204), "2–4 m", 200),
    ((8, 48, 107), "> 4 m", 400),
]
VELOCITY_CLASSES = [
    ((255, 255, 255), "< 0,2 m/s", 0.0),
    ((255, 255, 178), "0,2–0,5 m/s", 0.2),
    ((254, 204, 92), "0,5–1 m/s", 0.5),
    ((253, 141, 60), "1–2 m/s", 1.0),
    ((227, 26, 28), "> 2 m/s", 2.0),
]
BUILDING_RGB = (0, 0, 0)
# Outside the NRW layer extent the WMS answers transparent white, i.e. "dry" — guard by the
# layer's EX_GeographicBoundingBox (GetCapabilities 2026-09-04) so Berlin is None, not "Gering".
NRW_BBOX = (5.753, 50.242, 9.589, 52.619)  # west, south, east, north
# A depth class counts towards `max` only if at least this share of the open (non-building)
# area lies at that depth or deeper (~200 m² of a 100 m tile) — otherwise a single gully or
# kerb pocket would set the rating. Calibrated on seven Essen/Bochum points 2026-09-04.
_MIN_CLASS_SHARE = 0.02

SCENARIOS = {
    "agw": {"depth": "nw_tiefe_agw", "velocity": "nw_geschw_agw",
            "label": "Seltenes Ereignis (100-jährlich)"},
    "extrem": {"depth": "nw_tiefe_extrem", "velocity": "nw_geschw_extrem",
               "label": "Extremereignis (90 mm/h)"},
}


def _getmap_params(layer: str, lat: float, lon: float, half_m: float, px: int) -> dict:
    dlat = half_m / 111_320
    dlon = half_m / (111_320 * math.cos(math.radians(lat)))
    return {
        "SERVICE": "WMS", "VERSION": "1.3.0", "REQUEST": "GetMap", "LAYERS": layer, "STYLES": "",
        "CRS": "EPSG:4326",  # WMS 1.3.0 + EPSG:4326 => BBOX is lat,lon order
        "BBOX": f"{lat - dlat},{lon - dlon},{lat + dlat},{lon + dlon}",
        "WIDTH": px, "HEIGHT": px, "FORMAT": "image/png", "TRANSPARENT": "TRUE",
    }


def _get_tile(layer: str, lat: float, lon: float, half_m: float, px: int) -> Image.Image:
    resp = httpx.get(WMS_URL, params=_getmap_params(layer, lat, lon, half_m, px), timeout=_TIMEOUT_S, headers=headers())
    resp.raise_for_status()
    return Image.open(io.BytesIO(resp.content)).convert("RGBA")


def _count_classes(img: Image.Image, classes: list) -> tuple[dict, int, int]:
    """(pixels per class label, building/no-data pixels, unrecognised pixels)."""
    by_rgb = {rgb: label for rgb, label, _ in classes}
    counts: Counter = Counter()
    buildings = ignored = 0
    pixels = img.get_flattened_data() if hasattr(img, "get_flattened_data") else img.getdata()
    for (r, g, b, a), n in Counter(pixels).items():
        rgb = (r, g, b)
        if a == 0 and rgb == BUILDING_RGB:
            buildings += n
        elif rgb in by_rgb:
            counts[by_rgb[rgb]] += n
        else:
            ignored += n
    return dict(counts), buildings, ignored


def _max_class(counts: dict, classes: list, min_share: float = _MIN_CLASS_SHARE) -> Optional[tuple]:
    """Worst class whose cumulative share (that class and worse) reaches min_share."""
    total = sum(counts.values())
    if not total:
        return None
    cum = 0
    for cls in reversed(classes):
        cum += counts.get(cls[1], 0)
        if cum / total >= min_share:
            return cls
    return classes[0]


def _summarize(depth: Image.Image, velocity: Optional[Image.Image]) -> Optional[dict]:
    counts, buildings, _ = _count_classes(depth, DEPTH_CLASSES)
    total = sum(counts.values())
    if not total:
        return None
    worst = _max_class(counts, DEPTH_CLASSES)
    lowest = DEPTH_CLASSES[0][1]
    out = {
        "max": {"label": worst[1], "cm": worst[2]},
        "shares": {label: round(n / total, 3) for _, label, _ in DEPTH_CLASSES if (n := counts.get(label))},
        "wet_share": round((total - counts.get(lowest, 0)) / total, 3),
        "velocity_max": None,
        "building_pixels": buildings,
        "pixels": total,
    }
    if velocity is not None:
        vcounts, _, _ = _count_classes(velocity, VELOCITY_CLASSES)
        vworst = _max_class(vcounts, VELOCITY_CLASSES)
        if vworst:
            out["velocity_max"] = {"label": vworst[1], "mps": vworst[2]}
    return out


def _rate(agw_cm: Optional[int], extrem_cm: Optional[int]) -> tuple[str, str]:
    """Worst depth class within the tile; the extreme event counts one step
    softer than the 100-year one."""
    if agw_cm is None and extrem_cm is None:
        return "unbekannt", "gray"
    a, e = agw_cm or 0, extrem_cm or 0
    if a >= 50 or e >= 100:
        return "Hoch", "red"
    if a >= 30 or e >= 50:
        return "Erhöht", "orange"
    if a >= 10 or e >= 30:
        return "Mäßig", "yellow"
    return "Gering", "green"


def get_starkregen(lat: float, lon: float, half_m: float = 50, px: int = 100) -> Optional[dict]:
    """Depth/velocity summary per scenario within ±half_m of the point, or None
    when both depth tiles are entirely buildings/no-data (outside NRW)."""
    west, south, east, north = NRW_BBOX
    if not (west <= lon <= east and south <= lat <= north):
        return None
    layers = [sc[k] for sc in SCENARIOS.values() for k in ("depth", "velocity")]
    tiles, errors = {}, {}
    with ThreadPoolExecutor(max_workers=len(layers), thread_name_prefix="starkregen") as pool:
        futures = {layer: pool.submit(_get_tile, layer, lat, lon, half_m, px) for layer in layers}
        for layer, fut in futures.items():
            try:
                tiles[layer] = fut.result()
            except Exception as e:
                if layer.startswith("nw_tiefe"):
                    raise
                logger.warning("starkregen velocity layer %s failed: %s", layer, e)
                errors[layer] = str(e)

    scenarios = {}
    building_px = total_px = 0
    for key, sc in SCENARIOS.items():
        s = _summarize(tiles[sc["depth"]], tiles.get(sc["velocity"]))
        if s:
            building_px += s.pop("building_pixels")
            total_px += s.pop("pixels")
        scenarios[key] = {"label": sc["label"], **s} if s else None
    if not any(scenarios.values()):
        return None
    rating, color = _rate(*((scenarios[k] or {}).get("max", {}).get("cm") for k in ("agw", "extrem")))
    return {
        "radius_m": half_m,
        "building_share": round(building_px / (building_px + total_px), 3) if building_px + total_px else 0.0,
        "scenarios": scenarios,
        "rating": rating, "rating_color": color,
        "errors": errors,
    }
