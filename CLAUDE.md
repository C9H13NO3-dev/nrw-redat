# CLAUDE.md

Guidance for Claude Code (claude.ai/code) working in this repository.

> **Start here for current status:** [`HANDOVER.md`](HANDOVER.md) is the living source of truth for
> project state, the deploy runbook, and the work log. Read it before starting work.

## Commands

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/python -m pytest -q                     # 805 tests, hermetic, ~10s
GEOAPIFY_API_KEY=… .venv/bin/uvicorn redat.app:app --port 8200 --reload
docker compose up -d --build                      # build gate: the test stage runs `pytest -q` and aborts the image on a red suite
npx tailwindcss@3 -c tailwind.config.js -i tailwind.input.css -o redat/static/redat.css --minify
```

## Architecture

Package `redat`. Config precedence (`redat/settings.py`): env > `config/settings.yaml` > code defaults;
`Destination`/`get_settings()` live here. `redat/sources/` wraps each external geodata source (BORIS,
flood, Lärm, Zensus, Denkmal, ÖPNV, …), one module per source. `redat/core/sections.py` declares the
29-card `SECTIONS` registry (`Section(key, title, icon, tier, timeout_s, source, fetch)`); `core/envelope.py`'s
`run_section()` runs one card under its timeout and returns the fixed `{key, tier, status, data, message,
source, took_ms}` envelope, gating parcel-tier cards unless precision is house-number/coordinates/`force`;
`core/analyze.py` orchestrates geocode + all cards concurrently and the payload shapes shared by the API
and the website; its `cached_section()` helper is the single place that consults `SectionCache`, used by
both `run_all()` (`/analyze`) and `api_section` (`/section/{key}`). `redat/api/v1.py` is the versioned
JSON+PDF API (`/api/v1/*`, optional `X-Api-Key` via `api/auth.py`); `redat/web/pages.py` serves `/`,
`/a/{id}`, `/quellen`. `redat/store/` is SQLite: `runs.py` (persisted analyses, base32 ids) and `cache.py`
(`SectionCache`: persistent, bounded, per-card TTL, plus KV namespaces for geocode/autocomplete; built by
`core.analyze.build_cache()`). `redat/report/` builds and renders the PDF (Jinja2 → Playwright Chromium).
Per-source implementation notes (legend RGB tables, BBOX CRS traps, calibrated thresholds, the
"never say X on the parcel" rules, etc.) are documented card-by-card in the five specs copied into
`docs/2026-09-04-*.md` (originally written for house-hunter's `/analyze`; ported here verbatim as the
per-source reference — diff a moved module against its house-hunter original before trusting a spec
detail has drifted).

## Rules

- Every outbound HTTP call passes `headers=headers()` from `redat/http.py` (identifies the service by User-Agent) — never a bare `httpx.get(...)`.
- Never `verify=False`; a host needing a non-standard chain ships its cert under `redat/data/certs/` (see `backend/breitband_service` pattern carried over from house-hunter).
- All UI copy (website + PDF report) is German.
- Website partials (`redat/templates/analysis/_*.html`) keep the store name `app` — an intentional carry-over from the house-hunter partials' Alpine store contract; do not rename it.
- Access rules (spec §3): public = `/login`, `/logout`, `/invite/*`, `/healthz`, `/static/*`, `GET /a/{id}`, `GET /api/v1/run/{id}`, `GET /api/v1/run/{id}/report.pdf`, `GET /quellen`; everything else needs a principal (session cookie or `X-Api-Key`); `/admin*` needs an admin session.
- Gated tests log in with `tests/helpers_auth.login` (creates the user + session directly, no HTTP round-trip through `/login`).
- Every HTML form needs the CSRF double-submit (`redat/auth/csrf.py`'s `ensure_csrf`/`check_csrf`, cookie `redat_csrf`); JSON API mutations carry no token and instead rely on `SameSite=Lax` plus the `Content-Type: application/json` requirement (a cross-site form can't send either).
- `page_principal` (and `page_admin`) gate website pages — redirect to `/login?next=…` (303); `require_principal` (and `require_admin`) gate the API — `401`/`403` JSON.
- `data_dir()` (in each `sources/*.py` module) is always a function, never a module-level constant — it must re-read `REDAT_DATA_DIR` per call so tests can monkeypatch it.
- New static data lives in `redat/data/` and is committed: seven statewide grids in total (three of them NumPy `.npz`) — `zensus_2022_nrw.npz`, `eea_aq_grid_2023_nrw.json.gz`, `schulen_nrw.json.gz`, `unfallatlas_2020_2025_nrw.npz`, `bergbauberechtigungen_nrw.geojson.gz`, `ladesaeulen_nrw.json.gz`, `egms_vertical_velocity_nrw.npz` — see README "Static grids in the repo" for the build script and refresh cadence per file.
- Cache contract (README "Cache semantics"): `ok`/`empty` envelopes only, key `(key, lat₄, lon₄, plot, force, cache_version)`, TTL per card (`cache_ttls` yaml › `Section.cache_ttl_s` › `cache_ttl_s` 30 d), `error`/`gated` never cached, `destinations` suppresses caching for `commute`/`oepnv` only, `?fresh=1` is the cache bypass (`force` is the parcel-gate override, not a cache flag). Bump `Section.cache_version` when a card's `data` shape or meaning changes. An `ok` envelope whose `data` carries a truthy top-level `*_error` value is never cached either, so a permanent gate/hint must not use the `_error` suffix (see `bodenbewegung_hinweis`, not `bodenbewegung_error`).
- WFS/WMS quirks that cost a day each: the ALKIS WFS proxy accepts only `TYPENAMES` + `BBOX` in EPSG:25832 and returns GML (no JSON/CQL/SRSNAME); LINFOS wants an EPSG:25832 bbox; the BfS WFS wants `bbox` in lon,lat; wms.nrw.de GetFeatureInfo uses lat,lon (WMS 1.3.0) — reuse `redat/sources/esri_wms.py`.
- WCS `wcs_nw_dgm` returns float32 GeoTIFF (row 0 = north); the RVR umon WMS answers GetFeatureInfo without values — use GetMap images.
- Statewide grids: `redat/core/nrw.py` holds the NRW/RVR/Essen/Bochum boxes — never hard-code a window in a build script; the INSPIRE Denkmal WFS only filters with an EPSG:25832 BBOX; `ogc-api.nrw.de` needs the `/v1/` path and `follow_redirects`.
- Klimaanalyse NRW WMS: layers are numbers, GetFeatureInfo `application/geo+json`, rasters answer `Classify.Pixel Value` (`"NoData"` string); the Copernicus HRL WMS only serves EPSG:3857/4326 — request the 2 km window via `climate_maps.bbox_2km_3857`.
