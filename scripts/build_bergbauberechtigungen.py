"""Crop the NRW Bergbauberechtigungen statewide → redat/data/bergbauberechtigungen_nrw.geojson.gz.

Input: https://www.opengeodata.nrw.de/produkte/geologie/bergbau/bebu/BergbauberechtigungenNRW_EPSG25832_Shape.zip
(Bezirksregierung Arnsberg, dl-de/by-2-0, 860 KB, 5,361 polygons statewide, refreshed on opengeodata a few times a
year). Fields: FELDESNUMM, BERECHTIGU (Bergwerkseigentum / Bewilligung / Erlaubnis …), BODENSCHAT, FELDESNAME,
FELDESGROE ("140 110 991 m²"), ENTSTEHUNG ("23.01.1791" or "-"), LAUFZEIT_V/_B, ERLOSCHEN (ja/nein), RECHTSINHA.

Usage:
    .venv/bin/python scripts/build_bergbauberechtigungen.py --shape ~/Downloads/nrw-redat-sources/BergbauberechtigungenNRW_EPSG25832_Shape.zip
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
from datetime import date
from pathlib import Path

import geopandas as gpd
from shapely.geometry import box, mapping

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from redat.core.nrw import NRW_BBOX_WGS84  # noqa: E402

OUT = ROOT / "redat" / "data" / "bergbauberechtigungen_nrw.geojson.gz"
BBOX_WGS84 = NRW_BBOX_WGS84   # statewide


def _clean(v) -> str | None:
    s = str(v).strip() if v is not None else ""
    return None if s in ("", "-", "None", "nan") else s


def crop(gdf: gpd.GeoDataFrame, bbox: tuple[float, float, float, float]) -> gpd.GeoDataFrame:
    w = gdf.to_crs("EPSG:4326")
    return w[w.intersects(box(*bbox))].copy()


def to_features(gdf: gpd.GeoDataFrame) -> list[dict]:
    feats = []
    for _, r in gdf.iterrows():
        feats.append({"type": "Feature", "geometry": mapping(r.geometry), "properties": {
            "feld": _clean(r.get("FELDESNAME")), "art": _clean(r.get("BERECHTIGU")), "bodenschatz": _clean(r.get("BODENSCHAT")),
            "inhaber": _clean(r.get("RECHTSINHA")), "seit": _clean(r.get("ENTSTEHUNG")), "bis": _clean(r.get("LAUFZEIT_B")),
            "erloschen": str(r.get("ERLOSCHEN")).strip().lower() == "ja", "groesse": _clean(r.get("FELDESGROE")),
            "nummer": _clean(r.get("FELDESNUMM")),
        }})
    return feats


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--shape", required=True, help="BergbauberechtigungenNRW_EPSG25832_Shape.zip")
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args()
    feats = to_features(crop(gpd.read_file(f"zip://{a.shape}"), BBOX_WGS84))
    a.out.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(a.out, "wt", encoding="utf-8") as fh:
        json.dump({"type": "FeatureCollection", "built": date.today().isoformat(), "features": feats}, fh, ensure_ascii=False, separators=(",", ":"))
    print(f"wrote {a.out}: {len(feats)} Berechtigungen statewide")


if __name__ == "__main__":
    main()
