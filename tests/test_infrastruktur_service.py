"""backend/infrastruktur_service.py — Overpass + EEA discodata, hermetic (both HTTP points stubbed)."""
import pytest

from redat.sources import infrastruktur as inf

LAT, LON = 51.4586, 7.1934  # Bochum-Weitmar


def way(id_, tags, coords):
    return {"type": "way", "id": id_, "tags": tags, "geometry": [{"lat": la, "lon": lo} for la, lo in coords]}


def node(id_, tags, lat, lon):
    return {"type": "node", "id": id_, "tags": tags, "lat": lat, "lon": lon}


def line_at(offset_lat, tags, id_=1):
    """An east–west way `offset_lat` degrees north of the point (1e-3 ≈ 111 m)."""
    return way(id_, tags, [(LAT + offset_lat, LON - 0.01), (LAT + offset_lat, LON + 0.01)])


def site(sid, name, lat, lon, year=2024, acts="Chemicals", city="Essen"):
    return {"InspireSiteId": sid, "siteName": name, "cities": city, "eea_activities": acts,
            "Site_reporting_year": year, "x_4258": lon, "y_4258": lat}


def stub(monkeypatch, elements=None, sites=None):
    calls = {"overpass": [], "sql": []}

    def overpass(q):
        calls["overpass"].append(q)
        if isinstance(elements, Exception):
            raise elements
        return {"elements": elements or []}

    def discodata(sql):
        calls["sql"].append(sql)
        if isinstance(sites, Exception):
            raise sites
        return sites or []
    monkeypatch.setattr(inf, "_overpass", overpass)
    monkeypatch.setattr(inf, "_discodata", discodata)
    return calls


def test_nothing_found_is_green_never_none(monkeypatch):
    calls = stub(monkeypatch)
    d = inf.get_infrastruktur(LAT, LON)
    assert d["rating"] == "Unauffällig" and d["rating_color"] == "green"
    assert d["power_lines"] == [] and d["ied_sites"] == [] and d["industrial_landuse_m"] is None
    assert d["trafo_count"] == 0 and d["errors"] == {}
    assert "Seveso" in d["seveso_note"] and "Arnsberg" in d["seveso_note"]
    q = calls["overpass"][0]
    assert "around:500" in q and "around:1500" in q and 'landuse"="industrial' in q and "out tags geom" in q
    # only communication masts — church bell towers / lighting masts must not count as "Sendemasten"
    assert '"tower:type"~"communication"' in q and '"man_made"="communications_tower"' in q
    assert "bell_tower" not in q and '["tower:type"!="cooling"]' not in q
    sql = calls["sql"][0]
    assert "[IED].[latest].[SiteMap]" in sql and "countryCode='DE'" in sql and "BETWEEN" in sql


def test_voltage_parsing_and_line_distance(monkeypatch):
    stub(monkeypatch, elements=[
        line_at(0.0012, {"power": "line", "voltage": "380000;220000;110000", "name": "Eppendorf-Hattingen"}, 1),
        line_at(0.0030, {"power": "minor_line"}, 2),
        line_at(0.0020, {"power": "cable", "voltage": "110000", "location": "underground"}, 3),
        line_at(0.0100, {"power": "line", "voltage": "380000"}, 4),  # ~1.1 km → dropped
        {"type": "way", "id": 5, "tags": {"power": "line", "voltage": "110000"}, "geometry": [{"lat": LAT, "lon": LON}]},  # 1 pt → skipped
    ])
    d = inf.get_infrastruktur(LAT, LON)
    ids = [(l["voltage_kv"], l["kind"], l["underground"]) for l in d["power_lines"]]
    assert ids == [(380, "hochspannung", False), (110, "hochspannung", True), (None, "mittelspannung", False)]
    hv = d["power_lines"][0]
    assert hv["voltages"] == [380, 220, 110] and hv["name"] == "Eppendorf-Hattingen" and 125 < hv["distance_m"] < 140
    assert d["rating"] == "Erhöht" and d["rating_color"] == "orange"  # HV within 200 m


def test_hv_line_within_50m_is_red_but_underground_cable_is_not(monkeypatch):
    stub(monkeypatch, elements=[line_at(0.0003, {"power": "line", "voltage": "110000"})])
    assert inf.get_infrastruktur(LAT, LON)["rating"] == "Belastung"
    stub(monkeypatch, elements=[line_at(0.0003, {"power": "cable", "voltage": "110000"})])
    d = inf.get_infrastruktur(LAT, LON)
    assert d["rating"] == "Hinweise" and d["power_lines"][0]["underground"] is True


def test_substations_split_listed_vs_counted(monkeypatch):
    stub(monkeypatch, elements=[
        node(1, {"power": "substation", "voltage": "110000;10000", "name": "Umspannwerk Eppendorf"}, LAT + 0.0035, LON),
        node(2, {"power": "substation", "voltage": "10000;400"}, LAT + 0.001, LON),
        way(3, {"power": "substation"}, [(LAT + 0.002, LON), (LAT + 0.002, LON + 0.001), (LAT + 0.0021, LON + 0.001)]),
    ])
    d = inf.get_infrastruktur(LAT, LON)
    assert [s["name"] for s in d["substations"]] == ["Umspannwerk Eppendorf"]
    assert d["substations"][0]["voltage_kv"] == 110 and 380 < d["substations"][0]["distance_m"] < 400
    assert d["trafo_count"] == 2
    assert d["rating"] == "Hinweise"  # 389 m > 200 m


def test_umspannwerk_within_200m_is_orange(monkeypatch):
    stub(monkeypatch, elements=[node(1, {"power": "substation", "voltage": "110000", "name": "UW"}, LAT + 0.001, LON)])
    assert inf.get_infrastruktur(LAT, LON)["rating"] == "Erhöht"


def test_wind_mast_pipeline_and_landuse(monkeypatch):
    stub(monkeypatch, elements=[
        node(1, {"generator:source": "wind", "name": "WEA Karnap"}, LAT + 0.011, LON),          # ~1.2 km
        node(2, {"man_made": "mast", "tower:type": "communication"}, LAT + 0.002, LON),         # ~222 m
        node(3, {"man_made": "tower", "tower:type": "communication"}, LAT + 0.0025, LON),
        line_at(0.0004, {"man_made": "pipeline", "substance": "oxygen", "name": "O2 Leitung"}, 4),   # ~44 m
        line_at(0.0015, {"man_made": "pipeline", "substance": "water"}, 5),
        line_at(0.0010, {"man_made": "pipeline"}, 6),
        way(7, {"landuse": "industrial"}, [(LAT + 0.0005, LON - 0.001), (LAT + 0.0005, LON + 0.001),
                                          (LAT + 0.001, LON + 0.001), (LAT + 0.001, LON - 0.001), (LAT + 0.0005, LON - 0.001)]),
    ])
    d = inf.get_infrastruktur(LAT, LON)
    assert d["wind"] == [{"name": "WEA Karnap", "distance_m": d["wind"][0]["distance_m"]}] and 1200 < d["wind"][0]["distance_m"] < 1250
    assert [m["kind"] for m in d["masts"]] == ["mast", "tower"]
    pipes = {p["substance"]: p for p in d["pipelines"]}
    assert pipes["oxygen"]["hazardous"] is True and pipes["oxygen"]["name"] == "O2 Leitung" and pipes["oxygen"]["distance_m"] < 50
    assert pipes["water"]["hazardous"] is False and pipes[None]["hazardous"] is False
    assert 50 < d["industrial_landuse_m"] < 60
    assert d["rating"] == "Erhöht"  # hazardous pipeline ≤ 50 m


def test_landuse_inside_is_zero_and_orange(monkeypatch):
    stub(monkeypatch, elements=[way(7, {"landuse": "industrial"}, [(LAT - 0.001, LON - 0.001), (LAT - 0.001, LON + 0.001),
                                                                   (LAT + 0.001, LON + 0.001), (LAT + 0.001, LON - 0.001),
                                                                   (LAT - 0.001, LON - 0.001)])])
    d = inf.get_infrastruktur(LAT, LON)
    assert d["industrial_landuse_m"] == 0.0 and d["rating"] == "Erhöht"


def test_wind_thresholds(monkeypatch):
    stub(monkeypatch, elements=[node(1, {"generator:source": "wind"}, LAT + 0.004, LON)])  # ~445 m
    assert inf.get_infrastruktur(LAT, LON)["rating"] == "Belastung"
    stub(monkeypatch, elements=[node(1, {"generator:source": "wind"}, LAT + 0.008, LON)])  # ~890 m
    assert inf.get_infrastruktur(LAT, LON)["rating"] == "Erhöht"
    stub(monkeypatch, elements=[node(1, {"generator:source": "wind"}, LAT + 0.013, LON)])  # ~1.45 km
    assert inf.get_infrastruktur(LAT, LON)["rating"] == "Hinweise"


def test_ied_latest_year_distance_cap_and_sectors(monkeypatch):
    stub(monkeypatch, sites=[
        site("DE.1", "Evonik Operations GmbH", LAT + 0.0085, LON, 2022, "Chemicals"),
        site("DE.1", "Evonik Operations GmbH", LAT + 0.0085, LON, 2024, "Chemicals, Other waste management, Chemicals"),
        site("DE.2", "Weit weg", LAT + 0.03, LON, 2024),                         # > 2 km
        *[site(f"DE.{i}", f"Site {i}", LAT + 0.012 + i * 0.0001, LON, 2024) for i in range(3, 20)],
    ])
    d = inf.get_infrastruktur(LAT, LON)
    assert len(d["ied_sites"]) == 10
    s = d["ied_sites"][0]
    assert s["name"] == "Evonik Operations GmbH" and s["year"] == 2024 and s["city"] == "Essen"
    assert s["sectors"] == ["Chemicals", "Other waste management"] and 935 < s["distance_m"] < 955
    assert all("Weit weg" != x["name"] for x in d["ied_sites"])
    assert d["rating"] == "Erhöht"  # ≤ 1000 m


def test_ied_within_300m_is_red(monkeypatch):
    stub(monkeypatch, sites=[site("DE.9", "Kläranlage", LAT + 0.002, LON)])
    assert inf.get_infrastruktur(LAT, LON)["rating"] == "Belastung"


def test_stale_ied_site_is_flagged_and_not_rated(monkeypatch):
    """Legacy E-PRTR rows (last report 10+ years ago) are closed plants — listed after live ones, never rated."""
    stub(monkeypatch, sites=[site("DE.8", "Opel Werk I", LAT + 0.002, LON, 2014),
                             site("DE.9", "Recycling", LAT + 0.012, LON, 2024)])
    d = inf.get_infrastruktur(LAT, LON)
    assert [s["name"] for s in d["ied_sites"]] == ["Recycling", "Opel Werk I"]  # live first despite distance
    assert d["ied_sites"][1]["stale"] is True and d["ied_sites"][0]["stale"] is False
    assert d["rating"] == "Hinweise"  # the 2014 site 222 m away must not trigger "Belastung"
    stub(monkeypatch, sites=[site("DE.8", "Opel Werk I", LAT + 0.002, LON, 2014)])
    assert inf.get_infrastruktur(LAT, LON)["rating"] == "Unauffällig"


def test_part_isolation(monkeypatch):
    stub(monkeypatch, elements=RuntimeError("overpass down"), sites=[site("DE.9", "X", LAT + 0.015, LON)])
    d = inf.get_infrastruktur(LAT, LON)
    assert "osm" in d["errors"] and d["ied_sites"] and d["rating"] == "Hinweise"
    stub(monkeypatch, elements=[line_at(0.001, {"power": "line", "voltage": "110000"})], sites=RuntimeError("eea down"))
    d = inf.get_infrastruktur(LAT, LON)
    assert "ied" in d["errors"] and d["power_lines"]
    stub(monkeypatch, elements=RuntimeError("a"), sites=RuntimeError("b"))
    with pytest.raises(RuntimeError):
        inf.get_infrastruktur(LAT, LON)


def test_overpass_retries_then_falls_back_to_mirror(monkeypatch):
    seen = []

    class Resp:
        def __init__(self, status, body):
            self.status_code, self._body = status, body

        def json(self):
            return self._body

    def post(url, data=None, headers=None, timeout=None):
        seen.append(url)
        if url == inf.OVERPASS_URLS[0]:
            return Resp(429, None)
        return Resp(200, {"elements": [{"type": "node", "id": 1}]})
    monkeypatch.setattr(inf.httpx, "post", post)
    monkeypatch.setattr(inf.time, "sleep", lambda s: None)
    assert inf._overpass("[out:json];") == {"elements": [{"type": "node", "id": 1}]}
    assert seen == [inf.OVERPASS_URLS[0], inf.OVERPASS_URLS[0], inf.OVERPASS_URLS[1]]


def test_overpass_timeout_moves_on_to_mirror(monkeypatch):
    seen = []

    class Resp:
        status_code = 200

        def json(self):
            return {"elements": []}

    def post(url, data=None, headers=None, timeout=None):
        seen.append((url, timeout))
        if url == inf.OVERPASS_URLS[0]:
            raise inf.httpx.ReadTimeout("slow")
        return Resp()
    monkeypatch.setattr(inf.httpx, "post", post)
    monkeypatch.setattr(inf.time, "sleep", lambda s: None)
    assert inf._overpass("[out:json];") == {"elements": []}
    assert [u for u, _ in seen] == [inf.OVERPASS_URLS[0], inf.OVERPASS_URLS[0], inf.OVERPASS_URLS[1]]
    # worst case (three timeouts + pause) must fit inside the registry section timeout
    assert all(t == inf._TIMEOUT_S for _, t in seen)
    assert 3 * inf._TIMEOUT_S + inf._RETRY_SLEEP_S < 60


def test_overpass_all_timeouts_raise(monkeypatch):
    def post(url, data=None, headers=None, timeout=None):
        raise inf.httpx.ConnectTimeout("down")
    monkeypatch.setattr(inf.httpx, "post", post)
    monkeypatch.setattr(inf.time, "sleep", lambda s: None)
    with pytest.raises(RuntimeError, match="nicht erreichbar"):
        inf._overpass("x")


def test_overpass_hard_error_raises(monkeypatch):
    class Resp:
        status_code = 400
        text = "bad query"

        def json(self):
            return {}
    monkeypatch.setattr(inf.httpx, "post", lambda *a, **k: Resp())
    with pytest.raises(RuntimeError):
        inf._overpass("x")


def test_parse_voltages():
    assert inf._parse_voltages("380000;220000;110000") == [380, 220, 110]
    assert inf._parse_voltages("110000;0") == [110, 0]
    assert inf._parse_voltages("0") == [0]
    assert inf._parse_voltages(None) == [] and inf._parse_voltages("unknown") == []
