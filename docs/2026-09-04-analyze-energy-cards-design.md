# Analyze page — Energie, Schutzgebiete, Breitband cards — design

**Date:** 2026-09-04
**Scope:** batch 2 of the analyze-page extension (batch 1 = Starkregen/Bergbau/Zensus, `2026-09-04-analyze-risk-cards-design.md`). Three new sections plugged into the registry from `2026-09-04-analyze-rework-design.md` — each a service module, a `fetch` normaliser, a partial, and hermetic tests. Envelope, routes and the frontend component are unchanged. Deferred to batch 3: Denkmalschutz, ÖPNV-Qualität, Hochspannung/Störfallbetriebe.

## 1. Why these three

Live-probed 2026-09-04. All sources answer with a single point/polygon query; every endpoint below was exercised at Rüttenscheid (51.4378, 7.0053), Kettwig (51.3616, 6.9411) and Bochum (51.4586, 7.1934 / 51.4818, 7.2162).

| Card | Question | Source (verified) |
|---|---|---|
| **Energie** | What can this house do for its own energy? Solar yield of *its* roof, whether a ground-source heat pump is viable, and whether district heating is or will be available (the 2045 municipal heat plan decides which heating a buyer should budget for). | (a) LANUK *Solarkataster NRW* ArcGIS `https://arcgis.energieatlas.nrw.de/arcgis/rest/services/Solarkataster/25_09_04_EnergieatlasNRW_Solarkataster/MapServer` — layer 9 building outlines, layer 8 PV roof segments (kWp, kWh/a, orientation, tilt, 2020 flight). (b) GD NRW *Geothermie* WMS `https://www.wms.nrw.de/gd/GT` — layers 63/64/65/66 = mean thermal conductivity class for 100/80/60/40 m probes, 69 = collector suitability, 17 = hydrologically sensitive area, 67 = increased groundwater flow. (c) *Kommunale Wärmeplanung*: Essen `https://geo.essen.de/arcgis/rest/services/essen/Kommunale_Waermeplanung/MapServer/73` (Zieljahr 2045, adopted) and Bochum `https://geoservicekkm.bochum.de/arcgis/rest/services/maponline/KommunaleWaermeplanung/MapServer` (layers 0–6, draft until 30.06.2026). |
| **Schutzgebiete** | Is the plot in or next to a nature/landscape reserve (building restrictions, no extensions in an LSG without exemption) or in a drinking-water protection zone (restricts geothermal probes, oil tanks, some construction)? | LANUV *LINFOS* WFS `https://www.wfs.nrw.de/umwelt/linfos` (WFS 2.0, GeoJSON out, bbox **must** be EPSG:25832) — `nsg_polygon`, `lsg_polygon`, `ffh_polygon`, `vsg_polygon`, `np_polygon`, `gbt_polygon`. Wasserschutzgebiete WMS `https://www.wms.nrw.de/umwelt/wasser/wsg` GetFeatureInfo layers 1–4 (Heilquellen/Trinkwasser, geplant/festgesetzt). |
| **Breitband** | Is there fibre (FTTH) to the house, what is the gigabit/100 Mbit coverage, and which mobile networks have 5G here? | BNetzA *Breitbandatlas* WMS `https://breitbandatlas-wms.gigabit-grundbuch.online/WMS/Breitbandatlas` (Datenstand 12.2025, © BNetzA). No GetFeatureInfo — 100 m INSPIRE-grid layers are read by legend colour from a GetMap tile at the cell centre, exactly like `starkregen_service`. |

## 2. Decisions taken

- **Energie is parcel tier.** The PV part needs the actual building; a street-centroid geocode would sum a neighbour's roof. Erdwärme and Wärmeplanung would be fine at area precision but live in the same card — "Trotzdem laden" exposes them for a rough geocode.
- **Solarkataster building selection:** a point query on layer 9 (`esriSpatialRelIntersects`, no distance) returns the building the point is *in*; only if that is empty, search within 20 m and take the largest `Shape_Area` ≥ 40 m² (skips garages/sheds). Segments are then fetched with the building polygon and `esriSpatialRelContains` — `Intersects` pulls in neighbours' segments, `Within` returns nothing (verified). No building → the PV part is `None`, the card still shows Erdwärme/Wärmeplanung.
- **Erdwärme uses GetFeatureInfo** (`application/vnd.esri.wms_featureinfo_xml`) on one request for all seven layers; `application/geo+json` is rejected by that server. Class ranges arrive as strings like `"2,5 - 2,9"`; the rating uses the parsed lower bound (W/(m·K)). A WSG hit from the Schutzgebiete service is surfaced *inside* the Energie card as a caveat (zone I/II: probes generally prohibited; zone III: permit required) — one extra cheap GFI call, no cross-card coupling in the frontend.
- **Wärmeplanung:** Essen first (layer 73, `distance=30 m` because block polygons have gaps between them), Bochum second (`identify` over all layers, tolerance 5 px), else `None`. Both normalise to the same six-value `category`. The Bochum plan is labelled `status: "Entwurf"`.
- **Schutzgebiete is area tier**, one WFS call per type in a `ThreadPoolExecutor`, bbox = point ± 500 m in EPSG:25832 (pyproj). Point-in-polygon and distance via shapely (both already in the venv). Inside → `distance_m = 0`. WSG via GFI with `FEATURE_COUNT=10` on layers 1–4 — planned *and* fixed zones both matter to a buyer (a planned zone becomes binding).
- **Breitband** samples a 21×21 px tile (±0.0001°) at the centre of the 100 m EPSG:3035 cell containing the point (the atlas uses the INSPIRE grid, same as the Zensus grid); dominant legend colour wins, dark grid-line pixels are ignored. Nine layers (4 fixed-line coverage classes, 5 mobile 5G) fetched in parallel. A tile that is entirely transparent on every fixed-line layer means "outside Germany / no households" → `None` → `Empty`.
- **TLS:** the Breitbandatlas host serves a Let's Encrypt *YE2* leaf without its chain, and the 2026 *ISRG Root YE* is only cross-signed by ISRG Root X2 — so the system store cannot verify it. The two public issuer certificates (fetched from LE's own AIA URLs `http://ye2.i.lencr.org/` and `http://ye.i.lencr.org/`) are shipped as `backend/certs/lencr_ye_chain.pem` and loaded into an `ssl.create_default_context()` on top of the system store. Never `verify=False`.
- **Tiers:** `energie` parcel; `schutzgebiete` area; `breitband` area.
- **Order:** `energie` after `zensus` (property → neighbourhood → infrastructure); `schutzgebiete` after `gfnp` (land-use context); `breitband` after `energie`.

## 3. Services

### 3.1 `backend/energie_service.py`

```python
SOLAR_URL = "https://arcgis.energieatlas.nrw.de/arcgis/rest/services/Solarkataster/25_09_04_EnergieatlasNRW_Solarkataster/MapServer"
SOLAR_BUILDINGS_LAYER, SOLAR_PV_LAYER = 9, 8
GT_WMS_URL = "https://www.wms.nrw.de/gd/GT"
GT_LAYERS = {"63": "100 m", "64": "80 m", "65": "60 m", "66": "40 m"}   # probe depth → layer
GT_COLLECTOR_LAYER, GT_HYDRO_LAYER, GT_FLOW_LAYER = "69", "17", "67"
ESSEN_KWP_URL = "https://geo.essen.de/arcgis/rest/services/essen/Kommunale_Waermeplanung/MapServer/73"
BOCHUM_KWP_URL = "https://geoservicekkm.bochum.de/arcgis/rest/services/maponline/KommunaleWaermeplanung/MapServer"
```

HTTP/monkeypatch points: `_arcgis_query(url, params) -> dict` (GET `{url}/query`), `_arcgis_identify(url, params) -> dict` (GET `{url}/identify`), `_gt_featureinfo(lat, lon) -> str` (raw XML), `_wsg_zones(lat, lon) -> list[dict]` (delegates to `schutzgebiete_service._wsg_featureinfo` + `parse_wsg`). `get_energie(lat, lon) -> dict` runs `pv`, `erdwaerme`, `waermeplanung` and the WSG caveat in a `ThreadPoolExecutor`; each part is isolated — a failure lands in `errors[part]` and the part is `None`. All four `None` **and** any error → raise the first error; all four `None` without errors → return `None` (→ `Empty`).

**PV** (`_pv(lat, lon)`). Building selection: a `Contains` point query on layer 9 first; when the geocoded point sits on no outline (street-centre geocodes), the *nearest* outline within `_NEAR_M = 20` m with area ≥ `_MIN_BUILDING_M2 = 40` m² (shapely distance in EPSG:25832) is used — not the largest, which picked neighbouring apartment blocks in the spike. Every part carries a `link` (`SOLAR_LINK`, `GT_LINK`, city heat-plan page).

```python
{"building": {"geb_id": "…", "alkis_id": "DENW22AL8000048B", "area_m2": 924.0, "picked": "contains" | "nearest"},
 "segments": [{"orientation": "Süd", "tilt_deg": 35, "area_m2": 48.2, "kwp": 8.1, "kwh_a": 7400, "radiation_kwh_m2": 1010, "roof": "geneigt"}, …],  # sorted by kwh_a desc
 "total_kwp": 57.4, "total_kwh_a": 44449, "module_area_m2": 312.0, "best_orientation": "Süd",
 "household_equivalents": 11.1,   # total_kwh_a / 4000
 "survey_year": "2020", "segment_count": 5, "rating": "Sehr gut", "rating_color": "green", "link": SOLAR_LINK}
```

Rating on `total_kwh_a`: ≥ 8000 `Sehr gut`/green, ≥ 4000 `Gut`/green, ≥ 2000 `Mäßig`/yellow, > 0 `Gering`/orange, no segments `Keine geeigneten Dachflächen`/gray. `best_orientation` is the `himmel_kat` of the segment with the highest `kwh_a`. `segments` keeps at most 12 entries (the largest); `segment_count` carries the full count.

**Erdwärme** (`_erdwaerme(lat, lon)`) parses the `FeatureInfoCollection layername="…"` blocks:

```python
{"probes": [{"depth": "100 m", "class": 3, "range": "2,5 – 2,9", "lower_w_mk": 2.5}, … 80/60/40 …],
 "collector": "mittel" | "gering" | "hoch" | "zu flach" | "grundnass" | "nicht bewertet" | None,
 "hydro_sensitive": bool, "high_groundwater_flow": bool,
 "rating": "Gut", "rating_color": "green", "wsg_note": None, "link": GT_LINK}
```

Rating from the 100 m probe lower bound (fallback: deepest present): ≥ 2.5 `Gut`/green, ≥ 2.0 `Mittel`/yellow, > 0 `Gering`/orange; no probe data `Keine Bewertung`/gray. A WSG hit (see 3.2, `wsg` non-empty; worst zone wins) adds `wsg_note` = `"Wasserschutzgebiet Zone {zone} ({name}): Erdwärmesonden {generell unzulässig|nur mit Genehmigung}"` and overrides the badge, because the legal constraint beats the geological one: zone `I`/`II` → rating `Unzulässig (Wasserschutzgebiet)`/red; zone `III*` → green/yellow ratings become `"{rating}, genehmigungspflichtig"`/orange (orange/gray stay). Layer 69 (collectors) reports its `layername` as `1800 (2400) Betriebsstunden/Jahr`, so the collector block is recognised by its `ewk_wert` field, not by name.

**Wärmeplanung** (`_waermeplanung(lat, lon)`):

```python
{"city": "Essen" | "Bochum", "status": "beschlossen" | "Entwurf", "target_year": 2045,
 "category": "fernwaerme_bestand" | "fernwaerme_ausbau" | "pruefgebiet_waermenetz" | "pruefgebiet_wasserstoff" | "dezentral" | "sonstiges",
 "label": "Wärmenetzausbaugebiet", "detail": "sehr wahrscheinlich geeignet" | None,
 "has_grid_2024": bool | None, "has_grid_2045": bool | None, "link": str}
```

Essen mapping on `GEBIETSEINTEILUNG`: `Wärmenetzausbaugebiet` → `fernwaerme_ausbau` (`fernwaerme_bestand` when `HAS_HEAT_GRID_2024 == 1`), `Prüfgebiet Wärmenetze` → `pruefgebiet_waermenetz`, `Prüfgebiet Wasserstoff` → `pruefgebiet_wasserstoff`, `Dezentral` → `dezentral`, anything else → `sonstiges`; `detail` = text after `" - "` in `PREFERENCE_AREA`. Bochum mapping on the identify `layerId`: 0 → `fernwaerme_bestand`, 1 → `fernwaerme_ausbau`, 2 → `pruefgebiet_waermenetz`, 3 → `fernwaerme_bestand` (label "Nahwärme Dahlhausen"), 4 → `dezentral`, 5/6 → `sonstiges` (label = layer name, detail = `Zielbild`/`Name` attribute). With several Bochum hits the lowest layer id wins.

Card colour for the category chip: `fernwaerme_bestand` green, `fernwaerme_ausbau` green, `pruefgebiet_*` yellow, `dezentral` gray, `sonstiges` gray.

### 3.2 `backend/schutzgebiete_service.py`

```python
LINFOS_WFS_URL = "https://www.wfs.nrw.de/umwelt/linfos"
LINFOS_TYPES = [("nsg", "wfs_linfos:nsg_polygon", "Naturschutzgebiet"), ("lsg", "wfs_linfos:lsg_polygon", "Landschaftsschutzgebiet"),
                ("ffh", "wfs_linfos:ffh_polygon", "FFH-Gebiet"), ("vsg", "wfs_linfos:vsg_polygon", "Vogelschutzgebiet"),
                ("np", "wfs_linfos:np_polygon", "Naturpark"), ("gbt", "wfs_linfos:gbt_polygon", "Geschützter Biotop")]
WSG_WMS_URL = "https://www.wms.nrw.de/umwelt/wasser/wsg"
RADIUS_M = 500
```

Monkeypatch points: `_wfs_features(typename, bbox_25832) -> list[dict]` (GeoJSON features; the WFS 2.0 BBOX must be EPSG:25832 — a WGS84 bbox returns nothing — with `OUTPUTFORMAT=GEOJSON` yielding WGS84 geometry) and `_wsg_featureinfo(lat, lon) -> str`. `get_schutzgebiete(lat, lon) -> dict`:

```python
{"radius_m": 500,
 "areas": [{"kind": "nsg", "kind_label": "Naturschutzgebiet", "name": "NSG Heisinger Ruhraue", "kennung": "E-003",
            "status": "NSG, bestehend", "distance_m": 0 | 180.4, "inside": bool, "link": "https://…", "since": 1992 | None}, …],  # inside first, then by distance; at most _MAX_PER_KIND = 5 per kind
 "counts": {"nsg": 1, "gbt": 23, …},   # full per-kind counts before the cap
 "wsg": [{"name": "Essen-Burgaltendorf/Horst", "zone": "III A", "status": "festgesetzt" | "geplant", "kind": "Trinkwasser" | "Heilquellen", "since": "2019-05-03" | None, "ordinance": str | None, "area_km2": float | None}],
 "rating": "Im Naturschutzgebiet", "rating_color": "red", "errors": {}}
```

Rating (first match): inside NSG/FFH/VSG/GBT → `Im Naturschutzgebiet`/red; WSG zone I/II → `Wasserschutzgebiet Zone I|II`/red; inside LSG or NP → `Im Landschaftsschutzgebiet`/orange; WSG zone III → `Wasserschutzgebiet Zone III`/orange; any area within 500 m → `Schutzgebiet in der Nähe`/yellow; nothing → `Keine Schutzgebiete`/green. A type whose WFS call fails is recorded in `errors[kind]` and skipped; if *every* WFS call fails the service raises. WSG GFI failure → `errors["wsg"]`, `wsg = []`.

Distance: shapely `Polygon.distance` in EPSG:25832 (metres) after transforming the GeoJSON (WGS84) rings with pyproj; `inside` = `contains`. Only areas within `RADIUS_M` are kept.

### 3.3 `backend/breitband_service.py`

```python
WMS_URL = "https://breitbandatlas-wms.gigabit-grundbuch.online/WMS/Breitbandatlas"
CA_BUNDLE = Path(__file__).parent / "certs" / "lencr_ye_chain.pem"
FIXED_LAYERS = {"ftth_1000": "Breitband_Festnetz__100m_Gitter__Glasfaser_(FTTB/H)_≥_1000_Mbit/s44392",
                "hh_1000": "Breitband_Festnetz__100m_Gitter__Privathaushalte_≥_1000_Mbit/s41271",
                "hh_400": "Breitband_Festnetz__100m_Gitter__Privathaushalte_≥_400_Mbit/s56938",
                "hh_100": "Breitband_Festnetz__100m_Gitter__Privathaushalte_≥_100_Mbit/s49615"}
MOBILE_LAYERS = {"telekom": "Breitband_Mobilfunk__Fläche__100m_Gitter__Telekom_5G32661",
                 "vodafone": "Breitband_Mobilfunk_Fläche__100m_Gitter__Vodafone_5G65414",
                 "o2": "Breitband_Mobilfunk_Fläche__100m_Gitter__Telefónica_5G50216",
                 "1u1": "Breitband_Mobilfunk__Fläche__100m_Gitter__1u1_5G51009"}
COVERAGE_CLASSES = [((51, 111, 145), "> 95 %", 95, 5), ((102, 179, 185), "75 – 95 %", 75, 4), ((204, 230, 232), "50 – 75 %", 50, 3),
                    ((252, 228, 177), "10 – 50 %", 10, 2), ((254, 249, 216), "0 – 10 %", 0, 1)]   # (rgb, label, min_pct, step) — legend verified 2026-09-04
MOBILE_CLASSES = {(247, 187, 61): "5G", (251, 221, 158): "5G-Roaming"}
DATENSTAND = "12.2025"
```

`_get_tile(layer, lat, lon) -> Image` is the HTTP/monkeypatch point (21×21 px, bbox ±0.0001° around the *cell centre*). `cell_center(lat, lon)` snaps to the 100 m EPSG:3035 cell. `_dominant(img, palette)` returns the palette entry with the most pixels, ignoring pixels not in the palette (grid lines, anti-aliasing); all-transparent → `None`. `get_breitband(lat, lon) -> Optional[dict]`:

```python
{"cell_m": 100, "datenstand": "12.2025", "attribution": "© BNetzA, Breitbandatlas — Datenstand 12.2025", "cell_center": [lat, lon],
 "fixed": {"ftth_1000": {"label": "> 95 %", "min_pct": 95, "step": 5}, "hh_1000": {...}, "hh_400": {...}, "hh_100": {...}},  # value None when no data; step 1..5 drives the bar
 "mobile_5g": {"telekom": "5G", "vodafone": "5G", "o2": "5G", "1u1": "5G-Roaming"},   # None = no 5G
 "rating": "Glasfaser verfügbar", "rating_color": "green", "errors": {}}
```

Rating on `min_pct`: ftth ≥ 75 → `Glasfaser verfügbar`/green; ftth ≥ 10 → `Glasfaser teilweise`/yellow; hh_1000 ≥ 75 → `Gigabit (Kabel), kein Glasfaser`/yellow; hh_100 ≥ 75 → `≥ 100 Mbit/s, kein Gigabit`/orange; else `Unterversorgt`/red. Every fixed-line layer `None` (and no errors) → return `None`; every layer failing → raise. TLS: the WMS host chains to ISRG Root YE (not in the system store) — `_ssl_context()` loads the bundled `backend/certs/lencr_ye_chain.pem` (Let's Encrypt YE2 + Root YE); never `verify=False`.

## 4. Registry entries

| key | title | icon | timeout | tier | source line |
|---|---|---|---|---|---|
| `energie` | Energie (Solar · Erdwärme · Wärmeplanung) | ☀️ | 30 | parcel | LANUK Solarkataster NRW · GD NRW Geothermie · Kommunale Wärmeplanung Essen/Bochum |
| `schutzgebiete` | Schutzgebiete | 🌳 | 25 | area | LANUV LINFOS (NSG/LSG/FFH/VSG/Naturpark/Biotope) · Wasserschutzgebiete NRW |
| `breitband` | Breitband & Mobilfunk | 🌐 | 30 | area | © BNetzA, Breitbandatlas — Datenstand 12.2025, 100 m-Raster |

`_fetch_*` pass the service dict through; `None` → `Empty` with: energie `"Keine Energiedaten für diesen Ort (kein Gebäude im Solarkataster, außerhalb NRW)"`, schutzgebiete never `None` (always a rating), breitband `"Keine Breitbandatlas-Daten für diese Rasterzelle (außerhalb Deutschlands oder unbewohnt)"`. New order:

`boris, boris_trend, flood, starkregen, noise, bergbau, gfnp, schutzgebiete, planning_essen, planning_bochum, amenities, zensus, energie, breitband, air_quality, btw, commute`

`SERVICE_TIER` gains `"energie": "parcel"`, `"schutzgebiete": "area"`, `"breitband": "area"`.

## 5. Partials

- `_energie.html`: three stacked blocks. **Solar**: chip + totals (kWp, kWh/a, Modulfläche, "≈ n Haushalte"), a compact segment table (Ausrichtung, Neigung, Fläche, kWp, kWh/a), building id line; "kein Gebäude gefunden" text when `pv` is `None`. **Erdwärme**: chip, probe classes as four small tiles (Tiefe → Bereich W/(m·K)), collector line, flags, `wsg_note` in an amber callout. **Wärmeplanung**: chip with category colour, label/detail, grid 2024/2045 marks, status (Entwurf) note, link. Footnote: Solarkataster is a 2020 flight (new roofs/dormers missing), heat-plan area classes are planning intent, not a supply guarantee.
- `_schutzgebiete.html`: chip; list of areas (kind badge, name, "innerhalb" or "x m entfernt", link); WSG block with zone/status; footnote on what LSG/NSG/WSG restrict and the LINFOS link.
- `_breitband.html`: chip; four coverage rows with a five-step bar (class index), mobile 5G row of four provider chips; footnote "Anteil der Haushalte in der 100 m-Zelle mit verfügbarer Bandbreite, Anbieterangaben an die BNetzA; Verfügbarkeit am Haus beim Anbieter prüfen".

Colours use `$store.app.getAirQualityColor(color)` (green/yellow/orange/red/gray), like the batch-1 cards. The committed `frontend/static/css/tailwind.css` is a content-scanned build — new utilities in partials need `npx tailwindcss@3 -c tailwind.config.js -i frontend/static/css/tailwind.input.css -o frontend/static/css/tailwind.css --minify` (the file was stale before this batch; the Breitband bars rendered invisible until rebuilt).

## 6. Testing

Hermetic — one HTTP function per service is monkeypatched:

- `tests/test_energie_service.py`: PV picks the containing building over the nearest; nearest skips < 40 m²; segments aggregated and rated (fixtures from the Rüttenscheid/Kettwig live shapes); no building → `pv None`; GT XML parse (fixture from the live `vnd.esri.wms_featureinfo_xml` response) → probes/collector/flags + rating; WSG note downgrades colour; Essen `GEBIETSEINTEILUNG` mapping incl. bestand-vs-ausbau; Bochum identify mapping with lowest layer winning; all parts `None` → `None`; one part failing → `errors` filled, others kept.
- `tests/test_schutzgebiete_service.py`: bbox in 25832; inside vs. distance ordering; WSG XML parse (zone/status/kind); ratings for each tier; partial WFS failure tolerated, total failure raises.
- `tests/test_breitband_service.py`: `cell_center` snaps to the 100 m grid; dominant colour ignores grid lines; all-transparent → `None`; rating ladder; mobile mapping; `_ssl_context()` loads the bundle (file exists, two certificates).
- `tests/test_analysis_sections.py`: order updated; pass-through + `Empty` per fetch; tier assertions.
- Live smoke (manual): dev instance on :8011, `browser_check.py` on Rüttenscheid, Bochum-Weitmar and Berlin.

## 7. Documentation

CLAUDE.md gets a "Energie, Schutzgebiete & Breitband cards (2026-09-04)" paragraph (sources, the building-selection and `Contains` rule, the LINFOS 25832-bbox rule, the Breitbandatlas TLS bundle and colour method); HANDOVER.md a work-log entry.
