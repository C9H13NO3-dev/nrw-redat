"""Mosaic the nine Copernicus EGMS L3 Ortho vertical tiles covering NRW → redat/data/egms_vertical_velocity_nrw.npz.

Input: the nine Copernicus EGMS L3 Ortho vertical tiles covering NRW (`EGMS_L3_E40N30 … E42N32_100km_U_<from>_<to>_<v>.tif`,
ETRS89-LAEA EPSG:3035, 100 m, mm/year, positive = uplift; NaN or the GDAL_NODATA tag −9999 in unmeasured cells). Free
download behind an EU Login via the insar-api (`~/.config/nrw-redat/egms_download.py <tile>`, kept outside the repo
with the CLMS token; unzip the .tiff and rename to .tif). Output: redat/data/egms_vertical_velocity_nrw.npz — `v` int16
raster of the NRW bbox (mm/a × 100, −32768 = unmeasured, row 0 = north), `meta` JSON {x0, y1, cell_m, years, scale}.
Statewide 2020–2024: 2 728 × 2 750 cells, 1,717,178 measured, 3.3 MB. Usage:
    .venv/bin/python scripts/build_egms.py --src ~/Downloads
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from redat.core.nrw import bbox_3035  # noqa: E402

OUT = ROOT / "redat" / "data" / "egms_vertical_velocity_nrw.npz"
NODATA = -32768                      # int16 sentinel in the output raster
SCALE = 100                          # stored value = mm/a × SCALE
_TAG_SCALE, _TAG_TIEPOINT, _TAG_NODATA = 33550, 33922, 42113
_TILE_GLOB = "EGMS_L3_E*N*_100km_U_*.tif"


def raster_window(cell_m: int) -> tuple[int, int, int, int]:
    """(x0 west edge, y1 north edge, ncols, nrows) of the NRW bbox snapped outwards to the cell grid."""
    xmin, ymin, xmax, ymax = bbox_3035()
    x0, y0 = int(xmin // cell_m) * cell_m, int(ymin // cell_m) * cell_m
    x1, y1 = int(xmax // cell_m + 1) * cell_m, int(ymax // cell_m + 1) * cell_m
    return x0, y1, (x1 - x0) // cell_m, (y1 - y0) // cell_m


def read_geotiff(path: Path) -> tuple[np.ndarray, float, float, float, float]:
    """(array, x0, y0, pixel_size, nodata) — x0/y0 is the top-left corner in the raster CRS."""
    Image.MAX_IMAGE_PIXELS = None
    im = Image.open(path)
    im.load()
    tags = im.tag_v2
    sx, sy = float(tags[_TAG_SCALE][0]), float(tags[_TAG_SCALE][1])
    tp = tags[_TAG_TIEPOINT]                      # (i, j, k, x, y, z)
    x0, y0 = float(tp[3]) - float(tp[0]) * sx, float(tp[4]) + float(tp[1]) * sy
    nodata = float(tags[_TAG_NODATA]) if _TAG_NODATA in tags else -9999.0
    return np.asarray(im, dtype=np.float32), x0, y0, sx, nodata


def place_tile(ras: np.ndarray, x0: int, y1: int, cell_m: int, arr: np.ndarray, tx: float, ty: float,
               nodata: float, scale: int) -> int:
    """Write one tile (top-left corner tx/ty) into the raster, clipped to it; NaN/nodata cells are skipped.
    Returns the number of cells written."""
    nrows, ncols = ras.shape
    c_off, r_off = int(round((tx - x0) / cell_m)), int(round((y1 - ty) / cell_m))
    r0, r1 = max(r_off, 0), min(r_off + arr.shape[0], nrows)
    c0, c1 = max(c_off, 0), min(c_off + arr.shape[1], ncols)
    if r0 >= r1 or c0 >= c1:
        return 0
    sub = arr[r0 - r_off:r1 - r_off, c0 - c_off:c1 - c_off]
    valid = np.isfinite(sub) & (sub != nodata)
    target = ras[r0:r1, c0:c1]
    target[valid] = np.clip(np.round(sub[valid] * scale), -32767, 32767).astype(np.int16)
    ras[r0:r1, c0:c1] = target
    return int(valid.sum())


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", type=Path, required=True, help="directory holding the EGMS_L3_*_U_*.tif tiles")
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args()
    tiles = sorted(a.src.glob(_TILE_GLOB))
    if not tiles:
        raise SystemExit(f"no {_TILE_GLOB} in {a.src}")
    cell_m = 100
    x0, y1, ncols, nrows = raster_window(cell_m)
    ras = np.full((nrows, ncols), NODATA, dtype=np.int16)
    years = None
    for path in tiles:
        arr, tx, ty, px, nodata = read_geotiff(path)
        if int(px) != cell_m:
            raise SystemExit(f"{path.name}: pixel size {px} m, expected {cell_m}")
        m = re.search(r"_U_(\d{4})_(\d{4})_", path.name)
        y = f"{m.group(1)}-{m.group(2)}" if m else "unbekannt"
        if years not in (None, y):
            raise SystemExit(f"{path.name}: release {y} differs from {years}")
        years = y
        n = place_tile(ras, x0, y1, cell_m, arr, tx, ty, nodata, SCALE)
        print(f"{path.name}: {n} measured cells")
    a.out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(a.out, v=ras, meta=np.array(json.dumps({"x0": x0, "y1": y1, "cell_m": cell_m, "years": years, "scale": SCALE})))
    print(f"wrote {a.out}: {nrows}x{ncols} cells, {int((ras != NODATA).sum())} measured, years {years}, {a.out.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
