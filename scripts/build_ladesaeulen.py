"""Crop the BNetzA Ladesäulenregister statewide (NRW bbox) → redat/data/ladesaeulen_nrw.json.gz.

Input: the monthly CSV linked from https://www.bundesnetzagentur.de/DE/Fachthemen/ElektrizitaetundGas/E-Mobilitaet/Ladesaeulenkarte/start.html,
e.g. https://data.bundesnetzagentur.de/Bundesnetzagentur/DE/Fachthemen/ElektrizitaetundGas/E-Mobilitaet/Ladesaeulenregister_BNetzA_2026-09-01.csv
(CC BY 4.0, ~55 MB, UTF-8 BOM, ';', decimal comma, 116k rows). The header is the line starting with
"Ladeeinrichtungs-ID" (after a 9-line preamble that carries "Letzte Aktualisierung vom: dd.mm.yyyy"). Crop by
bbox, not by Ort: a Berlin charger carries Ort "Essen". Only Status "In Betrieb" is kept.

Usage:
    .venv/bin/python scripts/build_ladesaeulen.py --csv ~/Downloads/nrw-redat-sources/Ladesaeulenregister_BNetzA_2026-09-01.csv
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import re
import sys
from pathlib import Path
from typing import IO, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from redat.core.nrw import NRW_BBOX_WGS84  # noqa: E402

OUT = ROOT / "redat" / "data" / "ladesaeulen_nrw.json.gz"
BBOX_WGS84 = NRW_BBOX_WGS84
FIELDS = ["lat", "lon", "betreiber", "schnell", "punkte", "kw", "adresse"]


def _num(s: str) -> float:
    return float((s or "").strip().replace(".", "").replace(",", "."))


def read_stand(fh: IO[str]) -> Optional[str]:
    for line in fh:
        m = re.search(r"Letzte Aktualisierung vom:\s*(\d{2})\.(\d{2})\.(\d{4})", line)
        if m:
            return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
        if line.startswith("Ladeeinrichtungs-ID"):
            break
    return None


def parse_rows(fh: IO[str], bbox: tuple[float, float, float, float]) -> list[list]:
    lon_min, lat_min, lon_max, lat_max = bbox
    lines = iter(fh)
    for line in lines:
        if line.lstrip("﻿").startswith("Ladeeinrichtungs-ID"):
            header = next(csv.reader([line.lstrip("﻿")], delimiter=";"))
            break
    else:
        raise ValueError("Kopfzeile 'Ladeeinrichtungs-ID' nicht gefunden")
    ci = {h: i for i, h in enumerate(header)}
    rows = []
    for r in csv.reader(lines, delimiter=";"):
        if len(r) < len(header):
            continue
        try:
            lat, lon = _num(r[ci["Breitengrad"]]), _num(r[ci["Längengrad"]])
        except ValueError:
            continue
        if not (lon_min <= lon <= lon_max and lat_min <= lat <= lat_max) or r[ci["Status"]].strip() != "In Betrieb":
            continue
        try:
            punkte, kw = int(_num(r[ci["Anzahl Ladepunkte"]])), _num(r[ci["Nennleistung Ladeeinrichtung [kW]"]])
        except ValueError:
            continue
        street = " ".join(p for p in (r[ci["Straße"]].strip(), r[ci["Hausnummer"]].strip()) if p)
        adresse = ", ".join(p for p in (street, f"{r[ci['Postleitzahl']].strip()} {r[ci['Ort']].strip()}".strip()) if p)
        rows.append([round(lat, 6), round(lon, 6), r[ci["Betreiber"]].strip(),
                     1 if r[ci["Art der Ladeeinrichtung"]].strip().startswith("Schnell") else 0, punkte, kw, adresse])
    return rows


def sort_rows(rows: list[list]) -> list[list]:
    """Latitude-sorted so the runtime lookup can bisect a ±1 km band instead of scanning ~25k rows."""
    rows.sort(key=lambda r: r[0])
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args()
    with open(a.csv, encoding="utf-8-sig", newline="") as fh:
        stand = read_stand(fh)
    with open(a.csv, encoding="utf-8-sig", newline="") as fh:
        rows = sort_rows(parse_rows(fh, BBOX_WGS84))
    a.out.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(a.out, "wt", encoding="utf-8") as fh:
        json.dump({"stand": stand, "bbox": list(BBOX_WGS84), "fields": FIELDS, "rows": rows}, fh, ensure_ascii=False, separators=(",", ":"))
    print(f"wrote {a.out}: {len(rows)} Ladeeinrichtungen, Stand {stand}")


if __name__ == "__main__":
    main()
