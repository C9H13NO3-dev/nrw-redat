"""Payload → PDF bytes. Shared by POST /report, GET /report and /run/{id}/report.pdf."""
from fastapi import Response

from redat.report.builder import build_report_context, slugify
from redat.report.noise_map import render_noise_maps
from redat.report.pdf import html_to_pdf
from redat.report.render import render_report_html
from redat.report.svg import boris_trend_svg


def render_pdf(payload: dict) -> tuple[bytes, dict]:
    """Blocking: context → maps/SVG → HTML → Chromium PDF. Raises ReportPayloadError / RendererUnavailable."""
    ctx = build_report_context(payload)
    body_keys = {s["key"] for s in ctx["body"]}
    if "noise" in body_keys:
        ctx["noise_maps"] = render_noise_maps(ctx["lat"], ctx["lon"])
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
