"""Immobilienrichtwerte (IRW) — €/m² Wohnfläche per Teilmarkt from BORIS NRW.

Source: https://www.wms.nrw.de/boris/wms_nw_irw (Gutachterausschüsse NRW, dl-de/zero-2-0), WMS 1.3.0
GetFeatureInfo on the value layers 9 gemischt genutzt, 12 Mehrfamilienhäuser, 15 Reihen-/Doppelhäuser,
18 Ein-/Zweifamilienhäuser, 21 Eigentumswohnungen (Büro/Gewerbe are not asked). The layers have a
MinScaleDenominator of ~1:57,000, so the request must be a small tile (esri_wms default ≈ 2 m/px).
Fields (IRW_Datenmodell.pdf, verified live 2026-09-05): IMRW €/m², STAG "01.01.2026", TEILMA 1–7,
ORTST, PLZ, WHNLA Wohnlage 1–8, BJ/WHNFL/FLAE of the Normobjekt (single values or ranges "111-130"),
EGART Anbauweise, ANZEGEB Wohnungen im Gebäude, GABE Gutachterausschuss, UDOK_URL PDF with the
Umrechnungskoeffizienten. Essen and Bochum both publish IRW; dense inner-city points may lie in no zone.
`_featureinfo` is the single HTTP call and monkeypatch point.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import httpx

from redat.http import headers
from redat.sources.esri_wms import featureinfo_params, parse_featureinfo

IRW_WMS_URL = "https://www.wms.nrw.de/boris/wms_nw_irw"
LAYERS = "9,12,15,18,21"
_TIMEOUT_S = 20
TEILMARKT = {1: "Eigentumswohnungen", 2: "Ein-/Zweifamilienhäuser (freistehend)", 3: "Reihen-/Doppelhäuser",
             4: "Mehrfamilienhäuser", 5: "Gemischt genutzte Gebäude", 6: "Büro-/Geschäftsgebäude", 7: "Gewerbe/Industrie"}
WOHNLAGE = {1: "sehr gut", 2: "gut – sehr gut", 3: "gut", 4: "mittel – gut", 5: "mittel", 6: "einfach – mittel", 7: "einfach", 8: "sehr einfach"}
ANBAUWEISE = {1: "freistehend", 2: "Doppelhaushälfte", 4: "Reihenmittelhaus", 5: "Reihenendhaus"}


def _featureinfo(lat: float, lon: float) -> str:
    resp = httpx.get(IRW_WMS_URL, params=featureinfo_params(lat, lon, LAYERS), timeout=_TIMEOUT_S, headers=headers())
    resp.raise_for_status()
    return resp.text


def _int(v: Optional[str]) -> Optional[int]:
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def _iso(d: Optional[str]) -> Optional[str]:
    try:
        return datetime.strptime((d or "").strip(), "%d.%m.%Y").date().isoformat()
    except ValueError:
        return None


def parse_irw(xml_text: str) -> list[dict]:
    werte = []
    for _layer, f in parse_featureinfo(xml_text):
        eur, teilmarkt = _int(f.get("IMRW")), _int(f.get("TEILMA"))
        if eur is None or teilmarkt is None:
            continue
        werte.append({
            "teilmarkt": teilmarkt, "teilmarkt_label": TEILMARKT.get(teilmarkt, f"Teilmarkt {teilmarkt}"),
            "eur_m2": eur, "stichtag": _iso(f.get("STAG")),
            "ortsteil": f.get("ORTST"), "plz": f.get("PLZ"),
            "wohnlage": WOHNLAGE.get(_int(f.get("WHNLA"))),
            "gutachterausschuss": f.get("GABE"),
            "normobjekt": {"baujahr": f.get("BJ"), "wohnflaeche_m2": f.get("WHNFL"), "grundstueck_m2": f.get("FLAE"),
                           "anbauweise": ANBAUWEISE.get(_int(f.get("EGART"))), "wohnungen": f.get("ANZEGEB")},
            "doku_url": f.get("UDOK_URL"),
        })
    werte.sort(key=lambda w: w["teilmarkt"])
    return werte


def get_irw(lat: float, lon: float) -> Optional[dict]:
    """IRW per Teilmarkt at the point, or None when no value zone covers it."""
    werte = parse_irw(_featureinfo(lat, lon))
    if not werte:
        return None
    return {"stichtag": werte[0]["stichtag"], "gutachterausschuss": werte[0]["gutachterausschuss"], "werte": werte}
