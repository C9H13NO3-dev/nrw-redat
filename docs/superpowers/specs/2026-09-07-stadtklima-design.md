# Tier 4 — Stadtklima statewide: Design

**Date:** 2026-09-07 · **Status:** approved by the owner ("Yes please!") · **Plan:** `docs/superpowers/plans/2026-09-07-stadtklima.md`

## 1. Problem

The PDF figure "Grün und Hitze" (`redat/report/climate_maps.py`) draws two RVR Umweltmonitoring layers
(Beschirmungsgrad, Oberflächentemperatur) that exist only for the Regionalverband Ruhr. For Bonn and every other
address outside the Ruhr the two panels read "Karte nicht verfügbar". There is no statewide copy of those exact
layers, but two statewide services cover the same questions — and one of them returns real values.

## 2. Services (verified live 2026-09-07)

### 2.1 LANUV Klimaanalyse NRW 2026 — WMS with GetFeatureInfo

`https://www.wms.nrw.de/umwelt/klimaanpassung_klimaanalyse` (WMS 1.3.0, CRS EPSG:25832 among others, released
April 2026; FITNAH-3D mesoscale model after VDI 3787 Blatt 1; values 2 m above ground for a typical and an
extreme summer day). Layers are numbered; titles are CDATA. `GetFeatureInfo` with `INFO_FORMAT=application/geo+json`
returns one feature whose `properties` carry the value:

| Layer | Group path | Property → meaning |
|---|---|---|
| `59` | Klimatopkarte › Klimatope (vector) | `Klimatoptyp` (e.g. "Vorstadtklima", "Stadtklima", "Gewässerklima") |
| `54` | Klimaanalysekarte (tags) › Typischer Sommertag › Thermische Belastung – PET | `Classify.Pixel Value` (°C PET), `Classify.Class value` 1–6 |
| `52` | Klimaanalysekarte (tags) › Extremer Sommertag › Thermische Belastung – PET | same |
| `38` | Klimaanalysekarte (nachts) › Typischer Sommertag › Lufttemperatur | `Classify.Pixel Value` (°C, 4 Uhr) |
| `29` | Klimaanalysekarte (nachts) › Extremer Sommertag › Lufttemperatur | same |

`Classify.Pixel Value` is the string `"NoData"` where the model has no cell (water, outside NRW). Measured: Bonn
Käferberg → Vorstadtklima, PET 38.3 °C typical / 43.1 °C extreme, night 16.2 / 20.5 °C; Essen Rüttenscheid →
Stadtklima, PET 40.3 / 44.6 °C, night 16.6 / 20.8 °C. PET classes from the service legend (layer 54, 276 × 126 px):
`> 13–18` leichter Kältestress · `> 18–23` kein thermischer Stress · `> 23–29` leichte Wärmebelastung · `> 29–35`
moderate Wärmebelastung · `> 35–41` starke Wärmebelastung · `> 41` extrem starke Wärmebelastung.
`GetMap` on `54` renders the class raster (4–6 colours) in EPSG:25832; `GetLegendGraphic` (SLD_VERSION 1.1.0) works.

### 2.2 Copernicus HRL Tree Cover Density 2018 — EEA WMS (image only)

`https://image.discomap.eea.europa.eu/arcgis/services/GioLandPublic/HRL_TreeCoverDensity_2018/ImageServer/WMSServer`,
layer `HRL_TreeCoverDensity_2018:TCD_MosaicSymbology` (10 m, 0–100 % canopy, EU-wide, CLMS free licence). Offers
only `EPSG:3857`/`EPSG:4326` — a request in EPSG:3035/25832 returns an empty transparent image. In Web Mercator a
2 km ground window at latitude φ is `2000 / cos φ` metres wide. Its GetLegendGraphic is a 236 × 2040 px ramp,
useless in print → the panel carries a caption instead of a legend.

## 3. Design

### 3.1 New card `stadtklima` — "Stadtklima (Klimaanalyse NRW)"

`redat/sources/stadtklima.py`: one HTTP seam `_featureinfo(layer, lat, lon) -> dict` (GetFeatureInfo, 100 × 100 px
tile ±50 m around the point in EPSG:25832, `I=J=50`, `FEATURE_COUNT=1`, first feature's `properties` or `{}`);
`get_stadtklima(lat, lon)` queries the five layers concurrently (per-layer error isolation) and returns

```
{"klimatop": str|None,
 "pet_typisch": float|None, "pet_extrem": float|None,          # °C, one decimal
 "nacht_typisch": float|None, "nacht_extrem": float|None,      # °C air temperature 4 Uhr
 "klasse_typisch": str|None, "klasse_extrem": str|None,        # PET class label (section 2.1)
 "rating": str, "rating_color": str,                            # from pet_typisch (fallback pet_extrem), else "unbekannt"/"gray"
 "errors": {layer_key: message},
 "hinweis": "Modellwerte (FITNAH-3D, 2 m über Grund) für einen typischen bzw. extremen Sommertag — kein Messwert am Haus."}
```

Rating colours: extrem starke → red, starke → orange, moderate → yellow, everything cooler → green. `None` outside
NRW (`redat.core.nrw.in_bbox`). The fetcher raises `Empty("Keine Klimaanalyse-Daten für diesen Ort")` when
`klimatop` and both PET values are None and no error occurred (open water etc.). Card: tier `area`, timeout 15 s,
registered directly after `zensus`, `cache_version` 1, source string "LANUV Klimaanalyse NRW 2026 — FITNAH-3D-Modell
(WMS GetFeatureInfo)". Partials: website shows the rating chip, Klimatop, a two-column table typical/extreme day
(PET + class, Nachttemperatur), the hinweis and per-layer error line; report likewise. Cards: 29.

### 3.2 "Grün und Hitze" statewide

`climate_maps.render_climate_maps` keeps the RVR panels inside `RVR_BBOX_WGS84` and outside it renders
`baumkronen` (Copernicus TCD 2018, EPSG:3857 window, no legend) and `pet` (Klimaanalyse layer 54, EPSG:25832, with
legend). The result gains `"variant": "rvr" | "nrw"`; the attribution string follows the variant; the Zensus
report partial's footnote explains the panels per variant. Same 2 km window, concurrency and error isolation.

## 4. Non-goals

Surface temperature statewide (no free 1 km LST service with a usable style found); Kaltluft layers (the flow
vectors need cartography, not a card value); a website version of the figure.

## 5. Cache versions / counts

New `stadtklima` 1; `zensus` unchanged (the card's data does not change, only the PDF figure beside it). Cards 29.
