"""REDAT public API (spec §5). Everything under /api/v1, all behind the optional API key."""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool

from redat.api.auth import require_api_key
from redat.core import analyze as A
from redat.core.sections import SECTIONS, Ctx, manifest
from redat.report.builder import ReportPayloadError, build_report_context
from redat.report.pdf import RendererUnavailable
from redat.report.service import pdf_response, render_pdf
from redat.settings import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_api_key)])


def _destinations(raw: Optional[str]):
    try:
        return A.parse_destinations(raw)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


def _permalink(run_id: str) -> str:
    return f"{get_settings().public_url}/a/{run_id}"


@router.get("/sections")
def api_sections():
    return manifest()


@router.get("/geocode")
def api_geocode(request: Request, address: str):
    return A.geocode_dict(address, A.geocode_or_raise(address, cache=request.app.state.cache))


@router.get("/autocomplete")
def api_autocomplete(request: Request, text: str, limit: int = 8):
    return {"results": A.autocomplete_cached(text, limit, cache=request.app.state.cache)}


@router.get("/section/{key}")
def api_section(request: Request, key: str, lat: float, lon: float, precision: Optional[str] = None,
                plot_size_m2: Optional[float] = None, force: bool = False, destinations: Optional[str] = None,
                fresh: bool = False):
    """`force` lifts the parcel gate; `fresh` skips the cache read and re-runs the card (result replaces the cached one)."""
    if key not in SECTIONS:
        raise HTTPException(status_code=404, detail=f"Unbekannte Sektion: {key}")
    ctx = Ctx(lat=lat, lon=lon, plot_size_m2=plot_size_m2, destinations=_destinations(destinations))
    return A.cached_section(key, ctx, precision=precision, force=force, cache=request.app.state.cache, fresh=fresh)


def _analyze_sync(request: Request, address: str, plot_size_m2, force: bool, destinations, fresh: bool = False) -> dict:
    cache = request.app.state.cache
    g = A.geocode_or_raise(address, cache=cache)
    sections = A.run_all(lat=g.latitude, lon=g.longitude, precision=g.precision, plot_size_m2=plot_size_m2,
                         force=force, destinations=destinations, cache=cache, fresh=fresh)
    return {"geocode": A.geocode_dict(address, g), "sections": sections}


@router.get("/analyze")
async def api_analyze(request: Request, address: str, plot_size_m2: Optional[float] = None,
                      living_space_m2: Optional[float] = None, force: bool = False,
                      destinations: Optional[str] = None, save: bool = False, fresh: bool = False):
    dests = _destinations(destinations)
    out = await run_in_threadpool(_analyze_sync, request, address, plot_size_m2, force, dests, fresh)
    if save:
        run = A.payload_to_run({"address": address, "geocode": out["geocode"], "plot_size_m2": plot_size_m2,
                                "living_space_m2": living_space_m2, "sections": out["sections"]})
        run_id = request.app.state.runs.save(run)
        out = {"run_id": run_id, "permalink": _permalink(run_id), **out}
    return out


@router.post("/runs")
async def api_post_run(request: Request):
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="Ungültiger Payload")
    try:
        build_report_context(payload)  # same validation as the report
    except ReportPayloadError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    run_id = request.app.state.runs.save(A.payload_to_run(payload))
    return {"run_id": run_id, "permalink": _permalink(run_id)}


def _get_run_or_404(request: Request, run_id: str) -> dict:
    run = request.app.state.runs.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Unbekannte Analyse: {run_id}")
    return run


@router.get("/run/{run_id}")
def api_get_run(request: Request, run_id: str):
    run = _get_run_or_404(request, run_id)
    p = A.run_to_payload(run)
    return {"run_id": run_id, "permalink": _permalink(run_id), "created_at": run["created_at"],
            "address": run["address"], "plot_size_m2": run.get("plot_size_m2"),
            "living_space_m2": run.get("living_space_m2"),
            "geocode": {"address": run["address"], **p["geocode"]}, "sections": p["sections"]}


async def _pdf(payload: dict):
    try:
        build_report_context(payload)  # validate before touching Chromium
    except ReportPayloadError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    try:
        pdf, ctx = await run_in_threadpool(render_pdf, payload)
    except RendererUnavailable as exc:
        logger.error("PDF renderer unavailable: %s", exc)
        raise HTTPException(status_code=503, detail="PDF-Renderer nicht verfügbar")
    return pdf_response(pdf, ctx)


@router.post("/report")
async def api_report_post(request: Request):
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="Ungültiger Bericht-Payload")
    return await _pdf(payload)


@router.get("/report")
async def api_report_get(request: Request, address: str, plot_size_m2: Optional[float] = None,
                         living_space_m2: Optional[float] = None, force: bool = True,
                         destinations: Optional[str] = None, fresh: bool = False):
    dests = _destinations(destinations)
    out = await run_in_threadpool(_analyze_sync, request, address, plot_size_m2, force, dests, fresh)
    return await _pdf({"address": address, "geocode": out["geocode"], "plot_size_m2": plot_size_m2,
                       "living_space_m2": living_space_m2, "sections": out["sections"]})


@router.get("/run/{run_id}/report.pdf")
async def api_run_report(request: Request, run_id: str):
    run = _get_run_or_404(request, run_id)
    return await _pdf(A.run_to_payload(run))
