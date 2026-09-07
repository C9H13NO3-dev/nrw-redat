# Stadtklima statewide (Tier 4) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A new `stadtklima` card with real LANUV Klimaanalyse values for every NRW address, and a "Grün und Hitze" PDF figure that renders statewide (Copernicus canopy + Klimaanalyse thermal stress) instead of only in the Ruhr.

**Architecture:** Same shape as Tiers 1–3: one source module with a single HTTP seam, concurrent per-layer requests with isolated errors, card wired in `redat/core/sections.py` + tiers + sources_meta + builder SUMMARY + two partials + fixture + ORDER lists; the figure module gains a second panel set chosen by `redat.core.nrw.in_bbox(lat, lon, RVR_BBOX_WGS84)`.

**Tech Stack:** Python 3.12, httpx, Pillow, pyproj, FastAPI + Jinja2, Alpine.js, pytest.

**Spec:** `docs/superpowers/specs/2026-09-07-stadtklima-design.md` — read it first; every layer number, property name and sample value comes from it.

## Global Constraints

- Every outbound call passes `headers=headers()` from `redat/http.py`; never bare `httpx.get`; never `verify=False`.
- All UI copy German. Alpine store name `app`. Report partials render on `{}` without a Python `None` leaking (tests iterate every section with the fixture and with `{}`).
- A secondary layer failing never blanks the card: per-layer errors land in `errors`, values stay `None`.
- Tests hermetic: stub the module's HTTP function; never hit the network in `pytest`. Stubs must be thread-safe (the layers are fetched concurrently — key on the layer, never on call order).
- New card `stadtklima` starts at `cache_version` 1 (the registry default); no other cache_version changes.
- Session facts: `.venv/bin/python -m pytest -q` (712 tests green at baseline — verify at start); commit trailer lines
  `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>` and `Claude-Session: https://claude.ai/code/session_01ELQWyFxDQjrqLebFT6rmks`;
  work on a branch, never on main, never push.

---

## File Structure

| File | Responsibility |
|---|---|
| `redat/sources/stadtklima.py` (Task 1) | Klimaanalyse NRW GetFeatureInfo → values, PET classes, rating |
| `redat/templates/analysis/_stadtklima.html`, `redat/templates/report/_stadtklima.html` (Task 1) | card partials |
| `redat/core/sections.py`, `redat/core/tiers.py`, `redat/core/sources_meta.py`, `redat/report/builder.py` (Task 1) | wiring |
| `redat/report/climate_maps.py`, `redat/templates/report/_zensus.html` (Task 2) | statewide panel set for the PDF figure |
| `README.md`, `HANDOVER.md`, `CLAUDE.md` (Task 3) | docs |

---

### Task 1: `stadtklima` card — Klimaanalyse NRW values

**Files:**
- Create: `redat/sources/stadtklima.py`, `redat/templates/analysis/_stadtklima.html`, `redat/templates/report/_stadtklima.html`, `tests/test_stadtklima.py`
- Modify: `redat/core/sections.py` (`_fetch_stadtklima`, registry after `zensus`), `redat/core/tiers.py` (`"stadtklima": "area"`), `redat/core/sources_meta.py`, `redat/report/builder.py` (`_s_stadtklima` + SUMMARY), `tests/fixtures/report_envelopes.json`, `tests/test_analysis_sections.py` (ORDER list + tests), `tests/test_tiers.py` (first list), `tests/test_report_render.py` (needles), `tests/test_report_builder.py` (one summary test)
- Test: `tests/test_stadtklima.py`

**Interfaces:**
- Consumes: `redat.http.headers`, `redat.core.nrw.in_bbox`.
- Produces: `stadtklima._featureinfo(layer: str, lat, lon) -> dict` (HTTP seam), `stadtklima.pet_class(pet: float) -> tuple[str, str]` (label, colour), `stadtklima.get_stadtklima(lat, lon) -> dict | None` (shape in spec §3.1), `stadtklima.LAYERS`, `stadtklima.HINWEIS`.

- [ ] **Step 1: Write the failing tests**

`tests/test_stadtklima.py`:

```python
"""redat/sources/stadtklima.py — LANUV Klimaanalyse NRW GetFeatureInfo, hermetic (`_featureinfo` stubbed per layer)."""
import pytest

from redat.sources import stadtklima as sk

LAT, LON = 50.7160, 7.0748   # Bonn, Am Käferberg

BONN = {
    "59": {"KT_R02_2": "5", "Klimatoptyp": "Vorstadtklima"},
    "54": {"Classify.Pixel Value": "38.290001", "Classify.Class value": "4"},
    "52": {"Classify.Pixel Value": "43.080002", "Classify.Class value": "5"},
    "38": {"Classify.Pixel Value": "16.180000", "Classify.Class value": "2"},
    "29": {"Classify.Pixel Value": "20.450001", "Classify.Class value": "5"},
}


def stub(monkeypatch, by_layer: dict):
    calls = []

    def fi(layer, lat, lon):
        calls.append(layer)          # list.append is atomic under the GIL; assertions use set(calls)
        v = by_layer.get(layer, {})
        if isinstance(v, Exception):
            raise v
        return v
    monkeypatch.setattr(sk, "_featureinfo", fi)
    return calls


def test_layers_cover_the_five_spec_layers():
    assert sk.LAYERS == {"klimatop": "59", "pet_typisch": "54", "pet_extrem": "52", "nacht_typisch": "38", "nacht_extrem": "29"}


def test_pet_classes_follow_the_lanuv_legend():
    assert sk.pet_class(45.0) == ("extrem starke Wärmebelastung", "red")
    assert sk.pet_class(41.0) == ("starke Wärmebelastung", "orange")
    assert sk.pet_class(38.3) == ("starke Wärmebelastung", "orange")
    assert sk.pet_class(30.0) == ("moderate Wärmebelastung", "yellow")
    assert sk.pet_class(25.0) == ("leichte Wärmebelastung", "green")
    assert sk.pet_class(20.0) == ("kein thermischer Stress", "green")
    assert sk.pet_class(15.0) == ("leichter Kältestress", "green")


def test_bonn_values_and_rating(monkeypatch):
    calls = stub(monkeypatch, BONN)
    d = sk.get_stadtklima(LAT, LON)
    assert set(calls) == {"59", "54", "52", "38", "29"}
    assert d["klimatop"] == "Vorstadtklima"
    assert d["pet_typisch"] == 38.3 and d["pet_extrem"] == 43.1
    assert d["nacht_typisch"] == 16.2 and d["nacht_extrem"] == 20.5
    assert d["klasse_typisch"] == "starke Wärmebelastung" and d["klasse_extrem"] == "extrem starke Wärmebelastung"
    assert d["rating"] == "starke Wärmebelastung" and d["rating_color"] == "orange"
    assert d["errors"] == {} and "kein Messwert" in d["hinweis"]


def test_nodata_and_missing_feature_are_none(monkeypatch):
    stub(monkeypatch, {"59": {}, "54": {"Classify.Pixel Value": "NoData"}, "52": {}, "38": {"Classify.Pixel Value": "NoData"}, "29": {}})
    d = sk.get_stadtklima(LAT, LON)
    assert d["klimatop"] is None and d["pet_typisch"] is None and d["klasse_typisch"] is None and d["nacht_extrem"] is None
    assert d["rating"] == "unbekannt" and d["rating_color"] == "gray" and d["errors"] == {}


def test_rating_falls_back_to_extreme_day(monkeypatch):
    stub(monkeypatch, {**BONN, "54": {"Classify.Pixel Value": "NoData"}})
    d = sk.get_stadtklima(LAT, LON)
    assert d["pet_typisch"] is None and d["rating"] == "extrem starke Wärmebelastung" and d["rating_color"] == "red"


def test_one_layer_failing_is_isolated(monkeypatch):
    stub(monkeypatch, {**BONN, "38": RuntimeError("503 Service Unavailable")})
    d = sk.get_stadtklima(LAT, LON)
    assert d["nacht_typisch"] is None and d["pet_typisch"] == 38.3
    assert list(d["errors"]) == ["nacht_typisch"] and "503" in d["errors"]["nacht_typisch"]


def test_outside_nrw_is_none_without_http(monkeypatch):
    calls = stub(monkeypatch, BONN)
    assert sk.get_stadtklima(52.37, 4.90) is None and calls == []


def test_featureinfo_request_shape(monkeypatch):
    seen = {}

    def get(url, params=None, headers=None, timeout=None):
        seen.update(url=url, params=params, headers=headers)

        class R:
            status_code = 200
            def raise_for_status(self): pass
            def json(self): return {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {"Klimatoptyp": "Stadtklima"}}]}
        return R()
    monkeypatch.setattr(sk.httpx, "get", get)
    assert sk._featureinfo("59", 51.43, 7.005) == {"Klimatoptyp": "Stadtklima"}
    p = seen["params"]
    assert seen["url"] == sk.WMS_URL and p["REQUEST"] == "GetFeatureInfo" and p["INFO_FORMAT"] == "application/geo+json"
    assert p["LAYERS"] == "59" and p["QUERY_LAYERS"] == "59" and p["CRS"] == "EPSG:25832" and p["I"] == 50 and p["J"] == 50
    xmin, ymin, xmax, ymax = (float(v) for v in p["BBOX"].split(","))
    assert 99 < xmax - xmin < 101 and 99 < ymax - ymin < 101 and "User-Agent" in seen["headers"]
```

`tests/test_analysis_sections.py`: insert `"stadtklima"` directly after `"zensus"` in the ORDER list (line 16) and add:

```python
def test_stadtklima_passes_through_and_is_area(monkeypatch):
    from redat.core import tiers
    from redat.sources import stadtklima
    payload = {"klimatop": "Vorstadtklima", "pet_typisch": 38.3, "pet_extrem": 43.1, "nacht_typisch": 16.2, "nacht_extrem": 20.5,
               "klasse_typisch": "starke Wärmebelastung", "klasse_extrem": "extrem starke Wärmebelastung",
               "rating": "starke Wärmebelastung", "rating_color": "orange", "errors": {}, "hinweis": "x"}
    monkeypatch.setattr(stadtklima, "get_stadtklima", lambda lat, lon: payload)
    assert S._fetch_stadtklima(CTX) == payload
    assert tiers.SERVICE_TIER["stadtklima"] == "area" and S.SECTIONS["stadtklima"].cache_version == 1


def test_stadtklima_none_and_all_empty_are_empty(monkeypatch):
    from redat.sources import stadtklima
    monkeypatch.setattr(stadtklima, "get_stadtklima", lambda lat, lon: None)
    with pytest.raises(Empty, match="Nordrhein"):
        S._fetch_stadtklima(CTX)
    empty = {"klimatop": None, "pet_typisch": None, "pet_extrem": None, "nacht_typisch": None, "nacht_extrem": None,
             "klasse_typisch": None, "klasse_extrem": None, "rating": "unbekannt", "rating_color": "gray", "errors": {}, "hinweis": "x"}
    monkeypatch.setattr(stadtklima, "get_stadtklima", lambda lat, lon: empty)
    with pytest.raises(Empty, match="Klimaanalyse"):
        S._fetch_stadtklima(CTX)
    monkeypatch.setattr(stadtklima, "get_stadtklima", lambda lat, lon: {**empty, "errors": {"pet_typisch": "503"}})
    assert S._fetch_stadtklima(CTX)["errors"] == {"pet_typisch": "503"}      # an outage is an error state, not "no data"
```

`tests/test_tiers.py`: add `"stadtklima"` after `"zensus"` in the `test_every_section_has_a_tier` list (it is area, so the parcel set is unchanged). `tests/test_report_render.py` needles: `"stadtklima": ["Vorstadtklima", "38,3", "starke Wärmebelastung"]`. `tests/test_report_builder.py`: add

```python
def test_stadtklima_summary():
    from redat.report.builder import _s_stadtklima
    rating, color, fig = _s_stadtklima({"rating": "starke Wärmebelastung", "rating_color": "orange", "pet_typisch": 38.3, "nacht_typisch": 16.2, "klimatop": "Vorstadtklima"})
    assert (rating, color) == ("starke Wärmebelastung", "orange") and fig == "PET 38 °C · Nacht 16 °C · Vorstadtklima"
    assert _s_stadtklima({})[2] is None
```

Fixture entry (`tests/fixtures/report_envelopes.json`, after `zensus`):

```json
"stadtklima": {"key": "stadtklima", "tier": "area", "data": {"klimatop": "Vorstadtklima", "pet_typisch": 38.3, "pet_extrem": 43.1, "nacht_typisch": 16.2, "nacht_extrem": 20.5, "klasse_typisch": "starke Wärmebelastung", "klasse_extrem": "extrem starke Wärmebelastung", "rating": "starke Wärmebelastung", "rating_color": "orange", "errors": {}, "hinweis": "Modellwerte (FITNAH-3D, 2 m über Grund) für einen typischen bzw. extremen Sommertag — kein Messwert am Haus."}, "message": null, "source": "LANUV Klimaanalyse NRW 2026 — FITNAH-3D-Modell (WMS GetFeatureInfo)", "status": "ok", "took_ms": 812}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest -q tests/test_stadtklima.py tests/test_analysis_sections.py tests/test_tiers.py`
Expected: FAIL — `ModuleNotFoundError: redat.sources.stadtklima`, ORDER mismatch, `KeyError: 'stadtklima'`.

- [ ] **Step 3: `redat/sources/stadtklima.py`**

```python
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

from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import httpx
from pyproj import Transformer

from redat.core.nrw import in_bbox
from redat.http import headers

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
    klimatop = (props["klimatop"].get("Klimatoptyp") or "").strip() or None
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
```

- [ ] **Step 4: Wiring**

`redat/core/sections.py` (after `_fetch_zensus`):

```python
def _fetch_stadtklima(ctx: Ctx) -> dict:
    from redat.sources.stadtklima import get_stadtklima

    d = get_stadtklima(ctx.lat, ctx.lon)
    if d is None:
        raise Empty("Keine Klimaanalyse-Daten für diesen Ort (außerhalb Nordrhein-Westfalens)")
    if d["klimatop"] is None and d["pet_typisch"] is None and d["pet_extrem"] is None and not d["errors"]:
        raise Empty("Keine Klimaanalyse-Daten für diesen Ort (keine Modellzelle, z. B. Gewässer)")
    return d
```

Registry, directly after the `zensus` line: `Section("stadtklima", "Stadtklima (Klimaanalyse NRW)", "🌡️", 15, "LANUV Klimaanalyse NRW 2026 — FITNAH-3D-Modell (WMS GetFeatureInfo)", _fetch_stadtklima),`.
`tiers.py`: `"stadtklima": "area",` after `"zensus": "area"`. `sources_meta.py`: `SourceMeta(("stadtklima",), "Klimaanalyse NRW 2026 (Stadtklima)", "LANUV / LANUK NRW", "dl-de/by-2-0", "WMS GetFeatureInfo: wms.nrw.de/umwelt/klimaanpassung_klimaanalyse (Layer 59, 54, 52, 38, 29)", "area", "live"),`.
`redat/report/builder.py`:

```python
def _s_stadtklima(d):
    rating, color = _rated(d)
    parts = []
    if d.get("pet_typisch") is not None:
        parts.append(f"PET {d['pet_typisch']:.0f} °C")
    if d.get("nacht_typisch") is not None:
        parts.append(f"Nacht {d['nacht_typisch']:.0f} °C")
    if d.get("klimatop"):
        parts.append(d["klimatop"])
    return rating, color, " · ".join(parts) or None
```

and `"stadtklima": _s_stadtklima,` in `SUMMARY` next to `"zensus"`. (`_rated(d)` already returns `(d.get("rating"), d.get("rating_color") or "gray")` — check its exact signature in builder.py and use it the way `_s_denkmal` does.)

`redat/templates/analysis/_stadtklima.html`:

```html
<div class="flex items-center gap-4">
    <span class="px-3 py-1 rounded-full font-bold" :class="$store.app.getAirQualityColor(d.rating_color)" x-text="d.rating"></span>
    <div class="text-sm text-gray-500">Thermische Belastung an einem typischen Sommertag · Klimatop: <span class="text-gray-900" x-text="d.klimatop || '—'"></span></div>
</div>
<table class="mt-4 w-full text-sm">
    <thead><tr class="text-left text-xs text-gray-500"><th class="py-1"></th><th class="py-1">Typischer Sommertag</th><th class="py-1">Extremer Sommertag</th></tr></thead>
    <tbody>
        <tr><td class="py-1 text-gray-600">Gefühlte Temperatur (PET, tags)</td>
            <td class="py-1" x-text="d.pet_typisch != null ? $store.app.formatNumber(d.pet_typisch, 1) + ' °C — ' + (d.klasse_typisch || '') : '—'"></td>
            <td class="py-1" x-text="d.pet_extrem != null ? $store.app.formatNumber(d.pet_extrem, 1) + ' °C — ' + (d.klasse_extrem || '') : '—'"></td></tr>
        <tr><td class="py-1 text-gray-600">Lufttemperatur nachts (4 Uhr)</td>
            <td class="py-1" x-text="d.nacht_typisch != null ? $store.app.formatNumber(d.nacht_typisch, 1) + ' °C' : '—'"></td>
            <td class="py-1" x-text="d.nacht_extrem != null ? $store.app.formatNumber(d.nacht_extrem, 1) + ' °C' : '—'"></td></tr>
    </tbody>
</table>
<p class="mt-3 text-xs text-gray-500" x-text="d.hinweis"></p>
<p class="mt-1 text-xs text-red-700" x-show="d.errors && Object.keys(d.errors).length">Teile der Klimaanalyse waren nicht abrufbar.</p>
<p class="mt-1 text-xs text-gray-500">Quelle: <a class="underline" href="https://www.klimaatlas.nrw.de/" target="_blank" rel="noopener">LANUV Klimaanalyse NRW 2026</a> (FITNAH-3D, VDI 3787). PET-Klassen: ≤ 23 kein Stress · ≤ 29 leicht · ≤ 35 moderat · ≤ 41 stark · &gt; 41 extrem.</p>
```

(`$store.app.formatNumber(value, decimals)` — check its signature in `redat/static/redat.js`; if it takes no decimals argument, render `d.pet_typisch.toFixed(1).replace('.', ',')` instead.)

`redat/templates/report/_stadtklima.html`:

```jinja
<div class="kpis">
  <div class="kpi">
    <div class="label">Thermische Belastung, typischer Sommertag</div>
    <div class="value"><span class="chip {{ rating_class(d.get('rating_color')) }}">{{ d.get("rating") or "—" }}</span></div>
  </div>
  <div class="kpi"><div class="label">Klimatop</div><div class="value">{{ d.get("klimatop") or "—" }}</div></div>
</div>
<table>
  <thead><tr><th></th><th>Typischer Sommertag</th><th>Extremer Sommertag</th></tr></thead>
  <tbody>
    <tr><td>Gefühlte Temperatur (PET, tags)</td>
      <td>{% if d.get("pet_typisch") is not none %}{{ d.pet_typisch|fmt_num(1) }} °C — {{ d.get("klasse_typisch") or "" }}{% else %}—{% endif %}</td>
      <td>{% if d.get("pet_extrem") is not none %}{{ d.pet_extrem|fmt_num(1) }} °C — {{ d.get("klasse_extrem") or "" }}{% else %}—{% endif %}</td></tr>
    <tr><td>Lufttemperatur nachts (4 Uhr)</td>
      <td>{% if d.get("nacht_typisch") is not none %}{{ d.nacht_typisch|fmt_num(1) }} °C{% else %}—{% endif %}</td>
      <td>{% if d.get("nacht_extrem") is not none %}{{ d.nacht_extrem|fmt_num(1) }} °C{% else %}—{% endif %}</td></tr>
  </tbody>
</table>
<p class="footnote">{{ d.get("hinweis") or "" }} PET-Klassen (VDI 3787): ≤ 23 °C kein thermischer Stress · ≤ 29 leicht · ≤ 35 moderat · ≤ 41 stark · &gt; 41 extrem. Quelle: LANUV Klimaanalyse NRW 2026.{% if d.get("errors") %} Teile der Klimaanalyse waren nicht abrufbar.{% endif %}</p>
```

(`fmt_num` — check `redat/report/render.py` for its signature; if it takes no decimals argument, use `{{ "%.1f"|format(d.pet_typisch)|replace(".", ",") }}`.)

- [ ] **Step 5: Test, commit**

```bash
.venv/bin/python -m pytest -q
git add redat/sources/stadtklima.py redat/templates/analysis/_stadtklima.html redat/templates/report/_stadtklima.html tests/test_stadtklima.py redat/core/ redat/report/builder.py tests/fixtures/report_envelopes.json tests/test_analysis_sections.py tests/test_tiers.py tests/test_report_render.py tests/test_report_builder.py
git commit -m "feat(stadtklima): Klimaanalyse NRW card — PET, night temperature and Klimatop at the point"
```

Live check (once): `GEOAPIFY_API_KEY=x .venv/bin/python -c "from redat.sources.stadtklima import get_stadtklima as g; print(g(50.7160, 7.0748)); print(g(51.4300, 7.0050))"` → Bonn Vorstadtklima / PET 38.3 / night 16.2; Essen Stadtklima / PET 40.3.

---

### Task 2: "Grün und Hitze" statewide panels

**Files:**
- Modify: `redat/report/climate_maps.py`, `redat/templates/report/_zensus.html`, `tests/test_climate_maps.py`, `tests/test_report_render.py` (one render test)
- Test: `tests/test_climate_maps.py`

**Interfaces:**
- Consumes: `redat.core.nrw.RVR_BBOX_WGS84`, `in_bbox`; `climate_maps.bbox_2km`, `decorate`, `_get_png` (unchanged seams — `regionalplan_map.py` imports `WIDTH`, `HEIGHT`, `bbox_2km`, `decorate`, so their names and signatures stay).
- Produces: `climate_maps.RVR_PANELS`, `climate_maps.NRW_PANELS` (tuples of `Panel`), `climate_maps.bbox_2km_3857(lat, lon)`, `render_climate_maps(lat, lon)` result gains `"variant": "rvr" | "nrw"`; panels keep `{"key", "title", "image", "legend"}`.

- [ ] **Step 1: Write the failing tests** (`tests/test_climate_maps.py` — keep the three existing tests; add)

```python
import math

BONN = (50.7160, 7.0748)


def test_outside_rvr_uses_copernicus_and_klimaanalyse_panels(monkeypatch):
    calls = []

    def fake(url, params):
        calls.append((url, params))
        if params.get("REQUEST") == "GetLegendGraphic":
            return _png((276, 126), (200, 50, 50))
        return _png((cm.WIDTH, cm.HEIGHT), (120, 160, 120))
    monkeypatch.setattr(cm, "_get_png", fake)
    out = cm.render_climate_maps(*BONN)
    assert out["variant"] == "nrw" and [p["key"] for p in out["panels"]] == ["baumkronen", "pet"]
    assert "Copernicus" in out["attribution"] and "Klimaanalyse" in out["attribution"] and out["error"] is None
    by_layer = {p["LAYERS"]: (u, p) for u, p in calls if p.get("REQUEST") == "GetMap"}
    hrl_url, hrl = by_layer["HRL_TreeCoverDensity_2018:TCD_MosaicSymbology"]
    assert hrl_url == cm.HRL_URL and hrl["CRS"] == "EPSG:3857"
    xmin, ymin, xmax, ymax = (float(v) for v in hrl["BBOX"].split(","))
    assert abs((xmax - xmin) - 2000 / math.cos(math.radians(BONN[0]))) < 1.0
    pet_url, pet = by_layer["54"]
    assert pet_url == cm.KLIMA_URL and pet["CRS"] == "EPSG:25832"
    legends = [p for u, p in calls if p.get("REQUEST") == "GetLegendGraphic"]
    assert [p["LAYER"] for p in legends] == ["54"]                       # the Copernicus ramp legend is skipped on purpose
    assert out["panels"][0]["legend"] is None and out["panels"][1]["legend"]


def test_inside_rvr_keeps_the_rvr_panels(monkeypatch):
    monkeypatch.setattr(cm, "_get_png", lambda url, params: _png((cm.WIDTH, cm.HEIGHT), (1, 2, 3)))
    out = cm.render_climate_maps(51.43, 7.005)
    assert out["variant"] == "rvr" and [p["key"] for p in out["panels"]] == ["beschirmung", "oberflaechentemperatur"]


def test_bbox_2km_3857_scales_with_latitude():
    xmin, ymin, xmax, ymax = cm.bbox_2km_3857(*BONN)
    assert abs((xmax - xmin) - 2000 / math.cos(math.radians(BONN[0]))) < 1.0
    assert abs((ymax - ymin) - 1500 / math.cos(math.radians(BONN[0]))) < 1.0
```

`tests/test_report_render.py` — add:

```python
def test_zensus_partial_explains_the_statewide_climate_panels():
    fig = {"variant": "nrw", "panels": [{"key": "baumkronen", "title": "Baumkronendichte 2018", "image": base64.b64encode(b"png").decode(), "legend": None},
                                         {"key": "pet", "title": "PET", "image": None, "legend": None}],
           "attribution": "© Copernicus · LANUV", "error": "PET: down"}
    html = render_section_html("zensus", FIXTURES["zensus"]["data"], **{**EXTRA, "climate_maps": fig})
    assert "Baumkronendichte" in html and "Copernicus" in html and "Karte nicht verfügbar" in html and "None" not in html
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest -q tests/test_climate_maps.py tests/test_report_render.py`
Expected: FAIL — `KeyError: 'variant'`, `AttributeError: bbox_2km_3857`.

- [ ] **Step 3: `redat/report/climate_maps.py`**

Replace `BASE`/`PANELS`/`ATTRIBUTION` and the request builders with a panel type carrying its own service, CRS and legend flag; keep `WIDTH`, `HEIGHT`, `WINDOW_M`, `TIMEOUT_S`, `bbox_2km`, `_get_png`, `_b64`, `decorate` as they are.

```python
import math
from typing import NamedTuple

from redat.core.nrw import RVR_BBOX_WGS84, in_bbox

RVR_BASE = "https://services-rvr.geoportal.ruhr/umon/"
HRL_URL = "https://image.discomap.eea.europa.eu/arcgis/services/GioLandPublic/HRL_TreeCoverDensity_2018/ImageServer/WMSServer"
KLIMA_URL = "https://www.wms.nrw.de/umwelt/klimaanpassung_klimaanalyse"


class Panel(NamedTuple):
    key: str
    title: str
    url: str
    layer: str
    style: str
    crs: str            # "EPSG:25832" (bbox_2km) or "EPSG:3857" (bbox_2km_3857)
    legend: bool        # False when the service's GetLegendGraphic is unusable in print (Copernicus: 236 × 2040 px ramp)


RVR_PANELS = (
    Panel("beschirmung", "Beschirmungsgrad (Baumkronen)", RVR_BASE + "veg_schirm", "beschirmungsgrad", "default", "EPSG:25832", True),
    Panel("oberflaechentemperatur", "Oberflächentemperatur 13:30 Uhr (Sommer)", RVR_BASE + "oftemp", "Oberflaechentemperatur_1330", "day", "EPSG:25832", True),
)
NRW_PANELS = (
    Panel("baumkronen", "Baumkronendichte 2018 (Copernicus, 10 m)", HRL_URL, "HRL_TreeCoverDensity_2018:TCD_MosaicSymbology", "", "EPSG:3857", False),
    Panel("pet", "Thermische Belastung (PET), typischer Sommertag", KLIMA_URL, "54", "", "EPSG:25832", True),
)
ATTRIBUTIONS = {
    "rvr": "© Regionalverband Ruhr, Umweltmonitoring (Beschirmungsgrad 10 m; Oberflächentemperatur MODIS 1 km, Sommer-Median)",
    "nrw": "© Copernicus Land Monitoring Service, HRL Tree Cover Density 2018 (10 m, Anteil Baumkronen 0–100 %, dunkler = dichter) · LANUV Klimaanalyse NRW 2026 (FITNAH-3D, PET tags, typischer Sommertag)",
}
_TO_MERC = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)


def bbox_2km_3857(lat: float, lon: float) -> tuple[float, float, float, float]:
    """The same 2 km × 1.5 km ground window in Web Mercator, whose metres shrink by cos(lat)."""
    x, y = _TO_MERC.transform(lon, lat)
    k = 1.0 / math.cos(math.radians(lat))
    hw, hh = WINDOW_M / 2 * k, WINDOW_M * HEIGHT / WIDTH / 2 * k
    return x - hw, y - hh, x + hw, y + hh


def _fetch_map(url: str, bbox, layer: str, style: str, crs: str = "EPSG:25832") -> Image.Image:
    raw = _get_png(url, {"SERVICE": "WMS", "VERSION": "1.3.0", "REQUEST": "GetMap", "CRS": crs,
                         "BBOX": ",".join(f"{v:.3f}" for v in bbox), "WIDTH": WIDTH, "HEIGHT": HEIGHT,
                         "FORMAT": "image/png", "LAYERS": layer, "STYLES": style, "TRANSPARENT": "TRUE"})
    im = Image.open(io.BytesIO(raw))
    im.load()
    return im.convert("RGBA").resize((WIDTH, HEIGHT))


def render_climate_maps(lat: float, lon: float) -> dict:
    variant = "rvr" if in_bbox(lat, lon, RVR_BBOX_WGS84) else "nrw"
    panels_def = RVR_PANELS if variant == "rvr" else NRW_PANELS
    bboxes = {"EPSG:25832": bbox_2km(lat, lon), "EPSG:3857": bbox_2km_3857(lat, lon)}
    errors: list[str] = []

    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as ex:
        futures = {}
        for p in panels_def:
            futures[p.key, "map"] = ex.submit(_fetch_map, p.url, bboxes[p.crs], p.layer, p.style, p.crs)
            if p.legend:
                futures[p.key, "legend"] = ex.submit(_fetch_legend, p.url, p.layer, p.style)

        panels = []
        for p in panels_def:
            image: Optional[str] = None
            try:
                im = futures[p.key, "map"].result()
                buf = io.BytesIO()
                decorate(im, p.title).convert("RGB").save(buf, format="PNG", optimize=True)
                image = _b64(buf.getvalue())
            except Exception as e:  # noqa: BLE001 — a missing panel is a placeholder, never a failed PDF
                logger.warning("climate map %s failed: %s", p.key, e)
                errors.append(f"{p.title}: {e}")

            legend: Optional[str] = None
            if p.legend:
                try:
                    legend = _b64(futures[p.key, "legend"].result())
                except Exception as e:  # noqa: BLE001
                    logger.warning("climate legend %s failed: %s", p.key, e)
                    errors.append(f"Legende {p.title}: {e}")

            panels.append({"key": p.key, "title": p.title, "image": image, "legend": legend})

    return {"variant": variant, "panels": panels, "attribution": ATTRIBUTIONS[variant], "error": " · ".join(errors) or None}
```

Keep `_fetch_legend` unchanged. `PANELS = RVR_PANELS` may stay as an alias for anything that imported it (grep; nothing outside this module does today). Module docstring: describe both panel sets and the EPSG:3857 rule (spec §2.2).

- [ ] **Step 4: `redat/templates/report/_zensus.html`** — replace the footnote line inside `{% if climate_maps %}`:

```jinja
<p class="footnote">Ausschnitt ca. 2 × 1,5 km, Punkt im Zentrum. {% if climate_maps.variant == "nrw" %}Viel Baumkronen im Umfeld dämpfen Sommerhitze; die PET-Karte zeigt die gefühlte Temperatur an einem typischen Sommertag (Modell, 100-m-Raster) — Klassen wie auf der Stadtklima-Karte.{% else %}Viel Baumkronen im Umfeld dämpfen Sommerhitze; die Oberflächentemperatur zeigt Hitzeinseln (1-km-Raster, kein Messwert am Haus).{% endif %} {{ climate_maps.attribution }}{% if climate_maps.error %} · Hinweis: {{ climate_maps.error }}{% endif %}</p>
```

- [ ] **Step 5: Test, commit**

```bash
.venv/bin/python -m pytest -q
git add redat/report/climate_maps.py redat/templates/report/_zensus.html tests/test_climate_maps.py tests/test_report_render.py
git commit -m "feat(report): statewide Grün-und-Hitze panels — Copernicus canopy and Klimaanalyse PET outside the Ruhr"
```

Live check (once): `GEOAPIFY_API_KEY=x .venv/bin/python -c "from redat.report.climate_maps import render_climate_maps as r; o = r(50.716, 7.075); print(o['variant'], o['error'], [ (p['key'], bool(p['image']), bool(p['legend'])) for p in o['panels']])"` → `nrw None [('baumkronen', True, False), ('pet', True, True)]`.

---

### Task 3: Documentation and verification

**Files:** `README.md`, `HANDOVER.md`, `CLAUDE.md`

- [ ] **Step 1: README** — add the `stadtklima` row to the "Nachbarschaft & Versorgung" table (after `zensus`): "Stadtklima (`stadtklima`, area) | Klimatop, gefühlte Temperatur (PET) and night air temperature for a typical and an extreme summer day, LANUV model | LANUV Klimaanalyse NRW 2026 (WMS GetFeatureInfo)"; update "28 data cards" → 29 in the intro; in the PDF-figures paragraph say the "Grün und Hitze" panels are RVR layers in the Ruhr and Copernicus canopy + Klimaanalyse PET elsewhere; the coverage paragraph no longer lists the RVR climate panels as a Ruhr-only gap.
- [ ] **Step 2: HANDOVER** — Status line 29 cards / test count; work-log entry "**Tier 4 — Stadtklima** (commits …)" naming the two tasks, the service facts (numbered layers, geo+json GetFeatureInfo, `NoData` string, Copernicus WMS is EPSG:3857-only), and that the RVR panels remain in the Ruhr.
- [ ] **Step 3: CLAUDE.md** — card count 29, test count from `pytest -q`, one Rules line: "Klimaanalyse NRW WMS: layers are numbers, GetFeatureInfo `application/geo+json`, rasters answer `Classify.Pixel Value` (`"NoData"` string); the Copernicus HRL WMS only serves EPSG:3857/4326 — request the 2 km window via `climate_maps.bbox_2km_3857`."
- [ ] **Step 4: Verification** — full suite; with the key from `/home/mitja/nrw-redat/.env` (`set -a; source …; set +a`, never print it) start `REDAT_DATA_DIR=<scratch> .venv/bin/uvicorn redat.app:app --port 8201` and call `GET /api/v1/section/stadtklima?lat=50.7160&lon=7.0748&precision=building&fresh=1` (Bonn: Vorstadtklima, PET 38.3, rating "starke Wärmebelastung") and the same for Essen `51.4300/7.0050` (Stadtklima, PET 40.3) and Amsterdam `52.37/4.90` (empty, "außerhalb Nordrhein-Westfalens"); render the Bonn report HTML via `render_report_html` with a real `render_climate_maps(50.716, 7.075)` result and check it contains "Baumkronendichte" and "Stadtklima". Stop the server. Record every value in the report; local Chromium is absent, so the controller checks the PDF in production.
- [ ] **Step 5: Commit** — `git commit -m "docs: Tier-4 Stadtklima — README card, HANDOVER log, CLAUDE.md"` plus trailers.
