from fastapi.testclient import TestClient

import redat
from redat import app as appmod


def test_healthz_is_open_and_reports_version(monkeypatch):
    monkeypatch.setattr(appmod, "chromium_available", lambda: False)
    client = TestClient(appmod.create_app())
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["version"] == redat.__version__
    assert body["chromium"] is False and isinstance(body["sources_loaded"], int)


def test_healthz_ignores_api_key(monkeypatch):
    monkeypatch.setenv("REDAT_API_KEY", "secret")
    from redat import settings as s
    s.reset_settings()
    monkeypatch.setattr(appmod, "chromium_available", lambda: True)
    client = TestClient(appmod.create_app())
    assert client.get("/healthz").status_code == 200


def test_docs_served():
    client = TestClient(appmod.create_app())
    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").json()["info"]["version"] == redat.__version__
