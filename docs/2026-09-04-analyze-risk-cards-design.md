# Analyze page — Starkregen, Bergbau, Zensus cards — design

**Date:** 2026-09-04
**Scope:** three new sections for `/analyze`, plugged into the section registry from the analyze rework (`docs/superpowers/specs/2026-09-04-analyze-rework-design.md`). No changes to the envelope, routes, or frontend component — each section is a service module, a `fetch` normaliser, a partial, and tests. A follow-up batch (Energie: PV/Erdwärme/Fernwärme) is queued separately.

## 1. Why these three

Live-probed 2026-09-04. Each answers a question a buyer in Essen/Bochum actually asks and that no existing card covers:

| Card | Question | Source (verified) |
|---|---|---|
| **Starkregen** | Does water pool on/around this house in a cloudburst? The existing flood card is river flooding only; most Ruhrgebiet water damage is pluvial. | BKG *Hinweiskarte Starkregengefahren* WMS `https://sgx.geodatenzentrum.de/wms_starkregen` — NRW layers `nw_tiefe_agw` / `nw_tiefe_extrem` (water depth, 100-year KOSTRA event vs. 90 mm/h extreme) and `nw_geschw_agw` / `nw_geschw_extrem` (flow velocity). 1 m hydraulic model, buildings blanked. Licence DL-DE-BY 2.0. |
| **Bergbau** | Is there shallow mining / are there shafts or sinkholes under or next to it? A Ruhrgebiet-specific due-diligence item that every notary asks about. | GD NRW "NRW von unten" Bürgerversion, ArcGIS `https://www.gis.nrw.de/arcgis/rest/services/gd_gdu/buerger_utm/MapServer`. Layer 22 *Planquadrat* holds per-500 m-cell counts/flags; layers 5–21 are one schematic symbol per cell (anonymised). |
| **Zensus 2022** | Who lives here, in what kind of housing? Owner share, vacancy, building age, heating mix, age structure — the "neighbourhood character" numbers. | Destatis Zensus 2022 100 m Gitterdaten (CSV, EPSG:3035). 13 datasets, cropped offline to the Essen/Bochum window and shipped in-repo, like the EEA air-quality grid. |

## 2. Decisions taken

- **Starkregen method — legend-colour counting on a GetMap tile**, not GetFeatureInfo. GFI answers one pixel; a 100×100 px tile over ±50 m answers "what is the worst depth within 50 m and how much of the surroundings is wet", which is the actual question (water in the street in front of the house counts). The legend RGBs are fixed by the service style and were extracted from `GetLegendGraphic`. BKG only — Essen's own 3-class Starkregen map is coarser and Bochum has none; the city maps are linked in the footnote.
- **Bergbau — one query on the Planquadrat layer**, not eleven point-layer queries. The polygon carries every count and flag; the point layers are only symbols. Wording must say "im 500 m-Planquadrat", never "auf dem Grundstück" — the Bürgerversion is anonymised by design; the formal *Bergbauauskunft* comes from Bezirksregierung Arnsberg / RAG and the card says so.
- **Zensus — offline grid, sparse, gzipped.** The bbox `(6.85, 51.33, 7.40, 51.56)` holds ~35k populated 100 m cells × ~40 values; gzipped JSON is ~1–2 MB and loads in well under a second with `lru_cache`. Cells only, keyed `"{x}_{y}"` by EPSG:3035 centre; a value is `None` when Destatis suppressed it (`–`) — the `KLAMMERN` (low reliability) marker is dropped, the value is kept. The lookup returns the 100 m cell **and** a 5×5-cell (500 m) aggregate because single cells are frequently suppressed.
- **Tiers:** `starkregen` is **parcel** (1 m model — a street-centroid geocode is meaningless, same as `flood`); `bergbau` and `zensus` are **area** (500 m cell / 100 m cell with 500 m aggregate).
- **Order:** `starkregen` after `flood`; `bergbau` after `noise`; `zensus` after `amenities`.

## 3. Services

### 3.1 `backend/starkregen_service.py`

```python
WMS_URL = "https://sgx.geodatenzentrum.de/wms_starkregen"
DEPTH_CLASSES = [  # (rgb, label, lower edge cm) — transparent white = < 10 cm
    ((255, 255, 255), "< 10 cm", 0), ((204, 236, 255), "10–30 cm", 10), ((153, 204, 255), "30–50 cm", 30),
    ((110, 153, 255), "50–100 cm", 50), ((61, 102, 255), "1–2 m", 100), ((0, 51, 204), "2–4 m", 200), ((8, 48, 107), "> 4 m", 400)]
VELOCITY_CLASSES = [((255, 255, 255), "< 0,2 m/s", 0.0), ((255, 255, 178), "0,2–0,5 m/s", 0.2), ((254, 204, 92), "0,5–1 m/s", 0.5),
                    ((253, 141, 60), "1–2 m/s", 1.0), ((227, 26, 28), "> 2 m/s", 2.0)]
BUILDING_RGBA = (0, 0, 0, 0)
```

`get_starkregen(lat, lon, half_m=50, px=100) -> dict` fetches four tiles in a `ThreadPoolExecutor` (`_get_tile(layer, lat, lon, half_m, px)` is the HTTP call and monkeypatch point; returns a PIL RGBA image) and counts pixels by exact RGB (alpha 0 + white = lowest class; alpha 0 + black = building/no-data; any other colour = ignored). Per scenario:

```python
{"max": {"label": "30–50 cm", "cm": 30}, "shares": {"< 10 cm": 0.71, "10–30 cm": 0.22, "30–50 cm": 0.07},
 "wet_share": 0.29,          # share of non-building pixels ≥ 10 cm
 "velocity_max": {"label": "0,5–1 m/s", "mps": 0.5} | None}
```

Result: `{"radius_m": 50, "building_share": 0.31, "scenarios": {"agw": {...}, "extrem": {...}}, "rating": str, "rating_color": str, "errors": {layer: message}}`. The service returns `None` (not "Gering") outside the layer's NRW extent (`NRW_BBOX` from GetCapabilities — the WMS answers transparent white there). The rated `max` class is the worst depth class whose cumulative share of the open area reaches `_MIN_CLASS_SHARE = 0.02` (calibrated on seven Essen/Bochum points), so one gully pixel cannot set the rating. A velocity tile that fails to load lands in `errors` and leaves `velocity_max = None`; a failing depth tile raises. A tile that is entirely building/no-data on **both** depth layers raises `Empty("Keine Starkregen-Daten für diesen Ort (außerhalb NRW oder vollständig überbaut)")` (from `analysis.sections`, via the fetch — the service returns `None`).

Rating from the worst class within 50 m, 100-year event first: `"Hoch"/red` if agw ≥ 50 cm or extrem ≥ 100 cm; `"Erhöht"/orange` if agw ≥ 30 cm or extrem ≥ 50 cm; `"Mäßig"/yellow` if agw ≥ 10 cm or extrem ≥ 30 cm; else `"Gering"/green`.

### 3.2 `backend/bergbau_service.py`

`get_bergbau(lat, lon) -> Optional[dict]` — one `query` on layer 22 with a point geometry (`_query(layer_id, params)` is the HTTP/monkeypatch point). No feature → `None`. Field decoding (`b_` = Bezirksregierung Arnsberg mining records, `g_` = Geologischer Dienst, `gb_` = methane):

| Field | Item key | Label | Kind | Weight |
|---|---|---|---|---|
| `b_tabr_p` | `tagesbruch` | Bergbaubedingte Tagesbrüche | count | red |
| `b_taoe_p` | `tagesoeffnung` | Verlassene Tagesöffnungen (Schächte, Stollen) | count | red |
| `b_beba_f` | `bergbau_belegt` | Oberflächennaher Bergbau belegt | flag | orange |
| `g_beba_f` | `bergbau_moeglich` | Tagesnaher Bergbau möglich | flag | yellow |
| `gb_meth_p` / `gb_meth_f` | `methan` | Methanausgasung (punktuell / flächenhaft) | count+flag | orange |
| `g_erdf_p` | `erdfall` | Erdfälle | count | orange |
| `g_subs_f` | `subrosion` | Subrosionssenke | flag | orange |
| `g_kars_f` | `karst` | Karstgebiet | flag | yellow |
| `g_aust_f` | `gasaustritt` | Gasaustritt in Bohrungen möglich | flag | info |
| `g_erb1_f` or `g_erb2_f` | `erdbeben` | Erdbebenzone (DIN EN 1998) | flag | info |

Result: `{"cell_id", "cell_size_m": 500, "authority": "Bezirksregierung Arnsberg" if status_bb_gd in (2, 3) else "Geologischer Dienst NRW", "updated": "2026-08-01", "items": [ {key, label, kind, count|None, present: bool, weight} … only present ones ], "rating", "rating_color"}`. Rating = worst weight among present items: red → `"Tagesbrüche / Tagesöffnungen"`, orange → `"Bergbau belegt"`, yellow → `"Bergbau möglich"`, only info/none → `"Keine Hinweise"` green.

### 3.3 `backend/zensus_grid.py` + `scripts/build_zensus_grid.py`

Build script (manual, like `build_eea_aq_grid.py`): `--src DIR` of the 13 Destatis zips → `backend/zensus_2022_grid.json.gz`:

```json
{"source": "Destatis, Zensus 2022 (100 m-Gitter)", "year": 2022, "crs": "EPSG:3035", "cell_m": 100,
 "fields": ["einwohner", "alter", "u18", "ab65", "hh_groesse", "wohnfl_je_bew", "eigentuemer", "leerstand", "miete_qm",
            "geb", "bj_vor1919", "bj_1919_1949", …, "bj_2016plus", "hz_fern", "hz_etage", "hz_block", "hz_zentral", "hz_ofen", "hz_keine",
            "et_gas", "et_oel", "et_holz", "et_bio", "et_solar_wp", "et_strom", "et_kohle", "et_fern", "et_keine",
            "gw_1", "gw_2", "gw_3_6", "gw_7_12", "gw_13plus"],
 "cells": {"4110150_3150250": [12, 41.3, 17.0, 25.0, 2.1, 44.0, 60.0, 2.0, 7.1, 3, null, null, 3, …]}}
```

Percent fields (`u18`, `ab65`, `eigentuemer`, `leerstand`) are stored as Destatis publishes them, 0–100; `null` is a suppressed (`–`) value, and a `KLAMMERN` low-reliability value is kept. The build reads the 13 zips streaming (`utf-8` with `errors="replace"` — Energieträger and Heizungsart are cp1252, but only the suppression dash is non-ASCII), crops to `BBOX_WGS84 = (6.85, 51.33, 7.40, 51.56)` and drops cells with no value in any field: 43 376 cells, 1.4 MB gzipped.

```json
```

`lookup(lat, lon) -> Optional[dict]`: project, snap to the 100 m centre, read the cell and its 5×5 neighbourhood. Returns `None` when no cell in the neighbourhood has data (outside window / unpopulated).

```python
{"cell": {...} | None, "area": {...}, "radius_m": 250, "area_cells": 19, "year": 2022}
# both dicts: einwohner, alter, u18, ab65, hh_groesse, wohnfl_je_bew, eigentuemer, leerstand, miete_qm (None when suppressed),
# plus buildings: gebaeude (count), baujahr: {label: share}, heizung: {label: share}, energietraeger: {label: share}, gebaeudetyp: {label: share}
```

Aggregation over the neighbourhood: `einwohner`/building counts are summed; `alter/u18/ab65/hh_groesse/wohnfl_je_bew` are population-weighted means over cells that have both the value and `einwohner`; `eigentuemer/leerstand/miete_qm` are unweighted means (no per-cell dwelling count is shipped); category shares are computed from summed counts. Shares are 0–1 floats rounded to 3 places; percentages are formatted in the template.

## 4. Registry entries

```python
Section("starkregen", "Starkregen", "🌧️", 25, "BKG Hinweiskarte Starkregengefahren (dl-de/by-2-0) — 1 m-Modell ohne Kanalnetz", _fetch_starkregen),
Section("bergbau", "Bergbau & Untergrund", "⛏️", 20, "Geologischer Dienst NRW, „NRW von unten“ (Bürgerversion, 500 m-Planquadrat)", _fetch_bergbau),
Section("zensus", "Nachbarschaft (Zensus 2022)", "🏘️", 5, "Destatis, Zensus 2022 — 100 m-Gitterdaten (dl-de/by-2-0)", _fetch_zensus),
```

`SERVICE_TIER`: `"starkregen": "parcel"`, `"bergbau": "area"`, `"zensus": "area"`. Each `_fetch_*` maps a `None` service result to `Empty(msg)`; anything else raised propagates as `status="error"`.

## 5. Partials

- `_starkregen.html`: rating badge + two scenario columns ("Seltenes Ereignis (100-jährlich)" / "Extremereignis (90 mm/h)"), each with the max-depth headline, wet share, velocity, and a stacked share bar over the depth classes. Footnote: model ignores the sewer network; ±50 m; links to the BKG viewer and Essen's Starkregengefahrenkarte.
- `_bergbau.html`: rating badge, authority line, list of present items with counts; "Keine Hinweise im Planquadrat" when the list is empty. Footnote: 500 m grid, anonymised, formal Bergbauauskunft via Bezirksregierung Arnsberg (Abt. 6) / RAG, link to `https://www.gdu.nrw.de`.
- `_zensus.html`: a key-figure table (Kennzahl | 100 m-Zelle | Umfeld 500 m) for the nine scalar metrics, then three horizontal share bars (Baujahr, Heizung/Energieträger, Gebäudetyp) from the area aggregate. "–" for suppressed values.

## 6. Testing

Hermetic, in `tests/test_starkregen_service.py`, `tests/test_bergbau_service.py`, `tests/test_zensus_grid.py`, plus registry/tier assertions added to the existing `tests/test_analysis_sections.py`:

- Starkregen: synthetic PIL tiles (`_get_tile` monkeypatched) → class counts, shares, max, building handling, rating thresholds, all-building → `None`.
- Bergbau: canned ArcGIS JSON → item list, counts, authority, rating; empty features → `None`; HTTP error propagates.
- Zensus: a tiny in-memory grid (monkeypatch `_load`) → cell hit, neighbourhood aggregation (weighted vs. unweighted, suppressed handling), outside window → `None`; build script parser tested on a small CSV fixture (encoding, `–`, `KLAMMERN`, decimal comma).

`scripts/smoke_analyze.py` and a browser check on `/analyze` for one Essen and one Bochum address before merge.

## 7. Documentation

CLAUDE.md gets one paragraph per card under the analysis section; HANDOVER.md gets a work-log entry. `requirements.txt` is unchanged (PIL, pyproj, httpx already present).
