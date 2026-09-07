"""Bodenbewegung — Copernicus EGMS vertical ground velocity (InSAR, 100 m grid) at the point.

Data: redat/data/egms_vertical_velocity_nrw.npz, statewide raster, see scripts/build_egms.py.
mm/year, positive = Hebung (Grubenwasseranstieg shows as uplift in the Ruhrgebiet), negative = Senkung.
Classes on |v|: < 2 stabil (green), 2–5 leichte Bewegung (yellow), 5–10 deutliche Bewegung (orange), > 10 starke
Bewegung (red). `_load` is the monkeypatch point.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Optional

import numpy as np
from pyproj import Transformer

GRID_PATH = Path(__file__).resolve().parent.parent / "data" / "egms_vertical_velocity_nrw.npz"
NODATA = -32768
_TO_3035 = Transformer.from_crs("EPSG:4326", "EPSG:3035", always_xy=True)
_RING_500M = 5   # cells on each side → 11×11 = ±550 m


@lru_cache(maxsize=1)
def _load() -> Optional[dict]:
    try:
        with np.load(GRID_PATH, allow_pickle=False) as z:
            meta = json.loads(str(z["meta"]))
            return {"v": z["v"], "x0": int(meta["x0"]), "y1": int(meta["y1"]), "cell_m": int(meta["cell_m"]),
                    "years": meta.get("years"), "scale": int(meta.get("scale", 100))}
    except (OSError, ValueError, KeyError):
        return None


def classify(v: float) -> tuple[str, str]:
    a = abs(v)
    if a > 10:
        return "starke Bewegung", "red"
    if a > 5:
        return "deutliche Bewegung", "orange"
    if a >= 2:
        return "leichte Bewegung", "yellow"
    return "stabil", "green"


def lookup(lat: float, lon: float) -> Optional[dict]:
    grid = _load()
    if not grid:
        return None
    v, cell, scale = grid["v"], grid["cell_m"], grid["scale"]
    nrows, ncols = v.shape
    x, y = _TO_3035.transform(lon, lat)
    col, row = int((x - grid["x0"]) // cell), int((grid["y1"] - y) // cell)
    if not (0 <= row < nrows and 0 <= col < ncols):
        return None

    def get(dx: int, dy: int) -> Optional[float]:
        r, c = row - dy, col + dx
        if not (0 <= r < nrows and 0 <= c < ncols):
            return None
        raw = int(v[r, c])
        return None if raw == NODATA else round(raw / scale, 2)

    centre = get(0, 0)
    if centre is None:
        return None
    near = [w for dx in (-1, 0, 1) for dy in (-1, 0, 1) if (w := get(dx, dy)) is not None]
    ring = [w for dx in range(-_RING_500M, _RING_500M + 1) for dy in range(-_RING_500M, _RING_500M + 1) if (w := get(dx, dy)) is not None]
    klasse, color = classify(centre)
    return {
        "mm_a": centre, "mean_3x3": round(sum(near) / len(near), 2), "min_500m": min(ring), "max_500m": max(ring),
        "klasse": klasse, "klasse_color": color, "richtung": "Hebung" if centre > 0 else "Senkung" if centre < 0 else "keine",
        "years": grid.get("years"), "cell_m": cell,
    }
