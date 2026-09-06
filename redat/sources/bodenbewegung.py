"""Bodenbewegung — Copernicus EGMS vertical ground velocity (InSAR, 100 m grid) at the point.

Data: redat/data/egms_vertical_velocity.json.gz (scripts/build_egms.py; a free EU-Login download, see the script).
mm/year, positive = Hebung (Grubenwasseranstieg shows as uplift in the Ruhrgebiet), negative = Senkung.
Classes on |v|: < 2 stabil (green), 2–5 leichte Bewegung (yellow), 5–10 deutliche Bewegung (orange), > 10 starke
Bewegung (red). `_load` is the monkeypatch point.
"""
from __future__ import annotations

import gzip
import json
from functools import lru_cache
from pathlib import Path
from typing import Optional

from pyproj import Transformer

GRID_PATH = Path(__file__).resolve().parent.parent / "data" / "egms_vertical_velocity.json.gz"
_TO_3035 = Transformer.from_crs("EPSG:4326", "EPSG:3035", always_xy=True)
_RING_500M = 5   # cells on each side → 11×11 = ±550 m


@lru_cache(maxsize=1)
def _load() -> Optional[dict]:
    try:
        with gzip.open(GRID_PATH, "rt", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
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
    cell = int(grid.get("cell_m") or 100)
    cells = grid.get("cells") or {}
    x, y = _TO_3035.transform(lon, lat)
    cx, cy = int(x // cell) * cell + cell // 2, int(y // cell) * cell + cell // 2

    def get(dx: int, dy: int) -> Optional[float]:
        return cells.get(f"{cx + dx * cell}_{cy + dy * cell}")

    centre = get(0, 0)
    if centre is None:
        return None
    near = [v for dx in (-1, 0, 1) for dy in (-1, 0, 1) if (v := get(dx, dy)) is not None]
    ring = [v for dx in range(-_RING_500M, _RING_500M + 1) for dy in range(-_RING_500M, _RING_500M + 1) if (v := get(dx, dy)) is not None]
    klasse, color = classify(centre)
    return {
        "mm_a": centre, "mean_3x3": round(sum(near) / len(near), 2), "min_500m": min(ring), "max_500m": max(ring),
        "klasse": klasse, "klasse_color": color, "richtung": "Hebung" if centre > 0 else "Senkung" if centre < 0 else "keine",
        "years": grid.get("years"), "cell_m": cell,
    }
