"""Historic map panels for the PDF: the site in the 1840s, 1900s, 1950s and today.

WMS (Geobasis NRW, dl-de/zero-2-0, verified 2026-09-06): Uraufnahme https://www.wms.nrw.de/geobasis/wms_nw_uraufnahme
layer `nw_uraufnahme_rw` (1836–1850); Neuaufnahme .../wms_nw_neuaufnahme layer `nw_neuaufnahme` (1891–1912);
historic orthophotos .../wms_nw_hist_dop layers `nw_hist_dop_<year>` — Essen/Bochum are covered 1951–1954 and
the 1956–1998 tiles are blank there, so 1952 is tried first and 1951/1953/1954 as fallbacks; current
orthophoto .../wms_nw_dop layer `nw_dop_rgb`. Same 600 m window and decoration as noise_map. A Zeche, Halde,
Gleisanlage or Fabrik on an old panel is the cheapest Altlasten hint a buyer can get. `_get_png` is the
HTTP/monkeypatch point.
"""
from __future__ import annotations

import io
import logging
from typing import Optional

import httpx
from PIL import Image

from redat.http import headers
from redat.report.noise_map import HEIGHT, WIDTH, _decorate, _to_b64, bbox_25832

logger = logging.getLogger(__name__)

URAUFNAHME = ("https://www.wms.nrw.de/geobasis/wms_nw_uraufnahme", "nw_uraufnahme_rw")
NEUAUFNAHME = ("https://www.wms.nrw.de/geobasis/wms_nw_neuaufnahme", "nw_neuaufnahme")
HIST_DOP_URL = "https://www.wms.nrw.de/geobasis/wms_nw_hist_dop"
HIST_DOP_YEARS = (1952, 1951, 1953, 1954)
DOP = ("https://www.wms.nrw.de/geobasis/wms_nw_dop", "nw_dop_rgb")
ATTRIBUTION = "Karten und Luftbilder: © Geobasis NRW (dl-de/zero-2-0) — Preußische Uraufnahme, Neuaufnahme, historische und aktuelle Orthophotos"
TIMEOUT_S = 15.0
_BLANK_SHARE = 0.02   # a tile with fewer than 2 % non-white pixels carries no imagery


def _get_png(url: str, params: dict) -> bytes:
    r = httpx.get(url, params=params, timeout=TIMEOUT_S, headers=headers())
    r.raise_for_status()
    if not r.headers.get("content-type", "").startswith("image/"):
        raise RuntimeError(f"WMS lieferte {r.headers.get('content-type') or 'keine'} statt eines Bildes")
    return r.content


def _params(bbox, layer: str) -> dict:
    return {"SERVICE": "WMS", "VERSION": "1.3.0", "REQUEST": "GetMap", "CRS": "EPSG:25832",
            "BBOX": ",".join(f"{v:.3f}" for v in bbox), "WIDTH": WIDTH, "HEIGHT": HEIGHT, "FORMAT": "image/png",
            "LAYERS": layer, "STYLES": ""}


def _fetch(url: str, bbox, layer: str) -> Image.Image:
    im = Image.open(io.BytesIO(_get_png(url, _params(bbox, layer))))
    im.load()
    return im.convert("RGBA").resize((WIDTH, HEIGHT))


def is_blank(im: Image.Image) -> bool:
    """True when the tile is (almost) entirely white/transparent — the WMS has no imagery there."""
    px = im.convert("RGBA").getdata()
    ink = sum(1 for r, g, b, a in px if a > 0 and (r < 240 or g < 240 or b < 240))
    return ink < _BLANK_SHARE * im.width * im.height


def _hist_dop(bbox) -> tuple[Optional[Image.Image], Optional[int], Optional[str]]:
    last_err = None
    for year in HIST_DOP_YEARS:
        try:
            im = _fetch(HIST_DOP_URL, bbox, f"nw_hist_dop_{year}")
        except Exception as e:  # noqa: BLE001
            last_err = str(e)
            continue
        if not is_blank(im):
            return im, year, None
    return None, None, last_err or "kein historisches Luftbild (1951–1954) für diesen Ausschnitt"


def render_history_maps(lat: float, lon: float) -> dict:
    bbox = bbox_25832(lat, lon)
    panels, errors = [], []

    def add(key: str, title: str, fetch):
        try:
            im = fetch()
        except Exception as e:  # noqa: BLE001 — a missing panel is a placeholder, never a failed PDF
            logger.warning("history map %s failed: %s", key, e)
            errors.append(f"{title}: {e}")
            im = None
        panels.append({"key": key, "title": title, "image": _to_b64(_decorate(im, title)) if im else None})

    add("uraufnahme", "Preußische Uraufnahme (1836–1850)", lambda: _fetch(URAUFNAHME[0], bbox, URAUFNAHME[1]))
    add("neuaufnahme", "Preußische Neuaufnahme (1891–1912)", lambda: _fetch(NEUAUFNAHME[0], bbox, NEUAUFNAHME[1]))
    im, year, err = _hist_dop(bbox)
    if im is not None:
        panels.append({"key": "dop_alt", "title": f"Luftbild {year}", "image": _to_b64(_decorate(im, f"Luftbild {year}"))})
    else:
        errors.append(f"Luftbild 1950er: {err}")
        panels.append({"key": "dop_alt", "title": "Luftbild 1950er", "image": None})
    add("dop", "Luftbild heute", lambda: _fetch(DOP[0], bbox, DOP[1]))
    return {"panels": panels, "attribution": ATTRIBUTION, "error": " · ".join(errors) or None}
