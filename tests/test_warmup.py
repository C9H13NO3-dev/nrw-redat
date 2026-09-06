"""redat/core/warmup.py — the numpy C-extension stack is imported once, in the main thread, before any
section worker thread can race to import it (live failure 2026-09-06: 26 concurrent /section threads on a
fresh process → `ImportError: cannot import name '__cpu_features__' from partially initialized module
numpy._core._multiarray_umath`, and every later import in that process kept failing)."""
import sys
import threading

from redat import app as appmod
from redat.core import warmup


def test_warm_geo_stack_imports_the_whole_stack_fully_initialised():
    names = warmup.warm_geo_stack()
    assert set(names) >= {"numpy", "pyproj", "shapely", "shapely.geometry", "geopandas"}
    for n in names:
        assert n in sys.modules, n
    # numpy is only usable once its C core finished initialising — this attribute is the one the live
    # traceback could not find on the half-initialised module.
    assert hasattr(sys.modules["numpy._core._multiarray_umath"], "__cpu_features__")


def test_create_app_warms_the_stack_synchronously_in_the_main_thread(monkeypatch):
    seen = []

    def spy():
        seen.append(threading.current_thread() is threading.main_thread())
        return ()
    monkeypatch.setattr(appmod, "warm_geo_stack", spy)
    monkeypatch.setattr(appmod, "chromium_available", lambda: False)
    appmod.create_app()          # no TestClient/lifespan: the warm-up must happen before serving starts
    assert seen == [True]
