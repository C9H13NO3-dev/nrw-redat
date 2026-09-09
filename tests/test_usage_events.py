"""Usage events are recorded where the spec says, with the user attached."""
import pytest
from fastapi.testclient import TestClient

import redat.api.v1 as V
import redat.core.analyze as A
from redat.core.geocoding import GeocodeResult
from tests.helpers_auth import login

OK = GeocodeResult(formatted_address="Am Käferberg 12, 53127 Bonn", latitude=50.716, longitude=7.0748, precision="house")


def _env(key, status="ok"):
    return {"key": key, "tier": "area", "status": status, "data": {} if status == "ok" else None, "message": None, "source": "x", "took_ms": 1}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(A, "geocode_with_precision", lambda a: OK)
    monkeypatch.setattr(A, "run_section", lambda key, ctx, precision=None, force=False: _env(key))
    monkeypatch.setattr(V, "render_pdf", lambda payload: (b"%PDF-1.4 fake", {"formatted_address": "x", "address": payload["address"], "generated_date": "2026-09-09"}))
    from redat.app import create_app
    with TestClient(create_app()) as c:
        yield c


def _payload():
    return {"address": "Am Käferberg 12, Bonn", "geocode": A.geocode_dict("Am Käferberg 12, Bonn", OK), "plot_size_m2": None,
            "living_space_m2": None, "sections": {"noise": _env("noise"), "boris": _env("boris", "error"), "zensus": _env("zensus", "empty")}}


def test_saving_a_run_records_analyze_with_user_and_counts(client):
    u = login(client, username="anna")
    r = client.post("/api/v1/runs", json=_payload())
    rid = r.json()["run_id"]
    assert client.app.state.runs.get(rid)["user_id"] == u["id"]
    ev = client.app.state.events.recent(1)[0]
    assert ev["kind"] == "analyze" and ev["username"] == "anna" and ev["run_id"] == rid and ev["via"] == "session"
    assert ev["address"] == "Am Käferberg 12, Bonn" and abs(ev["lat"] - 50.716) < 1e-6
    assert ev["extra"] == {"ok": 1, "error": 1, "empty": 1, "gated": 0}


def test_machine_analyze_records_too(client, monkeypatch):
    from redat import settings as s
    monkeypatch.setenv("REDAT_API_KEY", "k"); s.reset_settings()
    r = client.get("/api/v1/analyze", params={"address": "Am Käferberg 12, Bonn", "save": 1}, headers={"X-Api-Key": "k"})
    ev = client.app.state.events.recent(1)[0]
    assert ev["kind"] == "analyze" and ev["via"] == "api_key" and ev["user_id"] is None and ev["run_id"] == r.json()["run_id"]


def test_pdf_and_permalink_views_are_recorded(client):
    login(client, username="bob")
    rid = client.post("/api/v1/runs", json=_payload()).json()["run_id"]
    assert client.post("/api/v1/report", json=_payload()).status_code == 200
    assert client.app.state.events.recent(1)[0]["kind"] == "pdf"
    client.cookies.clear()                                   # anonymous visitor with the link
    assert client.get(f"/a/{rid}").status_code == 200
    ev = client.app.state.events.recent(1)[0]
    assert ev["kind"] == "permalink_view" and ev["user_id"] is None and ev["run_id"] == rid and "Käferberg" in ev["address"]
    assert client.get(f"/api/v1/run/{rid}/report.pdf").status_code == 200
    assert client.app.state.events.recent(1)[0]["kind"] == "pdf"
