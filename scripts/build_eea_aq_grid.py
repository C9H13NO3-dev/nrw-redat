"""Crop the EEA 1 km interpolated air-quality rasters to the Essen/Bochum window.

Input: the four EEA GeoTIFFs (EPSG:3035, 1 km cells, float32, CC-BY 4.0) from
https://sdi.eea.europa.eu/datastore/public/eea_r_3035_1_km_aq-interpolated-{no2,pm25,pm10,O3}_p_2023_v01_r00/
    no2_avg_23.tif   annual mean NO2      (µg/m³)
    pm25_avg_23.tif  annual mean PM2.5    (µg/m³)
    pm10_avg_23.tif  annual mean PM10     (µg/m³)
    o3_peak_23.tif   peak-season mean of daily max 8h O3 (µg/m³, the WHO metric)

Output: redat/data/eea_aq_grid_2023.json — a ~1500-cell window per layer that
`redat/sources/airquality_grid.py` looks up at runtime without any raster library.

Usage:
    .venv/bin/python scripts/build_eea_aq_grid.py --src /path/to/dir/with/tifs [--year 2023]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from pyproj import Transformer

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "redat" / "data" / "eea_aq_grid_2023.json"

# Essen + Bochum with a margin (WGS84: lon_min, lat_min, lon_max, lat_max).
BBOX_WGS84 = (6.80, 51.30, 7.45, 51.60)

LAYERS = {
    "no2": "no2_avg_{yy}.tif",
    "pm25": "pm25_avg_{yy}.tif",
    "pm10": "pm10_avg_{yy}.tif",
    "o3_peak": "o3_peak_{yy}.tif",
}

_TAG_SCALE = 33550
_TAG_TIEPOINT = 33922
_TAG_NODATA = 42113


def _geo(im: Image.Image) -> tuple[float, float, float, float, float | None]:
    tags = im.tag_v2
    sx, sy = tags[_TAG_SCALE][0], tags[_TAG_SCALE][1]
    x0, y0 = tags[_TAG_TIEPOINT][3], tags[_TAG_TIEPOINT][4]
    nodata = tags.get(_TAG_NODATA)
    return x0, y0, sx, sy, (float(nodata) if nodata is not None else None)


def build(src: Path, year: int) -> dict:
    Image.MAX_IMAGE_PIXELS = None
    yy = f"{year % 100:02d}"
    tr = Transformer.from_crs("EPSG:4326", "EPSG:3035", always_xy=True)
    lon_min, lat_min, lon_max, lat_max = BBOX_WGS84
    xs, ys = zip(*(tr.transform(lon, lat) for lon, lat in
                   ((lon_min, lat_min), (lon_min, lat_max), (lon_max, lat_min), (lon_max, lat_max))))

    out: dict = {
        "source": "EEA, European air quality data (interpolated), 1 km grid, CC-BY 4.0",
        "year": year, "crs": "EPSG:3035", "bbox_wgs84": list(BBOX_WGS84), "layers": {},
    }
    window = None
    for key, pattern in LAYERS.items():
        path = src / pattern.format(yy=yy)
        im = Image.open(path)
        x0, y0, sx, sy, nodata = _geo(im)
        col0, col1 = int((min(xs) - x0) // sx), int((max(xs) - x0) // sx) + 1
        row0, row1 = int((y0 - max(ys)) // sy), int((y0 - min(ys)) // sy) + 1
        # Tie-points carry float noise across files (…000.0000000005); round to metres.
        this_window = (round(x0 + col0 * sx), round(y0 - row0 * sy), round(sx), col1 - col0, row1 - row0)
        if window is None:
            window = this_window
            out.update({"x0": window[0], "y0": window[1], "cell_m": window[2],
                        "ncols": window[3], "nrows": window[4]})
        elif this_window != window:
            sys.exit(f"{path.name}: grid window {this_window} differs from {window}")
        arr = np.array(im)[row0:row1, col0:col1].astype(float)
        if nodata is not None:
            arr[np.isclose(arr, nodata)] = np.nan
        out["layers"][key] = [[None if np.isnan(v) else round(float(v), 1) for v in row] for row in arr]
        print(f"{key}: {arr.shape[1]}x{arr.shape[0]} cells, "
              f"min {np.nanmin(arr):.1f} max {np.nanmax(arr):.1f}, nodata {int(np.isnan(arr).sum())}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", required=True, type=Path, help="directory holding the four .tif files")
    ap.add_argument("--year", type=int, default=2023)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    data = build(args.src, args.year)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {args.out} ({args.out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
