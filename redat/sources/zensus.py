"""Neighbourhood figures from the Zensus 2022 100 m grid (Destatis Gitterdaten,
licence dl-de/by-2-0, https://www.zensus2022.de/ → Gitterdaten).

`redat/data/zensus_2022_grid.json.gz` is a sparse window cropped to Essen/Bochum by
`scripts/build_zensus_grid.py`: `cells` maps `"{x}_{y}"` (EPSG:3035 cell
centre, metres) to a list of values in `FIELDS` order, `None` where Destatis
suppressed the value (`–`) for confidentiality. Percentages are stored as
percent (0–100), building categories as counts.

`lookup()` returns the 100 m cell **and** a 5×5-cell (500 m × 500 m) aggregate,
because single cells are often suppressed or hold a handful of people.
"""
from __future__ import annotations

import gzip
import json
from functools import lru_cache
from pathlib import Path
from typing import Optional

from pyproj import Transformer

GRID_PATH = Path(__file__).resolve().parent.parent / "data" / "zensus_2022_grid.json.gz"
CELL_M = 100
_WINDOW = 2  # cells on each side → 5×5

SCALARS = ("einwohner", "alter", "u18", "ab65", "hh_groesse", "wohnfl_je_bew", "eigentuemer", "leerstand", "miete_qm")
POP_WEIGHTED = ("alter", "u18", "ab65", "hh_groesse", "wohnfl_je_bew")   # mean weighted by einwohner
UNWEIGHTED = ("eigentuemer", "leerstand", "miete_qm")                      # no per-cell dwelling count shipped

GROUPS = {
    "baujahr": [("bj_vor1919", "vor 1919"), ("bj_1919_1949", "1919–1949"), ("bj_1950_1959", "1950–1959"),
                ("bj_1960_1969", "1960–1969"), ("bj_1970_1979", "1970–1979"), ("bj_1980_1989", "1980–1989"),
                ("bj_1990_1999", "1990–1999"), ("bj_2000_2009", "2000–2009"), ("bj_2010_2015", "2010–2015"),
                ("bj_2016plus", "2016 und später")],
    "heizung": [("hz_fern", "Fernheizung"), ("hz_etage", "Etagenheizung"), ("hz_block", "Blockheizung"),
                ("hz_zentral", "Zentralheizung"), ("hz_ofen", "Einzel-/Mehrraumöfen"), ("hz_keine", "keine Heizung")],
    "energietraeger": [("et_gas", "Gas"), ("et_oel", "Heizöl"), ("et_holz", "Holz/Pellets"), ("et_bio", "Biomasse/Biogas"),
                       ("et_solar_wp", "Solar/Geothermie/Wärmepumpe"), ("et_strom", "Strom"), ("et_kohle", "Kohle"),
                       ("et_fern", "Fernwärme"), ("et_keine", "kein Energieträger")],
    "gebaeudetyp": [("gw_1", "1 Wohnung"), ("gw_2", "2 Wohnungen"), ("gw_3_6", "3–6 Wohnungen"),
                    ("gw_7_12", "7–12 Wohnungen"), ("gw_13plus", "13+ Wohnungen")],
}
FIELDS = list(SCALARS) + ["geb"] + [k for keys in GROUPS.values() for k, _ in keys]

_TO_3035 = Transformer.from_crs("EPSG:4326", "EPSG:3035", always_xy=True)


def _to_3035(lon: float, lat: float) -> tuple[float, float]:
    return _TO_3035.transform(lon, lat)


def _cell_centre(x: float, y: float) -> tuple[int, int]:
    return int(x // CELL_M) * CELL_M + CELL_M // 2, int(y // CELL_M) * CELL_M + CELL_M // 2


@lru_cache(maxsize=1)
def _load() -> Optional[dict]:
    try:
        with gzip.open(GRID_PATH, "rt", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _shares(cells: list[dict]) -> dict:
    out = {}
    for group, keys in GROUPS.items():
        counts = {label: sum(c[k] for c in cells if c.get(k) is not None) for k, label in keys}
        total = sum(counts.values())
        out[group] = {label: round(n / total, 3) for label, n in counts.items() if n} if total else {}
    return out


def _summary(cells: list[dict]) -> dict:
    """Scalars + category shares over one or more cells (see module doc for the weighting)."""
    out: dict = {}
    pops = [c["einwohner"] for c in cells if c.get("einwohner") is not None]
    out["einwohner"] = sum(pops) if pops else None
    for f in POP_WEIGHTED:
        pairs = [(c[f], c["einwohner"]) for c in cells if c.get(f) is not None and c.get("einwohner")]
        out[f] = round(sum(v * w for v, w in pairs) / sum(w for _, w in pairs), 2) if pairs else None
    for f in UNWEIGHTED:
        vals = [c[f] for c in cells if c.get(f) is not None]
        out[f] = round(sum(vals) / len(vals), 2) if vals else None
    gebs = [c["geb"] for c in cells if c.get("geb") is not None]
    out["gebaeude"] = sum(gebs) if gebs else None
    out.update(_shares(cells))
    return out


def lookup(lat: float, lon: float) -> Optional[dict]:
    """The 100 m cell containing (lat, lon) plus its 5×5 neighbourhood, or None
    when no cell in the neighbourhood has data (outside the window / unpopulated)."""
    grid = _load()
    if not grid:
        return None
    fields = grid["fields"]
    cx, cy = _cell_centre(*_to_3035(lon, lat))
    cell_m = grid.get("cell_m", CELL_M)

    def get(x: int, y: int) -> Optional[dict]:
        vals = grid["cells"].get(f"{x}_{y}")
        return dict(zip(fields, vals)) if vals else None

    centre = get(cx, cy)
    window = [c for dx in range(-_WINDOW, _WINDOW + 1) for dy in range(-_WINDOW, _WINDOW + 1)
              if (c := get(cx + dx * cell_m, cy + dy * cell_m))]
    if not window:
        return None
    return {
        "year": grid.get("year"), "cell_m": cell_m, "radius_m": _WINDOW * cell_m + cell_m // 2,
        "area_cells": len(window),
        "cell": _summary([centre]) if centre else None,
        "area": _summary(window),
    }
