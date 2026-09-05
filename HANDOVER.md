# HANDOVER

## Status

Live on `:8200` since 2026-09-05, running via `docker compose` on the same host as House Hunter
(`/srv/nrw-redat`, LAN address `http://192.168.188.64:8200`). LAN-open by default (`REDAT_API_KEY`
unset). 443 tests pass hermetically; the Docker build's `test` stage re-runs the full suite and refuses
to produce an image on a red run.

## Deploy runbook

**First deploy:**

```bash
cd /srv/nrw-redat
cp .env.example .env    # GEOAPIFY_API_KEY from /srv/house-hunter/.env, REDAT_PUBLIC_URL=http://192.168.188.64:8200
mkdir -p data           # bind mount target; data/source/{boris,flood,elections} must be rsynced in separately (see below)
docker compose up -d --build
docker compose run --rm --no-deps redat python scripts/build_boris_gpkg.py   # once: index the 15 BRW shapefiles into data/source/boris/brw.gpkg (~5 min, chunked, <2 GB RAM)
curl -s localhost:8200/healthz
.venv/bin/python scripts/smoke_analyze.py --base-url http://localhost:8200   # manual live check: full browser flow, not run by pytest
```

**Update:**

```bash
cd /srv/nrw-redat && git pull && docker compose up -d --build
```

**Rollback:** `git checkout <previous-sha> && docker compose up -d --build` (the previous image tag is
overwritten by `docker compose build`, so there is no separate image rollback — rebuild from source).

## Non-git deploy assets

- **`data/source/{boris,flood,elections}`** (~6.2 GB) — a one-time rsync copy of House Hunter's own
  geodata directories at `/srv/house-hunter/data/{boris,flood,elections}` (exact source paths per
  `docs/2026-09-05-nrw-redat-plan.md` Task 1). Not tracked in git, not part of the Docker build context.
  If this host is ever rebuilt, this copy must be redone before `boris`/`flood`/`btw` sources will work.
  All of it is also directly downloadable (dl-de/zero-2-0, no login): BORIS
  `https://www.opengeodata.nrw.de/produkte/infrastruktur_bauen_wohnen/boris/BRW/BRW_{year}_EPSG25832_Shape.zip`
  (2011-2025, unpack each into `boris/BRW_{year}/`), HWRM
  `https://www.opengeodata.nrw.de/produkte/umwelt_klima/wasser/hochwasser/hwrm/{HQhaeufig,HQ100,HQextrem}-Ueberschwemmungsgrenzen_EPSG25832_Shape.zip`
  (convert to `flood/hwrm/{HQ}.gpkg` with geopandas/ogr2ogr, or leave the unpacked shapefile dirs for the
  fallback), BTW25 geometry from the `btw.py` URL into `elections/btw25/wahlkreise_shp_geo/`.
- **`data/source/boris/brw.gpkg`** — derived, not downloaded: `scripts/build_boris_gpkg.py` streams the 15
  yearly shapefiles into one GeoPackage with an R-tree-indexed layer per year (`brw_2011` … `brw_2025`).
  `boris.py` prefers it and falls back to the shapefiles per year, so it is optional for correctness but
  it is what makes `boris_trend` fast (15 indexed bbox reads ≈ well under a second vs. ~2 s per
  un-indexed shapefile scan, ×15). Rebuild after adding a year (existing layers are skipped).
- **`.env`** — holds `GEOAPIFY_API_KEY` (required) and the optional `REDAT_API_KEY`. Git-ignored; never
  commit it.
- `redat/data/{eea_aq_grid_2023.json, zensus_2022_grid.json.gz, certs/lencr_ye_chain.pem}` are, by
  contrast, committed package files and ship inside the image — do not confuse these with the `data/`
  bind mount above; `.dockerignore`'s `data` pattern is root-anchored and only excludes the top-level
  `./data` directory.

## Known limitations

- **API key vs. website:** with `REDAT_API_KEY` set, the website's own browser-side fetches to
  `/api/v1/*` (from `redat.js`/`analysis.js`) get 401 — neither script sends `X-Api-Key`, and baking the
  key into the served page would leak it to anyone with LAN access. Verified live: with the key set,
  `/` and `/healthz` still return 200, but `/api/v1/analyze` (what the analyzer page calls) 401s, so the
  page loads with no way to run an analysis. The key is meant to protect the API for machine/API clients
  only; the website is designed around the agreed LAN-open default (key unset). Follow-up (not yet
  built): a same-origin session cookie issued by the page, or an auth-terminating reverse proxy in front
  of `/api/v1` only.
- **Störfallbetriebe (Seveso III):** the `infrastruktur` card cannot show a Seveso overlay — NRW
  publishes no such geodata (checked open.nrw, GDI-DE, RVR CSW, wms.nrw.de, both cities' ArcGIS servers;
  the EEA Industrial Emissions Portal's `seveso` field is empty for NRW rows). The card states this
  instead of silently omitting it.
- **Bochum air quality:** the `air_quality` card's "aktuell" rating for Bochum addresses comes from the
  CAMS/citizen-sensor fallback, not a continuous monitoring station — the nearest one is Hattingen-
  Blankenstein, ~9 km away. This is by design, not a bug.
- **BORIS timeout:** `boris` (Bodenrichtwert) makes no HTTP call at all — it reads local geodata with
  geopandas in a `multiprocessing.Process` capped at a hard 12 s (`redat/sources/boris.py`), well inside
  the card's 25 s section timeout. With `brw.gpkg` in place (see "Non-git deploy assets") a lookup is a
  few ms and the cap is never reached. On a shapefile-only deployment a cold, un-indexed read of a
  200-400 MB file (~2 s, more under I/O contention) can still trip it, in which case the subprocess is
  killed and the card returns `status: error`, `message: "BORIS timeout"` — transient; a retry of the
  same address usually succeeds (observed during Task 10 verification: first Brückstraße 1 run errored at
  12 s, the retry was `ok` in 295 ms).
- **Cache semantics:** see README "Cache semantics" for the full contract. In short: persistent
  (`cache` table in `redat.db`), bounded (expired first, then LRU), per-card TTL (`cache_ttls` yaml ›
  registry `cache_ttl_s` › global 30 d; `air_quality` 1 h, `oepnv` 7 d), key = `(key, lat₄, lon₄, plot,
  force, cache_version)`, `ok`/`empty` only, `destinations` suppresses caching for `commute`/`oepnv`,
  `?fresh=1` re-runs and replaces, geocode/autocomplete cached in KV namespaces, `/healthz` exposes counts,
  `scripts/cache_admin.py` for stats/purge. Both routes go through `core.analyze.cached_section`.

## Work log

- **Task 1** (`64edbc4`, `c64f6ef`) — repo bootstrap: Gitea repo, package skeleton, `settings.py`
  (env > `config/settings.yaml` > defaults), app factory, `/healthz`, hermetic pytest collection env.
- **Task 2** (`4ed7273`) — moved the self-contained source modules, their data files (EEA AQ grid,
  Zensus grid, cert bundle), and their tests over from House Hunter unchanged in behaviour.
- **Task 3** (`79fb3b6`) — core tiers, Geoapify client with autocomplete, geocoding with a Nominatim
  fallback.
- **Task 4** (`0b417cc`) — local-geodata sources (BORIS, flood, BTW) repointed at `settings.source_dir`
  instead of hunter's config; ÖPNV destinations sourced from settings.
- **Task 5** (`cce817c`) — the 20-card section registry and the envelope runner; commute/ÖPNV take
  caller-supplied destinations instead of a fixed list.
- **Task 6** (`0727f26`) — moved the report package (builder, render, PDF, noise map, SVG) and report
  templates; dropped the house-hunter listing box that doesn't apply here.
- **Task 7** (`4e7aee0`, `de68aa0`) — SQLite-backed `RunStore` (WAL, base32 ids) and `SectionCache`
  (TTL, ok/empty-only); a follow-up commit fixed a connection fd leak.
- **Task 8** (`ea41384`) — `/api/v1`: sections, geocode, autocomplete, section, analyze (+save), runs,
  report (POST/GET/run), optional `X-Api-Key` auth.
- **Task 9** (`5ac42fc`) — website: analyzer page, `/a/{id}` permalinks, `/quellen` from `sources_meta`,
  the `app` Alpine store, committed Tailwind build.
- **Task 10** (this commit) — Dockerfile with a pytest test-gate stage, `docker-compose.yml` on `:8200`,
  live verification against both cities, README/HANDOVER/CLAUDE.md, spec+plan copies, `/srv/README.md`
  service-inventory entry, push to `origin/main`. Also fixed a latent packaging bug found during the
  Docker build: bare `pytest -q` failed to collect any test (`ModuleNotFoundError: No module named
  'redat'`) because nothing put the project root on `sys.path` — it only worked locally via
  `python -m pytest` (which inserts the cwd). Fixed by adding `pythonpath = ["."]` to
  `[tool.pytest.ini_options]` in `pyproject.toml`; no test or gate logic changed.
- **Task 11** (post-review fix round) — `GET /api/v1/section/{key}` now consults `SectionCache` too
  (`core.analyze.cached_section()`, shared with `/analyze`'s `run_all()`); corrected the cache-semantics
  and `destinations`-format wording in this file, `README.md` and `CLAUDE.md`; corrected the "BORIS
  timeout" explanation above; copied the five `2026-09-04-*` card specs into `docs/`; ported
  `scripts/smoke_analyze.py` (manual Playwright check against a running instance); fixed
  `require_api_key` to byte-compare so a non-ASCII `X-Api-Key` is a 401, not a 500; warmed
  `chromium_available()` in `lifespan` so the first `/healthz` is cheap; assorted housekeeping (lazy
  `mkdtemp` in `tests/conftest.py`, a stale comment in `analysis.js`, unused imports, a duplicate
  `fixed_destinations()` call in `oepnv.py`, dead house-hunter listing helpers deleted from
  `map-utils.js`). Commits `4660070`, `9475f91`.
- **Task 11 follow-up** (`5071063`) — the lifespan warm-up had called the sync Playwright probe on the
  event loop; `sync_playwright()` refuses to start inside a running asyncio loop and the `lru_cache`
  pinned that failure, so the redeployed container reported `chromium: false` on `/healthz` until the
  probe was moved to `anyio.to_thread.run_sync`. Regression test in `tests/test_app.py`.

- **Task 12** (2026-09-05, redat.ares-hud.com deploy) — `boris_trend` was unusable on a host with the
  real 15-year data: for a point outside every zone of a given year (common for pre-2020 stands in the
  Essen centre) `lookup_bodenrichtwert()` fell through its 1 km bbox read to a 5 km re-read and then a
  FULL shapefile load (~80 k polygons, 6-12 s, ~1 GB) — per year. The trend blew its 30 s timeout every
  time, OOM-killed the 2 GB container once, and starved the other cards into timeouts during a page
  analyze. Both fallbacks were dead weight: any zone that covers the point (or sits within the 10 m snap
  tolerance) must intersect the 1 km bbox, so the wider reads could never find anything the first one
  missed. Fixed by (a) making the lookup a single bbox read — no full load path exists any more, the
  module-level year cache is gone — and (b) adding `scripts/build_boris_gpkg.py` + GeoPackage-first
  source discovery (`_find_source`), which turns the ~2 s un-indexed shapefile scan into an R-tree
  lookup. Regression tests: one-read-only, gpkg-over-shapefile preference, shapefile fallback, 10 m snap
  bounds, chunked/idempotent build, half-written-layer rebuild, mixed-encoding repair. Found on the way:
  the 2022-2024 `BRW_{year}_EPSG25832_Shape.zip` files declare UTF-8 in `.cpg` but ~400 rows each
  (Gutachterausschuss Moers) are ISO-8859-1 - a plain GDAL read raises `UnicodeDecodeError`, which the
  old lookup swallowed into `None` for any bbox touching such a row. Both the build script and the
  shapefile fallback in `boris.py` now re-read as Latin-1 and repair per value
  (`repair_mixed_encoding`). Live after the fix on redat.ares-hud.com: `boris_trend` 1.2 s cold
  (was: timeout after 30 s + one OOM restart), `boris` ~130 ms, container RSS ~100 MB (was 1.4 GB).

- **Task 13** (2026-09-05) — caching strategy for a public deployment with a 30-day retention wish. The
  old `SectionCache` was a process dict with one 6 h TTL: lost on every redeploy, unbounded, and the same
  TTL for live sensor data and yearly geodata. Replaced by a persistent SQLite cache in `redat.db`
  (single connection + lock, WAL; `store/cache.py`) with: per-card TTL (`Section.cache_ttl_s`, yaml
  `cache_ttls`, global default now 30 d; `air_quality` 1 h, `oepnv` 7 d), `Section.cache_version` in
  the key, `cached_at` on hits, bounds (`cache_max_entries`/`cache_max_bytes`, expired-then-LRU eviction
  on write, hourly sweep task in lifespan), `?fresh=1` as the explicit refresh path (`force` never was a
  cache bypass — the README used to imply it), geocode/autocomplete KV caching (hits 30 d, misses 1 h,
  autocomplete 7 d; outages never), `/healthz` cache counts, `scripts/cache_admin.py`, and a „Stand
  dd.mm.yyyy" + ↻ per card on the website. Running totals keep bounds checks O(1); the cache is built in
  `create_app()` (not lifespan) so it exists for every caller. 33 new tests. The host `.env` no longer
  pins `REDAT_CACHE_TTL_S`.

## Open items

- **Hunter cutover** (spec §11) is explicitly out of scope for this plan — a separate, later plan covers
  pointing House Hunter's `/analyze` page at this service instead of its own embedded analysis code.
- The API-key-vs-website gap above (same-origin cookie or proxy auth) is unresolved; low priority while
  the service stays LAN-open.
- **`_pdf()` builds the report context twice** (`redat/api/v1.py`) — once in `build_report_context()` for
  validation, again inside `render_pdf()`. Cosmetic (~ms), but also means the "generated_at" timestamp
  used for validation is discarded and recomputed. Fix: let `render_pdf` accept a pre-built `ctx`, or
  move the `ReportPayloadError` catch to wrap one build.
- **`/quellen` and the PDF report footer are two independently maintained lists.** `core/sources_meta.py`
  drives `/quellen`; the report footer's sources come from `Section.source` strings in
  `core/sections.py`. `sources_meta.py` exists precisely so the two can't drift — but they still can
  today. Fix: derive `Section.source` from `sources_meta.for_section(key)`, or have the report footer
  render `for_section()` results directly.
- **Non-HTML 422/404 on HTML routes.** `GET /?plot_size_m2=abc` and `GET /nope` return FastAPI's default
  JSON error bodies instead of a rendered `404.html`/error page, unlike `/a/{unknown}`. Fix: an exception
  handler that renders an HTML error page for non-`/api` paths, plus manual float coercion for the m²
  query params.
- **`RunStore.save` has no retry on a run-id collision.** A 48-bit id collides with probability ~1 in
  2⁴⁸ per pair; an `IntegrityError` would surface as a 500. A `for _ in range(3)` retry loop closes it.
  Cosmetic.
- **Container runs as root**, so `data/redat.db` (and its `-wal`/`-shm`) in the host bind mount end up
  root-owned — the host user needs `sudo` to rotate or delete them. Not required by spec, but worth
  fixing (`USER pwuser` in the runtime stage after `chown`-ing `/data`) or at least documenting as a
  `sudo` requirement in the runbook.
- **Single-worker assumption is load-bearing and undocumented in the Dockerfile.** `SectionCache` and
  `RunStore`'s connections are per-process state; running `uvicorn --workers N > 1` would silently give
  each worker its own disjoint cache (and, for SQLite, is still safe but pointless). The `CMD` is
  correctly single-worker already — never add `--workers N` without redesigning the cache as shared
  state first.
- **`api_analyze`/`api_report_get` hold one anyio threadpool worker each, and a single page load fires
  20 concurrent `/section` requests** (each spawning its own section thread) — two simultaneous page
  loads plus one `/analyze` can saturate the default 40-worker limiter. Not a problem at LAN scale, and
  I1's cache fix reduces the load materially, but worth knowing before this sits behind anything shared.
