"""Überschwemmungsgebiete NRW (rechtlich) — the §78 WHG layer the HWRM hazard maps are not.

Source: https://www.wms.nrw.de/umwelt/wasser/uesg (Land NRW, open data), WMS 1.3.0 GetFeatureInfo,
query layers 6 "Festgesetzte Überschwemmungsgebiete" (Rechtsverordnung der Bezirksregierung), 5 "vorläufig
gesicherte Überschwemmungsgebiete" (same legal effect until the Verordnung is issued), 3 "Ermittelte
Überschwemmungsgebiete" (Fachplanung, HQ100 basis, no direct legal effect). Fields (verified 2026-09-05 on
the Ruhr at Essen-Steele): name "Ruhr", uesg_pdf "Amtsblatt Nr. 27 vom 06.07.2023", datum "14.4.2016",
BR "BR Düsseldorf". Inside a festgesetztes/vorläufig gesichertes ÜSG new buildings need an Ausnahme
(§78 WHG) and Heizöltanks are prohibited (§78c). `_featureinfo` is the single HTTP call and monkeypatch point.
"""
from __future__ import annotations

from typing import Optional

import httpx

from redat.http import headers
from redat.sources.esri_wms import featureinfo_params, parse_featureinfo

UESG_WMS_URL = "https://www.wms.nrw.de/umwelt/wasser/uesg"
LAYERS = "3,5,6"
_TIMEOUT_S = 20
# (layername prefix, kind, label) — legal kinds first so the zone list reads in order of consequence.
_KINDS = (
    ("festgesetzte", "festgesetzt", "Festgesetztes Überschwemmungsgebiet"),
    ("vorläufig", "vorlaeufig", "Vorläufig gesichertes Überschwemmungsgebiet"),
    ("ermittelte", "ermittelt", "Ermitteltes Überschwemmungsgebiet"),
)
LEGAL_KINDS = {"festgesetzt", "vorlaeufig"}


def _featureinfo(lat: float, lon: float) -> str:
    """Raw esri featureinfo XML for the three ÜSG layers at the point — HTTP/monkeypatch point."""
    resp = httpx.get(UESG_WMS_URL, params=featureinfo_params(lat, lon, LAYERS), timeout=_TIMEOUT_S, headers=headers())
    resp.raise_for_status()
    return resp.text


def _kind(layername: str) -> Optional[tuple[str, str]]:
    low = layername.lower()
    for prefix, kind, label in _KINDS:
        if low.startswith(prefix):
            return kind, label
    return None


def parse_uesg(xml_text: str) -> list[dict]:
    zones = []
    for layername, f in parse_featureinfo(xml_text):
        k = _kind(layername)
        if k is None:
            continue
        kind, label = k
        zones.append({"kind": kind, "kind_label": label, "name": f.get("name"), "amtsblatt": f.get("uesg_pdf"),
                      "date": f.get("datum"), "authority": f.get("BR")})
    order = {kind: i for i, (_, kind, _) in enumerate(_KINDS)}
    zones.sort(key=lambda z: order[z["kind"]])
    return zones


def get_uesg(lat: float, lon: float) -> dict:
    zones = parse_uesg(_featureinfo(lat, lon))
    return {"zones": zones, "legal": any(z["kind"] in LEGAL_KINDS for z in zones)}
