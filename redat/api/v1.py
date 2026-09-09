"""REDAT public API (spec §5). Everything under /api/v1 needs a session cookie or X-Api-Key, except
`GET /run/{run_id}` and `GET /run/{run_id}/report.pdf`: those back the `/a/{run_id}` permalink page, which
is itself public (a saved analysis is meant to be shareable), so the JSON/PDF behind it stays public too."""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool

from redat.auth.principal import client_ip, current_principal, require_principal
from redat.core import analyze as A
from redat.core.sections import SECTIONS, Ctx, manifest
from redat.report.builder import ReportPayloadError, build_report_context
from redat.report.pdf import RendererUnavailable
from redat.report.service import pdf_response, render_pdf
from redat.settings import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_principal)])
public_router = APIRouter(prefix="/api/v1")


def _status_counts(sections) -> dict:
    counts = {"ok": 0, "error": 0, "empty": 0, "gated": 0}
    for env in (sections or {}).values() if isinstance(sections, dict) else []:
        st = (env or {}).get("status")
        if st in counts:
            counts[st] += 1
    return counts


def _record_analyze(request: Request, payload: dict, run_id: Optional[str]) -> None:
    p = current_principal(request)
    g = payload.get("geocode") or {}
    request.app.state.events.record("analyze", user_id=p.user_id if p else None, via=p.via if p else None,
                                    address=payload.get("address"), lat=g.get("latitude"), lon=g.get("longitude"),
                                    run_id=run_id, extra=_status_counts(payload.get("sections")), ip=client_ip(request))


def _record_pdf(request: Request, payload: dict, run_id: Optional[str]) -> None:
    p = current_principal(request)
    request.app.state.events.record("pdf", user_id=p.user_id if p else None, via=p.via if p else None,
                                    address=payload.get("address"), run_id=run_id, ip=client_ip(request))


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
    run_id = None
    if save:
        run = A.payload_to_run({"address": address, "geocode": out["geocode"], "plot_size_m2": plot_size_m2,
                                "living_space_m2": living_space_m2, "sections": out["sections"]})
        p = current_principal(request)
        run_id = request.app.state.runs.save(run, user_id=p.user_id if p else None)
        out = {"run_id": run_id, "permalink": _permalink(run_id), **out}
    _record_analyze(request, {"address": address, "geocode": out["geocode"], "sections": out["sections"]}, run_id)
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
    p = current_principal(request)
    run_id = request.app.state.runs.save(A.payload_to_run(payload), user_id=p.user_id if p else None)
    _record_analyze(request, payload, run_id)
    return {"run_id": run_id, "permalink": _permalink(run_id)}


def _get_run_or_404(request: Request, run_id: str) -> dict:
    run = request.app.state.runs.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Unbekannte Analyse: {run_id}")
    return run


@public_router.get("/run/{run_id}")
def api_get_run(request: Request, run_id: str):
    run = _get_run_or_404(request, run_id)
    p = A.run_to_payload(run)
    return {"run_id": run_id, "permalink": _permalink(run_id), "created_at": run["created_at"],
            "address": run["address"], "plot_size_m2": run.get("plot_size_m2"),
            "living_space_m2": run.get("living_space_m2"),
            "geocode": {"address": run["address"], **p["geocode"]}, "sections": p["sections"]}


async def _pdf(payload: dict, request: Request, run_id: Optional[str] = None):
    try:
        build_report_context(payload)  # validate before touching Chromium
    except ReportPayloadError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    try:
        pdf, ctx = await run_in_threadpool(render_pdf, payload)
    except RendererUnavailable as exc:
        logger.error("PDF renderer unavailable: %s", exc)
        raise HTTPException(status_code=503, detail="PDF-Renderer nicht verfügbar")
    _record_pdf(request, payload, run_id)
    return pdf_response(pdf, ctx)


@router.post("/report")
async def api_report_post(request: Request):
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="Ungültiger Bericht-Payload")
    return await _pdf(payload, request, run_id=None)


@router.get("/report")
async def api_report_get(request: Request, address: str, plot_size_m2: Optional[float] = None,
                         living_space_m2: Optional[float] = None, force: bool = True,
                         destinations: Optional[str] = None, fresh: bool = False):
    dests = _destinations(destinations)
    out = await run_in_threadpool(_analyze_sync, request, address, plot_size_m2, force, dests, fresh)
    return await _pdf({"address": address, "geocode": out["geocode"], "plot_size_m2": plot_size_m2,
                       "living_space_m2": living_space_m2, "sections": out["sections"]}, request, run_id=None)


@public_router.get("/run/{run_id}/report.pdf")
async def api_run_report(request: Request, run_id: str):
    run = _get_run_or_404(request, run_id)
    return await _pdf(A.run_to_payload(run), request, run_id=run_id)
