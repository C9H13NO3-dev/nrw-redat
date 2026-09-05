"""Tests for report.builder — the payload → template-context step of the PDF export."""
import json
from pathlib import Path

import pytest

from redat.core.sections import SECTIONS
from redat.report import builder
from redat.report.builder import ReportPayloadError, build_report_context, slugify

FIXTURES = json.loads((Path(__file__).parent / "fixtures" / "report_envelopes.json").read_text())


def _payload(sections=None, **over):
    p = {
        "address": "Brückstraße 12, 45239 Essen",
        "geocode": {"formatted_address": "Brückstraße 12, 45239 Essen, Deutschland",
                    "latitude": 51.3885, "longitude": 7.0035, "precision": "building"},
        "plot_size_m2": 450,
        "living_space_m2": 140,
        "sections": FIXTURES if sections is None else sections,
    }
    p.update(over)
    return p


def test_body_follows_registry_order_and_only_ok_sections():
    ctx = build_report_context(_payload())
    keys = [s["key"] for s in ctx["body"]]
    assert keys == list(SECTIONS)  # fixture has every section ok
    assert ctx["appendix"] == []
    assert all(s["title"] == SECTIONS[s["key"]].title for s in ctx["body"])
    assert all(s["icon"] and s["source"] for s in ctx["body"])


def test_appendix_split_and_status_labels():
    sections = {
        "boris": {**FIXTURES["boris"]},
        "flood": {"key": "flood", "status": "gated", "data": None, "message": "Adresse nur straßengenau — …"},
        "noise": {"key": "noise", "status": "empty", "data": None, "message": "Unter Kartierungsschwelle"},
        "bergbau": {"key": "bergbau", "status": "error", "data": None, "message": "Timeout nach 20s"},
        "gfnp": {"key": "gfnp", "status": "loading", "data": None, "message": None},
        "denkmal": {"key": "denkmal", "status": "ok", "data": None, "message": None},  # ok but no data
    }
    ctx = build_report_context(_payload(sections=sections))
    assert [s["key"] for s in ctx["body"]] == ["boris"]
    app = {a["key"]: a for a in ctx["appendix"]}
    # every non-body registry section shows up, registry order
    assert [a["key"] for a in ctx["appendix"]] == [k for k in SECTIONS if k != "boris"]
    assert app["flood"]["status_label"].startswith("gesperrt")
    assert app["flood"]["message"].startswith("Adresse nur")
    assert app["noise"]["status_label"] == "kein Befund"
    assert app["bergbau"]["status_label"] == "Fehler"
    assert app["gfnp"]["status_label"] == "nicht geladen"
    assert app["denkmal"]["status_label"] == "kein Befund"
    assert app["oepnv"]["status_label"] == "nicht geladen"  # absent from payload
    assert app["oepnv"]["message"] in (None, "")


def test_unknown_section_key_rejected():
    with pytest.raises(ReportPayloadError) as ei:
        build_report_context(_payload(sections={"nope": {"status": "ok", "data": {}}}))
    assert "nope" in str(ei.value)


def test_envelope_without_status_rejected():
    with pytest.raises(ReportPayloadError) as ei:
        build_report_context(_payload(sections={"boris": {"data": {}}}))
    assert "boris" in str(ei.value)


@pytest.mark.parametrize("geocode", [None, {}, {"latitude": "x", "longitude": 7.0}, {"latitude": 51.0}])
def test_bad_geocode_rejected(geocode):
    with pytest.raises(ReportPayloadError):
        build_report_context(_payload(geocode=geocode))


@pytest.mark.parametrize("precision,label", [
    ("building", "hausnummerngenau"), ("street", "straßengenau"),
    ("coordinates", "Koordinaten"), ("city", "ortsgenau"), (None, "ortsgenau"),
])
def test_precision_label(precision, label):
    p = _payload(sections={})
    p["geocode"]["precision"] = precision
    assert build_report_context(p)["precision_label"] == label


def test_summary_rows_one_per_body_section_with_figures():
    ctx = build_report_context(_payload())
    rows = {r["key"]: r for r in ctx["summary"]}
    assert list(rows) == [s["key"] for s in ctx["body"]]
    assert rows["boris"]["figure"] == "670 €/m² (Stichtag 01.01.2025)"
    assert rows["boris_trend"]["figure"] == "2022: 670 → 2025: 670 €/m² (+0 %)"
    assert rows["flood"]["rating"] == "Gering" and rows["flood"]["rating_color"] == "green"
    assert rows["starkregen"]["rating"] == "Erhöht" and "30–50 cm" in rows["starkregen"]["figure"]
    assert rows["noise"]["figure"] == "Tag ab 70 dB(A) · Nacht ab 65 dB(A)"
    assert rows["bergbau"]["rating_color"] == "red" and "4 Hinweise" in rows["bergbau"]["figure"]
    assert rows["gfnp"]["figure"] == "Flächen für die örtlichen Hauptverkehrszüge"
    assert rows["schutzgebiete"]["figure"] == "4 Gebiete ≤ 500 m"
    assert rows["planning_essen"]["figure"] == "keine Verfahren"
    assert rows["planning_bochum"]["figure"] == "2 Verfahren"
    assert rows["denkmal"]["figure"] == "49 Bau-, 7 Bodendenkmäler ≤ 300 m"
    assert rows["amenities"]["figure"] == "Supermarkt 65 m · Schule 52 m · Arzt 95 m"
    assert rows["oepnv"]["figure"] == "keine Schiene ≤ 600 m · Essen Hbf 19 min"
    assert rows["zensus"]["figure"] == "1.572 EW (±250 m) · Ø Alter 47,6"
    assert rows["energie"]["figure"] == "PV 3.411 kWh/a · Erdwärme Gut · Prüfgebiet Wärmenetze"
    assert rows["breitband"]["figure"] == "FTTH > 95 % · 5G: Telekom, Vodafone, o2"
    assert rows["infrastruktur"]["figure"] == "0 Leitungen · 1 Sendemast · 1 Industrieanlage"
    assert rows["air_quality"]["figure"] == "NO₂ 18,8 · PM2.5 8,7 µg/m³ (2023) · aktuell Gut"
    assert rows["btw"]["figure"] == "CDU 29,6 % · SPD 21,1 %"
    assert rows["commute"]["figure"] == "Arbeit 1 25 min · Arbeit 2 10 min"
    # sections without a rating word get None and the neutral colour
    assert rows["boris"]["rating"] is None and rows["boris"]["rating_color"] == "gray"


@pytest.mark.parametrize("key", list(SECTIONS))
def test_summary_functions_never_raise(key):
    fn = builder.SUMMARY[key]
    for data in ({}, None, {"items": None, "areas": None, "parties": None}):
        rating, color, figure = builder.summarize(key, data)
        assert rating is None or isinstance(rating, str)
        assert isinstance(color, str)
        assert figure is None or isinstance(figure, str)
    assert fn is not None


def test_sources_deduped_in_order_plus_map_attribution():
    ctx = build_report_context(_payload())
    assert ctx["sources"] == list(dict.fromkeys(SECTIONS[k].source for k in SECTIONS))
    assert "basemap.de" in ctx["map_attribution"]


def test_context_has_no_listing_key():
    ctx = build_report_context(_payload())
    assert "listing" not in ctx
    assert ctx["generated_date"] and ctx["formatted_address"]


def test_slugify():
    assert slugify("Brückstraße 12, 45239 Essen, Deutschland") == "Brueckstrasse-12-45239-Essen-Deutschland"
    assert len(slugify("x" * 200)) <= 60
    assert slugify("   ") == "Standort"
