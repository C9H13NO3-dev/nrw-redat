"""Stadtklima — LANUV Klimaanalyse NRW 2026 at the point (statewide model values, not measurements).

WMS https://www.wms.nrw.de/umwelt/klimaanpassung_klimaanalyse (verified 2026-09-07): FITNAH-3D mesoscale model after
VDI 3787 Blatt 1, values 2 m above ground for a typical and an extreme summer day. Layers are numbered:
`59` Klimatope (vector, `Klimatoptyp`), `54`/`52` thermische Belastung PET tags (typisch/extrem),
`38`/`29` Lufttemperatur nachts 4 Uhr (typisch/extrem). GetFeatureInfo with INFO_FORMAT=application/geo+json returns
one feature whose properties carry `Classify.Pixel Value` (a float as string, or the string "NoData") for the
raster layers. PET classes follow the service legend (layer 54). `_featureinfo` is the HTTP/monkeypatch point; the
five layers are fetched concurrently with per-layer error isolation.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import httpx
from pyproj import Transformer

from redat.core.nrw import in_bbox
from redat.http import headers

logger = logging.getLogger(__name__)

WMS_URL = "https://www.wms.nrw.de/umwelt/klimaanpassung_klimaanalyse"
LAYERS = {"klimatop": "59", "pet_typisch": "54", "pet_extrem": "52", "nacht_typisch": "38", "nacht_extrem": "29"}
HINWEIS = ("Modellwerte (FITNAH-3D, 2 m über Grund) für einen typischen bzw. extremen Sommertag — "
           "kein Messwert am Haus.")
_TIMEOUT_S = 10.0
_WORKERS = 5
_HALF_M = 50.0            # 100 × 100 px tile, 1 m/px, point in the centre pixel
_TO_UTM = Transformer.from_crs("EPSG:4326", "EPSG:25832", always_xy=True)

# (upper bound °C inclusive, label, colour) in ascending order — the LANUV legend for layer 54
_PET_CLASSES = (
    (18.0, "leichter Kältestress", "green"),
    (23.0, "kein thermischer Stress", "green"),
    (29.0, "leichte Wärmebelastung", "green"),
    (35.0, "moderate Wärmebelastung", "yellow"),
    (41.0, "starke Wärmebelastung", "orange"),
)
_PET_TOP = ("extrem starke Wärmebelastung", "red")


def pet_class(pet: float) -> tuple[str, str]:
    """(label, colour) of a PET value per the LANUV legend: > 41 extrem, > 35 stark, > 29 moderat, > 23 leicht …"""
    for upper, label, colour in _PET_CLASSES:
        if pet <= upper:
            return label, colour
    return _PET_TOP


def _featureinfo(layer: str, lat: float, lon: float) -> dict:
    """Properties of the first GetFeatureInfo feature for `layer` at the point ({} when none) — the HTTP seam."""
    x, y = _TO_UTM.transform(lon, lat)
    params = {
        "SERVICE": "WMS", "VERSION": "1.3.0", "REQUEST": "GetFeatureInfo", "CRS": "EPSG:25832",
        "BBOX": f"{x - _HALF_M:.1f},{y - _HALF_M:.1f},{x + _HALF_M:.1f},{y + _HALF_M:.1f}",
        "WIDTH": 100, "HEIGHT": 100, "I": 50, "J": 50,
        "LAYERS": layer, "QUERY_LAYERS": layer, "STYLES": "",
        "INFO_FORMAT": "application/geo+json", "FEATURE_COUNT": 1,
    }
    resp = httpx.get(WMS_URL, params=params, headers=headers(), timeout=_TIMEOUT_S)
    resp.raise_for_status()
    feats = resp.json().get("features") or []
    return dict((feats[0] or {}).get("properties") or {}) if feats else {}


def _value(props: dict) -> Optional[float]:
    raw = props.get("Classify.Pixel Value")
    if raw is None or str(raw).strip().lower() == "nodata":
        return None
    try:
        return round(float(raw), 1)
    except (TypeError, ValueError):
        return None


def get_stadtklima(lat: float, lon: float) -> Optional[dict]:
    """Klimatop, PET and night temperature at the point; None outside NRW. Layer failures land in `errors`."""
    if not in_bbox(lat, lon):
        return None
    keys = list(LAYERS)
    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        futures = {k: pool.submit(_featureinfo, LAYERS[k], lat, lon) for k in keys}
        props: dict[str, dict] = {}
        errors: dict[str, str] = {}
        for k in keys:
            try:
                props[k] = futures[k].result()
            except Exception as exc:  # noqa: BLE001 — one layer failing must not blank the card
                props[k] = {}
                errors[k] = str(exc)
                logger.warning("stadtklima layer %s (%s): %s", k, LAYERS[k], exc)
    raw_klimatop = props["klimatop"].get("Klimatoptyp")
    klimatop = str(raw_klimatop).strip() or None if raw_klimatop is not None else None
    pet_t, pet_e = _value(props["pet_typisch"]), _value(props["pet_extrem"])
    basis = pet_t if pet_t is not None else pet_e
    rating, colour = pet_class(basis) if basis is not None else ("unbekannt", "gray")
    return {
        "klimatop": klimatop,
        "pet_typisch": pet_t, "pet_extrem": pet_e,
        "nacht_typisch": _value(props["nacht_typisch"]), "nacht_extrem": _value(props["nacht_extrem"]),
        "klasse_typisch": pet_class(pet_t)[0] if pet_t is not None else None,
        "klasse_extrem": pet_class(pet_e)[0] if pet_e is not None else None,
        "rating": rating, "rating_color": colour,
        "errors": errors, "hinweis": HINWEIS,
    }
