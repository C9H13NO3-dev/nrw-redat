# NRW-REDAT

**Real Estate Data Aggregation Tool** — a standalone Standortanalyse ("location analysis") service for
North Rhine-Westphalia. Given any NRW address it geocodes it, runs 29 data cards concurrently against
public open geodata (Land NRW, Bund, EU, RVR and the cities of Essen and Bochum), and renders the result as
a website page, a JSON payload, or a formatted A4 PDF — each run gets a permanent, shareable permalink. It
started as the analysis engine inside the House Hunter project and was extracted into its own FastAPI
service so it can be used for any address, not just scraped listings.

## Cards

Tier `parcel` cards need a house-number-exact address (or `force=1`); `area` cards also run on a street or
district. Every card fetches live except where a committed grid is named (see "Static grids in the repo").

**Grundstück, Wert & Planungsrecht**

| Card | What it shows | Source |
|---|---|---|
| Flurstück & Gebäude (`flurstueck`, parcel) | Parcel geometry and Flurstück data; in Essen also Baulasten | Geobasis NRW ALKIS (WFS) · Stadt Essen Baulasteninformation |
| Bodenrichtwert (`boris`, parcel) | Bodenrichtwert zone at the point, incl. the plot value | BORIS NRW, local GeoPackage (`data/source/boris`) |
| Bodenrichtwert-Trend (`boris_trend`, parcel) | The same zone across all historic Stichtage 2011–2025 | BORIS NRW |
| Immobilienrichtwerte (`irw`, parcel) | Sub-market values per m² Wohnfläche (Normobjekt) | BORIS NRW `wms_nw_irw` |
| Flächennutzungsplan & Regionalplan (`gfnp`, parcel) | GFNP designation in the six Ruhr core cities; a Regionalplan 1:50.000 panel in the PDF everywhere | geo.essen.de GFNP · Regionalplan NRW WMS |
| Bauleitplanung Essen (`planning_essen`, parcel) | B-Pläne, Satzungen, Sanierungsgebiete — Essen only | geo.essen.de ArcGIS |
| Bauleitplanung Bochum (`planning_bochum`, parcel) | B-Pläne and Stadterneuerung — Bochum only | RVR INSPIRE WMS · Stadt Bochum |
| Bauleitplanung NRW (`planning_nrw`, parcel) | Bebauungs-/Flächennutzungspläne containing the point, statewide; municipal delivery is voluntary, so an empty answer is not conclusive | Land NRW INSPIRE OGC API (`ogc-api.nrw.de`) |
| Denkmalschutz (`denkmal`, parcel) | Listed monuments on and within 300 m of the plot, Umgebungsschutz rating | RVR Denkmal-WFS in the Ruhr · IT.NRW INSPIRE Denkmal-WFS statewide |
| Energie (`energie`, parcel) | Roof PV potential, shallow geothermal suitability, Wärmeplanung (Essen/Bochum) | LANUK Solarkataster · GD NRW Geothermie · city Wärmeplanung |

**Risiken & Umwelt**

| Card | What it shows | Source |
|---|---|---|
| Hochwasserrisiko (`flood`, parcel) | HQhäufig / HQ100 / HQextrem hits and distances, Überschwemmungsgebiete (§ 78 WHG) | Land NRW HWRM (local GeoPackage) · ÜSG WMS |
| Starkregen & Gelände (`starkregen`, parcel) | Pluvial flood depth classes, plus terrain height, Hang-/Tieflage and slope from the DGM1 | BKG Hinweiskarte Starkregen · Geobasis NRW DGM1 WCS |
| Lärm (`noise`, area) | Loudest L_DEN / L_Night band within 25 m for road, rail, industry and aircraft; Essen Fluglärm detail and Ruhige Gebiete (Essen/Bochum) | Umgebungslärmkartierung NRW 2022 (WMS) · city layers |
| Bergbau & Untergrund (`bergbau`, area) | "NRW von unten" mining hazards per 500 m square, mining rights at the point, EGMS ground motion 2020–2024 (mm/a) | GD NRW · BezReg Arnsberg Bergbauberechtigungen (grid) · Copernicus EGMS (grid) |
| Baugrund & Versickerung (`baugrund`, area) | Soil type, kf value, infiltration suitability, Erdwärme classes; Essen kf-Werte from building applications | GD NRW BK50 (WMS) · Stadt Essen |
| Radon (`radon`, area) | Soil-air radon (kBq/m³, 1 km prognosis) and Radonpotenzial | Bundesamt für Strahlenschutz (WFS) |
| Schutzgebiete (`schutzgebiete`, area) | NSG/LSG/FFH/VSG/Naturpark/Biotope within 500 m, Wasserschutzgebiete | LANUV LINFOS · WSG NRW |
| Luftqualität (`air_quality`, area) | Annual-mean NO₂/PM/O₃ on the 1 km grid, nearest samplers, live station index | EEA 1 km grid 2023 (grid) · UBA/LANUV · Sensor.Community · CAMS |
| Hochspannung, Leitungen & Industrie (`infrastruktur`, area) | Power lines, substations, wind turbines, masts, pipelines, IED sites nearby | OpenStreetMap (Overpass) · EEA Industrial Emissions Portal |

**Nachbarschaft & Versorgung**

| Card | What it shows | Source |
|---|---|---|
| Entfernungen (`amenities`, area) | Nearest supermarket, pharmacy, doctor, playground … with distances | Geoapify Places |
| Schulen & Sozialindex (`schulen`, area) | Nearest schools per type with the Schulministerium Sozialindex; Bochum Grundschulbezirk | Schulministerium NRW · Geobasis NRW (grid) · Stadt Bochum |
| Verkehrsunfälle (`unfaelle`, area) | Injury accidents within 300 m, 2020–2025, by year, severity, type and participants | Unfallatlas (grid, statewide) |
| ÖPNV-Erreichbarkeit (`oepnv`, area) | Stops, lines, headways and trips to the Hauptbahnhöfe | VRR EFA |
| Fahrzeiten (`commute`, area) | Car travel times to configured destinations | Geoapify Routing |
| Nachbarschaft (`zensus`, area) | Population, age, ownership, vacancy, rent, building age/heating/energy mix for the 100 m cell and its 5×5 surroundings | Destatis Zensus 2022 (grid, statewide) |
| Stadtklima (`stadtklima`, area) | Klimatop, gefühlte Temperatur (PET) and night air temperature for a typical and an extreme summer day, LANUV model | LANUV Klimaanalyse NRW 2026 (WMS GetFeatureInfo) |
| E-Ladepunkte (`ladesaeulen`, area) | Public chargers within 1 km, nearest five, rating | BNetzA Ladesäulenregister (grid, statewide) |
| Breitband & Mobilfunk (`breitband`, area) | Fixed-line bandwidth classes and 5G coverage for the 100 m cell | BNetzA Breitbandatlas |
| Bundestagswahl (`btw`, area) | Zweitstimmen profile of the Wahlkreis | Die Bundeswahlleiterin (local shapes + live CSV) |

Coverage: every card with a statewide source answers for any NRW address. The city-only extras (Baulasten
and kf-Werte in Essen, the two municipal planning cards, Ruhige Gebiete and Essen Fluglärm detail,
Bochum Grundschulbezirke, Wärmeplanung) either render nothing or say "nur für Adressen in Essen/Bochum
verfügbar" elsewhere; the GFNP applies to the six Ruhr core cities. `redat/core/nrw.py` holds the
NRW/RVR/Essen/Bochum bounding boxes every statewide source and gate uses.

The PDF adds figures the website does not have: Lärm maps (day/night), "Der Ort im Wandel" (historic maps
1840s/1900s/1950s/today on the Flurstück page), "Grün und Hitze" on the Nachbarschaft page (RVR canopy and
surface-temperature panels in the Ruhr; a Copernicus HRL Tree Cover Density canopy panel and a Klimaanalyse
NRW PET class map with legend elsewhere in NRW), the Regionalplan panel on the GFNP page, and the
Bodenrichtwert trend chart.

Surfaces: a website (`/`, permalinks at `/a/{id}`, a source index at `/quellen`), a versioned JSON+PDF
API under `/api/v1` (OpenAPI docs at `/docs`), and `GET /healthz` for monitoring/container health.

## Quick start

```bash
git clone <this repo> nrw-redat && cd nrw-redat
cp .env.example .env            # fill in GEOAPIFY_API_KEY (see below)
docker compose up -d --build    # builds on :8200 — the build stage runs pytest; a red suite aborts the build
curl -s localhost:8200/healthz  # {"status":"ok","version":"1.0.0","chromium":true,"sources_loaded":29,"cache":{"entries":…,"bytes":…,"expired":…}}
```

`.env` (git-ignored, copy from `.env.example`):

| Key | Meaning |
|---|---|
| `GEOAPIFY_API_KEY` | Required — geocoding, autocomplete, amenities, commute. Same key as House Hunter's `.env`. |
| `REDAT_API_KEY` | Optional. When set, `/api/v1/*` also accepts an `X-Api-Key` header as an alternative to a session cookie, for machine clients. Works alongside sessions — the website logs in with its own session cookie regardless of whether this is set. |
| `REDAT_DATA_DIR` | Where `redat.db` and `source/{boris,flood,elections}` live. `/data` inside the container (bind-mounted from `./data` by `docker-compose.yml`). |
| `REDAT_CACHE_TTL_S` | Default cache TTL in seconds for cards without their own (default 2592000 = 30 d, `config/settings.yaml`). Per-card TTLs: `cache_ttls` in settings.yaml. |
| `REDAT_CACHE_MAX_ENTRIES` / `REDAT_CACHE_MAX_BYTES` | Cache bounds (defaults 100 000 entries / 256 MiB). Expired rows are evicted first, then least recently used. |
| `REDAT_PUBLIC_URL` | Base URL used to build permalinks **and invite links**, and it decides whether the session/CSRF cookies carry `Secure` (`Settings.cookie_secure` is true iff this starts with `https://`). Set it to the public HTTPS URL in production (e.g. `https://redat.example.com`) — an `http://` value here means every "Neuer Einladungslink" is unreachable off the LAN and the session cookie loses `Secure` on the public origin. |
| `REDAT_LOG_LEVEL` | Python logging level. |
| `REDAT_BOOTSTRAP_ADMIN_PASSWORD` | First start only: when the `users` table is empty, creates the user `admin` with this password. Change it after the first login. See "Zugang & Benutzer" below. |
| `REDAT_SESSION_DAYS` | Session lifetime in days (sliding expiry). Default 30. |
| `REDAT_TRUSTED_PROXIES` | Comma-separated CIDRs/IPs whose `X-Forwarded-For` is trusted for `client_ip()` (login throttle key, audit-log `ip` column). Empty/unset uses the built-in default (Docker networks + RFC1918); a public peer is never trusted regardless. Only matters if the app is reachable other than through Traefik. |

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

The `redat/data/` package files (the static grids below, plus the letsencrypt intermediate cert for the
Breitbandatlas host) **are** committed and shipped in the image — a different directory from the host
bind mount above.

### Static grids in the repo (`redat/data/`)

Gzipped JSON and NumPy `.npz` extracts that ship with the code (no download at deploy time):

| File | Built by | Source | Refresh |
|---|---|---|---|
| `zensus_2022_nrw.npz` | `scripts/build_zensus_grid.py --src …` | Destatis Zensus 2022 Gitterdaten | one-off |
| `eea_aq_grid_2023_nrw.json.gz` | `scripts/build_eea_aq_grid.py --src …` | EEA 1 km air-quality maps | yearly |
| `schulen_nrw.json.gz` | `scripts/build_schulen.py --shape … --sozialindex …` | opengeodata Schulstandorte NRW + Schulministerium Schulliste (Sozialindex) | each Schuljahr (autumn) |
| `unfallatlas_2020_2025_nrw.npz` | `scripts/build_unfallatlas.py --src …` | Unfallatlas CSV zips (opengeodata.nrw.de) | yearly (July), extend `YEARS` |
| `bergbauberechtigungen_nrw.geojson.gz` | `scripts/build_bergbauberechtigungen.py --shape …` | Bergbauberechtigungen NRW shapefile, Bezirksregierung Arnsberg (opengeodata.nrw.de) | a few times a year |
| `ladesaeulen_nrw.json.gz` | `scripts/build_ladesaeulen.py --csv …` | BNetzA Ladesäulenregister CSV (CC BY 4.0) | monthly |
| `egms_vertical_velocity_nrw.npz` | `scripts/build_egms.py --src …` (nine tiles, each downloaded via `~/.config/nrw-redat/egms_download.py`, mosaicked) | Copernicus EGMS L3 Ortho vertical velocity (EU-Login / insar-api) | yearly EGMS release |

The build scripts' module docstrings carry the download URLs and the exact commands.

Coverage: all seven grids are statewide (NRW bbox `redat/core/nrw.py`). They are loaded once at start-up
(`redat/core/warmup.py`) and stay resident: Zensus 75 MB, Unfallatlas 14 MB, EGMS 14 MB, Ladesäulen 11 MB,
EEA-Luftqualität 11 MB, Bergbauberechtigungen ~5 MB, Schulen ~1 MB — roughly 130 MB in total.

## Zugang & Benutzer

The website is app-native login, not a separate reverse-proxy auth layer. There is no public sign-up:
an admin creates an invite link from `/admin` ("Neuer Einladungslink"), the link is shown once and lets
its recipient set a username and password at `/invite/{token}`. Two roles: `user` (the analyzer, and the
permalinks it creates) and `admin` (also sees `/admin`).

Sessions are server-side (a row in `redat.db`, not a JWT), 30 days by default (`REDAT_SESSION_DAYS`,
sliding — every request bumps the expiry, at most once an hour) and end via the "Abmelden" button, "alle
anderen Geräte abmelden" on `/konto`, or by disabling the user.

`/admin` shows KPI tiles (active/total users, analyses 7 d/30 d/total, PDF exports, permalink views over
30 d), a 30-day bar chart, a per-user table (role, status, analyses, PDFs, last active, with
deaktivieren/aktivieren/Passwort-Link/löschen actions — an admin cannot disable or delete themselves) and
the most recent 50 usage events (who did what, when, with the address for an analysis). The login page
says so in one sentence: analyses, addresses and PDF exports are recorded per account and are visible to
the administrator. No e-mail addresses are collected and there is no self-service password reset — an
admin issues a reset link from `/admin`.

`X-Api-Key` stays as the credential for machine clients against `/api/v1/*` and now works **alongside**
sessions rather than instead of them: the website authenticates with its own session cookie regardless of
whether `REDAT_API_KEY` is set, so turning the key on no longer breaks the website's own fetches.

**Permalinks stay public.** Anyone holding an `/a/{run_id}` link (or its `report.pdf`) can open it without
logging in — that's the point of sharing a result — as is `/quellen` (the sources index, which carries no
data). Every other page and every other `/api/v1/*` route needs a session or an API key; a website route
without one redirects to `/login?next=…`, an API route answers `401`.

**Bootstrap.** On first start, while the `users` table is still empty, setting
`REDAT_BOOTSTRAP_ADMIN_PASSWORD` in `.env` creates the user `admin` with that password — change it on
`/konto` after the first login. Leave it unset and nobody is created automatically; use the CLI instead
(also the way back in if you get locked out):

```bash
docker compose exec redat python scripts/users.py list
docker compose exec redat python scripts/users.py create-admin --username admin
docker compose exec redat python scripts/users.py reset --username admin
docker compose exec redat python scripts/users.py disable --username anna
docker compose exec redat python scripts/users.py enable --username anna
docker compose exec redat python scripts/users.py prune-events --days 180
```

`reset` also logs out every one of the user's existing sessions (same as a password reset through the
admin page) — resetting your own password this way ends your current browser session too. `create-admin`/
`reset` read the new password from `--password-env VAR` (for scripting) or prompt twice interactively;
the script exits 1 with a message on stderr for an unknown user (`reset`/`disable`/
`enable`), an invalid/taken username (`create-admin`), or a password-policy violation.

## API overview (`/api/v1`)

| Method & path | What it does |
|---|---|
| `GET /api/v1/sections` | The card manifest (key, title, icon, tier, timeout, source) — 29 entries. |
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
- An `ok` envelope whose `data` carries a truthy top-level `*_error` sibling (a secondary source merged
  onto an otherwise-successful card, e.g. `gelaende_error`, `berechtigungen_error`) is not cached either —
  `SectionCache.put` is the single choke point for this, so a transient secondary-source failure can never
  be pinned in the cache for the card's full TTL. Corollary: a *permanent* gate/hint (one that is expected
  to stay truthy forever for a given point, e.g. `bodenbewegung_hinweis` when EGMS has no cell nearby) must
  not use the `_error` suffix, or the card would never be cacheable at all. The same rule applies to a
  non-empty top-level `errors` dict (per-layer/per-source failures collected by a card, e.g. `stadtklima`'s
  five WMS layers): a *permanent* failure must never be recorded there either, or the card would never be
  cacheable again.
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
.venv/bin/python -m pytest -q       # 794 tests, hermetic, ~10s

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
- Source tiers: [`docs/superpowers/specs/`](docs/superpowers/specs/) (Tier 1 sources, Tier 2 sources, Tier 3 NRW-weit) with their implementation plans in [`docs/superpowers/plans/`](docs/superpowers/plans/)
- Status, deploy runbook, known limitations, work log: [`HANDOVER.md`](HANDOVER.md)
