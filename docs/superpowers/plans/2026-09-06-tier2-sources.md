# Tier-2 Sources Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend three cards (Bergbau + Berechtigungen, Starkregen + Gelände, Lärm + Fluglärm/Ruhige Gebiete), add one card (Ladesäulen), add two PDF figures (historic maps, Grün & Hitze), and prepare the data-gated EGMS ground-motion block on the Bergbau card.

**Architecture:** Same shape as Tier 1: one module per source in `redat/sources/` with a single HTTP function as monkeypatch point (or a static grid built by a `scripts/build_*.py`), the card's `_fetch_*` in `redat/core/sections.py` merges secondary data with isolated errors, partials in `redat/templates/analysis/` and `redat/templates/report/`, `builder.SUMMARY`, fixture envelope, `cache_version` bump on extended cards. PDF figures follow `redat/report/noise_map.py` (Pillow composites, base64 in the template context, `_get_png` as the test seam).

**Tech Stack:** Python 3.12, httpx, numpy (already a dependency), Pillow, shapely, geopandas (build scripts only), FastAPI + Jinja2, Alpine.js, pytest.

**Spec:** `docs/superpowers/specs/2026-09-06-tier2-sources-design.md` — read it first; every endpoint, field and sample value comes from it.

## Global Constraints

- Every outbound call passes `headers=headers()` from `redat/http.py`; never bare `httpx.get`; never `verify=False`.
- All UI copy German. Alpine store name `app`. Report partials render on `{}` without a Python `None` leaking (tests iterate every section with the fixture and with `{}`).
- Static data under `redat/data/` is committed; build scripts carry the download URL in their docstring.
- Cache: `bergbau`, `starkregen`, `noise` gain data → `cache_version` 1 → 2 (`bergbau` → 3 in Task 7). New card `ladesaeulen` starts at 1.
- A secondary source failing never blanks the card: the extension lands under its own key with a sibling `*_error` string.
- Tests hermetic: stub the module's HTTP function / grid loader; never hit the network in `pytest`.
- Session facts: `.venv/bin/python -m pytest -q` (605 tests green at baseline — verify the number at start); commit trailer lines
  `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>` and `Claude-Session: https://claude.ai/code/session_01ELQWyFxDQjrqLebFT6rmks`;
  work on a branch, never on main, never push.
- Data-gated items are NOT in this plan: Altlasten Essen/Bochum (requests sent), Hebesätze (Regionaldatenbank registration), Sozialatlas, Wahlbezirke.

---

## File Structure

| File | Responsibility |
|---|---|
| `scripts/build_bergbauberechtigungen.py` (Task 1) | opengeodata shapefile → `redat/data/bergbauberechtigungen.geojson.gz` (window crop, WGS84) |
| `redat/sources/bergrechte.py` (Task 1) | Berechtigungen containing the point |
| `redat/sources/gelaende.py` (Task 2) | DGM WCS tile → height, Lage, slope |
| `redat/sources/noise_extra.py` (Task 3) | Essen Fluglärm layers, Ruhige Gebiete Essen/Bochum |
| `scripts/build_ladesaeulen.py`, `redat/sources/ladesaeulen.py` (Task 4) | BNetzA CSV crop → grid; nearest chargers |
| `redat/report/history_maps.py` (Task 5) | four historic map panels |
| `redat/report/climate_maps.py` (Task 6) | two RVR climate panels + legend images |
| `scripts/build_egms.py`, `redat/sources/bodenbewegung.py` (Task 7) | EGMS GeoTIFF crop → grid; vertical velocity at the point |
| `redat/core/sections.py`, `redat/core/tiers.py`, `redat/core/sources_meta.py`, `redat/report/builder.py`, `redat/report/service.py` | wiring |
| `redat/templates/analysis/_*.html`, `redat/templates/report/_*.html` | partials |
| `tests/fixtures/report_envelopes.json`, `tests/test_*.py` | fixtures and tests |

---

### Task 1: Bergbauberechtigungen on the Bergbau card

**Files:**
- Create: `scripts/build_bergbauberechtigungen.py`, `redat/sources/bergrechte.py`, `redat/data/bergbauberechtigungen.geojson.gz`
- Modify: `redat/core/sections.py` (`_fetch_bergbau`, `Section("bergbau", …, cache_version=2)`), `redat/templates/analysis/_bergbau.html`, `redat/templates/report/_bergbau.html`, `redat/report/builder.py` (`_s_bergbau`), `tests/fixtures/report_envelopes.json`, `tests/test_analysis_sections.py`
- Test: `tests/test_bergrechte.py`, `tests/test_build_bergbauberechtigungen.py`

**Interfaces:**
- Produces: `bergrechte.lookup(lat, lon) -> Optional[list[dict]]` (None when the grid file is missing; else the Berechtigungen containing the point, Bergwerkseigentum/Bewilligung first); item keys `feld, art, kurz, bodenschatz, inhaber, seit, erloschen, groesse`; `bergrechte._load()` (lru_cached loader, monkeypatch point); `bergrechte.kurz(art) -> str`. Build script functions `crop(gdf, bbox) -> GeoDataFrame`, `to_features(gdf) -> list[dict]`.

- [ ] **Step 1: Write the failing tests**

`tests/test_build_bergbauberechtigungen.py`:

```python
import importlib.util
from pathlib import Path

import geopandas as gpd
from shapely.geometry import box

_spec = importlib.util.spec_from_file_location("build_bb", Path(__file__).resolve().parent.parent / "scripts" / "build_bergbauberechtigungen.py")
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


def _gdf():
    return gpd.GeoDataFrame(
        {"FELDESNUMM": ["4000138701", "1"], "BERECHTIGU": ["aufrechterhaltenes Bergwerkseigentum", "Bewilligung"],
         "BODENSCHAT": ["Eisenerz", "Steinkohle"], "FELDESNAME": ["Neu Essen", "Fern"], "FELDESGROE": ["140 110 991 m²", "1 m²"],
         "ENTSTEHUNG": ["23.01.1791", "-"], "LAUFZEIT_V": ["-", "-"], "LAUFZEIT_B": ["-", "-"], "ERLOSCHEN": ["nein", "ja"],
         "RECHTSINHA": ["TRATON SE", "X"], "SCHLUESSEL": ["Eisenerze", "Kohle"], "SCHLUESS00": ["4", "1"]},
        geometry=[box(360000, 5698000, 362000, 5700000), box(200000, 5500000, 201000, 5501000)], crs="EPSG:25832")


def test_crop_keeps_only_window_features_in_wgs84():
    out = mod.crop(_gdf(), mod.BBOX_WGS84)
    assert len(out) == 1 and out.crs.to_epsg() == 4326 and out.iloc[0]["FELDESNAME"] == "Neu Essen"


def test_to_features_maps_fields_and_booleans():
    feats = mod.to_features(mod.crop(_gdf(), mod.BBOX_WGS84))
    p = feats[0]["properties"]
    assert p == {"feld": "Neu Essen", "art": "aufrechterhaltenes Bergwerkseigentum", "bodenschatz": "Eisenerz", "inhaber": "TRATON SE",
                 "seit": "23.01.1791", "bis": None, "erloschen": False, "groesse": "140 110 991 m²", "nummer": "4000138701"}
    assert feats[0]["geometry"]["type"] in ("Polygon", "MultiPolygon")
```

`tests/test_bergrechte.py`:

```python
import pytest

from redat.sources import bergrechte


def feat(name, art, ring, **props):
    base = {"feld": name, "art": art, "bodenschatz": "Steinkohle", "inhaber": "RAG AKTIENGESELLSCHAFT", "seit": "01.01.1900", "bis": None,
            "erloschen": False, "groesse": "1 000 m²", "nummer": "1"}
    base.update(props)
    return {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [ring]}, "properties": base}


BIG = [[6.99, 51.42], [7.02, 51.42], [7.02, 51.44], [6.99, 51.44], [6.99, 51.42]]
FAR = [[7.20, 51.48], [7.21, 51.48], [7.21, 51.49], [7.20, 51.49], [7.20, 51.48]]
GRID = {"type": "FeatureCollection", "features": [
    feat("Metropole Ruhr", "Erlaubnis zu gewerblichen Zwecken", BIG, bodenschatz="Erdwärme", inhaber="Deutsche ErdWärme GmbH & Co. KG; DMT GmbH", seit=None),
    feat("Neu Essen", "aufrechterhaltenes Bergwerkseigentum", BIG, bodenschatz="Eisenerz", inhaber="TRATON SE", seit="23.01.1791"),
    feat("Fern", "Bewilligung", FAR),
]}


def test_kurz_labels():
    assert bergrechte.kurz("aufrechterhaltenes Bergwerkseigentum") == "Bergwerkseigentum"
    assert bergrechte.kurz("Erlaubnis zu gewerblichen Zwecken") == "Erlaubnis (Aufsuchung)"
    assert bergrechte.kurz("Bewilligung") == "Bewilligung"
    assert bergrechte.kurz("irgendwas") == "irgendwas"


def test_lookup_returns_containing_fields_ownership_first(monkeypatch):
    monkeypatch.setattr(bergrechte, "_load", lambda: GRID)
    items = bergrechte.lookup(51.4300, 7.0050)
    assert [i["feld"] for i in items] == ["Neu Essen", "Metropole Ruhr"]
    assert items[0] == {"feld": "Neu Essen", "art": "aufrechterhaltenes Bergwerkseigentum", "kurz": "Bergwerkseigentum", "bodenschatz": "Eisenerz",
                        "inhaber": "TRATON SE", "seit": "23.01.1791", "erloschen": False, "groesse": "1 000 m²"}
    assert items[1]["kurz"] == "Erlaubnis (Aufsuchung)" and items[1]["seit"] is None


def test_lookup_empty_list_when_nothing_contains_point_and_none_without_grid(monkeypatch):
    monkeypatch.setattr(bergrechte, "_load", lambda: GRID)
    assert bergrechte.lookup(51.30, 6.90) == []
    monkeypatch.setattr(bergrechte, "_load", lambda: None)
    assert bergrechte.lookup(51.43, 7.0) is None
```

Add to `tests/test_analysis_sections.py` (replace `test_bergbau_passes_through_and_is_area` and `test_bergbau_none_is_empty` with):

```python
BERGBAU_RAW = {"cell_id": "x", "cell_size_m": 500, "authority": "Geologischer Dienst NRW", "updated": None, "items": [], "rating": "Unauffällig", "rating_color": "green"}


def test_bergbau_merges_berechtigungen(monkeypatch):
    from redat.core import tiers
    from redat.sources import bergbau, bergrechte
    monkeypatch.setattr(bergbau, "get_bergbau", lambda lat, lon: dict(BERGBAU_RAW))
    rows = [{"feld": "Neu Essen", "art": "aufrechterhaltenes Bergwerkseigentum", "kurz": "Bergwerkseigentum", "bodenschatz": "Eisenerz",
             "inhaber": "TRATON SE", "seit": "23.01.1791", "erloschen": False, "groesse": "1 m²"}]
    monkeypatch.setattr(bergrechte, "lookup", lambda lat, lon: rows)
    d = S._fetch_bergbau(CTX)
    assert d["berechtigungen"] == rows and d["berechtigungen_error"] is None and d["rating"] == "Unauffällig"
    assert tiers.SERVICE_TIER["bergbau"] == "area" and S.SECTIONS["bergbau"].cache_version == 2


def test_bergbau_missing_grid_is_reported_not_fatal(monkeypatch):
    from redat.sources import bergbau, bergrechte
    monkeypatch.setattr(bergbau, "get_bergbau", lambda lat, lon: dict(BERGBAU_RAW))
    monkeypatch.setattr(bergrechte, "lookup", lambda lat, lon: None)
    d = S._fetch_bergbau(CTX)
    assert d["berechtigungen"] is None and "bergbauberechtigungen.geojson.gz" in d["berechtigungen_error"]


def test_bergbau_none_is_empty(monkeypatch):
    from redat.sources import bergbau
    monkeypatch.setattr(bergbau, "get_bergbau", lambda lat, lon: None)
    with pytest.raises(Empty):
        S._fetch_bergbau(CTX)
```

`tests/test_report_render.py::test_fixture_content_is_present`: change the `"bergbau"` needles to `["Verlassene Tagesöffnungen", "500 m-Planquadrat", "Neu Essen", "Bergwerkseigentum"]`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_bergrechte.py tests/test_build_bergbauberechtigungen.py tests/test_analysis_sections.py -q`
Expected: `ModuleNotFoundError` for both new modules; the bergbau section tests fail on missing keys.

- [ ] **Step 3: Build script**

`scripts/build_bergbauberechtigungen.py`:

```python
"""Crop the NRW Bergbauberechtigungen to the Essen/Bochum window → redat/data/bergbauberechtigungen.geojson.gz.

Input: https://www.opengeodata.nrw.de/produkte/geologie/bergbau/bebu/BergbauberechtigungenNRW_EPSG25832_Shape.zip
(Bezirksregierung Arnsberg, dl-de/by-2-0, 860 KB, 5,361 polygons statewide, refreshed on opengeodata a few times a
year). Fields: FELDESNUMM, BERECHTIGU (Bergwerkseigentum / Bewilligung / Erlaubnis …), BODENSCHAT, FELDESNAME,
FELDESGROE ("140 110 991 m²"), ENTSTEHUNG ("23.01.1791" or "-"), LAUFZEIT_V/_B, ERLOSCHEN (ja/nein), RECHTSINHA.

Usage:
    .venv/bin/python scripts/build_bergbauberechtigungen.py --shape /tmp/BergbauberechtigungenNRW_EPSG25832_Shape.zip
"""
from __future__ import annotations

import argparse
import gzip
import json
from datetime import date
from pathlib import Path

import geopandas as gpd
from shapely.geometry import box, mapping

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "redat" / "data" / "bergbauberechtigungen.geojson.gz"
BBOX_WGS84 = (6.85, 51.33, 7.40, 51.56)   # same window as the Zensus/Unfallatlas grids


def _clean(v) -> str | None:
    s = str(v).strip() if v is not None else ""
    return None if s in ("", "-", "None", "nan") else s


def crop(gdf: gpd.GeoDataFrame, bbox: tuple[float, float, float, float]) -> gpd.GeoDataFrame:
    w = gdf.to_crs("EPSG:4326")
    return w[w.intersects(box(*bbox))].copy()


def to_features(gdf: gpd.GeoDataFrame) -> list[dict]:
    feats = []
    for _, r in gdf.iterrows():
        feats.append({"type": "Feature", "geometry": mapping(r.geometry), "properties": {
            "feld": _clean(r.get("FELDESNAME")), "art": _clean(r.get("BERECHTIGU")), "bodenschatz": _clean(r.get("BODENSCHAT")),
            "inhaber": _clean(r.get("RECHTSINHA")), "seit": _clean(r.get("ENTSTEHUNG")), "bis": _clean(r.get("LAUFZEIT_B")),
            "erloschen": str(r.get("ERLOSCHEN")).strip().lower() == "ja", "groesse": _clean(r.get("FELDESGROE")),
            "nummer": _clean(r.get("FELDESNUMM")),
        }})
    return feats


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--shape", required=True, help="BergbauberechtigungenNRW_EPSG25832_Shape.zip")
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args()
    feats = to_features(crop(gpd.read_file(f"zip://{a.shape}"), BBOX_WGS84))
    a.out.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(a.out, "wt", encoding="utf-8") as fh:
        json.dump({"type": "FeatureCollection", "built": date.today().isoformat(), "features": feats}, fh, ensure_ascii=False, separators=(",", ":"))
    print(f"wrote {a.out}: {len(feats)} Berechtigungen in the window")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Source module**

`redat/sources/bergrechte.py`:

```python
"""Bergbauberechtigungen — which mining rights (Bergwerkseigentum, Bewilligung, Erlaubnis) cover the point.

Data: redat/data/bergbauberechtigungen.geojson.gz (scripts/build_bergbauberechtigungen.py) from the open
Bezirksregierung Arnsberg dataset. A Berechtigung is a *right* to mine or explore, not evidence of workings —
the GDU Planquadrat on the same card is the hazard signal; the right tells the buyer who may still claim
Bergschäden liability (RAG, E.ON, …) and whether an Erlaubnis for Erdwärme/Kohlenwasserstoffe exists.
`_load` is the monkeypatch point.
"""
from __future__ import annotations

import gzip
import json
from functools import lru_cache
from pathlib import Path
from typing import Optional

from shapely.geometry import Point, shape

GRID_PATH = Path(__file__).resolve().parent.parent / "data" / "bergbauberechtigungen.geojson.gz"
_KURZ = {
    "aufrechterhaltenes Bergwerkseigentum": "Bergwerkseigentum",
    "Bewilligung": "Bewilligung",
    "Erlaubnis zu gewerblichen Zwecken": "Erlaubnis (Aufsuchung)",
    "Erlaubnis zu wissenschaftlichen Zwecken": "Erlaubnis (Forschung)",
}
_ORDER = {"Bergwerkseigentum": 0, "Bewilligung": 1, "Erlaubnis (Aufsuchung)": 2, "Erlaubnis (Forschung)": 3}


@lru_cache(maxsize=1)
def _load() -> Optional[dict]:
    try:
        with gzip.open(GRID_PATH, "rt", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def kurz(art: Optional[str]) -> str:
    return _KURZ.get(art or "", art or "")


def lookup(lat: float, lon: float) -> Optional[list[dict]]:
    """Berechtigungen whose field contains the point, ownership rights first; None when the file is missing."""
    grid = _load()
    if not grid:
        return None
    pt = Point(lon, lat)
    out = []
    for f in grid.get("features") or []:
        try:
            if not shape(f["geometry"]).contains(pt):
                continue
        except (KeyError, TypeError, ValueError):
            continue
        p = f.get("properties") or {}
        k = kurz(p.get("art"))
        out.append({"feld": p.get("feld"), "art": p.get("art"), "kurz": k, "bodenschatz": p.get("bodenschatz"),
                    "inhaber": p.get("inhaber"), "seit": p.get("seit"), "erloschen": bool(p.get("erloschen")), "groesse": p.get("groesse")})
    out.sort(key=lambda i: (_ORDER.get(i["kurz"], 9), i["feld"] or ""))
    return out
```

- [ ] **Step 5: Wiring**

`redat/core/sections.py` — replace `_fetch_bergbau`:

```python
def _fetch_bergbau(ctx: Ctx) -> dict:
    from redat.sources import bergrechte
    from redat.sources.bergbau import get_bergbau

    b = get_bergbau(ctx.lat, ctx.lon)
    if b is None:
        raise Empty("Kein GDU-Planquadrat für diesen Ort (außerhalb NRW)")
    b["berechtigungen"], b["berechtigungen_error"] = None, None
    try:
        rows = bergrechte.lookup(ctx.lat, ctx.lon)
        if rows is None:
            b["berechtigungen_error"] = "Bergbauberechtigungen nicht installiert (redat/data/bergbauberechtigungen.geojson.gz fehlt)"
        else:
            b["berechtigungen"] = rows
    except Exception as exc:  # noqa: BLE001 — the rights lookup must not blank the GDU result
        logger.warning("bergrechte: %s", exc)
        b["berechtigungen_error"] = str(exc)
    return b
```

Registry line: `Section("bergbau", "Bergbau & Untergrund", "⛏️", 20, "Geologischer Dienst NRW, „NRW von unten“ (Bürgerversion, 500 m-Planquadrat) · Bergbauberechtigungen NRW (BezReg Arnsberg)", _fetch_bergbau, cache_version=2),`

`redat/report/builder.py::_s_bergbau` — append before `return`:

```python
    own = [r for r in (d.get("berechtigungen") or []) if r.get("kurz") in ("Bergwerkseigentum", "Bewilligung") and not r.get("erloschen")]
    if own:
        fig += f" · Bergwerkseigentum: {own[0].get('feld')} ({own[0].get('bodenschatz')})"
```

(`fig` is the existing `f"{n} Hinweise im 500 m-Planquadrat"` string — assign it to a variable first if it is inline.)

Web partial `redat/templates/analysis/_bergbau.html` — insert before the final `<p class="mt-3 …">`:

```html
<template x-if="d.berechtigungen && d.berechtigungen.length">
    <div class="mt-4 text-sm">
        <div class="font-semibold text-gray-900">📜 Bergbauberechtigungen am Standort</div>
        <ul class="mt-1 space-y-0.5">
            <template x-for="(b, i) in d.berechtigungen" :key="i">
                <li class="text-gray-700">
                    <span class="px-1.5 py-0.5 rounded text-xs mr-1" :class="b.kurz === 'Bergwerkseigentum' || b.kurz === 'Bewilligung' ? 'bg-orange-100 text-orange-800' : 'bg-gray-100 text-gray-700'" x-text="b.kurz"></span>
                    <span class="font-medium" x-text="b.feld"></span> — <span x-text="b.bodenschatz"></span>
                    <span class="text-gray-500" x-text="' · ' + (b.inhaber || 'Inhaber unbekannt') + (b.seit ? ' · seit ' + b.seit : '') + (b.erloschen ? ' · erloschen' : '')"></span>
                </li>
            </template>
        </ul>
        <p class="mt-1 text-xs text-gray-500">Ein Bergwerkseigentum ist ein Recht, kein Nachweis von Abbau — es zeigt, wer für Bergschäden in Anspruch genommen werden kann. Eine Erlaubnis (Aufsuchung) erlaubt nur die Erkundung.</p>
    </div>
</template>
<p class="mt-4 text-sm text-gray-600" x-show="d.berechtigungen && !d.berechtigungen.length">Keine Bergbauberechtigung am Standort.</p>
<p class="mt-4 text-xs text-gray-500" x-show="d.berechtigungen_error" x-text="'Bergbauberechtigungen: ' + d.berechtigungen_error"></p>
```

Report partial `redat/templates/report/_bergbau.html` — insert before the footnote:

```html
{% set rights = d.get("berechtigungen") %}
{% if rights %}
<h3>Bergbauberechtigungen am Standort</h3>
<table>
  <thead><tr><th>Art</th><th>Feld</th><th>Bodenschatz</th><th>Inhaber</th><th>Seit</th></tr></thead>
  <tbody>
  {% for b in rights %}
    <tr>
      <td><span class="tag {{ 'tag-orange' if b.get('kurz') in ('Bergwerkseigentum', 'Bewilligung') else '' }}">{{ b.get("kurz") or "—" }}</span></td>
      <td>{{ b.get("feld") or "—" }}{% if b.get("erloschen") %} (erloschen){% endif %}</td>
      <td>{{ b.get("bodenschatz") or "—" }}</td>
      <td class="xs">{{ b.get("inhaber") or "—" }}</td>
      <td>{{ b.get("seit") or "—" }}</td>
    </tr>
  {% endfor %}
  </tbody>
</table>
<p class="footnote">Ein Bergwerkseigentum ist ein Recht, kein Nachweis von Abbau; es zeigt, wer für Bergschäden in Anspruch genommen werden kann. Quelle: Bergbauberechtigungen NRW, Bezirksregierung Arnsberg (dl-de/by-2-0).</p>
{% elif rights is not none %}
<p class="muted">Keine Bergbauberechtigung am Standort.</p>
{% endif %}
```

Fixture: in `tests/fixtures/report_envelopes.json` add to the `bergbau` `data`:

```json
"berechtigungen": [{"feld": "Neu Essen", "art": "aufrechterhaltenes Bergwerkseigentum", "kurz": "Bergwerkseigentum", "bodenschatz": "Eisenerz", "inhaber": "TRATON SE", "seit": "23.01.1791", "erloschen": false, "groesse": "140 110 991 m²"},
                    {"feld": "Metropole Ruhr", "art": "Erlaubnis zu gewerblichen Zwecken", "kurz": "Erlaubnis (Aufsuchung)", "bodenschatz": "Erdwärme", "inhaber": "Deutsche ErdWärme GmbH & Co. KG; DMT GmbH & Co. KG", "seit": null, "erloschen": false, "groesse": "1 641 275 000 m²"}],
"berechtigungen_error": null
```

- [ ] **Step 6: Build the real file, run the suite, commit**

```bash
curl -sSL -o /tmp/bebu.zip https://www.opengeodata.nrw.de/produkte/geologie/bergbau/bebu/BergbauberechtigungenNRW_EPSG25832_Shape.zip
.venv/bin/python scripts/build_bergbauberechtigungen.py --shape /tmp/bebu.zip     # verified 2026-09-06: "630 Berechtigungen in the window", 194 KB; Bochum Innenstadt then resolves to RAG "Präsident 2" (Steinkohle)
.venv/bin/python -m pytest -q
git add scripts/build_bergbauberechtigungen.py redat/sources/bergrechte.py redat/data/bergbauberechtigungen.geojson.gz redat/core/sections.py redat/report/builder.py redat/templates/analysis/_bergbau.html redat/templates/report/_bergbau.html tests/
git commit -m "feat(bergbau): Bergbauberechtigungen at the point (BezReg Arnsberg open data)"
```

---

### Task 2: Gelände (DGM) on the Starkregen card

**Files:**
- Create: `redat/sources/gelaende.py`
- Modify: `redat/core/sections.py` (`_fetch_starkregen`, `Section("starkregen", …, cache_version=2)`), `redat/templates/analysis/_starkregen.html`, `redat/templates/report/_starkregen.html`, `redat/report/builder.py` (`_s_starkregen`), `tests/fixtures/report_envelopes.json`, `tests/test_analysis_sections.py`
- Test: `tests/test_gelaende.py`

**Interfaces:**
- Produces: `gelaende.get_gelaende(lat, lon) -> dict` with `hoehe_m, min_25m, max_25m, min_100m, max_100m, ueber_tiefstem_100m, unter_hoechstem_100m, neigung_pct, lage, radius_m`; `gelaende._get_coverage(bbox25832) -> bytes` (HTTP point); `gelaende.parse_dgm(tiff_bytes) -> numpy.ndarray`; `gelaende.analyse(arr) -> dict`.

- [ ] **Step 1: Write the failing tests**

`tests/test_gelaende.py`:

```python
import io

import numpy as np
import pytest
from PIL import Image

from redat.sources import gelaende


def tiff(arr: np.ndarray) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(arr.astype(np.float32), mode="F").save(buf, format="TIFF")
    return buf.getvalue()


def plane(slope_x=0.0, slope_y=0.0, base=100.0, n=200):
    yy, xx = np.mgrid[0:n, 0:n]
    return base + slope_x * (xx - n / 2) + slope_y * (n / 2 - yy)     # row 0 = north, like the WCS tile


def test_parse_dgm_reads_float32_tile():
    arr = gelaende.parse_dgm(tiff(plane()))
    assert arr.shape == (200, 200) and arr.dtype == np.float32 and float(arr[100, 100]) == 100.0


def test_flat_plane_is_eben():
    d = gelaende.analyse(plane())
    assert d["hoehe_m"] == 100.0 and d["neigung_pct"] == 0.0 and d["lage"] == "eben"
    assert d["min_100m"] == 100.0 and d["max_100m"] == 100.0 and d["ueber_tiefstem_100m"] == 0.0


def test_slope_is_hanglage():
    d = gelaende.analyse(plane(slope_x=0.15))            # 15 % east-west gradient
    assert d["lage"] == "Hanglage" and 14.0 <= d["neigung_pct"] <= 16.0
    assert d["unter_hoechstem_100m"] > 10 and d["ueber_tiefstem_100m"] > 10


def test_bowl_is_tieflage():
    yy, xx = np.mgrid[0:200, 0:200]
    r = np.hypot(xx - 100, yy - 100)
    arr = 100.0 + np.where(r < 30, 0.0, (r - 30) * 0.1)  # flat floor, rising 10 % beyond 30 m
    d = gelaende.analyse(arr)
    assert d["lage"] == "Tieflage" and d["hoehe_m"] == 100.0 and d["max_100m"] >= 105


def test_hill_is_kuppenlage():
    yy, xx = np.mgrid[0:200, 0:200]
    r = np.hypot(xx - 100, yy - 100)
    arr = 100.0 - np.where(r < 30, 0.0, (r - 30) * 0.1)
    assert gelaende.analyse(arr)["lage"] == "Kuppenlage"


def test_nodata_is_ignored():
    arr = plane(); arr[:10, :10] = -9999.0
    d = gelaende.analyse(arr)
    assert d["min_100m"] == 100.0


def test_get_gelaende_requests_200m_box(monkeypatch):
    seen = {}

    def fake(bbox):
        seen["bbox"] = bbox
        return tiff(plane())
    monkeypatch.setattr(gelaende, "_get_coverage", fake)
    d = gelaende.get_gelaende(51.4300, 7.0050)
    xmin, ymin, xmax, ymax = seen["bbox"]
    assert abs((xmax - xmin) - 200) < 1e-6 and abs((ymax - ymin) - 200) < 1e-6 and 361_200 < xmin < 361_300
    assert d["radius_m"] == 100 and d["lage"] == "eben"


def test_bad_tile_raises(monkeypatch):
    monkeypatch.setattr(gelaende, "_get_coverage", lambda bbox: b"not a tiff")
    with pytest.raises(Exception):
        gelaende.get_gelaende(51.43, 7.0)
```

Add to `tests/test_analysis_sections.py` (replace `test_starkregen_passes_through_and_is_parcel`):

```python
def test_starkregen_merges_gelaende(monkeypatch):
    from redat.core import tiers
    from redat.sources import gelaende, starkregen
    payload = {"radius_m": 50, "building_share": 0.3, "scenarios": {}, "rating": "Gering", "rating_color": "green", "errors": {}}
    monkeypatch.setattr(starkregen, "get_starkregen", lambda lat, lon: dict(payload))
    g = {"hoehe_m": 110.2, "lage": "Tieflage", "neigung_pct": 1.1}
    monkeypatch.setattr(gelaende, "get_gelaende", lambda lat, lon: g)
    d = S._fetch_starkregen(CTX)
    assert d["gelaende"] == g and d["gelaende_error"] is None and d["rating"] == "Gering"
    assert tiers.SERVICE_TIER["starkregen"] == "parcel" and S.SECTIONS["starkregen"].cache_version == 2

    def boom(lat, lon):
        raise RuntimeError("wcs down")
    monkeypatch.setattr(gelaende, "get_gelaende", boom)
    d = S._fetch_starkregen(CTX)
    assert d["gelaende"] is None and d["gelaende_error"] == "wcs down"
```

`tests/test_report_render.py`: `"starkregen"` needles → `["30–50 cm", "Extremereignis", "Tieflage", "112"]`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_gelaende.py tests/test_analysis_sections.py -k "gelaende or starkregen" -q` → `ModuleNotFoundError`, missing keys.

- [ ] **Step 3: Implement `gelaende.py`**

```python
"""Gelände — height, Lage and slope from the 1 m digital terrain model, for the Starkregen card.

Source: Geobasis NRW WCS 2.0.1 https://www.wcs.nrw.de/geobasis/wcs_nw_dgm, coverage `nw_dgm`
(dl-de/zero-2-0). `GetCoverage&COVERAGEID=nw_dgm&SUBSET=x(<xmin>,<xmax>)&SUBSET=y(<ymin>,<ymax>)&FORMAT=image/tiff`
returns a float32 GeoTIFF, 1 px = 1 m, row 0 = north (verified 2026-09-06: 100 m box at Essen-Rüttenscheid →
100×100 px, 108.4–112.8 m NHN). The Geländeneigung WCS only serves styled RGB, so slope is derived here.
Window: HALF_M = 100 → 200×200 px (~70 KB). `_get_coverage` is the single HTTP call and monkeypatch point.
"""
from __future__ import annotations

import io

import httpx
import numpy as np
from PIL import Image
from pyproj import Transformer

from redat.http import headers

WCS_URL = "https://www.wcs.nrw.de/geobasis/wcs_nw_dgm"
COVERAGE = "nw_dgm"
HALF_M = 100
_NEAR_M = 25
_SLOPE_STEP_PX = 5
_NODATA_BELOW = -100.0
_TIMEOUT_S = 25
_TO_25832 = Transformer.from_crs("EPSG:4326", "EPSG:25832", always_xy=True)


def _get_coverage(bbox: tuple[float, float, float, float]) -> bytes:
    """GeoTIFF bytes of the DGM inside the EPSG:25832 bbox — HTTP/monkeypatch point."""
    xmin, ymin, xmax, ymax = bbox
    params = [("SERVICE", "WCS"), ("VERSION", "2.0.1"), ("REQUEST", "GetCoverage"), ("COVERAGEID", COVERAGE),
              ("SUBSET", f"x({xmin:.0f},{xmax:.0f})"), ("SUBSET", f"y({ymin:.0f},{ymax:.0f})"), ("FORMAT", "image/tiff")]
    resp = httpx.get(WCS_URL, params=params, timeout=_TIMEOUT_S, headers=headers())
    resp.raise_for_status()
    if not resp.headers.get("content-type", "").startswith("image/tiff"):
        raise RuntimeError(f"WCS lieferte {resp.headers.get('content-type')} statt GeoTIFF: {resp.text[:160]}")
    return resp.content


def parse_dgm(tiff_bytes: bytes) -> np.ndarray:
    im = Image.open(io.BytesIO(tiff_bytes))
    im.load()
    return np.asarray(im, dtype=np.float32)


def _valid(a: np.ndarray) -> np.ndarray:
    return a[a > _NODATA_BELOW]


def analyse(arr: np.ndarray) -> dict:
    """Terrain figures for a tile whose centre pixel is the point (row 0 = north)."""
    h, w = arr.shape
    cy, cx = h // 2, w // 2
    hoehe = float(arr[cy, cx])
    near = arr[max(0, cy - _NEAR_M):cy + _NEAR_M, max(0, cx - _NEAR_M):cx + _NEAR_M]
    s = _SLOPE_STEP_PX
    dzdx = (float(arr[cy, min(w - 1, cx + s)]) - float(arr[cy, max(0, cx - s)])) / (2 * s)
    dzdy = (float(arr[max(0, cy - s), cx]) - float(arr[min(h - 1, cy + s), cx])) / (2 * s)
    neigung = round(100 * float(np.hypot(dzdx, dzdy)), 1)
    all_v, near_v = _valid(arr), _valid(near)
    min100, max100 = float(all_v.min()), float(all_v.max())
    min25, max25 = float(near_v.min()), float(near_v.max())
    if neigung >= 10:
        lage = "Hanglage"
    elif hoehe - min25 <= 0.3 and max100 - hoehe >= 1.5:
        lage = "Tieflage"
    elif hoehe - min100 >= 1.5 and max100 - hoehe <= 0.3:
        lage = "Kuppenlage"
    else:
        lage = "eben"
    return {
        "hoehe_m": round(hoehe, 1), "min_25m": round(min25, 1), "max_25m": round(max25, 1),
        "min_100m": round(min100, 1), "max_100m": round(max100, 1),
        "ueber_tiefstem_100m": round(hoehe - min100, 1), "unter_hoechstem_100m": round(max100 - hoehe, 1),
        "neigung_pct": neigung, "lage": lage, "radius_m": HALF_M,
    }


def get_gelaende(lat: float, lon: float) -> dict:
    x, y = _TO_25832.transform(lon, lat)
    bbox = (x - HALF_M, y - HALF_M, x + HALF_M, y + HALF_M)
    return analyse(parse_dgm(_get_coverage(bbox)))
```

- [ ] **Step 4: Wiring**

`_fetch_starkregen`:

```python
def _fetch_starkregen(ctx: Ctx) -> dict:
    from redat.sources import gelaende
    from redat.sources.starkregen import get_starkregen

    s = get_starkregen(ctx.lat, ctx.lon)
    if s is None:
        raise Empty("Keine Starkregen-Daten für diesen Ort (außerhalb NRW oder vollständig überbaut)")
    s["gelaende"], s["gelaende_error"] = None, None
    try:
        s["gelaende"] = gelaende.get_gelaende(ctx.lat, ctx.lon)
    except Exception as exc:  # noqa: BLE001 — the WCS must not blank the Starkregen result
        logger.warning("gelaende: %s", exc)
        s["gelaende_error"] = str(exc)
    return s
```

Registry: `Section("starkregen", "Starkregen & Gelände", "🌧️", 25, "BKG Hinweiskarte Starkregengefahren (dl-de/by-2-0) — 1 m-Modell ohne Kanalnetz · Geobasis NRW DGM1 (WCS)", _fetch_starkregen, cache_version=2),`

`_s_starkregen`: after `fig` is assembled, add `g = d.get("gelaende") or {}` and `if g.get("lage"): fig = (fig + " · " if fig else "") + f"{g['lage']}, {fmt_num(g.get('hoehe_m') or 0, 0)} m NHN"`.

Web partial `_starkregen.html` — insert before the final `<p class="mt-3 …">`:

```html
<template x-if="d.gelaende">
    <div class="mt-4 text-sm">
        <div class="font-semibold text-gray-900">⛰ Gelände</div>
        <div class="mt-1 grid grid-cols-2 md:grid-cols-4 gap-2">
            <div><div class="text-gray-500">Lage</div><div class="font-medium" :class="{Tieflage: 'text-orange-700', Hanglage: 'text-yellow-700'}[d.gelaende.lage] || 'text-gray-900'" x-text="d.gelaende.lage"></div></div>
            <div><div class="text-gray-500">Höhe</div><div class="font-medium text-gray-900" x-text="d.gelaende.hoehe_m + ' m NHN'"></div></div>
            <div><div class="text-gray-500">Über dem tiefsten Punkt (100 m)</div><div class="font-medium text-gray-900" x-text="d.gelaende.ueber_tiefstem_100m + ' m'"></div></div>
            <div><div class="text-gray-500">Neigung</div><div class="font-medium text-gray-900" x-text="d.gelaende.neigung_pct + ' %'"></div></div>
        </div>
        <p class="mt-1 text-xs text-gray-500" x-show="d.gelaende.lage === 'Tieflage'">Tiefster Punkt der Umgebung: Oberflächenwasser sammelt sich hier — Rückstausicherung und Lichtschachtabdeckungen prüfen.</p>
        <p class="mt-1 text-xs text-gray-500" x-show="d.gelaende.lage === 'Hanglage'">Hanglage: Wasser fließt hangabwärts an oder über das Grundstück — Entwässerung oberhalb prüfen.</p>
    </div>
</template>
<p class="mt-2 text-xs text-gray-500" x-show="d.gelaende_error">Geländemodell derzeit nicht abrufbar.</p>
```

Report partial `_starkregen.html` — insert before the footnote:

```html
{% set g = d.get("gelaende") %}
{% if g %}
<table class="mt">
  <tbody>
    <tr><td class="muted">Gelände</td><td><strong>{{ g.get("lage") or "—" }}</strong>{% if g.get("hoehe_m") is not none %} · {{ g.hoehe_m|fmt_num(1) }} m NHN{% endif %}{% if g.get("ueber_tiefstem_100m") is not none %} · {{ g.ueber_tiefstem_100m|fmt_num(1) }} m über dem tiefsten Punkt im Umkreis von {{ g.get("radius_m") or 100 }} m{% endif %}{% if g.get("neigung_pct") is not none %} · Neigung {{ g.neigung_pct|fmt_num(1) }} %{% endif %}</td></tr>
  </tbody>
</table>
{% endif %}
```

Fixture: add to `starkregen` data `"gelaende": {"hoehe_m": 112.4, "min_25m": 112.1, "max_25m": 113.0, "min_100m": 112.1, "max_100m": 116.8, "ueber_tiefstem_100m": 0.3, "unter_hoechstem_100m": 4.4, "neigung_pct": 1.1, "lage": "Tieflage", "radius_m": 100}, "gelaende_error": null`.

- [ ] **Step 5: Suite green, commit**

```bash
.venv/bin/python -m pytest -q
git add redat/sources/gelaende.py redat/core/sections.py redat/report/builder.py redat/templates/analysis/_starkregen.html redat/templates/report/_starkregen.html tests/
git commit -m "feat(starkregen): terrain height, Lage and slope from the NRW DGM1 WCS"
```

---

### Task 3: Fluglärm and Ruhige Gebiete on the noise card

**Files:**
- Create: `redat/sources/noise_extra.py`
- Modify: `redat/core/sections.py` (`_fetch_noise`, `Section("noise", …, cache_version=2)`), `redat/templates/analysis/_noise.html`, `redat/templates/report/_noise.html`, `tests/fixtures/report_envelopes.json`, `tests/test_analysis_sections.py`
- Test: `tests/test_noise_extra.py`

**Interfaces:**
- Produces: `noise_extra.get_noise_extra(lat, lon) -> {"flug": dict|None, "ruhiges_gebiet": dict|None}`; `noise_extra._query(url, lat, lon, out_fields) -> dict` (HTTP point).

- [ ] **Step 1: Write the failing tests**

`tests/test_noise_extra.py`:

```python
from redat.sources import noise_extra as ne


def stub(monkeypatch, by_url: dict):
    calls = []

    def fake(url, lat, lon, out_fields):
        calls.append(url)
        v = by_url.get(url, [])
        if isinstance(v, Exception):
            raise v
        return {"features": [{"attributes": a} for a in v]}
    monkeypatch.setattr(ne, "_query", fake)
    return calls


def test_essen_kettwig_flug_dus_day_and_night(monkeypatch):
    calls = stub(monkeypatch, {ne.ESSEN_FLUG_DUS_DAY: [{"CATEGORY": "Lden5559", "PEGEL": "LDEN", "TEXT": "ab 55 bis 59 dB(A)"}],
                               ne.ESSEN_FLUG_DUS_NIGHT: [{"CATEGORY": "Lnight5054", "PEGEL": "LNIGHT", "TEXT": "ab 50 bis 54 dB(A)"}]})
    d = ne.get_noise_extra(51.362, 6.940)
    assert d["flug"] == {"airport": "DUS", "day": "ab 55 bis 59 dB(A)", "night": "ab 50 bis 54 dB(A)"}
    assert d["ruhiges_gebiet"] is None
    assert ne.ESSEN_RUHIG in calls and ne.BOCHUM_RUHIG not in calls


def test_essen_emh_when_dus_silent(monkeypatch):
    stub(monkeypatch, {ne.ESSEN_FLUG_EMH_DAY: [{"TEXT": "ab 55 bis 59 dB(A)"}]})
    assert ne.get_noise_extra(51.40, 6.95)["flug"] == {"airport": "EMH", "day": "ab 55 bis 59 dB(A)", "night": None}


def test_ruhiges_gebiet_essen_and_bochum(monkeypatch):
    stub(monkeypatch, {ne.ESSEN_RUHIG: [{"NAME": "Stadtwald", "BESCHREIBU": "Stadtwald"}]})
    assert ne.get_noise_extra(51.42, 7.02)["ruhiges_gebiet"] == {"name": "Stadtwald", "stadt": "Essen"}
    calls = stub(monkeypatch, {ne.BOCHUM_RUHIG: [{"NAME": "Weitmarer Holz", "ART": "Ruhiges Gebiet", "BEZIRK": "Südwest"}]})
    d = ne.get_noise_extra(51.4818, 7.2162)
    assert d["ruhiges_gebiet"] == {"name": "Weitmarer Holz", "stadt": "Bochum"} and d["flug"] is None
    assert ne.ESSEN_FLUG_DUS_DAY not in calls


def test_outside_both_cities_queries_nothing(monkeypatch):
    calls = stub(monkeypatch, {})
    assert ne.get_noise_extra(51.2199, 6.7943) == {"flug": None, "ruhiges_gebiet": None, "errors": {}} and calls == []


def test_one_layer_failing_does_not_hide_the_rest(monkeypatch):
    stub(monkeypatch, {ne.ESSEN_FLUG_DUS_DAY: RuntimeError("down"), ne.ESSEN_RUHIG: [{"NAME": "Stadtwald"}]})
    d = ne.get_noise_extra(51.42, 7.02)
    assert d["ruhiges_gebiet"]["name"] == "Stadtwald" and d["flug"] is None and d["errors"] == {"flug_dus_day": "down"}
```

Add to `tests/test_analysis_sections.py` (replace the existing `_fetch_noise` pass-through assertion at the test around line 196 — keep its name, extend it):

```python
def test_noise_merges_extra(monkeypatch):
    from redat.sources import noise, noise_extra
    payload = {"day": None, "night": None, "sources": {}, "below_threshold": True, "window_m": 25}
    monkeypatch.setattr(noise, "get_noise_levels", lambda lat, lon: dict(payload))
    extra = {"flug": {"airport": "DUS", "day": "ab 55 bis 59 dB(A)", "night": None}, "ruhiges_gebiet": None, "errors": {}}
    monkeypatch.setattr(noise_extra, "get_noise_extra", lambda lat, lon: extra)
    d = S._fetch_noise(CTX)
    assert d["flug"] == extra["flug"] and d["ruhiges_gebiet"] is None and d["extra_error"] is None and d["below_threshold"] is True
    assert S.SECTIONS["noise"].cache_version == 2

    def boom(lat, lon):
        raise RuntimeError("essen down")
    monkeypatch.setattr(noise_extra, "get_noise_extra", boom)
    d = S._fetch_noise(CTX)
    assert d["flug"] is None and d["extra_error"] == "essen down"
```

`tests/test_report_render.py`: `"noise"` needles → `["Straße", "70 dB(A)", "Düsseldorf", "Stadtwald"]`.

- [ ] **Step 2: Run the tests to verify they fail** → `ModuleNotFoundError: redat.sources.noise_extra`.

- [ ] **Step 3: Implement `noise_extra.py`**

```python
"""Fluglärm and Ruhige Gebiete — what the state Umgebungslärm map does not show.

Sources (ArcGIS REST point queries, verified 2026-09-06):
- Essen Lärmkarte https://geo.essen.de/arcgis/rest/services/essen/Laermkarte_aktuell/MapServer: layer 5 Flugverkehr
  DUS (L_DEN; two polygons, 20 km² in Kettwig/Werden, classes Lden5559/Lden6064), 11 Flugverkehr DUS (L_night),
  4 Flugverkehr EMH (Essen/Mülheim, L_DEN). Fields CATEGORY, PEGEL, TEXT ("ab 55 bis 59 dB(A)").
- Ruhige Gebiete (§ 47d BImSchG, Lärmaktionsplan): Essen .../Ruhige_Gebiete/MapServer/26 (NAME, BESCHREIBU),
  Bochum https://geoservicekkm.bochum.de/arcgis/rest/services/maponline/Laermkartierung_Stufe4/MapServer/20
  (NAME, ART, BEZIRK; the server rejects resultRecordCount — never send it).
Queries are city-gated by bbox; every layer is isolated (`errors[<key>]`). `_query` is the HTTP/monkeypatch point.
"""
from __future__ import annotations

import logging
from typing import Optional

import httpx

from redat.http import headers

logger = logging.getLogger(__name__)

ESSEN_FLUG_DUS_DAY = "https://geo.essen.de/arcgis/rest/services/essen/Laermkarte_aktuell/MapServer/5/query"
ESSEN_FLUG_DUS_NIGHT = "https://geo.essen.de/arcgis/rest/services/essen/Laermkarte_aktuell/MapServer/11/query"
ESSEN_FLUG_EMH_DAY = "https://geo.essen.de/arcgis/rest/services/essen/Laermkarte_aktuell/MapServer/4/query"
ESSEN_RUHIG = "https://geo.essen.de/arcgis/rest/services/essen/Ruhige_Gebiete/MapServer/26/query"
BOCHUM_RUHIG = "https://geoservicekkm.bochum.de/arcgis/rest/services/maponline/Laermkartierung_Stufe4/MapServer/20/query"
ESSEN_BBOX = (6.89, 51.35, 7.14, 51.53)
BOCHUM_BBOX = (7.10, 51.40, 7.35, 51.53)
_TIMEOUT_S = 15


def _in(bbox, lat, lon) -> bool:
    lon_min, lat_min, lon_max, lat_max = bbox
    return lon_min <= lon <= lon_max and lat_min <= lat <= lat_max


def _query(url: str, lat: float, lon: float, out_fields: str) -> dict:
    params = {"f": "json", "where": "1=1", "geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint", "inSR": 4326,
              "spatialRel": "esriSpatialRelIntersects", "outFields": out_fields, "returnGeometry": "false"}
    resp = httpx.get(url, params=params, timeout=_TIMEOUT_S, headers=headers())
    resp.raise_for_status()
    return resp.json()


def _first(url: str, lat: float, lon: float, out_fields: str, errors: dict, key: str) -> Optional[dict]:
    try:
        feats = _query(url, lat, lon, out_fields).get("features") or []
    except Exception as exc:  # noqa: BLE001
        logger.warning("noise_extra %s: %s", key, exc)
        errors[key] = str(exc)
        return None
    return (feats[0].get("attributes") or {}) if feats else None


def get_noise_extra(lat: float, lon: float) -> dict:
    out: dict = {"flug": None, "ruhiges_gebiet": None, "errors": {}}
    if _in(ESSEN_BBOX, lat, lon):
        dus = _first(ESSEN_FLUG_DUS_DAY, lat, lon, "CATEGORY,PEGEL,TEXT", out["errors"], "flug_dus_day")
        if dus:
            night = _first(ESSEN_FLUG_DUS_NIGHT, lat, lon, "CATEGORY,PEGEL,TEXT", out["errors"], "flug_dus_night")
            out["flug"] = {"airport": "DUS", "day": dus.get("TEXT"), "night": night.get("TEXT") if night else None}
        else:
            emh = _first(ESSEN_FLUG_EMH_DAY, lat, lon, "CATEGORY,PEGEL,TEXT", out["errors"], "flug_emh_day")
            if emh:
                out["flug"] = {"airport": "EMH", "day": emh.get("TEXT"), "night": None}
        rg = _first(ESSEN_RUHIG, lat, lon, "NAME,BESCHREIBU", out["errors"], "ruhig_essen")
        if rg:
            out["ruhiges_gebiet"] = {"name": rg.get("NAME") or rg.get("BESCHREIBU") or "Ruhiges Gebiet", "stadt": "Essen"}
    elif _in(BOCHUM_BBOX, lat, lon):
        rg = _first(BOCHUM_RUHIG, lat, lon, "NAME,ART,BEZIRK", out["errors"], "ruhig_bochum")
        if rg:
            out["ruhiges_gebiet"] = {"name": rg.get("NAME") or "Ruhiges Gebiet", "stadt": "Bochum"}
    return out
```

- [ ] **Step 4: Wiring**

`_fetch_noise`:

```python
def _fetch_noise(ctx: Ctx) -> dict:
    from redat.sources import noise_extra
    from redat.sources.noise import get_noise_levels

    n = get_noise_levels(ctx.lat, ctx.lon)
    n["flug"], n["ruhiges_gebiet"], n["extra_error"] = None, None, None
    try:
        extra = noise_extra.get_noise_extra(ctx.lat, ctx.lon)
        n["flug"], n["ruhiges_gebiet"] = extra.get("flug"), extra.get("ruhiges_gebiet")
        if extra.get("errors"):
            n["extra_error"] = ", ".join(f"{k}: {v}" for k, v in extra["errors"].items())
    except Exception as exc:  # noqa: BLE001 — the city layers must not blank the state map
        logger.warning("noise_extra: %s", exc)
        n["extra_error"] = str(exc)
    return n
```

Registry: `Section("noise", "Lärm", "🔊", 20, "Land NRW, Umgebungslärmkartierung 2022 (WMS, Maximum im 25-m-Fenster) · Stadt Essen Fluglärm DUS/EMH · Ruhige Gebiete Essen/Bochum", _fetch_noise, cache_version=2),`

Web partial `_noise.html` — append after the outer `</template>` (so it renders for both branches):

```html
<template x-if="d.flug">
    <p class="mt-3 text-sm text-gray-800">✈️ Fluglärm <span x-text="d.flug.airport === 'DUS' ? 'Flughafen Düsseldorf' : 'Flughafen Essen/Mülheim'"></span>:
        Tag <span class="font-medium" x-text="d.flug.day || '—'"></span><span x-show="d.flug.night" x-text="', Nacht ' + d.flug.night"></span>
        <span class="text-xs text-gray-500">(Lärmkarte der Stadt Essen)</span></p>
</template>
<template x-if="d.ruhiges_gebiet">
    <p class="mt-2 text-sm text-gray-800">🌳 Im „Ruhigen Gebiet“ <span class="font-medium" x-text="d.ruhiges_gebiet.name"></span> (Lärmaktionsplan <span x-text="d.ruhiges_gebiet.stadt"></span>) — vor Verlärmung besonders geschützt.</p>
</template>
<p class="mt-2 text-xs text-gray-500" x-show="d.extra_error">Städtische Lärmdaten teilweise nicht abrufbar.</p>
```

Report partial `_noise.html` — insert before the `{% if noise_maps %}` block:

```html
{% set fl = d.get("flug") %}
{% if fl %}<p>Fluglärm {{ "Flughafen Düsseldorf" if fl.get("airport") == "DUS" else "Flughafen Essen/Mülheim" }}: Tag {{ fl.get("day") or "—" }}{% if fl.get("night") %}, Nacht {{ fl.night }}{% endif %} (Lärmkarte der Stadt Essen).</p>{% endif %}
{% set rg = d.get("ruhiges_gebiet") %}
{% if rg %}<p>Im „Ruhigen Gebiet“ <strong>{{ rg.get("name") or "—" }}</strong> (Lärmaktionsplan {{ rg.get("stadt") or "" }}) — vor Verlärmung besonders geschützt.</p>{% endif %}
```

Fixture: add to `noise` data `"flug": {"airport": "DUS", "day": "ab 55 bis 59 dB(A)", "night": null}, "ruhiges_gebiet": {"name": "Stadtwald", "stadt": "Essen"}, "extra_error": null`.

- [ ] **Step 5: Suite green, commit**

```bash
.venv/bin/python -m pytest -q
git add redat/sources/noise_extra.py redat/core/sections.py redat/templates/analysis/_noise.html redat/templates/report/_noise.html tests/
git commit -m "feat(noise): Fluglärm DUS/EMH and Ruhige Gebiete from the Essen and Bochum city layers"
```

---

### Task 4: `ladesaeulen` card — build script, source, wiring

**Files:**
- Create: `scripts/build_ladesaeulen.py`, `redat/data/ladesaeulen.json.gz`, `redat/sources/ladesaeulen.py`, `redat/templates/analysis/_ladesaeulen.html`, `redat/templates/report/_ladesaeulen.html`
- Modify: `redat/core/sections.py` (after `energie`), `redat/core/tiers.py` (area), `redat/core/sources_meta.py`, `redat/report/builder.py`, `tests/fixtures/report_envelopes.json`, `tests/test_analysis_sections.py` (order list + test), `tests/test_tiers.py`, `tests/test_report_render.py`
- Test: `tests/test_build_ladesaeulen.py`, `tests/test_ladesaeulen.py`

**Interfaces:**
- Build: `parse_rows(fh, bbox) -> list[list]` (`FIELDS = ["lat","lon","betreiber","schnell","punkte","kw","adresse"]`), `main()`; output `{"stand": "2026-09-01", "bbox": [...], "fields": FIELDS, "rows": [...]}`.
- Source: `ladesaeulen.lookup(lat, lon) -> Optional[dict]` (None outside bbox or without grid) with `radius_m, anzahl_500m, anzahl_1000m, ladepunkte_1000m, schnell_1000m, naechste, stand, rating, rating_color`; `ladesaeulen._load()` monkeypatch point. Section key `ladesaeulen` right after `energie`.

- [ ] **Step 1: Write the failing tests**

`tests/test_build_ladesaeulen.py`:

```python
import importlib.util
import io
from pathlib import Path

_spec = importlib.util.spec_from_file_location("build_ls", Path(__file__).resolve().parent.parent / "scripts" / "build_ladesaeulen.py")
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)

CSV = (
    "\ufeffLadesäulenregister Bundesnetzagentur;;;;;;;;;;;;;;;;\n"
    ";;;;;;;;;;;;;;;;\n"
    "Letzte Aktualisierung vom: 01.09.2026;;;;;;;;;;;;;;;;\n"
    "Allgemeine Informationen;;;;;;;;;;;;;;;;\n"
    "Ladeeinrichtungs-ID;Betreiber;Anzeigename (Karte);Status;Art der Ladeeinrichtung;Anzahl Ladepunkte;Nennleistung Ladeeinrichtung [kW];Inbetriebnahmedatum;Straße;Hausnummer;Adresszusatz;Postleitzahl;Ort;Kreis/kreisfreie Stadt;Bundesland;Breitengrad;Längengrad\n"
    "1;E.ON Drive Germany GmbH;E.ON;In Betrieb;Normalladeeinrichtung;2;22;25.01.2021;Rüttenscheider Str.;1;;45131;Essen;Kreisfreie Stadt Essen;Nordrhein-Westfalen;51,430500;7,005500\n"
    "2;Fastned;Fastned;In Betrieb;Schnellladeeinrichtung;4;300;01.01.2024;A40;;;45141;Essen;Kreisfreie Stadt Essen;Nordrhein-Westfalen;51,460000;7,010000\n"
    "3;X;X;In Betrieb;Normalladeeinrichtung;1;11;01.01.2021;Grunerstraße;20;;10179;Essen;Kreisfreie Stadt Berlin;Berlin;52,519366;13,416644\n"   # Ort 'Essen' but Berlin → bbox drops it
    "4;Y;Y;In Wartung;Normalladeeinrichtung;1;11;01.01.2021;Weg;1;;45131;Essen;Kreisfreie Stadt Essen;Nordrhein-Westfalen;51,431000;7,006000\n"   # not in Betrieb → dropped
)


def test_parse_rows_crops_by_bbox_and_keeps_only_operating():
    rows = mod.parse_rows(io.StringIO(CSV), mod.BBOX_WGS84)
    assert rows == [[51.4305, 7.0055, "E.ON Drive Germany GmbH", 0, 2, 22.0, "Rüttenscheider Str. 1, 45131 Essen"],
                    [51.46, 7.01, "Fastned", 1, 4, 300.0, "A40, 45141 Essen"]]


def test_stand_is_read_from_the_preamble():
    assert mod.read_stand(io.StringIO(CSV)) == "2026-09-01"
```

`tests/test_ladesaeulen.py`:

```python
import pytest

from redat.sources import ladesaeulen as ls

F = ["lat", "lon", "betreiber", "schnell", "punkte", "kw", "adresse"]
ROWS = [
    [51.4320, 7.0050, "E.ON", 0, 2, 22.0, "Rüttenscheider Str. 1, 45131 Essen"],    # 222 m
    [51.4300, 7.0110, "Fastned", 1, 4, 300.0, "A40, 45141 Essen"],                   # 416 m
    [51.4380, 7.0050, "Stadtwerke", 0, 2, 11.0, "Weg 3, 45131 Essen"],               # 890 m
    [51.4420, 7.0050, "Fern", 0, 2, 11.0, "Fern 1"],                                  # 1334 m → outside 1 km
]
GRID = {"stand": "2026-09-01", "bbox": [6.85, 51.33, 7.40, 51.56], "fields": F, "rows": ROWS}


@pytest.fixture(autouse=True)
def grid(monkeypatch):
    monkeypatch.setattr(ls, "_load", lambda: GRID)


def test_lookup_counts_and_nearest():
    d = ls.lookup(51.4300, 7.0050)
    assert d["radius_m"] == 1000 and d["stand"] == "2026-09-01"
    assert d["anzahl_500m"] == 2 and d["anzahl_1000m"] == 3 and d["ladepunkte_1000m"] == 8 and d["schnell_1000m"] == 1
    assert [n["betreiber"] for n in d["naechste"]] == ["E.ON", "Fastned", "Stadtwerke"]
    assert 200 < d["naechste"][0]["distance_m"] < 240 and d["naechste"][1]["schnell"] is True and d["naechste"][1]["kw"] == 300.0
    assert d["rating"] == "Ladepunkt in Gehweite" and d["rating_color"] == "green"


def test_rating_yellow_and_orange(monkeypatch):
    monkeypatch.setattr(ls, "_load", lambda: {**GRID, "rows": ROWS[1:]})
    assert ls.lookup(51.4300, 7.0050)["rating"] == "Ladepunkt im Umkreis"
    monkeypatch.setattr(ls, "_load", lambda: {**GRID, "rows": []})
    d = ls.lookup(51.4300, 7.0050)
    assert d["rating"] == "Kein öffentlicher Ladepunkt im Umkreis von 1 km" and d["rating_color"] == "orange" and d["naechste"] == []


def test_outside_window_and_missing_grid(monkeypatch):
    assert ls.lookup(50.9, 6.9) is None
    monkeypatch.setattr(ls, "_load", lambda: None)
    assert ls.lookup(51.43, 7.0) is None
```

Registry tests: insert `"ladesaeulen"` after `"energie"` in `test_registry_keys_and_order` and in `test_tiers.py`'s list (area); render needles `"ladesaeulen": ["Fastned", "300", "Gehweite"]`; and:

```python
def test_ladesaeulen_passthrough_and_empty(monkeypatch):
    from redat.sources import ladesaeulen
    monkeypatch.setattr(ladesaeulen, "lookup", lambda lat, lon: {"anzahl_1000m": 3})
    assert S._fetch_ladesaeulen(CTX) == {"anzahl_1000m": 3}
    monkeypatch.setattr(ladesaeulen, "lookup", lambda lat, lon: None)
    with pytest.raises(Empty):
        S._fetch_ladesaeulen(CTX)
```

- [ ] **Step 2: Run the tests to verify they fail** → script/module missing, order test fails.

- [ ] **Step 3: Build script**

`scripts/build_ladesaeulen.py`:

```python
"""Crop the BNetzA Ladesäulenregister to the Essen/Bochum window → redat/data/ladesaeulen.json.gz.

Input: the monthly CSV linked from https://www.bundesnetzagentur.de/DE/Fachthemen/ElektrizitaetundGas/E-Mobilitaet/Ladesaeulenkarte/start.html,
e.g. https://data.bundesnetzagentur.de/Bundesnetzagentur/DE/Fachthemen/ElektrizitaetundGas/E-Mobilitaet/Ladesaeulenregister_BNetzA_2026-09-01.csv
(CC BY 4.0, ~55 MB, UTF-8 BOM, ';', decimal comma, 116k rows). The header is the line starting with
"Ladeeinrichtungs-ID" (after a 9-line preamble that carries "Letzte Aktualisierung vom: dd.mm.yyyy"). Crop by
bbox, not by Ort: a Berlin charger carries Ort "Essen". Only Status "In Betrieb" is kept.

Usage:
    .venv/bin/python scripts/build_ladesaeulen.py --csv /tmp/Ladesaeulenregister_BNetzA_2026-09-01.csv
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import re
from datetime import datetime
from pathlib import Path
from typing import IO, Optional

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "redat" / "data" / "ladesaeulen.json.gz"
BBOX_WGS84 = (6.85, 51.33, 7.40, 51.56)
FIELDS = ["lat", "lon", "betreiber", "schnell", "punkte", "kw", "adresse"]


def _num(s: str) -> float:
    return float((s or "").strip().replace(".", "").replace(",", "."))


def read_stand(fh: IO[str]) -> Optional[str]:
    for line in fh:
        m = re.search(r"Letzte Aktualisierung vom:\s*(\d{2})\.(\d{2})\.(\d{4})", line)
        if m:
            return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
        if line.startswith("Ladeeinrichtungs-ID"):
            break
    return None


def parse_rows(fh: IO[str], bbox: tuple[float, float, float, float]) -> list[list]:
    lon_min, lat_min, lon_max, lat_max = bbox
    lines = iter(fh)
    for line in lines:
        if line.lstrip("\ufeff").startswith("Ladeeinrichtungs-ID"):
            header = next(csv.reader([line.lstrip("\ufeff")], delimiter=";"))
            break
    else:
        raise ValueError("Kopfzeile 'Ladeeinrichtungs-ID' nicht gefunden")
    ci = {h: i for i, h in enumerate(header)}
    rows = []
    for r in csv.reader(lines, delimiter=";"):
        if len(r) < len(header):
            continue
        try:
            lat, lon = _num(r[ci["Breitengrad"]]), _num(r[ci["Längengrad"]])
        except ValueError:
            continue
        if not (lon_min <= lon <= lon_max and lat_min <= lat <= lat_max) or r[ci["Status"]].strip() != "In Betrieb":
            continue
        try:
            punkte, kw = int(_num(r[ci["Anzahl Ladepunkte"]])), _num(r[ci["Nennleistung Ladeeinrichtung [kW]"]])
        except ValueError:
            continue
        street = " ".join(p for p in (r[ci["Straße"]].strip(), r[ci["Hausnummer"]].strip()) if p)
        adresse = ", ".join(p for p in (street, f"{r[ci['Postleitzahl']].strip()} {r[ci['Ort']].strip()}".strip()) if p)
        rows.append([round(lat, 6), round(lon, 6), r[ci["Betreiber"]].strip(),
                     1 if r[ci["Art der Ladeeinrichtung"]].strip().startswith("Schnell") else 0, punkte, kw, adresse])
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args()
    with open(a.csv, encoding="utf-8-sig", newline="") as fh:
        stand = read_stand(fh)
    with open(a.csv, encoding="utf-8-sig", newline="") as fh:
        rows = parse_rows(fh, BBOX_WGS84)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(a.out, "wt", encoding="utf-8") as fh:
        json.dump({"stand": stand, "bbox": list(BBOX_WGS84), "fields": FIELDS, "rows": rows}, fh, ensure_ascii=False, separators=(",", ":"))
    print(f"wrote {a.out}: {len(rows)} Ladeeinrichtungen, Stand {stand}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Source module**

`redat/sources/ladesaeulen.py`:

```python
"""Öffentliche E-Ladepunkte im Umkreis — BNetzA Ladesäulenregister (CC BY 4.0), cropped to Essen/Bochum.

Data: redat/data/ladesaeulen.json.gz (scripts/build_ladesaeulen.py), rows in FIELDS order; only chargers
"In Betrieb". `_load` is the monkeypatch point.
"""
from __future__ import annotations

import gzip
import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Optional

GRID_PATH = Path(__file__).resolve().parent.parent / "data" / "ladesaeulen.json.gz"
RADIUS_M = 1000
_NEAR_M = 500
_WALK_M = 300
_MAX_NEAREST = 5


@lru_cache(maxsize=1)
def _load() -> Optional[dict]:
    try:
        with gzip.open(GRID_PATH, "rt", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _dist_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    k = math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot((lat2 - lat1) * 111_195, (lon2 - lon1) * 111_195 * k)


def _rate(nearest_m: Optional[float]) -> tuple[str, str]:
    if nearest_m is not None and nearest_m <= _WALK_M:
        return "Ladepunkt in Gehweite", "green"
    if nearest_m is not None:
        return "Ladepunkt im Umkreis", "yellow"
    return "Kein öffentlicher Ladepunkt im Umkreis von 1 km", "orange"


def lookup(lat: float, lon: float) -> Optional[dict]:
    grid = _load()
    if not grid:
        return None
    lon_min, lat_min, lon_max, lat_max = grid["bbox"]
    if not (lon_min <= lon <= lon_max and lat_min <= lat <= lat_max):
        return None
    idx = {n: i for i, n in enumerate(grid["fields"])}
    hits = []
    for r in grid["rows"]:
        d = _dist_m(lat, lon, r[idx["lat"]], r[idx["lon"]])
        if d <= RADIUS_M:
            hits.append((d, r))
    hits.sort(key=lambda t: t[0])
    naechste = [{"betreiber": r[idx["betreiber"]], "distance_m": round(d), "punkte": r[idx["punkte"]], "kw": r[idx["kw"]],
                 "schnell": bool(r[idx["schnell"]]), "adresse": r[idx["adresse"]]} for d, r in hits[:_MAX_NEAREST]]
    rating, color = _rate(hits[0][0] if hits else None)
    return {
        "radius_m": RADIUS_M, "stand": grid.get("stand"),
        "anzahl_500m": sum(1 for d, _ in hits if d <= _NEAR_M), "anzahl_1000m": len(hits),
        "ladepunkte_1000m": sum(r[idx["punkte"]] for _, r in hits), "schnell_1000m": sum(1 for _, r in hits if r[idx["schnell"]]),
        "naechste": naechste, "rating": rating, "rating_color": color,
    }
```

- [ ] **Step 5: Wiring**

`sections.py` (area tier):

```python
def _fetch_ladesaeulen(ctx: Ctx) -> dict:
    from redat.sources import ladesaeulen

    d = ladesaeulen.lookup(ctx.lat, ctx.lon)
    if d is None:
        raise Empty("Keine Ladesäulen-Daten für diesen Ort (außerhalb Essen/Bochum oder Datei fehlt)")
    return d
```

Registry line after `energie`: `Section("ladesaeulen", "E-Ladepunkte", "🔌", 10, "Bundesnetzagentur, Ladesäulenregister (CC BY 4.0) — nur gemeldete Ladeeinrichtungen in Betrieb", _fetch_ladesaeulen),`
`tiers.py`: `"ladesaeulen": "area",`. `sources_meta.py`: `SourceMeta(("ladesaeulen",), "Ladesäulenregister", "Bundesnetzagentur", "CC BY 4.0", "lokal: redat/data/ladesaeulen.json.gz (scripts/build_ladesaeulen.py)", "area", "monatlich, Datei-Import"),`.
`builder.py`:

```python
def _s_ladesaeulen(d):
    rating, color = _rated(d)
    if d.get("anzahl_1000m") is None:
        return rating, color, None
    fig = f"{d['anzahl_1000m']} Ladeeinrichtungen ≤ 1 km ({d.get('ladepunkte_1000m') or 0} Ladepunkte, {d.get('schnell_1000m') or 0} Schnelllader)"
    if d.get("naechste"):
        fig += f" · nächste {fmt_m(d['naechste'][0]['distance_m'])}"
    return rating, color, fig
```

`"ladesaeulen": _s_ladesaeulen,` after `"energie"` in `SUMMARY`.

`redat/templates/analysis/_ladesaeulen.html`:

```html
<div class="flex items-center gap-4">
    <span class="px-3 py-1 rounded-full font-bold" :class="$store.app.getAirQualityColor(d.rating_color)" x-text="d.rating"></span>
    <div class="text-sm">
        <div class="text-gray-500">Öffentliche Ladeeinrichtungen im Umkreis von 1 km</div>
        <div class="font-medium text-gray-900"><span x-text="d.anzahl_1000m"></span> Standorte · <span x-text="d.ladepunkte_1000m"></span> Ladepunkte · <span x-text="d.schnell_1000m"></span> Schnelllader<span class="text-gray-500" x-text="' · ' + d.anzahl_500m + ' innerhalb 500 m'"></span></div>
    </div>
</div>
<template x-if="d.naechste.length">
    <ul class="mt-4 space-y-1 text-sm">
        <template x-for="(n, i) in d.naechste" :key="i">
            <li class="flex items-start gap-2">
                <span class="text-gray-500 w-14 flex-shrink-0 text-right" x-text="$store.app.formatDistance(n.distance_m)"></span>
                <span><span class="text-gray-900" x-text="n.betreiber"></span>
                    <span class="text-gray-500" x-text="' · ' + n.punkte + ' Ladepunkte · ' + n.kw + ' kW' + (n.schnell ? ' · Schnellladen' : '')"></span>
                    <span class="block text-xs text-gray-500" x-text="n.adresse"></span></span>
            </li>
        </template>
    </ul>
</template>
<p class="mt-3 text-xs text-gray-500">Ladesäulenregister der Bundesnetzagentur, Stand <span x-text="d.stand"></span>; enthält nur Betreiber, die das Anzeigeverfahren abgeschlossen haben. Private Wallboxen und nicht gemeldete Anlagen fehlen.</p>
```

`redat/templates/report/_ladesaeulen.html`:

```html
<div class="kpis">
  <div class="kpi">
    <div class="label">Öffentliche Ladeeinrichtungen ≤ 1 km</div>
    <div class="value"><span class="chip {{ rating_class(d.get('rating_color')) }}">{{ d.get("rating") or "—" }}</span></div>
  </div>
  <div class="kpi">
    <div class="label">Standorte · Ladepunkte · Schnelllader</div>
    <div class="value">{{ d.get("anzahl_1000m") if d.get("anzahl_1000m") is not none else "—" }} · {{ d.get("ladepunkte_1000m") if d.get("ladepunkte_1000m") is not none else "—" }} · {{ d.get("schnell_1000m") if d.get("schnell_1000m") is not none else "—" }}</div>
  </div>
</div>
{% set n = d.get("naechste") or [] %}
{% if n %}
<table class="mt">
  <thead><tr><th class="num">Abstand</th><th>Betreiber</th><th class="num">Ladepunkte</th><th class="num">kW</th><th>Adresse</th></tr></thead>
  <tbody>
  {% for x in n %}
    <tr><td class="num">{{ (x.distance_m|fmt_m) if x.get("distance_m") is not none else "—" }}</td><td>{{ x.get("betreiber") or "—" }}{% if x.get("schnell") %} (Schnellladen){% endif %}</td><td class="num">{{ x.get("punkte") or "—" }}</td><td class="num">{{ x.kw|fmt_num(0) if x.get("kw") is not none else "—" }}</td><td class="xs">{{ x.get("adresse") or "" }}</td></tr>
  {% endfor %}
  </tbody>
</table>
{% endif %}
<p class="footnote">Ladesäulenregister der Bundesnetzagentur{% if d.get("stand") %}, Stand {{ d.stand|fmt_date }}{% endif %} (CC BY 4.0); nur gemeldete Ladeeinrichtungen in Betrieb.</p>
```

Fixture `"ladesaeulen"`:

```json
"ladesaeulen": {"key": "ladesaeulen", "tier": "area", "status": "ok", "message": null, "took_ms": 6,
  "source": "Bundesnetzagentur, Ladesäulenregister (CC BY 4.0) — nur gemeldete Ladeeinrichtungen in Betrieb",
  "data": {"radius_m": 1000, "stand": "2026-09-01", "anzahl_500m": 2, "anzahl_1000m": 3, "ladepunkte_1000m": 8, "schnell_1000m": 1,
           "naechste": [{"betreiber": "E.ON Drive Germany GmbH", "distance_m": 222, "punkte": 2, "kw": 22.0, "schnell": false, "adresse": "Rüttenscheider Str. 1, 45131 Essen"},
                        {"betreiber": "Fastned", "distance_m": 416, "punkte": 4, "kw": 300.0, "schnell": true, "adresse": "A40, 45141 Essen"}],
           "rating": "Ladepunkt in Gehweite", "rating_color": "green"}}
```

- [ ] **Step 6: Build the real file, suite, commit**

```bash
curl -sSL -o /tmp/lsr.csv "$(curl -s https://www.bundesnetzagentur.de/DE/Fachthemen/ElektrizitaetundGas/E-Mobilitaet/Ladesaeulenkarte/start.html | grep -oE 'https://data\.bundesnetzagentur\.de/[^"]*Ladesaeulenregister_BNetzA_[0-9-]+\.csv' | head -1)"
.venv/bin/python scripts/build_ladesaeulen.py --csv /tmp/lsr.csv     # verified 2026-09-06: 2,603 Ladeeinrichtungen in the window (the bbox also covers Mülheim, Gelsenkirchen, Hattingen …), 38 KB, Stand 2026-09-01
.venv/bin/python -m pytest -q
git add scripts/build_ladesaeulen.py redat/data/ladesaeulen.json.gz redat/sources/ladesaeulen.py redat/templates/analysis/_ladesaeulen.html redat/templates/report/_ladesaeulen.html redat/core redat/report/builder.py tests/
git commit -m "feat(ladesaeulen): public EV chargers within 1 km from the BNetzA register"
```

---

### Task 5: PDF figure "Der Ort im Wandel" (historic maps)

**Files:**
- Create: `redat/report/history_maps.py`
- Modify: `redat/report/service.py`, `redat/templates/report/_flurstueck.html`, `tests/test_report_render.py` (`EXTRA` gains `"history_maps": None`; a render test with a stub figure)
- Test: `tests/test_history_maps.py`

**Interfaces:**
- Produces: `history_maps.render_history_maps(lat, lon) -> {"panels": [{"key","title","image"(b64)|None}], "attribution": str, "error": str|None}`; `history_maps._get_png(url, params) -> bytes` (HTTP point, own copy so tests stub this module); reuses `noise_map.bbox_25832`, `noise_map._decorate`, `noise_map._to_b64`, `noise_map.WIDTH/HEIGHT`.

- [ ] **Step 1: Write the failing tests**

`tests/test_history_maps.py`:

```python
import base64
import io

from PIL import Image

from redat.report import history_maps as hm
from redat.report.noise_map import HEIGHT, WIDTH


def _png(color):
    buf = io.BytesIO()
    Image.new("RGB", (WIDTH, HEIGHT), color).save(buf, format="PNG")
    return buf.getvalue()


def test_four_panels_with_titles_and_fallback_year(monkeypatch):
    calls = []

    def fake(url, params):
        calls.append((url, params["LAYERS"]))
        if params["LAYERS"] == "nw_hist_dop_1952":
            return _png((255, 255, 255))      # blank tile → fall back to 1951
        return _png((120, 120, 120))
    monkeypatch.setattr(hm, "_get_png", fake)
    out = hm.render_history_maps(51.43, 7.005)
    assert [p["key"] for p in out["panels"]] == ["uraufnahme", "neuaufnahme", "dop_alt", "dop"]
    assert [p["title"] for p in out["panels"]] == ["Preußische Uraufnahme (1836–1850)", "Preußische Neuaufnahme (1891–1912)", "Luftbild 1951", "Luftbild heute"]
    assert all(Image.open(io.BytesIO(base64.b64decode(p["image"]))).size == (WIDTH, HEIGHT) for p in out["panels"])
    layers = [l for _, l in calls]
    assert "nw_uraufnahme_rw" in layers and "nw_neuaufnahme" in layers and "nw_dop_rgb" in layers
    assert layers.index("nw_hist_dop_1952") < layers.index("nw_hist_dop_1951")
    assert out["error"] is None and "Geobasis NRW" in out["attribution"]


def test_failed_panel_is_none_and_reported(monkeypatch):
    def fake(url, params):
        if "uraufnahme" in url:
            raise RuntimeError("WMS down")
        return _png((120, 120, 120))
    monkeypatch.setattr(hm, "_get_png", fake)
    out = hm.render_history_maps(51.43, 7.005)
    assert out["panels"][0]["image"] is None and "WMS down" in out["error"] and out["panels"][1]["image"]


def test_all_hist_dop_years_blank_gives_none_panel(monkeypatch):
    monkeypatch.setattr(hm, "_get_png", lambda url, params: _png((255, 255, 255)) if "hist_dop" in url else _png((90, 90, 90)))
    out = hm.render_history_maps(51.43, 7.005)
    dop_alt = out["panels"][2]
    assert dop_alt["image"] is None and dop_alt["title"] == "Luftbild 1950er" and "kein historisches Luftbild" in out["error"]


def test_is_blank():
    assert hm.is_blank(Image.new("RGBA", (10, 10), (255, 255, 255, 255)))
    assert not hm.is_blank(Image.new("RGBA", (10, 10), (100, 100, 100, 255)))
```

`tests/test_report_render.py`: `EXTRA` gains `"history_maps": None`; add:

```python
def test_flurstueck_partial_renders_history_figure():
    fig = {"panels": [{"key": "uraufnahme", "title": "Preußische Uraufnahme (1836–1850)", "image": "AAAA"}, {"key": "dop", "title": "Luftbild heute", "image": None}],
           "attribution": "© Geobasis NRW", "error": "Luftbild heute: down"}
    html = render_section_html("flurstueck", FIXTURES["flurstueck"]["data"], **{**EXTRA, "history_maps": fig})
    assert "Der Ort im Wandel" in html and "data:image/png;base64,AAAA" in html and "Karte nicht verfügbar" in html and "Altlastenverdacht" in html
```

- [ ] **Step 2: Run the tests to verify they fail** → `ModuleNotFoundError`, then the render assertion.

- [ ] **Step 3: Implement `history_maps.py`**

```python
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
```

- [ ] **Step 4: Wiring**

`redat/report/service.py`: import `from redat.report.history_maps import render_history_maps` and after the noise block add
`if body_keys & {"flurstueck", "bergbau"}: ctx["history_maps"] = render_history_maps(ctx["lat"], ctx["lon"])`.

Append to `redat/templates/report/_flurstueck.html`:

```html
{% if history_maps %}
<h3>Der Ort im Wandel</h3>
<div class="maps">
  {% for p in history_maps.panels %}
    {% if p.image %}<img src="data:image/png;base64,{{ p.image }}" alt="{{ p.title }}">{% else %}<div class="map-missing">Karte nicht verfügbar — {{ p.title }}</div>{% endif %}
  {% endfor %}
</div>
<p class="footnote">Ausschnitt ca. 600 × 450 m, Punkt im Zentrum. Zeche, Halde, Gleisanlage oder Fabrik auf einem alten Bild ist ein Altlastenverdacht — Auskunft bei der Unteren Bodenschutzbehörde. {{ history_maps.attribution }}{% if history_maps.error %} · Hinweis: {{ history_maps.error }}{% endif %}</p>
{% endif %}
```

(`report.html` already defines `.maps` as a 2-column grid, so four panels form 2×2.)

- [ ] **Step 5: Suite green, commit**

```bash
.venv/bin/python -m pytest -q
git add redat/report/history_maps.py redat/report/service.py redat/templates/report/_flurstueck.html tests/
git commit -m "feat(report): historic map panels 1840s/1900s/1950s/today on the Flurstück page"
```

---

### Task 6: PDF figure "Grün und Hitze" (RVR climate layers as images)

**Files:**
- Create: `redat/report/climate_maps.py`
- Modify: `redat/report/service.py`, `redat/templates/report/_zensus.html`, `tests/test_report_render.py` (`EXTRA` gains `"climate_maps": None`; one render test)
- Test: `tests/test_climate_maps.py`

**Interfaces:**
- Produces: `climate_maps.render_climate_maps(lat, lon) -> {"panels": [{"key","title","image","legend"}], "attribution", "error"}`; `climate_maps._get_png(url, params)` (HTTP point); 2 km window (`WINDOW_M = 2000`), own `bbox_2km()` and `decorate()` (500 m scale bar).

- [ ] **Step 1: Write the failing tests**

`tests/test_climate_maps.py`:

```python
import base64
import io

from PIL import Image

from redat.report import climate_maps as cm


def _png(size, color):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def test_two_panels_with_legends_over_2km(monkeypatch):
    calls = []

    def fake(url, params):
        calls.append(params)
        if params.get("REQUEST") == "GetLegendGraphic":
            return _png((88, 50), (200, 50, 50))
        return _png((cm.WIDTH, cm.HEIGHT), (120, 160, 120))
    monkeypatch.setattr(cm, "_get_png", fake)
    out = cm.render_climate_maps(51.43, 7.005)
    assert [p["key"] for p in out["panels"]] == ["beschirmung", "oberflaechentemperatur"]
    assert all(p["image"] and p["legend"] for p in out["panels"]) and out["error"] is None
    maps = [p for p in calls if p.get("REQUEST") == "GetMap"]
    xmin, ymin, xmax, ymax = (float(v) for v in maps[0]["BBOX"].split(","))
    assert abs((xmax - xmin) - 2000) < 0.01 and maps[0]["CRS"] == "EPSG:25832"
    legends = [p for p in calls if p.get("REQUEST") == "GetLegendGraphic"]
    assert all(p["SLD_VERSION"] == "1.1.0" for p in legends) and {p["STYLE"] for p in legends} == {"default", "day"}
    assert Image.open(io.BytesIO(base64.b64decode(out["panels"][0]["image"]))).size == (cm.WIDTH, cm.HEIGHT)


def test_legend_failure_keeps_panel(monkeypatch):
    def fake(url, params):
        if params.get("REQUEST") == "GetLegendGraphic":
            raise RuntimeError("no legend")
        return _png((cm.WIDTH, cm.HEIGHT), (120, 160, 120))
    monkeypatch.setattr(cm, "_get_png", fake)
    out = cm.render_climate_maps(51.43, 7.005)
    assert out["panels"][0]["image"] and out["panels"][0]["legend"] is None and "no legend" in out["error"]


def test_map_failure_is_none(monkeypatch):
    def fake(url, params):
        if params.get("LAYERS") == "beschirmungsgrad":
            raise RuntimeError("down")
        return _png((88, 50), (1, 2, 3))
    monkeypatch.setattr(cm, "_get_png", fake)
    out = cm.render_climate_maps(51.43, 7.005)
    assert out["panels"][0]["image"] is None and "down" in out["error"]
```

`tests/test_report_render.py`: `EXTRA` gains `"climate_maps": None`; add:

```python
def test_zensus_partial_renders_climate_figure():
    fig = {"panels": [{"key": "beschirmung", "title": "Beschirmungsgrad", "image": "AAAA", "legend": "BBBB"},
                      {"key": "oberflaechentemperatur", "title": "Oberflächentemperatur 13:30 Uhr (Sommer)", "image": None, "legend": None}],
           "attribution": "© RVR", "error": "x"}
    html = render_section_html("zensus", FIXTURES["zensus"]["data"], **{**EXTRA, "climate_maps": fig})
    assert "Grün und Hitze" in html and "base64,AAAA" in html and "base64,BBBB" in html and "Karte nicht verfügbar" in html
```

- [ ] **Step 2: Run the tests to verify they fail** → `ModuleNotFoundError`.

- [ ] **Step 3: Implement `climate_maps.py`**

```python
"""Two RVR Umweltmonitoring panels for the PDF: tree canopy (Beschirmungsgrad) and summer surface temperature.

WMS https://services-rvr.geoportal.ruhr/umon/<service> (Regionalverband Ruhr, "lizenzkostenfrei"; verified
2026-09-06): `veg_schirm` layer `beschirmungsgrad` (10 m, share of area under vegetation) and `oftemp` layer
`Oberflaechentemperatur_1330` with STYLE `day` (MODIS 1 km, summer median 13:30 °C). GetFeatureInfo returns no
values and the legends are continuous ramps, so the layers are shown as images with their own legend PNGs
(GetLegendGraphic needs SLD_VERSION=1.1.0). 2 km window because the temperature pixels are 1 km.
`_get_png` is the HTTP/monkeypatch point.
"""
from __future__ import annotations

import base64
import io
import logging
from typing import Optional

import httpx
from PIL import Image, ImageDraw
from pyproj import Transformer

from redat.http import headers

logger = logging.getLogger(__name__)

WIDTH, HEIGHT = 480, 360
WINDOW_M = 2000.0
TIMEOUT_S = 15.0
BASE = "https://services-rvr.geoportal.ruhr/umon/"
PANELS = (
    ("beschirmung", "Beschirmungsgrad (Baumkronen)", "veg_schirm", "beschirmungsgrad", "default"),
    ("oberflaechentemperatur", "Oberflächentemperatur 13:30 Uhr (Sommer)", "oftemp", "Oberflaechentemperatur_1330", "day"),
)
ATTRIBUTION = "© Regionalverband Ruhr, Umweltmonitoring (Beschirmungsgrad 10 m; Oberflächentemperatur MODIS 1 km, Sommer-Median)"
_TO_UTM = Transformer.from_crs("EPSG:4326", "EPSG:25832", always_xy=True)


def bbox_2km(lat: float, lon: float) -> tuple[float, float, float, float]:
    x, y = _TO_UTM.transform(lon, lat)
    hw, hh = WINDOW_M / 2, WINDOW_M * HEIGHT / WIDTH / 2
    return x - hw, y - hh, x + hw, y + hh


def _get_png(url: str, params: dict) -> bytes:
    r = httpx.get(url, params=params, timeout=TIMEOUT_S, headers=headers())
    r.raise_for_status()
    if not r.headers.get("content-type", "").startswith("image/"):
        raise RuntimeError(f"WMS lieferte {r.headers.get('content-type') or 'keine'} statt eines Bildes")
    return r.content


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def decorate(im: Image.Image, title: str) -> Image.Image:
    draw = ImageDraw.Draw(im)
    cx, cy = WIDTH // 2, HEIGHT // 2
    draw.ellipse((cx - 9, cy - 9, cx + 9, cy + 9), fill=(255, 255, 255, 255))
    draw.ellipse((cx - 6, cy - 6, cx + 6, cy + 6), fill=(220, 38, 38, 255))
    bar = int(round(500 * WIDTH / WINDOW_M))
    x0, y0 = 12, HEIGHT - 16
    draw.rectangle((x0 - 4, y0 - 16, x0 + bar + 44, y0 + 8), fill=(255, 255, 255, 220))
    draw.rectangle((x0, y0, x0 + bar, y0 + 4), fill=(17, 24, 39, 255))
    draw.text((x0 + bar + 6, y0 - 7), "500 m", fill=(17, 24, 39, 255))
    tw = int(draw.textlength(title)) if hasattr(draw, "textlength") else 8 * len(title)
    draw.rectangle((8, 8, 8 + tw + 12, 26), fill=(255, 255, 255, 230))
    draw.text((14, 11), title, fill=(17, 24, 39, 255))
    return im


def render_climate_maps(lat: float, lon: float) -> dict:
    bbox = bbox_2km(lat, lon)
    panels, errors = [], []
    for key, title, service, layer, style in PANELS:
        url = BASE + service
        image: Optional[str] = None
        legend: Optional[str] = None
        try:
            raw = _get_png(url, {"SERVICE": "WMS", "VERSION": "1.3.0", "REQUEST": "GetMap", "CRS": "EPSG:25832",
                                 "BBOX": ",".join(f"{v:.3f}" for v in bbox), "WIDTH": WIDTH, "HEIGHT": HEIGHT,
                                 "FORMAT": "image/png", "LAYERS": layer, "STYLES": style, "TRANSPARENT": "TRUE"})
            im = Image.open(io.BytesIO(raw)); im.load()
            im = im.convert("RGBA").resize((WIDTH, HEIGHT))
            buf = io.BytesIO(); decorate(im, title).convert("RGB").save(buf, format="PNG", optimize=True)
            image = _b64(buf.getvalue())
        except Exception as e:  # noqa: BLE001
            logger.warning("climate map %s failed: %s", key, e)
            errors.append(f"{title}: {e}")
        try:
            legend = _b64(_get_png(url, {"SERVICE": "WMS", "VERSION": "1.3.0", "REQUEST": "GetLegendGraphic", "LAYER": layer,
                                         "FORMAT": "image/png", "STYLE": style, "SLD_VERSION": "1.1.0"}))
        except Exception as e:  # noqa: BLE001
            logger.warning("climate legend %s failed: %s", key, e)
            errors.append(f"Legende {title}: {e}")
        panels.append({"key": key, "title": title, "image": image, "legend": legend})
    return {"panels": panels, "attribution": ATTRIBUTION, "error": " · ".join(errors) or None}
```

- [ ] **Step 4: Wiring**

`service.py`: `from redat.report.climate_maps import render_climate_maps` and `if "zensus" in body_keys: ctx["climate_maps"] = render_climate_maps(ctx["lat"], ctx["lon"])`.

Append to `redat/templates/report/_zensus.html`:

```html
{% if climate_maps %}
<h3>Grün und Hitze</h3>
<div class="maps">
  {% for p in climate_maps.panels %}
    <div>
      {% if p.image %}<img src="data:image/png;base64,{{ p.image }}" alt="{{ p.title }}">{% else %}<div class="map-missing">Karte nicht verfügbar — {{ p.title }}</div>{% endif %}
      {% if p.legend %}<img src="data:image/png;base64,{{ p.legend }}" alt="Legende {{ p.title }}" style="width: auto; max-height: 14mm; border: none; margin-top: 1mm">{% endif %}
    </div>
  {% endfor %}
</div>
<p class="footnote">Ausschnitt ca. 2 × 1,5 km, Punkt im Zentrum. Viel Baumkronen im Umfeld dämpfen Sommerhitze; die Oberflächentemperatur zeigt Hitzeinseln (1-km-Raster, kein Messwert am Haus). {{ climate_maps.attribution }}{% if climate_maps.error %} · Hinweis: {{ climate_maps.error }}{% endif %}</p>
{% endif %}
```

- [ ] **Step 5: Suite green, commit**

```bash
.venv/bin/python -m pytest -q
git add redat/report/climate_maps.py redat/report/service.py redat/templates/report/_zensus.html tests/
git commit -m "feat(report): RVR canopy and surface-temperature panels on the Nachbarschaft page"
```

---

### Task 7: Bodenbewegung (EGMS) on the Bergbau card — data-gated

**Files:**
- Create: `scripts/build_egms.py`, `redat/sources/bodenbewegung.py`
- Modify: `redat/core/sections.py` (`_fetch_bergbau`, `cache_version=3`), `redat/templates/analysis/_bergbau.html`, `redat/templates/report/_bergbau.html`, `redat/report/builder.py`, `tests/fixtures/report_envelopes.json`, `tests/test_analysis_sections.py`
- Test: `tests/test_build_egms.py`, `tests/test_bodenbewegung.py`
- Data: `redat/data/egms_vertical_velocity.json.gz` is committed only once the user has downloaded the tile (see Step 6); until then the card shows the "nicht installiert" hint.

**Interfaces:**
- Build: `read_geotiff(path) -> (arr, x0, y0, px)` (Pillow; tags 33550 ModelPixelScale, 33922 ModelTiepoint; `x0,y0` = top-left corner in EPSG:3035), `crop_cells(arr, x0, y0, px, bbox3035) -> dict[str, float]` (`"x_y"` cell-centre keys, mm/a, NoData skipped), output `{"years": "2019-2023", "cell_m": 100, "cells": {...}}`.
- Source: `bodenbewegung.lookup(lat, lon) -> Optional[dict]` (None without grid or no cell within 500 m): `mm_a, mean_3x3, min_500m, max_500m, klasse, klasse_color, richtung, years, cell_m`; `bodenbewegung._load()` monkeypatch point.

- [ ] **Step 1: Write the failing tests**

`tests/test_build_egms.py`:

```python
import importlib.util
from pathlib import Path

import numpy as np

_spec = importlib.util.spec_from_file_location("build_egms", Path(__file__).resolve().parent.parent / "scripts" / "build_egms.py")
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


def test_crop_cells_keeps_window_and_skips_nodata():
    arr = np.full((4, 4), -1.5, dtype=np.float32)      # 4×4 cells of 100 m, top-left corner at (4_100_000, 3_160_000)
    arr[0, 0] = mod.NODATA
    arr[3, 3] = 2.25
    cells = mod.crop_cells(arr, 4_100_000, 3_160_000, 100, (4_100_000, 3_159_600, 4_100_400, 3_160_000))
    assert cells["4100350_3159650"] == 2.25 and cells["4100150_3159950"] == -1.5   # row 3 is the southern row
    assert "4100050_3159950" not in cells and len(cells) == 15


def test_crop_cells_bbox_excludes_outside():
    arr = np.zeros((2, 2), dtype=np.float32)
    assert mod.crop_cells(arr, 0, 200, 100, (150, 0, 200, 50)) == {"150_50": 0.0}
```

`tests/test_bodenbewegung.py`:

```python
import pytest

from redat.sources import bodenbewegung as bb
from pyproj import Transformer

T = Transformer.from_crs("EPSG:4326", "EPSG:3035", always_xy=True)
X, Y = T.transform(7.0050, 51.4300)
CX, CY = int(X // 100) * 100 + 50, int(Y // 100) * 100 + 50


def grid(centre=-6.0, ring=-1.0, far=3.0):
    cells = {f"{CX + dx * 100}_{CY + dy * 100}": (centre if dx == dy == 0 else ring) for dx in (-1, 0, 1) for dy in (-1, 0, 1)}
    cells[f"{CX + 400}_{CY}"] = far
    return {"years": "2019-2023", "cell_m": 100, "cells": cells}


def test_classes():
    assert bb.classify(-0.5) == ("stabil", "green") and bb.classify(3.0) == ("leichte Bewegung", "yellow")
    assert bb.classify(-7.0) == ("deutliche Bewegung", "orange") and bb.classify(12.0) == ("starke Bewegung", "red")


def test_lookup_reports_cell_neighbourhood_and_direction(monkeypatch):
    monkeypatch.setattr(bb, "_load", grid)
    d = bb.lookup(51.4300, 7.0050)
    assert d["mm_a"] == -6.0 and d["klasse"] == "deutliche Bewegung" and d["richtung"] == "Senkung"
    assert d["mean_3x3"] == pytest.approx(-1.56, abs=0.01) and d["min_500m"] == -6.0 and d["max_500m"] == 3.0
    assert d["years"] == "2019-2023" and d["cell_m"] == 100


def test_uplift_and_missing(monkeypatch):
    monkeypatch.setattr(bb, "_load", lambda: grid(centre=4.0))
    assert bb.lookup(51.4300, 7.0050)["richtung"] == "Hebung"
    monkeypatch.setattr(bb, "_load", lambda: {"years": "x", "cell_m": 100, "cells": {}})
    assert bb.lookup(51.4300, 7.0050) is None
    monkeypatch.setattr(bb, "_load", lambda: None)
    assert bb.lookup(51.4300, 7.0050) is None
```

`tests/test_analysis_sections.py` — extend `test_bergbau_merges_berechtigungen` (from Task 1) with:

```python
    from redat.sources import bodenbewegung
    monkeypatch.setattr(bodenbewegung, "lookup", lambda lat, lon: {"mm_a": -6.0, "klasse": "deutliche Bewegung"})
    d = S._fetch_bergbau(CTX)
    assert d["bodenbewegung"]["mm_a"] == -6.0 and d["bodenbewegung_hinweis"] is None
    monkeypatch.setattr(bodenbewegung, "lookup", lambda lat, lon: None)
    d = S._fetch_bergbau(CTX)
    assert d["bodenbewegung"] is None and "EGMS" in d["bodenbewegung_hinweis"]
    assert S.SECTIONS["bergbau"].cache_version == 3
```

Render needles for `"bergbau"`: append `"Senkung"`.

- [ ] **Step 2: Run the tests to verify they fail** → module/script missing.

- [ ] **Step 3: Build script**

`scripts/build_egms.py`:

```python
"""Crop the Copernicus EGMS L3 Ortho vertical-velocity tile to the Essen/Bochum window → redat/data/egms_vertical_velocity.json.gz.

Input: the GeoTIFF `EGMS_L3_E41N31_100km_U_<from>_<to>_<v>.tif` (tile E41N31 covers Essen and Bochum; ETRS89-LAEA
EPSG:3035, 100 m pixels, mean vertical velocity in mm/year, positive = uplift). It is a free download behind an EU
Login — either the Explorer (https://egms.land.copernicus.eu/ → geographical search → tile list → "L3 Ortho U") or the
insar-api with a CLMS API token (`~/.config/nrw-redat/egms_download.py E41N31`, kept outside the repo with the token;
search `POST /insar-api/archive/search {tileId, levels:[L3], releases, productType:ORTHO-UP}`, then
`GET /download/<filename>?id=<query id>&token=<access token>`). The zip holds the .tiff plus a 488 MB CSV — only the
.tiff (renamed .tif) is needed. Georeference is read from the GeoTIFF tags with Pillow (33550 ModelPixelScaleTag,
33922 ModelTiepointTag); NoData is the tile's GDAL_NODATA tag (42113, -9999) — but the 2020-2024 tile actually stores
NaN in unmeasured cells, so both are skipped.

Usage:
    .venv/bin/python scripts/build_egms.py --tif ~/Downloads/EGMS_L3_E41N31_100km_U_2020_2024_1.tif
"""
from __future__ import annotations

import argparse
import gzip
import json
import re
from pathlib import Path

import numpy as np
from PIL import Image
from pyproj import Transformer

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "redat" / "data" / "egms_vertical_velocity.json.gz"
BBOX_WGS84 = (6.85, 51.33, 7.40, 51.56)
NODATA = -9999.0
_TAG_SCALE, _TAG_TIEPOINT, _TAG_NODATA = 33550, 33922, 42113


def read_geotiff(path: Path) -> tuple[np.ndarray, float, float, float, float]:
    """(array, x0, y0, pixel_size, nodata) — x0/y0 is the top-left corner in the raster CRS."""
    im = Image.open(path)
    im.load()
    tags = im.tag_v2
    sx, sy = float(tags[_TAG_SCALE][0]), float(tags[_TAG_SCALE][1])
    tp = tags[_TAG_TIEPOINT]                      # (i, j, k, x, y, z)
    x0, y0 = float(tp[3]) - float(tp[0]) * sx, float(tp[4]) + float(tp[1]) * sy
    nodata = float(tags[_TAG_NODATA]) if _TAG_NODATA in tags else NODATA
    return np.asarray(im, dtype=np.float32), x0, y0, sx, nodata


def crop_cells(arr: np.ndarray, x0: float, y0: float, px: float, bbox3035: tuple[float, float, float, float], nodata: float = NODATA) -> dict[str, float]:
    """Cells whose centre lies in bbox3035 → {"x_y": mm/a}; row 0 is the northern row."""
    xmin, ymin, xmax, ymax = bbox3035
    out: dict[str, float] = {}
    rows, cols = arr.shape
    for r in range(rows):
        cy = y0 - (r + 0.5) * px
        if not (ymin <= cy <= ymax):
            continue
        for c in range(cols):
            cx = x0 + (c + 0.5) * px
            v = float(arr[r, c])
            if not (xmin <= cx <= xmax) or v == nodata or not np.isfinite(v):
                continue
            out[f"{int(cx)}_{int(cy)}"] = round(v, 2)
    return out


def bbox_3035() -> tuple[float, float, float, float]:
    t = Transformer.from_crs("EPSG:4326", "EPSG:3035", always_xy=True)
    xs, ys = zip(*(t.transform(lon, lat) for lon, lat in ((BBOX_WGS84[0], BBOX_WGS84[1]), (BBOX_WGS84[2], BBOX_WGS84[1]),
                                                           (BBOX_WGS84[0], BBOX_WGS84[3]), (BBOX_WGS84[2], BBOX_WGS84[3]))))
    return min(xs), min(ys), max(xs), max(ys)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tif", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args()
    arr, x0, y0, px, nodata = read_geotiff(a.tif)
    cells = crop_cells(arr, x0, y0, px, bbox_3035(), nodata)
    m = re.search(r"_U_(\d{4})_(\d{4})_", a.tif.name)
    years = f"{m.group(1)}-{m.group(2)}" if m else "unbekannt"
    a.out.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(a.out, "wt", encoding="utf-8") as fh:
        json.dump({"years": years, "cell_m": int(px), "cells": cells}, fh, separators=(",", ":"))
    print(f"wrote {a.out}: {len(cells)} cells, years {years}, pixel {px} m")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Source module**

`redat/sources/bodenbewegung.py`:

```python
"""Bodenbewegung — Copernicus EGMS vertical ground velocity (InSAR, 100 m grid) at the point.

Data: redat/data/egms_vertical_velocity.json.gz (scripts/build_egms.py; a free EU-Login download, see the script).
mm/year, positive = Hebung (Grubenwasseranstieg shows as uplift in the Ruhrgebiet), negative = Senkung.
Classes on |v|: < 2 stabil (green), 2–5 leichte Bewegung (yellow), 5–10 deutliche Bewegung (orange), > 10 starke
Bewegung (red). `_load` is the monkeypatch point.
"""
from __future__ import annotations

import gzip
import json
from functools import lru_cache
from pathlib import Path
from typing import Optional

from pyproj import Transformer

GRID_PATH = Path(__file__).resolve().parent.parent / "data" / "egms_vertical_velocity.json.gz"
_TO_3035 = Transformer.from_crs("EPSG:4326", "EPSG:3035", always_xy=True)
_RING_500M = 5   # cells on each side → 11×11 = ±550 m


@lru_cache(maxsize=1)
def _load() -> Optional[dict]:
    try:
        with gzip.open(GRID_PATH, "rt", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def classify(v: float) -> tuple[str, str]:
    a = abs(v)
    if a > 10:
        return "starke Bewegung", "red"
    if a > 5:
        return "deutliche Bewegung", "orange"
    if a >= 2:
        return "leichte Bewegung", "yellow"
    return "stabil", "green"


def lookup(lat: float, lon: float) -> Optional[dict]:
    grid = _load()
    if not grid:
        return None
    cell = int(grid.get("cell_m") or 100)
    cells = grid.get("cells") or {}
    x, y = _TO_3035.transform(lon, lat)
    cx, cy = int(x // cell) * cell + cell // 2, int(y // cell) * cell + cell // 2

    def get(dx: int, dy: int) -> Optional[float]:
        return cells.get(f"{cx + dx * cell}_{cy + dy * cell}")

    centre = get(0, 0)
    if centre is None:
        return None
    near = [v for dx in (-1, 0, 1) for dy in (-1, 0, 1) if (v := get(dx, dy)) is not None]
    ring = [v for dx in range(-_RING_500M, _RING_500M + 1) for dy in range(-_RING_500M, _RING_500M + 1) if (v := get(dx, dy)) is not None]
    klasse, color = classify(centre)
    return {
        "mm_a": centre, "mean_3x3": round(sum(near) / len(near), 2), "min_500m": min(ring), "max_500m": max(ring),
        "klasse": klasse, "klasse_color": color, "richtung": "Hebung" if centre > 0 else "Senkung" if centre < 0 else "keine",
        "years": grid.get("years"), "cell_m": cell,
    }
```

- [ ] **Step 5: Wiring**

In `_fetch_bergbau` (Task 1 version) add after the Berechtigungen block:

```python
    from redat.sources import bodenbewegung
    b["bodenbewegung"], b["bodenbewegung_hinweis"] = None, None
    try:
        b["bodenbewegung"] = bodenbewegung.lookup(ctx.lat, ctx.lon)
    except Exception as exc:  # noqa: BLE001
        logger.warning("bodenbewegung: %s", exc)
    if b["bodenbewegung"] is None:
        b["bodenbewegung_hinweis"] = "EGMS-Bodenbewegungsdaten nicht installiert oder keine Messzelle im Umkreis (siehe scripts/build_egms.py)"
```

Registry: `cache_version=3` for `bergbau`; source string gains `" · Copernicus EGMS Bodenbewegung"`.

`_s_bergbau`: `bw = d.get("bodenbewegung") or {}` and `if bw.get("mm_a") is not None: fig += f" · Bodenbewegung {fmt_num(bw['mm_a'], 1)} mm/a ({bw.get('richtung')})"`.

Web partial `_bergbau.html` — after the Berechtigungen block:

```html
<template x-if="d.bodenbewegung">
    <div class="mt-4 text-sm">
        <div class="font-semibold text-gray-900">📡 Bodenbewegung (Satellit, <span x-text="d.bodenbewegung.years"></span>)</div>
        <div class="mt-1 flex items-center gap-3">
            <span class="px-2 py-0.5 rounded-full text-xs font-bold" :class="$store.app.getAirQualityColor(d.bodenbewegung.klasse_color)" x-text="d.bodenbewegung.klasse"></span>
            <span class="text-gray-900 font-medium" x-text="d.bodenbewegung.mm_a + ' mm/Jahr ' + d.bodenbewegung.richtung"></span>
            <span class="text-gray-500 text-xs" x-text="'Umkreis 500 m: ' + d.bodenbewegung.min_500m + ' bis ' + d.bodenbewegung.max_500m + ' mm/Jahr'"></span>
        </div>
        <p class="mt-1 text-xs text-gray-500">Mittlere vertikale Geschwindigkeit der 100-m-Zelle (Copernicus EGMS, InSAR). Hebung ist im Ruhrgebiet oft Folge des Grubenwasseranstiegs; ungleichmäßige Bewegung im Umkreis ist das Warnsignal für Bergschäden.</p>
    </div>
</template>
<p class="mt-2 text-xs text-gray-500" x-show="d.bodenbewegung_hinweis" x-text="d.bodenbewegung_hinweis"></p>
```

Report partial `_bergbau.html` — before the footnote:

```html
{% set bw = d.get("bodenbewegung") %}
{% if bw %}
<p>Bodenbewegung (Copernicus EGMS{% if bw.get("years") %} {{ bw.years }}{% endif %}): <span class="chip {{ rating_class(bw.get('klasse_color')) }}">{{ bw.get("klasse") or "—" }}</span> {{ bw.mm_a|fmt_num(1) if bw.get("mm_a") is not none else "—" }} mm/Jahr {{ bw.get("richtung") or "" }}{% if bw.get("min_500m") is not none %}; Umkreis 500 m {{ bw.min_500m|fmt_num(1) }} bis {{ bw.max_500m|fmt_num(1) }} mm/Jahr{% endif %}.</p>
{% endif %}
```

Fixture: add to `bergbau` data `"bodenbewegung": {"mm_a": -6.0, "mean_3x3": -4.2, "min_500m": -8.1, "max_500m": 1.2, "klasse": "deutliche Bewegung", "klasse_color": "orange", "richtung": "Senkung", "years": "2019-2023", "cell_m": 100}, "bodenbewegung_hinweis": null`.

- [ ] **Step 6: Data (needs the user's download)**

`~/Downloads/EGMS_L3_E41N31_100km_U_2020_2024_1.tif` is present (downloaded 2026-09-06 via the insar-api). Run `scripts/build_egms.py --tif <file>`, check the printed cell count (the window is ~38 × 26 km → 106,896 cells of which 67,564 are measured, a few hundred KB gzipped; expect a median of about -1 mm/a, minimum about -28 mm/a near 51.559 N / 7.132 E) and commit `redat/data/egms_vertical_velocity.json.gz`. If it does not exist, commit code and tests only; the card shows the "nicht installiert" hint until the file is added.

- [ ] **Step 7: Suite green, commit**

```bash
.venv/bin/python -m pytest -q
git add scripts/build_egms.py redat/sources/bodenbewegung.py redat/core/sections.py redat/report/builder.py redat/templates/analysis/_bergbau.html redat/templates/report/_bergbau.html tests/ redat/data/egms_vertical_velocity.json.gz 2>/dev/null
git commit -m "feat(bergbau): EGMS vertical ground motion at the point (data-gated)"
```

---

### Task 8: Documentation, CSS rebuild, live verification

**Files:** `README.md`, `HANDOVER.md`, `CLAUDE.md`, `redat/static/redat.css`

- [ ] **Step 1: README** — extend the "Static grids in the repo" table with `bergbauberechtigungen.geojson.gz` (build_bergbauberechtigungen.py, opengeodata, a few times a year), `ladesaeulen.json.gz` (build_ladesaeulen.py, BNetzA, monthly), `egms_vertical_velocity.json.gz` (build_egms.py, Copernicus EGMS, yearly, EU Login); add the `ladesaeulen` card and the three extensions plus the two PDF figures to the card overview; update the card count (27).
- [ ] **Step 2: HANDOVER** — work-log entry "Tier-2 sources" listing tasks 1–7, the `cache_version` bumps (bergbau 3, starkregen 2, noise 2), the RVR-WMS finding (GetFeatureInfo carries no values; continuous legends → image-only), and the data-gated items with what unblocks them (Altlasten e-mails, Regionaldatenbank registration for Hebesätze, EGMS download).
- [ ] **Step 3: CLAUDE.md** — card count 27, test count from `pytest -q`, and one line in Rules: "WCS `wcs_nw_dgm` returns float32 GeoTIFF (row 0 = north); the RVR umon WMS answers GetFeatureInfo without values — use GetMap images."
- [ ] **Step 4: CSS** — `npx tailwindcss@3 -c tailwind.config.js -i tailwind.input.css -o redat/static/redat.css --minify`.
- [ ] **Step 5: Verification** — full suite; start a local instance on :8201 with a scratch `REDAT_DATA_DIR` (as in Tier 1 Task 14) and call `/api/v1/section/{bergbau,starkregen,noise,ladesaeulen}?lat=51.4300&lon=7.0050&precision=building&fresh=1`, `noise` at Kettwig `51.362/6.940` (expects Fluglärm DUS), `noise` at Bochum `51.4818/7.2162`; then `GET /api/v1/report?address=Herthastraße 4, 45131 Essen` — in the production image the PDF must contain both new figures (check the PDF page count grew and grep the HTML via `render_report_html` for "Der Ort im Wandel" and "Grün und Hitze"). Record every figure in the report.
- [ ] **Step 6: Commit** — `git commit -m "docs: Tier-2 sources — README grids and cards, HANDOVER log, CLAUDE.md; rebuild CSS"` plus trailers.
