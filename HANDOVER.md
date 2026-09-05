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
- **BORIS timeout:** `boris` (Bodenrichtwert) makes no HTTP call at all — it reads local shapefiles with
  geopandas in a `multiprocessing.Process` capped at a hard 12 s (`redat/sources/boris.py`), well inside
  the card's 25 s section timeout. A slow cold-cache shapefile read (e.g. after page-cache eviction) can
  still trip that 12 s cap, in which case the subprocess is killed and the card returns
  `status: error`, `message: "BORIS timeout"` — a genuine but transient section error, not a WMS
  slowdown. A retry of the same address usually succeeds — observed live during Task 10 verification
  (first Brückstraße 1 run: `boris` errored at 12 s; retried run: `boris ok` in 295 ms).
- **Cache semantics:** `ok`/`empty` envelopes are cached for `REDAT_CACHE_TTL_S` per
  `(key, lat₄, lon₄, plot, force)` — by `/analyze` and `/section/{key}` alike (both routes consult
  `SectionCache` via the shared `core.analyze.cached_section` helper); `error`/`gated` are never cached,
  so a transient BORIS timeout self-heals without manual cache clearing. A `destinations` param
  suppresses caching for the two sections it can affect (`commute`, `oepnv`) and nothing else — the
  other 18 cards are cached as usual even on a request that also carries `destinations`.

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
  `map-utils.js`).

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
- **`SectionCache` has no size cap** — only lazy expiry (an entry is dropped on read after its TTL, never
  proactively). Not a practical risk at LAN scale with a 6 h default TTL, but there is no ceiling at all.
  Fix: a `max_entries` cap with oldest-expiry eviction on `put`, or a periodic sweep.
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
