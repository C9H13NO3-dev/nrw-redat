"""Baugrund & Versickerung — the BK50 soil unit under the point, plus real kf values from Essen Baugrundgutachten.

Source A: GD NRW "IS BK50 Bodenkarte 1:50.000" WMS https://www.wms.nrw.de/gd/bk050 (dl-de/by-2-0).
GetFeatureInfo with INFO_FORMAT=text/html returns one 37-row HTML table for the soil unit with
human-readable values (the esri XML carries only codes) — the same table for every layer, so we ask one
layer (Versickerungseignung). Rows read (label = text of the <a> in the first cell; verified 2026-09-05):
Bodentyp, Grundwasserstufe, Staunässegrad, Bodenartengruppe des Oberbodens, Hauptbodenart nach BBodSchG,
Schutzwürdigkeit der Böden, Verdichtungsempfindlichkeit, Erodierbarkeit des Oberbodens (value, class),
gesättigte Wasserleitfähigkeit (value, "cm/d", class), Versickerungseignung ("ungeeignet - VSA, …"),
Grabbarkeit, Eignung für Erdwärmekollektoren (two depths: values, unit, classes). Versickerung classes
per GD NRW: geeignet ≥ 1·10⁻⁵ m/s, bedingt geeignet 5·10⁻⁶–1·10⁻⁵, ungeeignet below (or staunass).
Scale 1:50,000 → area statement, never grundstücksscharf.

Source B (Essen only): https://geo.essen.de/arcgis/rest/services/essen/Umwelt/MapServer/0 "kf Werte aus
Bauanträgen" — points with GUTACHTEN, KF_WERT ("<1x10-7" m/s), GEEIGNET (ja/nein für Versickerung),
JAHR, ANMERKUNG ("Auffüllung bis zu 1,9m Mächtigkeit"); the Ruhrgebiet-typical hint at Auffüllungen.
`_featureinfo_html` and `_kf_query` are the HTTP calls and monkeypatch points.
"""
from __future__ import annotations

import html as htmlmod
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import httpx

from redat.http import headers
from redat.sources.esri_wms import featureinfo_params

logger = logging.getLogger(__name__)

BK50_WMS_URL = "https://www.wms.nrw.de/gd/bk050"
BK50_LAYER = "Versickerungseignung"
KF_URL = "https://geo.essen.de/arcgis/rest/services/essen/Umwelt/MapServer/0/query"
ESSEN_BBOX = (6.89, 51.35, 7.14, 51.53)
KF_RADIUS_M = 300
_TIMEOUT_S = 20
_LABELS = ("Bodentyp", "Grundwasserstufe", "Staunässegrad", "Bodenartengruppe des Oberbodens", "Hauptbodenart",
           "Schutzwürdigkeit der Böden", "Verdichtungsempfindlichkeit", "Erodierbarkeit des Oberbodens",
           "gesättigte Wasserleitfähigkeit", "Versickerungseignung", "Grabbarkeit", "Eignung für Erdwärmekollektoren")


def in_essen(lat: float, lon: float) -> bool:
    lon_min, lat_min, lon_max, lat_max = ESSEN_BBOX
    return lon_min <= lon <= lon_max and lat_min <= lat <= lat_max


def _featureinfo_html(lat: float, lon: float) -> str:
    """BK50 GetFeatureInfo as HTML — HTTP/monkeypatch point."""
    params = featureinfo_params(lat, lon, BK50_LAYER, feature_count=1, info_format="text/html")
    resp = httpx.get(BK50_WMS_URL, params=params, timeout=_TIMEOUT_S, headers=headers())
    resp.raise_for_status()
    return resp.text


def _kf_query(lat: float, lon: float) -> dict:
    """Essen kf-Werte within KF_RADIUS_M — HTTP/monkeypatch point."""
    params = {"f": "json", "where": "1=1", "geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint", "inSR": 4326,
              "spatialRel": "esriSpatialRelIntersects", "distance": KF_RADIUS_M, "units": "esriSRUnit_Meter",
              "outFields": "GUTACHTEN,KF_WERT,GEEIGNET,JAHR,ANMERKUNG", "returnGeometry": "false", "resultRecordCount": 10}
    resp = httpx.get(KF_URL, params=params, timeout=_TIMEOUT_S, headers=headers())
    resp.raise_for_status()
    return resp.json()


def _text(cell_html: str) -> str:
    t = re.sub(r"<br\s*/?>", " ", cell_html)
    t = re.sub(r"<[^>]+>", "", t)
    return re.sub(r"\s+", " ", htmlmod.unescape(t)).strip()


def parse_bk50_html(text: str) -> dict[str, list[str]]:
    """label (text of the <a> in the first cell, matched against _LABELS) → the remaining cells as text."""
    text = re.sub(r"<style.*?</style>", "", text, flags=re.S)
    rows: dict[str, list[str]] = {}
    for tr in re.findall(r"<tr.*?</tr>", text, flags=re.S):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", tr, flags=re.S)
        if len(cells) < 2:
            continue
        m = re.search(r"<a[^>]*>(.*?)</a>", cells[0], flags=re.S)
        label = _text(m.group(1) if m else cells[0])
        key = next((lab for lab in _LABELS if label.startswith(lab)), None)
        if key and key not in rows:
            rows[key] = [_text(c) for c in cells[1:] if _text(c)]
    return rows


def versickerung_klasse(text: Optional[str]) -> Optional[str]:
    low = (text or "").lower()
    if not low:
        return None
    if low.startswith("bedingt"):
        return "bedingt geeignet"
    if low.startswith("ungeeignet"):
        return "ungeeignet"
    if low.startswith("geeignet"):
        return "geeignet"
    return None


def _stufe(text: Optional[str]) -> int:
    m = re.search(r"Stufe\s+(\d)", text or "")
    return int(m.group(1)) if m else 0


def rate(vers: Optional[str], grundwasser: Optional[str], staunaesse: Optional[str]) -> tuple[str, str]:
    if vers is None and not grundwasser and not staunaesse:
        return "Keine Bewertung", "gray"
    wet = max(_stufe(grundwasser), _stufe(staunaesse))
    if wet >= 3:
        return "Nasser Boden (Grundwasser/Staunässe)", "orange"
    if vers == "ungeeignet":
        return "Schwer versickerbarer Boden", "orange"
    if vers == "bedingt geeignet" or wet >= 1:
        return "Eingeschränkte Versickerung", "yellow"
    return "Unauffälliger Baugrund (BK50)", "green"


def _float(s: Optional[str]) -> Optional[float]:
    try:
        return float(str(s).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _first(rows: dict, label: str, i: int = 0) -> Optional[str]:
    cells = rows.get(label) or []
    return cells[i] if len(cells) > i else None


# GD NRW Bewertungsstufen as they appear in the BK50 HTML (single- and two-word labels)
_KLASSEN = ("extrem gering", "sehr gering", "gering", "mittel", "hoch", "sehr hoch", "extrem hoch")


def _split_klassen(text: str) -> tuple[Optional[str], Optional[str]]:
    """'extrem hoch mittel' → ('extrem hoch', 'mittel'): find the split where both halves are known labels."""
    words = text.split()
    for i in range(1, len(words)):
        a, b = " ".join(words[:i]), " ".join(words[i:])
        if a in _KLASSEN and b in _KLASSEN:
            return a, b
    if not words:
        return None, None
    return words[0], " ".join(words[1:]) or None   # unknown vocabulary: fall back to the positional split


def _erdwaerme(rows: dict) -> Optional[dict]:
    cells = rows.get("Eignung für Erdwärmekollektoren") or []
    if len(cells) < 4:
        return None
    vals = cells[1].split()
    m1, m2 = _split_klassen(cells[3])
    return {"m1_w_mk": _float(vals[0]) if vals else None, "m1_klasse": m1,
            "m2_w_mk": _float(vals[1]) if len(vals) > 1 else None, "m2_klasse": m2}


def get_baugrund(lat: float, lon: float) -> Optional[dict]:
    # The BK50 WMS and the Essen kf layer are independent servers — one round-trip instead of two.
    # kf is resolved first so a BK50 failure never escapes with the kf future's exception unretrieved.
    kf_features, kf_error = [], None
    with ThreadPoolExecutor(max_workers=2) as ex:
        bk50 = ex.submit(_featureinfo_html, lat, lon)
        kf = ex.submit(_kf_query, lat, lon) if in_essen(lat, lon) else None
        if kf is not None:
            try:
                kf_features = kf.result().get("features") or []
            except Exception as exc:  # noqa: BLE001 — Essen down must not blank the BK50 result
                logger.warning("Essen kf-Werte: %s", exc)
                kf_error = str(exc)
        html = bk50.result()          # BK50 is the card: a failure here still raises
    rows = parse_bk50_html(html)
    if not rows.get("Bodentyp"):
        return None
    vers_text = _first(rows, "Versickerungseignung")
    vers = versickerung_klasse(vers_text)
    gw, sn = _first(rows, "Grundwasserstufe"), _first(rows, "Staunässegrad")
    kf_cells = rows.get("gesättigte Wasserleitfähigkeit") or []
    kf_val = _float(kf_cells[0]) if kf_cells else None
    kf_klasse = kf_cells[-1] if len(kf_cells) >= 2 and kf_cells[-1] != "cm/d" else None
    erod = rows.get("Erodierbarkeit des Oberbodens") or []
    bodenart_cells = rows.get("Bodenartengruppe des Oberbodens") or []

    kf_gutachten = []
    for f in kf_features:
        a = f.get("attributes") or {}
        kf_gutachten.append({"gutachten": a.get("GUTACHTEN"), "kf": a.get("KF_WERT"), "geeignet": a.get("GEEIGNET"),
                             "jahr": a.get("JAHR"), "anmerkung": a.get("ANMERKUNG") or None})

    rating, color = rate(vers, gw, sn)
    return {
        "bodentyp": _first(rows, "Bodentyp"),
        "bodenart": bodenart_cells[-1] if bodenart_cells else None,
        "hauptbodenart": _first(rows, "Hauptbodenart"),
        "grundwasser": gw, "staunaesse": sn,
        "kf_cm_d": kf_val, "kf_klasse": kf_klasse,
        "versickerung": vers_text, "versickerung_klasse": vers,
        "grabbarkeit": _first(rows, "Grabbarkeit"),
        "verdichtung": _first(rows, "Verdichtungsempfindlichkeit"),
        "schutzwuerdigkeit": _first(rows, "Schutzwürdigkeit der Böden"),
        "erodierbarkeit": erod[-1] if erod else None,
        "erdwaerme": _erdwaerme(rows),
        "kf_gutachten": kf_gutachten, "kf_gutachten_error": kf_error,
        "rating": rating, "rating_color": color,
    }
