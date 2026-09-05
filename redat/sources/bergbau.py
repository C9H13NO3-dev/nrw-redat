"""Mining and subsurface hazards for a point from the Geologischer Dienst NRW
"NRW von unten" (GDU) Bürgerversion —
https://www.gis.nrw.de/arcgis/rest/services/gd_gdu/buerger_utm/MapServer

The public version is anonymised to 500 m × 500 m *Planquadrate*: layer 22 is
the cell polygon carrying every count and flag, layers 5–21 only draw one
schematic symbol per cell and hazard. So one point query on layer 22 answers
everything, and the card must speak of "im 500 m-Planquadrat", never "auf dem
Grundstück". The formal, parcel-exact *Bergbauauskunft* comes from
Bezirksregierung Arnsberg (Abteilung 6, Bergbau und Energie in NRW) or RAG.

Field prefixes (verified 2026-09-04): `b_` = mining records held by
Bezirksregierung Arnsberg, `g_` = Geologischer Dienst geohazards, `gb_` =
methane; `_p` = count of points, `_f` = area flag. `status_bb_gd` 2/3 means the
cell lies inside the Arnsberg mining-information polygon (layer 1).

`_query` is the single HTTP call and the monkeypatch point.
"""
from __future__ import annotations

import logging
from typing import Optional

import httpx

from redat.http import headers

logger = logging.getLogger(__name__)

GDU_URL = "https://www.gis.nrw.de/arcgis/rest/services/gd_gdu/buerger_utm/MapServer"
PLANQUADRAT_LAYER = 22
_TIMEOUT_S = 15.0

# (key, label, count field or None, flag fields, weight) — display order == this order
_ITEMS = [
    ("tagesbruch", "Bergbaubedingte Tagesbrüche", "b_tabr_p", (), "red"),
    ("tagesoeffnung", "Verlassene Tagesöffnungen (Schächte, Stollen)", "b_taoe_p", (), "red"),
    ("bergbau_belegt", "Oberflächennaher Bergbau belegt", None, ("b_beba_f",), "orange"),
    ("bergbau_moeglich", "Tagesnaher Bergbau möglich", None, ("g_beba_f",), "yellow"),
    ("methan", "Methanausgasung (punktuell / flächenhaft)", "gb_meth_p", ("gb_meth_f",), "orange"),
    ("erdfall", "Erdfälle", "g_erdf_p", (), "orange"),
    ("subrosion", "Subrosionssenke", None, ("g_subs_f",), "orange"),
    ("karst", "Karstgebiet", None, ("g_kars_f",), "yellow"),
    ("gasaustritt", "Gasaustritt in Bohrungen möglich", None, ("g_aust_f",), "info"),
    ("erdbeben", "Erdbebenzone (DIN EN 1998)", None, ("g_erb1_f", "g_erb2_f"), "info"),
]
_WEIGHT_RANK = {"info": 0, "yellow": 1, "orange": 2, "red": 3}
_RATINGS = {
    "red": ("Tagesbrüche / Tagesöffnungen", "red"),
    "orange": ("Bergbau belegt", "orange"),
    "yellow": ("Bergbau möglich", "yellow"),
    "info": ("Keine Hinweise", "green"),
}


def _query(layer_id: int, params: dict) -> dict:
    resp = httpx.get(f"{GDU_URL}/{layer_id}/query", params=params, timeout=_TIMEOUT_S, headers=headers())
    resp.raise_for_status()
    return resp.json()


def _int(v) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def _items(attrs: dict) -> list[dict]:
    out = []
    for key, label, count_field, flag_fields, weight in _ITEMS:
        count = _int(attrs.get(count_field)) if count_field else None
        flagged = any(_int(attrs.get(f)) for f in flag_fields)
        if not (count or flagged):
            continue
        out.append({"key": key, "label": label, "kind": "count" if count_field else "flag",
                    "count": count if count_field else None, "present": True, "weight": weight})
    return out


def _rate(items: list[dict]) -> tuple[str, str]:
    worst = max((i["weight"] for i in items), key=_WEIGHT_RANK.get, default="info")
    return _RATINGS[worst]


def get_bergbau(lat: float, lon: float) -> Optional[dict]:
    """Hazard summary of the 500 m Planquadrat containing the point, or None
    outside the GDU coverage (i.e. outside NRW)."""
    payload = _query(PLANQUADRAT_LAYER, {
        "geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint", "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects", "outFields": "*", "returnGeometry": "false", "f": "json",
    })
    if payload.get("error"):
        raise RuntimeError(payload["error"].get("message") or str(payload["error"]))
    feats = payload.get("features") or []
    if not feats:
        return None
    attrs = feats[0].get("attributes") or {}
    items = _items(attrs)
    rating, color = _rate(items)
    return {
        "cell_id": str(attrs.get("pq_name") or attrs.get("OBJECTID") or ""),
        "cell_size_m": 500,
        "authority": "Bezirksregierung Arnsberg" if _int(attrs.get("status_bb_gd")) in (2, 3) else "Geologischer Dienst NRW",
        "updated": (attrs.get("zeitstempel") or "")[:10] or None,
        "items": items,
        "rating": rating, "rating_color": color,
    }
