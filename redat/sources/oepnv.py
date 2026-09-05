"""ÖPNV-Erreichbarkeit card — stops, rush-hour lines and travel times via the VRR EFA.

Source: VRR EFA-Fahrplanauskunft, https://efa.vrr.de/standard/ with
`outputFormat=rapidJSON` (JSON, WGS84 coordinates, planned times in UTC "Z"):
- XML_COORD_REQUEST — stops within STOP_RADIUS_M of a coordinate, with
  `productClasses` and `properties.distance` (metres).
- XML_DM_REQUEST — departure monitor of one stop (`type_dm=stop&name_dm=<globalId>`,
  `mode=direct`, `itdDate/itdTime`), used to count planned departures per line in
  the 07:00–09:00 window.
- XML_TRIP_REQUEST2 — trips from the coordinate to a stop id or coordinate
  (`itdTripDateTimeDepArr=dep`, `calcNumberOfTrips=3`, `useRealtime=0`).

Every timetable query uses one fixed reference time — the next Tuesday strictly
after today, 08:00 Europe/Berlin — so the card is a stable weekday snapshot rather
than "now" (with realtime delays and night gaps). Destinations default to the
`oepnv_stops` fixed stops from settings; a caller may pass its own list (e.g. the
user's configured "wichtige Orte") via `get_oepnv(..., destinations=...)`.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

import httpx

from redat.http import headers
from redat.settings import get_settings

logger = logging.getLogger(__name__)

EFA_URL = "https://efa.vrr.de/standard/"
EFA_COMMON = {"outputFormat": "rapidJSON", "coordOutputFormat": "WGS84[dd.ddddd]", "version": "10.4.18.18"}
STOP_RADIUS_M = 600
PRODUCT_LABELS = {0: "Zug", 1: "S-Bahn", 2: "U-Bahn", 3: "Stadtbahn", 4: "Straßenbahn", 5: "Bus", 6: "Regionalbus",
                  7: "Schnellbus", 8: "Seilbahn", 9: "AST", 10: "Fähre", 11: "TaxiBus", 13: "Regionalzug", 14: "ICE",
                  15: "IC/EC", 16: "Sonstiger Zug"}  # VRR class 11 = TaxiBus (live-verified: line T8.2 Werden)
RAIL_CLASSES = {0, 1, 2, 3, 4, 13, 14, 15, 16}
_MAX_STOPS, _DM_STOPS = 8, 3
_WINDOW_H = 2          # departure monitor window 07:00 + 2 h
_TIMEOUT_S = 25
_TZ = ZoneInfo("Europe/Berlin")
_WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]


def fixed_destinations() -> list[tuple[str, str]]:
    """(name, EFA stop id) of the fixed trip targets — settings.yaml `oepnv_stops`."""
    return list(get_settings().oepnv_stops)


def reference_time(now: Optional[datetime] = None) -> datetime:
    """Next Tuesday strictly after today's date, 08:00 Europe/Berlin."""
    now = (now or datetime.now(_TZ)).astimezone(_TZ)
    days_ahead = (1 - now.weekday()) % 7 or 7  # Tuesday == 1; today never counts
    day = now.date() + timedelta(days=days_ahead)
    return datetime(day.year, day.month, day.day, 8, 0, tzinfo=_TZ)


def _efa(endpoint: str, params: dict) -> dict:
    """GET one EFA endpoint — HTTP/monkeypatch point."""
    resp = httpx.get(EFA_URL + endpoint, params={**EFA_COMMON, **params}, timeout=_TIMEOUT_S,
                     headers=headers())
    resp.raise_for_status()
    return resp.json()


def _coord(lat: float, lon: float) -> str:
    return f"{lon}:{lat}:WGS84[dd.ddddd]"


def _local_hhmm(iso_utc: Optional[str]) -> Optional[str]:
    if not iso_utc:
        return None
    return datetime.fromisoformat(iso_utc.replace("Z", "+00:00")).astimezone(_TZ).strftime("%H:%M")


def _fetch_stops(lat: float, lon: float) -> list[dict]:
    data = _efa("XML_COORD_REQUEST", {"coord": _coord(lat, lon), "inclFilter": 1, "radius_1": STOP_RADIUS_M,
                                      "type_1": "STOP"})
    stops = []
    for loc in data.get("locations", []) or []:
        classes = sorted(int(c) for c in loc.get("productClasses", []) or [])
        coord = loc.get("coord") or [None, None]
        stops.append({
            "id": loc.get("id"), "name": loc.get("name"),
            "distance_m": int((loc.get("properties") or {}).get("distance") or 0),
            "products": [PRODUCT_LABELS.get(c, "Sonstige") for c in classes],
            "classes": classes, "rail": bool(RAIL_CLASSES & set(classes)),
            "lat": coord[0], "lon": coord[1],
        })
    stops.sort(key=lambda s: s["distance_m"])
    return stops[:_MAX_STOPS]


def _fetch_lines(stops: list[dict], ref: datetime) -> list[dict]:
    start = ref.replace(hour=7, minute=0)
    end = start + timedelta(hours=_WINDOW_H)
    best: dict[str, dict] = {}
    for s in stops[:_DM_STOPS]:
        data = _efa("XML_DM_REQUEST", {"type_dm": "stop", "name_dm": s["id"], "mode": "direct",
                                       "itdDate": ref.strftime("%Y%m%d"), "itdTime": "0700", "limit": 120,
                                       "useRealtime": 0})
        per_line: dict[str, dict] = {}
        for ev in data.get("stopEvents", []) or []:
            planned = ev.get("departureTimePlanned")
            if not planned:
                continue
            t = datetime.fromisoformat(planned.replace("Z", "+00:00")).astimezone(_TZ)
            if not (start <= t < end):
                continue
            tr = ev.get("transportation") or {}
            number = tr.get("number") or tr.get("disassembledName") or "?"
            entry = per_line.setdefault(number, {
                "line": number, "product": (tr.get("product") or {}).get("name") or "",
                "stop": s["name"], "destinations": [], "departures_2h": 0})
            entry["departures_2h"] += 1
            dest = (tr.get("destination") or {}).get("name")
            if dest and dest not in entry["destinations"]:
                entry["destinations"].append(dest)
        for number, entry in per_line.items():
            if number not in best or entry["departures_2h"] > best[number]["departures_2h"]:
                best[number] = entry
    lines = sorted(best.values(), key=lambda l: (-l["departures_2h"], l["line"]))
    for l in lines:
        l["headway_min"] = round(_WINDOW_H * 60 / l["departures_2h"], 1)
    return lines


def _fetch_trip(lat: float, lon: float, name: str, kind: str, target: tuple, ref: datetime) -> dict:
    params = {"type_origin": "coord", "name_origin": _coord(lat, lon),
              "itdDate": ref.strftime("%Y%m%d"), "itdTime": ref.strftime("%H%M"), "itdTripDateTimeDepArr": "dep",
              "calcNumberOfTrips": 3, "useRealtime": 0}
    if target[0] == "stop":
        params.update(type_destination="stop", name_destination=target[1])
    else:
        params.update(type_destination="coord", name_destination=_coord(target[1], target[2]))
    data = _efa("XML_TRIP_REQUEST2", params)
    out = {"name": name, "kind": kind, "duration_min": None, "interchanges": None, "walk_min": None,
           "legs": [], "departure": None, "arrival": None}
    best = None
    for j in data.get("journeys", []) or []:
        legs = j.get("legs") or []
        if not legs:
            continue
        dep = legs[0].get("origin", {}).get("departureTimePlanned")
        arr = legs[-1].get("destination", {}).get("arrivalTimePlanned")
        if not dep or not arr:
            continue
        span = (datetime.fromisoformat(arr.replace("Z", "+00:00")) - datetime.fromisoformat(dep.replace("Z", "+00:00")))
        if best is None or span < best[0]:
            best = (span, j, dep, arr)
    if best is None:
        return out
    span, j, dep, arr = best
    walk_s = 0
    numbers = []
    for leg in j["legs"]:
        tr = leg.get("transportation") or {}
        if (tr.get("product") or {}).get("name") == "footpath" or not tr.get("number"):
            walk_s += int(leg.get("duration") or 0)
        else:
            numbers.append(tr["number"])
    out.update(duration_min=int(round(span.total_seconds() / 60)), interchanges=j.get("interchanges"),
               walk_min=int(round(walk_s / 60)), legs=numbers, departure=_local_hhmm(dep), arrival=_local_hhmm(arr))
    return out


def _rate(stops: list[dict], trips: list[dict]) -> tuple[str, str, Optional[int]]:
    rail = [s["distance_m"] for s in stops if s["rail"]]
    nearest_rail = min(rail) if rail else None
    nearest = min((s["distance_m"] for s in stops), default=None)
    hbf = [t["duration_min"] for t in trips
           if t["kind"] == "fixed" and t["name"] in ("Essen Hbf", "Bochum Hbf") and t["duration_min"] is not None]
    hbf_min = min(hbf) if hbf else None
    if nearest is None:
        return "Keine Haltestelle im Umkreis von 600 m", "orange", None
    if nearest_rail is not None and nearest_rail <= 400 and hbf_min is not None and hbf_min <= 20:
        return "Sehr gut", "green", nearest_rail
    if (nearest_rail is not None and nearest_rail <= 800) or (hbf_min is not None and hbf_min <= 30):
        return "Gut", "green", nearest_rail
    if nearest <= 600:
        return "Mäßig", "yellow", nearest_rail
    return "Gering", "orange", nearest_rail


def get_oepnv(lat: float, lon: float, *, destinations: Optional[list[tuple[str, tuple]]] = None) -> Optional[dict]:
    """Stops/lines/trips around the point, or None when neither stops nor any trip exist (outside the VRR)."""
    ref = reference_time()
    errors: dict[str, str] = {}
    fixed = fixed_destinations()
    dests = destinations if destinations is not None else [(n, ("stop", sid)) for n, sid in fixed]
    fixed_ids = {sid for _, sid in fixed}

    with ThreadPoolExecutor(max_workers=4) as pool:
        stops_f = pool.submit(_fetch_stops, lat, lon)
        trip_fs = [pool.submit(_fetch_trip, lat, lon, name, "fixed" if t[0] == "stop" and t[1] in fixed_ids else "custom",
                               t, ref) for name, t in dests]
        try:
            stops = stops_f.result()
        except Exception as exc:  # noqa: BLE001
            logger.warning("oepnv stops failed: %s", exc)
            errors["stops"] = str(exc)
            stops = []
        lines: list[dict] = []
        if stops:
            try:
                lines = pool.submit(_fetch_lines, stops, ref).result()
            except Exception as exc:  # noqa: BLE001
                logger.warning("oepnv lines failed: %s", exc)
                errors["lines"] = str(exc)
        trips: list[dict] = []
        trip_failed = 0
        for (name, _), f in zip(dests, trip_fs):
            try:
                trips.append(f.result())
            except Exception as exc:  # noqa: BLE001
                logger.warning("oepnv trip to %s failed: %s", name, exc)
                trip_failed += 1
        if trip_failed:
            errors["trips"] = f"{trip_failed} von {len(dests)} Verbindungsanfragen fehlgeschlagen"

    if "stops" in errors and dests and trip_failed == len(dests):
        raise RuntimeError(f"EFA nicht erreichbar: {errors['stops']}")
    trips.sort(key=lambda t: (t["kind"] != "fixed"))
    if not stops and not any(t["duration_min"] is not None for t in trips):
        return None
    rating, color, nearest_rail = _rate(stops, trips)
    return {
        "reference": {"date": ref.strftime("%Y-%m-%d"), "weekday": _WEEKDAYS[ref.weekday()], "window": "07:00–09:00"},
        "stops": stops, "lines": lines, "trips": trips,
        "nearest_rail_m": nearest_rail, "rating": rating, "rating_color": color, "errors": errors,
    }
