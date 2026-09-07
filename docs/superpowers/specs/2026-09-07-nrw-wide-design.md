# Tier 3 — NRW-weite Abdeckung: Design

**Date:** 2026-09-07 · **Status:** approved by the owner ("please execute this") · **Plan:** `docs/superpowers/plans/2026-09-07-nrw-wide.md`

## 1. Problem

`Am Käferberg 12, 53127 Bonn` (50.7160 N, 7.0748 E) returns 28 cards of which three are `empty` and three more carry
null extension blocks, although the underlying data exists statewide. Verified live on 2026-09-07:

| Card | Today at Bonn | Cause |
|---|---|---|
| `zensus` | empty | grid cropped to the Essen/Bochum window (6.85–7.40 E / 51.33–51.56 N) by `scripts/build_zensus_grid.py` |
| `unfaelle` | empty | same window in `scripts/build_unfallatlas.py` |
| `ladesaeulen` | empty | same window in `scripts/build_ladesaeulen.py` |
| `bergbau.berechtigungen` | null | same window in `scripts/build_bergbauberechtigungen.py` (the shapefile is statewide, 5,361 polygons) |
| `bergbau.bodenbewegung` | null | only EGMS tile E41N31 shipped; Bonn is in E41N30 |
| `air_quality.longterm.grid` | null | EEA 1 km grid cropped to the window |
| `denkmal` | empty ("außerhalb des RVR-Verbandsgebiets") | RVR WFS only |
| `gfnp` | found=false | GFNP exists only for the six Ruhr cities |
| `planning_essen`, `planning_bochum` | ok, `items` null | city services queried for a point outside their city — misleading "keine Bauleitpläne" |

Not coverage: the `boris` timeout at Bonn was transient (retries answer in 180 ms), the `infrastruktur` IED timeout likewise.
`noise` already samples the state layers `FLG_DEN/FLG_NGT` (Flugverkehr) and `IND_*` statewide (`redat/sources/noise.py`
`SOURCES`), so Fluglärm needs no change; `noise_extra` (Essen Fluglärm detail, Ruhige Gebiete) stays a city extra.

## 2. Goal

Every card that has a statewide source answers for any NRW address; cards that are city-only by nature say so
explicitly instead of showing a hollow "nothing found". Memory and repo size stay bounded: the process must not grow by
more than ~100 MB resident, no single committed data file above ~20 MB.

## 3. Shared geometry: `redat/core/nrw.py`

```python
NRW_BBOX_WGS84 = (5.753, 50.242, 9.589, 52.619)      # lon_min, lat_min, lon_max, lat_max (= starkregen.NRW_BBOX)
def in_bbox(lat, lon, bbox) -> bool
def bbox_3035(bbox_wgs84) -> (xmin, ymin, xmax, ymax)   # 6 sample points (4 corners + N/S mid) → min/max, like the build scripts
def bbox_25832(bbox_wgs84) -> (xmin, ymin, xmax, ymax)
```

Every statewide build script imports `NRW_BBOX_WGS84` (`sys.path.insert(0, str(ROOT))` — the scripts already define
`ROOT`). `starkregen.NRW_BBOX` is replaced by the import. Measured NRW bbox in EPSG:3035 (6 sample points):
x 4 018 209 … 4 293 164, y 3 014 508 … 3 287 273 → 2 750 × 2 728 cells of 100 m.

## 4. Storage formats (measured 2026-09-07 with the real inputs)

The current JSON dict-of-lists costs ~600 B per Zensus cell resident (43,376 cells → 26 MB), ~270 B per accident row,
~110 B per EGMS cell. Statewide that would be several hundred MB, so the three large grids move to NumPy arrays saved
with `np.savez_compressed`; the three small ones stay gzipped JSON.

| Data | Statewide size | Format | Resident |
|---|---|---|---|
| Zensus 2022, NRW | 796,280 cells with data (785,062 populated) — 16.9 MB file | `zensus_2022_nrw.npz`: `keys` int64 sorted (`(x//100)*1_000_000 + y//100`), `values` int16 `[n, 40]` (scaled, sentinel −32768), `fields`, `scales`, `meta` JSON | 70 MB |
| Unfallatlas 2020–2025, NRW | 418,359 rows — 2.6 MB file | `unfallatlas_2020_2025_nrw.npz`: `lat`/`lon` float64 sorted by lat, `attrs` int16 `[n, 9]`, `fields`, `meta` | 17 MB |
| EGMS 2020–2024, NRW | 2 728 rows × 2 750 cols, 1,717,178 measured cells — 3.3 MB file | `egms_vertical_velocity_nrw.npz`: `v` int16 (mm/a × 100, sentinel −32768), `meta` {x0, y1, cell_m, years, scale} | 15 MB |
| EEA AQ 2023, NRW | 276 × 274 × 4 | `eea_aq_grid_2023_nrw.json.gz` (same layout as today, gzipped) | 210 KB file |
| Ladesäulen, NRW | ≈ 25k rows | `ladesaeulen_nrw.json.gz`, rows sorted by lat | < 5 MB |
| Bergbauberechtigungen, NRW | 5,361 polygons | `bergbauberechtigungen_nrw.geojson.gz` + STRtree at load | < 10 MB |

Zensus scale factors (int16 keeps two decimals where the source has them): `alter ×10, u18 ×10, ab65 ×10,
hh_groesse ×100, wohnfl_je_bew ×10, eigentuemer ×10, leerstand ×10, miete_qm ×100`, all counts ×1. Maximum observed
values in the window (`einwohner` 499, `hz_fern` 355, `miete_qm` 22.87) leave int16 headroom; the build asserts
`max < 32768` per field.

Lookups: Zensus and EGMS index by cell arithmetic (`np.searchsorted` on the sorted keys; row/col into the raster);
Unfallatlas and Ladesäulen pre-filter a latitude band with `np.searchsorted`/`bisect` before computing distances;
Bergbauberechtigungen query a `shapely.STRtree` built once in the cached `_geoms()`.

The old window files (`zensus_2022_grid.json.gz`, `unfallatlas_2020_2025.json.gz`, `egms_vertical_velocity.json.gz`,
`eea_aq_grid_2023.json`, `ladesaeulen.json.gz`, `bergbauberechtigungen.geojson.gz`) are deleted; the loaders read only
the new names. Tests keep monkeypatching `_load()`; its return shape becomes a dict of NumPy arrays (see the plan).

## 5. Statewide live sources

### 5.1 Denkmal — INSPIRE Denkmal WFS des Landes (`redat/sources/denkmal_nrw.py`)

`https://www.wfs.nrw.de/wfs/wfs_nw_inspire-denkmal`, WFS 2.0, GML 3.2 only (no JSON output), DefaultCRS EPSG:4258 but
the geometries are served in `urn:ogc:def:crs:EPSG::25832`; a `BBOX=xmin,ymin,xmax,ymax,urn:ogc:def:crs:EPSG::25832`
filter works (WGS84 bboxes silently match nothing). Typenames: `ps:ProtectedSites_Cultural_{Point,Multipoint,Line,Surface}`
(32,456 points / 15,852 surfaces statewide) and `ps:ProtectedSites_Archaeological_{…}` (Bodendenkmäler). Feature
elements: `ps:nummer` (`DE_05314000_A_00749` — the same `DE_<AGS>_<A|B|C|D>_<nr>` scheme the RVR uses), `ps:sitename`,
`ps:designation` ("Baudenkmal"), `ps:legalfoundationdate` (ISO date), geometry under `ps:SHAPE` (`gml:Point/gml:pos` or
`gml:MultiSurface/…/gml:posList`). Coverage is per municipality and voluntary: Bonn centre has 402 points within 500 m,
Essen only surfaces, Köln nothing (Köln runs its own WFS). Verified 2026-09-07.

Integration: `denkmal.get_denkmal(lat, lon)` keeps the RVR path inside `RVR_BBOX` and delegates to
`denkmal_nrw.get_denkmal_nrw(lat, lon)` outside it. The statewide function returns the **same dict** (`radius_m, items,
counts, on_site, authority, rating, rating_color`) plus `"source": "nrw"` and a `hinweis` string
("Landesweiter INSPIRE-Dienst; Kommunen liefern freiwillig — fehlende Einträge bedeuten nicht 'kein Denkmal'.").
`kind` comes from the id letter (A/B/C/D); archaeological typenames force `B`. `authority` is `None` statewide (the
feature carries no municipality name). `denkmal` `cache_version` 1 → 2.

### 5.2 Bauleitplanung NRW — OGC API Features (`redat/sources/planning_nrw.py`, new card `planning_nrw`)

`https://ogc-api.nrw.de/inspire-lu-bplan/v1/collections/spatialplan/items?f=json&bbox=<lon,lat,lon,lat>&limit=50`
(the un-versioned path 307-redirects; `Accept: application/json`). 82,140 plans statewide as GeoJSON MultiPolygons
(CRS84). Properties: `officialTitle`, `planTypeName.title` (Bebauungsplan / Flächennutzungsplan / …),
`levelOfSpatialPlan.title` (lokal / sublokal), `processStepGeneral.title` ("rechtsverbindlich oder in Kraft (In Kraft
getreten)" …), `validFrom` (`1900-01-01` = unknown), `officialDocument` (PDF/portal link), `texturl`, `kommune`, `gkz`,
`nr`, `planart.title`, `verfahren.title`. Coverage is voluntary: Essen 21 plans in a 1 km bbox, Bochum 52, Bonn only
its FNP. Verified 2026-09-07.

Card: key `planning_nrw`, title "Bauleitplanung NRW", tier `parcel`, timeout 30 s, registered directly after
`planning_bochum`; it always runs (also in Essen/Bochum — the city cards stay the richer view). Data shape is the one
`_planning.html` already renders: `{"found", "items": [{"category", "name", "link"}], "errors": {}, "hinweis"}`,
`category` = `planTypeName.title`, `name` = `officialTitle` + " (" + `processStepGeneral.title` short form + ", ab
<validFrom>" + ")", `link` = `officialDocument` or `texturl`. Only plans whose polygon **contains** the point are
listed (bbox ±25 m is only the server filter). `hinweis` = "Landesweiter Dienst (INSPIRE); Lieferung durch die Kommunen
freiwillig — nicht flächendeckend." rendered as a footnote in both partials.

### 5.3 Regionalplan — WMS des Landes (`redat/report/regionalplan_map.py`, PDF figure)

`https://www.wms.nrw.de/wms/wms_nw_regionalplan`, one raster layer `regionalplan` (1:50,000, all six planning regions
plus the RFNP), not queryable (no GetFeatureInfo), `GetLegendGraphic` returns a 959 × 1918 px poster with ~120 entries
→ image only, legend linked, not embedded. Figure: 2 km window (`WINDOW_M = 2000`, 480 × 360 px, 500 m scale bar,
title "Regionalplan (1:50.000)"), fetched concurrently with the other figures in `render_pdf`, rendered in
`report/_gfnp.html` for every address (also in the Ruhr, where the GFNP text stays above it). Legend link:
`https://www.wms.nrw.de/wms/wms_nw_regionalplan?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetLegendGraphic&LAYER=regionalplan&FORMAT=image/png&SLD_VERSION=1.1.0`.

`gfnp` gets an RVR bbox gate (`denkmal.RVR_BBOX`): outside it the Essen ArcGIS query is skipped and the card returns
`{"found": false, "rvr": false, "hinweis": "Der GFNP gilt nur für Bochum, Essen, Gelsenkirchen, Herne, Mülheim und
Oberhausen. Für andere Orte zeigt der PDF-Bericht den Regionalplan-Ausschnitt."}`; inside it `rvr: true`. `gfnp`
`cache_version` 1 → 2.

## 6. City-only cards say so

| Card | Gate | Message (`Empty`) |
|---|---|---|
| `planning_essen` | outside `baugrund.ESSEN_BBOX` | "Bauleitplanung Essen: nur für Adressen in Essen verfügbar" |
| `planning_bochum` | outside `schulen.BOCHUM_BBOX` | "Bauleitplanung Bochum: nur für Adressen in Bochum verfügbar" |
| `zensus`, `unfaelle`, `ladesaeulen` | outside NRW | messages say "außerhalb Nordrhein-Westfalens" instead of "außerhalb Essen/Bochum" |
| `denkmal` | outside NRW | "Kein Denkmal-Datensatz (außerhalb Nordrhein-Westfalens)" |

`baulasten` (Essen), `kf_gutachten` (Essen), `grundschulbezirk` (Bochum) and `noise_extra` already gate by bbox and
render nothing outside; unchanged.

## 7. Non-goals

- Köln's own Denkmal WFS, Wuppertal's open-data list etc. — no per-city sources beyond Essen/Bochum.
- Hebesätze (Regionaldatenbank registration), Altlasten (city requests pending), Sozialatlas, Wahlbezirke — unchanged.
- Replacing `planning_essen`/`planning_bochum` by the statewide API — the city services carry more (Veränderungssperren,
  Satzungen, Sanierungsgebiete).

## 8. Cache versions after this tier

`bergbau` 3 → 4 (EGMS raster + statewide Berechtigungen), `zensus` 1 → 2, `unfaelle` 1 → 2, `ladesaeulen` 1 → 2,
`air_quality` → +1, `denkmal` 1 → 2, `gfnp` 1 → 2, new `planning_nrw` 1. Cards: 28. Static grids: 6 statewide files
plus `schulen_nrw.json.gz`.
