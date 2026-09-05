# Analyze page rework — design

**Date:** 2026-09-04
**Scope:** the `/analyze` page (Standort-Analyse), its JavaScript, and the API contract that feeds it. The individual data services (BORIS, flood, Geoapify, …), the listing-enrichment worker, and the detail page's enrichment display are out of scope except where a shared bug is fixed at its source.

## 1. Why

The page fans out to ten `/api/enrichment/*` endpoints and hand-maps each raw response shape in JavaScript. There is no contract between the two sides, and the mapping has drifted. Live-verified on 2026-09-04 against the running service:

| # | Symptom | Root cause |
|---|---|---|
| 1 | Politics loaded but never displayed | Backend returns `top_parties`; template gates on `btw.parties`. Broken since the initial commit. |
| 2 | Map has no pin and is not centered | `#result-map` sits inside `x-show="result && !loading"`, so `initMap()` polls until loading ends; `$watch('result')` fires *during* loading while `this.map` is `null` and `updateMapMarker` returns early. Nothing re-triggers it. |
| 3 | Flood card never shows; one request 500s | JS reads `flood_zone`/`flood_risk_level`, backend returns `zone`/`risk_level`. Separately `flood_service` returns `min_distance_m = inf` when no polygon lies within 2 km, which FastAPI's JSON encoder rejects. |
| 4 | Planning cards show "—" even when plans are found | JS reads `planning.usage`; Essen returns six typed lists, Bochum returns `items`. |
| 5 | `/analyze?listing_id=X` is dead for 459 of 829 active listings | `plotSize: {{ listing.plot_size_m2 }}` renders `None` → JS `ReferenceError` → the Alpine component never initializes. |
| 6 | Lärm card never shows | Nothing produces `noise_road_day`; no numeric noise source exists in the codebase. |
| 7 | Stale cards on a second search | `enrich()` resets `result` only; `btw/airQuality/gfnp/planning/commutes` survive, and the BTW chart's `x-if` stays truthy so it never re-renders. |
| 8 | Wasted work | Route runs a 120-row `SELECT` for a `listings` dropdown the template never renders; `save-listing` has no UI caller. |
| 9 | Correctness gap | Analyze bypasses `enrichment_allowed()`: parcel-tier BORIS/flood/planning run on street-centroid geocodes, unlike the detail page. |

A previous fix (`6bf2805`, defensive optional chaining) patched symptoms; the drift returned because nothing enforces the contract. This rework introduces that contract.

## 2. Decisions taken

- **Scope:** analyze page + its API contract only (option A of three).
- **Precision gate:** parcel-tier sections are gated like the detail page, with a visible "gesperrt" state and a per-card / global "Trotzdem laden" override. Area-tier sections always run.
- **Noise:** wire a real noise section to the NRW Lärm WMS `GetFeatureInfo` (feasibility probed live, see §4.2).
- **Architecture:** server-side section registry with a fixed per-section envelope and one normalized endpoint per section; the frontend renders generically. Progressive loading and per-section retry are preserved. (A single streaming endpoint and an in-place patch were considered and rejected: the former still needs per-section endpoints for override/retry and adds async complexity; the latter is what failed last time.)
- **Entry from a listing** auto-runs the analysis (today it only prefills).

## 3. Backend

### 3.1 Package `backend/analysis/`

**`sections.py`** — the single declaration of what the page can show.

```python
@dataclass(frozen=True)
class Ctx:
    lat: float
    lon: float
    plot_size_m2: float | None = None

@dataclass(frozen=True)
class Section:
    key: str
    title: str
    icon: str
    timeout_s: float
    source: str                                  # attribution line
    fetch: Callable[[Ctx], dict | None]          # normalized data, or None = "nothing here"

    @property
    def tier(self) -> str:                       # "parcel" | "area"
        return enrichment_service.SERVICE_TIER[self.key]

SECTIONS: dict[str, Section]                     # insertion order == card order
def manifest() -> list[dict]                     # [{key, title, icon, tier, timeout_s}]
```

`tier` is read from the existing `enrichment_service.SERVICE_TIER` so the gate rule has exactly one source; `noise` is added to that map as `"area"`. Every `fetch` calls an existing service module and returns the normalized shape from §4 — the *only* place a service's raw keys are translated.

**`envelope.py`**

```python
def run_section(key: str, ctx: Ctx, *, precision: str | None, force: bool) -> dict
```

Always returns, never raises:

```json
{"key": "...", "tier": "parcel|area",
 "status": "ok|empty|gated|error",
 "data": {...} | null, "message": "..." | null,
 "source": "...", "took_ms": 123}
```

- `gated` — `tier == "parcel"`, `not force`, and `precision not in ("building", "coordinates")`. `message` names the precision found ("Adresse nur straßengenau — Parzellendaten benötigen eine Hausnummer").
- `empty` — `fetch` returned `None`. `message` optional (e.g. commute: "Keine Zieladressen konfiguriert").
- `error` — `fetch` raised, or exceeded `timeout_s` (run in a single-worker `ThreadPoolExecutor`; `future.result(timeout=…)`; the worker thread is abandoned on timeout). `message` is the exception text or "Timeout nach Ns".
- `ok` — `data` is the normalized shape, passed through `sanitize()`.

`sanitize(obj)` recursively converts non-finite floats to `None` and numpy scalars to Python scalars. It is applied to every envelope, so the `inf`-class 500 cannot occur on these routes. `flood_service` is additionally fixed at the source: `FloodHit.min_distance_m: float | None`, `None` instead of `float("inf")`.

**`backend/geocoding.py`** — `geocode_with_precision(address)` is moved here from `routes/enrichment.py` (re-exported there as `_geocode_with_precision` so the address flow and its tests are untouched) and extended: an input matching `^\s*(-?\d+(\.\d+)?)\s*,\s*(-?\d+(\.\d+)?)\s*$` is parsed as `lat, lon` and returned with `precision = "coordinates"` and `formatted_address = "lat, lon"`. Return type becomes a small dataclass `GeocodeResult(latitude, longitude, precision, formatted_address)` (the route-side tuple is kept via the re-export wrapper).

### 3.2 Routes `backend/routes/analysis.py`

| Route | Returns |
|---|---|
| `GET /api/analysis/geocode?address=` | `{address, formatted_address, latitude, longitude, precision}`; geocoding failure → HTTP 422 `{detail}` |
| `GET /api/analysis/section/{key}?lat&lon&precision[&plot_size_m2][&force=1]` | envelope (§3.1); unknown key → 404 |

The manifest is not a route: `routes/html.py`'s `analyze_page` injects `analysis.sections.manifest()` into the template via `|tojson` together with the listing prefill (§5.1).

### 3.3 Removed

After each is confirmed caller-less by grep during implementation:

- `GET /api/enrichment/{analyze, amenities, air-quality, politics/btw, landuse/gfnp, planning/essen, planning/bochum, commute-times, boris-current, flood-risk, boris-trend}`
- `POST /api/enrichment/save-listing` and `SaveListingRequest`
- `GET /api/enrichment/{noise-map, flood-map}` (screenshot generators; the listing worker does not call them; the `noise_map_image`/`flood_map_image` DB columns stay)
- the `listings` query in `analyze_page`

`POST /api/listings/{id}/enrich`, the address flow, and the AI routes in `routes/enrichment.py` are unchanged. The `SERVICE_TIER` comment stating that the raw analyze endpoints are deliberately ungated is rewritten to describe the new gate + override.

## 4. Section catalogue

`data` shapes below are the contract. Distances are metres, money is EUR, `null` means unknown.

| key | tier | timeout | `data` |
|---|---|---|---|
| `boris` | parcel | 25 s | `{bodenrichtwert: number, date: str\|null, zone: str\|null, grundstueckswert: number\|null, raw: {}}` — `grundstueckswert = bodenrichtwert × plot_size_m2` when a plot size is known |
| `boris_trend` | parcel | 30 s | `{current_year, current_value, oldest_year, oldest_value, avg_yearly_change, total_change, history: [{year, value, change_percent}]}`; no trend → `None` |
| `flood` | parcel | 15 s | `{flood_zone: str\|null, flood_risk_level: "low"\|"medium"\|"high", hits: {HQhaeufig: {hit, min_distance_m}, HQ100: {...}, HQextrem: {...}}}` — names match the `enrichments` columns |
| `gfnp` | parcel | 30 s | `{found: bool, designation: str\|null, city: str\|null, date: str\|null}`; service `ok: false` → raise (→ `error`) |
| `planning_essen` | parcel | 30 s | `{found: bool, items: [{category, name, link}]}` — the six typed lists (`bplan`, `vhbplan`, `veraenderungssperre`, `aufstellungsbeschluss`, `auslegungsbeschluss`, `aufhebungsbeschluss`) flattened; `category` is the German label of the list, `name` is `"{nr} {name}"` (plus `plan_type`/`status` when present), `link` from the item's `link` or `null` |
| `planning_bochum` | parcel | 30 s | **identical shape**; `category = plan_type or "B-Plan"`, `name = official_name (+ legal_status)`, `link = plan_link or metadata_link or null` |
| `amenities` | area | 25 s | `{public_transport_score, walkability_score, distances: {public_transport, school, kindergarten, supermarket, doctor}, nearest: {school: {name, distance_m}, kindergarten: …, supermarket: …, doctor: …}}` — `distances.*` from `distance_to_*_m`; `nearest.*` from the first element of each list, `null` when absent |
| `air_quality` | area | 20 s | `{rating: str, rating_color: str, station: {name, distance_km}\|null, measurements: {COMP: {value, unit, who_limit, period?}}}` (the UBA service has no single AQI — the card lists the per-pollutant measurements against WHO limits); a service `error` with no `station` (e.g. "Keine Messstation in der Nähe gefunden") → `Empty(message)`; an `error` alongside a found station → data with `rating: "unbekannt"` |
| `btw` | area | 30 s | `{election, wahlkreis: {nr, name}, parties: [{party, percent, color}]}` — `top_parties` renamed here, once |
| `commute` | area | 30 s | `{destinations: [{name, address, time_minutes, distance_km}]}`; no configured destinations → `None` with message "Keine Zieladressen konfiguriert" (fetch signals this by raising a dedicated `Empty(message)` exception that `run_section` maps to `status: empty`) |
| `noise` | area | 20 s | see §4.2 |

Card order on the page = table order, except `noise` is placed after `flood`.

### 4.2 Noise section (`backend/noise_service.py`, new)

Probed live 2026-09-04 against `https://www.wms.nrw.de/umwelt/laerm` (Umgebungslärmkartierung 2022):

- All eleven layers are `queryable="1"`; `GetFeatureInfo` supports `text/plain`.
- Two requests per point: `LAYERS=QUERY_LAYERS=STR_DEN,SCB_DEN,SCS_DEN,IND_DEN,FLG_DEN` and the `_NGT` set. WMS 1.3.0, `CRS=EPSG:4326`, `BBOX=lat-d,lon-d,lat+d,lon+d` with `d = 0.0002`, `WIDTH=HEIGHT=101`, `I=J=50`, `FEATURE_COUNT=5`.
- Response is one line per layer:
  `@str_isof_denClassify.Pixel Value;Classify.Class value;65113000;3;` or `@str_isof_denClassify.Pixel Value;NoData;`
- `db_min = pixel_value // 1_000_000` (55/60/65/70/75 for L<sub>DEN</sub>, 50/55/60/65/70 for L<sub>night</sub>, verified against the legend graphics and an A40 transect). `NoData` = below the mapping threshold (< 55 dB L<sub>DEN</sub> / < 50 dB L<sub>night</sub>).

```json
{"day":   {"db_min": 65, "label": "ab 65 bis 69 dB(A)", "source": "str"} | null,
 "night": {"db_min": 55, "label": "ab 55 bis 59 dB(A)", "source": "str"} | null,
 "sources": {"str": {"day": 65, "night": 55}, "scb": {"day": null, "night": null},
             "scs": {...}, "ind": {...}, "flg": {...}},
 "below_threshold": false}
```

`day`/`night` are the loudest source at the point. Labels: `"ab {n} bis {n+4} dB(A)"`, top band `"ab 75 dB(A)"` / `"ab 70 dB(A)"`. Source labels for the UI: `str` Straße, `scb` Schiene (Bund), `scs` Schiene (Stadt), `ind` Industrie, `flg` Flughafen. `below_threshold` is true when every layer is `NoData` in both periods — rendered as "unter der Kartierungsschwelle (< 55 dB Tag / < 50 dB Nacht)", which is the good-news case. A malformed or non-200 response raises (→ `error` envelope).

## 5. Frontend

### 5.1 Component `frontend/static/js/analysis.js` (replaces `enrichment.js`)

`base.html` currently loads `enrichment.js` on every page; only analyze uses it. `analysis.js` is loaded by `analyze.html` only.

```js
window.analysisPage = (config) => ({ ... })
// config = {address, plot_size_m2, living_space_m2, listing_id, sections: manifest, auto_run}
```

Injected as `x-data="analysisPage({{ page_config|tojson }})"` — `None` → `null`, strings escaped; bug #5 cannot recur.

State: `address`, `geocode` (geocode response | null), `sections` (`key → envelope | {status:"loading"} | null`), `running`, `error`, `map`, `marker`, `wmsLayers`.

- `init()` — `initMap()` once (container is always mounted, §5.2); if `config.auto_run && address` → `run()`.
- `run()` — reset `geocode`, `error`, every `sections[key] = null`, destroy charts; `GET /api/analysis/geocode`; on 422 set `error` and stop; else store `geocode`, `placePin()`, then `Promise.allSettled(keys.map(k => this.load(k)))`.
- `load(key, {force=false})` — `sections[key] = {status:"loading"}`; fetch the section with `AbortController` at `(timeout_s + 5) s`, passing `lat, lon, precision, plot_size_m2, force`; store the envelope; a network/abort failure stores a local `{key, status:"error", message}` envelope of the same shape. If `key` is `btw` or `boris_trend` and status is `ok`, render the chart in `$nextTick` (destroying the previous instance).
- `loadGated()` — `load(key, {force:true})` for every section whose status is `gated`.
- Derived: `progress` = settled / total; `gatedCount`.

### 5.2 Map

`#result-map` moves out of the results block and is always mounted directly under the input card; `initMap()` runs once from `init()` at the Ruhrgebiet default (`MapUtils.createMap` + `addWMSLayers`). `placePin()` is a plain call from `run()`: `setView([lat, lon], 16)`, create-or-move `L.marker`, popup with `formatted_address`, `invalidateSize()`. No `$watch`, no polling. WMS toggle buttons stay as today. `map-utils.js` and `charts.js` are unchanged (the BTW renderer already takes `[{party, percent, color}]`).

### 5.3 Template

`analyze.html` becomes layout + one generic card frame per manifest entry:

- header: icon, title, tier badge (🏠 Parzelle / 🌐 Umgebung), `took_ms` when ok;
- body switched on `status`: `loading` skeleton · `gated` 🔒 + message + "Trotzdem laden" · `empty` message · `error` message + "Erneut laden" · `ok` → `{% include "analysis/_" ~ key ~ ".html" %}`.

The `ok` bodies live in `frontend/templates/analysis/_<key>.html` (one per section; `planning_essen` and `planning_bochum` share `_planning.html`). The geocode card shows coordinates, `formatted_address`, and a precision badge (🟢 hausnummerngenau · 🟡 straßengenau · ⚪ ortsgenau · 📍 Koordinaten) plus an "Alle gesperrten laden (n)" button when `gatedCount > 0`. The status-line list is removed; each card shows its own state.

### 5.4 Route `analyze_page`

Builds `page_config` from the optional listing (`address_manual or address`, `plot_size_m2`, `living_space_m2`, `id`, `auto_run = listing is not None`) plus `manifest()`. The `listings` query is deleted.

## 6. Testing

- **`tests/test_analysis_sections.py`** — registry: every key exists in `SERVICE_TIER`, `timeout_s > 0`, keys unique, manifest shape. Envelope: parcel without precision → `gated`; `force` and `precision="coordinates"` bypass; area never gated; `fetch` raising → `error` (never propagates); `fetch` sleeping past `timeout_s` → `error` with timeout message; `None` → `empty`; `Empty(msg)` → `empty` with message; `inf`/`nan`/numpy in data → sanitized. Normalizers: one test per section with the service monkeypatched to return a fixture captured from today's live payloads (real `top_parties` and flood/planning shapes), asserting the exact `data` keys of §4.
- **`tests/test_noise_service.py`** — parses the real `text/plain` bodies captured in the probe: band values and labels, loudest-source selection per period, all-`NoData` → `below_threshold`, malformed body raises. HTTP is stubbed.
- **`tests/test_analysis_routes.py`** — TestClient: geocode route with the geocoder monkeypatched (hit, 422 on failure, coordinate input → `precision="coordinates"`); section route returns an envelope and 404 on unknown key; `/analyze?listing_id=` for a seeded listing with `NULL` `plot_size_m2` renders `null` in `page_config` and never the string `None`.
- **`tests/test_flood_service_finite.py`** (or added to an existing flood test) — `_hit_for_scenario` with no polygons yields `min_distance_m is None`, and `flood_risk()` is JSON-serializable.
- **`scripts/smoke_analyze.py`** — manual live smoke (not collected by pytest, like `scripts/test_ml_spam.py`): headless Playwright runs one analysis against the running service and asserts the BTW card is visible, the map center equals the geocode within 1e-3° with a marker present, and the flood + noise cards rendered.

## 7. Documentation

CLAUDE.md gains an **Analysis** paragraph (package, envelope, gate, noise service); HANDOVER.md gets a work-log entry listing the nine root causes and the removed routes.
