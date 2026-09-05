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
curl -s localhost:8200/healthz  # {"status":"ok","version":"1.0.0","chromium":true,"sources_loaded":20}
```

`.env` (git-ignored, copy from `.env.example`):

| Key | Meaning |
|---|---|
| `GEOAPIFY_API_KEY` | Required — geocoding, autocomplete, amenities, commute. Same key as House Hunter's `.env`. |
| `REDAT_API_KEY` | Optional. When set, every `/api/*` route requires an `X-Api-Key` header. Leave empty for LAN-open (the agreed default) — see "Known limitations" in `HANDOVER.md` for why the website's own cards stop loading if you set this. |
| `REDAT_DATA_DIR` | Where `redat.db` and `source/{boris,flood,elections}` live. `/data` inside the container (bind-mounted from `./data` by `docker-compose.yml`). |
| `REDAT_CACHE_TTL_S` | Section result cache TTL in seconds (default 21600 = 6 h). |
| `REDAT_PUBLIC_URL` | Base URL used to build permalinks (e.g. `http://192.168.188.64:8200`). |
| `REDAT_LOG_LEVEL` | Python logging level. |

### Geodata (not in git)

`data/source/{boris,flood,elections}` (~6.2 GB) is a copy of House Hunter's own geodata files, rsynced
onto the host once — it is not tracked in git and not part of the Docker build context (`.dockerignore`
excludes the top-level `data/` bind-mount directory). The smaller, still-large `redat/data/` package
files (EEA air-quality grid, Zensus 2022 grid, the letsencrypt intermediate cert for the Breitbandatlas
host) **are** committed and shipped in the image — they are a different directory from the host bind
mount. See `HANDOVER.md` for the exact rsync source and the deploy runbook.

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
| `GET /api/v1/report?address=&plot_size_m2&living_space_m2&destinations` | Convenience machine path: geocode + analyze + PDF in one call. |
| `GET /api/v1/run/{run_id}/report.pdf` | Re-render a stored run as a PDF. |

`destinations` is a `;`-separated list of `Name,lat,lon` triples for custom commute destinations (bypasses
the section cache — see `HANDOVER.md`).

## Deep link

`/?address=Musterstraße 1, 45127 Essen&auto=1` loads the homepage and immediately runs the analysis,
so it can be bookmarked or shared as a direct "run this address" link.

## Local development

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
GEOAPIFY_API_KEY=… .venv/bin/uvicorn redat.app:app --port 8200 --reload
.venv/bin/python -m pytest -q       # 439 tests, hermetic, ~6.5s
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
