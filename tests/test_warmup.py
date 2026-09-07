"""redat/core/warmup.py — the numpy C-extension stack is imported once, in the main thread, before any
section worker thread can race to import it (live failure 2026-09-06: 26 concurrent /section threads on a
fresh process → `ImportError: cannot import name '__cpu_features__' from partially initialized module
numpy._core._multiarray_umath`, and every later import in that process kept failing)."""
import importlib
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
    order = []

    def spy():
        seen.append(threading.current_thread() is threading.main_thread())
        order.append("geo_stack")
        return ()

    def grids_spy():
        seen.append(threading.current_thread() is threading.main_thread())
        order.append("grids")
        return ()
    monkeypatch.setattr(appmod, "warm_geo_stack", spy)
    monkeypatch.setattr(appmod, "warm_grids", grids_spy)
    monkeypatch.setattr(appmod, "chromium_available", lambda: False)
    appmod.create_app()          # no TestClient/lifespan: the warm-up must happen before serving starts
    assert seen == [True, True]
    assert order == ["geo_stack", "grids"]


def test_warm_grids_returns_the_module_names(monkeypatch):
    for name in warmup.GRID_MODULES:
        mod = importlib.import_module(f"redat.sources.{name}")
        if name == "bergrechte":
            monkeypatch.setattr(mod, "_geoms", lambda: [])
            monkeypatch.setattr(mod, "_tree", lambda: None)
        else:
            monkeypatch.setattr(mod, "_load", lambda: None)
    names = warmup.warm_grids()
    assert names == warmup.GRID_MODULES


def test_warm_grids_never_raises_when_grid_files_are_missing(monkeypatch, tmp_path):
    """A missing grid file is `None`, not an error — warm_grids() must still return cleanly."""
    missing = tmp_path / "missing.does-not-exist"
    for name in warmup.GRID_MODULES:
        mod = importlib.import_module(f"redat.sources.{name}")
        monkeypatch.setattr(mod, "GRID_PATH", missing)
        for cache_fn in ("_load", "_geoms", "_tree"):
            if hasattr(mod, cache_fn):
                getattr(mod, cache_fn).cache_clear()
    try:
        names = warmup.warm_grids()  # must not raise
        assert names == warmup.GRID_MODULES  # _load()/_geoms() gracefully return None on a missing file
    finally:
        for name in warmup.GRID_MODULES:
            mod = importlib.import_module(f"redat.sources.{name}")
            for cache_fn in ("_load", "_geoms", "_tree"):
                if hasattr(mod, cache_fn):
                    getattr(mod, cache_fn).cache_clear()


def test_warm_grids_survives_an_unexpected_exception_in_one_module(monkeypatch):
    """Even a genuinely broken loader (not just a missing file) must not stop the rest from warming."""
    mod = importlib.import_module("redat.sources.zensus")
    monkeypatch.setattr(mod, "_load", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    names = warmup.warm_grids()
    assert "zensus" not in names
    assert set(warmup.GRID_MODULES) - {"zensus"} <= set(names)


def test_warm_grids_loads_real_grids():
    """Smoke test: reads the committed grid files for real (hermetic — they ship in the repo).

    Clears every module's cache first — otherwise an earlier test in this file may already have
    warmed them (all are `lru_cache`d) and this would pass vacuously without touching disk.
    """
    for name in warmup.GRID_MODULES:
        mod = importlib.import_module(f"redat.sources.{name}")
        for cache_fn in ("_load", "_geoms", "_tree"):
            if hasattr(mod, cache_fn):
                getattr(mod, cache_fn).cache_clear()
    names = warmup.warm_grids()
    assert names == warmup.GRID_MODULES
    # Prove it actually parsed the committed files, not just that the function returned.
    assert importlib.import_module("redat.sources.zensus")._load() is not None
    # Fix 1 and fix 4 must compose: warming bergrechte via _geoms()+_tree() must still release the
    # raw GeoJSON dict, and the tree must be built from the (still-cached) parsed geometries.
    bergrechte = importlib.import_module("redat.sources.bergrechte")
    assert bergrechte._load.cache_info().currsize == 0
    assert bergrechte._tree() is not None
