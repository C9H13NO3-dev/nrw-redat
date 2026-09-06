import io

import numpy as np
import pytest
from PIL import Image

from redat.sources import gelaende


def tiff(arr: np.ndarray) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(arr.astype(np.float32), mode="F").save(buf, format="TIFF")
    return buf.getvalue()


def plane(slope_x=0.0, slope_y=0.0, base=100.0, n=200):
    yy, xx = np.mgrid[0:n, 0:n]
    return base + slope_x * (xx - n / 2) + slope_y * (n / 2 - yy)     # row 0 = north, like the WCS tile


def test_parse_dgm_reads_float32_tile():
    arr = gelaende.parse_dgm(tiff(plane()))
    assert arr.shape == (200, 200) and arr.dtype == np.float32 and float(arr[100, 100]) == 100.0


def test_flat_plane_is_eben():
    d = gelaende.analyse(plane())
    assert d["hoehe_m"] == 100.0 and d["neigung_pct"] == 0.0 and d["lage"] == "eben"
    assert d["min_100m"] == 100.0 and d["max_100m"] == 100.0 and d["ueber_tiefstem_100m"] == 0.0


def test_slope_is_hanglage():
    d = gelaende.analyse(plane(slope_x=0.15))            # 15 % east-west gradient
    assert d["lage"] == "Hanglage" and 14.0 <= d["neigung_pct"] <= 16.0
    assert d["unter_hoechstem_100m"] > 10 and d["ueber_tiefstem_100m"] > 10


def test_bowl_is_tieflage():
    yy, xx = np.mgrid[0:200, 0:200]
    r = np.hypot(xx - 100, yy - 100)
    arr = 100.0 + np.where(r < 30, 0.0, (r - 30) * 0.1)  # flat floor, rising 10 % beyond 30 m
    d = gelaende.analyse(arr)
    assert d["lage"] == "Tieflage" and d["hoehe_m"] == 100.0 and d["max_100m"] >= 105


def test_hill_is_kuppenlage():
    yy, xx = np.mgrid[0:200, 0:200]
    r = np.hypot(xx - 100, yy - 100)
    arr = 100.0 - np.where(r < 30, 0.0, (r - 30) * 0.1)
    assert gelaende.analyse(arr)["lage"] == "Kuppenlage"


def test_nodata_is_ignored():
    arr = plane(); arr[:10, :10] = -9999.0
    d = gelaende.analyse(arr)
    assert d["min_100m"] == 100.0


def test_center_nodata_raises():
    arr = plane(); arr[100, 100] = -9999.0
    with pytest.raises(Exception):
        gelaende.analyse(arr)


def test_get_gelaende_requests_200m_box(monkeypatch):
    seen = {}

    def fake(bbox):
        seen["bbox"] = bbox
        return tiff(plane())
    monkeypatch.setattr(gelaende, "_get_coverage", fake)
    d = gelaende.get_gelaende(51.4300, 7.0050)
    xmin, ymin, xmax, ymax = seen["bbox"]
    assert abs((xmax - xmin) - 200) < 1e-6 and abs((ymax - ymin) - 200) < 1e-6 and 361_200 < xmin < 361_300
    assert d["radius_m"] == 100 and d["lage"] == "eben"


def test_bad_tile_raises(monkeypatch):
    monkeypatch.setattr(gelaende, "_get_coverage", lambda bbox: b"not a tiff")
    with pytest.raises(Exception):
        gelaende.get_gelaende(51.43, 7.0)
