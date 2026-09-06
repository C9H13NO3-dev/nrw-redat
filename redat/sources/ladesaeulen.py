"""Öffentliche E-Ladepunkte im Umkreis — BNetzA Ladesäulenregister (CC BY 4.0), cropped to Essen/Bochum.

Data: redat/data/ladesaeulen.json.gz (scripts/build_ladesaeulen.py), rows in FIELDS order; only chargers
"In Betrieb". `_load` is the monkeypatch point.
"""
from __future__ import annotations

import gzip
import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Optional

GRID_PATH = Path(__file__).resolve().parent.parent / "data" / "ladesaeulen.json.gz"
RADIUS_M = 1000
_NEAR_M = 500
_WALK_M = 300
_MAX_NEAREST = 5


@lru_cache(maxsize=1)
def _load() -> Optional[dict]:
    try:
        with gzip.open(GRID_PATH, "rt", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _dist_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    k = math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot((lat2 - lat1) * 111_195, (lon2 - lon1) * 111_195 * k)


def _rate(nearest_m: Optional[float]) -> tuple[str, str]:
    if nearest_m is not None and nearest_m <= _WALK_M:
        return "Ladepunkt in Gehweite", "green"
    if nearest_m is not None:
        return "Ladepunkt im Umkreis", "yellow"
    return "Kein öffentlicher Ladepunkt im Umkreis von 1 km", "orange"


def lookup(lat: float, lon: float) -> Optional[dict]:
    grid = _load()
    if not grid:
        return None
    lon_min, lat_min, lon_max, lat_max = grid["bbox"]
    if not (lon_min <= lon <= lon_max and lat_min <= lat <= lat_max):
        return None
    idx = {n: i for i, n in enumerate(grid["fields"])}
    hits = []
    for r in grid["rows"]:
        d = _dist_m(lat, lon, r[idx["lat"]], r[idx["lon"]])
        if d <= RADIUS_M:
            hits.append((d, r))
    hits.sort(key=lambda t: t[0])
    naechste = [{"betreiber": r[idx["betreiber"]], "distance_m": round(d), "punkte": r[idx["punkte"]], "kw": r[idx["kw"]],
                 "schnell": bool(r[idx["schnell"]]), "adresse": r[idx["adresse"]]} for d, r in hits[:_MAX_NEAREST]]
    rating, color = _rate(hits[0][0] if hits else None)
    return {
        "radius_m": RADIUS_M, "stand": grid.get("stand"),
        "anzahl_500m": sum(1 for d, _ in hits if d <= _NEAR_M), "anzahl_1000m": len(hits),
        "ladepunkte_1000m": sum(r[idx["punkte"]] for _, r in hits), "schnell_1000m": sum(1 for _, r in hits if r[idx["schnell"]]),
        "naechste": naechste, "rating": rating, "rating_color": color,
    }
