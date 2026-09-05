"""Crop the Unfallatlas (Verkehrsunfälle mit Personenschaden) to the Essen/Bochum window.

Input: one zip per year from https://www.opengeodata.nrw.de/produkte/transport_verkehr/unfallatlas/
`Unfallorte<YYYY>_EPSG25832_CSV.zip` (Statistische Ämter des Bundes und der Länder, dl-de/by-2-0). The
inner file name and extension vary by year (csv/Unfallorte2020_LinRef.csv, csv/Unfallorte_2025_LR_BasisDLM.csv,
Unfallorte2021_EPSG25832_CSV/Unfallorte_2021_LinRef.txt for 2021 — same content, just a .txt extension), the
layout is ';'-separated with decimal comma and a BOM; columns used: UJAHR, UKATEGORIE (1 Getötete,
2 Schwerverletzte, 3 Leichtverletzte), UTYP1 (1 Fahrunfall, 2 Abbiegen, 3 Einbiegen/Kreuzen,
4 Überschreiten, 5 ruhender Verkehr, 6 Längsverkehr, 7 sonstiger), ULICHTVERH (0 Tag, 1 Dämmerung,
2 Dunkelheit), IstRad/IstPKW/IstFuss/IstKrad/IstGkfz (0/1), XGCSWGS84/YGCSWGS84 (lon/lat).

Output: redat/data/unfallatlas_2020_2025.json.gz with compact rows in FIELDS order, read at runtime by
redat/sources/unfaelle.py.

Usage:
    .venv/bin/python scripts/build_unfallatlas.py --src /dir/with/Unfallorte*_EPSG25832_CSV.zip
"""
from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import re
import zipfile
from pathlib import Path
from typing import IO

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "redat" / "data" / "unfallatlas_2020_2025.json.gz"
YEARS = list(range(2020, 2026))
BBOX_WGS84 = (6.85, 51.33, 7.40, 51.56)   # lon_min, lat_min, lon_max, lat_max — same window as the Zensus grid
FIELDS = ["lat", "lon", "jahr", "kat", "typ", "licht", "rad", "pkw", "fuss", "krad", "gkfz"]
_INT_COLS = {"jahr": "UJAHR", "kat": "UKATEGORIE", "typ": "UTYP1", "licht": "ULICHTVERH",
             "rad": "IstRad", "pkw": "IstPKW", "fuss": "IstFuss", "krad": "IstKrad", "gkfz": "IstGkfz"}


def _num(s: str) -> float:
    return float((s or "").strip().replace(",", "."))


def parse_rows(fh: IO[str], bbox: tuple[float, float, float, float]) -> list[list]:
    lon_min, lat_min, lon_max, lat_max = bbox
    rows = []
    reader = csv.DictReader(fh, delimiter=";")
    reader.fieldnames = [f.lstrip("﻿") for f in reader.fieldnames or []]   # BOM survives when a caller passes a plain StringIO
    for r in reader:
        try:
            lon, lat = _num(r["XGCSWGS84"]), _num(r["YGCSWGS84"])
        except (KeyError, ValueError):
            continue
        if not (lon_min <= lon <= lon_max and lat_min <= lat <= lat_max):
            continue
        row = [round(lat, 6), round(lon, 6)]
        try:
            row += [int(_num(r[col])) for col in _INT_COLS.values()]
        except (KeyError, ValueError):
            continue
        rows.append(row)
    return rows


def read_zip(path: Path, bbox: tuple[float, float, float, float]) -> list[list]:
    with zipfile.ZipFile(path) as z:
        # the inner data file is always ';'-separated/BOM CSV content, but its extension varies by
        # year — most years ship .csv, 2021 ships Unfallorte_2021_LinRef.txt
        name = next(n for n in z.namelist() if n.lower().endswith((".csv", ".txt")))
        with z.open(name) as raw:
            return parse_rows(io.TextIOWrapper(raw, encoding="utf-8-sig", errors="replace"), bbox)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", type=Path, required=True, help="directory holding Unfallorte<YYYY>_EPSG25832_CSV.zip")
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args()
    rows, years = [], []
    for y in YEARS:
        zips = sorted(a.src.glob(f"Unfallorte{y}_EPSG25832_CSV.zip"))
        if not zips:
            print(f"skip {y}: no zip in {a.src}")
            continue
        got = read_zip(zips[0], BBOX_WGS84)
        print(f"{y}: {len(got)} accidents in window")
        rows += got
        years.append(y)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(a.out, "wt", encoding="utf-8") as fh:
        json.dump({"years": years, "bbox": list(BBOX_WGS84), "fields": FIELDS, "rows": rows}, fh, separators=(",", ":"))
    print(f"wrote {a.out}: {len(rows)} rows, years {years}")


if __name__ == "__main__":
    main()
