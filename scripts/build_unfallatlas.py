"""Crop the Unfallatlas (Verkehrsunfälle mit Personenschaden) to the NRW-wide window.

Input: one zip per year from https://www.opengeodata.nrw.de/produkte/transport_verkehr/unfallatlas/
`Unfallorte<YYYY>_EPSG25832_CSV.zip` (Statistische Ämter des Bundes und der Länder, dl-de/by-2-0). The
inner file name and extension vary by year (csv/Unfallorte2020_LinRef.csv, csv/Unfallorte_2025_LR_BasisDLM.csv,
Unfallorte2021_EPSG25832_CSV/Unfallorte_2021_LinRef.txt for 2021 — same content, just a .txt extension), the
layout is ';'-separated with decimal comma and a BOM; columns used: UJAHR, UKATEGORIE (1 Getötete,
2 Schwerverletzte, 3 Leichtverletzte), UTYP1 (1 Fahrunfall, 2 Abbiegen, 3 Einbiegen/Kreuzen,
4 Überschreiten, 5 ruhender Verkehr, 6 Längsverkehr, 7 sonstiger), ULICHTVERH (0 Tag, 1 Dämmerung,
2 Dunkelheit), IstRad/IstPKW/IstFuss/IstKrad/IstGkfz (0/1), XGCSWGS84/YGCSWGS84 (lon/lat).

Output: redat/data/unfallatlas_2020_2025_nrw.npz — `lat`/`lon` float64 sorted by latitude, `attrs` int16
`[n, 9]` in FIELDS[2:] order, `fields`, `meta` (JSON: years, bbox). Statewide 2020–2025: 418,359 rows,
2.6 MB.

Usage:
    .venv/bin/python scripts/build_unfallatlas.py --src ~/Downloads/nrw-redat-sources/unfall
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import zipfile
from pathlib import Path
from typing import IO

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from redat.core.nrw import NRW_BBOX_WGS84  # noqa: E402

OUT = ROOT / "redat" / "data" / "unfallatlas_2020_2025_nrw.npz"
YEARS = list(range(2020, 2026))
BBOX_WGS84 = NRW_BBOX_WGS84
FIELDS = ["lat", "lon", "jahr", "kat", "typ", "licht", "rad", "pkw", "fuss", "krad", "gkfz"]
_INT_COLS = {"jahr": "UJAHR", "kat": "UKATEGORIE", "typ": "UTYP1", "licht": "ULICHTVERH",
             "rad": "IstRad", "pkw": "IstPKW", "fuss": "IstFuss", "krad": "IstKrad", "gkfz": "IstGkfz"}
assert list(_INT_COLS) == FIELDS[2:]   # rows are written in FIELDS order: lat, lon, then _INT_COLS


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
        # year — most years ship .csv, 2021 ships Unfallorte_2021_LinRef.txt; require "unfallorte"
        # in the name so a stray README.txt/schema.ini alongside it is never picked by mistake
        name = next((n for n in z.namelist() if n.lower().endswith((".csv", ".txt")) and "unfallorte" in n.lower()), None)
        if name is None:
            raise FileNotFoundError(f"{path}: no Unfallorte*.csv/.txt inside")
        with z.open(name) as raw:
            return parse_rows(io.TextIOWrapper(raw, encoding="utf-8-sig", errors="replace"), bbox)


def to_arrays(rows: list[list]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """parse_rows() output → (lat, lon, attrs) sorted by latitude so lookups can bisect a band."""
    arr = np.array(rows, dtype=np.float64).reshape(-1, len(FIELDS))
    order = np.argsort(arr[:, 0], kind="stable")
    arr = arr[order]
    return arr[:, 0].copy(), arr[:, 1].copy(), arr[:, 2:].astype(np.int16)


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
    lat, lon, attrs = to_arrays(rows)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(a.out, lat=lat, lon=lon, attrs=attrs, fields=np.array(FIELDS),
                        meta=np.array(json.dumps({"years": years, "bbox": list(BBOX_WGS84)})))
    print(f"wrote {a.out}: {len(rows)} rows, years {years}, {a.out.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
