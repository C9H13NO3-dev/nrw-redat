import json
import re
import pytest
from fastapi.testclient import TestClient

import redat.core.analyze as A
from redat.core.geocoding import GeocodeResult
from redat.settings import reset_settings

OK = GeocodeResult(formatted_address="Brückstraße 1, 45239 Essen", latitude=51.3878, longitude=7.0011, precision="building")


@pytest.fixture
def client():
    from redat.app import create_app
    with TestClient(create_app()) as c:
        yield c


def _config(html):
    m = re.search(r'<script type="application/json" id="analysis-config">(.*?)</script>', html, re.S)
    return json.loads(m.group(1))


def test_index_renders_manifest(client):
    r = client.get("/")
    assert r.status_code == 200 and "Standort-Analyse" in r.text
    cfg = _config(r.text)
    assert cfg["run"] is None and cfg["auto_run"] is False and [s["key"] for s in cfg["sections"]] == list(A.SECTIONS)
    assert 'id="card-noise"' in r.text and "Quellen" in r.text


def test_index_prefill_and_auto(client):
    r = client.get("/", params={"address": "Brückstraße 1, Essen", "plot_size_m2": 400, "auto": 1})
    cfg = _config(r.text)
    assert cfg["address"] == "Brückstraße 1, Essen" and cfg["plot_size_m2"] == 400.0 and cfg["auto_run"] is True
    assert _config(client.get("/", params={"auto": 1}).text)["auto_run"] is False  # no address → nothing to run


def test_stored_run_page(client):
    payload = {"address": "Brückstraße 1, Essen", "geocode": A.geocode_dict("Brückstraße 1, Essen", OK),
               "plot_size_m2": None, "living_space_m2": None,
               "sections": {"noise": {"key": "noise", "status": "ok", "data": {"below_threshold": True}}}}
    rid = client.post("/api/v1/runs", json=payload).json()["run_id"]
    r = client.get(f"/a/{rid}")
    assert r.status_code == 200
    cfg = _config(r.text)
    assert cfg["run"]["run_id"] == rid and cfg["run"]["sections"]["noise"]["status"] == "ok"
    assert cfg["run"]["geocode"]["latitude"] == 51.3878 and cfg["address"] == "Brückstraße 1, Essen"


def test_stored_run_404(client):
    r = client.get("/a/zzzzzzzzzz")
    assert r.status_code == 404 and "Analyse nicht gefunden" in r.text


def test_quellen(client):
    r = client.get("/quellen")
    assert r.status_code == 200 and "BORIS NRW" in r.text and "Bundesnetzagentur" in r.text and "Lärm" in r.text


def test_pages_never_need_api_key(monkeypatch):
    monkeypatch.setenv("REDAT_API_KEY", "k"); reset_settings()
    from redat.app import create_app
    with TestClient(create_app()) as c:
        assert c.get("/").status_code == 200 and c.get("/quellen").status_code == 200
