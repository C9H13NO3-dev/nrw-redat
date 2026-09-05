import pytest
from fastapi.testclient import TestClient

import redat.api.v1 as V
import redat.core.analyze as A
from redat.core.geocoding import GeocodeResult
from redat.report.builder import ReportPayloadError
from redat.report.pdf import RendererUnavailable

OK = GeocodeResult(formatted_address="Brückstraße 1, 45239 Essen", latitude=51.3878, longitude=7.0011, precision="house")


def _env(key, status="ok"):
    return {"key": key, "tier": "area", "status": status, "data": {} if status == "ok" else None,
            "message": None, "source": "x", "took_ms": 1}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(A, "geocode_with_precision", lambda a: OK if a != "nirgendwo" else None)
    monkeypatch.setattr(A, "run_section", lambda key, ctx, precision=None, force=False: _env(key))
    monkeypatch.setattr(V, "render_pdf", lambda payload: (b"%PDF-1.4 fake", {
        "formatted_address": payload["geocode"]["formatted_address"], "address": payload["address"],
        "generated_date": "2026-09-05"}))
    from redat.app import create_app
    with TestClient(create_app()) as c:
        yield c


def _payload():
    return {"address": "Brückstraße 1, Essen", "geocode": A.geocode_dict("Brückstraße 1, Essen", OK),
            "plot_size_m2": 400, "living_space_m2": None, "sections": {"noise": _env("noise")}}


def test_sections_manifest(client):
    r = client.get("/api/v1/sections"); assert r.status_code == 200
    first = r.json()[0]
    assert set(first) == {"key", "title", "icon", "tier", "timeout_s", "source"}
    assert [s["key"] for s in r.json()] == list(A.SECTIONS)


def test_geocode(client):
    r = client.get("/api/v1/geocode", params={"address": "Brückstraße 1, Essen"})
    assert r.status_code == 200 and r.json()["precision"] == "house" and r.json()["address"] == "Brückstraße 1, Essen"
    assert client.get("/api/v1/geocode", params={"address": "nirgendwo"}).status_code == 422


def test_autocomplete(client, monkeypatch):
    monkeypatch.setattr(A, "autocomplete_address", lambda text, limit=8: [{"formatted": text, "lat": 1, "lon": 2}])   # call site moved into analyze (cached)
    r = client.get("/api/v1/autocomplete", params={"text": "Brück", "limit": 3})
    assert r.status_code == 200 and r.json() == {"results": [{"formatted": "Brück", "lat": 1, "lon": 2}]}


def test_section_route(client):
    r = client.get("/api/v1/section/noise", params={"lat": 51.38, "lon": 7.0})
    assert r.status_code == 200 and r.json()["key"] == "noise"
    assert client.get("/api/v1/section/nope", params={"lat": 1, "lon": 2}).status_code == 404
    r = client.get("/api/v1/section/commute", params={"lat": 1, "lon": 2, "destinations": "nope"})
    assert r.status_code == 422


def test_section_route_consults_cache(client, monkeypatch):
    calls = []
    monkeypatch.setattr(A, "run_section", lambda key, ctx, precision=None, force=False: (calls.append(key), _env(key))[1])

    r1 = client.get("/api/v1/section/noise", params={"lat": 51.38, "lon": 7.0})
    assert r1.status_code == 200 and "cached" not in r1.json()
    r2 = client.get("/api/v1/section/noise", params={"lat": 51.38, "lon": 7.0})
    assert r2.status_code == 200 and r2.json()["cached"] is True
    assert calls == ["noise"]  # second call was served from cache, run_section was not called again


def test_section_route_with_destinations_is_never_cached(client, monkeypatch):
    calls = []
    monkeypatch.setattr(A, "run_section", lambda key, ctx, precision=None, force=False: (calls.append(key), _env(key))[1])
    dests = '[{"name": "Arbeit", "lat": 51.45, "lon": 7.01}]'

    client.get("/api/v1/section/commute", params={"lat": 51.38, "lon": 7.0, "destinations": dests})
    r2 = client.get("/api/v1/section/commute", params={"lat": 51.38, "lon": 7.0, "destinations": dests})
    assert "cached" not in r2.json()
    assert calls == ["commute", "commute"]  # both calls actually ran, cache was bypassed


def test_section_route_error_envelope_is_never_cached(client, monkeypatch):
    calls = []

    def fake(key, ctx, precision=None, force=False):
        calls.append(key)
        return _env(key, status="error")

    monkeypatch.setattr(A, "run_section", fake)

    client.get("/api/v1/section/noise", params={"lat": 51.38, "lon": 7.0})
    r2 = client.get("/api/v1/section/noise", params={"lat": 51.38, "lon": 7.0})
    assert "cached" not in r2.json()
    assert calls == ["noise", "noise"]


def test_analyze_and_save(client):
    r = client.get("/api/v1/analyze", params={"address": "Brückstraße 1, Essen", "plot_size_m2": 400})
    assert r.status_code == 200
    body = r.json()
    assert set(body["sections"]) == set(A.SECTIONS) and body["geocode"]["latitude"] == 51.3878
    assert "run_id" not in body
    r = client.get("/api/v1/analyze", params={"address": "Brückstraße 1, Essen", "save": 1})
    body = r.json()
    assert len(body["run_id"]) == 10 and body["permalink"].endswith(f"/a/{body['run_id']}")
    got = client.get(f"/api/v1/run/{body['run_id']}").json()
    assert got["address"] == "Brückstraße 1, Essen" and got["created_at"] and set(got["sections"]) == set(A.SECTIONS)
    assert got["plot_size_m2"] is None and got["geocode"]["precision"] == "house"


def test_analyze_unresolvable(client):
    assert client.get("/api/v1/analyze", params={"address": "nirgendwo"}).status_code == 422


def test_post_runs_and_get(client):
    r = client.post("/api/v1/runs", json=_payload())
    assert r.status_code == 200 and r.json()["permalink"].endswith("/a/" + r.json()["run_id"])
    assert client.get("/api/v1/run/zzzzzzzzzz").status_code == 404
    bad = _payload(); bad["sections"] = {"unknown_key": _env("unknown_key")}
    assert client.post("/api/v1/runs", json=bad).status_code == 422
    assert client.post("/api/v1/runs", json=[1, 2]).status_code == 422


def test_report_post(client):
    r = client.post("/api/v1/report", json=_payload())
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert r.headers["content-disposition"] == 'attachment; filename="Standortanalyse_Brueckstrasse-1-45239-Essen_2026-09-05.pdf"'
    assert "x-dossier-document-id" not in {k.lower() for k in r.headers}


def test_report_post_errors(client, monkeypatch):
    assert client.post("/api/v1/report", json={"address": "x"}).status_code == 422

    def boom(payload): raise RendererUnavailable("no chromium")
    monkeypatch.setattr(V, "render_pdf", boom)
    r = client.post("/api/v1/report", json=_payload())
    assert r.status_code == 503 and r.json()["detail"] == "PDF-Renderer nicht verfügbar"


def test_report_get_forces_and_renders(client, monkeypatch):
    seen = {}

    def fake_run_section(key, ctx, precision=None, force=False):
        seen["force"] = force
        return _env(key)
    monkeypatch.setattr(A, "run_section", fake_run_section)
    r = client.get("/api/v1/report", params={"address": "Brückstraße 1, Essen"})
    assert r.status_code == 200 and r.content.startswith(b"%PDF") and seen["force"] is True


def test_run_report_pdf(client):
    rid = client.post("/api/v1/runs", json=_payload()).json()["run_id"]
    r = client.get(f"/api/v1/run/{rid}/report.pdf")
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert client.get("/api/v1/run/zzzzzzzzzz/report.pdf").status_code == 404


def test_fresh_param_bypasses_cache_on_section_and_analyze(client, monkeypatch):
    calls = []
    monkeypatch.setattr(A, "run_section", lambda key, ctx, precision=None, force=False: (calls.append(key), _env(key))[1])
    client.get("/api/v1/section/noise", params={"lat": 51.38, "lon": 7.0})
    r = client.get("/api/v1/section/noise", params={"lat": 51.38, "lon": 7.0, "fresh": 1})
    assert "cached" not in r.json() and calls == ["noise", "noise"]
    assert client.get("/api/v1/section/noise", params={"lat": 51.38, "lon": 7.0}).json()["cached"] is True
    calls.clear()
    client.get("/api/v1/analyze", params={"address": "Brückstraße 1, Essen"})
    r = client.get("/api/v1/analyze", params={"address": "Brückstraße 1, Essen", "fresh": 1})
    assert all("cached" not in env for env in r.json()["sections"].values())
    assert len(calls) == 2 * len(A.SECTIONS)


def test_analyze_geocodes_once_per_address(client, monkeypatch):
    calls = []
    monkeypatch.setattr(A, "geocode_with_precision", lambda a: (calls.append(a), OK)[1])
    client.get("/api/v1/analyze", params={"address": "Brückstraße 1, Essen"})
    client.get("/api/v1/analyze", params={"address": "brückstraße 1,  essen"})
    client.get("/api/v1/geocode", params={"address": "Brückstraße 1, Essen"})
    assert calls == ["Brückstraße 1, Essen"]


def test_autocomplete_route_is_cached(client, monkeypatch):
    calls = []
    monkeypatch.setattr(A, "autocomplete_address", lambda text, limit=8: (calls.append(text), [{"formatted": "Brückstraße"}])[1])
    for _ in range(2):
        r = client.get("/api/v1/autocomplete", params={"text": "Brück", "limit": 8})
        assert r.json() == {"results": [{"formatted": "Brückstraße"}]}
    assert calls == ["Brück"]
