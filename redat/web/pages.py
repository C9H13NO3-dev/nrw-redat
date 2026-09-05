"""Server-rendered pages: analyzer, stored-run permalink, sources. Never behind the API key."""
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from redat import __version__
from redat.core import analyze as A
from redat.core.sections import manifest
from redat.core.sources_meta import SOURCES
from redat.templating import templates

router = APIRouter(include_in_schema=False)


def _render(request: Request, name: str, ctx: dict, status_code: int = 200) -> HTMLResponse:
    return templates.TemplateResponse(request, name, {"request": request, "version": __version__, **ctx},
                                      status_code=status_code)


def _page_config(address: str = "", plot_size_m2=None, living_space_m2=None, auto_run: bool = False, run=None) -> dict:
    return {"address": address, "plot_size_m2": plot_size_m2, "living_space_m2": living_space_m2,
            "auto_run": auto_run, "sections": manifest(), "run": run}


@router.get("/", response_class=HTMLResponse)
def index(request: Request, address: str = "", plot_size_m2: Optional[float] = None,
          living_space_m2: Optional[float] = None, auto: bool = False):
    cfg = _page_config(address, plot_size_m2, living_space_m2, auto_run=bool(auto and address))
    return _render(request, "index.html", {"active": "analyse", "page_config": cfg, "sections": cfg["sections"]})


@router.get("/a/{run_id}", response_class=HTMLResponse)
def stored_run(request: Request, run_id: str):
    run = request.app.state.runs.get(run_id)
    if run is None:
        return _render(request, "404.html", {"message": f"Es gibt keine gespeicherte Analyse mit der Kennung {run_id}."},
                       status_code=404)
    p = A.run_to_payload(run)
    stored = {"run_id": run_id, "created_at": run["created_at"],
              "geocode": {"address": run["address"], **p["geocode"]}, "sections": p["sections"]}
    cfg = _page_config(run["address"], run.get("plot_size_m2"), run.get("living_space_m2"), run=stored)
    return _render(request, "index.html", {"active": "analyse", "page_config": cfg, "sections": cfg["sections"]})


@router.get("/quellen", response_class=HTMLResponse)
def quellen(request: Request):
    titles = {s["key"]: f'{s["icon"]} {s["title"]}' for s in manifest()}
    return _render(request, "quellen.html", {"active": "quellen", "sources": SOURCES, "titles": titles})
