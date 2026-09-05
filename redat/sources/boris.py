"""
BORIS NRW Local Lookup Service
Uses downloaded Shapefile data for fast Bodenrichtwert queries.
Supports historical data from 2011-2025.
"""
import logging
from pathlib import Path
from typing import Optional, NamedTuple
from dataclasses import dataclass

import geopandas as gpd
from pyproj import Transformer
from shapely.geometry import Point

import warnings
from functools import lru_cache

from redat.settings import get_settings

# Silence noisy shapefile geometry warnings (we handle robustness ourselves)
warnings.filterwarnings("ignore", category=RuntimeWarning, module="pyogrio")

logger = logging.getLogger(__name__)


class MissingData(RuntimeError):
    """The local BRW shapefiles are not where settings.source_dir says (deploy asset, not in git)."""


def data_dir() -> Path:
    return get_settings().source_dir / "boris"


# Coordinate transformer: WGS84 (GPS) -> EPSG:25832 (UTM Zone 32N)
transformer = Transformer.from_crs("EPSG:4326", "EPSG:25832", always_xy=True)

# Available years
AVAILABLE_YEARS = list(range(2011, 2026))  # 2011-2025

# Cache only for most recent year to keep memory bounded
_boris_cache: dict[int, gpd.GeoDataFrame] = {}
_MAX_CACHED_YEARS = 1


class BorisResult(NamedTuple):
    """Result from BORIS lookup."""
    bodenrichtwert: float  # €/m²
    stichtag: str  # Date (YYYY-MM-DD)
    nutzung: str  # Land use type
    zone_name: str  # Zone identifier
    gemeinde: str  # Municipality
    year: int  # Data year
    raw: dict  # All attributes


def _parse_boris_number(v) -> float:
    """Parse BORIS numeric fields that may be stored as strings with comma decimals."""
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if not s:
        return 0.0
    # handle german decimal comma
    s = s.replace('.', '').replace(',', '.') if (',' in s and s.count(',') == 1) else s.replace(',', '.')
    try:
        return float(s)
    except Exception:
        return 0.0


@dataclass
class BorisTrend:
    """Historical trend data for a location."""
    current_value: float
    current_year: int
    history: list[dict]  # [{year, value, change_percent}]
    avg_yearly_change: float  # Average yearly change in %
    total_change: float  # Total change from oldest to newest in %
    oldest_year: int
    oldest_value: float


def _find_shapefile(year: int) -> Optional[Path]:
    """Find the shapefile for a given year."""
    # Try different naming patterns
    d = data_dir()
    patterns = [
        d / f"BRW_{year}" / f"BRW_{year}_Polygon.shp",
        d / f"BRW_{year}" / "BRW_Polygon.shp",
        d / f"BRW_{year}_Polygon.shp",
    ]

    for pattern in patterns:
        if pattern.exists():
            return pattern

    # Search for any .shp file in the year directory
    year_dir = d / f"BRW_{year}"
    if year_dir.exists():
        shp_files = list(year_dir.glob("*.shp"))
        if shp_files:
            return shp_files[0]
    
    return None


def _load_boris_data(year: int) -> Optional[gpd.GeoDataFrame]:
    """Load BORIS Shapefile for a specific year.

    We intentionally keep caching bounded to avoid loading 15 full NRW shapefiles into RAM.
    """
    if year in _boris_cache:
        return _boris_cache[year]

    shapefile = _find_shapefile(year)
    if not shapefile:
        logger.warning(f"No BORIS data found for year {year}")
        return None

    logger.info(f"Loading BORIS {year} data from {shapefile}...")
    gdf = gpd.read_file(shapefile)
    logger.info(f"Loaded {len(gdf)} BORIS zones for {year}")

    # Keep cache small (most recent lookup only)
    _boris_cache.clear()
    _boris_cache[year] = gdf
    return gdf


def lookup_bodenrichtwert(lat: float, lon: float, year: int = 2025) -> Optional[BorisResult]:
    """
    Look up Bodenrichtwert for a WGS84 coordinate.
    
    Args:
        lat: Latitude (WGS84)
        lon: Longitude (WGS84)
        year: Year of data to query (2011-2025)
    
    Returns:
        BorisResult or None if not found
    """
    if not data_dir().exists():
        raise MissingData(f"BORIS-Daten fehlen unter {data_dir()}")
    if year not in AVAILABLE_YEARS:
        logger.warning(f"Year {year} not available. Using 2025.")
        year = 2025
    
    try:
        # Transform WGS84 to EPSG:25832
        x, y = transformer.transform(lon, lat)
        point = Point(x, y)

        shapefile = _find_shapefile(year)
        if not shapefile:
            return None

        # For speed, load only a small bbox around the point (in EPSG:25832 meters)
        # 1000m buffer to robustly catch the correct BRW polygon across years.
        buf = 1000
        bbox = (x - buf, y - buf, x + buf, y + buf)

        def _match(gdf):
            # covers() includes boundary points; more robust than contains()
            try:
                return gdf[gdf.geometry.covers(point)]
            except Exception:
                return gdf[gdf.geometry.contains(point)]

        try:
            gdf = gpd.read_file(shapefile, bbox=bbox)
        except TypeError:
            gdf = None

        matches = _match(gdf) if gdf is not None else gpd.GeoDataFrame()

        # Fallback 1: expand bbox if no match
        if matches.empty:
            buf2 = 5000
            bbox2 = (x - buf2, y - buf2, x + buf2, y + buf2)
            try:
                gdf2 = gpd.read_file(shapefile, bbox=bbox2)
                matches = _match(gdf2)
            except Exception:
                matches = gpd.GeoDataFrame()

        # Fallback 2: full load (cached) if still no match
        if matches.empty:
            gdf_full = _load_boris_data(year)
            if gdf_full is None:
                return None
            matches = _match(gdf_full)
        
        if matches.empty:
            # Last resort: pick nearest polygon within tolerance (handles tiny gaps)
            try:
                distances = gdf_full.geometry.distance(point) if 'gdf_full' in locals() else gdf.geometry.distance(point)
                min_dist = float(distances.min())
                if min_dist <= 10.0:
                    idx = distances.idxmin()
                    matches = (gdf_full if 'gdf_full' in locals() else gdf).loc[[idx]]
                else:
                    logger.debug(f"No BORIS zone found for {lat}, {lon} in {year} (min_dist={min_dist:.2f}m)")
                    return None
            except Exception:
                return None

        # Take first match
        row = matches.iloc[0]
        
        # Extract relevant fields
        raw = row.to_dict()
        raw.pop('geometry', None)
        
        return BorisResult(
            bodenrichtwert=_parse_boris_number(row.get('BRW', 0)),
            stichtag=str(row.get('STAG', f'{year}-01-01')),
            nutzung=str(row.get('NUTZ', '') or row.get('NUTZUNG', '') or row.get('NUTA', '')),
            zone_name=str(row.get('GENA', '') or row.get('BRWZ', '')),
            gemeinde=str(row.get('GEMNAME', '') or row.get('GEM', '')),
            year=year,
            raw={k: str(v) if v is not None else None for k, v in raw.items()},
        )
        
    except Exception as e:
        logger.error(f"BORIS lookup error for {year}: {e}")
        return None


@lru_cache(maxsize=512)
def _trend_cached(lat_r: float, lon_r: float) -> Optional[BorisTrend]:
    # default: all available years
    return _trend_uncached(lat_r, lon_r, tuple(AVAILABLE_YEARS))


def get_historical_trend(lat: float, lon: float, years: list[int] = None) -> Optional[BorisTrend]:
    """Get historical Bodenrichtwert trend for a location.

    Uses caching keyed by rounded coordinates to keep /enrichment responsive.
    """
    if years is None:
        # cache at ~11m precision
        return _trend_cached(round(lat, 4), round(lon, 4))
    return _trend_uncached(lat, lon, tuple(years))


def _trend_uncached(lat: float, lon: float, years_t: tuple[int, ...]) -> Optional[BorisTrend]:
    """Non-cached trend computation."""
    if not data_dir().exists():
        raise MissingData(f"BORIS-Daten fehlen unter {data_dir()}")
    years = list(years_t)

    history = []
    prev_value = None

    for year in sorted(years):
        result = lookup_bodenrichtwert(lat, lon, year)
        if result and result.bodenrichtwert > 0:
            change_pct = None
            if prev_value and prev_value > 0:
                change_pct = ((result.bodenrichtwert - prev_value) / prev_value) * 100
            
            history.append({
                "year": year,
                "value": result.bodenrichtwert,
                "change_percent": round(change_pct, 2) if change_pct is not None else None,
                "nutzung": result.nutzung,
            })
            prev_value = result.bodenrichtwert
    
    if not history:
        return None
    
    # Calculate statistics
    current = history[-1]
    oldest = history[0]
    
    total_change = ((current["value"] - oldest["value"]) / oldest["value"]) * 100 if oldest["value"] > 0 else 0
    
    # Average yearly change (excluding first year which has no change)
    changes = [h["change_percent"] for h in history if h["change_percent"] is not None]
    avg_change = sum(changes) / len(changes) if changes else 0
    
    return BorisTrend(
        current_value=current["value"],
        current_year=current["year"],
        history=history,
        avg_yearly_change=round(avg_change, 2),
        total_change=round(total_change, 2),
        oldest_year=oldest["year"],
        oldest_value=oldest["value"],
    )


def get_available_years() -> list[int]:
    """Get list of years with available data."""
    available = []
    for year in AVAILABLE_YEARS:
        if _find_shapefile(year):
            available.append(year)
    return available


_TIMEOUT = object()  # sentinel returned by _lookup_in_subprocess when the worker is killed


def _worker(queue, lat: float, lon: float) -> None:
    try:
        queue.put(lookup_bodenrichtwert(lat, lon))
    except Exception as e:  # noqa: BLE001 — serialised back to the parent
        queue.put({"__error__": str(e)})


def _lookup_in_subprocess(lat: float, lon: float):
    """Run the (memory-heavy) shapefile lookup in a child process with a 12 s hard cap."""
    from multiprocessing import Process, Queue
    q: Queue = Queue()
    p = Process(target=_worker, args=(q, lat, lon), daemon=True)
    p.start()
    p.join(timeout=12)
    if p.is_alive():
        p.kill()
        return _TIMEOUT
    return q.get() if not q.empty() else None


def get_boris_nrw(lat: float, lon: float) -> dict:
    """{bodenrichtwert, date, zone, nutzung, gemeinde, raw} or {"error": …} — never raises."""
    try:
        out = _lookup_in_subprocess(lat, lon)
    except Exception as e:  # noqa: BLE001
        logger.error("BORIS error: %s", e)
        return {"error": str(e)}
    if out is _TIMEOUT:
        return {"error": "BORIS timeout"}
    if isinstance(out, dict) and out.get("__error__"):
        return {"error": out["__error__"]}
    if out:
        return {"bodenrichtwert": out.bodenrichtwert, "date": out.stichtag, "zone": out.zone_name,
                "nutzung": out.nutzung, "gemeinde": out.gemeinde, "raw": out.raw}
    return {"error": "No BORIS data for this location"}
