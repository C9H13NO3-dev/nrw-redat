"""Render tests for the report templates: every partial on its live fixture and on an empty dict."""
import html as htmlmod
import json
from pathlib import Path

import pytest

from redat.core.sections import SECTIONS
from redat.report.builder import build_report_context
from redat.report.noise_map import LEGEND_BANDS
from redat.report.render import render_report_html, render_section_html
from redat.report.svg import boris_trend_svg

FIXTURES = json.loads((Path(__file__).parent / "fixtures" / "report_envelopes.json").read_text())

PAYLOAD = {
    "address": "Brückstraße 12, 45239 Essen",
    "geocode": {"formatted_address": "Brückstraße 12, 45239 Essen, Deutschland",
                "latitude": 51.3885, "longitude": 7.0035, "precision": "building"},
    "plot_size_m2": 450, "living_space_m2": 140, "sections": FIXTURES,
}

EXTRA = {"plot_size_m2": 450, "living_space_m2": 140, "noise_maps": None, "boris_trend_svg": None}


@pytest.mark.parametrize("key", list(SECTIONS))
def test_partial_renders_fixture(key):
    html = render_section_html(key, FIXTURES[key]["data"], **EXTRA)
    assert html.strip()
    assert "None" not in html.replace("Nonebank", ""), f"{key}: a Python None leaked into the HTML"


@pytest.mark.parametrize("key", list(SECTIONS))
def test_partial_tolerates_empty_data(key):
    render_section_html(key, {}, **EXTRA)


def test_fixture_content_is_present():
    checks = {
        "boris": ["670 €/m²", "Stichtag 01.01.2025"],
        "flood": ["HQ100", "180 m"],
        "starkregen": ["30–50 cm", "Extremereignis"],
        "noise": ["Straße", "70 dB(A)"],
        "bergbau": ["Verlassene Tagesöffnungen", "500 m-Planquadrat"],
        "gfnp": ["Flächen für die örtlichen Hauptverkehrszüge"],
        "schutzgebiete": ["LSG-Weinberg", "180 m"],
        "planning_bochum": ["Gestaltungssatzung Werden"],
        "denkmal": ["Wohnhaus Effmann", "Untere Denkmalbehörde Essen"],
        "amenities": ["EDEKA Diekmann", "65 m"],
        "oepnv": ["Werdener Markt", "SB19", "Essen Hbf"],
        "zensus": ["1.572", "vor 1919"],
        "energie": ["3.411", "Prüfgebiet Wärmenetze", "2,5 – 2,9"],
        "breitband": ["> 95 %", "5G-Roaming"],
        "infrastruktur": ["Medienhaus Ruhr GmbH", "Sendemast", "Seveso"],
        "air_quality": ["Essen Abteistraße", "18,8", "Sensor.Community"],
        "btw": ["Essen III", "CDU", "29,6 %"],
        "commute": ["Arbeit 1", "25 Min"],
    }
    for key, needles in checks.items():
        html = htmlmod.unescape(render_section_html(key, FIXTURES[key]["data"], **EXTRA))
        for n in needles:
            assert n in html, f"{key}: expected {n!r} in rendered HTML"


def test_full_report_renders_with_maps_and_svg():
    ctx = build_report_context(PAYLOAD)
    ctx["noise_maps"] = {"day": "AAAA", "night": None, "legend": LEGEND_BANDS, "attribution": "© test", "error": "Nacht fehlt"}
    ctx["boris_trend_svg"] = boris_trend_svg(FIXTURES["boris_trend"]["data"]["history"])
    html = htmlmod.unescape(render_report_html(ctx))
    for s in SECTIONS.values():
        assert s.title in html
    assert "data:image/png;base64,AAAA" in html
    assert "Karte nicht verfügbar" in html
    assert "<svg" in html
    assert "Zusammenfassung" in html and "Quellen" in html
    assert "Anhang" not in html  # everything ok → no appendix


def test_full_report_appendix():
    sections = {"boris": FIXTURES["boris"], "flood": {"key": "flood", "status": "gated", "data": None, "message": "nur ortsgenau"}}
    ctx = build_report_context({**PAYLOAD, "sections": sections})
    html = render_report_html(ctx)
    assert "Anhang" in html and "gesperrt" in html and "nur ortsgenau" in html
    assert "NRW-REDAT" in html and "House Hunter" not in html
