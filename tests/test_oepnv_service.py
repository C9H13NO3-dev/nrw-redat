"""redat/sources/oepnv.py — VRR EFA, hermetic (`_efa` stubbed)."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from redat.sources import oepnv as ov

BERLIN = ZoneInfo("Europe/Berlin")
REF = datetime(2026, 9, 8, 8, 0, tzinfo=BERLIN)  # Tuesday


def stop(id_, name, dist, classes, lat=51.4376, lon=7.0055):
    return {"id": id_, "isGlobalId": True, "name": name, "type": "stop", "coord": [lat, lon],
            "productClasses": classes, "properties": {"distance": dist, "STOP_NAME_WITH_PLACE": f"Essen {name}"}}


def event(number, cls, product, dest, t_utc):
    return {"departureTimePlanned": t_utc,
            "transportation": {"number": number, "product": {"class": cls, "name": product},
                               "destination": {"name": dest}}}


def leg(dep, arr, duration, number=None, cls=None, product="footpath"):
    tr = {"product": {"class": 100 if number is None else cls, "name": product}}
    if number:
        tr["number"] = number
    return {"duration": duration, "origin": {"departureTimePlanned": dep},
            "destination": {"arrivalTimePlanned": arr}, "transportation": tr}


COORD = {"locations": [
    stop("de:05113:9530", "Rüttenscheider Stern", 40, [2, 4, 5]),
    stop("de:05113:9531", "Rüttenscheider Markt", 274, [4]),
    stop("de:05113:9532", "Zweigertstr.", 350, [5]),
    stop("de:05113:9533", "Witteringstr.", 424, [5]),
]}

DM_STERN = {"stopEvents": [
    *[event("U11", 2, "U-Bahn", "Essen Messe W.-Süd/Gruga", f"2026-09-08T05:{m:02d}:00Z") for m in range(0, 60, 10)],
    *[event("U11", 2, "U-Bahn", "Essen Messe W.-Süd/Gruga", f"2026-09-08T06:{m:02d}:00Z") for m in range(0, 60, 10)],
    event("U11", 2, "U-Bahn", "Essen Messe W.-Süd/Gruga", "2026-09-08T07:00:00Z"),   # 09:00 local → outside window
    event("U11", 2, "U-Bahn", "Essen Messe W.-Süd/Gruga", "2026-09-08T04:50:00Z"),   # 06:50 local → outside window
    event("107", 4, "Straßenbahn", "Essen Hanielstr.", "2026-09-08T05:05:00Z"),
    event("107", 4, "Straßenbahn", "Bredeney", "2026-09-08T05:25:00Z"),
    event("107", 4, "Straßenbahn", "Essen Hanielstr.", "2026-09-08T05:45:00Z"),
]}
DM_MARKT = {"stopEvents": [event("107", 4, "Straßenbahn", "Bredeney", f"2026-09-08T0{h}:{m:02d}:00Z")
                           for h in (5, 6) for m in range(0, 60, 15)]}  # 8 departures > 3 at Stern

TRIP_ESSEN = {"journeys": [
    {"interchanges": 1, "legs": [leg("2026-09-08T05:53:00Z", "2026-09-08T05:56:00Z", 180),
                                 leg("2026-09-08T05:56:00Z", "2026-09-08T06:00:00Z", 240, "103", 4, "Straßenbahn"),
                                 leg("2026-09-08T06:08:00Z", "2026-09-08T06:50:00Z", 2520, "S6", 1, "S-Bahn")]},
    {"interchanges": 0, "legs": [leg("2026-09-08T06:01:00Z", "2026-09-08T06:03:00Z", 120),
                                 leg("2026-09-08T06:03:00Z", "2026-09-08T06:10:00Z", 420, "U11", 2, "U-Bahn")]},
]}
TRIP_NONE = {"journeys": []}


def stub(monkeypatch, coord=COORD, dm=None, trips=None):
    calls = []
    dm = dm if dm is not None else {"de:05113:9530": DM_STERN, "de:05113:9531": DM_MARKT}
    trips = trips if trips is not None else {}

    def efa(endpoint, params):
        calls.append((endpoint, dict(params)))
        if endpoint == "XML_COORD_REQUEST":
            if isinstance(coord, Exception):
                raise coord
            return coord
        if endpoint == "XML_DM_REQUEST":
            v = dm.get(params["name_dm"], {"stopEvents": []})
            if isinstance(v, Exception):
                raise v
            return v
        if endpoint == "XML_TRIP_REQUEST2":
            v = trips.get(params["name_destination"], TRIP_NONE)
            if isinstance(v, Exception):
                raise v
            return v
        raise AssertionError(endpoint)
    monkeypatch.setattr(ov, "_efa", efa)
    monkeypatch.setattr(ov, "reference_time", lambda now=None: REF)
    return calls


def test_reference_time_is_next_tuesday_0800_berlin():
    # Friday 2026-09-04 → Tuesday 2026-09-08
    r = ov.reference_time(datetime(2026, 9, 4, 15, 0, tzinfo=BERLIN))
    assert (r.year, r.month, r.day, r.hour, r.minute) == (2026, 9, 8, 8, 0) and r.tzinfo == BERLIN
    # a Tuesday must give the *next* Tuesday, never today
    r = ov.reference_time(datetime(2026, 9, 8, 6, 0, tzinfo=BERLIN))
    assert r.day == 15
    # Monday → tomorrow
    r = ov.reference_time(datetime(2026, 9, 7, 23, 0, tzinfo=BERLIN))
    assert r.day == 8
    # naive/UTC input still yields Berlin
    r = ov.reference_time(datetime(2026, 9, 4, 22, 30, tzinfo=timezone.utc))
    assert r.day == 8 and r.hour == 8


def test_stops_parsed_sorted_and_flagged(monkeypatch):
    calls = stub(monkeypatch)
    d = ov.get_oepnv(51.4378, 7.0053, destinations=[])
    assert [s["name"] for s in d["stops"]] == ["Rüttenscheider Stern", "Rüttenscheider Markt", "Zweigertstr.", "Witteringstr."]
    s0 = d["stops"][0]
    assert s0["distance_m"] == 40 and s0["rail"] is True and s0["products"] == ["U-Bahn", "Straßenbahn", "Bus"]
    assert d["stops"][2]["rail"] is False and d["stops"][2]["products"] == ["Bus"]
    assert d["nearest_rail_m"] == 40
    coord_calls = [p for e, p in calls if e == "XML_COORD_REQUEST"]
    assert coord_calls[0]["coord"] == "7.0053:51.4378:WGS84[dd.ddddd]" and coord_calls[0]["radius_1"] == 600
    assert d["reference"] == {"date": "2026-09-08", "weekday": "Dienstag", "window": "07:00–09:00"}


def test_lines_grouped_within_window_with_headway_and_best_stop(monkeypatch):
    calls = stub(monkeypatch)
    d = ov.get_oepnv(51.4378, 7.0053, destinations=[])
    dm_stops = [p["name_dm"] for e, p in calls if e == "XML_DM_REQUEST"]
    assert dm_stops == ["de:05113:9530", "de:05113:9531", "de:05113:9532"]  # nearest three only
    assert all(p["itdDate"] == "20260908" and p["itdTime"] == "0700" for e, p in calls if e == "XML_DM_REQUEST")
    by_line = {l["line"]: l for l in d["lines"]}
    u11 = by_line["U11"]
    assert u11["departures_2h"] == 12 and u11["headway_min"] == 10.0 and u11["product"] == "U-Bahn"
    assert u11["stop"] == "Rüttenscheider Stern" and u11["destinations"] == ["Essen Messe W.-Süd/Gruga"]
    l107 = by_line["107"]
    assert l107["departures_2h"] == 8 and l107["stop"] == "Rüttenscheider Markt" and l107["headway_min"] == 15.0
    assert d["lines"][0]["line"] == "U11"  # sorted by departures desc


def test_trips_pick_shortest_journey_and_convert_to_local_time(monkeypatch):
    calls = stub(monkeypatch, trips={"de:05113:9289": TRIP_ESSEN})
    d = ov.get_oepnv(51.4378, 7.0053, destinations=[("Essen Hbf", ("stop", "de:05113:9289"))])
    t = d["trips"][0]
    assert t == {"name": "Essen Hbf", "kind": "fixed", "duration_min": 9, "interchanges": 0, "walk_min": 2,
                 "legs": ["U11"], "departure": "08:01", "arrival": "08:10"}
    p = [p for e, p in calls if e == "XML_TRIP_REQUEST2"][0]
    assert p["type_origin"] == "coord" and p["name_origin"] == "7.0053:51.4378:WGS84[dd.ddddd]"
    assert p["type_destination"] == "stop" and p["name_destination"] == "de:05113:9289"
    assert p["itdDate"] == "20260908" and p["itdTime"] == "0800" and p["itdTripDateTimeDepArr"] == "dep"


def test_custom_coord_destination_and_missing_journey(monkeypatch):
    stub(monkeypatch, trips={"6.7833:51.22:WGS84[dd.ddddd]": TRIP_ESSEN})
    d = ov.get_oepnv(51.4378, 7.0053, destinations=[
        ("Arbeit 1", ("coord", 51.22, 6.7833)), ("Essen Hbf", ("stop", "de:05113:9289"))])
    assert d["trips"][0]["name"] == "Essen Hbf" and d["trips"][0]["duration_min"] is None  # fixed first, no journey
    assert d["trips"][1]["name"] == "Arbeit 1" and d["trips"][1]["kind"] == "custom" and d["trips"][1]["duration_min"] == 9


def test_default_destinations_are_the_settings_stops(monkeypatch):
    calls = stub(monkeypatch)
    d = ov.get_oepnv(51.4378, 7.0053)
    assert [t["name"] for t in d["trips"]] == ["Essen Hbf", "Bochum Hbf", "Düsseldorf Hbf"]
    dests = [p["name_destination"] for e, p in calls if e == "XML_TRIP_REQUEST2"]
    assert dests == ["de:05113:9289", "de:05911:5194", "de:05111:18235"]
    assert all(t["kind"] == "fixed" for t in d["trips"])


def test_rating_ladder(monkeypatch):
    # rail 40 m + Hbf 9 min → Sehr gut
    stub(monkeypatch, trips={"de:05113:9289": TRIP_ESSEN})
    d = ov.get_oepnv(51.4378, 7.0053, destinations=[("Essen Hbf", ("stop", "de:05113:9289"))])
    assert (d["rating"], d["rating_color"]) == ("Sehr gut", "green")
    # rail 700 m, no trips → Gut
    stub(monkeypatch, coord={"locations": [stop("x", "Fern", 700, [1])]}, dm={})
    d = ov.get_oepnv(51.4378, 7.0053, destinations=[])
    assert (d["rating"], d["rating_color"]) == ("Gut", "green")
    # bus only at 300 m → Mäßig
    stub(monkeypatch, coord={"locations": [stop("x", "Bus", 300, [5])]}, dm={})
    d = ov.get_oepnv(51.4378, 7.0053, destinations=[])
    assert (d["rating"], d["rating_color"]) == ("Mäßig", "yellow") and d["nearest_rail_m"] is None
    # rail at 900 m only (EFA radius filter is inclusive, but > 800) → Gering
    stub(monkeypatch, coord={"locations": [stop("x", "Fern", 900, [1])]}, dm={})
    d = ov.get_oepnv(51.4378, 7.0053, destinations=[])
    assert (d["rating"], d["rating_color"]) == ("Gering", "orange")


def test_no_stops_but_trip_gives_orange_message(monkeypatch):
    stub(monkeypatch, coord={"locations": []}, dm={}, trips={"de:05113:9289": TRIP_ESSEN})
    d = ov.get_oepnv(51.4378, 7.0053, destinations=[("Essen Hbf", ("stop", "de:05113:9289"))])
    assert d["stops"] == [] and d["rating"] == "Keine Haltestelle im Umkreis von 600 m" and d["rating_color"] == "orange"


def test_nothing_at_all_returns_none(monkeypatch):
    stub(monkeypatch, coord={"locations": []}, dm={})
    assert ov.get_oepnv(52.52, 13.40, destinations=[("Essen Hbf", ("stop", "de:05113:9289"))]) is None


def test_part_isolation_and_all_failed(monkeypatch):
    stub(monkeypatch, dm={"de:05113:9530": RuntimeError("dm down")}, trips={"de:05113:9289": RuntimeError("trip down")})
    d = ov.get_oepnv(51.4378, 7.0053, destinations=[("Essen Hbf", ("stop", "de:05113:9289"))])
    assert d["stops"] and "lines" in d["errors"] and "trips" in d["errors"]
    stub(monkeypatch, coord=RuntimeError("coord down"), dm={}, trips={"de:05113:9289": RuntimeError("x")})
    with pytest.raises(RuntimeError):
        ov.get_oepnv(51.4378, 7.0053, destinations=[("Essen Hbf", ("stop", "de:05113:9289"))])


def test_stops_capped(monkeypatch):
    stub(monkeypatch, coord={"locations": [stop(f"s{i}", f"S{i}", 100 + i, [5]) for i in range(12)]}, dm={})
    d = ov.get_oepnv(51.4378, 7.0053, destinations=[])
    assert len(d["stops"]) == ov._MAX_STOPS
