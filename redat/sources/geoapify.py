"""Geoapify Places & Routing API for POI lookups and travel times."""

from __future__ import annotations

import logging
from typing import Any, Optional
import httpx

from redat.http import headers
from redat.settings import get_settings

logger = logging.getLogger(__name__)


def _api_key() -> str:
    return get_settings().geoapify_api_key


PLACES_URL = "https://api.geoapify.com/v2/places"
ROUTING_URL = "https://api.geoapify.com/v1/routing"
GEOCODE_URL = "https://api.geoapify.com/v1/geocode/search"
REVERSE_GEOCODE_URL = "https://api.geoapify.com/v1/geocode/reverse"


def _get(url: str, params: dict) -> httpx.Response:
    """Shared HTTP GET helper for the geocode endpoints (forward + reverse).

    Mirrors the timeout/error-handling used by geocode_address: a 10s timeout,
    no retries, and raise_for_status() so callers can catch via a single
    except Exception block.
    """
    with httpx.Client(timeout=10.0, headers=headers()) as client:
        resp = client.get(url, params=params)
        resp.raise_for_status()
        return resp


def _parse_geocode_feature(feature: dict) -> dict:
    """Parse a single Geoapify GeoJSON feature into a structured geocode result.

    Returns keys: lat, lon, address, precision, housenumber, confidence, suburb.
    "suburb" is the first non-empty of suburb/neighbourhood/district (same
    normalization as reverse_geocode) -- forward-geocode results carry the
    same address-component properties as reverse ones. Geoapify GeoJSON
    coordinates are [lon, lat] order.
    """
    props = feature.get("properties", {})
    coords = feature.get("geometry", {}).get("coordinates", [])

    lat = coords[1] if len(coords) >= 2 else None
    lon = coords[0] if len(coords) >= 2 else None

    # precision: prefer result_type; fallback based on housenumber presence
    result_type = props.get("result_type")
    housenumber = props.get("housenumber")
    if result_type:
        precision = result_type
    elif housenumber:
        precision = "building"
    else:
        precision = "unknown"

    # confidence: nested under rank.confidence — guard missing
    rank = props.get("rank") or {}
    confidence = rank.get("confidence") if isinstance(rank, dict) else None

    return {
        "lat": lat,
        "lon": lon,
        "address": props.get("formatted", ""),
        "precision": precision,
        "housenumber": housenumber,
        "confidence": confidence,
        "suburb": props.get("suburb") or props.get("neighbourhood") or props.get("district") or None,
    }


def geocode_address(address: str) -> Optional[dict]:
    """Geocode an address to coordinates.

    Returns {lat, lon, address, precision, housenumber, confidence} or None.
    Existing callers that read only lat/lon/address are unaffected by the added keys.
    """
    if not address or not address.strip():
        return None

    params = {
        "text": address,
        "filter": "countrycode:de",
        "limit": 1,
        "apiKey": _api_key(),
    }

    try:
        resp = _get(GEOCODE_URL, params)
        data = resp.json()
    except httpx.HTTPError:
        # Transport/status errors are a real outage, not "address unknown" — let the
        # caller (redat.core.geocoding) see it so it can fall back to Nominatim and
        # only raise GeocoderUnavailable if that fails too.
        raise
    except Exception as e:
        logger.error(f"Geocode error: {e}")
        return None

    features = data.get("features", [])
    if not features:
        return None

    coords = features[0].get("geometry", {}).get("coordinates", [])
    if len(coords) < 2:
        return None

    result = _parse_geocode_feature(features[0])
    # If formatted address is empty, fall back to the input address
    if not result["address"]:
        result["address"] = address
    return result


def reverse_geocode(lat: float, lon: float) -> Optional[dict]:
    """Reverse geocode coordinates to the enclosing address/district.

    Returns the first feature's properties (a dict incl. city, postcode, ...)
    with "suburb" normalized to the first non-empty of suburb/neighbourhood/
    district. None on HTTP error (incl. a missing/invalid API key, which the
    API rejects) or no results. Mirrors geocode_address's key handling: the
    key is passed through as-is and any resulting HTTP error is caught below.
    """
    params = {
        "lat": lat,
        "lon": lon,
        "apiKey": _api_key(),
    }

    try:
        resp = _get(REVERSE_GEOCODE_URL, params)
        data = resp.json()

        features = data.get("features", [])
        if not features:
            return None

        props = dict(features[0].get("properties", {}))
        props["suburb"] = (
            props.get("suburb") or props.get("neighbourhood") or props.get("district") or None
        )
        return props
    except Exception as e:
        logger.error(f"Reverse geocode error: {e}")
        return None


def get_driving_time(
    from_lat: float, from_lon: float,
    to_lat: float, to_lon: float,
) -> Optional[dict]:
    """Get driving time and distance between two points."""
    params = {
        "waypoints": f"{from_lat},{from_lon}|{to_lat},{to_lon}",
        "mode": "drive",
        "apiKey": _api_key(),
    }

    try:
        with httpx.Client(timeout=15.0, headers=headers()) as client:
            resp = client.get(ROUTING_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
        
        features = data.get("features", [])
        if not features:
            return None
        
        props = features[0].get("properties", {})
        
        # Time is in seconds, distance in meters
        time_sec = props.get("time", 0)
        distance_m = props.get("distance", 0)
        
        return {
            "time_minutes": round(time_sec / 60),
            "time_seconds": time_sec,
            "distance_km": round(distance_m / 1000, 1),
            "distance_m": distance_m,
        }
    except Exception as e:
        logger.error(f"Routing error: {e}")
        return None


def get_commute_times(from_lat: float, from_lon: float, destinations: list[dict]) -> list[dict]:
    """
    Calculate driving times to multiple destinations.
    
    destinations: [{"name": "Work", "address": "..."}, ...]
    Returns: [{"name": "Work", "address": "...", "time_minutes": 25, "distance_km": 18.5}, ...]
    """
    results = []
    
    for dest in destinations:
        if not dest.get("address"):
            continue
        
        # Geocode destination
        geo = geocode_address(dest["address"])
        if not geo:
            results.append({
                "name": dest.get("name", ""),
                "address": dest.get("address", ""),
                "error": "Adresse nicht gefunden",
            })
            continue
        
        # Get driving time
        route = get_driving_time(from_lat, from_lon, geo["lat"], geo["lon"])
        if not route:
            results.append({
                "name": dest.get("name", ""),
                "address": dest.get("address", ""),
                "error": "Route nicht berechenbar",
            })
            continue
        
        results.append({
            "name": dest.get("name", ""),
            "address": geo["address"],
            "time_minutes": route["time_minutes"],
            "distance_km": route["distance_km"],
        })
    
    return results


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance in meters between two points."""
    from math import radians, sin, cos, sqrt, atan2
    R = 6371000
    phi1, phi2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dlambda = radians(lon2 - lon1)
    a = sin(dphi/2)**2 + cos(phi1) * cos(phi2) * sin(dlambda/2)**2
    return R * 2 * atan2(sqrt(a), sqrt(1-a))


def get_places(
    lat: float,
    lon: float,
    categories: list[str],
    radius_m: int = 2000,
    limit: int = 10,
) -> list[dict]:
    """
    Fetch places from Geoapify.
    
    Categories: https://apidocs.geoapify.com/docs/places/#categories
    Examples: education.school, commercial.supermarket, healthcare, public_transport
    """
    params = {
        "categories": ",".join(categories),
        "filter": f"circle:{lon},{lat},{radius_m}",
        "limit": limit,
        "apiKey": _api_key(),
    }

    try:
        with httpx.Client(timeout=15.0, headers=headers()) as client:
            resp = client.get(PLACES_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
        
        results = []
        for feat in data.get("features", []):
            props = feat.get("properties", {})
            coords = feat.get("geometry", {}).get("coordinates", [None, None])
            
            if coords[0] is None:
                continue
                
            place_lon, place_lat = coords[0], coords[1]
            distance = _haversine(lat, lon, place_lat, place_lon)
            
            results.append({
                "name": props.get("name") or props.get("address_line1") or "Unbenannt",
                "category": props.get("categories", [""])[0] if props.get("categories") else "",
                "lat": place_lat,
                "lon": place_lon,
                "distance_m": int(distance),
                "address": props.get("formatted", ""),
            })
        
        # Sort by distance (should already be sorted, but ensure consistency)
        results.sort(key=lambda x: (x["distance_m"], x["name"]))
        return results
        
    except Exception as e:
        logger.error(f"Geoapify error: {e}")
        return []


def get_schools(lat: float, lon: float, radius_m: int = 2000) -> list[dict]:
    """Get nearby schools."""
    return get_places(lat, lon, ["education.school"], radius_m, limit=10)


def get_kindergartens(lat: float, lon: float, radius_m: int = 2000) -> list[dict]:
    """Get nearby kindergartens/childcare."""
    return get_places(lat, lon, ["childcare"], radius_m, limit=10)


def get_supermarkets(lat: float, lon: float, radius_m: int = 2000) -> list[dict]:
    """Get nearby supermarkets."""
    return get_places(lat, lon, ["commercial.supermarket"], radius_m, limit=10)


def get_doctors(lat: float, lon: float, radius_m: int = 2000) -> list[dict]:
    """Get nearby doctors/clinics/healthcare."""
    return get_places(lat, lon, ["healthcare"], radius_m, limit=10)


def get_public_transport(lat: float, lon: float, radius_m: int = 1500) -> dict:
    """Get nearby public transport stops with score calculation."""
    stops = get_places(
        lat, lon,
        ["public_transport.bus", "public_transport.train", "public_transport.tram", "public_transport.subway"],
        radius_m,
        limit=20
    )
    
    # Enrich with type
    for stop in stops:
        cat = stop.get("category", "")
        if "train" in cat or "railway" in cat:
            stop["type"] = "train"
        elif "tram" in cat:
            stop["type"] = "tram"
        elif "subway" in cat or "metro" in cat:
            stop["type"] = "ubahn"
        else:
            stop["type"] = "bus"
    
    # Calculate score
    score = 0
    if stops:
        nearest = stops[0]["distance_m"]
        if nearest < 300:
            score = 10
        elif nearest < 500:
            score = 8
        elif nearest < 800:
            score = 6
        elif nearest < 1200:
            score = 4
        else:
            score = 2
        
        # Bonus for variety
        types = set(s["type"] for s in stops[:5])
        if "train" in types or "ubahn" in types:
            score = min(10, score + 1)
        if len(types) > 1:
            score = min(10, score + 1)
    
    return {
        "score": score,
        "nearest_m": stops[0]["distance_m"] if stops else None,
        "stops": stops[:10],
    }


def get_all_amenities(lat: float, lon: float) -> dict:
    """Get all amenities in one call (more efficient)."""
    result = {}
    
    # Public transport
    transport = get_public_transport(lat, lon)
    result["public_transport_score"] = transport["score"]
    result["distance_to_public_transport_m"] = transport["nearest_m"]
    result["public_transport"] = transport["stops"][:5]
    
    # Schools
    schools = get_schools(lat, lon)
    if schools:
        result["distance_to_school_m"] = schools[0]["distance_m"]
        result["schools"] = schools[:5]
    
    # Kindergartens
    kindergartens = get_kindergartens(lat, lon)
    if kindergartens:
        result["distance_to_kindergarten_m"] = kindergartens[0]["distance_m"]
        result["kindergartens"] = kindergartens[:5]
    
    # Supermarkets
    supermarkets = get_supermarkets(lat, lon)
    if supermarkets:
        result["distance_to_supermarket_m"] = supermarkets[0]["distance_m"]
        result["supermarkets"] = supermarkets[:5]
    
    # Doctors
    doctors = get_doctors(lat, lon)
    if doctors:
        result["distance_to_doctor_m"] = doctors[0]["distance_m"]
        result["doctors"] = doctors[:5]
    
    # Walkability score
    walkability = 0
    if result.get("distance_to_supermarket_m") and result["distance_to_supermarket_m"] < 800:
        walkability += 3
    if result.get("distance_to_public_transport_m") and result["distance_to_public_transport_m"] < 500:
        walkability += 3
    if result.get("distance_to_school_m") and result["distance_to_school_m"] < 1000:
        walkability += 2
    if result.get("distance_to_doctor_m") and result["distance_to_doctor_m"] < 1000:
        walkability += 2
    result["walkability_score"] = min(10, walkability)

    return result


AUTOCOMPLETE_URL = "https://api.geoapify.com/v1/geocode/autocomplete"


def autocomplete_address(text: str, limit: int = 8, bias_lat: float | None = None, bias_lon: float | None = None) -> list[dict[str, Any]]:
    if not text or not text.strip():
        return []

    params: dict[str, Any] = {
        "text": text,
        "format": "json",
        "filter": "countrycode:de",
        "limit": max(1, min(int(limit), 15)),
        "apiKey": _api_key(),
    }

    # Optional bias around Ruhrgebiet to improve ranking
    if bias_lat is not None and bias_lon is not None:
        params["bias"] = f"proximity:{bias_lon},{bias_lat}"

    try:
        with httpx.Client(timeout=6.0, headers=headers()) as client:
            r = client.get(AUTOCOMPLETE_URL, params=params)
            r.raise_for_status()
            data = r.json()

        results = []
        for it in data.get("results", []) or []:
            results.append(
                {
                    "formatted": it.get("formatted"),
                    "lat": it.get("lat"),
                    "lon": it.get("lon"),
                    "postcode": it.get("postcode"),
                    "city": it.get("city") or it.get("town"),
                    "street": it.get("street"),
                    "housenumber": it.get("housenumber"),
                }
            )
        # Drop empties
        return [x for x in results if x.get("formatted") and x.get("lat") and x.get("lon")]

    except Exception as e:
        logger.warning(f"Geoapify autocomplete failed: {e}")
        return []
