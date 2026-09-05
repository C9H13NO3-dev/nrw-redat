"""Server-rendered inline SVG for the BORIS trend chart (Chart.js has no place in a PDF)."""
from __future__ import annotations

from typing import Optional

W, H = 560, 200
PAD_L, PAD_R, PAD_T, PAD_B = 56, 16, 12, 28


def _fmt(v: float) -> str:
    return f"{int(round(v)):,}".replace(",", ".")


def boris_trend_svg(history) -> Optional[str]:
    """Line chart of €/m² over years. None when fewer than two usable points."""
    pts = [(int(h["year"]), float(h["value"])) for h in (history or [])
           if isinstance(h, dict) and h.get("year") is not None and h.get("value") is not None]
    pts.sort()
    if len(pts) < 2:
        return None

    years = [p[0] for p in pts]
    vals = [p[1] for p in pts]
    y_min, y_max = min(vals), max(vals)
    if y_max == y_min:  # flat series: give the line some headroom so it sits mid-chart
        y_min, y_max = y_min * 0.9, y_max * 1.1 or 1.0
    span_y = y_max - y_min
    span_x = max(years[-1] - years[0], 1)
    inner_w, inner_h = W - PAD_L - PAD_R, H - PAD_T - PAD_B

    def sx(year: int) -> float:
        return PAD_L + (year - years[0]) / span_x * inner_w

    def sy(val: float) -> float:
        return PAD_T + (y_max - val) / span_y * inner_h

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
           f'font-family="Helvetica, Arial, sans-serif" font-size="11">']
    # horizontal gridlines at min / mid / max
    for frac in (0.0, 0.5, 1.0):
        val = y_min + frac * span_y
        y = sy(val)
        out.append(f'<line x1="{PAD_L}" y1="{y:.1f}" x2="{W - PAD_R}" y2="{y:.1f}" stroke="#e5e7eb" stroke-width="1"/>')
        out.append(f'<text x="{PAD_L - 6}" y="{y + 4:.1f}" text-anchor="end" fill="#6b7280">{_fmt(val)}</text>')
    # x labels
    for year in years:
        out.append(f'<text x="{sx(year):.1f}" y="{H - 8}" text-anchor="middle" fill="#6b7280">{year}</text>')
    poly = " ".join(f"{sx(y):.1f},{sy(v):.1f}" for y, v in pts)
    out.append(f'<polyline points="{poly}" fill="none" stroke="#2563eb" stroke-width="2"/>')
    for year, val in pts:
        out.append(f'<circle cx="{sx(year):.1f}" cy="{sy(val):.1f}" r="3.5" fill="#2563eb"/>')
        out.append(f'<text x="{sx(year):.1f}" y="{sy(val) - 8:.1f}" text-anchor="middle" fill="#111827">{_fmt(val)}</text>')
    out.append("</svg>")
    return "".join(out)
