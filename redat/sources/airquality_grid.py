"""Long-term air-quality exposure from the EEA 1 km interpolated annual maps.

`redat/data/eea_aq_grid_2023.json` is a window of the EEA rasters cropped to
Essen/Bochum by `scripts/build_eea_aq_grid.py` (EPSG:3035, 1 km cells, values in
µg/m³, `None` for NoData). Looking a point up is a projection plus one array
index — no raster library, no network.

Reference lines: WHO Air Quality Guidelines 2021 (annual PM2.5 5, PM10 15, NO2 10;
O3 peak-season 60) and the EU Ambient Air Quality Directive 2024/2881 limit values
that apply from 2030 (annual PM2.5 10, PM10 20, NO2 20; no peak-season O3 limit).
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Optional

from pyproj import Transformer

GRID_PATH = Path(__file__).resolve().parent.parent / "data" / "eea_aq_grid_2023.json"

# layer key -> (display name, WHO AQG 2021, EU limit value from 2030)
_LAYERS = {
    "pm25": ("PM2.5", 5, 10),
    "pm10": ("PM10", 15, 20),
    "no2": ("NO2", 10, 20),
    "o3_peak": ("O3", 60, None),
}

_TO_3035 = Transformer.from_crs("EPSG:4326", "EPSG:3035", always_xy=True)
_FROM_3035 = Transformer.from_crs("EPSG:3035", "EPSG:4326", always_xy=True)


def _to_3035(lon: float, lat: float) -> tuple[float, float]:
    return _TO_3035.transform(lon, lat)


def _from_3035(x: float, y: float) -> tuple[float, float]:
    return _FROM_3035.transform(x, y)


@lru_cache(maxsize=1)
def _load() -> Optional[dict]:
    try:
        return json.loads(GRID_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def lookup(lat: float, lon: float) -> Optional[dict]:
    """Annual-mean values of the 1 km cell containing (lat, lon), or None outside
    the window / on NoData."""
    grid = _load()
    if not grid:
        return None
    x, y = _to_3035(lon, lat)
    col = int((x - grid["x0"]) // grid["cell_m"])
    row = int((grid["y0"] - y) // grid["cell_m"])
    if not (0 <= col < grid["ncols"] and 0 <= row < grid["nrows"]):
        return None
    values = {}
    for key, (name, who, eu2030) in _LAYERS.items():
        layer = grid["layers"].get(key)
        v = layer[row][col] if layer else None
        if v is not None:
            values[name] = {"value": v, "unit": "µg/m³", "who": who, "eu2030": eu2030}
    if not values:
        return None
    return {"source": grid.get("source"), "year": grid.get("year"), "resolution_km": 1, "values": values}
