"""Live air-quality signals that are finer or gap-free compared with the official
station network:

* Sensor.Community (ex luftdaten.info) — citizen PM sensors (SDS011 & co.), dozens
  within a few km anywhere in the Ruhrgebiet. The `filter/area` endpoint returns the
  last ~5 minutes of readings, so no time filtering is needed; we take the median over
  the nearest sensors to damp single bad units. Low-cost sensors over-read in humid
  air — label it as "Bürgersensoren", never as an official value.
* Open-Meteo Air Quality — the Copernicus CAMS Europe model (~11 km cells, hourly).
  Coarse, but it always answers, including for Bochum where the UBA network has no
  continuous station.

Both are keyless. `_get_json` is the single HTTP call and the monkeypatch point.
"""
from __future__ import annotations

import statistics
from typing import Optional

import httpx

from redat.http import headers

SENSOR_COMMUNITY_URL = "https://data.sensor.community/airrohr/v1/filter/area={lat},{lon},{km}"
OPEN_METEO_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"

_PM_SENSOR_TYPES = {"SDS011", "SPS30", "PMS5003", "PMS7003", "PMS1003", "PMS3003", "HPM", "SDS021"}
_RADII_KM = (2, 5)
_MIN_SENSORS = 3
_PM_MAX = 1000.0  # µg/m³ — above this the unit is misreading
_TIMEOUT_S = 8.0


def _get_json(url: str, params: Optional[dict] = None):
    resp = httpx.get(url, params=params, timeout=_TIMEOUT_S, headers=headers())
    resp.raise_for_status()
    return resp.json()


def _plausible(v) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if 0 <= f <= _PM_MAX else None


def _latest_per_sensor(readings: list) -> dict:
    """Newest reading per PM sensor id."""
    latest: dict = {}
    for r in readings:
        try:
            if r["sensor"]["sensor_type"]["name"] not in _PM_SENSOR_TYPES:
                continue
            sid = r["sensor"]["id"]
        except (KeyError, TypeError):
            continue
        if sid not in latest or (r.get("timestamp") or "") > (latest[sid].get("timestamp") or ""):
            latest[sid] = r
    return latest


def get_citizen_pm(lat: float, lon: float) -> Optional[dict]:
    """Median PM10/PM2.5 over the nearest Sensor.Community PM sensors, widening the
    radius from 2 km to 5 km if fewer than 3 sensors are in range. None if none."""
    best: Optional[dict] = None
    for km in _RADII_KM:
        readings = _get_json(SENSOR_COMMUNITY_URL.format(lat=lat, lon=lon, km=km))
        sensors = _latest_per_sensor(readings or [])
        if not sensors:
            continue
        pm10, pm25 = [], []
        for r in sensors.values():
            for v in r.get("sensordatavalues") or []:
                val = _plausible(v.get("value"))
                if val is None:
                    continue
                if v.get("value_type") == "P1":
                    pm10.append(val)
                elif v.get("value_type") == "P2":
                    pm25.append(val)
        if not pm10 and not pm25:
            continue
        best = {
            "sensors": len(sensors),
            "radius_km": km,
            "pm10": round(statistics.median(pm10), 1) if pm10 else None,
            "pm25": round(statistics.median(pm25), 1) if pm25 else None,
            "timestamp": max((r.get("timestamp") or "") for r in sensors.values()) or None,
            "source": "Sensor.Community",
        }
        if len(sensors) >= _MIN_SENSORS:
            break
    return best


def european_aqi_label(aqi: float) -> tuple[str, str]:
    """European Air Quality Index bands (EEA): 0-20 good … 81-100 very poor, >100 extremely poor."""
    if aqi <= 20:
        return "Gut", "green"
    if aqi <= 40:
        return "Ausreichend", "green"
    if aqi <= 60:
        return "Mäßig", "yellow"
    if aqi <= 80:
        return "Schlecht", "orange"
    if aqi <= 100:
        return "Sehr schlecht", "red"
    return "Extrem schlecht", "red"


def get_model_current(lat: float, lon: float) -> Optional[dict]:
    """Current hour from the CAMS Europe model via Open-Meteo. None if no values."""
    data = _get_json(OPEN_METEO_URL, params={
        "latitude": lat, "longitude": lon, "domains": "cams_europe",
        "current": "european_aqi,pm10,pm2_5,nitrogen_dioxide,ozone",
    })
    cur = (data or {}).get("current") or {}
    values = {name: cur.get(key) for name, key in
              (("PM10", "pm10"), ("PM2.5", "pm2_5"), ("NO2", "nitrogen_dioxide"), ("O3", "ozone"))}
    if all(v is None for v in values.values()):
        return None
    aqi = cur.get("european_aqi")
    label, color = european_aqi_label(aqi) if aqi is not None else ("unbekannt", "gray")
    return {"time": cur.get("time"), "european_aqi": aqi, "aqi_label": label, "aqi_color": color,
            **values, "resolution_km": 11, "source": "CAMS Europe (Open-Meteo)"}
