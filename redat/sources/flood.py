"""HWRM NRW (Flood) local lookup.

Uses HWRM-RL flood boundary shapefiles (EPSG:25832) to determine whether a point
falls into a flood area for different probability scenarios:
- HQhaeufig (high probability, ~HQ10–HQ50)
- HQ100 (medium probability)
- HQextrem (extreme)

Data source (Open Data NRW):
https://www.opengeodata.nrw.de/produkte/umwelt_klima/wasser/hochwasser/hwrm/
"""

import logging
from pathlib import Path
from typing import NamedTuple, Optional

import geopandas as gpd
from pyproj import Transformer
from shapely.geometry import Point

from redat.settings import get_settings

logger = logging.getLogger(__name__)


def data_dir() -> Path:
    return get_settings().source_dir / "flood" / "hwrm"


# Coordinate transformer: WGS84 -> EPSG:25832
transformer = Transformer.from_crs("EPSG:4326", "EPSG:25832", always_xy=True)


class FloodHit(NamedTuple):
    scenario: str  # HQhaeufig | HQ100 | HQextrem
    hit: bool
    min_distance_m: Optional[float]
    raw: dict | None


def SCENARIOS() -> dict[str, Path]:
    d = data_dir()
    return {"HQhaeufig": d / "HQhaeufig.gpkg", "HQ100": d / "HQ100.gpkg", "HQextrem": d / "HQextrem.gpkg"}


def _SCENARIOS_SHP() -> dict[str, Path]:
    d = data_dir()
    return {  # shapefile fallback (only the .gpkg files are copied to REDAT, but keep the lookup)
        "HQhaeufig": d / "HQhaeufig-Ueberschwemmungsgrenzen_EPSG25832_Shape" / "ueberflutungsgrenzen_hohe_wahrscheinlichkeit.shp",
        "HQ100": d / "HQ100-Ueberschwemmungsgrenzen_EPSG25832_Shape" / "ueberflutungsgrenzen_mittlere_wahrscheinlichkeit.shp",
        "HQextrem": d / "HQextrem-Ueberschwemmungsgrenzen_EPSG25832_Shape" / "ueberflutungsgrenzen_niedrige Wahrscheinlichkeit.shp",
    }


def _read_bbox(shp: Path, bbox: tuple[float, float, float, float]) -> gpd.GeoDataFrame:
    try:
        return gpd.read_file(shp, bbox=bbox)
    except TypeError:
        # fallback if bbox not supported
        return gpd.read_file(shp)


def _hit_for_scenario(lat: float, lon: float, scenario: str) -> FloodHit:
    shp = SCENARIOS().get(scenario)
    # Fallback to shapefile if GPKG missing
    if not shp or not shp.exists():
        shp = _SCENARIOS_SHP().get(scenario)
    if not shp or not shp.exists():
        return FloodHit(scenario=scenario, hit=False, min_distance_m=None, raw=None)

    x, y = transformer.transform(lon, lat)
    pt = Point(x, y)

    # try small bbox first
    buf = 2000
    bbox = (x - buf, y - buf, x + buf, y + buf)

    gdf = _read_bbox(shp, bbox)

    # Robust predicate: covers includes boundary points
    try:
        matches = gdf[gdf.geometry.covers(pt)]
    except Exception:
        matches = gdf[gdf.geometry.contains(pt)]

    if not matches.empty:
        row = matches.iloc[0].to_dict()
        row.pop("geometry", None)
        return FloodHit(scenario=scenario, hit=True, min_distance_m=0.0, raw={k: str(v) if v is not None else None for k, v in row.items()})

    # fallback: nearest polygon within tolerance (handles tiny gaps)
    try:
        dists = gdf.geometry.distance(pt)
        min_dist = float(dists.min()) if len(dists) else None
        if min_dist is not None and min_dist <= 10.0:
            idx = dists.idxmin()
            row = gdf.loc[idx].to_dict()
            row.pop("geometry", None)
            return FloodHit(scenario=scenario, hit=True, min_distance_m=min_dist, raw={k: str(v) if v is not None else None for k, v in row.items()})
        return FloodHit(scenario=scenario, hit=False, min_distance_m=min_dist, raw=None)
    except Exception:
        return FloodHit(scenario=scenario, hit=False, min_distance_m=None, raw=None)


def flood_risk(lat: float, lon: float) -> dict:
    """Return flood risk summary for a point."""
    if not data_dir().exists():
        raise RuntimeError(f"Hochwasser-Daten fehlen unter {data_dir()}")
    hits = {sc: _hit_for_scenario(lat, lon, sc) for sc in SCENARIOS().keys()}

    # Determine worst-case zone (if any)
    zone = None
    risk_level = "low"

    if hits["HQhaeufig"].hit:
        zone = "HQhaeufig"
        risk_level = "high"
    elif hits["HQ100"].hit:
        zone = "HQ100"
        risk_level = "medium"
    elif hits["HQextrem"].hit:
        zone = "HQextrem"
        risk_level = "medium"

    return {
        "zone": zone,
        "risk_level": risk_level,
        "hits": {sc: {"hit": h.hit, "min_distance_m": (round(h.min_distance_m, 2) if h.min_distance_m is not None else None), "raw": h.raw} for sc, h in hits.items()},
    }
