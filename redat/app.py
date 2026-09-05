"""FastAPI factory: website + /api/v1 + static files + /healthz (spec §3, §5.3)."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI
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


def create_app() -> FastAPI:
    settings = get_settings()  # raises SettingsError → uvicorn exits: fail loudly
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings.data_dir.mkdir(parents=True, exist_ok=True)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        from redat.store.runs import RunStore
        _app.state.runs = RunStore(settings.db_path)
        _app.state.runs.init()
        yield

    app = FastAPI(title="NRW-REDAT", version=__version__, description=DESCRIPTION, lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/healthz", include_in_schema=False)
    def healthz():
        return {"status": "ok", "version": __version__, "chromium": chromium_available(),
                "sources_loaded": sources_loaded()}

    from redat.api.v1 import router as api_router
    from redat.web.pages import router as web_router
    app.include_router(api_router)
    app.include_router(web_router)
    return app


app = create_app()
