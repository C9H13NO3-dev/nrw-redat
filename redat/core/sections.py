"""Section registry for the analysis run.

Every card the service can produce is declared here once: key, title, tier (via
redat.core.tiers.SERVICE_TIER), timeout, attribution and a `fetch` that calls a
redat.sources module and returns the *normalized* data shape (ported verbatim
from house-hunter's docs/superpowers/specs/2026-09-04-analyze-rework-design.md
§4 — the only place a source's raw keys are translated). Insertion order of
SECTIONS == card order.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Optional

from redat.settings import Destination, get_settings

logger = logging.getLogger(__name__)


class Empty(Exception):
    """Raised by a fetch to signal "nothing here" with an explanatory message.

    run_section maps it to status="empty". Returning None from fetch is the
    message-less equivalent.
    """

    def __init__(self, message: str = ""):
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class Ctx:
    lat: float
    lon: float
    plot_size_m2: Optional[float] = None
    destinations: tuple[Destination, ...] = ()   # caller-supplied; () → settings defaults


def _destinations(ctx: Ctx) -> tuple[Destination, ...]:
    return ctx.destinations or get_settings().destinations


@dataclass(frozen=True)
class Section:
    key: str
    title: str
    icon: str
    timeout_s: float
    source: str  # attribution line shown under the card
    fetch: Callable[[Ctx], Optional[dict]]  # normalized data, or None = "nothing here"
    # Cache policy. cache_ttl_s None -> settings.cache_ttl_s (30 d default): right for geodata that
    # changes yearly at most. Set it only where the source is live/time-bound. Bump cache_version
    # when the card's `data` shape or meaning changes - it is part of the cache key, so stale
    # envelopes from the previous version are simply never found again.
    cache_ttl_s: Optional[float] = None
    cache_version: int = 1

    @property
    def tier(self) -> str:  # "parcel" | "area"
        from redat.core.tiers import SERVICE_TIER
        return SERVICE_TIER[self.key]


# --------------------------------------------------------------------------- area tier

_POI_LISTS = {"school": "schools", "kindergarten": "kindergartens", "supermarket": "supermarkets", "doctor": "doctors"}


def _first_poi(items) -> Optional[dict]:
    if not items:
        return None
    it = items[0]
    return {"name": it.get("name") or "—", "distance_m": it.get("distance_m")}


def _fetch_amenities(ctx: Ctx) -> dict:
    from redat.sources.geoapify import get_all_amenities

    a = get_all_amenities(ctx.lat, ctx.lon)
    if a.get("error"):
        raise RuntimeError(a["error"])
    return {
        "public_transport_score": a.get("public_transport_score"),
        "walkability_score": a.get("walkability_score"),
        "distances": {
            "public_transport": a.get("distance_to_public_transport_m"),
            "school": a.get("distance_to_school_m"),
            "kindergarten": a.get("distance_to_kindergarten_m"),
            "supermarket": a.get("distance_to_supermarket_m"),
            "doctor": a.get("distance_to_doctor_m"),
        },
        "nearest": {k: _first_poi(a.get(v)) for k, v in _POI_LISTS.items()},
    }


def _fetch_air_quality(ctx: Ctx) -> dict:
    from redat.sources import airquality

    report = airquality.get_air_quality_report(ctx.lat, ctx.lon)
    if airquality.is_empty(report):
        raise Empty("Keine Luftdaten für diesen Ort")
    return report


def _fetch_btw(ctx: Ctx) -> Optional[dict]:
    from redat.sources.btw import get_btw_wahlkreis_profile

    b = get_btw_wahlkreis_profile(ctx.lat, ctx.lon, top_n=6)
    if b.get("error"):
        if "nicht gefunden" in b["error"]:
            return None
        raise RuntimeError(b["error"])
    return {
        "election": b.get("election"),
        "wahlkreis": b.get("wahlkreis"),
        "parties": [{"party": p.get("party"), "percent": p.get("percent"), "color": p.get("color")} for p in b.get("top_parties") or []],
    }


def _fetch_commute(ctx: Ctx) -> dict:
    from redat.sources.geoapify import get_driving_time

    dests = _destinations(ctx)
    if not dests:
        raise Empty("Keine Zielorte konfiguriert (destinations)")
    rows = []
    for d in dests:
        try:
            r = get_driving_time(ctx.lat, ctx.lon, d.lat, d.lon) or {}
        except Exception as exc:  # noqa: BLE001 — one unreachable target must not blank the card
            logger.warning("commute: routing to %s failed: %s", d.name, exc)
            r = {}
        rows.append({"name": d.name, "address": d.address or None, "group": d.group,
                     "time_minutes": r.get("time_minutes"), "distance_km": r.get("distance_km")})
    return {"destinations": rows}


def _fetch_noise(ctx: Ctx) -> dict:
    from redat.sources.noise import get_noise_levels

    return get_noise_levels(ctx.lat, ctx.lon)


def _fetch_bergbau(ctx: Ctx) -> dict:
    from redat.sources.bergbau import get_bergbau

    b = get_bergbau(ctx.lat, ctx.lon)
    if b is None:
        raise Empty("Kein GDU-Planquadrat für diesen Ort (außerhalb NRW)")
    return b


def _fetch_schutzgebiete(ctx: Ctx) -> dict:
    from redat.sources.schutzgebiete import get_schutzgebiete

    return get_schutzgebiete(ctx.lat, ctx.lon)  # always rated — "Keine Schutzgebiete" is data, not Empty


def _fetch_energie(ctx: Ctx) -> dict:
    from redat.sources.energie import get_energie

    e = get_energie(ctx.lat, ctx.lon)
    if e is None:
        raise Empty("Keine Energiedaten für diesen Ort (kein Gebäude im Solarkataster, außerhalb NRW)")
    return e


def _fetch_breitband(ctx: Ctx) -> dict:
    from redat.sources.breitband import get_breitband

    b = get_breitband(ctx.lat, ctx.lon)
    if b is None:
        raise Empty("Keine Breitbandatlas-Daten für diese Rasterzelle (außerhalb Deutschlands oder unbewohnt)")
    return b


def _fetch_denkmal(ctx: Ctx) -> dict:
    from redat.sources.denkmal import get_denkmal

    d = get_denkmal(ctx.lat, ctx.lon)
    if d is None:
        raise Empty("Kein Denkmal-Datensatz für diesen Ort (außerhalb des RVR-Verbandsgebiets)")
    return d


def _fetch_oepnv(ctx: Ctx) -> dict:
    from redat.sources.oepnv import fixed_destinations, get_oepnv

    dests = [(n, ("stop", sid)) for n, sid in fixed_destinations()]
    dests += [(d.name, ("coord", d.lat, d.lon)) for d in ctx.destinations if d.group != "hbf"][:5]
    o = get_oepnv(ctx.lat, ctx.lon, destinations=dests)
    if o is None:
        raise Empty("Keine VRR-Haltestellen im Umkreis und keine Verbindung gefunden (außerhalb des VRR?)")
    return o


def _fetch_infrastruktur(ctx: Ctx) -> dict:
    from redat.sources.infrastruktur import get_infrastruktur

    return get_infrastruktur(ctx.lat, ctx.lon)  # always rated — "Unauffällig" is data, not Empty


def _fetch_zensus(ctx: Ctx) -> dict:
    from redat.sources.zensus import lookup

    z = lookup(ctx.lat, ctx.lon)
    if z is None:
        raise Empty("Keine Zensus-Gitterzelle mit Daten im Umkreis von 250 m (unbewohnt oder außerhalb Essen/Bochum)")
    return z


# --------------------------------------------------------------------------- parcel tier

def _fetch_boris(ctx: Ctx) -> Optional[dict]:
    from redat.sources.boris import get_boris_nrw

    b = get_boris_nrw(ctx.lat, ctx.lon)
    value = b.get("bodenrichtwert")
    if not value:
        err = b.get("error") or ""
        if not err or err.startswith("No BORIS data"):
            return None
        raise RuntimeError(err)
    return {
        "bodenrichtwert": value,
        "date": b.get("date"),
        "zone": b.get("zone"),
        "grundstueckswert": value * ctx.plot_size_m2 if ctx.plot_size_m2 else None,
        "raw": b.get("raw") or {},
    }


def _fetch_boris_trend(ctx: Ctx) -> Optional[dict]:
    from redat.sources.boris import get_historical_trend

    t = get_historical_trend(ctx.lat, ctx.lon)
    if not t:
        return None
    return {
        "current_year": t.current_year,
        "current_value": t.current_value,
        "oldest_year": t.oldest_year,
        "oldest_value": t.oldest_value,
        "avg_yearly_change": t.avg_yearly_change,
        "total_change": t.total_change,
        "history": list(t.history or []),
    }


def _fetch_flood(ctx: Ctx) -> dict:
    from redat.sources.flood import flood_risk

    fr = flood_risk(ctx.lat, ctx.lon)
    return {
        "flood_zone": fr.get("zone"),
        "flood_risk_level": fr.get("risk_level") or "low",
        "hits": {sc: {"hit": bool(h.get("hit")), "min_distance_m": h.get("min_distance_m")} for sc, h in (fr.get("hits") or {}).items()},
    }


def _fetch_starkregen(ctx: Ctx) -> dict:
    from redat.sources.starkregen import get_starkregen

    s = get_starkregen(ctx.lat, ctx.lon)
    if s is None:
        raise Empty("Keine Starkregen-Daten für diesen Ort (außerhalb NRW oder vollständig überbaut)")
    return s


def _fetch_gfnp(ctx: Ctx) -> dict:
    from redat.sources.gfnp import get_gfnp_designation

    g = get_gfnp_designation(ctx.lat, ctx.lon)
    if not g.get("ok"):
        raise RuntimeError(g.get("error") or "GFNP-Abfrage fehlgeschlagen")
    return {"found": bool(g.get("found")), "designation": g.get("designation"), "city": g.get("city"), "date": g.get("date")}


_ESSEN_LISTS = (
    ("bplan", "Bebauungsplan"),
    ("vhbplan", "Vorhabenbezogener B-Plan"),
    ("veraenderungssperre", "Veränderungssperre"),
    ("aufstellungsbeschluss", "Aufstellungsbeschluss"),
    ("auslegungsbeschluss", "Auslegungsbeschluss"),
    ("aufhebungsbeschluss", "Aufhebungsbeschluss"),
)


def _fetch_planning_essen(ctx: Ctx) -> dict:
    from redat.sources.planning_essen import get_planning_signals

    p = get_planning_signals(ctx.lat, ctx.lon)
    if not p.get("ok"):
        raise RuntimeError(p.get("error") or "Planungsabfrage Essen fehlgeschlagen")
    items = []
    for field, label in _ESSEN_LISTS:
        for it in p.get(field) or []:
            name = " ".join(str(x) for x in (it.get("nr"), it.get("name")) if x) or "—"
            extra = ", ".join(str(x) for x in (it.get("plan_type"), it.get("status")) if x)
            items.append({"category": label, "name": f"{name} ({extra})" if extra else name, "link": it.get("link")})
    return {"found": bool(items), "items": items}


def _fetch_planning_bochum(ctx: Ctx) -> dict:
    from redat.sources.planning_bochum import get_bochum_bplan_outline

    p = get_bochum_bplan_outline(ctx.lat, ctx.lon)
    if not p.get("ok"):
        raise RuntimeError(p.get("error") or "Planungsabfrage Bochum fehlgeschlagen")
    items = []
    for it in p.get("items") or []:
        name = it.get("official_name") or it.get("plan_id") or "—"
        if it.get("legal_status"):
            name = f"{name} ({it['legal_status']})"
        items.append({"category": it.get("plan_type") or "B-Plan", "name": name, "link": it.get("plan_link") or it.get("metadata_link")})
    return {"found": bool(items), "items": items}


# Insertion order == card order (spec §4: table order, noise after flood).
SECTIONS: dict[str, Section] = {s.key: s for s in [
    Section("boris", "Bodenrichtwert (BORIS)", "🏷️", 25, "BORIS NRW (Gutachterausschüsse)", _fetch_boris),
    Section("boris_trend", "Bodenrichtwert-Trend", "📈", 30, "BORIS NRW, historische Stichtage", _fetch_boris_trend),
    Section("flood", "Hochwasserrisiko", "🌊", 15, "Land NRW, Hochwassergefahrenkarten (HQhäufig / HQ100 / HQextrem)", _fetch_flood),
    Section("starkregen", "Starkregen", "🌧️", 25, "BKG Hinweiskarte Starkregengefahren (dl-de/by-2-0) — 1 m-Modell ohne Kanalnetz", _fetch_starkregen),
    Section("noise", "Lärm", "🔊", 20, "Land NRW, Umgebungslärmkartierung 2022 (WMS, Maximum im 25-m-Fenster)", _fetch_noise),
    Section("bergbau", "Bergbau & Untergrund", "⛏️", 20, "Geologischer Dienst NRW, „NRW von unten“ (Bürgerversion, 500 m-Planquadrat)", _fetch_bergbau),
    Section("gfnp", "Flächennutzungsplan (GFNP)", "🗺️", 30, "geo.essen.de — Gemeinsamer Flächennutzungsplan", _fetch_gfnp),
    Section("schutzgebiete", "Schutzgebiete", "🌳", 25,
            "LANUV LINFOS (NSG/LSG/FFH/VSG/Naturpark/Biotope) · Wasserschutzgebiete NRW", _fetch_schutzgebiete),
    Section("planning_essen", "Bauleitplanung Essen", "🏗️", 30, "geo.essen.de — Planen und Bauen", _fetch_planning_essen),
    Section("planning_bochum", "Bauleitplanung Bochum", "🏗️", 30, "RVR INSPIRE Bauleitplanung (WMS GetFeatureInfo)", _fetch_planning_bochum),
    Section("denkmal", "Denkmalschutz", "🏛️", 25,
            "RVR Geoportal Ruhr — Denkmäler (INSPIRE WFS) · Untere Denkmalbehörden Essen/Bochum", _fetch_denkmal),
    Section("amenities", "Entfernungen (POIs)", "📍", 25, "Geoapify Places", _fetch_amenities),
    Section("oepnv", "ÖPNV-Erreichbarkeit", "🚋", 45, "VRR EFA-Fahrplanauskunft (efa.vrr.de) — Fahrplan-Stichtag, kein Echtzeit", _fetch_oepnv,
            cache_ttl_s=7 * 86400),   # trips are normalised to "next Tuesday 08:00"; only timetable changes matter
    Section("zensus", "Nachbarschaft (Zensus 2022)", "🏘️", 5, "Destatis, Zensus 2022 — 100 m-Gitterdaten (dl-de/by-2-0)", _fetch_zensus),
    Section("energie", "Energie (Solar · Erdwärme · Wärmeplanung)", "☀️", 30,
            "LANUK Solarkataster NRW · GD NRW Geothermie · Kommunale Wärmeplanung Essen/Bochum", _fetch_energie),
    Section("breitband", "Breitband & Mobilfunk", "🌐", 30, "© BNetzA, Breitbandatlas — Datenstand 12.2025, 100 m-Raster", _fetch_breitband),
    Section("infrastruktur", "Hochspannung, Leitungen & Industrie", "⚡", 60,
            "OpenStreetMap (Overpass) · EEA Industrial Emissions Portal (IED/E-PRTR)", _fetch_infrastruktur),
    Section("air_quality", "Luftqualität", "🌬️", 25, "EEA 1 km-Raster 2023 · UBA/LANUV Messstationen · Sensor.Community · CAMS", _fetch_air_quality,
            cache_ttl_s=3600),        # "aktuell" comes from live station/sensor readings
    Section("btw", "Bundestagswahl", "🗳️", 30, "Die Bundeswahlleiterin (kerg2.csv, Zweitstimmen, Wahlkreis)", _fetch_btw),
    Section("commute", "Fahrzeiten (Auto)", "🚗", 30, "Geoapify Routing", _fetch_commute),
]}


def manifest() -> list[dict]:
    """Static per-section metadata a caller can use to build a page/config."""
    return [
        {"key": s.key, "title": s.title, "icon": s.icon, "tier": s.tier, "timeout_s": s.timeout_s, "source": s.source}
        for s in SECTIONS.values()
    ]
