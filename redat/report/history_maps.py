"""Historic map panels for the PDF: the site in the 1840s, 1900s, 1950s and today.

WMS (Geobasis NRW, dl-de/zero-2-0, verified 2026-09-06): Uraufnahme https://www.wms.nrw.de/geobasis/wms_nw_uraufnahme
layer `nw_uraufnahme_rw` (1836–1850); Neuaufnahme .../wms_nw_neuaufnahme layer `nw_neuaufnahme` (1891–1912);
historic orthophotos .../wms_nw_hist_dop layers `nw_hist_dop_<year>` — Essen/Bochum are covered 1951–1954 and
the 1956–1998 tiles are blank there, so all four years (1952, 1951, 1953, 1954) are fetched and the first
non-blank one in that order wins; current orthophoto .../wms_nw_dop layer `nw_dop_rgb`. Same 600 m window
and decoration as noise_map. A Zeche, Halde, Gleisanlage or Fabrik on an old panel is the cheapest Altlasten
hint a buyer can get.

Every GetMap request (3 fixed panels + 4 hist-DOP year candidates = 7) runs concurrently in a small
`ThreadPoolExecutor` so the whole figure costs about one `TIMEOUT_S` in the worst case instead of stacking
up to seven sequential timeouts. `_get_png` is the HTTP/monkeypatch point — kept as this module's own
function (rather than reusing `noise_map._fetch_image`, which calls noise_map's own `_get_png`) so tests
can stub it; the WMS param dict is still built via `noise_map._getmap_params` to avoid duplicating that.
"""
from __future__ import annotations

import io
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import httpx
from PIL import Image

from redat.http import headers
from redat.report import noise_map
from redat.report.noise_map import HEIGHT, WIDTH, _decorate, _to_b64, bbox_25832

logger = logging.getLogger(__name__)

URAUFNAHME = ("https://www.wms.nrw.de/geobasis/wms_nw_uraufnahme", "nw_uraufnahme_rw")
NEUAUFNAHME = ("https://www.wms.nrw.de/geobasis/wms_nw_neuaufnahme", "nw_neuaufnahme")
HIST_DOP_URL = "https://www.wms.nrw.de/geobasis/wms_nw_hist_dop"
HIST_DOP_YEARS = (1952, 1951, 1953, 1954)
DOP = ("https://www.wms.nrw.de/geobasis/wms_nw_dop", "nw_dop_rgb")
ATTRIBUTION = "Karten und Luftbilder: © Geobasis NRW (dl-de/zero-2-0) — Preußische Uraufnahme, Neuaufnahme, historische und aktuelle Orthophotos"
TIMEOUT_S = 10.0
_BLANK_SHARE = 0.02   # a tile with fewer than 2 % non-white pixels carries no imagery
_MAX_WORKERS = 7      # 3 fixed panels + 4 hist-DOP year candidates, all in flight at once


def _get_png(url: str, params: dict) -> bytes:
    r = httpx.get(url, params=params, timeout=TIMEOUT_S, headers=headers())
    r.raise_for_status()
    if not r.headers.get("content-type", "").startswith("image/"):
        raise RuntimeError(f"WMS lieferte {r.headers.get('content-type') or 'keine'} statt eines Bildes")
    return r.content


def _fetch(url: str, bbox, layer: str) -> Image.Image:
    params = noise_map._getmap_params(bbox, layer, transparent=False)
    im = Image.open(io.BytesIO(_get_png(url, params)))
    im.load()
    return im.convert("RGBA").resize((WIDTH, HEIGHT))


def is_blank(im: Image.Image) -> bool:
    """True when the tile is (almost) entirely white/transparent — the WMS has no imagery there."""
    px = im.convert("RGBA").getdata()
    ink = sum(1 for r, g, b, a in px if a > 0 and (r < 240 or g < 240 or b < 240))
    return ink < _BLANK_SHARE * im.width * im.height


def render_history_maps(lat: float, lon: float) -> dict:
    bbox = bbox_25832(lat, lon)
    errors: list[str] = []

    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as ex:
        fut_ura = ex.submit(_fetch, URAUFNAHME[0], bbox, URAUFNAHME[1])
        fut_neu = ex.submit(_fetch, NEUAUFNAHME[0], bbox, NEUAUFNAHME[1])
        fut_dop = ex.submit(_fetch, DOP[0], bbox, DOP[1])
        fut_hist = {year: ex.submit(_fetch, HIST_DOP_URL, bbox, f"nw_hist_dop_{year}") for year in HIST_DOP_YEARS}

        def resolve(key: str, title: str, fut) -> dict:
            try:
                im = fut.result()
            except Exception as e:  # noqa: BLE001 — a missing panel is a placeholder, never a failed PDF
                logger.warning("history map %s failed: %s", key, e)
                errors.append(f"{title}: {e}")
                im = None
            return {"key": key, "title": title, "image": _to_b64(_decorate(im, title)) if im else None}

        panels = [
            resolve("uraufnahme", "Preußische Uraufnahme (1836–1850)", fut_ura),
            resolve("neuaufnahme", "Preußische Neuaufnahme (1891–1912)", fut_neu),
        ]

        im_alt: Optional[Image.Image] = None
        year_alt: Optional[int] = None
        last_err: Optional[str] = None
        for year in HIST_DOP_YEARS:
            try:
                im = fut_hist[year].result()
            except Exception as e:  # noqa: BLE001
                last_err = str(e)
                continue
            if not is_blank(im):
                im_alt, year_alt = im, year
                break
        if im_alt is not None:
            title = f"Luftbild {year_alt}"
            panels.append({"key": "dop_alt", "title": title, "image": _to_b64(_decorate(im_alt, title))})
        else:
            err = last_err or "kein historisches Luftbild (1951–1954) für diesen Ausschnitt"
            errors.append(f"Luftbild 1950er: {err}")
            panels.append({"key": "dop_alt", "title": "Luftbild 1950er", "image": None})

        panels.append(resolve("dop", "Luftbild heute", fut_dop))

    return {"panels": panels, "attribution": ATTRIBUTION, "error": " · ".join(errors) or None}
