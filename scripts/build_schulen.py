"""Build redat/data/schulen_nrw.json.gz — every NRW school with coordinates, Schulform and Sozialindex.

Inputs (both open data, dl-de/by-2-0):
- Schulstandorte in NRW als Shape (Geobasis/Schulministerium, point geometry EPSG:25832, DBF fields
  Schulnumme, Schulform, Name, Kurzname, Adresse, Postleitza, Ort, Schueler, Rufnummer, Email):
  https://www.opengeodata.nrw.de/produkte/bildung_wissenschaft/schulen/SchulenNRW_EPSG25832_Shape.zip
- Schulliste mit Sozialindexstufe (Schulministerium NRW, ';'-separated, **cp850** (DOS codepage — cp1252
  fails on byte 0x81 in "Düsseldorf", verified 2026-09-05); columns
  Schulnummer;Kurzbezeichnung;Bezirksregierung;Kreis;Gemeinde;Sozialindexstufe — Stufe 1 = geringe,
  9 = hohe soziale Herausforderungen, blank for schools without an index):
  https://www.schulministerium.nrw/system/files/media/document/file/schulliste_sj_25_26_open_data.csv

Usage:
    .venv/bin/python scripts/build_schulen.py --shape /tmp/SchulenNRW_EPSG25832_Shape.zip \
        --sozialindex /tmp/schulliste_sj_25_26_open_data.csv --schuljahr 2025/26
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
from datetime import date
from pathlib import Path
from typing import IO, Optional

import geopandas as gpd

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "redat" / "data" / "schulen_nrw.json.gz"


def read_sozialindex(fh: IO[str]) -> dict[str, int]:
    """Schulnummer → Sozialindexstufe (1–9); rows without a Stufe are skipped."""
    out = {}
    for row in csv.DictReader(fh, delimiter=";"):
        nr, stufe = (row.get("Schulnummer") or "").strip(), (row.get("Sozialindexstufe") or "").strip()
        if nr and stufe.isdigit():
            out[nr] = int(stufe)
    return out


def _int_or_none(v) -> Optional[int]:
    try:
        n = int(float(str(v).strip()))
    except (TypeError, ValueError):
        return None
    return n or None   # the shapefile writes 0 for "not reported"


def rows_from_gdf(gdf: gpd.GeoDataFrame) -> list[dict]:
    g = gdf.to_crs("EPSG:4326")
    rows = []
    for _, r in g.iterrows():
        if r.geometry is None or r.geometry.is_empty:
            continue
        rows.append({
            "nr": str(r["Schulnumme"]).strip(), "name": str(r.get("Name") or "").strip(), "kurzname": str(r.get("Kurzname") or "").strip(),
            "form": str(r.get("Schulform") or "").strip(), "lat": round(float(r.geometry.y), 6), "lon": round(float(r.geometry.x), 6),
            "adresse": str(r.get("Adresse") or "").strip() or None, "plz": str(r.get("Postleitza") or "").strip() or None,
            "ort": str(r.get("Ort") or "").strip() or None, "schueler": _int_or_none(r.get("Schueler")),
        })
    return rows


def merge(rows: list[dict], index: dict[str, int]) -> list[dict]:
    return [{**r, "sozialindex": index.get(r["nr"])} for r in rows]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--shape", required=True, help="SchulenNRW_EPSG25832_Shape.zip")
    ap.add_argument("--sozialindex", required=True, help="schulliste_sj_25_26_open_data.csv")
    ap.add_argument("--schuljahr", default="2025/26")
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args()
    with open(a.sozialindex, encoding="cp850", newline="") as fh:
        index = read_sozialindex(fh)
    rows = merge(rows_from_gdf(gpd.read_file(f"zip://{a.shape}")), index)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(a.out, "wt", encoding="utf-8") as fh:
        json.dump({"schuljahr": a.schuljahr, "built": date.today().isoformat(), "schools": rows}, fh, ensure_ascii=False, separators=(",", ":"))
    with_index = sum(1 for r in rows if r["sozialindex"] is not None)
    print(f"wrote {a.out} — {len(rows)} schools, {with_index} with Sozialindex")


if __name__ == "__main__":
    main()
