"""Turn the browser's report payload (envelopes + geocode) into the template context.

The browser POSTs the section envelopes it already holds; nothing is re-fetched
here. This module validates the payload against the section registry, splits
sections into body (ok + data) and appendix (everything else), and derives one
summary row per body section. Summary functions are deliberately defensive —
a shape they don't understand yields "—", never a 500.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from datetime import datetime
from typing import Any, Callable, Optional

from redat.core.sections import SECTIONS

logger = logging.getLogger(__name__)

MAP_ATTRIBUTION = "Kartengrundlage: © basemap.de / BKG (dl-de/by-2-0) · Lärmkartierung: Land NRW (LANUV), Umgebungslärm 2022"

PRECISION_LABELS = {"building": "hausnummerngenau", "street": "straßengenau", "coordinates": "Koordinaten"}
_DEFAULT_PRECISION_LABEL = "ortsgenau"

STATUS_LABELS = {
    "gated": "gesperrt (Parzellendaten benötigen Hausnummer)",
    "empty": "kein Befund",
    "error": "Fehler",
    "loading": "nicht geladen",
}
_DEFAULT_STATUS_LABEL = "nicht geladen"

FLOOD_LEVELS = {"low": ("Gering", "green"), "medium": ("Mittel", "yellow"), "high": ("Hoch", "red")}


class ReportPayloadError(ValueError):
    """The POSTed payload is malformed (→ 422 in the route)."""


# --------------------------------------------------------------------------- formatting helpers

def fmt_int(v: Any) -> str:
    """1572 → '1.572' (German thousands separator)."""
    return f"{int(round(float(v))):,}".replace(",", ".")


def fmt_num(v: Any, digits: int = 1) -> str:
    """47.6 → '47,6'; drops a trailing ',0' when digits == 1 and the value is whole."""
    s = f"{float(v):,.{digits}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return s


def fmt_date(iso: Any) -> str:
    """'2025-01-01' → '01.01.2025'; anything unparsable is returned as-is."""
    try:
        return datetime.strptime(str(iso)[:10], "%Y-%m-%d").strftime("%d.%m.%Y")
    except ValueError:
        return str(iso)


def fmt_m(v: Any) -> str:
    v = float(v)
    return f"{fmt_num(v / 1000, 1)} km" if v >= 1000 else f"{int(round(v))} m"


def slugify(text: str) -> str:
    """ASCII filename slug: umlauts transliterated, max 60 chars, 'Standort' when empty."""
    text = (text or "").replace("ä", "ae").replace("ö", "oe").replace("ü", "ue") \
        .replace("Ä", "Ae").replace("Ö", "Oe").replace("Ü", "Ue").replace("ß", "ss")
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-")
    return text[:60].rstrip("-") or "Standort"


# --------------------------------------------------------------------------- per-section summaries
# Each returns (rating, rating_color, figure). They are wrapped by summarize(), so raising is
# tolerated — but they still use .get() so a partial envelope yields a partial figure.

def _rated(d: dict) -> tuple[Optional[str], str]:
    return d.get("rating") or None, d.get("rating_color") or "gray"


def _s_boris(d):
    brw = d.get("bodenrichtwert")
    if brw is None:
        return None, "gray", None
    fig = f"{fmt_int(brw)} €/m²"
    if d.get("date"):
        fig += f" (Stichtag {fmt_date(d['date'])})"
    return None, "gray", fig


def _s_boris_trend(d):
    if d.get("current_value") is None:
        return None, "gray", None
    pct = float(d.get("total_change") or 0)
    return None, "gray", (f"{d.get('oldest_year')}: {fmt_int(d.get('oldest_value'))} → "
                          f"{d.get('current_year')}: {fmt_int(d['current_value'])} €/m² ({pct:+.0f} %)")


def _s_flood(d):
    rating, color = FLOOD_LEVELS.get(d.get("flood_risk_level"), (None, "gray"))
    zone = d.get("flood_zone")
    return rating, color, f"Zone {zone}" if zone else "außerhalb aller Szenarien"


def _s_starkregen(d):
    rating, color = _rated(d)
    sc = d.get("scenarios") or {}
    agw = ((sc.get("agw") or {}).get("max") or {}).get("label")
    ext = ((sc.get("extrem") or {}).get("max") or {}).get("label")
    fig = " · ".join(p for p in (f"selten {agw}" if agw else None, f"extrem {ext}" if ext else None) if p)
    return rating, color, fig or None


def _s_noise(d):
    if d.get("below_threshold"):
        return "unter Schwelle", "green", "< 55 dB Tag / < 50 dB Nacht"
    day = (d.get("day") or {}).get("db_min")
    night = (d.get("night") or {}).get("db_min")
    fig = " · ".join(p for p in (f"Tag ab {day} dB(A)" if day is not None else None,
                                 f"Nacht ab {night} dB(A)" if night is not None else None) if p)
    return None, "gray", fig or None


def _s_bergbau(d):
    rating, color = _rated(d)
    n = len([i for i in (d.get("items") or []) if i.get("present")])
    return rating, color, f"{n} Hinweise im 500 m-Planquadrat"


def _s_gfnp(d):
    if not d.get("found"):
        return None, "gray", "keine Zuordnung"
    return None, "gray", d.get("designation") or "—"


def _s_schutzgebiete(d):
    rating, color = _rated(d)
    areas = d.get("areas") or []
    n = sum((d.get("counts") or {}).values()) or len(areas)
    fig = f"{n} Gebiete ≤ {d.get('radius_m') or 500} m"
    inside = [a.get("name") for a in areas if a.get("inside") and a.get("name")]
    if inside:
        fig += " · innerhalb: " + ", ".join(inside[:2])
    wsg = d.get("wsg") or []
    if wsg:
        fig += f" · Wasserschutzgebiet Zone {wsg[0].get('zone') or '?'}"
    return rating, color, fig


def _s_planning(d):
    n = len(d.get("items") or [])
    return None, "gray", f"{n} Verfahren" if n else "keine Verfahren"


def _s_denkmal(d):
    rating, color = _rated(d)
    c = d.get("counts") or {}
    fig = f"{c.get('A', 0)} Bau-, {c.get('B', 0)} Bodendenkmäler ≤ {d.get('radius_m') or 300} m"
    if d.get("on_site"):
        fig = f"{len(d['on_site'])} auf dem Grundstück · " + fig
    return rating, color, fig


def _s_amenities(d):
    dist = d.get("distances") or {}
    parts = [f"{label} {fmt_m(dist[k])}" for k, label in (("supermarket", "Supermarkt"), ("school", "Schule"), ("doctor", "Arzt"))
             if dist.get(k) is not None]
    return None, "gray", " · ".join(parts) or None


def _s_oepnv(d):
    rating, color = _rated(d)
    rail = d.get("nearest_rail_m")
    parts = [f"Schiene {fmt_m(rail)}" if rail is not None else "keine Schiene ≤ 600 m"]
    for t in d.get("trips") or []:
        if t.get("kind") == "fixed" and t.get("duration_min") is not None:
            parts.append(f"{t.get('name')} {t['duration_min']} min")
            break
    return rating, color, " · ".join(parts)


def _s_zensus(d):
    area = d.get("area") or {}
    if area.get("einwohner") is None:
        return None, "gray", None
    fig = f"{fmt_int(area['einwohner'])} EW (±{d.get('radius_m') or 250} m)"
    if area.get("alter") is not None:
        fig += f" · Ø Alter {fmt_num(area['alter'], 1)}"
    return None, "gray", fig


def _s_energie(d):
    pv, ew, wp = d.get("pv") or {}, d.get("erdwaerme") or {}, d.get("waermeplanung") or {}
    parts = []
    if pv.get("total_kwh_a") is not None:
        parts.append(f"PV {fmt_int(pv['total_kwh_a'])} kWh/a")
    if ew.get("rating"):
        parts.append(f"Erdwärme {ew['rating']}")
    if wp.get("label"):
        parts.append(wp["label"])
    return None, "gray", " · ".join(parts) or None


def _s_breitband(d):
    rating, color = _rated(d)
    fixed = d.get("fixed") or {}
    parts = []
    ftth = fixed.get("ftth_1000") or {}
    if ftth.get("label"):
        parts.append(f"FTTH {ftth['label']}")
    g5 = [name for key, name in (("telekom", "Telekom"), ("vodafone", "Vodafone"), ("o2", "o2"), ("1u1", "1&1"))
          if (d.get("mobile_5g") or {}).get(key) == "5G"]
    parts.append("5G: " + (", ".join(g5) if g5 else "keiner"))
    return rating, color, " · ".join(parts)


def _s_infrastruktur(d):
    rating, color = _rated(d)
    n_lines = len(d.get("power_lines") or [])
    masts = len(d.get("masts") or [])
    ied = len([s for s in (d.get("ied_sites") or []) if not s.get("stale")])
    fig = f"{n_lines} Leitungen · {masts} Sendemast{'en' if masts != 1 else ''} · {ied} Industrieanlage{'n' if ied != 1 else ''}"
    wind = len(d.get("wind") or [])
    if wind:
        fig += f" · {wind} WKA"
    return rating, color, fig


def _s_air_quality(d):
    lt, cur = d.get("longterm") or {}, d.get("current") or {}
    vals = ((lt.get("grid") or {}).get("values") or {})
    parts = []
    no2, pm = vals.get("NO2") or {}, vals.get("PM2.5") or {}
    if no2.get("value") is not None and pm.get("value") is not None:
        parts.append(f"NO₂ {fmt_num(no2['value'])} · PM2.5 {fmt_num(pm['value'])} µg/m³ ({(lt.get('grid') or {}).get('year')})")
    if cur.get("rating"):
        parts.append(f"aktuell {cur['rating']}")
    return lt.get("rating") or None, lt.get("rating_color") or "gray", " · ".join(parts) or None


def _s_btw(d):
    parties = [p for p in (d.get("parties") or []) if p.get("percent") is not None][:2]
    return None, "gray", " · ".join(f"{p.get('party')} {fmt_num(p['percent'])} %" for p in parties) or None


def _s_commute(d):
    dests = [c for c in (d.get("destinations") or []) if c.get("time_minutes") is not None][:2]
    return None, "gray", " · ".join(f"{c.get('name')} {c['time_minutes']} min" for c in dests) or None


SUMMARY: dict[str, Callable[[dict], tuple[Optional[str], str, Optional[str]]]] = {
    "boris": _s_boris, "boris_trend": _s_boris_trend, "flood": _s_flood, "starkregen": _s_starkregen,
    "noise": _s_noise, "bergbau": _s_bergbau, "gfnp": _s_gfnp, "schutzgebiete": _s_schutzgebiete,
    "planning_essen": _s_planning, "planning_bochum": _s_planning, "denkmal": _s_denkmal,
    "amenities": _s_amenities, "oepnv": _s_oepnv, "zensus": _s_zensus, "energie": _s_energie,
    "breitband": _s_breitband, "infrastruktur": _s_infrastruktur, "air_quality": _s_air_quality,
    "btw": _s_btw, "commute": _s_commute,
}


def summarize(key: str, data: Any) -> tuple[Optional[str], str, Optional[str]]:
    """(rating, rating_color, figure) for a section — never raises."""
    fn = SUMMARY.get(key)
    if fn is None or not isinstance(data, dict):
        return None, "gray", None
    try:
        rating, color, figure = fn(data)
        return rating, color or "gray", figure
    except Exception as e:  # noqa: BLE001 — a summary must never break the report
        logger.debug("summary for %s failed: %s", key, e)
        return None, "gray", "—"


# --------------------------------------------------------------------------- context

def _validate(payload: dict) -> tuple[dict, dict]:
    if not isinstance(payload, dict):
        raise ReportPayloadError("Payload muss ein Objekt sein")
    geo = payload.get("geocode")
    if not isinstance(geo, dict):
        raise ReportPayloadError("geocode fehlt")
    try:
        lat, lon = float(geo.get("latitude")), float(geo.get("longitude"))
    except (TypeError, ValueError):
        raise ReportPayloadError("geocode.latitude/longitude fehlen oder sind keine Zahlen")
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ReportPayloadError("geocode außerhalb des gültigen Bereichs")
    sections = payload.get("sections") or {}
    if not isinstance(sections, dict):
        raise ReportPayloadError("sections muss ein Objekt sein")
    for key, env in sections.items():
        if key not in SECTIONS:
            raise ReportPayloadError(f"Unbekannte Sektion: {key}")
        if not isinstance(env, dict) or not env.get("status"):
            raise ReportPayloadError(f"Sektion {key}: Envelope ohne status")
    return {**geo, "latitude": lat, "longitude": lon}, sections


def build_report_context(payload: dict, *, now: Optional[datetime] = None) -> dict:
    """Validate the payload and derive everything the report template needs (maps/SVG are added by the route)."""
    geo, sections = _validate(payload)
    body, appendix, summary = [], [], []
    for key, section in SECTIONS.items():
        env = sections.get(key)
        status = (env or {}).get("status") or "loading"
        data = (env or {}).get("data")
        if status == "ok" and isinstance(data, dict):
            body.append({"key": key, "icon": section.icon, "title": section.title, "source": section.source, "data": data})
            rating, color, figure = summarize(key, data)
            summary.append({"key": key, "icon": section.icon, "title": section.title,
                            "rating": rating, "rating_color": color, "figure": figure})
        else:
            label = "kein Befund" if status == "ok" else STATUS_LABELS.get(status, _DEFAULT_STATUS_LABEL)
            appendix.append({"key": key, "icon": section.icon, "title": section.title,
                             "status": status, "status_label": label, "message": (env or {}).get("message")})

    when = now or datetime.now()
    formatted = geo.get("formatted_address") or payload.get("address") or f"{geo['latitude']:.5f}, {geo['longitude']:.5f}"
    return {
        "address": payload.get("address") or formatted,
        "formatted_address": formatted,
        "lat": geo["latitude"],
        "lon": geo["longitude"],
        "precision": geo.get("precision"),
        "precision_label": PRECISION_LABELS.get(geo.get("precision"), _DEFAULT_PRECISION_LABEL),
        "plot_size_m2": payload.get("plot_size_m2"),
        "living_space_m2": payload.get("living_space_m2"),
        "generated_at": when.strftime("%d.%m.%Y %H:%M"),
        "generated_date": when.strftime("%Y-%m-%d"),
        "summary": summary,
        "body": body,
        "appendix": appendix,
        "sources": list(dict.fromkeys(s["source"] for s in body)),
        "map_attribution": MAP_ATTRIBUTION,
        "noise_maps": None,
        "boris_trend_svg": None,
    }
