# HANDOVER

## Status

Live on `:8200` since 2026-09-05, running via `docker compose` on the same host as House Hunter
(`/srv/nrw-redat`, LAN address `http://192.168.188.64:8200`). LAN-open by default (`REDAT_API_KEY`
unset). 439 tests pass hermetically; the Docker build's `test` stage re-runs the full suite and refuses
to produce an image on a red run.

## Deploy runbook

**First deploy:**

```bash
cd /srv/nrw-redat
cp .env.example .env    # GEOAPIFY_API_KEY from /srv/house-hunter/.env, REDAT_PUBLIC_URL=http://192.168.188.64:8200
mkdir -p data           # bind mount target; data/source/{boris,flood,elections} must be rsynced in separately (see below)
docker compose up -d --build
curl -s localhost:8200/healthz
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
- **BORIS timeout:** the `boris` (Bodenrichtwert) card has a 25 s timeout; the BORIS NRW WMS is
  occasionally slow enough to trip it (`status: error`, `message: "BORIS timeout"`), which then shows up
  as a genuine but transient section error. A retry of the same address usually succeeds — observed live
  during Task 10 verification (first Brückstraße 1 run: `boris` errored at 25 s; retried run: `boris ok`
  in 295 ms).
- **Cache semantics:** `SectionCache` only stores `ok`/`empty` envelopes — `error`/`gated` are always
  recomputed on the next request, so a transient BORIS timeout self-heals without manual cache clearing.
  Any `/analyze` or `/section` call carrying a `destinations` param bypasses the cache entirely (custom
  commute destinations are per-request and must not pollute or be served from another caller's cached
  result).

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

## Open items

- **Hunter cutover** (spec §11) is explicitly out of scope for this plan — a separate, later plan covers
  pointing House Hunter's `/analyze` page at this service instead of its own embedded analysis code.
- The API-key-vs-website gap above (same-origin cookie or proxy auth) is unresolved; low priority while
  the service stays LAN-open.
