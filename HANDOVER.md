# HANDOVER

## Status

Live on `:8200` since 2026-09-05, running via `docker compose` on the same host as House Hunter
(`/srv/nrw-redat`), publicly at `https://redat.ares-hud.com` behind Traefik. `REDAT_PUBLIC_URL` on this
host is `https://redat.ares-hud.com` — it is the host of both permalinks and invite links, and it
switches the session/CSRF cookies to `Secure`. `docker-compose.yml` publishes the port as
`127.0.0.1:8200:8200` (Traefik reaches the container over the Docker network, not the published port),
so the LAN address `http://192.168.188.64:8200` is dead both at the TCP level and, had it still
answered, at login: `Secure` cookies are dropped on a plaintext origin. LAN access is out of scope for
this feature — anyone who wants the app goes through `https://redat.ares-hud.com`, LAN included;
`curl -s localhost:8200/healthz` and the runbook's `smoke_analyze.py --base-url http://localhost:8200`
still work because they run on the host itself. `REDAT_API_KEY` unset. Access is
app-native login as of the user-management feature (Work log below): accounts, server-side sessions,
invite links and an admin dashboard live in the app itself, so the host's Traefik `redat-auth` BasicAuth
middleware (the single shared `test` user) has been removed from the router — Traefik still terminates
TLS, does the HTTP→HTTPS redirect and adds the security headers (`sec-headers@docker`), nothing else. 29
cards, 794 tests pass hermetically; the Docker build's `test` stage re-runs the full suite and refuses to
produce an image on a red run.

## Deploy runbook

**First deploy:**

```bash
cd /srv/nrw-redat
cp .env.example .env    # GEOAPIFY_API_KEY, REDAT_PUBLIC_URL, REDAT_BOOTSTRAP_ADMIN_PASSWORD
docker compose build    # the geodata script runs its GeoPackage builds inside this image
scripts/fetch_geodata.sh   # downloads BORIS/HWRM/BTW25 (~3.3 GB) into ./data/source and builds brw.gpkg + the flood .gpkg files (~10 min); idempotent
docker compose up -d
curl -s localhost:8200/healthz
.venv/bin/python scripts/smoke_analyze.py --base-url http://localhost:8200   # manual live check: full browser flow, not run by pytest
```

With `REDAT_BOOTSTRAP_ADMIN_PASSWORD` set, this first `docker compose up -d` also creates the user
`admin` with that password (only while the `users` table is empty — a warning is logged, and the
password should be changed via `/konto` right after the first login).

**Enabling app-native login on a host that still has the Traefik BasicAuth override** (this host, done
once on 2026-09-10): edit the host-only `docker-compose.override.yml` — remove the two `redat-auth`
middleware labels (the `traefik.http.middlewares.redat-auth.basicauth.*` label and the one wiring it into
the router) and change the router's `traefik.http.routers.redat.middlewares` label to `sec-headers@docker`
only — then `docker compose up -d` again to pick up the label change. Traefik keeps TLS, the
HTTP→HTTPS redirect and the security headers; the app's own session cookie is now the only gate.

**Verification checklist** (design spec §9, also the one this task ran locally against a scratch
instance — see "Task 5" in the Work log below for the actual transcript): over HTTPS, `GET /` → `303` to
`/login?next=%2F`; login as `admin` → `303` to `/`, `GET /` → `200` with the username in the nav;
`GET /api/v1/sections` without a cookie → `401`; `GET /a/<id>` and its `report.pdf` → public, no cookie
needed; `GET /admin` loads for the admin session; an invite link created from `/admin` round-trips to a
new account in a private/second browser session, and that user shows up in the admin users table.

**Update:**

```bash
cd /srv/nrw-redat && git pull && docker compose up -d --build
```

**Rollback:** `git checkout <previous-sha> && docker compose up -d --build` (the previous image tag is
overwritten by `docker compose build`, so there is no separate image rollback — rebuild from source).

**Locked out / no admin account:**

```bash
docker compose exec redat python scripts/users.py list
docker compose exec redat python scripts/users.py create-admin --username admin
docker compose exec redat python scripts/users.py reset --username admin
```

## Non-git deploy assets

- **`data/source/`** (~11 GB) — not tracked in git, not part of the Docker build context. Everything in it
  is public open data (dl-de/zero-2-0 / Bundeswahlleiterin) and `scripts/fetch_geodata.sh` fetches and
  prepares all of it; the README "Geodata" table lists every path, its source URL and the card that uses
  it. Originally this was an rsync copy of House Hunter's `/srv/house-hunter/data/{boris,flood,elections}`;
  since Task 14 the script is the source of truth, so a rebuilt host needs no other machine.
- **`data/source/boris/brw.gpkg`** and **`flood/hwrm/{HQ}.gpkg`** — derived by `scripts/build_boris_gpkg.py`
  / `scripts/build_flood_gpkg.py` (the fetch script runs both inside the app image; chunked, idempotent,
  crash-safe). The sources prefer the GeoPackages and fall back to the shapefiles, so the .gpkg files are
  optional for correctness but are what makes `boris`/`boris_trend`/`flood` fast (R-tree bbox reads in ms
  instead of scanning a 200-400 MB shapefile). After a new BORIS year: extend `AVAILABLE_YEARS` +
  the script's `YEARS`, re-run the script, `scripts/cache_admin.py purge --section boris`.
- **`.env`** — holds `GEOAPIFY_API_KEY` (required), the optional `REDAT_API_KEY`, and the user-management
  keys `REDAT_BOOTSTRAP_ADMIN_PASSWORD` (bootstrap-only, see "Deploy runbook" above) and
  `REDAT_SESSION_DAYS` (session lifetime, default 30). Git-ignored; never commit it.
- `redat/data/{eea_aq_grid_2023_nrw.json.gz, zensus_2022_nrw.npz, schulen_nrw.json.gz,
  unfallatlas_2020_2025_nrw.npz, bergbauberechtigungen_nrw.geojson.gz, ladesaeulen_nrw.json.gz,
  egms_vertical_velocity_nrw.npz, certs/lencr_ye_chain.pem}` are, by contrast, committed package files and
  ship inside the image — do not confuse these with the `data/` bind mount above; README "Static grids in
  the repo" lists build script and source per file. `.dockerignore`'s `data` pattern is root-anchored and only excludes the top-level
  `./data` directory.

## Known limitations

- **The throttle, audit-log `ip` column and Secure-cookie reasoning assume the app is reached only
  through Traefik.** `client_ip()` (`redat/auth/principal.py`) honours `X-Forwarded-For` only from a
  peer inside `REDAT_TRUSTED_PROXIES` (default: Docker networks + RFC1918) — otherwise a public client
  could spoof the header and rotate it to defeat the login throttle (keyed on `(client_ip, username)`)
  and pollute `events.ip`. `docker-compose.yml` now binds the published port to `127.0.0.1:8200:8200`
  so the container is reachable only via the Docker network Traefik sits on; narrow
  `REDAT_TRUSTED_PROXIES` further (or firewall the host) if that path ever changes.
- **Login throttle is per process:** `redat/auth/throttle.py`'s `LoginThrottle` (5 failed logins per
  `(client IP, username)` within 10 minutes → 60 s lock) is an in-memory dict on the running process, not
  a shared store. It resets on every restart/redeploy and, if the app ever ran with more than one worker
  process, each worker would count failures independently — fine at the current single-worker scale (see
  "Single-worker assumption" in "Open items" below, which already applies to the cache for the same
  reason), worth revisiting together if that ever changes.
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

- **Task 14** (2026-09-05) — new-server runbook made executable: `scripts/fetch_geodata.sh` downloads
  BORIS 2011-2025, the three HWRM zips and the BTW25 geometry (resumable curl, idempotent, `--only`,
  `--no-build`, `--prune`, `--data-dir`/`--python` for non-docker), then runs `build_boris_gpkg.py` and the
  new chunked `build_flood_gpkg.py` (replaces the by-hand ogr2ogr step; writes `<HQ>.partial.gpkg` and
  renames, so a crash never leaves a half-written file flood.py would pick up) via `docker compose run`
  as the invoking user. README "Geodata" documents the layout, sources and the add-a-year procedure.
  Verified: idempotent against the live host data, real download into a scratch dir, docker build path.

- **Tier-1 sources** (2026-09-05, plan `docs/superpowers/plans/2026-09-05-tier1-sources.md`, spec
  `docs/superpowers/specs/2026-09-05-tier1-sources-design.md`) — six new cards (`flurstueck`, `irw`, `baugrund`,
  `radon`, `schulen`, `unfaelle`) and three extensions (`flood` + ÜSG §78 WHG, `planning_essen` + Satzungen/
  Sanierung, `planning_bochum` + Stadterneuerung; all three at `cache_version=2`). New shared helper
  `redat/sources/esri_wms.py`. Two new static grids under `redat/data/` with build scripts. The ALKIS WFS proxy
  only accepts TYPENAMES+BBOX(EPSG:25832) and answers GML — no JSON, no CQL. The BfS WFS bbox is lon,lat.
  The BK50 WMS is read as HTML because only the HTML carries readable class labels.

- **Hotfix** (2026-09-06, `74358cd`) — `/a/khchav5vji` showed "numpy failed to import" on every geo card: the
  first page load after a restart spawns ~26 section threads that raced on the *first* import of numpy/shapely,
  CPython broke the import cycle and left numpy half-initialised in `sys.modules` for the life of the process.
  `create_app()` now calls `core/warmup.warm_geo_stack()` in the main thread before serving (~0.4 s). Verified
  with three fresh restarts × 26 concurrent `/section` requests: 0 errors.

- **Tier-2 sources** (2026-09-06, plan `docs/superpowers/plans/2026-09-06-tier2-sources.md`, spec
  `docs/superpowers/specs/2026-09-06-tier2-sources-design.md`) — three card extensions and one new card:
  `bergbau` gained Bergbauberechtigungen at the point (`73c44ab`, Bezirksregierung Arnsberg shapefile
  cropped to the Essen/Bochum window, `redat/data/bergbauberechtigungen.geojson.gz`, 630 features) and
  Copernicus EGMS Bodenbewegung (`9dd3782`, `0261ce1`, vertical ground velocity,
  `redat/data/egms_vertical_velocity.json.gz`, release 2020-2024, downloaded via the insar-api with a
  CLMS token — no longer data-gated, the tile shipped); `starkregen` gained Gelände from the NRW DGM1 WCS
  (`06284fd`, `37e25e1`, height/Hanglage-Tieflage/slope, fetched concurrently with the Starkregen lookup);
  `noise` gained Fluglärm DUS/EMH and Ruhige Gebiete from the Essen and Bochum city layers (`73174c6`,
  `2559a60`, queried concurrently, additive bbox selection in the Essen/Bochum overlap). New card
  `ladesaeulen` (`cbcfda3`, public EV chargers within 1 km from the BNetzA Ladesäulenregister,
  `redat/data/ladesaeulen.json.gz`, 2,603 chargers, Stand 2026-09-01). Two PDF-only figures: "Der Ort im Wandel"
  (`33039a9`, `2288052`, four historic-map WMS panels 1840s/1900s/1950s/today on the Flurstück page,
  fetched concurrently, 10 s timeout) and "Grün und Hitze" (`d4a815c`, RVR umon WMS canopy-cover and
  surface-temperature panels with legends on the Nachbarschaft/Zensus page); a shared `title_font()`
  TrueType helper landed in `noise_map.py` (`21858d4`) so umlauts render in map titles instead of boxing.
  `cache_version` bumps: `bergbau` → 3, `starkregen` → 2, `noise` → 2 (`ladesaeulen` is new at the
  default 1). Cards: 27. Suite: 654 tests.
  - **RVR-WMS finding:** the RVR raster WMS (`services-rvr.geoportal.ruhr/umon`) answers GetFeatureInfo
    with geometry only, no pixel values, and its legends are continuous colour ramps (146 colours in an
    88×50 px legend) — pixel decoding would be guesswork. Dropped a planned "Grün und Hitze" *value* card
    for this reason; the layers are used as GetMap images with their GetLegendGraphic PNGs instead
    (`SLD_VERSION=1.1.0` is required on the legend call).
  - **Data-gated items, now resolved or still open:** EGMS Bodenbewegung is now resolved — the tile
    (`EGMS_L3_E41N31_100km_U_2020_2024_1.tif`) was downloaded via the CLMS insar-api and built into
    `redat/data/egms_vertical_velocity.json.gz`; the card is live, not a "nicht installiert" placeholder.
    Still open: **Altlasten Essen/Bochum** (e-mails to the two cities' Untere Bodenschutzbehörde drafted
    for the site owner to send; unblocks once a reply with usable geodata/API access arrives) and
    **Hebesätze** (current values need a registered Regionaldatenbank account for table 71231-03-01-5 —
    the open Destatis workbook stops at the 2022 edition, before the 2025 Grundsteuer reform; unblocks
    once someone registers and pulls the table).

- **Tier 3 — NRW-weit** (2026-09-07, plan `.superpowers/sdd/2026-09-07-nrw-wide/`, commits `f55cd98`,
  `0412b4d`, `2eecaa9`, `b8e8413`, `0bb3ece`, `1804d95`, `bc07f7f`, `bf3b49f`, `bca96ab`) — took the
  service statewide instead of Essen/Bochum-only. New `redat/core/nrw.py` holds the shared NRW/RVR/Essen/
  Bochum bounding boxes every statewide build script, source module and gate now uses instead of a
  hand-rolled window.
  - **Task 1** — Zensus 2022 grid rebuilt statewide as `redat/data/zensus_2022_nrw.npz` (796,280 cells,
    16.9 MB on disk, ~70 MB resident: sorted int64 cell keys + an int16 value matrix, replacing the old
    gzipped-JSON crop).
  - **Task 2** — Unfallatlas rebuilt statewide as `redat/data/unfallatlas_2020_2025_nrw.npz` (418,359
    rows, 5.1 MB, ~17 MB resident, latitude-sorted for a binary-search window lookup).
  - **Task 3** — new Copernicus EGMS vertical-ground-velocity raster, `redat/data/
    egms_vertical_velocity_nrw.npz`, mosaicked from the nine EGMS L3 Ortho tiles covering NRW (each
    downloaded via `~/.config/nrw-redat/egms_download.py`, the CLMS insar-api client kept outside the
    repo) — 2728 × 2750 cells, 1,717,178 measured, 3.3 MB, ~15 MB resident.
  - **Task 4** — three more statewide grids: `redat/data/ladesaeulen_nrw.json.gz` (28,659 chargers, Stand
    2026-09-01, 450 KB), `redat/data/bergbauberechtigungen_nrw.geojson.gz` (5,361 fields, 1.4 MB, looked
    up via an STRtree instead of a linear scan) and `redat/data/eea_aq_grid_2023_nrw.json.gz` (276 × 274
    cells, 210 KB).
  - **Task 5** — `redat/sources/denkmal_nrw.py`: the statewide INSPIRE Denkmal WFS
    (`wfs_nw_inspire-denkmal`) backs the `denkmal` card outside the RVR bbox. **Verified service fact:**
    the WFS advertises EPSG:4258 in its capabilities but only accepts a working `BBOX` filter in
    EPSG:25832 (`BBOX=xmin,ymin,xmax,ymax,urn:ogc:def:crs:EPSG::25832`) — a WGS84 bbox silently matches
    nothing — and only answers GML 3.2 (`outputFormat=json` is rejected). `denkmal`'s `data` gained
    `source` (`"rvr"` or `"nrw"`) and `hinweis` (delivery is voluntary per municipality; Bonn is complete,
    Essen ships surfaces only, Köln nothing).
  - **Task 6** — new card `planning_nrw` ("Bauleitplanung NRW", parcel tier) from the statewide INSPIRE
    "geplante Bodennutzung" OGC API Features service. **Verified service fact:** the endpoint is
    `https://ogc-api.nrw.de/inspire-lu-bplan/v1/collections/spatialplan/items` — the un-versioned path
    307-redirects, so the client needs `follow_redirects=True`, and delivery is voluntary per
    municipality (Essen 21 plans in a 1 km bbox, Bochum 52, Bonn only its FNP — verified 2026-09-07), so
    an empty answer never means "kein Bebauungsplan". A follow-up commit (`bc07f7f`) guards null/
    unrecognized geometry and coerces non-string properties, found while exercising real data statewide.
  - **Task 7** — `redat/report/regionalplan_map.py`: a Regionalplan WMS panel on the GFNP page of the
    PDF. **Verified service fact:** `wms_nw_regionalplan`'s one layer has no GetFeatureInfo and its
    legend is a 959 × 1918 px poster with ~120 entries, so the figure is image-only (GetMap) with the
    legend linked, not decoded into structured data. `gfnp`'s `data` gained `rvr` (bool) and `hinweis`,
    and the card skips its Essen ArcGIS GFNP query outside the RVR bbox; the card title is now
    "Flächennutzungsplan (GFNP) & Regionalplan".
  - **Task 8** — `planning_essen`/`planning_bochum` now raise `Empty` ("nur für Adressen in Essen/Bochum
    verfügbar") outside their city's bbox instead of silently running a query that could never match; all
    four planning source modules import the shared city boxes from `nrw.py`.
  - **`cache_version` bumps:** `bergbau` → 4, `zensus` → 2, `unfaelle` → 2, `ladesaeulen` → 2,
    `air_quality` → 2, `denkmal` → 2, `gfnp` → 2; `planning_nrw` is new at the default 1. Cards: 28
    (was 27). Suite: 704 tests (was 654).
  - **Storage change:** the three large grids (Zensus, Unfallatlas, EGMS) moved from gzipped JSON to
    NumPy `.npz` — sorted/searchable arrays instead of a Python dict walk, needed once the crop went from
    an Essen/Bochum window to the full state. The four smaller grids stayed gzipped JSON/GeoJSON; see
    README "Static grids in the repo" for the exact file/build-script/refresh table.
  - **Still open (unchanged by this tier):** **Altlasten Essen/Bochum** — e-mails to the two cities'
    Untere Bodenschutzbehörde are drafted for the site owner to send; unblocks once a reply with usable
    geodata/API access arrives. **Hebesätze** — current values need a registered Regionaldatenbank
    account for table 71231-03-01-5; the open Destatis workbook stops at the 2022 edition, before the
    2025 Grundsteuer reform. **Köln's own Denkmal WFS is not integrated** — the statewide INSPIRE Denkmal
    WFS (Task 5) returns nothing for Köln (the city doesn't deliver into it), and Köln publishes its own
    Denkmalliste separately; wiring that up as a fourth source (after RVR, statewide INSPIRE, and the
    existing city sources) is future work, not done here.

- **Tier 4 — Stadtklima** (2026-09-07, plan `.superpowers/sdd/2026-09-07-stadtklima/`, commits `59c9f15`,
  `c2c140e`) — a Klimatop/Wärmebelastung card and a statewide "Grün und Hitze" PDF figure, both against the
  LANUV Klimaanalyse NRW 2026 WMS.
  - **Task 1** — new card `stadtklima` ("Stadtklima (Klimaanalyse NRW)", area tier, after `zensus`) from
    `redat/sources/stadtklima.py`. **Verified service facts:** WMS
    `https://www.wms.nrw.de/umwelt/klimaanpassung_klimaanalyse` layers are numbered, not named (`59`
    Klimatope, `54`/`52` PET typisch/extrem, `38`/`29` Lufttemperatur nachts typisch/extrem);
    GetFeatureInfo with `INFO_FORMAT=application/geo+json` returns one feature whose properties carry
    `Classify.Pixel Value` — a float-as-string for a raster hit, or the literal string `"NoData"` for a
    miss, not a JSON null. The five layers are fetched concurrently with per-layer error isolation so one
    layer failing doesn't blank the card. The card reports PET (typical and extreme summer day) and night
    air temperature, the Klimatoptyp, and a rating (`unbekannt` … `extrem starke Wärmebelastung`) from the
    layer-54 PET legend.
  - **Task 2** — `redat/report/climate_maps.py`'s `render_climate_maps()` now branches on whether the
    point falls in the RVR bbox: inside, the existing RVR canopy/surface-temperature panel pair is
    unchanged; everywhere else in NRW it swaps in a Copernicus HRL Tree Cover Density 2018 canopy panel
    (10 m, no legend — the service's GetLegendGraphic is a 236×2040 px ramp that doesn't fit the print
    layout) and the LANUV Klimaanalyse PET class map with legend. **Verified service fact:** the
    Copernicus HRL WMS serves only EPSG:3857/4326 — a 3035/25832 GetMap request comes back a blank
    transparent tile — so that panel's window goes out via the new `bbox_2km_3857()` helper in Web
    Mercator, whose metres shrink by cos(lat) at this latitude. The result dict gained `"variant"`
    (`"rvr"`/`"nrw"`) and the zensus report footnote explains whichever pair rendered. The RVR panels stay
    in the Ruhr; nothing about them changed.
  - Cards: 29 (was 28). Suite: 730 tests (was 704). `stadtklima` is new at the default `cache_version` 1;
    no existing card's `cache_version` needed a bump (a new card plus a PDF-only figure change).
  - **Fix wave** (2026-09-07): a total outage of the five Klimaanalyse WMS layers now raises instead of
    being cached as a blank "unbekannt" card, and `SectionCache.put`'s never-cache-a-transient-failure rule
    (README "Cache semantics") now also covers a non-empty top-level `errors` dict, not just `*_error`
    siblings — the Klimaanalyse PET raster's rendered pitch was measured at 25 m during this work; the
    service does not document a native resolution.

- **User management** (2026-09-09/10, plan `.superpowers/sdd/2026-09-09-user-management/`, spec
  `docs/superpowers/specs/2026-09-09-user-management-design.md`) — app-native login, sessions, invite
  links and an admin dashboard, replacing the host's single-user Traefik BasicAuth (see "Status" above).
  No new Python dependency: passwords via `hashlib.scrypt`, session/invite tokens via `secrets`, CSRF via
  a double-submit cookie.
  - **Task 1** (`112b0ea`) — `redat/store/users.py` (`UserStore`: users, sessions with a sliding expiry,
    invites) and `redat/store/events.py` (`EventStore`: append-only usage events, `stats()` for the
    dashboard, `prune()`), both in `redat.db`; `redat/auth/passwords.py` (`hash_password`, `check_policy`,
    `PasswordPolicyError`) and `redat/auth/tokens.py` (opaque tokens, stored only as sha256).
  - **Task 2** (`6a6264b`) — `redat/auth/principal.py`: `current_principal`/`require_principal`/
    `require_admin` for the API, `page_principal`/`page_admin` for the website (redirect instead of a bare
    401/403), `safe_next` (open-redirect guard), the session/CSRF cookie contracts; bootstrap admin
    creation wired into `redat/app.py::create_app`.
  - **Task 3** (`b4d9064`, fix round `756c3b2`) — `redat/web/auth_pages.py` and the `login.html`/
    `invite.html`/`konto.html` templates: login/logout, invite acceptance (new user or password reset),
    change-password and device-session management, all CSRF-protected; `756c3b2` closed a login timing
    oracle (a disabled account no longer short-circuits before the password hash) and a `safe_next`
    backslash bypass.
  - **Task 4** (`bf3f60e`) — `redat/web/admin_pages.py` and `admin.html`: KPI tiles, a 30-day analyses
    chart, the users table (with disable/enable/delete/password-reset-link actions; an admin cannot
    disable or delete themselves), invites table, recent-activity table, "Neuer Einladungslink" form.
  - **Task 5** (`124fede`, `0af5d53`) — `scripts/users.py` (CLI over `UserStore`/`EventStore` for
    lockout recovery: `list`, `create-admin`, `reset`, `disable`, `enable`, `prune-events`; no
    `GEOAPIFY_API_KEY` needed), README "Zugang & Benutzer" and `.env` table, this Status/runbook/Known-
    limitations update, `CLAUDE.md` access-rules/testing rules, and the Tailwind rebuild for the four new
    templates. Verified locally end-to-end against a scratch instance (login → nav → API 401 without a
    cookie → admin page → invite round-trip in a second cookie jar → logout); see the task report for the
    full status-line transcript.
  - Suite: 794 tests (783 at the start of Task 5; +11 for `scripts/users.py` in `tests/test_users_cli.py`).

## Open items

- **Hunter cutover** (spec §11) is explicitly out of scope for this plan — a separate, later plan covers
  pointing House Hunter's `/analyze` page at this service instead of its own embedded analysis code.
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
