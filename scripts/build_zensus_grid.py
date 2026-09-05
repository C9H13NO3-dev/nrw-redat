"""Crop the Zensus 2022 100 m grid CSVs to the Essen/Bochum window.

Input: the Destatis "Gitterdaten" zips (licence dl-de/by-2-0), downloaded from
https://www.destatis.de/static/DE/zensus/gitterdaten/{name}.zip — one zip per
topic, each holding a `*_100m-Gitter.csv` (semicolon-separated, EPSG:3035 cell
centres in `x_mp_100m`/`y_mp_100m`, decimal comma, `–` for a suppressed value,
`KLAMMERN` in `werterlaeuternde_Zeichen` for a low-reliability value that is
kept). Most files are UTF-8, a few (Energieträger, Heizungsart) are cp1252 — we
only ever need ASCII digits, so anything non-numeric becomes None either way.

Output: redat/data/zensus_2022_grid.json.gz — a sparse dict `cells["x_y"] ->
[values in FIELDS order]` that `redat/sources/zensus.py` looks up at runtime.

Usage:
    .venv/bin/python scripts/build_zensus_grid.py --src /path/to/dir/with/zips
"""
from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import sys
import zipfile
from pathlib import Path
from typing import IO, Optional

from pyproj import Transformer

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from redat.sources.zensus import FIELDS  # noqa: E402

OUT = ROOT / "redat" / "data" / "zensus_2022_grid.json.gz"

# Essen + Bochum with a margin (WGS84: lon_min, lat_min, lon_max, lat_max).
BBOX_WGS84 = (6.85, 51.33, 7.40, 51.56)

# (zip file name, {csv column: FIELDS key})
SOURCES = [
    ("Zensus2022_Bevoelkerungszahl.zip", {"Einwohner": "einwohner"}),
    ("Durchschnittsalter_in_Gitterzellen.zip", {"Durchschnittsalter": "alter"}),
    ("Anteil_unter_18-jaehrige_in_Gitterzellen.zip", {"AnteilUnter18": "u18"}),
    ("Anteil_ab_65-jaehrige_in_Gitterzellen.zip", {"AnteilUeber65": "ab65"}),
    ("Durchschnittliche_Haushaltsgroesse_in_Gitterzellen.zip", {"DurchschnHHGroesse": "hh_groesse"}),
    ("Durchschnittliche_Wohnflaeche_je_Bewohner_in_Gitterzellen.zip", {"durchschnFlaechejeBew": "wohnfl_je_bew"}),
    ("Eigentuemerquote_in_Gitterzellen.zip", {"Eigentuemerquote": "eigentuemer"}),
    ("Leerstandsquote_in_Gitterzellen.zip", {"Leerstandsquote": "leerstand"}),
    ("Zensus2022_Durchschn_Nettokaltmiete.zip", {"durchschnMieteQM": "miete_qm"}),
    ("Gebaeude_nach_Baujahr_Jahrzehnte.zip", {
        "Insgesamt_Gebaeude": "geb", "Vor1919": "bj_vor1919", "a1919bis1949": "bj_1919_1949",
        "a1950bis1959": "bj_1950_1959", "a1960bis1969": "bj_1960_1969", "a1970bis1979": "bj_1970_1979",
        "a1980bis1989": "bj_1980_1989", "a1990bis1999": "bj_1990_1999", "a2000bis2009": "bj_2000_2009",
        "a2010bis2015": "bj_2010_2015", "a2016undspaeter": "bj_2016plus"}),
    ("Zensus2022_Heizungsart.zip", {
        "Fernheizung": "hz_fern", "Etagenheizung": "hz_etage", "Blockheizung": "hz_block",
        "Zentralheizung": "hz_zentral", "Einzel_Mehrraumoefen": "hz_ofen", "keine_Heizung": "hz_keine"}),
    ("Zensus2022_Energietraeger.zip", {
        "Gas": "et_gas", "Heizoel": "et_oel", "Holz_Holzpellets": "et_holz", "Biomasse_Biogas": "et_bio",
        "Solar_Geothermie_Waermepumpen": "et_solar_wp", "Strom": "et_strom", "Kohle": "et_kohle",
        "Fernwaerme": "et_fern", "kein_Energietraeger": "et_keine"}),
    ("Gebaeude_nach_Anzahl_der_Wohnungen_im_Gebaeude.zip", {
        "1_Wohnung": "gw_1", "2_Wohnungen": "gw_2", "3bis6_Wohnungen": "gw_3_6",
        "7bis12_Wohnungen": "gw_7_12", "13undmehr_Wohnungen": "gw_13plus"}),
]


def parse_value(s: str) -> Optional[float | int]:
    s = (s or "").strip().replace(",", ".")
    if not s:
        return None
    try:
        f = float(s)
    except ValueError:
        return None
    return int(f) if f.is_integer() and "." not in s else f


def bbox_3035() -> tuple[float, float, float, float]:
    tr = Transformer.from_crs("EPSG:4326", "EPSG:3035", always_xy=True)
    lon_min, lat_min, lon_max, lat_max = BBOX_WGS84
    xs, ys = zip(*(tr.transform(lon, lat) for lon, lat in
                   ((lon_min, lat_min), (lon_min, lat_max), (lon_max, lat_min), (lon_max, lat_max))))
    return min(xs), min(ys), max(xs), max(ys)


def ingest(fh: IO[str], colmap: dict[str, str], bbox: tuple[float, float, float, float], cells: dict) -> int:
    """Stream one CSV, merging the mapped columns of every in-bbox row into `cells`. Returns rows kept."""
    x_min, y_min, x_max, y_max = bbox
    reader = csv.DictReader(fh, delimiter=";")
    missing = set(colmap) - set(reader.fieldnames or [])
    if missing:
        raise SystemExit(f"columns {sorted(missing)} not in header {reader.fieldnames}")
    kept = 0
    for row in reader:
        x, y = int(row["x_mp_100m"]), int(row["y_mp_100m"])
        if not (x_min <= x <= x_max and y_min <= y <= y_max):
            continue
        cell = cells.setdefault(f"{x}_{y}", {})
        for col, field in colmap.items():
            cell[field] = parse_value(row[col])
        kept += 1
    return kept


def to_rows(cells: dict, fields: list[str]) -> dict[str, list]:
    """Dense per-cell value lists in `fields` order; cells with no value at all are dropped."""
    out = {}
    for key, vals in cells.items():
        row = [vals.get(f) for f in fields]
        if any(v is not None for v in row):
            out[key] = row
    return out


def build(src: Path) -> dict:
    bbox = bbox_3035()
    cells: dict = {}
    for zip_name, colmap in SOURCES:
        path = src / zip_name
        with zipfile.ZipFile(path) as zf:
            member = next(n for n in zf.namelist() if n.endswith("100m-Gitter.csv"))
            with zf.open(member) as raw:
                n = ingest(io.TextIOWrapper(raw, encoding="utf-8", errors="replace", newline=""), colmap, bbox, cells)
        print(f"{zip_name}: {n} cells in window", file=sys.stderr)
    rows = to_rows(cells, FIELDS)
    return {
        "source": "Destatis, Zensus 2022 — Gitterdaten 100 m (dl-de/by-2-0)",
        "year": 2022, "crs": "EPSG:3035", "cell_m": 100,
        "bbox_wgs84": list(BBOX_WGS84), "fields": FIELDS, "cells": rows,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", type=Path, required=True, help="directory holding the Destatis zips")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    grid = build(args.src)
    with gzip.open(args.out, "wt", encoding="utf-8") as fh:
        json.dump(grid, fh, ensure_ascii=False, separators=(",", ":"))
    print(f"wrote {args.out} — {len(grid['cells'])} cells, {args.out.stat().st_size / 1e6:.1f} MB", file=sys.stderr)


if __name__ == "__main__":
    main()
