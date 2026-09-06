# Tier-2 data sources — design (2026-09-06)

Follow-up to `2026-09-05-tier1-sources-design.md`. Every endpoint, layer, field and sample value below was
read from a live response on 2026-09-06 unless marked otherwise. Same global rules as Tier 1 (CLAUDE.md +
the Tier-1 spec's "Global rules"): `headers=headers()` on every call, German copy, one HTTP function per
module as monkeypatch point, hermetic tests, `cache_version` bump when a card's data changes.

## Scope

| # | key | change | tier | kind | source |
|---|---|---|---|---|---|
| 1 | `bergbau` (extended) | + Bergbauberechtigungen at the point | area | static crop in repo | opengeodata NRW `BergbauberechtigungenNRW_EPSG25832_Shape.zip` (dl-de/by-2-0, 860 KB) |
| 2 | `starkregen` (extended) | + Gelände (height, Tieflage/Hanglage, slope) | parcel | live WCS | Geobasis NRW `wcs_nw_dgm` (1 m DGM, dl-de/zero-2-0) |
| 3 | `noise` (extended) | + Fluglärm DUS/EMH (Essen), Ruhige Gebiete (Essen, Bochum) | area | live ArcGIS | geo.essen.de `Laermkarte_aktuell`, `Ruhige_Gebiete`; Bochum `Laermkartierung_Stufe4` |
| 4 | `ladesaeulen` (new) | E-Ladepunkte im Umkreis | area | static crop in repo | BNetzA Ladesäulenregister CSV (CC BY 4.0, monthly) |
| 5 | PDF figure "Der Ort im Wandel" | 4 historic map panels | report only | live WMS | Geobasis NRW Uraufnahme, Neuaufnahme, historische DOP 1952, DOP (dl-de/zero-2-0) |
| 6 | PDF figure "Grün und Hitze" | 2 climate panels with legend images | report only | live WMS | RVR Umweltmonitoring `veg_schirm`, `oftemp` (lizenzkostenfrei) |
| 7 | `bergbau` (extended, data-gated) | + Bodenbewegung (EGMS vertical velocity) | area | static crop in repo, built from a user-downloaded tile | Copernicus EGMS L3 Ortho `EGMS_L3_E41N31_100km_U_*.tif` (free EU Login) |

Out of scope until data arrives (not plannable, tracked in the plan's preamble): Altlasten Essen/Bochum
(e-mail requests sent 2026-09-06), Hebesätze (current values only via a registered Regionaldatenbank
account, table 71231-03-01-5; the open Destatis workbook ended with the 2022 edition, i.e. before the 2025
Grundsteuer reform), Sozialatlas Essen (InstantAtlas web app only), election results per Wahlbezirk
(Bochum only). Dropped: an RVR Stadtklima *value* card — the RVR raster WMS answers GetFeatureInfo with
geometry only and its legends are continuous colour ramps (146 colours in a 88×50 px legend), so pixel
decoding would be guesswork; the layers are used as images instead (#6).

## 1. Bergbauberechtigungen

Shapefile `bergbaufd.berechtigungen_v_inspire.shp`, EPSG:25832, 5,361 polygons statewide, 630 inside the
Essen/Bochum window `(6.85, 51.33, 7.40, 51.56)`. Fields: `FELDESNUMM` 4000138701, `BERECHTIGU`
("aufrechterhaltenes Bergwerkseigentum" 572 · "Bewilligung" 33 · "Erlaubnis zu gewerblichen Zwecken" 24 ·
"Erlaubnis zu wissenschaftlichen Zwecken" 1), `BODENSCHAT` (Steinkohle 395, Eisenerz 53, Kohlenwasserstoffe
45, Eisenstein 42, Bleierz 17, Sole 14, Erdwärme 13, …), `FELDESNAME` "Neu Essen", `FELDESGROE`
"140 110 991 m²", `ENTSTEHUNG` "23.01.1791", `LAUFZEIT_V/_B`, `ERLOSCHEN` ja/nein, `RECHTSINHA`
("RAG AKTIENGESELLSCHAFT" 254, "E.ON SE" 107, "Auskunft erteilt Bezirksregierung Arnsberg, Dez. 64" 64, …).
Rüttenscheid test point: Bergwerkseigentum "Neu Essen" (Eisenerz, 1791, TRATON SE) and the Erdwärme
Erlaubnis "Metropole Ruhr" (1,641 km², consortium). Build once: crop to the window, WGS84 GeoJSON,
`redat/data/bergbauberechtigungen.geojson.gz` (~200 KB). Lookup: polygons containing the point, sorted
Bergwerkseigentum/Bewilligung first, Erlaubnisse last; Erdwärme-Erlaubnisse are labelled "Aufsuchung"
(exploration, not mining). Data shape added to the bergbau card:
`"berechtigungen": [{"feld": "Neu Essen", "art": "aufrechterhaltenes Bergwerkseigentum", "kurz": "Bergwerkseigentum",
"bodenschatz": "Eisenerz", "inhaber": "TRATON SE", "seit": "23.01.1791", "erloschen": false, "groesse": "140 110 991 m²"}]`,
`"berechtigungen_error": null`. Copy: a Berechtigung is a right, not evidence of workings; the GDU
Planquadrat above stays the hazard signal. `cache_version` bergbau → 2.

## 2. Gelände (DGM)

WCS 2.0.1 `https://www.wcs.nrw.de/geobasis/wcs_nw_dgm`, coverage `nw_dgm`, axis labels `x y` (EPSG:25832),
`GetCoverage&COVERAGEID=nw_dgm&SUBSET=x(<xmin>,<xmax>)&SUBSET=y(<ymin>,<ymax>)&FORMAT=image/tiff` →
float32 GeoTIFF, 1 px = 1 m, row 0 = north (verified: 100 m box at Rüttenscheid → 100×100 px, 108.4–112.8 m
NHN, 18 KB). The slope WCS only serves styled RGB, so slope is derived from the DGM. Request a 200 m box
(200×200 px, ~70 KB). Derived: `hoehe_m` (centre pixel), `min_100m`, `max_100m` (whole tile), `min_25m`,
`max_25m` (central 50×50 px), `ueber_tiefstem_100m = hoehe − min_100m`, `unter_hoechstem_100m = max_100m −
hoehe`, `neigung_pct` = 100·√(dz/dx² + dz/dy²) with dz over ±5 px around the centre. `lage`: "Hanglage" when
neigung ≥ 10 %, "Tieflage" when hoehe − min_25m ≤ 0.3 and max_100m − hoehe ≥ 1.5, "Kuppenlage" when hoehe −
min_100m ≥ 1.5 and max_100m − hoehe ≤ 0.3, else "eben". Attached to the starkregen card as
`"gelaende": {...}` / `"gelaende_error"` (isolated). `cache_version` starkregen → 2.

## 3. Fluglärm & Ruhige Gebiete

Essen `Laermkarte_aktuell/MapServer` layers `4` Flugverkehr EMH (L_DEN), `5` Flugverkehr DUS (L_DEN; two
polygons, 20 km² in Kettwig/Werden, classes `Lden5559`, `Lden6064`), `11` Flugverkehr DUS (L_night);
fields `CATEGORY`, `PEGEL` (LDEN/LNIGHT), `TEXT` "ab 55 bis 59 dB(A)". Ruhige Gebiete: Essen
`Ruhige_Gebiete/MapServer/26` (`NAME`, `BESCHREIBU`, `CATEGORY`), Bochum
`Laermkartierung_Stufe4/MapServer/20` (`NAME`, `ART`, `BEZIRK`; 94 polygons; the server rejects
`resultRecordCount` — never send it). All point queries, city-gated by the bboxes already used in Tier 1
(Essen 6.89–7.14 / 51.35–51.53, Bochum 7.10–7.35 / 51.40–51.53). Added to the noise card:
`"flug": {"airport": "DUS"|"EMH", "day": "ab 55 bis 59 dB(A)"|null, "night": ...} | null`,
`"ruhiges_gebiet": {"name": ..., "stadt": "Essen"|"Bochum"} | null`, `"extra_error"`. `cache_version` noise → 2.

## 4. Ladesäulen

CSV `https://data.bundesnetzagentur.de/Bundesnetzagentur/DE/Fachthemen/ElektrizitaetundGas/E-Mobilitaet/
Ladesaeulenregister_BNetzA_<YYYY-MM-DD>.csv` (the date is in the file name; the page
`bundesnetzagentur.de/…/Ladesaeulenkarte/start.html` links the current one; 55 MB, UTF-8 BOM, `;`, decimal
comma). Header is the line starting with `Ladeeinrichtungs-ID` (line 10); columns used: `Betreiber`,
`Status` (In Betrieb / In Wartung), `Art der Ladeeinrichtung` (Normalladeeinrichtung / Schnellladeeinrichtung),
`Anzahl Ladepunkte`, `Nennleistung Ladeeinrichtung [kW]`, `Straße`, `Hausnummer`, `Postleitzahl`, `Ort`,
`Breitengrad`, `Längengrad`. Crop by **bbox**, not by `Ort` (a Berlin row carries Ort "Essen"). Window rows
≈ 1,270 → `redat/data/ladesaeulen.json.gz` rows `[lat, lon, betreiber, schnell(0/1), punkte, kw, adresse]`.
Card `ladesaeulen` (area, after `energie`): `radius_m` 1000, `anzahl_500m`, `anzahl_1000m`, `ladepunkte_1000m`,
`schnell_1000m`, `naechste` (5 nearest: name, distance_m, punkte, kw, schnell, adresse), `rating`:
≥ 1 charger ≤ 300 m green "Ladepunkt in Gehweite", ≤ 1000 m yellow "Ladepunkt im Umkreis", none orange
"Kein öffentlicher Ladepunkt im Umkreis von 1 km". Empty outside the window.

## 5. PDF figure "Der Ort im Wandel"

Four 480×360 px panels, 600 m wide window, same pipeline as `report/noise_map.py` (basemap not needed —
the layers are opaque): Uraufnahme `wms_nw_uraufnahme` layer `nw_uraufnahme_rw` (1836–1850),
Neuaufnahme `wms_nw_neuaufnahme` layer `nw_neuaufnahme` (1891–1912), historic orthophoto
`wms_nw_hist_dop` layer `nw_hist_dop_1952` (Essen/Bochum are covered 1951–1954; 1956–1998 tiles are
blank at Essen; fall back through 1951, 1953, 1954 when the 1952 tile is blank), current `wms_nw_dop`
layer `nw_dop_rgb`. GetMap `CRS=EPSG:25832`, `FORMAT=image/png`, `STYLES=`. Pin + 100 m scale bar + title
box (year) drawn with Pillow. Attached as `ctx["history_maps"]` when `flurstueck` or `bergbau` is in the
body; rendered at the end of `report/_flurstueck.html`. Copy: "Zeche, Halde, Gleisanlage oder Fabrik auf
einem alten Bild ist ein Altlastenverdacht — Auskunft bei der Unteren Bodenschutzbehörde."

## 6. PDF figure "Grün und Hitze"

RVR Umweltmonitoring WMS (`https://services-rvr.geoportal.ruhr/umon/<svc>`): `veg_schirm` layer
`beschirmungsgrad` (10 m, share of area under vegetation) and `oftemp` layer `Oberflaechentemperatur_1330`
(MODIS 1 km, summer median 13:30, `STYLE=day`). GetMap works as above; GetLegendGraphic needs
`SLD_VERSION=1.1.0` (`&LAYER=<layer>&FORMAT=image/png&STYLE=<style>`; 88×50 / 113×70 px ramps). Two 480×360
panels over a 2 km window (the temperature layer is 1 km pixels) plus the two legend PNGs embedded next
to them. Attached as `ctx["climate_maps"]` when `zensus` is in the body; rendered at the end of
`report/_zensus.html`.

## 7. Bodenbewegung (EGMS) — data-gated

Copernicus EGMS L3 Ortho vertical component: tile `EGMS_L3_E41N31_100km_U_<from>_<to>_<v>.tif` covers all
of Essen and Bochum (LAEA EPSG:3035, Essen ≈ 4 112 774 / 3 150 851). 100 m raster of the mean vertical
velocity in mm/year (positive = uplift). Download needs a free EU Login at
`https://egms.land.copernicus.eu/` (Explorer → area → "Download" → tile list → L3 Ortho U, or the insar-api with a CLMS token — tile 2020-2024 downloaded 2026-09-06). Build script
crops the GeoTIFF (read with Pillow, georeference from TIFF tags 33550 ModelPixelScale and 33922
ModelTiepoint) to the Essen/Bochum window → `redat/data/egms_vertical_velocity.json.gz` (sparse cells like
the Zensus grid, EPSG:3035 cell centres). Lookup: cell value, 3×3 mean, min/max within 500 m. Classes:
|v| < 2 mm/a "stabil" green, 2–5 "leichte Bewegung" yellow, 5–10 "deutliche Bewegung" orange, > 10
"starke Bewegung" red; sign → Senkung/Hebung (Grubenwasseranstieg shows as uplift). Attached to the
bergbau card as `"bodenbewegung": {...} | null` with a hint when the file is absent. Until the user
downloads the tile the card shows "EGMS-Daten nicht installiert".
