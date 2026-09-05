# NRW-REDAT

**Real Estate Data Aggregation Tool** — a standalone Standortanalyse ("location analysis") service for
Essen/Bochum, built from public NRW/Bund geodata (Bodenrichtwert, Hochwasser, Lärm, Denkmalschutz, ÖPNV,
Luftqualität, Bundestagswahl and more — 20 cards in total). It runs the same analysis engine that used
to live inside the House Hunter project, extracted into its own FastAPI service so it can be used for
any address, not just scraped listings. Given an address it geocodes it, runs every applicable data
source concurrently, and renders the result as a website page, a JSON payload, or a formatted A4 PDF —
each run gets a permanent, shareable permalink.

Surfaces: a website (`/`, permalinks at `/a/{id}`, a source index at `/quellen`), a versioned JSON+PDF
API under `/api/v1` (OpenAPI docs at `/docs`), and `GET /healthz` for monitoring/container health.

## Quick start

```bash
git clone <this repo> nrw-redat && cd nrw-redat
cp .env.example .env            # fill in GEOAPIFY_API_KEY (see below)
docker compose up -d --build    # builds on :8200 — the build stage runs pytest; a red suite aborts the build
curl -s localhost:8200/healthz  # {"status":"ok","version":"1.0.0","chromium":true,"sources_loaded":20,"cache":{"entries":…,"bytes":…,"expired":…}}
```

`.env` (git-ignored, copy from `.env.example`):

| Key | Meaning |
|---|---|
| `GEOAPIFY_API_KEY` | Required — geocoding, autocomplete, amenities, commute. Same key as House Hunter's `.env`. |
| `REDAT_API_KEY` | Optional. When set, every `/api/*` route requires an `X-Api-Key` header. Leave empty for LAN-open (the agreed default) — see "Known limitations" in `HANDOVER.md` for why the website's own cards stop loading if you set this. |
| `REDAT_DATA_DIR` | Where `redat.db` and `source/{boris,flood,elections}` live. `/data` inside the container (bind-mounted from `./data` by `docker-compose.yml`). |
| `REDAT_CACHE_TTL_S` | Default cache TTL in seconds for cards without their own (default 2592000 = 30 d, `config/settings.yaml`). Per-card TTLs: `cache_ttls` in settings.yaml. |
| `REDAT_CACHE_MAX_ENTRIES` / `REDAT_CACHE_MAX_BYTES` | Cache bounds (defaults 100 000 entries / 256 MiB). Expired rows are evicted first, then least recently used. |
| `REDAT_PUBLIC_URL` | Base URL used to build permalinks (e.g. `http://192.168.188.64:8200`). |
| `REDAT_LOG_LEVEL` | Python logging level. |

### Geodata (not in git)

`data/source/` (~11 GB with the derived GeoPackages, ~6.6 GB without) is not tracked in git and not part of
the Docker build context (`.dockerignore` excludes the top-level `data/` bind-mount directory). It is all
public open data and one script fetches and prepares it:

```bash
docker compose build            # once - the GeoPackage builds run inside the app image (geopandas lives there)
scripts/fetch_geodata.sh        # ~3.3 GB from opengeodata.nrw.de + bundeswahlleiterin.de, then builds the .gpkg files (~10 min)
docker compose up -d            # or `docker compose restart redat` if it was already running
```

The script is idempotent (anything present is skipped, interrupted downloads resume), so re-run it after a
failure or when a new BORIS year is published. `--only boris|flood|btw` limits it to one dataset,
`--no-build` skips the GeoPackage step, `--prune` deletes the unpacked shapefiles once their GeoPackages
exist (saves ~6.6 GB), `--data-dir` / `--python` are for non-docker setups (`--help` lists everything).
What it produces under `data/source/`:

| Path | Source | Used by |
|---|---|---|
| `boris/BRW_{2011…2025}/BRW_{year}_Polygon.shp` | [opengeodata.nrw.de …/boris/BRW/](https://www.opengeodata.nrw.de/produkte/infrastruktur_bauen_wohnen/boris/BRW/) `BRW_{year}_EPSG25832_Shape.zip`, dl-de/zero-2-0, 15 × 150–225 MB | `boris`, `boris_trend` (fallback per year) |
| `boris/brw.gpkg` | derived by `scripts/build_boris_gpkg.py`: one R-tree-indexed layer `brw_{year}` per year, chunked, UTF-8-repaired (the 2022–2024 zips carry a few ISO-8859-1 rows) | `boris`, `boris_trend` (preferred: ms instead of a ~2 s file scan per year) |
| `flood/hwrm/{HQ}-Ueberschwemmungsgrenzen_EPSG25832_Shape/*.shp` | [opengeodata.nrw.de …/hochwasser/hwrm/](https://www.opengeodata.nrw.de/produkte/umwelt_klima/wasser/hochwasser/hwrm/) for HQhaeufig / HQ100 / HQextrem, 150–200 MB each | `flood` (fallback) |
| `flood/hwrm/{HQhaeufig,HQ100,HQextrem}.gpkg` | derived by `scripts/build_flood_gpkg.py` | `flood` (preferred) |
| `elections/btw25/wahlkreise_shp_geo/*.shp` | [bundeswahlleiterin.de](https://www.bundeswahlleiterin.de/bundestagswahlen/2025/wahlkreiseinteilung/downloads.html) `btw25_geometrie_wahlkreise_vg250_shp_geo.zip`, 5 MB | `btw` (the Zweitstimmen CSV is fetched live) |

Adding a BORIS year: extend `AVAILABLE_YEARS` in `redat/sources/boris.py` and the `YEARS` line in
`scripts/fetch_geodata.sh`, run the script (only the new year is fetched and appended to `brw.gpkg`), then
`scripts/cache_admin.py purge --section boris` (and `boris_trend`) so cached cards pick it up.

The smaller, still-large `redat/data/` package files (EEA air-quality grid, Zensus 2022 grid, the
letsencrypt intermediate cert for the Breitbandatlas host) **are** committed and shipped in the image —
they are a different directory from the host bind mount.

## API overview (`/api/v1`)

| Method & path | What it does |
|---|---|
| `GET /api/v1/sections` | The card manifest (key, title, icon, tier, timeout, source) — 20 entries. |
| `GET /api/v1/geocode?address=` | Geocode an address → `{address, formatted_address, latitude, longitude, precision}`, 422 if unresolvable. |
| `GET /api/v1/autocomplete?text=&limit=` | Address autocomplete suggestions. |
| `GET /api/v1/section/{key}?lat&lon&precision&plot_size_m2&force&destinations` | Run one card in isolation; 404 for an unknown key. |
| `GET /api/v1/analyze?address=&plot_size_m2&living_space_m2&force&destinations&save` | Geocode + run every card; `save=1` also persists the run and returns `run_id`/`permalink`. |
| `POST /api/v1/runs` | Persist a pre-computed payload (same shape `analyze` returns) as a run; returns `run_id`/`permalink`. |
| `GET /api/v1/run/{run_id}` | Fetch a stored run's full payload; 404 if unknown. |
| `POST /api/v1/report` | Render a PDF from a posted payload (the browser's own "already-fetched" path — nothing is re-fetched server-side). |
| `GET /api/v1/report?address=&plot_size_m2&living_space_m2&destinations` | Convenience machine path: geocode + analyze + PDF in one call. `force` defaults to `1` here (unlike `/analyze`), so a report always reflects live data, not a cached card. |
| `GET /api/v1/run/{run_id}/report.pdf` | Re-render a stored run as a PDF. |

`destinations` is a JSON-encoded list of up to 10 objects, each `{"name":…,"lat":…,"lon":…,"group":…}`
(`group` optional), feeding the `commute` and `oepnv` cards only — anything else 422s. URL-encoded
example:

```
GET /api/v1/analyze?address=…&destinations=%5B%7B%22name%22%3A%22Arbeit%22%2C%22lat%22%3A51.45%2C%22lon%22%3A7.01%2C%22group%22%3A%22work%22%7D%5D
```

i.e. `destinations=[{"name":"Arbeit","lat":51.45,"lon":7.01,"group":"work"}]` before encoding. See
"Cache semantics" below for how a `destinations` param interacts with caching.

## Cache semantics

The cache is **persistent** (a table in `redat.db`, survives restarts and redeploys), **bounded**
(`cache_max_entries` / `cache_max_bytes`; expired rows are evicted first, then least recently used) and
**per card**:

- `ok`/`empty` envelopes are stored per `(key, lat₄, lon₄, plot, force, cache_version)` — by `/analyze`
  and `/section/{key}` alike; `error`/`gated` are never cached; a `destinations` param suppresses caching
  for the two sections it can affect (`commute`, `oepnv`) and nothing else.
- TTL per card: `settings.yaml` `cache_ttls` › the card's registry `cache_ttl_s` › the global
  `cache_ttl_s` (30 days). Registry defaults: `air_quality` 1 h (live sensor readings), `oepnv` 7 days
  (timetable); everything else is geodata that changes yearly at most and takes the 30 days. `0` disables
  caching for a card.
- A cached envelope carries `cached: true` and `cached_at` (ISO-8601 UTC); the website shows it as
  „Stand dd.mm.yyyy" with a ↻ button. `?fresh=1` on `/section/{key}`, `/analyze` and `GET /report`
  skips the cache read and re-runs the card(s); the fresh result replaces the cached one. (`force` lifts
  the parcel gate and has nothing to do with the cache.)
- Geocoding and autocomplete results are cached in the same store (hits 30 days, unknown addresses 1 h,
  autocomplete 7 days; outages are never cached) — Geoapify is the metered resource.
- Ops: `/healthz` reports `cache.{entries,bytes,expired}`; `scripts/cache_admin.py stats|purge` inspects or
  purges (`--expired`, `--section KEY` e.g. after a new BRW year, `--all`). Bumping a card's
  `cache_version` in `core/sections.py` invalidates its entries on the next deploy.

## Deep link

`/?address=Musterstraße 1, 45127 Essen&auto=1` loads the homepage and immediately runs the analysis,
so it can be bookmarked or shared as a direct "run this address" link.

## Local development

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
GEOAPIFY_API_KEY=… .venv/bin/uvicorn redat.app:app --port 8200 --reload
.venv/bin/python -m pytest -q       # 443 tests, hermetic, ~6.5s

# manual, non-hermetic: drives a real browser against a running instance (Playwright + live
# external services). Not collected by pytest. Point it at any running REDAT with --base-url.
.venv/bin/python scripts/smoke_analyze.py
```

### Tailwind

The website's CSS is a committed, content-scanned Tailwind build. After changing template classes:

```bash
npx tailwindcss@3 -c tailwind.config.js -i tailwind.input.css -o redat/static/redat.css --minify
```

## Docs

- Design: [`docs/DESIGN.md`](docs/DESIGN.md)
- Plan: [`docs/2026-09-05-nrw-redat-plan.md`](docs/2026-09-05-nrw-redat-plan.md)
- Status, deploy runbook, known limitations, work log: [`HANDOVER.md`](HANDOVER.md)
