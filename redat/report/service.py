"""Payload → PDF bytes. Shared by POST /report, GET /report and /run/{id}/report.pdf."""
import logging
from concurrent.futures import ThreadPoolExecutor

from fastapi import Response

from redat.report.builder import build_report_context, slugify
from redat.report.climate_maps import render_climate_maps
from redat.report.history_maps import render_history_maps
from redat.report.noise_map import render_noise_maps
from redat.report.pdf import html_to_pdf
from redat.report.regionalplan_map import render_regionalplan_map
from redat.report.render import render_report_html
from redat.report.svg import boris_trend_svg

logger = logging.getLogger(__name__)


def render_pdf(payload: dict) -> tuple[bytes, dict]:
    """Blocking: context → maps/SVG → HTML → Chromium PDF. Raises ReportPayloadError / RendererUnavailable."""
    ctx = build_report_context(payload)
    body_keys = {s["key"] for s in ctx["body"]}
    jobs: dict[str, tuple] = {}
    if "noise" in body_keys:
        jobs["noise_maps"] = (render_noise_maps, (ctx["lat"], ctx["lon"]))
    if "flurstueck" in body_keys:
        jobs["history_maps"] = (render_history_maps, (ctx["lat"], ctx["lon"]))
    if "zensus" in body_keys:
        jobs["climate_maps"] = (render_climate_maps, (ctx["lat"], ctx["lon"]))
    if "gfnp" in body_keys:
        jobs["regionalplan_map"] = (render_regionalplan_map, (ctx["lat"], ctx["lon"]))
    if jobs:
        # The four figure renderers each block on their own HTTP calls + Pillow drawing;
        # run them concurrently instead of one after another (worst case was ~36+10+10 s).
        # A renderer is designed never to raise, but a failure here must still degrade to a
        # missing figure rather than break the whole PDF.
        with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
            futures = {key: pool.submit(fn, *args) for key, (fn, args) in jobs.items()}
            for key, future in futures.items():
                try:
                    ctx[key] = future.result()
                except Exception:
                    logger.warning("report figure renderer %r failed", key, exc_info=True)
                    ctx[key] = None
    if "boris_trend" in body_keys:
        data = next(s["data"] for s in ctx["body"] if s["key"] == "boris_trend")
        ctx["boris_trend_svg"] = boris_trend_svg(data.get("history") or [])
    html = render_report_html(ctx)
    pdf = html_to_pdf(html, header_address=ctx["formatted_address"] or ctx["address"],
                      generated_at=ctx["generated_at"])
    return pdf, ctx


def pdf_filename(ctx: dict) -> str:
    return f"Standortanalyse_{slugify(ctx['formatted_address'] or ctx['address'])}_{ctx['generated_date']}.pdf"


def pdf_response(pdf: bytes, ctx: dict) -> Response:
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{pdf_filename(ctx)}"'})
