"""Hermetic defaults for every test: a fake Geoapify key, a tmp data dir, no API key."""
import pytest

import os, tempfile
# Module-level defaults so `import redat.app` at collection time (module-level `app = create_app()`)
# succeeds in a bare `pytest`; the autouse fixture still overrides per test.
os.environ.setdefault("GEOAPIFY_API_KEY", "test-key")
os.environ.setdefault("REDAT_DATA_DIR", tempfile.mkdtemp(prefix="redat-tests-"))


@pytest.fixture(autouse=True)
def _redat_env(monkeypatch, tmp_path):
    from redat import settings as s
    monkeypatch.setenv("GEOAPIFY_API_KEY", "test-key")
    monkeypatch.setenv("REDAT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("REDAT_API_KEY", raising=False)
    monkeypatch.delenv("REDAT_CACHE_TTL_S", raising=False)
    monkeypatch.delenv("REDAT_PUBLIC_URL", raising=False)
    s.reset_settings()
    yield
    s.reset_settings()
