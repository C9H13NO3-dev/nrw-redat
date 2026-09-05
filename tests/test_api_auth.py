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


def test_non_ascii_key_is_a_clean_401_not_a_500(monkeypatch):
    """secrets.compare_digest(str, str) raises TypeError on non-ASCII; must be a 401, not a 500.

    Starlette decodes header values as latin-1, so the byte 0xE4 ("ä") arrives as a valid latin-1
    header rather than being rejected client-side (an ASCII-encoded str value would fail before it
    ever left the test client) — passing raw bytes here reproduces exactly what a real client can send.
    """
    monkeypatch.setenv("REDAT_API_KEY", "s3cret"); reset_settings()
    c = _client()
    r = c.get("/api/v1/sections", headers={"X-Api-Key": "ä".encode("latin-1")})
    assert r.status_code == 401
