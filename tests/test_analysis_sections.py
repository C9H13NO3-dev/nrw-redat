"""Registry invariants + one normalizer test per section (fixtures = live payload shapes, 2026-09-04)."""
import pytest

from redat.core import sections as S
from redat.core.sections import Ctx, Empty

CTX = Ctx(lat=51.4568, lon=7.0110, plot_size_m2=500)

# ---------------------------------------------------------------- registry

def test_registry_keys_and_order():
    assert list(S.SECTIONS) == [
        "boris", "boris_trend", "flood", "starkregen", "noise", "bergbau", "gfnp", "schutzgebiete", "planning_essen",
        "planning_bochum", "denkmal", "amenities", "oepnv", "zensus", "energie", "breitband", "infrastruktur",
        "air_quality", "btw", "commute",
    ]


def test_registry_entries_are_consistent():
    from redat.core import tiers
    for key, sec in S.SECTIONS.items():
        assert sec.key == key
        assert key in tiers.SERVICE_TIER
        assert sec.tier in ("parcel", "area")
        assert sec.timeout_s > 0
        assert sec.title and sec.icon and sec.source
        assert callable(sec.fetch)


def test_manifest_shape():
    m = S.manifest()
    assert [e["key"] for e in m] == list(S.SECTIONS)
    assert set(m[0]) == {"key", "title", "icon", "tier", "timeout_s", "source"}
    assert {e["key"]: e["tier"] for e in m}["noise"] == "area"
    assert {e["key"]: e["tier"] for e in m}["boris"] == "parcel"

# ---------------------------------------------------------------- area tier

AMENITIES_RAW = {
    "public_transport_score": 8, "walkability_score": 7,
    "distance_to_public_transport_m": 120, "distance_to_school_m": 450,
    "distance_to_kindergarten_m": None, "distance_to_supermarket_m": 300, "distance_to_doctor_m": 800,
    "public_transport": {"stops": [], "nearest_m": 120, "score": 8},
    "schools": [{"name": "Grundschule A", "distance_m": 450, "type": "school"}],
    "kindergartens": [],
    "supermarkets": [{"name": "REWE", "distance_m": 300}],
    "doctors": [{"name": None, "distance_m": 800}],
}


def test_amenities_normalizer(monkeypatch):
    from redat.sources import geoapify
    monkeypatch.setattr(geoapify, "get_all_amenities", lambda lat, lon: AMENITIES_RAW)
    d = S._fetch_amenities(CTX)
    assert d == {
        "public_transport_score": 8, "walkability_score": 7,
        "distances": {"public_transport": 120, "school": 450, "kindergarten": None, "supermarket": 300, "doctor": 800},
        "nearest": {
            "school": {"name": "Grundschule A", "distance_m": 450},
            "kindergarten": None,
            "supermarket": {"name": "REWE", "distance_m": 300},
            "doctor": {"name": "—", "distance_m": 800},
        },
    }


AIR_REPORT = {
    "longterm": {
        "grid": {"source": "EEA", "year": 2023, "resolution_km": 1,
                 "values": {"NO2": {"value": 22.2, "unit": "µg/m³", "who": 10, "eu2030": 20}}},
        "no2_samplers": [{"name": "Essen Alfredstraße 9/11", "type": "Verkehr", "distance_km": 0.3, "value": 27.0, "unit": "µg/m³", "year": 2025}],
        "rating": "Schlecht", "rating_color": "orange",
    },
    "current": {
        "station": {"id": "1098", "name": "Essen-Ost Steeler Straße", "city": "Essen", "type": "Verkehr", "distance_km": 2.3,
                    "timestamp": "2026-09-04 10:00:00", "measurements": {"NO2": {"value": 6.0, "unit": "µg/m³", "index": 1}},
                    "index": 1, "index_label": "Sehr gut", "index_color": "green"},
        "citizen": None, "model": None, "rating": "Sehr gut", "rating_color": "green",
    },
    "errors": {},
}


def test_air_quality_passes_report_through(monkeypatch):
    from redat.sources import airquality
    monkeypatch.setattr(airquality, "get_air_quality_report", lambda lat, lon: AIR_REPORT)
    assert S._fetch_air_quality(CTX) == AIR_REPORT


def test_air_quality_all_sources_empty_is_empty(monkeypatch):
    from redat.sources import airquality
    monkeypatch.setattr(airquality, "get_air_quality_report", lambda lat, lon: {
        "longterm": {"grid": None, "no2_samplers": [], "rating": "unbekannt", "rating_color": "gray"},
        "current": {"station": None, "citizen": None, "model": None, "rating": "unbekannt", "rating_color": "gray"},
        "errors": {"station": "down"}})
    with pytest.raises(Empty) as ei:
        S._fetch_air_quality(CTX)
    assert ei.value.message == "Keine Luftdaten für diesen Ort"


def test_air_quality_partial_report_is_not_empty(monkeypatch):
    from redat.sources import airquality
    report = {"longterm": {"grid": None, "no2_samplers": [], "rating": "unbekannt", "rating_color": "gray"},
              "current": {"station": None, "citizen": None, "model": AIR_REPORT["current"]["station"] and {"european_aqi": 14},
                          "rating": "Gut", "rating_color": "green"}, "errors": {"station": "timeout"}}
    monkeypatch.setattr(airquality, "get_air_quality_report", lambda lat, lon: report)
    assert S._fetch_air_quality(CTX)["errors"] == {"station": "timeout"}


BTW_RAW = {
    "election": "Bundestagswahl 2025",
    "wahlkreis": {"nr": 119, "name": "Essen II"},
    "top_parties": [{"party": "SPD", "percent": 28.4, "color": "#E3000F"}, {"party": "CDU", "percent": 25.1, "color": "#000000"}],
    "source": "Die Bundeswahlleiterin (Open Data kerg2.csv, Zweitstimmen, Wahlkreise)",
}


def test_btw_normalizer_renames_top_parties(monkeypatch):
    from redat.sources import btw
    monkeypatch.setattr(btw, "get_btw_wahlkreis_profile", lambda lat, lon, top_n=5: BTW_RAW)
    d = S._fetch_btw(CTX)
    assert d == {"election": "Bundestagswahl 2025", "wahlkreis": {"nr": 119, "name": "Essen II"},
                 "parties": BTW_RAW["top_parties"]}
    assert "top_parties" not in d


def test_btw_not_found_is_none(monkeypatch):
    from redat.sources import btw
    monkeypatch.setattr(btw, "get_btw_wahlkreis_profile", lambda lat, lon, top_n=5: {"error": "Wahlkreis nicht gefunden"})
    assert S._fetch_btw(CTX) is None


def test_commute_uses_ctx_destinations_then_defaults(monkeypatch):
    from redat.sources import geoapify
    from redat.settings import Destination
    seen = []
    def fake(flat, flon, tlat, tlon):
        seen.append((tlat, tlon))
        return {"time_minutes": 12, "distance_km": 5.4} if tlat == 51.5 else None
    monkeypatch.setattr(geoapify, "get_driving_time", fake)
    ctx = Ctx(lat=51.4, lon=7.0, destinations=(Destination("Büro", 51.5, 7.1, "work", "Kettwiger Str. 1"), Destination("Oma", 51.6, 7.2)))
    assert S._fetch_commute(ctx) == {"destinations": [
        {"name": "Büro", "address": "Kettwiger Str. 1", "group": "work", "time_minutes": 12, "distance_km": 5.4},
        {"name": "Oma", "address": None, "group": "custom", "time_minutes": None, "distance_km": None},
    ]}
    assert seen == [(51.5, 7.1), (51.6, 7.2)]
    seen.clear()
    S._fetch_commute(Ctx(lat=51.4, lon=7.0))
    assert [n for n, _ in seen] == [51.4508, 51.4785, 51.2199]   # settings.yaml Hbf defaults


def test_commute_without_any_destinations_is_empty(monkeypatch):
    monkeypatch.setattr(S, "_destinations", lambda ctx: ())
    with pytest.raises(Empty) as ei:
        S._fetch_commute(Ctx(lat=51.4, lon=7.0))
    assert "Keine Zielorte" in ei.value.message


def test_oepnv_passes_fixed_stops_plus_custom_coords(monkeypatch):
    from redat.sources import oepnv
    from redat.settings import Destination
    seen = {}
    def fake(lat, lon, *, destinations=None):
        seen["d"] = destinations
        return {"stops": [], "trips": []}
    monkeypatch.setattr(oepnv, "get_oepnv", fake)
    ctx = Ctx(lat=51.4, lon=7.0, destinations=(Destination("Essen Hbf", 51.45, 7.01, "hbf"), Destination("Büro", 51.5, 7.1, "work")))
    S._fetch_oepnv(ctx)
    assert seen["d"] == [("Essen Hbf", ("stop", "de:05113:9289")), ("Bochum Hbf", ("stop", "de:05911:5194")),
                         ("Düsseldorf Hbf", ("stop", "de:05111:18235")), ("Büro", ("coord", 51.5, 7.1))]


def test_noise_normalizer_passes_through(monkeypatch):
    from redat.sources import noise
    payload = {"day": None, "night": None, "sources": {}, "below_threshold": True}
    monkeypatch.setattr(noise, "get_noise_levels", lambda lat, lon: payload)
    assert S._fetch_noise(CTX) == payload

# ---------------------------------------------------------------- parcel tier

def test_boris_normalizer_with_plot_value(monkeypatch):
    from redat.sources import boris
    monkeypatch.setattr(boris, "get_boris_nrw", lambda lat, lon: {"bodenrichtwert": 420.0, "date": "2025-01-01", "zone": "Rüttenscheid", "raw": {"brw": "420"}})
    d = S._fetch_boris(CTX)
    assert d == {"bodenrichtwert": 420.0, "date": "2025-01-01", "zone": "Rüttenscheid", "grundstueckswert": 210000.0, "raw": {"brw": "420"}}


def test_boris_without_plot_has_null_value(monkeypatch):
    from redat.sources import boris
    monkeypatch.setattr(boris, "get_boris_nrw", lambda lat, lon: {"bodenrichtwert": 420.0, "date": None, "zone": None, "raw": {}})
    assert S._fetch_boris(Ctx(lat=51.4, lon=7.0))["grundstueckswert"] is None


def test_boris_no_data_is_none(monkeypatch):
    from redat.sources import boris
    monkeypatch.setattr(boris, "get_boris_nrw", lambda lat, lon: {"error": "No BORIS data for this location"})
    assert S._fetch_boris(CTX) is None


def test_boris_service_error_raises(monkeypatch):
    from redat.sources import boris
    monkeypatch.setattr(boris, "get_boris_nrw", lambda lat, lon: {"error": "BORIS timeout"})
    with pytest.raises(RuntimeError, match="BORIS timeout"):
        S._fetch_boris(CTX)


def test_boris_trend_normalizer(monkeypatch):
    from redat.sources import boris
    trend = boris.BorisTrend(
        current_value=420.0, current_year=2025,
        history=[{"year": 2020, "value": 360.0, "change_percent": None}, {"year": 2025, "value": 420.0, "change_percent": 16.7}],
        avg_yearly_change=3.1, total_change=16.7, oldest_year=2020, oldest_value=360.0,
    )
    monkeypatch.setattr(boris, "get_historical_trend", lambda lat, lon: trend)
    d = S._fetch_boris_trend(CTX)
    assert d == {"current_year": 2025, "current_value": 420.0, "oldest_year": 2020, "oldest_value": 360.0,
                 "avg_yearly_change": 3.1, "total_change": 16.7, "history": trend.history}


def test_boris_trend_none(monkeypatch):
    from redat.sources import boris
    monkeypatch.setattr(boris, "get_historical_trend", lambda lat, lon: None)
    assert S._fetch_boris_trend(CTX) is None


def test_flood_normalizer(monkeypatch):
    from redat.sources import flood
    raw = {"zone": "HQextrem", "risk_level": "medium", "hits": {
        "HQhaeufig": {"hit": False, "min_distance_m": 812.5, "raw": None},
        "HQ100": {"hit": False, "min_distance_m": None, "raw": None},
        "HQextrem": {"hit": True, "min_distance_m": 0.0, "raw": {"name": "Ruhr"}},
    }}
    monkeypatch.setattr(flood, "flood_risk", lambda lat, lon: raw)
    d = S._fetch_flood(CTX)
    assert d == {"flood_zone": "HQextrem", "flood_risk_level": "medium", "hits": {
        "HQhaeufig": {"hit": False, "min_distance_m": 812.5},
        "HQ100": {"hit": False, "min_distance_m": None},
        "HQextrem": {"hit": True, "min_distance_m": 0.0},
    }}


def test_gfnp_normalizer(monkeypatch):
    from redat.sources import gfnp
    monkeypatch.setattr(gfnp, "get_gfnp_designation", lambda lat, lon: {
        "ok": True, "found": True, "designation": "Wohnbaufläche", "city": "Essen", "date": "2023-05-01", "overlays": [], "source": "x"})
    assert S._fetch_gfnp(CTX) == {"found": True, "designation": "Wohnbaufläche", "city": "Essen", "date": "2023-05-01"}


def test_gfnp_not_ok_raises(monkeypatch):
    from redat.sources import gfnp
    monkeypatch.setattr(gfnp, "get_gfnp_designation", lambda lat, lon: {"ok": False, "error": "ArcGIS 503"})
    with pytest.raises(RuntimeError, match="ArcGIS 503"):
        S._fetch_gfnp(CTX)


def test_planning_essen_flattens_lists(monkeypatch):
    from redat.sources import planning_essen
    monkeypatch.setattr(planning_essen, "get_planning_signals", lambda lat, lon: {
        "ok": True, "found": True,
        "bplan": [{"nr": "12/07", "name": "Rüttenscheider Stern", "plan_type": "B-Plan", "status": "rechtskräftig", "plan_id": 5, "link": "https://geo.essen.de/x"}],
        "vhbplan": [], "veraenderungssperre": [{"nr": "VS 3", "name": None}],
        "aufstellungsbeschluss": [], "auslegungsbeschluss": [], "aufhebungsbeschluss": [], "source": "x"})
    d = S._fetch_planning_essen(CTX)
    assert d == {"found": True, "items": [
        {"category": "Bebauungsplan", "name": "12/07 Rüttenscheider Stern (B-Plan, rechtskräftig)", "link": "https://geo.essen.de/x"},
        {"category": "Veränderungssperre", "name": "VS 3", "link": None},
    ]}


def test_planning_essen_nothing_found(monkeypatch):
    from redat.sources import planning_essen
    monkeypatch.setattr(planning_essen, "get_planning_signals", lambda lat, lon: {
        "ok": True, "found": False, "bplan": [], "vhbplan": [], "veraenderungssperre": [],
        "aufstellungsbeschluss": [], "auslegungsbeschluss": [], "aufhebungsbeschluss": [], "source": "x"})
    assert S._fetch_planning_essen(CTX) == {"found": False, "items": []}


def test_planning_bochum_same_shape(monkeypatch):
    from redat.sources import planning_bochum
    monkeypatch.setattr(planning_bochum, "get_bochum_bplan_outline", lambda lat, lon: {
        "ok": True, "found": True, "source": "x",
        "items": [{"official_name": "Nr. 800 Ehrenfeld", "plan_id": "800", "commune": "Bochum", "plan_type": "BPlan",
                   "legal_status": "rechtsverbindlich", "plan_link": None, "metadata_link": "https://rvr/meta"}]})
    d = S._fetch_planning_bochum(CTX)
    assert d == {"found": True, "items": [
        {"category": "BPlan", "name": "Nr. 800 Ehrenfeld (rechtsverbindlich)", "link": "https://rvr/meta"}]}


def test_planning_bochum_not_ok_raises(monkeypatch):
    from redat.sources import planning_bochum
    monkeypatch.setattr(planning_bochum, "get_bochum_bplan_outline", lambda lat, lon: {"ok": False, "error": "WMS down"})
    with pytest.raises(RuntimeError, match="WMS down"):
        S._fetch_planning_bochum(CTX)


# ---------------------------------------------------------------- risk cards (2026-09-04)

def test_starkregen_passes_through_and_is_parcel(monkeypatch):
    from redat.core import tiers
    from redat.sources import starkregen
    payload = {"radius_m": 50, "building_share": 0.3, "scenarios": {"agw": None, "extrem": None},
               "rating": "Gering", "rating_color": "green", "errors": {}}
    monkeypatch.setattr(starkregen, "get_starkregen", lambda lat, lon: payload)
    assert S._fetch_starkregen(CTX) == payload
    assert tiers.SERVICE_TIER["starkregen"] == "parcel"


def test_starkregen_none_is_empty(monkeypatch):
    from redat.sources import starkregen
    monkeypatch.setattr(starkregen, "get_starkregen", lambda lat, lon: None)
    with pytest.raises(Empty, match="Starkregen"):
        S._fetch_starkregen(CTX)


def test_bergbau_passes_through_and_is_area(monkeypatch):
    from redat.core import tiers
    from redat.sources import bergbau
    payload = {"cell_id": "1", "cell_size_m": 500, "authority": "Geologischer Dienst NRW", "updated": None,
               "items": [], "rating": "Keine Hinweise", "rating_color": "green"}
    monkeypatch.setattr(bergbau, "get_bergbau", lambda lat, lon: payload)
    assert S._fetch_bergbau(CTX) == payload
    assert tiers.SERVICE_TIER["bergbau"] == "area"


def test_bergbau_none_is_empty(monkeypatch):
    from redat.sources import bergbau
    monkeypatch.setattr(bergbau, "get_bergbau", lambda lat, lon: None)
    with pytest.raises(Empty, match="Planquadrat"):
        S._fetch_bergbau(CTX)


def test_zensus_passes_through_and_is_area(monkeypatch):
    from redat.core import tiers
    from redat.sources import zensus
    payload = {"year": 2022, "cell_m": 100, "radius_m": 250, "area_cells": 3, "cell": None, "area": {"einwohner": 7}}
    monkeypatch.setattr(zensus, "lookup", lambda lat, lon: payload)
    assert S._fetch_zensus(CTX) == payload
    assert tiers.SERVICE_TIER["zensus"] == "area"


def test_zensus_none_is_empty(monkeypatch):
    from redat.sources import zensus
    monkeypatch.setattr(zensus, "lookup", lambda lat, lon: None)
    with pytest.raises(Empty, match="Zensus"):
        S._fetch_zensus(CTX)


def test_energie_passes_through_and_is_parcel(monkeypatch):
    from redat.core import tiers
    from redat.sources import energie
    payload = {"pv": {"total_kwp": 7.4}, "erdwaerme": None, "waermeplanung": None, "errors": {}}
    monkeypatch.setattr(energie, "get_energie", lambda lat, lon: payload)
    assert S._fetch_energie(CTX) == payload
    assert tiers.SERVICE_TIER["energie"] == "parcel"


def test_energie_none_is_empty(monkeypatch):
    from redat.sources import energie
    monkeypatch.setattr(energie, "get_energie", lambda lat, lon: None)
    with pytest.raises(S.Empty):
        S._fetch_energie(CTX)


def test_schutzgebiete_passes_through_and_is_area(monkeypatch):
    from redat.core import tiers
    from redat.sources import schutzgebiete
    payload = {"radius_m": 500, "areas": [], "wsg": [], "rating": "Keine Schutzgebiete", "rating_color": "green", "errors": {}}
    monkeypatch.setattr(schutzgebiete, "get_schutzgebiete", lambda lat, lon: payload)
    assert S._fetch_schutzgebiete(CTX) == payload
    assert tiers.SERVICE_TIER["schutzgebiete"] == "area"


def test_breitband_passes_through_and_is_area(monkeypatch):
    from redat.core import tiers
    from redat.sources import breitband
    payload = {"cell_m": 100, "fixed": {}, "mobile_5g": {}, "rating": "Glasfaser verfügbar", "rating_color": "green", "errors": {}}
    monkeypatch.setattr(breitband, "get_breitband", lambda lat, lon: payload)
    assert S._fetch_breitband(CTX) == payload
    assert tiers.SERVICE_TIER["breitband"] == "area"


def test_breitband_none_is_empty(monkeypatch):
    from redat.sources import breitband
    monkeypatch.setattr(breitband, "get_breitband", lambda lat, lon: None)
    with pytest.raises(S.Empty):
        S._fetch_breitband(CTX)


def test_denkmal_passes_through_and_is_parcel(monkeypatch):
    from redat.core import tiers
    from redat.sources import denkmal
    payload = {"radius_m": 300, "items": [], "counts": {}, "on_site": [], "authority": None,
               "rating": "Kein Denkmalschutz", "rating_color": "green"}
    monkeypatch.setattr(denkmal, "get_denkmal", lambda lat, lon: payload)
    assert S._fetch_denkmal(CTX) == payload
    assert tiers.SERVICE_TIER["denkmal"] == "parcel"


def test_denkmal_none_is_empty(monkeypatch):
    from redat.sources import denkmal
    monkeypatch.setattr(denkmal, "get_denkmal", lambda lat, lon: None)
    with pytest.raises(S.Empty, match="RVR"):
        S._fetch_denkmal(CTX)


def test_oepnv_passes_through_and_is_area(monkeypatch):
    from redat.core import tiers
    from redat.sources import oepnv
    payload = {"reference": {}, "stops": [], "lines": [], "trips": [], "nearest_rail_m": None,
               "rating": "Gering", "rating_color": "orange", "errors": {}}
    monkeypatch.setattr(oepnv, "get_oepnv", lambda lat, lon, *, destinations=None: payload)
    assert S._fetch_oepnv(CTX) == payload
    assert tiers.SERVICE_TIER["oepnv"] == "area"


def test_oepnv_none_is_empty(monkeypatch):
    from redat.sources import oepnv
    monkeypatch.setattr(oepnv, "get_oepnv", lambda lat, lon, *, destinations=None: None)
    with pytest.raises(S.Empty, match="VRR"):
        S._fetch_oepnv(CTX)


def test_infrastruktur_passes_through_and_is_area(monkeypatch):
    from redat.core import tiers
    from redat.sources import infrastruktur
    payload = {"power_lines": [], "ied_sites": [], "rating": "Unauffällig", "rating_color": "green", "errors": {}}
    monkeypatch.setattr(infrastruktur, "get_infrastruktur", lambda lat, lon: payload)
    assert S._fetch_infrastruktur(CTX) == payload
    assert tiers.SERVICE_TIER["infrastruktur"] == "area"
