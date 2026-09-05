"""Air quality for a point: official UBA/LANUV stations plus a composite report.

UBA Luftdaten API v3 — https://luftdaten.umweltbundesamt.de/api/air-data/v3/
(the old `umweltbundesamt.api.proxy.bund.dev` alias stopped resolving in 2026;
note the hyphen in `air-data`). Two kinds of station matter here:

* continuous stations (hourly PM10/PM2.5/NO2/O3; `meta/json?use=airquality`
  lists the ones currently delivering) — Essen has four, Bochum none;
* NO2 passive samplers (`annualbalances` only) — dozens across the Ruhrgebiet,
  often < 1 km apart, all kerbside "Verkehr" sites.

`get_air_quality_report()` combines: the EEA 1 km annual grid
(`airquality_grid`) + nearest NO2 samplers as the *long-term* picture, and the
nearest hourly station + Sensor.Community citizen PM + the CAMS model
(`airquality_live`) as the *current* one. Every source is isolated — a failure
lands in `errors[source]` and never blanks the others.

`_get_json` is the single UBA HTTP call and the monkeypatch point.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from functools import lru_cache
from math import atan2, cos, radians, sin, sqrt
from typing import Optional

import httpx

from redat.http import headers

logger = logging.getLogger(__name__)

UBA_API_BASE = "https://luftdaten.umweltbundesamt.de/api/air-data/v3"
_TIMEOUT_S = 10.0

COMPONENTS = {1: "PM10", 3: "O3", 5: "NO2", 9: "PM2.5"}
_NO2_COMPONENT = 5

# UBA Luftqualitätsindex class upper bounds (µg/m³): sehr gut / gut / mäßig / schlecht; above = sehr schlecht.
UBA_INDEX_BANDS = {
    "NO2": (20, 40, 100, 200),
    "PM10": (20, 35, 50, 100),
    "PM2.5": (10, 20, 25, 50),
    "O3": (60, 120, 180, 240),
}
INDEX_LABELS = {1: ("Sehr gut", "green"), 2: ("Gut", "green"), 3: ("Mäßig", "yellow"),
                4: ("Schlecht", "orange"), 5: ("Sehr schlecht", "red")}

_MAX_STATION_KM = 15
_MAX_SAMPLER_KM = 5
_SAMPLER_COUNT = 3


def _get_json(path: str, params: Optional[dict] = None) -> dict:
    resp = httpx.get(f"{UBA_API_BASE}/{path}", params=params, timeout=_TIMEOUT_S, headers=headers())
    resp.raise_for_status()
    return resp.json()


def _this_year() -> int:
    return date.today().year


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = radians(lat1), radians(lat2)
    a = sin(radians(lat2 - lat1) / 2) ** 2 + cos(phi1) * cos(phi2) * sin(radians(lon2 - lon1) / 2) ** 2
    return 6371 * 2 * atan2(sqrt(a), sqrt(1 - a))


# --- station catalogue ------------------------------------------------------

@lru_cache(maxsize=1)
def _stations() -> tuple:
    """All UBA stations as dicts, parsed by the `indices` names the API ships
    (column positions have changed between API versions)."""
    payload = _get_json("stations/json", {"lang": "de"})
    idx = {name: i for i, name in enumerate(payload.get("indices") or [])}
    out = []
    for row in (payload.get("data") or {}).values():
        try:
            out.append({
                "id": str(row[idx["station id"]]),
                "code": row[idx["station code"]],
                "name": row[idx["station name"]],
                "city": row[idx["station city"]],
                "lon": float(row[idx["station longitude"]]),
                "lat": float(row[idx["station latitude"]]),
                "type": row[idx["station type name"]],
                "active": not row[idx["station active to"]],
            })
        except (KeyError, IndexError, TypeError, ValueError):
            continue
    return tuple(out)


@lru_cache(maxsize=2)
def _hourly_station_ids(day: str) -> frozenset:
    """Stations that delivered index data in the last two days (cached per day)."""
    d = date.fromisoformat(day)
    payload = _get_json("meta/json", {
        "use": "airquality", "lang": "de",
        "date_from": (d - timedelta(days=1)).isoformat(), "date_to": d.isoformat(),
        "time_from": "1", "time_to": "24",
    })
    return frozenset(str(k) for k in (payload.get("stations") or {}))


@lru_cache(maxsize=4)
def _annual_no2(year: int) -> dict:
    payload = _get_json("annualbalances/json", {"component": _NO2_COMPONENT, "year": year})
    out = {}
    for row in payload.get("data") or []:
        try:
            if row[1] is not None:
                out[str(row[0])] = float(row[1])
        except (IndexError, TypeError, ValueError):
            continue
    return out


def _by_distance(lat: float, lon: float, max_km: float, keep) -> list:
    rows = []
    for st in _stations():
        if not keep(st):
            continue
        d = _haversine_km(lat, lon, st["lat"], st["lon"])
        if d <= max_km:
            rows.append({**st, "distance_km": round(d, 1)})
    rows.sort(key=lambda r: r["distance_km"])
    return rows


def nearest_hourly_station(lat: float, lon: float, max_km: float = _MAX_STATION_KM) -> Optional[dict]:
    hourly = _hourly_station_ids(date.today().isoformat())
    rows = _by_distance(lat, lon, max_km, lambda st: st["active"] and st["id"] in hourly)
    return rows[0] if rows else None


def uba_index(component: str, value: float) -> int:
    """1 (sehr gut) … 5 (sehr schlecht) per the UBA Luftqualitätsindex bands."""
    bands = UBA_INDEX_BANDS[component]
    for i, upper in enumerate(bands, start=1):
        if value <= upper:
            return i
    return 5


def station_current(station_id: str) -> Optional[dict]:
    """Latest hour with measurements at a continuous station."""
    today = date.today()
    payload = _get_json("airquality/json", {
        "station": station_id, "date_from": (today - timedelta(days=1)).isoformat(),
        "date_to": today.isoformat(), "time_from": "1", "time_to": "24",
    })
    rows = (payload.get("data") or {}).get(str(station_id)) or {}
    for start in sorted(rows, reverse=True):
        row = rows[start]
        if not isinstance(row, list) or len(row) < 4:
            continue
        measurements = {}
        for comp in row[3:]:
            try:
                name = COMPONENTS.get(int(comp[0]))
                value = float(comp[1])
            except (TypeError, ValueError, IndexError):
                continue
            if name:
                measurements[name] = {"value": round(value, 1), "unit": "µg/m³", "index": uba_index(name, value)}
        if measurements:
            index = max(m["index"] for m in measurements.values())
            label, color = INDEX_LABELS[index]
            return {"timestamp": row[0], "measurements": measurements,
                    "index": index, "index_label": label, "index_color": color}
    return None


def nearest_no2_samplers(lat: float, lon: float, max_km: float = _MAX_SAMPLER_KM, n: int = _SAMPLER_COUNT) -> list:
    """Nearest stations with an annual NO2 mean (mostly kerbside passive samplers),
    from the last complete year that has data."""
    for year in (_this_year() - 1, _this_year() - 2):
        annual = _annual_no2(year)
        if annual:
            break
    else:
        return []
    rows = _by_distance(lat, lon, max_km, lambda st: st["id"] in annual)
    return [{"name": r["name"], "type": r["type"], "distance_km": r["distance_km"],
             "value": annual[r["id"]], "unit": "µg/m³", "year": year} for r in rows[:n]]


# --- composite ---------------------------------------------------------------

def longterm_rating(values: dict) -> tuple[str, str]:
    """Worst ratio of annual mean to the EU limit value from 2030 (O3 has none and
    is regional anyway, so it is left out)."""
    worst = 0.0
    for m in values.values():
        if m.get("eu2030") and m.get("value") is not None:
            worst = max(worst, m["value"] / m["eu2030"])
    if not worst:
        return "unbekannt", "gray"
    if worst <= 0.75:
        return "Gut", "green"
    if worst <= 1.0:
        return "Mäßig", "yellow"
    if worst <= 1.5:
        return "Schlecht", "orange"
    return "Sehr schlecht", "red"


def _uba_current(lat: float, lon: float) -> Optional[dict]:
    st = nearest_hourly_station(lat, lon)
    if not st:
        return None
    cur = station_current(st["id"]) or {}
    return {"id": st["id"], "name": st["name"], "city": st["city"], "type": st["type"],
            "distance_km": st["distance_km"], "timestamp": cur.get("timestamp"),
            "measurements": cur.get("measurements") or {}, "index": cur.get("index"),
            "index_label": cur.get("index_label") or "unbekannt", "index_color": cur.get("index_color") or "gray"}


def _current_rating(current: dict) -> tuple[str, str]:
    st = current.get("station")
    if st and st.get("index"):
        return st["index_label"], st["index_color"]
    model = current.get("model")
    if model and model.get("european_aqi") is not None:
        return model["aqi_label"], model["aqi_color"]
    cit = current.get("citizen")
    if cit and (cit.get("pm10") is not None or cit.get("pm25") is not None):
        idx = max(uba_index(c, cit[k]) for c, k in (("PM10", "pm10"), ("PM2.5", "pm25")) if cit.get(k) is not None)
        return INDEX_LABELS[idx]
    return "unbekannt", "gray"


def is_empty(report: dict) -> bool:
    lt, cur = report.get("longterm") or {}, report.get("current") or {}
    return not (lt.get("grid") or lt.get("no2_samplers") or cur.get("station") or cur.get("citizen") or cur.get("model"))


def get_air_quality_report(lat: float, lon: float) -> dict:
    from redat.sources import airquality_grid
    from redat.sources import airquality_live

    jobs = {
        "grid": lambda: airquality_grid.lookup(lat, lon),
        "samplers": lambda: nearest_no2_samplers(lat, lon),
        "station": lambda: _uba_current(lat, lon),
        "citizen": lambda: airquality_live.get_citizen_pm(lat, lon),
        "model": lambda: airquality_live.get_model_current(lat, lon),
    }
    results, errors = {}, {}
    with ThreadPoolExecutor(max_workers=len(jobs), thread_name_prefix="airquality") as pool:
        futures = {k: pool.submit(fn) for k, fn in jobs.items()}
        for k, fut in futures.items():
            try:
                results[k] = fut.result()
            except Exception as e:  # one source down must not blank the card
                logger.warning("air quality source %s failed: %s", k, e)
                results[k] = None
                errors[k] = str(e)

    grid = results["grid"]
    lt_label, lt_color = longterm_rating(grid["values"]) if grid else ("unbekannt", "gray")
    current = {"station": results["station"], "citizen": results["citizen"], "model": results["model"]}
    cur_label, cur_color = _current_rating(current)
    return {
        "longterm": {"grid": grid, "no2_samplers": results["samplers"] or [],
                     "rating": lt_label, "rating_color": lt_color},
        "current": {**current, "rating": cur_label, "rating_color": cur_color},
        "errors": errors,
    }
