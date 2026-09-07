"""render_pdf: the three figure renderers run concurrently and a raising renderer degrades to None."""
import threading
import time

import pytest

from redat.report import service


def _ctx(body_keys):
    return {
        "body": [{"key": k, "data": {}} for k in body_keys],
        "lat": 51.45, "lon": 7.01,
        "formatted_address": "Teststraße 1", "address": "Teststraße 1",
        "generated_at": "01.01.2026 00:00", "generated_date": "2026-01-01",
        "noise_maps": None, "history_maps": None, "climate_maps": None, "regionalplan_map": None, "boris_trend_svg": None,
    }


@pytest.fixture(autouse=True)
def _stub_html_and_pdf(monkeypatch):
    monkeypatch.setattr(service, "render_report_html", lambda ctx: "<html></html>")
    monkeypatch.setattr(service, "html_to_pdf", lambda html, **kw: b"%PDF-1.4 fake")


def test_figure_renderers_run_concurrently_and_populate_ctx(monkeypatch):
    monkeypatch.setattr(service, "build_report_context", lambda payload: _ctx(["noise", "flurstueck", "zensus", "gfnp"]))

    barrier = threading.Barrier(4, timeout=5)

    def make_renderer(tag):
        def renderer(lat, lon):
            # Every renderer must be mid-flight at the same time — proves they run
            # concurrently rather than sequentially. Thread-safe: no ordering asserted.
            barrier.wait()
            return {"tag": tag, "thread": threading.current_thread().name}
        return renderer

    monkeypatch.setattr(service, "render_noise_maps", make_renderer("noise"))
    monkeypatch.setattr(service, "render_history_maps", make_renderer("history"))
    monkeypatch.setattr(service, "render_climate_maps", make_renderer("climate"))
    monkeypatch.setattr(service, "render_regionalplan_map", make_renderer("regionalplan"))

    pdf, ctx = service.render_pdf({})

    assert pdf == b"%PDF-1.4 fake"
    assert ctx["noise_maps"]["tag"] == "noise"
    assert ctx["history_maps"]["tag"] == "history"
    assert ctx["climate_maps"]["tag"] == "climate"
    assert ctx["regionalplan_map"]["tag"] == "regionalplan"


def test_a_raising_renderer_degrades_to_none_without_breaking_the_pdf(monkeypatch):
    monkeypatch.setattr(service, "build_report_context", lambda payload: _ctx(["noise", "flurstueck", "zensus"]))
    monkeypatch.setattr(service, "render_noise_maps", lambda lat, lon: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(service, "render_history_maps", lambda lat, lon: {"tag": "history"})
    monkeypatch.setattr(service, "render_climate_maps", lambda lat, lon: {"tag": "climate"})
    monkeypatch.setattr(service, "render_regionalplan_map", lambda lat, lon: {"tag": "regionalplan"})

    pdf, ctx = service.render_pdf({})

    assert pdf == b"%PDF-1.4 fake"
    assert ctx["noise_maps"] is None
    assert ctx["history_maps"] == {"tag": "history"}
    assert ctx["climate_maps"] == {"tag": "climate"}


def test_no_applicable_sections_skips_the_thread_pool_entirely(monkeypatch):
    monkeypatch.setattr(service, "build_report_context", lambda payload: _ctx([]))
    called = []
    monkeypatch.setattr(service, "render_noise_maps", lambda lat, lon: called.append("noise"))
    monkeypatch.setattr(service, "render_history_maps", lambda lat, lon: called.append("history"))
    monkeypatch.setattr(service, "render_climate_maps", lambda lat, lon: called.append("climate"))
    monkeypatch.setattr(service, "render_regionalplan_map", lambda lat, lon: called.append("regionalplan"))

    pdf, ctx = service.render_pdf({})

    assert called == []
    assert ctx["noise_maps"] is None and ctx["history_maps"] is None and ctx["climate_maps"] is None
    assert ctx["regionalplan_map"] is None
