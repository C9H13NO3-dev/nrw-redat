"""Bauleitpläne NRW-weit — INSPIRE "geplante Bodennutzung" des Landes als OGC API Features.

Endpoint: https://ogc-api.nrw.de/inspire-lu-bplan/v1/collections/spatialplan/items (the un-versioned path
307-redirects → `follow_redirects=True`; `Accept: application/json`). 82,140 Bebauungs-/Flächennutzungs-/
Regionalpläne as GeoJSON MultiPolygons in CRS84. Properties used: officialTitle, planTypeName.title,
processStepGeneral.title, validFrom (`1900-01-01` = unknown), officialDocument, texturl, kommune.
Delivery by the municipalities is voluntary (Essen 21 plans in a 1 km bbox, Bochum 52, Bonn only its FNP —
verified 2026-09-07), so an empty answer never means "kein Bebauungsplan" — hence HINWEIS on the card.
Only plans whose polygon contains the point are reported; the ±25 m bbox is just the server-side filter.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Optional

import httpx
from shapely.errors import ShapelyError
from shapely.geometry import Point, shape

from redat.http import headers

logger = logging.getLogger(__name__)

API_URL = "https://ogc-api.nrw.de/inspire-lu-bplan/v1/collections/spatialplan/items"
HINWEIS = ("Landesweiter INSPIRE-Dienst (ogc-api.nrw.de); die Kommunen liefern ihre Bauleitpläne freiwillig — "
           "nicht flächendeckend, Änderungen und laufende Verfahren können fehlen.")
_TIMEOUT_S = 20.0
_LIMIT = 50
_PAD_LAT = 0.00025          # ≈ 28 m
_PAD_LON = 0.00040          # ≈ 28 m at 51° N
_UNKNOWN_DATE = "1900-01-01"


def _items(bbox: tuple[float, float, float, float]) -> list[dict]:
    """GeoJSON features intersecting the WGS84 bbox — the HTTP/monkeypatch point."""
    params = {"f": "json", "bbox": ",".join(f"{v:.6f}" for v in bbox), "limit": _LIMIT}
    resp = httpx.get(API_URL, params=params, headers={**headers(), "Accept": "application/json"},
                     timeout=_TIMEOUT_S, follow_redirects=True)
    resp.raise_for_status()
    return resp.json().get("features") or []


def _http(v) -> Optional[str]:
    v = str(v or "").strip()
    return v if v.startswith("http") else None


def _short_status(step) -> Optional[str]:
    s = str(step or "").lower()
    if not s:
        return None
    if "in kraft" in s or "rechtsverbindlich" in s:
        return "in Kraft"
    if "verfahren" in s or "aufstellung" in s or "entwurf" in s:
        return "im Verfahren"
    return str(step or "").split("(")[0].strip()[:40] or None


def _de_date(iso) -> Optional[str]:
    try:
        return date.fromisoformat(str(iso or "")[:10]).strftime("%d.%m.%Y")
    except ValueError:
        return None


def _name(p: dict) -> str:
    parts = [_short_status(p.get("processStepGeneral.title"))]
    valid = str(p.get("validFrom") or "")
    if valid and not valid.startswith(_UNKNOWN_DATE) and _de_date(valid):
        parts.append(f"ab {_de_date(valid)}")
    extra = ", ".join(x for x in parts if x)
    title = (p.get("officialTitle") or "—").strip()
    return f"{title} ({extra})" if extra else title


def _sort_year(valid_from) -> int:
    s = str(valid_from or "")
    return int(s[:4]) if s.startswith(("1", "2")) else 0


def get_planning_nrw(lat: float, lon: float) -> dict:
    """Plans containing the point → {"ok", "found", "items", "kommune"}; {"ok": False, "error"} on HTTP failure."""
    try:
        feats = _items((lon - _PAD_LON, lat - _PAD_LAT, lon + _PAD_LON, lat + _PAD_LAT))
    except Exception as e:  # noqa: BLE001 — the caller turns this into the card's error state
        logger.warning("planning_nrw: %s", e)
        return {"ok": False, "error": str(e)}
    pt = Point(lon, lat)
    items = []
    for f in feats:
        if not isinstance(f, dict) or not f.get("geometry"):
            continue
        try:
            geom = shape(f["geometry"])
        except (KeyError, TypeError, ValueError, AttributeError, ShapelyError):
            continue
        if not geom.contains(pt):
            continue
        p = f.get("properties") or {}
        items.append({"category": p.get("planTypeName.title") or "Bauleitplan", "name": _name(p),
                      "link": _http(p.get("officialDocument")) or _http(p.get("texturl")),
                      "kommune": p.get("kommune"), "valid_from": p.get("validFrom")})
    items.sort(key=lambda i: (i["category"] != "Bebauungsplan", -_sort_year(i["valid_from"]), i["name"]))
    return {"ok": True, "found": bool(items), "items": items, "kommune": items[0]["kommune"] if items else None}
