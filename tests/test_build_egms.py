import importlib.util
from pathlib import Path

import numpy as np

_spec = importlib.util.spec_from_file_location("build_egms", Path(__file__).resolve().parent.parent / "scripts" / "build_egms.py")
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


def test_crop_cells_keeps_window_and_skips_nodata():
    arr = np.full((4, 4), -1.5, dtype=np.float32)      # 4×4 cells of 100 m, top-left corner at (4_100_000, 3_160_000)
    arr[0, 0] = mod.NODATA
    arr[3, 3] = 2.25
    cells = mod.crop_cells(arr, 4_100_000, 3_160_000, 100, (4_100_000, 3_159_600, 4_100_400, 3_160_000))
    assert cells["4100350_3159650"] == 2.25 and cells["4100150_3159950"] == -1.5   # row 3 is the southern row
    assert "4100050_3159950" not in cells and len(cells) == 15


def test_crop_cells_bbox_excludes_outside():
    arr = np.zeros((2, 2), dtype=np.float32)
    assert mod.crop_cells(arr, 0, 200, 100, (150, 0, 200, 50)) == {"150_50": 0.0}


def test_crop_cells_skips_nan_keeps_neighbours():
    arr = np.full((2, 2), 1.0, dtype=np.float32)      # top-left corner at (0, 200), cells of 100 m
    arr[0, 1] = float("nan")                          # NE cell — unmeasured, as the real tile stores it
    cells = mod.crop_cells(arr, 0, 200, 100, (0, 0, 200, 200))
    assert cells == {"50_150": 1.0, "50_50": 1.0, "150_50": 1.0} and "150_150" not in cells


def test_crop_cells_rounds_float_error_in_cell_key():
    arr = np.array([[1.0]], dtype=np.float32)
    cells = mod.crop_cells(arr, 4_100_000 - 1e-9, 3_160_000, 100, (4_100_000, 3_159_900, 4_100_100, 3_160_000))
    assert cells == {"4100050_3159950": 1.0}   # int(round(...)) — a bare int(...) truncates ...49.9999999995 to ...49
