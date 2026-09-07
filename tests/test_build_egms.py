import importlib.util
from pathlib import Path

import numpy as np

_spec = importlib.util.spec_from_file_location("build_egms", Path(__file__).resolve().parent.parent / "scripts" / "build_egms.py")
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


def test_raster_window_matches_nrw_bbox():
    x0, y1, ncols, nrows = mod.raster_window(100)
    assert x0 % 100 == 0 and y1 % 100 == 0
    assert 2_700 <= ncols <= 2_800 and 2_700 <= nrows <= 2_800


def test_place_tile_scales_clips_and_skips_nodata():
    ras = np.full((4, 4), mod.NODATA, dtype=np.int16)          # raster 400×400 m, west edge 1000, north edge 2000
    tile = np.array([[1.234, float("nan")], [-9999.0, -27.66]], dtype=np.float32)
    n = mod.place_tile(ras, 1000, 2000, 100, tile, tx=1100, ty=1900, nodata=-9999.0, scale=100)   # tile top-left at col 1, row 1
    assert n == 2
    assert ras[1, 1] == 123 and ras[2, 2] == -2766
    assert ras[1, 2] == mod.NODATA and ras[2, 1] == mod.NODATA


def test_place_tile_clips_tiles_that_overhang_the_raster():
    ras = np.full((2, 2), mod.NODATA, dtype=np.int16)
    tile = np.full((3, 3), 1.0, dtype=np.float32)
    n = mod.place_tile(ras, 0, 200, 100, tile, tx=-100, ty=300, nodata=-9999.0, scale=100)       # overhangs west and north
    assert n == 4 and ras.tolist() == [[100, 100], [100, 100]]
