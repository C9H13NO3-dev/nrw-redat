"""FastAPI factory: website + /api/v1 + static files + /healthz (spec §3, §5.3)."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path

import anyio
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from redat import __version__
from redat.settings import get_settings

log = logging.getLogger("redat")
STATIC_DIR = Path(__file__).resolve().parent / "static"

DESCRIPTION = (
    "NRW-REDAT bündelt öffentliche Geodaten (BORIS, Hochwasser, Lärm, Luftqualität, ÖPNV, …) "
    "zu einer Standortanalyse für Essen und Bochum. Jede Karte ist eine eigene Sektion mit "
    "festem Envelope `{key, tier, status, data, message, source, took_ms}`."
)


@lru_cache(maxsize=1)
def chromium_available() -> bool:
    """One Playwright launch probe per process — /healthz reports it as `chromium`."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch()
            b.close()
        return True
    except Exception as e:  # noqa: BLE001 — any failure means "no PDF renderer"
        log.warning("Chromium probe failed: %s", e)
        return False


def sources_loaded() -> int:
    from redat.core.sections import SECTIONS
    return len(SECTIONS)


CACHE_SWEEP_INTERVAL_S = 3600


def sweep_cache(cache) -> dict:
    """One maintenance pass: drop expired rows (bounds are enforced on every write already) and report."""
    purged = cache.purge_expired()
    st = cache.stats()
    log.info("cache sweep: purged %d expired, %d entries / %.1f MB live (%s)", purged, st["entries"],
             st["bytes"] / 1e6, ", ".join(f"{k}={v}" for k, v in sorted(st["by_section"].items())) or "empty")
    return st


async def _cache_maintenance(cache) -> None:
    """Hourly sweep off the event loop, for the life of the process (cancelled in lifespan teardown)."""
    while True:
        try:
            await anyio.to_thread.run_sync(sweep_cache, cache)
        except Exception as e:  # noqa: BLE001 - maintenance must never take the app down
            log.warning("cache sweep failed: %s", e)
        await asyncio.sleep(CACHE_SWEEP_INTERVAL_S)


def create_app() -> FastAPI:
    settings = get_settings()  # raises SettingsError → uvicorn exits: fail loudly
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings.data_dir.mkdir(parents=True, exist_ok=True)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        from redat.store.runs import RunStore
        _app.state.runs = RunStore(settings.db_path)
        _app.state.runs.init()
        sweeper = asyncio.create_task(_cache_maintenance(_app.state.cache))
        # Warm the (lru_cache'd) Playwright probe so the first /healthz is cheap. It MUST run off the
        # event loop: the sync Playwright API refuses to start inside a running asyncio loop, and the
        # cache would pin that failure as `chromium: false` for the life of the process.
        await anyio.to_thread.run_sync(chromium_available)
        yield
        sweeper.cancel()
        _app.state.cache.close()

    app = FastAPI(title="NRW-REDAT", version=__version__, description=DESCRIPTION, lifespan=lifespan)
    # Built here, not in lifespan: every route (and /healthz) needs it, and it must exist for callers that
    # construct the app without running the lifespan (tests). The sweeper task is lifespan-bound.
    from redat.core.analyze import build_cache
    app.state.cache = build_cache(settings)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/healthz", include_in_schema=False)
    def healthz(request: Request):
        st = request.app.state.cache.stats()
        return {"status": "ok", "version": __version__, "chromium": chromium_available(),
                "sources_loaded": sources_loaded(),
                "cache": {"entries": st["entries"], "bytes": st["bytes"], "expired": st["expired"]}}

    from redat.api.v1 import router as api_router
    from redat.web.pages import router as web_router
    app.include_router(api_router)
    app.include_router(web_router)
    return app


app = create_app()
