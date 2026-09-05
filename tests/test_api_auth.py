from fastapi.testclient import TestClient
from redat.settings import reset_settings


def _client():
    from redat.app import create_app
    return TestClient(create_app())


def test_api_open_when_no_key():
    r = _client().get("/api/v1/sections")
    assert r.status_code == 200


def test_api_requires_key_when_set(monkeypatch):
    monkeypatch.setenv("REDAT_API_KEY", "s3cret"); reset_settings()
    c = _client()
    assert c.get("/api/v1/sections").status_code == 401
    assert c.get("/api/v1/sections", headers={"X-Api-Key": "wrong"}).status_code == 401
    assert c.get("/api/v1/sections", headers={"X-Api-Key": "s3cret"}).status_code == 200
    assert c.get("/healthz").status_code == 200  # never gated
    assert c.get("/docs").status_code == 200
