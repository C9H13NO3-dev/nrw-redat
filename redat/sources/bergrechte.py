"""Bergbauberechtigungen — which mining rights (Bergwerkseigentum, Bewilligung, Erlaubnis) cover the point.

Data: redat/data/bergbauberechtigungen.geojson.gz (scripts/build_bergbauberechtigungen.py) from the open
Bezirksregierung Arnsberg dataset. A Berechtigung is a *right* to mine or explore, not evidence of workings —
the GDU Planquadrat on the same card is the hazard signal; the right tells the buyer who may still claim
Bergschäden liability (RAG, E.ON, …) and whether an Erlaubnis for Erdwärme/Kohlenwasserstoffe exists.
`_load` is the monkeypatch point.
"""
from __future__ import annotations

import gzip
import json
from functools import lru_cache
from pathlib import Path
from typing import Optional

from shapely.geometry import Point, shape

GRID_PATH = Path(__file__).resolve().parent.parent / "data" / "bergbauberechtigungen.geojson.gz"
_KURZ = {
    "aufrechterhaltenes Bergwerkseigentum": "Bergwerkseigentum",
    "Bewilligung": "Bewilligung",
    "Erlaubnis zu gewerblichen Zwecken": "Erlaubnis (Aufsuchung)",
    "Erlaubnis zu wissenschaftlichen Zwecken": "Erlaubnis (Forschung)",
}
_ORDER = {"Bergwerkseigentum": 0, "Bewilligung": 1, "Erlaubnis (Aufsuchung)": 2, "Erlaubnis (Forschung)": 3}


@lru_cache(maxsize=1)
def _load() -> Optional[dict]:
    try:
        with gzip.open(GRID_PATH, "rt", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


@lru_cache(maxsize=1)
def _geoms() -> Optional[list[tuple]]:
    """Parsed (shapely geometry, properties) pairs, built once from `_load()`'s dict.

    Cached separately from `_load()` so the ~630 polygons are only ever shapely-parsed once per
    process, not on every `lookup()` call. Tests that monkeypatch `_load` must also call
    `_geoms.cache_clear()` so this cache is rebuilt from the new grid.
    """
    grid = _load()
    if not grid:
        return None
    out = []
    for f in grid.get("features") or []:
        try:
            geom = shape(f["geometry"])
        except (KeyError, TypeError, ValueError):
            continue
        out.append((geom, f.get("properties") or {}))
    return out


def kurz(art: Optional[str]) -> str:
    return _KURZ.get(art or "", art or "")


def lookup(lat: float, lon: float) -> Optional[list[dict]]:
    """Berechtigungen whose field contains the point, ownership rights first; None when the file is missing."""
    geoms = _geoms()
    if not geoms:
        return None
    pt = Point(lon, lat)
    out = []
    for geom, p in geoms:
        try:
            if not geom.contains(pt):
                continue
        except (TypeError, ValueError):
            continue
        k = kurz(p.get("art"))
        out.append({"feld": p.get("feld"), "art": p.get("art"), "kurz": k, "bodenschatz": p.get("bodenschatz"),
                    "inhaber": p.get("inhaber"), "seit": p.get("seit"), "erloschen": bool(p.get("erloschen")), "groesse": p.get("groesse")})
    out.sort(key=lambda i: (_ORDER.get(i["kurz"], 9), i["feld"] or ""))
    return out
