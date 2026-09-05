"""HTML → PDF via headless Chromium (Playwright, sync API — call from a worker thread).

One browser launch per request keeps the process free of long-lived Chromium
state; the launch costs ~0.5 s, the render 1–3 s. A missing/broken Chromium
surfaces as RendererUnavailable so the route can answer 503 with a runbook hint
(`.venv/bin/playwright install chromium`).
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

PDF_MARGIN = {"top": "22mm", "bottom": "18mm", "left": "16mm", "right": "16mm"}

_HEADER_TEMPLATE = """
<div style="width:100%;font-size:8px;font-family:Helvetica,Arial,sans-serif;color:#6b7280;
            padding:0 16mm;display:flex;justify-content:space-between;">
  <span>{address}</span><span>Standortanalyse · NRW-REDAT</span>
</div>"""

_FOOTER_TEMPLATE = """
<div style="width:100%;font-size:8px;font-family:Helvetica,Arial,sans-serif;color:#6b7280;
            padding:0 16mm;display:flex;justify-content:space-between;">
  <span>erstellt am {generated_at}</span>
  <span>Seite <span class="pageNumber"></span> / <span class="totalPages"></span></span>
</div>"""


class RendererUnavailable(RuntimeError):
    """Chromium could not be launched (Playwright missing, browser not installed, sandbox refused)."""


def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def html_to_pdf(html: str, *, header_address: str = "", generated_at: str = "") -> bytes:
    """Render `html` to A4 PDF bytes. Raises RendererUnavailable when Chromium can't start."""
    try:
        from playwright.sync_api import Error as PlaywrightError, sync_playwright
    except ImportError as e:  # pragma: no cover — playwright is in requirements
        raise RendererUnavailable(f"playwright nicht installiert: {e}") from e

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except PlaywrightError as e:
            logger.error("Chromium launch failed: %s", e)
            raise RendererUnavailable(str(e)) from e
        try:
            page = browser.new_page()
            page.set_content(html, wait_until="load")
            return page.pdf(
                format="A4",
                print_background=True,
                margin=PDF_MARGIN,
                display_header_footer=True,
                header_template=_HEADER_TEMPLATE.format(address=_esc(header_address)),
                footer_template=_FOOTER_TEMPLATE.format(generated_at=_esc(generated_at)),
                prefer_css_page_size=False,
            )
        finally:
            browser.close()
