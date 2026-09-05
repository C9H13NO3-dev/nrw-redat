# NRW-REDAT — Real Estate Data Aggregation Tool: design

**Date:** 2026-09-05 · **Status:** draft for review · **Origin:** extraction of house-hunter's `/analyze` stack

> This spec lives in house-hunter because the target repository does not exist yet.
> It is copied verbatim to `docs/DESIGN.md` in `nrw-redat` on the first commit there.

## 1. Goal

Turn the `/analyze` location-analysis stack (20 data-source cards + PDF report) into a
**standalone product**: its own repository, its own website, its own Docker
deployment, its own (smaller) test suite — and an HTTP API so house-hunter (and
anything else) can consume it. After the cutover house-hunter deletes its copy of the
stack and becomes a client.

Name: **NRW-REDAT** (package `redat`, HTTP `User-Agent: nrw-redat/1.0`). The "NRW"
is honest: every source is North-Rhine-Westphalian or Essen/Bochum-specific.

### Non-goals

- No listings, scraping, scoring, ML, dossiers, favourites — nothing that knows what a
  "house for sale" is. REDAT answers *"what do the public data sources say about this
  point?"*, nothing more.
- No user accounts. Access control is a single optional API key (§7).
- No new data sources or card changes in this project. Behaviour of every card is
  frozen at house-hunter `main` as of the cutover commit; the two specs
  `2026-09-04-analyze-*-design.md` and `2026-09-04-analysis-pdf-report-design.md`
  remain the card-level reference and move with the code.
- No coverage expansion beyond Essen/Bochum for the cropped grids (Zensus, EEA).

## 2. Decisions taken (2026-09-05)

| Topic | Decision |
|---|---|
| Location | Source checkout at `/srv/nrw-redat`, Gitea repo `jarvis/nrw-redat`, `docker compose` run from the checkout. Port **8200**. |
| house-hunter integration | **Replace.** Hunter links to the REDAT website and calls the REDAT API for the dossier PDF; its own analysis code, templates, JS and ~400 tests are deleted. |
| Access | LAN-open. If `REDAT_API_KEY` is set, `/api/*` requires `X-Api-Key`; the website never does. |
| Website | Analyzer + shareable result permalinks (`/a/{id}`, results stored server-side, PDF re-downloadable) + `/docs` (OpenAPI) + `/quellen` (data sources & licences). |
| Commute / ÖPNV destinations | REDAT owns a default list in `config/settings.yaml`; API callers may pass their own `destinations`. Hunter passes its `IMPORTANT_LOCATIONS`. |
| Duplicated code | REDAT gets its **own copies** of `boris_service`, `flood_service`, `geoapify_service`; hunter keeps its copies for the listing-enrichment pipeline (`enrichment_service`). Autonomy beats DRY across repos. |

## 3. Architecture

```
 browser ──► redat.web   (Jinja pages: /, /a/{id}, /quellen)          ┐
                                                                       │ one FastAPI app
 hunter  ──► redat.api   (/api/v1/…, JSON + PDF)                      ┘  (uvicorn, :8200)
                 │
                 ▼
          redat.core      sections registry · envelope runner · tiers/gating · geocoding
                 │
                 ▼
          redat.sources   one module per external source (unchanged service code)
                 │
                 ▼
          redat.report    builder · Jinja render · Playwright PDF · noise maps · SVG
                 │
          redat.store     SQLite `runs` table (permalinks) + in-process TTL cache
```

Everything below `redat.web`/`redat.api` is the existing house-hunter code, moved.
The four coupling points to house-hunter are cut as follows:

| Today (house-hunter) | REDAT |
|---|---|
| `enrichment_service.SERVICE_TIER`, `enrichment_allowed()` | `redat/core/tiers.py` (the dict + the function, verbatim) |
| `EnrichmentService.geocode()` / `.get_boris_nrw()` | `redat/core/geocoding.py` owns Geoapify → Nominatim geocoding; `redat/sources/boris.py` = hunter's `boris_service.py` (geopandas over the local BRW shapefiles, see §4 "Source data") plus `get_boris_nrw()`'s subprocess-with-timeout wrapper moved out of the class as a plain function |
| `config.IMPORTANT_LOCATIONS` (commute, ÖPNV) | `Ctx.destinations` (request-scoped, §5.2) with the default from `settings.yaml` |
| `routes/analysis.py` → `database`, `dossier` (listing lookup, PDF filing) | dropped — REDAT returns bytes; the caller files them |
| `report/render.py` → `app_config.templates` | REDAT's own Jinja environment |

## 4. Repository layout

```
nrw-redat/
├── redat/
│   ├── __init__.py            __version__
│   ├── app.py                 FastAPI factory, mounts web + api, static files, lifespan (store init)
│   ├── settings.py            env + settings.yaml → Settings dataclass (§7)
│   ├── core/
│   │   ├── sections.py        Section registry (moved from backend/analysis/sections.py)
│   │   ├── envelope.py        run_section(), sanitize()
│   │   ├── tiers.py           SERVICE_TIER, enrichment_allowed()
│   │   └── geocoding.py       geocode_with_precision(), parse_coordinates()
│   ├── sources/               airquality{,_grid,_live}.py bergbau.py boris.py breitband.py btw.py
│   │                          denkmal.py energie.py flood.py geoapify.py gfnp.py infrastruktur.py
│   │                          noise.py oepnv.py planning_essen.py planning_bochum.py
│   │                          schutzgebiete.py starkregen.py zensus.py
│   ├── report/                builder.py render.py pdf.py noise_map.py svg.py
│   ├── store/
│   │   ├── runs.py            SQLite: save_run(), get_run(), list_recent()
│   │   └── cache.py           TTL cache for section results
│   ├── api/v1.py              /api/v1/* routes
│   ├── web/pages.py           /, /a/{id}, /quellen
│   ├── data/                  eea_aq_grid_2023.json · zensus_2022_grid.json.gz · certs/lencr_ye_chain.pem
│   ├── templates/             base.html · index.html · run.html · quellen.html
│   │   ├── analysis/_*.html   card partials (moved)
│   │   └── report/            report.html + _*.html (moved)
│   └── static/                analysis.js · map-utils.js · charts.js · redat.css (built Tailwind)
├── config/settings.yaml       default destinations, cache TTL, timeouts (committed defaults)
├── scripts/                   build_zensus_grid.py · build_eea_aq_grid.py · smoke_analyze.py
├── tests/                     §9
├── docs/                      DESIGN.md (this) · the three 2026-09-04 card specs · SOURCES.md
├── Dockerfile · docker-compose.yml · .env.example
├── requirements.txt · requirements-dev.txt · pyproject.toml (pytest config)
├── tailwind.config.js · tailwind.input.css
└── README.md · HANDOVER.md · CLAUDE.md
```

Module renames drop the `_service` suffix (`noise_service.py` → `sources/noise.py`);
public function names inside are unchanged so the section `fetch` bodies move with a
one-line import edit each. The `_fetch_*`/`_get_png` test seams stay exactly where they are.

**Source data (not committed).** `redat/data/` holds only the small derived grids
(EEA 1 km, Zensus 100 m, ~15 MB). Three sources read large local geodata with
geopandas — hunter's `data/` is 9.6 GB and git-ignored for the same reason:

| Source | Files | Size (without the `.zip` archives) |
|---|---|---|
| `sources/boris.py` | `boris/BRW_{2011..2025}/BRW_{year}_Polygon.shp` (+ `.dbf/.shx/.prj/.cpg`) | 5.3 GB |
| `sources/flood.py` | `flood/hwrm/HQhaeufig.gpkg`, `HQ100.gpkg`, `HQextrem.gpkg` (the shapefile fallback dirs are not copied) | 0.9 GB |
| `sources/btw.py` | `elections/btw25/wahlkreise_shp_geo/…/Wahlkreise_WGS84.shp`; `kerg2.csv` is downloaded on first use | 8 MB |

They live under `{REDAT_DATA_DIR}/source/` (§7) — on the host `/srv/nrw-redat/data/source/`,
one-time `rsync` from `/srv/house-hunter/data/` (§12 step 1), inside the container via
the single `./data:/data` volume. Each of the three modules resolves its paths from
`settings.source_dir` at call time (no import-time `Path(__file__)` constants) and, when
the directory is missing, raises a `RuntimeError("BORIS-Daten fehlen unter …")`-style
error so the card reads `error` with a precise message instead of a traceback. Hunter
keeps its own copy — `flood`/`boris` still serve its listing enrichment after the cutover.

## 5. API (`/api/v1`)

All JSON. Errors are FastAPI `{detail}` bodies. `X-Api-Key` required on every route
when `REDAT_API_KEY` is set (401 otherwise); never required for `/docs`.

### 5.1 Read

| Route | Purpose | Response |
|---|---|---|
| `GET /api/v1/sections` | manifest for generic clients | `[{key, title, icon, tier, timeout_s, source}]` (display order) |
| `GET /api/v1/geocode?address=` | address or `"lat, lon"` → point | `{address, formatted_address, latitude, longitude, precision}` · 422 when unresolvable |
| `GET /api/v1/section/{key}?lat&lon&precision&plot_size_m2&force&destinations` | one card | the envelope `{key, tier, status, data, message, source, took_ms}` · 404 unknown key |
| `GET /api/v1/analyze?address&plot_size_m2&living_space_m2&force&destinations&save` | everything in one call: geocode, then all sections concurrently (bounded pool of 6 — the same concurrency the browser produces today) | `{run_id?, geocode, sections: {key: envelope}}` · with `save=1` the run is stored and `run_id` + `permalink` returned |
| `POST /api/v1/runs` | store a run the client already holds (the browser's path; body = `{address, geocode, plot_size_m2, living_space_m2, sections}`, validated like the report payload) | `{run_id, permalink}` · 422 on payload errors |
| `GET /api/v1/run/{id}` | a stored run | same shape as `/analyze` plus `created_at`, `address`, `plot_size_m2`, `living_space_m2` · 404 |

`destinations` is a JSON-encoded list `[{name, lat, lon, group}]` (query param; ≤ 10
entries, validated); when absent, `settings.yaml` defaults apply. It feeds the
`commute` and `oepnv` cards only.

### 5.2 Report

| Route | Purpose |
|---|---|
| `POST /api/v1/report` | body exactly as today (`{address, geocode, plot_size_m2, living_space_m2, sections}`) → `application/pdf`, `Content-Disposition: attachment; filename="Standortanalyse_<slug>_<date>.pdf"`. The browser uses this (renders what is on screen, force-loaded cards included). 422 on payload errors, 503 `RendererUnavailable`. `listing_id`, dossier filing and the `X-Dossier-*`/`X-Report-Warning` headers are **gone**. |
| `GET /api/v1/report?address&plot_size_m2&living_space_m2&force=1&destinations` | server-side convenience for machine callers (hunter's dossier button): geocode → all sections (`force=1` default here so the PDF is complete) → PDF. Same response headers. |
| `GET /api/v1/run/{id}/report.pdf` | re-render a stored run's PDF from its stored envelopes (~3 s; nothing re-fetched) |

### 5.3 Ops

`GET /healthz` → `{status: "ok", version, chromium: true|false, sources_loaded: n}`
(never behind the API key; `chromium` is the result of a cached Playwright launch probe
at startup).

## 6. Website

Server-rendered Jinja + Alpine, same visual language as today (Tailwind, Leaflet map,
Chart.js) but REDAT's own `base.html`: header with name + nav (Analyse · Quellen ·
API), no sidebar, no house-hunter store. `analysis.js` is adapted to the `/api/v1`
paths; after a run settles the page calls `POST /api/v1/runs` with the envelopes it
holds (same body shape as the report POST) and receives `{run_id, permalink}`; the URL
bar is updated via `history.replaceState` to `/a/{id}`.

| Page | Content |
|---|---|
| `/` | the analyzer: address input (Geoapify autocomplete, own key), optional Grundstück/Wohnfläche m², "Analysieren", map with WMS overlay toggles (the `wmsLayerConfigs` bits of hunter's `app.js` are inlined into a small REDAT Alpine store), one generic card frame per manifest entry (partials unchanged), "Alle gesperrten laden", "📄 PDF-Bericht". `?address=…&plot_size_m2=…&living_space_m2=…&auto=1` pre-fills and auto-runs — this is the link hunter uses. |
| `/a/{id}` | a stored run: same card layout rendered from the stored envelopes (no live fetch), a banner "Analyse vom dd.mm.yyyy hh:mm — [neu laden]" (re-runs into a *new* id), the PDF button hits `/api/v1/run/{id}/report.pdf`. This is the shareable link. |
| `/quellen` | one row per source: name, publisher, licence, endpoint, tier, refresh cadence (Zensus 2022, EEA 2023, Breitband 12.2025 …). Generated from a `SOURCES` list in `docs/SOURCES.md`-adjacent Python (`redat/core/sources_meta.py`) so the page and the report footer cannot drift. |
| `/docs` | FastAPI's OpenAPI UI, with `redat.__version__` and a one-paragraph description. |

## 7. Configuration

Precedence: environment > `config/settings.yaml` > code defaults.

| Env | Meaning | Default |
|---|---|---|
| `GEOAPIFY_API_KEY` | the only external key the stack needs (geocoding, autocomplete, amenities, commute) | required — startup fails loudly without it |
| `REDAT_API_KEY` | if set, `/api/*` requires `X-Api-Key` | unset |
| `REDAT_DATA_DIR` | mutable + bulky state: SQLite `redat.db` at its root, local geodata under `source/{boris,flood,elections}` (§4) | `/data` in the container, `./data` locally |
| `REDAT_CACHE_TTL_S` | section cache TTL | `21600` (6 h) |
| `REDAT_PUBLIC_URL` | base for permalinks in API responses | `http://192.168.188.64:8200` |
| `REDAT_LOG_LEVEL` | | `INFO` |

`config/settings.yaml` (committed): default `destinations` (Essen Hbf, Bochum Hbf,
Düsseldorf Hbf — coordinates, no personal places), the per-section `timeout_s`
overrides if ever needed, the fixed Hbf stop ids for ÖPNV.

## 8. Persistence & caching

**Runs** (`store/runs.py`, SQLite, WAL): `runs(id TEXT PK, created_at, address,
formatted_address, latitude, longitude, precision, plot_size_m2, living_space_m2,
sections_json)`. `id` = 10-char base32 of `secrets.token_bytes(6)` — unguessable
enough for a LAN permalink. No PDF blobs stored; PDFs re-render from `sections_json`.
No retention policy (a run is ~50–150 KB; thousands fit comfortably). The DB is the
only mutable state → one Docker volume.

**Section cache** (`store/cache.py`): in-process `dict[(key, lat_r, lon_r, plot, force)] → (expires, envelope)`
with `lat/lon` rounded to 4 decimals (≈ 10 m), guarded by a lock, TTL from settings,
only `status == "ok" | "empty"` envelopes cached (errors and gated results are not).
`/api/v1/section` and `/analyze` consult it; the envelope carries `cached: true` when
served from it and `took_ms` of the original fetch. Cleared on restart — intentional.

## 9. Tests (the "smaller suite")

Move the 27 analyze-related test files (400 tests today), then prune to intent:

- **Keep as-is:** every source parser test on captured fixtures (`test_noise`,
  `test_starkregen`, `test_bergbau`, `test_denkmal`, `test_oepnv`, `test_energie`,
  `test_schutzgebiete`, `test_breitband`, `test_infrastruktur`, `test_airquality_*`,
  `test_zensus_grid`, `test_geocoding`) — they are what catches an upstream format change.
- **Collapse:** the 43 render tests → one parametrized test over `(partial × {fixture, {}})`;
  `test_report_route` shrinks (no dossier/listing cases); `test_analysis_routes` is
  rewritten for `/api/v1` and gains API-key, `/analyze`, `/runs`, `/run/{id}` cases.
- **Add:** `test_store_runs.py`, `test_cache.py`, `test_settings.py` (precedence,
  missing Geoapify key fails), `test_web_pages.py` (`/`, `/a/{id}`, `/quellen`, 404).

Target ≈ 250 tests, < 20 s, fully hermetic (tmp SQLite, every HTTP seam stubbed).
`scripts/smoke_analyze.py` stays the manual live check (Playwright against a running
instance). No CI runner (Gitea, same as hunter) — the Dockerfile runs `pytest` in a
build stage so an image cannot be built from a red tree.

## 10. Docker

```dockerfile
FROM mcr.microsoft.com/playwright/python:v1.5x-noble AS base   # matching the pinned playwright version; Chromium included
WORKDIR /app
COPY requirements.txt . && RUN pip install --no-cache-dir -r requirements.txt
COPY . .
FROM base AS test
RUN pip install -r requirements-dev.txt && pytest -q
FROM base AS runtime
ENV REDAT_DATA_DIR=/data
EXPOSE 8200
HEALTHCHECK CMD curl -sf http://localhost:8200/healthz || exit 1
CMD ["uvicorn", "redat.app:app", "--host", "0.0.0.0", "--port", "8200"]
```

`docker-compose.yml`: one service `redat`, `build: .` (target `runtime`), `ports: 8200:8200`,
`env_file: .env`, volume `./data:/data` (DB + `source/` geodata), `restart: unless-stopped`,
`mem_limit: 2g` (Chromium plus a geopandas bbox read of a 400 MB shapefile in the BORIS
subprocess). `requirements.txt`: fastapi, uvicorn, jinja2, httpx, Pillow, pyproj, shapely,
geopandas (pulls numpy/pandas/pyogrio — needed by boris/flood/btw, wheels only, no GDAL
build), playwright, pyyaml — no scikit-learn/scrapling/openai. `sanitize()` keeps its
numpy branch and it is now actually taken for geopandas results.

Deploy runbook: `git clone` to `/srv/nrw-redat`, `cp .env.example .env` + key,
`docker compose up -d --build`; update = `git pull && docker compose up -d --build`.
The `test` stage failing aborts the build — that is the deploy gate.

## 11. house-hunter side (cutover)

In hunter, on a branch `feat/redat-client`, after REDAT is live:

1. `config.py`: `REDAT_URL` (default `http://192.168.188.64:8200`), `REDAT_API_KEY` (optional, from `.env`).
2. `detail.html`'s "Analyse" link → `{REDAT_URL}/?address=…&plot_size_m2=…&living_space_m2=…&auto=1`
   (`target="_blank"`); nav entries for `/analyze` in `base.html` become that external link.
3. Dossier (`decide.html`): new "📄 Standortbericht erzeugen" button → `POST /api/listings/{id}/redat-report`
   (new hunter route in `routes/decision.py`): calls REDAT `GET /api/v1/report?address&plot_size_m2&living_space_m2&destinations=<IMPORTANT_LOCATIONS>`,
   files the bytes with `dossier.save_upload(..., kind="report")`, returns the document id;
   REDAT unreachable → 502 with a clear message. `tests/test_redat_client.py` stubs the HTTP call.
4. Delete: `backend/analysis/`, `backend/report/`, `backend/routes/analysis.py`,
   `routes/html.analyze_page`, the 17 analyze-only services (§2 table: `boris`, `flood`,
   `geoapify`, `enrichment_service`, `geocoding` **stay** — `routes/enrichment.py` and the
   listing pipeline use them), `frontend/templates/analyze.html`, `analysis/`, `report/`,
   `static/js/analysis.js`, `charts.js` (no other template loads it — verified 2026-09-05),
   `zensus_2022_grid.json.gz`, `eea_aq_grid_2023.json`, `certs/`, the 27 test files,
   `scripts/smoke_analyze.py`, `build_zensus_grid.py`, `build_eea_aq_grid.py`;
   `requirements.txt` loses `pyproj` and `shapely` (verified: only the analyze stack imports them) but **keeps `playwright`** — `archiver.py` uses it for the browser fetch fallback.
5. Tailwind rebuild, CLAUDE.md (replace the four analysis paragraphs with one "REDAT client" paragraph), HANDOVER entry, ~650 tests green, merge, restart, push.

The three `2026-09-04-analyze-*` specs and the PDF spec move to REDAT's `docs/` and are
deleted from hunter in the same commit.

## 12. Migration plan (order of work)

1. **Repo bootstrap** — create `jarvis/nrw-redat` on Gitea, skeleton (§4), settings, app
   factory, `/healthz`, Dockerfile, compose, README. First image builds and answers `/healthz`.
   One-time data copy: `rsync -a --exclude='*.zip' --exclude='*_Shape/'` of
   `/srv/house-hunter/data/{boris,flood,elections}` → `/srv/nrw-redat/data/source/` (~6.2 GB;
   398 GB free on the volume).
2. **Move core + sources** — `git mv`-equivalent copy of the modules with import edits;
   `tiers.py`, `geocoding.py`, `sources/boris.py` extracted from `enrichment_service`;
   the moved parser tests pass unchanged apart from imports.
3. **API v1** — sections, geocode, section, analyze, report (POST + GET), runs, run,
   API-key dependency. Route tests.
4. **Store** — runs table, cache, `/a/{id}`, `run/{id}/report.pdf`.
5. **Website** — base, index, run page, quellen, docs description; Tailwind build;
   `analysis.js` on `/api/v1`; smoke script.
6. **Live verification** on the host (Werden + Kortumstraße, permalink, PDF, API key on/off),
   `docker compose up -d` on :8200.
7. **house-hunter cutover** (§11) — separate branch, after 6 is stable.
8. **Docs** — REDAT `HANDOVER.md`/`CLAUDE.md`; hunter's updated; `/srv/README.md` gets the
   new service line.

Steps 1–5 are self-contained and land in the new repo; nothing in hunter changes until 7.

## 13. Error handling & operational rules

- A section failure never fails a run: the envelope model is unchanged (`ok|empty|gated|error`).
- `/api/v1/analyze` and `GET /report` return 422 for an unresolvable address, 502 for a
  geocoder outage (Geoapify **and** Nominatim failed), never a 500 for a source failure.
- PDF renderer unavailable → 503 with `{detail: "PDF-Renderer nicht verfügbar"}`; `/healthz.chromium=false`.
- Every outbound call carries `User-Agent: nrw-redat/1.0 (+{REDAT_PUBLIC_URL})` — Overpass
  and basemap.de require one; the per-source timeouts and retry rules documented in the
  card specs are unchanged.
- Logging: one structured line per section run (`key lat lon status took_ms cached`), one
  per report; uvicorn access log on.

## 14. Risks

| Risk | Mitigation |
|---|---|
| Upstream endpoints rate-limit a second consumer | section cache (§8); hunter's own pipeline no longer hits these sources at all after the cutover, so total load drops |
| Chromium + geopandas in a 2 GB container | Playwright's own image; `mem_limit` sized for one render at a time — `html_to_pdf` already serialises via a single-worker thread; BORIS reads are bbox-filtered and run in a 12 s-capped subprocess |
| 6 GB of source geodata is a second copy on the same host | one-time rsync, read-only in practice (BRW gets a new year folder once a year; both copies are updated by hand) — documented in REDAT's HANDOVER as the only non-git deploy asset |
| Two copies of `boris`/`flood`/`geoapify` drift | accepted; hunter's copies serve the listing pipeline only and rarely change. Noted in both HANDOVERs. |
| Permalinks leak addresses on the LAN | ids are unguessable; the site is LAN-only by decision. Revisit if it is ever reverse-proxied to the internet (then `REDAT_API_KEY` mandatory + basic auth on the proxy). |
| Cutover deletes something hunter still uses | §11 step 4 is grep-gated per module; the `tests/` run is the safety net |

## 15. Out of scope, noted for later

Multi-city grids beyond Essen/Bochum; run retention/cleanup; comparing two runs side by
side; a JSON export of the report; auth beyond one key; scheduled re-analysis.
