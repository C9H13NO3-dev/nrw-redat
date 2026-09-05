"""Verkehrsunfälle mit Personenschaden around the point — Unfallatlas der Statistischen Ämter.

Data: redat/data/unfallatlas_2020_2025.json.gz (scripts/build_unfallatlas.py), compact rows in FIELDS
order cropped to the Essen/Bochum window. Only accidents with injured persons are recorded; the location
is the accident spot on the road, never an address. `_load` is the monkeypatch point.
"""
from __future__ import annotations

import gzip
import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Optional

GRID_PATH = Path(__file__).resolve().parent.parent / "data" / "unfallatlas_2020_2025.json.gz"
RADIUS_M = 300
SEVERITY = {1: "getoetete", 2: "schwerverletzte", 3: "leichtverletzte"}
TYPES = {1: "Fahrunfall", 2: "Abbiegeunfall", 3: "Einbiegen/Kreuzen", 4: "Überschreiten", 5: "Ruhender Verkehr", 6: "Längsverkehr", 7: "Sonstiger"}
_NIGHT = 2


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


def _rate(per_year_avg: float, fatal: int) -> tuple[str, str]:
    if per_year_avg > 15:
        rating, color = "Unfallschwerpunkt", "red"
    elif per_year_avg > 6:
        rating, color = "Viele Unfälle", "orange"
    elif per_year_avg > 2:
        rating, color = "Mäßig viele Unfälle", "yellow"
    else:
        rating, color = "Wenige Unfälle", "green"
    if fatal and color in ("green", "yellow"):
        rating, color = "Viele Unfälle", "orange"   # a fatality within 300 m outweighs a low count
    return rating, color


def lookup(lat: float, lon: float) -> Optional[dict]:
    """Accident statistics within RADIUS_M, or None outside the data window / without the grid file."""
    grid = _load()
    if not grid:
        return None
    lon_min, lat_min, lon_max, lat_max = grid["bbox"]
    if not (lon_min <= lon <= lon_max and lat_min <= lat <= lat_max):
        return None
    idx = {name: i for i, name in enumerate(grid["fields"])}
    years = [int(y) for y in grid["years"]]
    per_year = {str(y): 0 for y in years}
    severity = {v: 0 for v in SEVERITY.values()}
    beteiligt = {"rad": 0, "fuss": 0, "pkw": 0, "krad": 0, "gkfz": 0}
    by_type: dict[str, int] = {}
    nachts, nearest = 0, None
    dlat = RADIUS_M / 111_195 * 1.05
    for r in grid["rows"]:
        rlat, rlon = r[idx["lat"]], r[idx["lon"]]
        if abs(rlat - lat) > dlat:
            continue
        dist = _dist_m(lat, lon, rlat, rlon)
        if dist > RADIUS_M:
            continue
        nearest = dist if nearest is None else min(nearest, dist)
        per_year[str(r[idx["jahr"]])] = per_year.get(str(r[idx["jahr"]]), 0) + 1
        sev = SEVERITY.get(r[idx["kat"]])
        if sev:
            severity[sev] += 1
        for k in beteiligt:
            beteiligt[k] += 1 if r[idx[k]] else 0
        t = TYPES.get(r[idx["typ"]], "Sonstiger")
        by_type[t] = by_type.get(t, 0) + 1
        if r[idx["licht"]] == _NIGHT:
            nachts += 1
    total = sum(per_year.values())
    avg = round(total / len(years), 1) if years else 0.0
    rating, color = _rate(avg, severity["getoetete"])
    return {
        "radius_m": RADIUS_M, "years": years, "total": total, "per_year": per_year, "per_year_avg": avg,
        "by_severity": severity, "beteiligt": beteiligt,
        "by_type": dict(sorted(by_type.items(), key=lambda kv: -kv[1])),
        "nachts": nachts, "nearest_m": round(nearest, 1) if nearest is not None else None,
        "rating": rating, "rating_color": color,
    }
