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


def test_lifespan_warms_chromium_probe_off_the_event_loop(monkeypatch):
    """The sync Playwright API raises inside a running asyncio loop; a probe run there would
    lru_cache `False` for the whole process (seen live: /healthz chromium=false after the M6 warm-up)."""
    import asyncio
    seen = []

    def fake_probe():
        try:
            asyncio.get_running_loop()
            seen.append("on-loop")
        except RuntimeError:
            seen.append("worker")
        return True

    monkeypatch.setattr(appmod, "chromium_available", fake_probe)
    with TestClient(appmod.create_app()) as client:
        assert client.get("/healthz").json()["chromium"] is True
    assert seen and seen[0] == "worker"


def test_docs_served():
    client = TestClient(appmod.create_app())
    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").json()["info"]["version"] == redat.__version__


def test_healthz_reports_cache_stats(monkeypatch):
    monkeypatch.setattr(appmod, "chromium_available", lambda: False)
    with TestClient(appmod.create_app()) as client:
        body = client.get("/healthz").json()
    assert body["cache"] == {"entries": 0, "bytes": 0, "expired": 0}


def test_sweep_cache_purges_expired_and_reports(monkeypatch):
    import redat.store.cache as m
    from redat.store.cache import SectionCache
    now = [1e6]; monkeypatch.setattr(m.time, "time", lambda: now[0])
    c = SectionCache(10)
    c.put(c.key("noise", 1, 1, None, False), {"key": "noise", "status": "ok", "data": {}})
    c.put(c.key("noise", 2, 2, None, False), {"key": "noise", "status": "ok", "data": {}})
    now[0] += 11
    c.put(c.key("noise", 3, 3, None, False), {"key": "noise", "status": "ok", "data": {}})
    st = appmod.sweep_cache(c)
    assert st["entries"] == 1 and st["expired"] == 0


def test_cache_survives_an_app_restart(monkeypatch):
    monkeypatch.setattr(appmod, "chromium_available", lambda: False)
    import redat.core.analyze as A
    env = {"key": "noise", "tier": "area", "status": "ok", "data": {}, "message": None, "source": "x", "took_ms": 1}
    monkeypatch.setattr(A, "run_section", lambda key, ctx, precision=None, force=False: env)
    with TestClient(appmod.create_app()) as c1:
        assert "cached" not in c1.get("/api/v1/section/noise", params={"lat": 51.38, "lon": 7.0}).json()
    with TestClient(appmod.create_app()) as c2:          # same REDAT_DATA_DIR, new process state
        assert c2.get("/api/v1/section/noise", params={"lat": 51.38, "lon": 7.0}).json()["cached"] is True
