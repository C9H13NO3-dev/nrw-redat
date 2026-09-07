"""Öffentliche E-Ladepunkte im Umkreis — BNetzA Ladesäulenregister (CC BY 4.0), statewide (NRW bbox).

Data: redat/data/ladesaeulen_nrw.json.gz (scripts/build_ladesaeulen.py), rows in FIELDS order, sorted by
latitude; only chargers "In Betrieb". `_load` is the monkeypatch point.
"""
from __future__ import annotations

import bisect
import gzip
import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Optional

from redat.core.nrw import in_bbox

GRID_PATH = Path(__file__).resolve().parent.parent / "data" / "ladesaeulen_nrw.json.gz"
RADIUS_M = 1000
_NEAR_M = 500
_WALK_M = 300
_MAX_NEAREST = 5
_DLAT = RADIUS_M / 111_195 * 1.05


@lru_cache(maxsize=1)
def _load() -> Optional[dict]:
    try:
        with gzip.open(GRID_PATH, "rt", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


@lru_cache(maxsize=1)
def _lats() -> list[float]:
    """Latitudes of the loaded rows — must be ascending (the build sorts); a bisect over them bounds the scan."""
    grid = _load()
    lats = [r[0] for r in (grid or {}).get("rows") or []]
    if any(b < a for a, b in zip(lats, lats[1:])):
        raise ValueError("ladesaeulen rows are not sorted by latitude — rebuild with scripts/build_ladesaeulen.py")
    return lats


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
    if not in_bbox(lat, lon, tuple(grid["bbox"])):
        return None
    idx = {n: i for i, n in enumerate(grid["fields"])}
    lats = _lats()
    i0, i1 = bisect.bisect_left(lats, lat - _DLAT), bisect.bisect_right(lats, lat + _DLAT)
    hits = []
    for r in grid["rows"][i0:i1]:
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
