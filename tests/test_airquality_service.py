import pytest

from redat.sources import airquality as A

STATION_INDICES = ["station id", "station code", "station name", "station city", "station synonym",
                   "station active from", "station active to", "station longitude", "station latitude",
                   "network id", "station setting id", "station type id", "network code", "network name",
                   "station setting name", "station setting short name", "station type name",
                   "station street", "station street nr", "station zip code"]


def _st(sid, code, name, city, lon, lat, typ, active_to=None):
    return [sid, code, name, city, "", "2000-01-01", active_to, str(lon), str(lat), "10", "1", "3",
            "NW", "Nordrhein-Westfalen", "städtisches Gebiet", "städtisch", typ, "", "", "45138"]


STATIONS = {
    "1098": _st("1098", "DENW043", "Essen-Ost Steeler Straße", "Essen", 7.0305, 51.4512, "Verkehr"),
    "1290": _st("1290", "DENW247", "Essen-Schuir (LANUV)", "Essen", 6.9700, 51.4000, "Hintergrund"),
    "1204": _st("1204", "DENW161", "Essen Alfredstraße 9/11", "Essen", 7.0040, 51.4360, "Verkehr"),
    "1083": _st("1083", "DENW028", "Essen-Schuir (LUA)", "Essen", 6.9700, 51.4000, "Hintergrund", active_to="2007-08-29"),
    "9489": _st("9489", "DENW406", "Bochum Dorstener Straße 229", "Bochum", 7.2050, 51.4900, "Verkehr"),
    "bad": ["bad", "X", "No coords", "Essen", "", "", None, None, None],
}

AIRQUALITY_1098 = {
    "2026-09-04 08:00:00": ["2026-09-04 09:00:00", 0, 1, [5, 6, 0, "0.3"], [1, 7, 0, "0.35"], [9, 4, 0, "0.4"]],
    "2026-09-04 09:00:00": ["2026-09-04 10:00:00", 0, 1, [5, 45, 0, "0.3"], [1, 22, 0, "0.35"], [9, 11, 0, "0.4"], [3, 70, 0, "0.1"]],
}


def make_fake(*, hourly=("1098", "1290"), annual=None, airquality=AIRQUALITY_1098, fail=()):
    annual = {2025: [["1098", "23", "0"], ["1204", "27", None], ["9489", "25", None], ["1290", "20", "0"]]} if annual is None else annual
    calls = []

    def fake(path, params=None):
        calls.append((path, dict(params or {})))
        if path in fail:
            raise RuntimeError(f"{path} down")
        if path == "stations/json":
            return {"indices": STATION_INDICES, "data": STATIONS}
        if path == "meta/json":
            return {"stations": {sid: STATIONS[sid] for sid in hourly}}
        if path == "annualbalances/json":
            return {"data": annual.get(int(params["year"]), [])}
        if path == "airquality/json":
            return {"data": {params["station"]: airquality} if params["station"] == "1098" else {}}
        raise AssertionError(path)

    fake.calls = calls
    return fake


@pytest.fixture(autouse=True)
def _clear_caches():
    A._stations.cache_clear()
    A._hourly_station_ids.cache_clear()
    A._annual_no2.cache_clear()
    yield
    A._stations.cache_clear()
    A._hourly_station_ids.cache_clear()
    A._annual_no2.cache_clear()


def test_base_url_is_the_new_uba_host():
    assert A.UBA_API_BASE == "https://luftdaten.umweltbundesamt.de/api/air-data/v3"


def test_stations_parsed_by_index_names_not_positions(monkeypatch):
    monkeypatch.setattr(A, "_get_json", make_fake())
    s = {x["id"]: x for x in A._stations()}
    assert s["1098"]["name"] == "Essen-Ost Steeler Straße" and s["1098"]["city"] == "Essen"
    assert s["1098"]["lat"] == 51.4512 and s["1098"]["lon"] == 7.0305 and s["1098"]["type"] == "Verkehr"
    assert s["1083"]["active"] is False and s["1098"]["active"] is True
    assert "bad" not in s


def test_nearest_hourly_station_skips_annual_only_and_inactive(monkeypatch):
    monkeypatch.setattr(A, "_get_json", make_fake())
    # Alfredstraße (1204) is closest to Rüttenscheid but is a passive sampler (not in meta)
    st = A.nearest_hourly_station(51.4378, 7.0053)
    assert st["id"] == "1098" and st["type"] == "Verkehr" and st["distance_km"] == 2.3


def test_nearest_hourly_station_none_beyond_max_km(monkeypatch):
    monkeypatch.setattr(A, "_get_json", make_fake())
    assert A.nearest_hourly_station(52.52, 13.40) is None


def test_station_current_uses_latest_row_with_uba_index_bands(monkeypatch):
    monkeypatch.setattr(A, "_get_json", make_fake())
    cur = A.station_current("1098")
    assert cur["timestamp"] == "2026-09-04 10:00:00"
    assert cur["measurements"]["NO2"] == {"value": 45.0, "unit": "µg/m³", "index": 3}
    assert cur["measurements"]["PM10"] == {"value": 22.0, "unit": "µg/m³", "index": 2}
    assert cur["measurements"]["PM2.5"] == {"value": 11.0, "unit": "µg/m³", "index": 2}
    assert cur["measurements"]["O3"] == {"value": 70.0, "unit": "µg/m³", "index": 2}
    assert (cur["index"], cur["index_label"], cur["index_color"]) == (3, "Mäßig", "yellow")


def test_station_current_none_without_rows(monkeypatch):
    monkeypatch.setattr(A, "_get_json", make_fake())
    assert A.station_current("1290") is None


@pytest.mark.parametrize("comp,value,idx", [
    ("NO2", 20, 1), ("NO2", 21, 2), ("NO2", 40, 2), ("NO2", 100, 3), ("NO2", 200, 4), ("NO2", 201, 5),
    ("PM10", 20, 1), ("PM10", 35, 2), ("PM10", 50, 3), ("PM10", 100, 4), ("PM10", 100.1, 5),
    ("PM2.5", 10, 1), ("PM2.5", 20, 2), ("PM2.5", 25, 3), ("PM2.5", 50, 4), ("PM2.5", 51, 5),
    ("O3", 60, 1), ("O3", 120, 2), ("O3", 180, 3), ("O3", 240, 4), ("O3", 241, 5),
])
def test_uba_index_bands(comp, value, idx):
    assert A.uba_index(comp, value) == idx


def test_nearest_no2_samplers_latest_available_year(monkeypatch):
    fake = make_fake()
    monkeypatch.setattr(A, "_get_json", fake)
    monkeypatch.setattr(A, "_this_year", lambda: 2026)
    rows = A.nearest_no2_samplers(51.4378, 7.0053)
    assert [r["name"] for r in rows] == ["Essen Alfredstraße 9/11", "Essen-Ost Steeler Straße", "Essen-Schuir (LANUV)"]
    assert rows[0] == {"name": "Essen Alfredstraße 9/11", "type": "Verkehr", "distance_km": 0.2, "value": 27.0,
                       "unit": "µg/m³", "year": 2025}
    years = [c[1]["year"] for c in fake.calls if c[0] == "annualbalances/json"]
    assert years == [2025]  # last complete year first; 2026 is never asked for


def test_nearest_no2_samplers_falls_back_one_more_year(monkeypatch):
    annual = {2024: [["1204", "29", None]]}
    fake = make_fake(annual=annual)
    monkeypatch.setattr(A, "_get_json", fake)
    monkeypatch.setattr(A, "_this_year", lambda: 2026)
    rows = A.nearest_no2_samplers(51.4378, 7.0053)
    assert [(r["name"], r["year"]) for r in rows] == [("Essen Alfredstraße 9/11", 2024)]


def test_longterm_rating_against_eu_2030_limits():
    v = lambda pm25, pm10, no2: {"PM2.5": {"value": pm25, "eu2030": 10}, "PM10": {"value": pm10, "eu2030": 20},
                                 "NO2": {"value": no2, "eu2030": 20}, "O3": {"value": 300, "eu2030": None}}
    assert A.longterm_rating(v(7.0, 14.0, 15.0)) == ("Gut", "green")
    assert A.longterm_rating(v(9.0, 14.0, 15.0)) == ("Mäßig", "yellow")
    assert A.longterm_rating(v(9.0, 14.0, 28.0)) == ("Schlecht", "orange")
    assert A.longterm_rating(v(9.0, 14.0, 31.0)) == ("Sehr schlecht", "red")
    assert A.longterm_rating({}) == ("unbekannt", "gray")


def test_report_composes_all_sources(monkeypatch):
    monkeypatch.setattr(A, "_get_json", make_fake())
    monkeypatch.setattr(A, "_this_year", lambda: 2026)
    from redat.sources import airquality_grid, airquality_live
    monkeypatch.setattr(airquality_grid, "lookup", lambda lat, lon: {
        "source": "EEA", "year": 2023, "resolution_km": 1,
        "values": {"PM2.5": {"value": 9.2, "unit": "µg/m³", "who": 5, "eu2030": 10},
                   "NO2": {"value": 22.2, "unit": "µg/m³", "who": 10, "eu2030": 20}}})
    monkeypatch.setattr(airquality_live, "get_citizen_pm", lambda lat, lon: {"sensors": 7, "radius_km": 2, "pm10": 5.1, "pm25": 2.3, "timestamp": "t", "source": "Sensor.Community"})
    monkeypatch.setattr(airquality_live, "get_model_current", lambda lat, lon: {"time": "t", "european_aqi": 14, "aqi_label": "Gut", "aqi_color": "green", "PM10": 5.7, "PM2.5": 3.6, "NO2": 6.2, "O3": 38.0, "resolution_km": 11, "source": "CAMS Europe (Open-Meteo)"})

    r = A.get_air_quality_report(51.4378, 7.0053)
    assert r["longterm"]["grid"]["values"]["NO2"]["value"] == 22.2
    assert r["longterm"]["rating"] == "Schlecht" and r["longterm"]["rating_color"] == "orange"
    assert [s["name"] for s in r["longterm"]["no2_samplers"]][0] == "Essen Alfredstraße 9/11"
    assert r["current"]["station"]["name"] == "Essen-Ost Steeler Straße"
    assert r["current"]["station"]["distance_km"] == 2.3 and r["current"]["station"]["type"] == "Verkehr"
    assert r["current"]["station"]["index_label"] == "Mäßig"
    assert r["current"]["citizen"]["sensors"] == 7
    assert r["current"]["model"]["european_aqi"] == 14
    assert (r["current"]["rating"], r["current"]["rating_color"]) == ("Mäßig", "yellow")
    assert r["errors"] == {}


def test_report_survives_single_source_failures(monkeypatch):
    monkeypatch.setattr(A, "_get_json", make_fake(fail=("stations/json",)))
    monkeypatch.setattr(A, "_this_year", lambda: 2026)
    from redat.sources import airquality_grid, airquality_live
    monkeypatch.setattr(airquality_grid, "lookup", lambda lat, lon: None)

    def boom(lat, lon):
        raise RuntimeError("sensor.community down")
    monkeypatch.setattr(airquality_live, "get_citizen_pm", boom)
    monkeypatch.setattr(airquality_live, "get_model_current", lambda lat, lon: {"time": "t", "european_aqi": 55, "aqi_label": "Mäßig", "aqi_color": "yellow", "PM10": 5.7, "PM2.5": 3.6, "NO2": 6.2, "O3": 38.0, "resolution_km": 11, "source": "CAMS Europe (Open-Meteo)"})

    r = A.get_air_quality_report(51.4378, 7.0053)
    assert r["longterm"] == {"grid": None, "no2_samplers": [], "rating": "unbekannt", "rating_color": "gray"}
    assert r["current"]["station"] is None and r["current"]["citizen"] is None
    assert (r["current"]["rating"], r["current"]["rating_color"]) == ("Mäßig", "yellow")  # from the model
    assert set(r["errors"]) == {"station", "samplers", "citizen"}  # samplers need the station catalogue too


def test_report_current_rating_from_citizen_pm_when_only_source(monkeypatch):
    monkeypatch.setattr(A, "_get_json", make_fake(fail=("stations/json",)))
    from redat.sources import airquality_grid, airquality_live
    monkeypatch.setattr(airquality_grid, "lookup", lambda lat, lon: None)
    monkeypatch.setattr(airquality_live, "get_citizen_pm", lambda lat, lon: {"sensors": 4, "radius_km": 2, "pm10": 38.0, "pm25": 12.0, "timestamp": "t", "source": "Sensor.Community"})
    monkeypatch.setattr(airquality_live, "get_model_current", lambda lat, lon: None)
    r = A.get_air_quality_report(51.4378, 7.0053)
    assert (r["current"]["rating"], r["current"]["rating_color"]) == ("Mäßig", "yellow")  # PM10 38 -> band 3


def test_is_empty_only_when_every_source_is_empty():
    empty = {"longterm": {"grid": None, "no2_samplers": []}, "current": {"station": None, "citizen": None, "model": None}}
    assert A.is_empty(empty) is True
    assert A.is_empty({**empty, "current": {"station": None, "citizen": None, "model": {"x": 1}}}) is False
