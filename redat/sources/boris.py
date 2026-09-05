"""
BORIS NRW Local Lookup Service
Point-in-polygon Bodenrichtwert queries against local geodata, 2011-2025.

Preferred source is `<source_dir>/boris/brw.gpkg` - one R-tree-indexed GeoPackage layer per year
(`brw_{year}`), built once by scripts/build_boris_gpkg.py from the yearly NRW shapefiles. Any year
without a layer falls back to `BRW_{year}/BRW_{year}_Polygon.shp`. Every lookup is a single
bbox-limited read: a few ms against the GeoPackage, ~2 s cold against an un-indexed shapefile (GDAL has
to scan the whole 200-400 MB file). Nothing ever loads a whole year into memory.
"""
import logging
from pathlib import Path
from typing import Optional, NamedTuple
from dataclasses import dataclass

import geopandas as gpd
import pyogrio
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

GPKG_NAME = "brw.gpkg"  # <source_dir>/boris/brw.gpkg, layers brw_2011 ... brw_2025


class Source(NamedTuple):
    path: Path
    layer: Optional[str]  # GeoPackage layer name, or None for a bare shapefile


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


def _gpkg_layers(path: Path) -> set[str]:
    if not path.exists():
        return set()
    try:
        return {name for name, _geom in pyogrio.list_layers(path).tolist()}
    except Exception as e:  # noqa: BLE001 - unreadable file: behave as if absent, shapefiles still work
        logger.warning("BORIS GeoPackage %s unreadable, falling back to shapefiles: %s", path, e)
        return set()


def _find_source(year: int) -> Optional[Source]:
    """GeoPackage layer for the year if present, else the year's shapefile, else None."""
    gpkg = data_dir() / GPKG_NAME
    layer = f"brw_{year}"
    if layer in _gpkg_layers(gpkg):
        return Source(gpkg, layer)
    shp = _find_shapefile(year)
    return Source(shp, None) if shp else None


def _redecode(v: str) -> str:
    """Undo a Latin-1 read of bytes that were really UTF-8; leave genuine Latin-1 text alone."""
    try:
        return v.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return v


def repair_mixed_encoding(df):
    """Fix text columns of a frame that was read with encoding="ISO-8859-1" from a file whose rows mix
    UTF-8 and ISO-8859-1 (the 2022-2024 NRW BRW shapefiles: .cpg says UTF-8, ~400 Moers rows are not).

    Latin-1 maps every byte to exactly one code point, so the read is lossless; per value we then
    re-decode as UTF-8 where that succeeds and keep the Latin-1 reading where it does not. Only
    non-ASCII cells are touched. Modifies and returns df.
    """
    for col in df.columns:
        if col == "geometry" or df[col].dtype != object:
            continue
        mask = df[col].notna() & df[col].astype(str).str.contains(r"[^\x00-\x7f]", regex=True)
        if mask.any():
            df.loc[mask, col] = df.loc[mask, col].map(lambda v: _redecode(str(v)))
    return df


def _read_bbox(source: Source, bbox: tuple[float, float, float, float]) -> gpd.GeoDataFrame:
    kw = {"layer": source.layer} if source.layer else {}
    try:
        return gpd.read_file(source.path, bbox=bbox, **kw)
    except UnicodeDecodeError:
        # Shapefile with mixed-encoding rows (see repair_mixed_encoding); GeoPackages built by
        # scripts/build_boris_gpkg.py are clean UTF-8 and never take this path.
        logger.warning("BORIS %s: mixed-encoding rows, re-reading as ISO-8859-1 with per-value repair", source.path.name)
        return repair_mixed_encoding(gpd.read_file(source.path, bbox=bbox, encoding="ISO-8859-1", **kw))


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

        source = _find_source(year)
        if not source:
            return None

        # ONE bbox-limited read. A zone that covers the point - or sits within the 10 m snap
        # tolerance below - necessarily intersects this bbox, so a wider read or a full-file load
        # could never find anything this read missed. (The old 5 km re-read + full shapefile load
        # fallbacks cost 6-12 s and ~1 GB per year and found nothing extra - they took boris_trend
        # past its 30 s timeout and OOM-killed a 2 GB container.)
        buf = 1000
        gdf = _read_bbox(source, (x - buf, y - buf, x + buf, y + buf))
        if gdf.empty:
            return None

        # covers() includes boundary points; more robust than contains()
        try:
            matches = gdf[gdf.geometry.covers(point)]
        except Exception:
            matches = gdf[gdf.geometry.contains(point)]

        if matches.empty:
            # Last resort: nearest polygon within tolerance (handles tiny gaps between zones)
            distances = gdf.geometry.distance(point)
            min_dist = float(distances.min())
            if min_dist > 10.0:
                logger.debug(f"No BORIS zone found for {lat}, {lon} in {year} (min_dist={min_dist:.2f}m)")
                return None
            matches = gdf.loc[[distances.idxmin()]]

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
        if _find_source(year):
            available.append(year)
    return available


_TIMEOUT = object()  # sentinel returned by _lookup_in_subprocess when the worker is killed


def _worker(queue, lat: float, lon: float) -> None:
    try:
        queue.put(lookup_bodenrichtwert(lat, lon))
    except Exception as e:  # noqa: BLE001 — serialised back to the parent
        queue.put({"__error__": str(e)})


def _lookup_in_subprocess(lat: float, lon: float):
    """Run the geodata lookup in a child process with a 12 s hard cap (guards a cold, un-indexed shapefile read)."""
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
