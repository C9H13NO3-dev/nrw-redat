# Analyze page — Denkmalschutz, ÖPNV, Hochspannung & Industrie cards — design

**Date:** 2026-09-04
**Scope:** batch 3 of the analyze-page extension (batch 1 = Starkregen/Bergbau/Zensus, batch 2 = Energie/Schutzgebiete/Breitband). Three new sections plugged into the registry from `2026-09-04-analyze-rework-design.md` — each a service module, a `fetch` normaliser, a partial and hermetic tests. Envelope, routes and the frontend component are unchanged.

## 1. Why these three

Live-probed 2026-09-04 at Rüttenscheid (51.4378, 7.0053), Werden (51.3885, 7.0035), Bochum Hbf (51.4786, 7.2233), Bochum Weitmar (51.4586, 7.1934) and Essen-Karnap (51.5180, 7.0010).

| Card | Question | Source (verified) |
|---|---|---|
| **Denkmalschutz** | Is *this* building a listed monument (Umbau/Fenster/Dämmung need approval, in return §7i EStG depreciation), does it sit in a Denkmalbereich or on a Bodendenkmal (archaeology before any excavation), and is a monument next door (Umgebungsschutz §9 DSchG NRW)? | RVR *Geoportal Ruhr* INSPIRE WFS 2.0 `https://geodaten.metropoleruhr.de/inspire/schutzgebiete/metropoleruhr`, typenames `ms:denkmal_polygon` (Essen: every monument as an outline; Bochum: Siedlungen + Denkmalbereichssatzungen) and `ms:denkmal_point_unclustered` (Bochum: one point per Baudenkmal). DefaultCRS EPSG:25832; `outputFormat=geojson&srsName=EPSG:4326` works although the capabilities only advertise GML. Properties: `bezeichnun`, `inspire_id` (`DE_<AGS>_<A|B|C|D>_<nr>…` — A Baudenkmal, B Bodendenkmal, C bewegliches Denkmal, D Denkmalbereich), `gemeinde`, `kategorie` (1000 Bau-/bewegliches Denkmal, 2000 Siedlung/Denkmalbereich, 4000 Bodendenkmal), `datum`, `merkmale` (Essen → Denkmalliste .htm; Bochum → photo .jpg), `denkmal_ei` (Bochum → Begründung .pdf). The Essen city ArcGIS `essen/Denkmaeler` has richer `LAYER` classes but no Bochum; Bochum's ArcGIS has no Denkmal layer; OSM `heritage` is far too thin in Bochum (42 vs 291 objects within 3 km). |
| **ÖPNV** | Which stops are within walking distance, which lines and how often at rush hour, and how long is the ride to Essen/Bochum/Düsseldorf Hbf and to the buyer's own "Wichtige Orte"? | VRR *EFA* `https://efa.vrr.de/standard/` (`outputFormat=rapidJSON`, `coordOutputFormat=WGS84[dd.ddddd]`): `XML_COORD_REQUEST` (stops around a coordinate, `inclFilter=1&radius_1=600&type_1=STOP`, returns `productClasses` and `properties.distance`), `XML_DM_REQUEST` (departure monitor per stop, `type_dm=stop&name_dm=<globalId>&mode=direct&itdDate&itdTime&limit`), `XML_TRIP_REQUEST2` (`type_origin=coord`, destination by stop global id or coordinate, `itdDate/itdTime/itdTripDateTimeDepArr=dep/calcNumberOfTrips=3/useRealtime=0`). Times are UTC (`Z`). Probe timings: coord 0.2 s, trip 3 s. |
| **Hochspannung, Leitungen & Industrie** | Overhead high-voltage lines, substations, wind turbines, transmitter masts and gas/oil pipelines next to the plot (value, EMF worries, noise), plus heavy industry in the neighbourhood. | OpenStreetMap via Overpass (`https://overpass-api.de/api/interpreter`, needs a `User-Agent` — 406 without; rate-limits with 429 on burst) — `power=line|minor_line|cable` with `voltage`, `power=substation`, `generator:source=wind`, `man_made=mast|tower|communications_tower`, `man_made=pipeline` with `substance`, `landuse=industrial`. Industry: EEA *Industrial Emissions Portal* via discodata SQL `https://discodata.eea.europa.eu/sql` on `[IED].[latest].[SiteMap]` (one row per site and reporting year; `siteName`, `cities`, `eea_activities`, `x_4258/y_4258`; 67 distinct sites in Essen/Bochum, 51 reported for 2024). |

**Störfallbetriebe (Seveso III) are not available for NRW.** Checked open.nrw, the GDI-DE catalogue, RVR CSW, wms.nrw.de, both city ArcGIS servers and the EEA registry: Sachsen, Hamburg, Bremen, Brandenburg, Schleswig-Holstein, Saarland and Thüringen publish Betriebsbereiche with Achtungsabstand, NRW does not, and NRW leaves the EEA `seveso` field empty. The card says so and points to the competent Bezirksregierung (Düsseldorf for Essen, Arnsberg for Bochum) instead of pretending with a proxy.

## 2. Decisions taken

- **Denkmal is parcel tier.** The decisive question ("steht das Haus unter Schutz") needs the building; a street-centre geocode would hit the wrong polygon. "Trotzdem laden" exposes the neighbourhood list for rough geocodes. Search radius `RADIUS_M = 300` (bbox in EPSG:25832, like `schutzgebiete_service`). Bochum's points are building centroids, so a point within `_POINT_HIT_M = 25` m counts as *on the property*; Essen's polygons use `contains`. Dedupe key is `inspire_id` truncated to `DE_<AGS>_<letter>_<nr>` (Bochum appends the coordinate to the id; Hauptbahnhof appeared twice in the spike). Outside `RVR_BBOX = (6.35, 51.25, 7.85, 51.85)` the WFS returns nothing that means anything → `None` → `Empty`, never "Kein Denkmalschutz".
- **ÖPNV is area tier**, three isolated parts in a `ThreadPoolExecutor`: `stops`, `departures` (rush-hour departure counts for the nearest three stops), `trips` (to three fixed Hauptbahnhöfe + the configured `IMPORTANT_LOCATIONS` with an address, geocoded through `geocoding.geocode_with_precision`). All timetable queries use one fixed **reference time**: the next Tuesday ≥ tomorrow, 08:00 Europe/Berlin (departure monitor window 07:00–09:00), so the card is a stable weekday snapshot, not "now". The destination list is capped at 8 (3 fixed + 5 custom) and every trip request runs in the pool — the card's 45 s timeout covers ~8 × 3 s in ≤ 4 parallel workers.
- **Infrastruktur is area tier**, two isolated parts (`osm`, `ied`). One Overpass request with `out geom` for ways and `out center` for the rest; distances via shapely in EPSG:25832 (`LineString.distance`, `Polygon.distance`/`contains`). Overpass 429/504 → one retry after 3 s, then the mirror `https://overpass.private.coffee/api/interpreter`; anything else raises into `errors["osm"]`. 10 kV Trafostationen (`power=substation` < 110 kV) are only *counted*, never listed — there are ~30 within 1.5 km of any Bochum address. Discodata rows are reduced to the latest `Site_reporting_year` per `InspireSiteId`, then filtered by haversine ≤ 2000 m.
- **Tiers:** `denkmal` parcel; `oepnv` area; `infrastruktur` area.
- **Order:** `denkmal` after `planning_bochum` (legal constraints block), `oepnv` after `amenities` (reachability block), `infrastruktur` after `breitband` (infrastructure block, before the environmental `air_quality`).

## 3. Services

### 3.1 `backend/denkmal_service.py`

```python
RVR_WFS_URL = "https://geodaten.metropoleruhr.de/inspire/schutzgebiete/metropoleruhr"
RVR_TYPES = ("ms:denkmal_polygon", "ms:denkmal_point_unclustered")
RVR_BBOX = (6.35, 51.25, 7.85, 51.85)          # lon_min, lat_min, lon_max, lat_max — RVR Verbandsgebiet
RADIUS_M = 300
_POINT_HIT_M = 25
_NEIGHBOUR_M = 50
_MAX_ITEMS = 12
KIND_LABELS = {"A": "Baudenkmal", "B": "Bodendenkmal", "C": "Bewegliches Denkmal", "D": "Denkmalbereich"}
AUTHORITY = {"Essen": ("Untere Denkmalbehörde Essen", "https://www.essen.de/leben/planen_und_bauen/denkmalschutz.de.html"),
             "Bochum": ("Untere Denkmalbehörde Bochum", "https://www.bochum.de/Denkmalschutz")}
```

Monkeypatch point: `_wfs_features(typename, bbox_25832) -> list[dict]` (GeoJSON features, WGS84 geometry). `get_denkmal(lat, lon) -> Optional[dict]`:

```python
{"radius_m": 300,
 "items": [{"id": "DE_05113000_A_1234", "name": "Villa Hügel", "kind": "A", "kind_label": "Baudenkmal",
            "scope": "objekt" | "gebiet",          # gebiet = kategorie 2000 or kind D (Siedlung / Denkmalbereich)
            "city": "Essen", "listed_since": "2003-06-18" | None,
            "distance_m": 0.0 | 37.5, "on_site": bool, "link": "https://…" | None}, …],  # on_site first, then by distance; ≤ _MAX_ITEMS
 "counts": {"A": 3, "B": 1, "C": 0, "D": 0},       # full counts within the radius before the cap
 "on_site": [ … the on_site items … ],
 "authority": {"name": "Untere Denkmalbehörde Essen", "link": "…"} | None,   # from the majority `gemeinde` of the hits
 "rating": "Baudenkmal", "rating_color": "orange"}
```

Rules: `kind` = letter after the AGS in `inspire_id` (unknown → `"A"` if `kategorie` is 1000, `"B"` if 4000, `"D"` if 2000). `scope = "gebiet"` when `kategorie == "2000"` or `kind == "D"`. `on_site` = polygon `contains` point, or point feature ≤ `_POINT_HIT_M`. `link` = `denkmal_ei` if it is an http URL, else `merkmale` if http, else `None`. `listed_since` = first 10 chars of `datum`. Rating (first match): on-site Baudenkmal/bewegliches (`A`/`C`, scope objekt) → `Baudenkmal`/orange; on-site `B` → `Bodendenkmal`/orange; on-site gebiet (`D` or kategorie 2000) → `Im Denkmalbereich`/yellow; any item ≤ `_NEIGHBOUR_M` → `Denkmal in unmittelbarer Nachbarschaft`/yellow; any item within the radius → `Denkmäler in der Nähe`/green; none → `Kein Denkmalschutz`/green. Outside `RVR_BBOX` → return `None` before any HTTP.

### 3.2 `backend/oepnv_service.py`

```python
EFA_URL = "https://efa.vrr.de/standard/"
EFA_COMMON = {"outputFormat": "rapidJSON", "coordOutputFormat": "WGS84[dd.ddddd]", "version": "10.4.18.18"}
STOP_RADIUS_M = 600
FIXED_DESTINATIONS = [("Essen Hbf", "de:05113:9289"), ("Bochum Hbf", "de:05911:5194"), ("Düsseldorf Hbf", "de:05111:18235")]
PRODUCT_LABELS = {0: "Zug", 1: "S-Bahn", 2: "U-Bahn", 3: "Stadtbahn", 4: "Straßenbahn", 5: "Bus", 6: "Regionalbus", 7: "Schnellbus",
                  8: "Seilbahn", 9: "AST", 10: "Fähre", 13: "Regionalzug", 14: "ICE", 15: "IC/EC", 16: "Sonstiger Zug"}
RAIL_CLASSES = {0, 1, 2, 3, 4, 13, 14, 15, 16}
_MAX_STOPS, _DM_STOPS, _MAX_CUSTOM_DESTINATIONS = 8, 3, 5
```

Monkeypatch point: `_efa(endpoint, params) -> dict` (GET `EFA_URL + endpoint`, `EFA_COMMON` merged in, 25 s timeout, raises on non-2xx). `reference_time(now=None) -> datetime` returns the next Tuesday strictly after `now.date()` at 08:00 Europe/Berlin. `get_oepnv(lat, lon, *, destinations=None) -> Optional[dict]`:

```python
{"reference": {"date": "2026-09-08", "weekday": "Dienstag", "window": "07:00–09:00"},
 "stops": [{"id": "de:05113:9530", "name": "Rüttenscheider Stern", "distance_m": 40, "products": ["U-Bahn", "Straßenbahn", "Bus"],
            "classes": [2, 4, 5], "rail": True, "lat": 51.4376, "lon": 7.0055}, …],   # by distance, ≤ _MAX_STOPS
 "lines": [{"line": "U11", "product": "U-Bahn", "stop": "Rüttenscheider Stern", "destinations": ["Essen Messe W.-Süd/Gruga", "GE Buerer Str."],
            "departures_2h": 16, "headway_min": 7.5}, …],   # merged over the _DM_STOPS nearest stops, by departures desc
 "trips": [{"name": "Essen Hbf", "kind": "fixed" | "custom", "duration_min": 7, "interchanges": 0, "walk_min": 3,
            "legs": ["U11"], "departure": "07:53", "arrival": "08:00"}, …],   # fixed first, then custom; None duration when no journey
 "nearest_rail_m": 40 | None, "rating": "Sehr gut", "rating_color": "green", "errors": {}}
```

`stops` come from `XML_COORD_REQUEST` (`coord=lon:lat:WGS84[dd.ddddd]`, `inclFilter=1`, `radius_1=STOP_RADIUS_M`, `type_1=STOP`), `rail = bool(RAIL_CLASSES & classes)`. `lines` from one `XML_DM_REQUEST` per nearest-three stop (`type_dm=stop`, `name_dm=<id>`, `mode=direct`, `itdDate=YYYYMMDD`, `itdTime=0700`, `limit=120`, `useRealtime=0`): `stopEvents` are grouped by `transportation.number`, only planned departures inside the two-hour window count, `headway_min = round(120 / departures_2h, 1)`, and the same line seen at several stops keeps the stop with the most departures. `trips` from `XML_TRIP_REQUEST2` per destination (`type_origin=coord`, `name_origin=lon:lat:WGS84[dd.ddddd]`; fixed → `type_destination=stop&name_destination=<id>`, custom → `type_destination=coord&name_destination=lon:lat:WGS84[dd.ddddd]`; `itdDate`, `itdTime=0800`, `itdTripDateTimeDepArr=dep`, `calcNumberOfTrips=3`, `useRealtime=0`): the journey with the smallest departure→arrival span wins; `walk_min` sums `footpath` legs; `legs` lists `transportation.number` of non-footpath legs; times are converted from UTC to Europe/Berlin `HH:MM`. Custom destinations are `IMPORTANT_LOCATIONS` (`work`, `family`) entries with an address, geocoded via `geocoding.geocode_with_precision(address)` — a failed geocode is skipped (recorded in `errors["geocode:<name>"]`), capped at `_MAX_CUSTOM_DESTINATIONS`. `destinations=` overrides the config list in tests (`[(name, ("stop", id) | ("coord", lat, lon))]`).

Rating on `nearest_rail_m` (nearest stop with `rail`), `nearest_m` (any stop) and `hbf_min` = min `duration_min` of the Essen/Bochum Hbf trips: rail ≤ 400 m and hbf ≤ 20 → `Sehr gut`/green; rail ≤ 800 m or hbf ≤ 30 → `Gut`/green; any stop ≤ 600 m → `Mäßig`/yellow; stops present but nothing closer → `Gering`/orange; no stops at all → `Keine Haltestelle im Umkreis von 600 m`/orange. No stops **and** no trip with a duration → return `None` (outside VRR). A part that fails lands in `errors[part]` with the other parts kept; all three failing raises.

### 3.3 `backend/infrastruktur_service.py`

```python
OVERPASS_URLS = ("https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter")
DISCODATA_URL = "https://discodata.eea.europa.eu/sql"
USER_AGENT = "HouseHunter/1.0"
R_LINES, R_SUBSTATION, R_WIND, R_MAST, R_PIPELINE, R_INDUSTRIAL, R_IED = 500, 500, 1500, 300, 300, 300, 2000
HV_MIN_V = 110_000
PIPELINE_HAZARD = {"gas", "oil", "hydrogen", "ethylene", "propylene", "oxygen", "chlorine", "ammonia", "fuel", "petroleum"}
```

Monkeypatch points: `_overpass(query) -> dict` (POST `data=`, `User-Agent`, retry/mirror as in §2) and `_discodata(sql) -> list[dict]` (GET `DISCODATA_URL?query=&p=1&nrOfHits=2000`, returns `results`). `get_infrastruktur(lat, lon) -> Optional[dict]`:

```python
{"power_lines": [{"name": "110kV Bochum-Eppendorf+Eppendorf-Hattingen" | None, "voltage_kv": 380, "voltages": [380, 220, 110],
                  "kind": "hochspannung" | "mittelspannung", "underground": bool, "distance_m": 132.0}, …],   # ≤ 500 m, by distance
 "substations": [{"name": "Umspannwerk Eppendorf", "voltage_kv": 110, "distance_m": 410.0}, …],  # ≥ 110 kV only
 "trafo_count": 4,                                                                                   # < 110 kV substations within 500 m
 "wind": [{"name": str | None, "distance_m": 900.0}], "masts": [{"name": str | None, "kind": "mast" | "tower", "distance_m": 120.0}],
 "pipelines": [{"name": "Boye" | None, "substance": "gas" | None, "hazardous": bool, "location": "underground" | "overground" | None, "distance_m": 55.0}],
 "industrial_landuse_m": 80.0 | None,                                                                 # nearest landuse=industrial polygon within 300 m (0 = inside)
 "ied_sites": [{"name": "Evonik Operations GmbH", "city": "Essen", "sectors": ["Chemicals", "Other waste management"], "year": 2024, "distance_m": 1180.0}, …],  # ≤ 2 km, ≤ 10
 "seveso_note": "NRW veröffentlicht keine Geodaten zu Störfallbetrieben (Seveso III). Auskunft: Bezirksregierung Düsseldorf (Essen) bzw. Arnsberg (Bochum).",
 "rating": "Belastung", "rating_color": "red", "errors": {}}
```

Overpass query (one request, `[out:json][timeout:40]`): `way["power"~"^(line|minor_line|cable)$"](around:500)`, `nwr["power"="substation"](around:500)`, `nwr["generator:source"="wind"](around:1500)`, `nwr["man_made"~"^(mast|tower|communications_tower)$"]["tower:type"!="cooling"](around:300)`, `way["man_made"="pipeline"](around:300)`, `way["landuse"="industrial"](around:300)`; `out tags geom;` — for nodes `geom` yields `lat/lon`, for ways the `geometry` list. `voltages` = every integer in `voltage` split on `;`, `voltage_kv = max // 1000`; `kind = "hochspannung"` when `max ≥ HV_MIN_V`, else `mittelspannung` (a `minor_line` without a voltage tag is `mittelspannung` with `voltage_kv None`); `underground = power == "cable" or location == "underground"`. Ways with fewer than two coordinates are skipped. Pipelines: `hazardous = substance in PIPELINE_HAZARD`; `water`/`sewage`/`steam`/`heat`/`district_heating` and unknown are not hazardous.

IED: `SELECT InspireSiteId, siteName, cities, eea_activities, Site_reporting_year, x_4258, y_4258 FROM [IED].[latest].[SiteMap] WHERE countryCode='DE' AND x_4258 BETWEEN {lon-0.03} AND {lon+0.03} AND y_4258 BETWEEN {lat-0.02} AND {lat+0.02}`; keep the row with the highest `Site_reporting_year` per `InspireSiteId`; `sectors` = distinct comma-split `eea_activities` in order; haversine ≤ `R_IED`, sorted, capped at 10.

Rating (first match): hochspannung line (not underground) ≤ 50 m, wind ≤ 500 m, or IED ≤ 300 m → `Belastung`/red; hochspannung ≤ 200 m, substation ≤ 200 m, hazardous pipeline ≤ 50 m, mast ≤ 100 m, wind ≤ 1000 m, IED ≤ 1000 m, or `industrial_landuse_m == 0` → `Erhöht`/orange; anything at all found (any list non-empty, `industrial_landuse_m` not None) → `Hinweise`/yellow; nothing → `Unauffällig`/green. `osm` failing → `errors["osm"]`, lists empty, rating computed from the rest (the card shows the error); both parts failing → raise. Both parts empty *and* no error → still a dict (`Unauffällig`), never `None` — OSM coverage is global.

## 4. Registry entries

| key | title | icon | timeout | tier | source line |
|---|---|---|---|---|---|
| `denkmal` | Denkmalschutz | 🏛️ | 25 | parcel | RVR Geoportal Ruhr — Denkmäler (INSPIRE WFS) · Untere Denkmalbehörden Essen/Bochum |
| `oepnv` | ÖPNV-Erreichbarkeit | 🚋 | 45 | area | VRR EFA-Fahrplanauskunft (efa.vrr.de) — Fahrplan-Stichtag, kein Echtzeit |
| `infrastruktur` | Hochspannung, Leitungen & Industrie | ⚡ | 40 | area | OpenStreetMap (Overpass) · EEA Industrial Emissions Portal (IED/E-PRTR) |

`_fetch_*` pass the service dict through; `None` → `Empty` with: denkmal `"Kein Denkmal-Datensatz für diesen Ort (außerhalb des RVR-Verbandsgebiets)"`, oepnv `"Keine VRR-Haltestellen im Umkreis und keine Verbindung gefunden (außerhalb des VRR?)"`, infrastruktur never `None`. New order:

`boris, boris_trend, flood, starkregen, noise, bergbau, gfnp, schutzgebiete, planning_essen, planning_bochum, denkmal, amenities, oepnv, zensus, energie, breitband, infrastruktur, air_quality, btw, commute`

`SERVICE_TIER` gains `"denkmal": "parcel"`, `"oepnv": "area"`, `"infrastruktur": "area"`.

## 5. Partials

- `_denkmal.html`: chip; "Auf dem Grundstück" block listing `on_site` items (kind badge, name, since, link) with a one-line consequence per kind (Baudenkmal: Genehmigungspflicht für Umbauten/Fenster/Dämmung, dafür erhöhte AfA §7i EStG; Bodendenkmal: Erdarbeiten genehmigungspflichtig; Denkmalbereich: Erscheinungsbild geschützt); "Im Umkreis von 300 m" list with distance; counts per kind; authority link; footnote "Umgebungsschutz: Auch Bauvorhaben *neben* einem Denkmal brauchen eine Erlaubnis (§ 9 DSchG NRW)".
- `_oepnv.html`: chip + reference line ("Fahrplan Di 08.09.2026, 07–09 Uhr"); stops table (name, products as chips, distance); lines table (line, product, Takt "alle 7,5 min", 16 Abfahrten/2 h, Richtungen); trips table (destination, duration, Umstiege, Linien, Fußweg); footnote on the fixed weekday snapshot and `errors` rendered as a muted line.
- `_infrastruktur.html`: chip; sections rendered only when non-empty — Hochspannungsleitungen (voltage chip, distance, name, "erdverlegt"), Umspannwerke + "n Trafostationen im Umkreis", Windkraft, Sendemasten, Pipelines (substance, hazardous mark), Gewerbe-/Industriefläche, Industrieanlagen (name, sectors, distance, year); grey callout with `seveso_note`; footnote "OSM-Vollständigkeit variiert; Abstände zur nächsten Kante".

Colours use `$store.app.getAirQualityColor(color)`. After editing partials run `npx --yes tailwindcss@3 -c tailwind.config.js -i frontend/static/css/tailwind.input.css -o frontend/static/css/tailwind.css --minify` (committed content-scanned build).

## 6. Testing

Hermetic — the HTTP functions above are monkeypatched:

- `tests/test_denkmal_service.py`: kind from `inspire_id`, scope from kategorie/kind, dedupe of Bochum coordinate-suffixed ids, polygon `contains` → on_site/0 m, point ≤ 25 m → on_site, ordering, cap, links (Bochum pdf preferred, Essen htm), rating ladder, outside RVR bbox → `None` without HTTP.
- `tests/test_oepnv_service.py`: `reference_time` (Tuesday, strictly after today, 08:00 Berlin), stops parsing (products/rail/distance), DM grouping (window filter, headway, best stop per line), trip selection (shortest span, walk, legs, local times), custom destinations via injected list, rating ladder, part isolation, all-empty → `None`.
- `tests/test_infrastruktur_service.py`: voltage parsing (`380000;220000;110000`, `minor_line` without voltage), line distance in metres, underground flag, substation split (≥ 110 kV listed, rest counted), pipeline hazard, industrial landuse inside → 0, IED latest-year reduction + distance cap + sectors, rating ladder, Overpass 429 → retry → mirror, part isolation.
- `tests/test_analysis_sections.py`: order updated; pass-through + `Empty` per fetch; tier assertions.
- Live smoke (manual): dev instance on :8011, `browser_check2.py` on Rüttenscheid, Werden, Bochum Hbf, Bochum Weitmar, Essen-Karnap and Berlin.

## 7. Documentation

CLAUDE.md gets a "Denkmalschutz, ÖPNV & Infrastruktur cards (2026-09-04)" paragraph (sources, the RVR id/dedupe rule, the EFA reference-time rule, the Overpass retry/mirror and the missing-Seveso-data fact); HANDOVER.md a work-log entry.
