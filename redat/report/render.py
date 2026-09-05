"""Render the report context to a self-contained HTML string (Jinja, server-side, no Alpine)."""
from __future__ import annotations

from redat.templating import templates
from redat.report import builder

_FILTERS = {
    "fmt_int": builder.fmt_int,
    "fmt_num": builder.fmt_num,
    "fmt_date": builder.fmt_date,
    "fmt_m": builder.fmt_m,
    "pct": lambda v, digits=0: builder.fmt_num(float(v) * 100, digits) + " %",  # 0.469 → "47 %"
}
templates.env.filters.update(_FILTERS)

RATING_CLASS = {"green": "chip-green", "yellow": "chip-yellow", "orange": "chip-orange", "red": "chip-red", "gray": "chip-gray"}
templates.env.globals.setdefault("rating_class", lambda c: RATING_CLASS.get(c or "gray", "chip-gray"))


def render_report_html(ctx: dict) -> str:
    return templates.env.get_template("report/report.html").render(**ctx)


def render_section_html(key: str, data: dict, **extra) -> str:
    """Render one section partial on its own — used by the per-partial tests."""
    name = "report/_planning.html" if key.startswith("planning_") else f"report/_{key}.html"
    return templates.env.get_template(name).render(d=data, key=key, **extra)
