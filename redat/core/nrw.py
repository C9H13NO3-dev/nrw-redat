"""Shared NRW geometry — the bounding boxes every statewide grid, gate and build script uses.

Boxes are WGS84 (lon_min, lat_min, lon_max, lat_max). The city boxes are coarse (they overlap on the
Essen/Bochum border, see redat/sources/noise_extra.py) and only gate whether a city-only source is queried.
"""
from __future__ import annotations

from pyproj import Transformer

NRW_BBOX_WGS84: tuple[float, float, float, float] = (5.753, 50.242, 9.589, 52.619)
RVR_BBOX_WGS84: tuple[float, float, float, float] = (6.35, 51.25, 7.85, 51.85)     # Regionalverband Ruhr, coarse
ESSEN_BBOX_WGS84: tuple[float, float, float, float] = (6.89, 51.35, 7.14, 51.53)
BOCHUM_BBOX_WGS84: tuple[float, float, float, float] = (7.10, 51.40, 7.35, 51.53)

_TO_3035 = Transformer.from_crs("EPSG:4326", "EPSG:3035", always_xy=True)
_TO_25832 = Transformer.from_crs("EPSG:4326", "EPSG:25832", always_xy=True)


def in_bbox(lat: float, lon: float, bbox: tuple[float, float, float, float] = NRW_BBOX_WGS84) -> bool:
    lon_min, lat_min, lon_max, lat_max = bbox
    return lon_min <= lon <= lon_max and lat_min <= lat <= lat_max


def _projected(bbox: tuple[float, float, float, float], transformer: Transformer) -> tuple[float, float, float, float]:
    """Min/max of the four corners plus the north/south edge midpoints (curved edges in LAEA/UTM)."""
    lon_min, lat_min, lon_max, lat_max = bbox
    lon_mid = (lon_min + lon_max) / 2
    pts = [(lon_min, lat_min), (lon_min, lat_max), (lon_max, lat_min), (lon_max, lat_max), (lon_mid, lat_min), (lon_mid, lat_max)]
    xs, ys = zip(*(transformer.transform(lon, lat) for lon, lat in pts))
    return min(xs), min(ys), max(xs), max(ys)


def bbox_3035(bbox: tuple[float, float, float, float] = NRW_BBOX_WGS84) -> tuple[float, float, float, float]:
    return _projected(bbox, _TO_3035)


def bbox_25832(bbox: tuple[float, float, float, float] = NRW_BBOX_WGS84) -> tuple[float, float, float, float]:
    return _projected(bbox, _TO_25832)
