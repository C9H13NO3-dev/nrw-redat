"""Crop the Copernicus EGMS L3 Ortho vertical-velocity tile to the Essen/Bochum window → redat/data/egms_vertical_velocity.json.gz.

Input: the GeoTIFF `EGMS_L3_E41N31_100km_U_<from>_<to>_<v>.tif` (tile E41N31 covers Essen and Bochum; ETRS89-LAEA
EPSG:3035, 100 m pixels, mean vertical velocity in mm/year, positive = uplift). It is a free download behind an EU
Login — either the Explorer (https://egms.land.copernicus.eu/ → geographical search → tile list → "L3 Ortho U") or the
insar-api with a CLMS API token (`~/.config/nrw-redat/egms_download.py E41N31`, kept outside the repo with the token;
search `POST /insar-api/archive/search {tileId, levels:[L3], releases, productType:ORTHO-UP}`, then
`GET /download/<filename>?id=<query id>&token=<access token>`). The zip holds the .tiff plus a 488 MB CSV — only the
.tiff (renamed .tif) is needed. Georeference is read from the GeoTIFF tags with Pillow (33550 ModelPixelScaleTag,
33922 ModelTiepointTag); NoData is the tile's GDAL_NODATA tag (42113, -9999) — but the 2020-2024 tile actually stores
NaN in unmeasured cells, so both are skipped.

Usage:
    .venv/bin/python scripts/build_egms.py --tif ~/Downloads/EGMS_L3_E41N31_100km_U_2020_2024_1.tif
"""
from __future__ import annotations

import argparse
import gzip
import json
import re
from pathlib import Path

import numpy as np
from PIL import Image
from pyproj import Transformer

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "redat" / "data" / "egms_vertical_velocity.json.gz"
BBOX_WGS84 = (6.85, 51.33, 7.40, 51.56)
NODATA = -9999.0
_TAG_SCALE, _TAG_TIEPOINT, _TAG_NODATA = 33550, 33922, 42113


def read_geotiff(path: Path) -> tuple[np.ndarray, float, float, float, float]:
    """(array, x0, y0, pixel_size, nodata) — x0/y0 is the top-left corner in the raster CRS."""
    im = Image.open(path)
    im.load()
    tags = im.tag_v2
    sx, sy = float(tags[_TAG_SCALE][0]), float(tags[_TAG_SCALE][1])
    tp = tags[_TAG_TIEPOINT]                      # (i, j, k, x, y, z)
    x0, y0 = float(tp[3]) - float(tp[0]) * sx, float(tp[4]) + float(tp[1]) * sy
    nodata = float(tags[_TAG_NODATA]) if _TAG_NODATA in tags else NODATA
    return np.asarray(im, dtype=np.float32), x0, y0, sx, nodata


def crop_cells(arr: np.ndarray, x0: float, y0: float, px: float, bbox3035: tuple[float, float, float, float], nodata: float = NODATA) -> dict[str, float]:
    """Cells whose centre lies in bbox3035 → {"x_y": mm/a}; row 0 is the northern row."""
    xmin, ymin, xmax, ymax = bbox3035
    out: dict[str, float] = {}
    rows, cols = arr.shape
    for r in range(rows):
        cy = y0 - (r + 0.5) * px
        if not (ymin <= cy <= ymax):
            continue
        for c in range(cols):
            cx = x0 + (c + 0.5) * px
            v = float(arr[r, c])
            if not (xmin <= cx <= xmax) or v == nodata or not np.isfinite(v):
                continue
            out[f"{int(round(cx))}_{int(round(cy))}"] = round(v, 2)
    return out


def bbox_3035() -> tuple[float, float, float, float]:
    t = Transformer.from_crs("EPSG:4326", "EPSG:3035", always_xy=True)
    xs, ys = zip(*(t.transform(lon, lat) for lon, lat in ((BBOX_WGS84[0], BBOX_WGS84[1]), (BBOX_WGS84[2], BBOX_WGS84[1]),
                                                           (BBOX_WGS84[0], BBOX_WGS84[3]), (BBOX_WGS84[2], BBOX_WGS84[3]))))
    return min(xs), min(ys), max(xs), max(ys)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tif", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args()
    arr, x0, y0, px, nodata = read_geotiff(a.tif)
    cells = crop_cells(arr, x0, y0, px, bbox_3035(), nodata)
    m = re.search(r"_U_(\d{4})_(\d{4})_", a.tif.name)
    years = f"{m.group(1)}-{m.group(2)}" if m else "unbekannt"
    a.out.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(a.out, "wt", encoding="utf-8") as fh:
        json.dump({"years": years, "cell_m": int(px), "cells": cells}, fh, separators=(",", ":"))
    print(f"wrote {a.out}: {len(cells)} cells, years {years}, pixel {px} m")


if __name__ == "__main__":
    main()
