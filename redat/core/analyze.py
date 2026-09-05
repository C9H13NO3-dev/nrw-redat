"""Orchestration shared by the API and the website: geocode, all sections, payload shapes."""
import dataclasses
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from fastapi import HTTPException

from redat.core.envelope import cache_ttl_for, run_section
from redat.core.geocoding import GeocodeResult, GeocoderUnavailable, geocode_with_precision
from redat.core.sections import SECTIONS, Ctx
from redat.settings import Destination, Settings
from redat.sources.geoapify import autocomplete_address
from redat.store.cache import SectionCache

logger = logging.getLogger(__name__)

POOL_SIZE = 6            # the concurrency the browser produced against hunter
MAX_DESTINATIONS = 10

# Geoapify is the metered resource, so its answers are cached too (KV namespaces in the same store).
GEOCODE_TTL_S = 30 * 86400       # an address does not move
GEOCODE_MISS_TTL_S = 3600        # "unknown address" is worth remembering briefly (typos get retried), not for a month
AUTOCOMPLETE_TTL_S = 7 * 86400
_MISS = object()
_WS = re.compile(r"\s+")


def build_cache(settings: Settings) -> SectionCache:
    """The one SectionCache of the process: persistent in redat.db, per-card TTLs resolved from the registry + yaml."""
    return SectionCache(settings.cache_ttl_s, db_path=settings.db_path,
                        ttl_overrides={key: cache_ttl_for(sec) for key, sec in SECTIONS.items()},
                        max_entries=settings.cache_max_entries, max_bytes=settings.cache_max_bytes)


def _norm(text: str) -> str:
    return _WS.sub(" ", (text or "").strip()).casefold()


def parse_destinations(raw: Optional[str]) -> tuple[Destination, ...]:
    """`destinations` query param: JSON list of {name, lat, lon, group?}. ValueError on anything off."""
    if not raw:
        return ()
    try:
        items = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"destinations: kein gültiges JSON ({exc.msg})")
    if not isinstance(items, list):
        raise ValueError("destinations: Liste erwartet")
    if len(items) > MAX_DESTINATIONS:
        raise ValueError(f"destinations: höchstens {MAX_DESTINATIONS} Einträge")
    out = []
    for i, it in enumerate(items):
        if not isinstance(it, dict) or not str(it.get("name") or "").strip():
            raise ValueError(f"destinations[{i}]: name fehlt")
        try:
            lat, lon = float(it["lat"]), float(it["lon"])
        except (KeyError, TypeError, ValueError):
            raise ValueError(f"destinations[{i}]: lat/lon fehlen oder sind keine Zahlen")
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError(f"destinations[{i}]: lat/lon außerhalb des gültigen Bereichs")
        out.append(Destination(str(it["name"]).strip(), lat, lon, str(it.get("group") or "custom"),
                               str(it.get("address") or "")))
    return tuple(out)


def geocode_or_raise(address: str, cache: Optional[SectionCache] = None) -> GeocodeResult:
    """Geocode via the cache (hits 30 d, misses 1 h; outages are never cached). 422 unknown, 502 outage."""
    k = _norm(address)
    hit = cache.kv_get("geocode", k, _MISS) if cache is not None and k else _MISS
    if hit is _MISS:
        try:
            result = geocode_with_precision(address)
        except GeocoderUnavailable as exc:
            logger.error("geocoding unavailable: %s", exc)
            raise HTTPException(status_code=502, detail="Geocoding nicht erreichbar (Geoapify und Nominatim)")
        if cache is not None and k:
            if result is None:
                cache.kv_put("geocode", k, None, ttl_s=GEOCODE_MISS_TTL_S)
            else:
                cache.kv_put("geocode", k, dataclasses.asdict(result), ttl_s=GEOCODE_TTL_S)
    else:
        result = None if hit is None else GeocodeResult(**hit)
    if result is None:
        raise HTTPException(status_code=422, detail="Adresse konnte nicht geocodiert werden")
    return result


def autocomplete_cached(text: str, limit: int, cache: Optional[SectionCache] = None) -> list[dict]:
    k = _norm(text)
    if not k:
        return []
    kk = f"{k}|{int(limit)}"
    hit = cache.kv_get("autocomplete", kk, _MISS) if cache is not None else _MISS
    if hit is not _MISS:
        return hit
    results = autocomplete_address(text, limit=limit)
    if cache is not None:
        cache.kv_put("autocomplete", kk, results, ttl_s=AUTOCOMPLETE_TTL_S)
    return results


def geocode_dict(address: str, g: GeocodeResult) -> dict:
    return {"address": address, "formatted_address": g.formatted_address,
            "latitude": g.latitude, "longitude": g.longitude, "precision": g.precision}


def cached_section(key: str, ctx: Ctx, *, precision: Optional[str], force: bool, cache: SectionCache,
                   fresh: bool = False) -> dict:
    """Run one section through the shared TTL cache — used by both /analyze and /section/{key}.

    destinations are request-scoped: commute/oepnv results with custom destinations must not be
    cached (they'd otherwise leak one caller's destinations to the next). Only ok/empty envelopes
    are stored at all (SectionCache.put already enforces that). `fresh` skips the read - the card
    is re-run and the new envelope replaces whatever was cached - it is the explicit refresh path
    (`?fresh=1`); `force` is the parcel-gate override and has nothing to do with the cache.
    """
    cacheable = not (bool(ctx.destinations) and key in ("commute", "oepnv"))
    k = cache.key(key, ctx.lat, ctx.lon, ctx.plot_size_m2, force, version=SECTIONS[key].cache_version)
    if cacheable and not fresh:
        hit = cache.get(k)
        if hit is not None:
            return hit
    env = run_section(key, ctx, precision=precision, force=force)
    if cacheable:
        cache.put(k, env)
    return env


def run_all(*, lat: float, lon: float, precision: Optional[str], plot_size_m2, force: bool,
            destinations: tuple[Destination, ...], cache: SectionCache, fresh: bool = False) -> dict[str, dict]:
    ctx = Ctx(lat=lat, lon=lon, plot_size_m2=plot_size_m2, destinations=tuple(destinations))

    def one(key: str) -> dict:
        return cached_section(key, ctx, precision=precision, force=force, cache=cache, fresh=fresh)

    keys = list(SECTIONS)
    with ThreadPoolExecutor(max_workers=POOL_SIZE) as pool:
        results = list(pool.map(one, keys))
    return dict(zip(keys, results))


def payload_to_run(payload: dict) -> dict:
    g = payload.get("geocode") or {}
    return {"address": payload.get("address"), "formatted_address": g.get("formatted_address"),
            "latitude": g.get("latitude"), "longitude": g.get("longitude"), "precision": g.get("precision"),
            "plot_size_m2": payload.get("plot_size_m2"), "living_space_m2": payload.get("living_space_m2"),
            "sections": payload.get("sections") or {}}


def run_to_payload(run: dict) -> dict:
    return {"address": run["address"],
            "geocode": {"formatted_address": run.get("formatted_address"), "latitude": run["latitude"],
                        "longitude": run["longitude"], "precision": run.get("precision")},
            "plot_size_m2": run.get("plot_size_m2"), "living_space_m2": run.get("living_space_m2"),
            "sections": run.get("sections") or {}}
