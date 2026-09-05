import pytest

from redat.sources import airquality_live as L


def _reading(sid, lat, lon, p1, p2, stype="SDS011", ts="2026-09-04 10:26:02"):
    return {
        "timestamp": ts,
        "location": {"latitude": str(lat), "longitude": str(lon)},
        "sensor": {"id": sid, "sensor_type": {"name": stype}},
        "sensordatavalues": [{"value_type": "P1", "value": str(p1)}, {"value_type": "P2", "value": str(p2)}],
    }


def test_citizen_pm_median_of_nearby_pm_sensors(monkeypatch):
    calls = []

    def fake(url, params=None):
        calls.append(url)
        return [
            _reading(1, 51.438, 7.005, 10.0, 4.0),
            _reading(2, 51.439, 7.006, 12.0, 6.0),
            _reading(3, 51.437, 7.004, 30.0, 8.0),
            _reading(4, 51.437, 7.004, 22.0, 30.0, stype="BME280"),   # temperature sensor: ignored
            _reading(1, 51.438, 7.005, 11.0, 5.0, ts="2026-09-04 10:20:00"),  # older duplicate of sensor 1: ignored
        ]

    monkeypatch.setattr(L, "_get_json", fake)
    r = L.get_citizen_pm(51.4378, 7.0053)
    assert calls == ["https://data.sensor.community/airrohr/v1/filter/area=51.4378,7.0053,2"]
    assert r == {"sensors": 3, "radius_km": 2, "pm10": 12.0, "pm25": 6.0,
                 "timestamp": "2026-09-04 10:26:02", "source": "Sensor.Community"}


def test_citizen_pm_widens_radius_when_too_few_sensors(monkeypatch):
    def fake(url, params=None):
        if url.endswith(",2"):
            return [_reading(1, 51.438, 7.005, 10.0, 4.0)]
        return [_reading(1, 51.438, 7.005, 10.0, 4.0), _reading(2, 51.45, 7.02, 14.0, 6.0),
                _reading(3, 51.42, 7.00, 12.0, 5.0)]

    monkeypatch.setattr(L, "_get_json", fake)
    r = L.get_citizen_pm(51.4378, 7.0053)
    assert r["sensors"] == 3 and r["radius_km"] == 5 and r["pm10"] == 12.0


def test_citizen_pm_none_when_nothing_nearby(monkeypatch):
    monkeypatch.setattr(L, "_get_json", lambda url, params=None: [])
    assert L.get_citizen_pm(51.4378, 7.0053) is None


def test_citizen_pm_drops_implausible_values(monkeypatch):
    monkeypatch.setattr(L, "_get_json", lambda url, params=None: [
        _reading(1, 51.438, 7.005, 10.0, 4.0), _reading(2, 51.439, 7.006, 1999.9, 6.0),
        _reading(3, 51.437, 7.004, 12.0, -1.0), _reading(4, 51.436, 7.004, 14.0, 5.0)])
    r = L.get_citizen_pm(51.4378, 7.0053)
    assert r["sensors"] == 4 and r["pm10"] == 12.0 and r["pm25"] == 5.0


def test_model_current_from_open_meteo(monkeypatch):
    seen = {}

    def fake(url, params=None):
        seen["url"], seen["params"] = url, params
        return {"current": {"time": "2026-09-04T10:00", "european_aqi": 14, "pm10": 5.7,
                            "pm2_5": 3.6, "nitrogen_dioxide": 6.2, "ozone": 38.0}}

    monkeypatch.setattr(L, "_get_json", fake)
    r = L.get_model_current(51.4378, 7.0053)
    assert seen["url"] == "https://air-quality-api.open-meteo.com/v1/air-quality"
    assert seen["params"]["domains"] == "cams_europe" and seen["params"]["latitude"] == 51.4378
    assert r == {"time": "2026-09-04T10:00", "european_aqi": 14, "aqi_label": "Gut", "aqi_color": "green",
                 "PM10": 5.7, "PM2.5": 3.6, "NO2": 6.2, "O3": 38.0,
                 "resolution_km": 11, "source": "CAMS Europe (Open-Meteo)"}


@pytest.mark.parametrize("aqi,label,color", [
    (0, "Gut", "green"), (20, "Gut", "green"), (21, "Ausreichend", "green"), (40, "Ausreichend", "green"),
    (41, "Mäßig", "yellow"), (60, "Mäßig", "yellow"), (61, "Schlecht", "orange"), (80, "Schlecht", "orange"),
    (81, "Sehr schlecht", "red"), (100, "Sehr schlecht", "red"), (101, "Extrem schlecht", "red"),
])
def test_european_aqi_labels(aqi, label, color):
    assert L.european_aqi_label(aqi) == (label, color)


def test_model_current_none_without_values(monkeypatch):
    monkeypatch.setattr(L, "_get_json", lambda url, params=None: {"current": {"time": "x", "pm10": None}})
    assert L.get_model_current(51.4378, 7.0053) is None
