"""Address → coordinates with a precision signal (Geoapify first, Nominatim fallback).

A bare "lat, lon" input is parsed directly and reported with precision="coordinates"
(treated like a verified address by the parcel-tier gate). Nominatim has no
result_type, so its hits carry precision=None and parcel-tier cards stay gated.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

import httpx

from redat.http import headers
from redat.sources.geoapify import geocode_address

logger = logging.getLogger(__name__)

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
_COORD_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$")


class GeocoderUnavailable(RuntimeError):
    """Geoapify *and* Nominatim errored — an outage, not an unknown address (→ 502)."""


@dataclass(frozen=True)
class GeocodeResult:
    latitude: float
    longitude: float
    precision: Optional[str]  # "building" | "street" | "suburb" | ... | "coordinates" | None
    formatted_address: str


def parse_coordinates(text: str) -> Optional[tuple[float, float]]:
    """Return (lat, lon) if `text` is a plain "lat, lon" pair within WGS84 bounds."""
    m = _COORD_RE.match(text or "")
    if not m:
        return None
    lat, lon = float(m.group(1)), float(m.group(2))
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return None
    return lat, lon


def _nominatim(address: str) -> Optional[tuple[float, float, str]]:
    """(lat, lon, display_name) from Nominatim, None when it has no result. Raises on transport errors."""
    resp = httpx.get(NOMINATIM_URL, params={"q": address, "format": "json", "addressdetails": 1, "limit": 1, "countrycodes": "de"},
                     headers=headers(), timeout=10.0)
    resp.raise_for_status()
    results = resp.json()
    if not results:
        return None
    r = results[0]
    return float(r["lat"]), float(r["lon"]), r.get("display_name") or address


def geocode_with_precision(address: str) -> Optional[GeocodeResult]:
    """Geocode `address`; None when no source knows it; GeocoderUnavailable when every source errored."""
    coords = parse_coordinates(address)
    if coords:
        lat, lon = coords
        return GeocodeResult(lat, lon, "coordinates", f"{lat:.6f}, {lon:.6f}")

    failures = 0
    try:
        geo = geocode_address(address)
    except Exception as exc:  # noqa: BLE001
        logger.warning("geoapify geocode failed for %r: %s", address, exc)
        geo, failures = None, failures + 1
    if geo and geo.get("lat") and geo.get("lon"):
        return GeocodeResult(float(geo["lat"]), float(geo["lon"]), geo.get("precision"), geo.get("address") or address)

    try:
        hit = _nominatim(address)
    except Exception as exc:  # noqa: BLE001
        logger.warning("nominatim geocode failed for %r: %s", address, exc)
        hit, failures = None, failures + 1
    if hit:
        lat, lon, name = hit
        logger.info("geocode: Geoapify miss for %r, Nominatim fallback (precision=None → parcel gated)", address)
        return GeocodeResult(lat, lon, None, name)
    if failures == 2:
        raise GeocoderUnavailable("Geoapify und Nominatim nicht erreichbar")
    return None
