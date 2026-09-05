# Tier-1 data sources — design (2026-09-05)

Research result of 2026-09-05: which open geodata a Ruhrgebiet house buyer needs that the 20 existing cards
do not cover, restricted to sources that were verified live from this host on 2026-09-05 and that are open
(dl-de/zero, dl-de/by, CC BY, CC0) or free of charge with no key. Every endpoint, layer id, field name and
sample value below was read from a real response on that date — the implementer should not need to
re-discover anything, but should re-verify any detail that fails.

## Scope

Six new cards and three extensions of existing cards, in this order of the card list (insertion order in
`redat/core/sections.py` == card order on the website and in the PDF):

| # | key | title | tier | kind | source |
|---|---|---|---|---|---|
| 1 | `flurstueck` (new) | Flurstück & Gebäude (ALKIS) | parcel | live WFS + Essen ArcGIS | Geobasis NRW ALKIS vereinfacht (dl-de/zero-2-0); Stadt Essen Baulasteninformation |
| 2 | `boris`, `boris_trend` | unchanged | | | |
| 3 | `irw` (new) | Immobilienrichtwerte | parcel | live WMS GetFeatureInfo | BORIS NRW `wms_nw_irw` (dl-de/zero-2-0) |
| 4 | `flood` (extended) | + Überschwemmungsgebiete (rechtlich) | parcel | live WMS GetFeatureInfo | Land NRW `umwelt/wasser/uesg` |
| 5 | `baugrund` (new) | Baugrund & Versickerung (BK50) | area | live WMS GetFeatureInfo (HTML) + Essen ArcGIS | GD NRW `gd/bk050` (dl-de/by-2-0); Stadt Essen kf-Werte |
| 6 | `radon` (new) | Radon | area | live WFS (GeoJSON) | BfS `imis.bfs.de/ogc/opendata/ows` (dl-de/by-2-0) |
| 7 | `planning_essen` (extended) | + Satzungen, Sanierungsgebiete | parcel | live ArcGIS | geo.essen.de |
| 8 | `planning_bochum` (extended) | + Stadterneuerungsgebiete | parcel | live ArcGIS | geoservicekkm.bochum.de |
| 9 | `schulen` (new) | Schulen & Sozialindex | area | static grid (repo) + Bochum ArcGIS | Schulministerium NRW CSV + opengeodata Schulen shape (dl-de/by-2-0); Bochum Grundschulbezirke |
| 10 | `unfaelle` (new) | Verkehrsunfälle (Unfallatlas) | area | static grid (repo) | Statistische Ämter, Unfallatlas (dl-de/by-2-0) |

Not in scope (Tier 2 of the research, needs data requests or heavier builds): Altlasten Essen/Bochum,
Grubenwasser/Bodenbewegung, RVR Stadtklima, Hebesätze, Ladesäulen, DGM/Hanglage, Bochum election results,
Sozialatlas scraping, historical maps, Bergbauberechtigungen, Essen Kitas (Geoapify already gives the
nearest Kindergarten).

## Global rules (from CLAUDE.md, restated because every task depends on them)

- Every outbound call: `httpx.get(..., headers=headers())` from `redat.http`, never bare. Never `verify=False`.
- All UI copy German. Alpine store name `app` in web partials.
- Envelope contract unchanged. A source module raises for a hard failure (→ `error`), returns `None` for
  "no data here" (→ `empty`), or the fetch raises `Empty("…")` with a German message.
- Cache: bump `Section.cache_version` when a card's `data` shape or meaning changes (`flood`,
  `planning_essen`, `planning_bochum` go to 2). New cards start at 1. Live cards take the 30-day default.
- One HTTP function per module is the monkeypatch point (`_wfs_gml`, `_featureinfo`, `_query`, …); tests
  never touch the network.
- New cards need, in one task: source module + tests, `SECTIONS` entry, `SERVICE_TIER` entry, `SOURCES`
  row in `sources_meta.py`, `templates/analysis/_<key>.html`, `templates/report/_<key>.html`,
  `builder.SUMMARY[<key>]`, an `ok` envelope in `tests/fixtures/report_envelopes.json`, and the updated
  key lists in `tests/test_analysis_sections.py::test_registry_keys_and_order` and `tests/test_tiers.py`.

## 1. `flurstueck` — Flurstück & Gebäude

**Why:** the parcel's official area replaces the hand-typed `plot_size_m2`, the building footprint gives
the Überbauungsgrad, and the Baulasten (Essen only) are otherwise a paid written Auskunft.

**Source A — ALKIS vereinfacht WFS.** `https://www.wfs.nrw.de/geobasis/wfs_nw_alkis_vereinfacht`,
WFS 2.0.0, licence dl-de/zero-2-0. Feature types `ave:Flurstueck`, `ave:GebaeudeBauwerk`, `ave:Nutzung`
(also `ave:FlurstueckPunkt`, `ave:KatasterBezirk`, `ave:NutzungFlurstueck`, `ave:VerwaltungsEinheit`, unused).
The service sits behind an "OGC Proxy" that **rejects** `OUTPUTFORMAT=application/json`, any `CQL_FILTER`,
and `TYPENAMES` combined with `SRSNAME` — the working request is exactly:

```
SERVICE=WFS&VERSION=2.0.0&REQUEST=GetFeature&TYPENAMES=ave:Flurstueck
&BBOX=<xmin>,<ymin>,<xmax>,<ymax>,urn:ogc:def:crs:EPSG::25832&COUNT=50
```

Response is GML 3.2 (`application/gml+xml; version=3.2`). Namespaces: default
`http://repository.gdi-de.org/schemas/adv/produkt/alkis-vereinfacht/2.0`, `gml` =
`http://www.opengis.net/gml/3.2`, `wfs` = `http://www.opengis.net/wfs/2.0`. Each `wfs:member` holds one
feature; geometry is `<geometrie><gml:MultiSurface srsName="urn:ogc:def:crs:EPSG::25832"><gml:surfaceMember>
<gml:Polygon><gml:exterior><gml:LinearRing><gml:posList>x y x y …` (interiors as `gml:interior`).
Coordinates are EPSG:25832 metres, axis order x(East) y(North).

Flurstueck properties (verified at Herthastr. 4, Essen): `idflurst` DENW22AL800005He, `flstkennz`
`05314403900040______` (14 significant chars + underscores), `gemarkung` Rüttenscheid, `gemaschl` 053144,
`flur` 39, `flstnrzae` 40 (Zähler; `flstnrnen` Nenner may be absent), `gemeinde` Essen, `gmdschl` 05113000,
`kreis` Essen, `aktualit` 2026-02-17Z, `flaeche` 538.0, `abwrecht`, `lagebeztxt` "Herthastr. 4", `tntxt`
"Wohnbaufläche;538" (one or more `Nutzungsart;m²` entries; treat `|` as separator between entries).
GebaeudeBauwerk properties: `funktion` "Wohngebäude", `gebnutzbez` "Gebäude", `gfkzshh` "31001_1000",
`lagebeztxt`, `aktualit`. Nutzung properties: `nutzart` "Wohnbaufläche".

Lookup: BBOX ±1 m around the point → the Flurstueck polygon that `contains` the point, else the nearest
one within 5 m (geocodes land at the street edge), else `None`. Buildings: BBOX = parcel bounds; a
building is "on the parcel" when more than half of its footprint intersects the parcel polygon; the
footprint sum over on-parcel buildings / parcel area = Überbauungsgrad.

**Source B — Essen Baulasteninformation.**
`https://geo.essen.de/arcgis/rest/services/essen/Baulasteninformation/MapServer`, layers `0` "Baulasten
vorhanden" (21,410 polygons) and `1` "Baulasten ggf. vorhanden" (207). Query: standard ArcGIS `query` with
`geometry=<lon>,<lat>&geometryType=esriGeometryPoint&inSR=4326&distance=50&units=esriSRUnit_Meter&
spatialRel=esriSpatialRelIntersects&outFields=ART,FSK,BAULAST,TYP_BL,ALKIS_AMTL_FLAECHE&returnGeometry=false
&f=json`. Fields: `FSK` "05314403900040" (matches the 14 significant chars of ALKIS `flstkennz`), `ART`
"BauOrdnungsrecht / Zufahrt" (Rechtsgrund ` / ` Art; Art may be empty), `BAULAST` "9 / 604 / 1" (Blatt id),
`TYP_BL` "baulasten_aktuell". Seen ART values: Zufahrt, Abstandfläche, Grundstücksvereinigung, Überbauung,
notwendiger Stellplatz, Feuerwehrzufahrt, Zweiter Rettungsweg, Entwässerung, Erschließung, Anbauverpflichtung,
Bauverbot, Nutzungssicherung, Mehrwertverzicht, … Layer `2` (Blatt/Vermerk per Flurstück, 137k rows, mostly
blank) is not used. Coverage: Essen city only → outside the Essen bbox (lon 6.89–7.14, lat 51.35–51.53)
the sub-block is `None` with the message "nur für Essen verfügbar". The city calls the data "kostenlos,
unverbindlich, ohne Gewähr, wöchentlich aktualisiert" — the card must repeat that.

**Data shape (`data`):**

```json
{
  "flurstueck": {"id": "DENW22AL800005He", "kennzeichen": "05314403900040", "gemarkung": "Rüttenscheid",
                 "gemarkung_nr": "053144", "flur": 39, "nummer": "40", "flaeche_m2": 538.0,
                 "lage": "Herthastr. 4", "gemeinde": "Essen", "stand": "2026-02-17",
                 "nutzung": [{"art": "Wohnbaufläche", "m2": 538}], "distance_m": 0.0},
  "gebaeude": [{"funktion": "Wohngebäude", "lage": "Herthastr. 4", "grundflaeche_m2": 118.4, "on_parcel": true}],
  "grundflaeche_m2": 118.4, "ueberbauung_pct": 22.0,
  "nutzung_am_punkt": "Wohnbaufläche",
  "baulasten": {"status": "vorhanden", "on_parcel": [{"rechtsgrund": "BauOrdnungsrecht", "art": "Zufahrt", "blatt": "9 / 604 / 1", "kennzeichen": "05314403900040"}],
                "nearby": [{"rechtsgrund": "BauOrdnungsrecht", "art": "Abstandfläche", "blatt": "9 / 1126 / 1", "kennzeichen": "05314403800349"}],
                "radius_m": 50} ,
  "baulasten_error": null
}
```

`baulasten.status` ∈ `vorhanden` (layer 0 hit on this Flurstück), `moeglich` (layer 1 hit only), `keine`
(Essen, no hit), and `baulasten` is `null` outside Essen. `baulasten_error` carries the exception text when
the Essen query failed (the card still renders the parcel). Web card offers "Als Grundstücksgröße
übernehmen" when `plotSize` is empty: sets `plotSize = round(flaeche_m2)` and re-loads `boris`.

Empty: `Empty("Kein Flurstück an diesem Punkt (außerhalb NRW?)")`. Error: WFS unreachable.

## 2. `irw` — Immobilienrichtwerte

`https://www.wms.nrw.de/boris/wms_nw_irw`, WMS 1.3.0, GetFeatureInfo with
`INFO_FORMAT=application/vnd.esri.wms_featureinfo_xml` (same esri XML the WSG layer in `schutzgebiete.py`
uses). Value layers (all have MinScaleDenominator 56696, so the request must use a small BBOX — the
`schutzgebiete` pattern of a 0.002°×0.002° box at 101×101 px, ~2 m/px, works): `9` irw_gemischt_genutzt,
`12` irw_mehrfamilienhaeuser, `15` irw_reihen_doppelhaeuser, `18` irw_ein_zweifamilienhaeuser,
`21` irw_eigentumswohnungen (3 gewerbe, 6 büro not used). `1` irw_verfuegbarkeit says whether the
Gutachterausschuss publishes IRW at all (`STATUS` "Richtwerte verfuegbar" for Essen and Bochum).

Fields (IRW_Datenmodell.pdf): `IMRW` €/m² Wohnfläche (int), `STAG` "01.01.2026", `TEILMA` 1 ETW,
2 EFH/ZFH freistehend, 3 RH/DH, 4 MFH, 5 gemischt, 6 Büro, 7 Gewerbe; `ORTST`, `PLZ`, `WHNLA` Wohnlage
1 sehr gut … 8 sehr einfach (often blank), `BJ` Baujahr of the Normobjekt, `WHNFL` Wohnfläche (single value
or range "111-130"), `FLAE` Grundstücksfläche (single or range), `EGART` 1 freistehend, 2 DHH, 4 Reihenmittel,
5 Reihenend; `ANZEGEB` Wohnungen im Gebäude ("7-12"); `GABE` Gutachterausschuss; `UDOK_URL` PDF with the
Umrechnungskoeffizienten. Sample Rüttenscheid 2026: RH/DH 3950, EFH 4400, ETW 2800 €/m². Bochum Stiepel:
MFH 1400, RH/DH 3080, EFH 3350, ETW 2460. Dense inner-city points may return no polygon at all.

Data: `{"stichtag": "2026-01-01", "gutachterausschuss": "…", "werte": [{"teilmarkt": 3, "teilmarkt_label":
"Reihen-/Doppelhäuser", "eur_m2": 3950, "ortsteil": "Rüttenscheid", "plz": "45131", "wohnlage": null,
"normobjekt": {"baujahr": "1962", "wohnflaeche_m2": "130", "grundstueck_m2": "300", "anbauweise":
"Doppelhaushälfte", "wohnungen": null}, "doku_url": "https://…LGDIR_3_0510900_2026.pdf"}]}`, sorted by
`teilmarkt`. Empty when no value layer answers: `Empty("Keine Immobilienrichtwerte für diesen Ort")`.

## 3. `flood` extension — Überschwemmungsgebiete

`https://www.wms.nrw.de/umwelt/wasser/uesg`, esri featureinfo XML, query layers `3,5,6`
(3 "Ermittelte Überschwemmungsgebiete", 5 "vorläufig gesicherte Überschwemmungsgebiete", 6 "Festgesetzte
Überschwemmungsgebiete"; `FeatureInfoCollection@layername` carries these titles). Fields: `name` "Ruhr",
`uesg_pdf` "Amtsblatt Nr. 27 vom 06.07.2023", `datum` "14.4.2016", `BR` "BR Düsseldorf", `gewkz`. Verified hit
on the Ruhr at Essen-Steele (51.4400, 7.0850); no hit inland. Legal meaning: festgesetzt/vorläufig gesichert
→ §78 WHG Bauverbot (Ausnahme nötig), Heizöltank-Verbot §78c; ermittelt = Fachplanung.

`_fetch_flood` adds `"uesg": {"zones": [{"kind": "festgesetzt", "kind_label": "Festgesetztes
Überschwemmungsgebiet", "name": "Ruhr", "amtsblatt": "…", "date": "14.4.2016", "authority": "BR Düsseldorf"}],
"legal": true, "error": null}` and sets `flood_risk_level` to `"high"` when `legal` is true.
`Section("flood", …, cache_version=2)`.

## 4. `baugrund` — Baugrund & Versickerung (BK50)

`https://www.wms.nrw.de/gd/bk050` (GD NRW, dl-de/by-2-0), GetFeatureInfo `INFO_FORMAT=text/html`,
`LAYERS=QUERY_LAYERS=Versickerungseignung`, `FEATURE_COUNT=1`. Every layer returns the same 37-row HTML
table for the soil unit, with **human-readable** values — parse the HTML, not the esri codes. Rows are
`<tr><td><a …>Label</a> <br> qualifier</td><td …>value</td>…</tr>`; labels of interest (match on the
`<a>` text): Bodentyp, Grundwasserstufe, Staunässegrad, Bodenartengruppe des Oberbodens, Hauptbodenart nach
BBodSchG, Verdichtungsempfindlichkeit, gesättigte Wasserleitfähigkeit (cells: value, "cm/d", class),
Versickerungseignung, Grabbarkeit, Eignung für Erdwärmekollektoren (cells: "im 1. Meter <br> im 2. Meter",
values, unit, classes), Schutzwürdigkeit der Böden, Erodierbarkeit des Oberbodens (value, class). Sample
Rüttenscheid: Parabraunerde · Stufe 0 - ohne Grundwasser · Stufe 0 - ohne Staunässe · kf 15 cm/d mittel ·
"ungeeignet - VSA, Mulden-Rigolen-Systeme (Bewirtschaftung mit gedrosselter Ableitung)" · Grabbarkeit
"im 1. Meter : mittel grabbar …". Versickerung classes per GD NRW note SIC.pdf: geeignet (kf ≥ 1·10⁻⁵ m/s),
bedingt geeignet (5·10⁻⁶–1·10⁻⁵), ungeeignet. Scale 1:50,000 → area tier, copy says "keine
grundstücksscharfe Aussage".

Essen supplement: `https://geo.essen.de/arcgis/rest/services/essen/Umwelt/MapServer/0` "kf Werte aus
Bauanträgen" (points; fields `GUTACHTEN`, `KF_WERT` "<1x10-7", `GEEIGNET` "nein", `JAHR` 2000, `ANMERKUNG`
"Auffüllung bis zu 1,9m Mächtigkeit") within 300 m — real Baugrundgutachten values, a Ruhrgebiet-typical hint
for Auffüllungen. Essen only; isolated error.

Data: `{"bodentyp", "bodenart", "hauptbodenart", "grundwasser", "staunaesse", "kf_cm_d", "kf_klasse",
"versickerung", "versickerung_klasse" ∈ geeignet|bedingt geeignet|ungeeignet|null, "grabbarkeit",
"verdichtung", "schutzwuerdigkeit", "erodierbarkeit", "erdwaerme": {"m1_w_mk", "m1_klasse", "m2_w_mk",
"m2_klasse"}, "kf_gutachten": [{"gutachten","kf","geeignet","jahr","anmerkung"}], "kf_gutachten_error",
"rating", "rating_color"}`. Rating: Grundwasserstufe/Staunässegrad "Stufe 3" or higher or
versickerung ungeeignet → orange "Nasser oder schwer versickerbarer Boden"; bedingt geeignet or Stufe 1–2 →
yellow "Eingeschränkte Versickerung"; else green "Unauffälliger Baugrund (BK50)". Empty when the table has
no Bodentyp row (outside NRW / no soil unit, e.g. water).

## 5. `radon` — Radon

BfS WFS `https://www.imis.bfs.de/ogc/opendata/ows`, WFS 2.0.0, GeoJSON out, dl-de/by-2-0. Types:
`opendata:radon222_boden_rfv_risikokommunikation` (≈3 km cells; `rn_max` = 90th-percentile radon in soil air
in kBq/m³, `geo_unit` "Karbon"/"Kreide"/"Quartär", `descript` cell id) and `opendata:radonpotential`
(≈10 km cells; `grp_pb_` geogenic radon potential, dimensionless). The bbox parameter must be **lon,lat**
order (`bbox=6.99,51.42,7.02,51.44,EPSG:4326`; lat,lon returns nothing); polygons are WGS84 lon/lat.
Verified at Essen: Karbon cell rn_max 57 next to Kreide cell 6.3; potential 36.5.

Classes. Bodenluft (BfS legend): < 20 gering (green), 20–40 mittel (yellow), 40–100 erhöht (orange),
> 100 hoch (red). Potenzial (Neznal classification used by BfS): < 10 gering (green), 10–35 mittel (yellow),
> 35 hoch (orange). Card rating = worse of the two. Copy: "1-km-Prognose des BfS, kein Messwert am Haus.
NRW hat keine Radonvorsorgegebiete; bei Keller-Wohnnutzung im Karbon Messung empfehlen (Referenzwert
300 Bq/m³ Innenraumluft)."

Data: `{"bodenluft": {"kbq_m3": 57.0, "klasse": "erhöht", "klasse_color": "orange", "geologie": "Karbon",
"zelle": "AC138"} | null, "potenzial": {"wert": 36.5, "klasse": "hoch", "klasse_color": "orange"} | null,
"rating", "rating_color"}`. Empty when both are null.

## 6. `planning_essen` extension — Satzungen & Sanierung

Same MapServer as today, layer `3` "Sonstige Satzungen" (fields `PLANID` DE_05113000_S22_0_2, `NAME`
"Gestaltungssatzung und Erhaltungssatzung Langenbrahm - Siedlung vom 07.11.1980", `NR` S22, `DATUM`,
`BEGRUNDURL`, `ERKLAERURL`; also "Satzung … über besondere Vorkaufsrechte im Bereich 'Deckelung A40'"). Plus
`https://geo.essen.de/arcgis/rest/services/essen/Sanierung_Untersuchung/MapServer/0` (fields `ART` ∈
"Sanierung", "Sanierung abgeschlossen, Ausgleichsbetrag", "Untersuchung"; `ORT` "Werden", "Altstadt Kettwig",
"Altenessen Sued", …). Point queries (distance 0). `get_planning_signals` gains keys `satzung` and
`sanierung`; `_ESSEN_LISTS` gains `("satzung", "Satzung")` and `("sanierung", "Sanierungsgebiet")`.
`cache_version=2`.

## 7. `planning_bochum` extension — Stadterneuerung

`https://geoservicekkm.bochum.de/arcgis/rest/services/maponline/Stadtplanung/MapServer`, point queries on
layers `7` ISEK Hamme, `8` ISEK Innenstadt, `9` Stadtumbau Laer, `10` Wattenscheid, `11` WLAB (fields
`Titel`, `Fördergebi`, `Förderprog`, `Homepage`, `Ende`, `Kategorie` "Stadterneuerungsgebiet"), `16` Gebiete
der Stadtteilentwicklungskonzepte (`Name`), `20` "1036 S - Laer West - (Stadtumbausatzung)" (no name field →
fixed label). Verified: Bochum Innenstadt point returns ISEK Hamme + ISEK Innenstadt. Items are appended to
the existing `items` list in the shape the card already renders (`official_name`, `plan_type`,
`legal_status`, `plan_link`); failures are isolated per layer and never blank the B-Plan result.
`cache_version=2`.

## 8. `schulen` — Schulen & Sozialindex

Static build → `redat/data/schulen_nrw.json.gz` (all NRW, ~5,400 schools, small). Inputs:
`https://www.opengeodata.nrw.de/produkte/bildung_wissenschaft/schulen/SchulenNRW_EPSG25832_Shape.zip`
(point shapefile, 440 KB; DBF fields `Schulnumme`, `Schulform`, `Name`, `Kurzname`, `Adresse`, `Postleitza`,
`Ort`, `Schueler`, `Rufnummer`, `Email`; cpg present) and
`https://www.schulministerium.nrw/system/files/media/document/file/schulliste_sj_25_26_open_data.csv`
(`;`-separated, **cp850** — not cp1252, which fails on 0x81 in "Düsseldorf":
`Schulnummer;Kurzbezeichnung;Bezirksregierung;Kreis;Gemeinde;Sozialindexstufe`). Real Schulform values (2025/26):
Grundschule, Gymnasium, Förderschule, Gesamtschule, Realschule, Berufskolleg, Hauptschule, Sekundarschule,
Waldorfschule, Weiterbildungskolleg, "Primus (Schulversuch)", Volksschule.
Join on Schulnummer. Sozialindex: Stufe 1 (geringe) … 9 (hohe soziale Herausforderungen); it is explicitly
not a quality ranking — copy must say so.

Lookup (`radius_m` 2000): `grundschulen` nearest 3 with Schulform containing "Grundschule" or "PRIMUS";
`weiterfuehrend` nearest one per form among Gymnasium, Gesamtschule, Realschule, Hauptschule, Sekundarschule,
Gemeinschaftsschule, Waldorfschule; `foerderschulen` nearest 2 "Förderschule"; each item
`{"name","form","distance_m","sozialindex","schueler","adresse","plz","ort"}`; `counts` per group in radius.
Bochum supplement (live, isolated): `https://geoservicekkm.bochum.de/arcgis/rest/services/maponline/
Grundschulen/MapServer/3` Grundschulbezirke (`SCHULNAME` "Arnoldschule, Arnoldstr. 31, 44793 Bochum",
`KAP_20_21` 196) → `grundschulbezirk: {"schule", "kapazitaet"}` when inside Bochum (lon 7.10–7.35, lat
51.40–51.53), else null. Rating: nearest Grundschule ≤ 1000 m → green "Grundschule fußläufig", ≤ 2000 m →
yellow, none → orange "Keine Grundschule im Umkreis von 2 km".

## 9. `unfaelle` — Verkehrsunfälle

Static build → `redat/data/unfallatlas_2020_2025.json.gz`. Inputs: opengeodata
`https://www.opengeodata.nrw.de/produkte/transport_verkehr/unfallatlas/Unfallorte<YYYY>_EPSG25832_CSV.zip`
for 2020–2025 (12–13 MB each; inner CSV name varies: `csv/Unfallorte2020_LinRef.csv`,
`csv/Unfallorte_2025_LR_BasisDLM.csv` → glob `*.csv`). Columns (`;`, decimal comma, BOM): `UJAHR`,
`UKATEGORIE` 1 Getötete 2 Schwerverletzte 3 Leichtverletzte, `UART`, `UTYP1` 1 Fahrunfall 2 Abbiegeunfall
3 Einbiegen/Kreuzen 4 Überschreiten 5 ruhender Verkehr 6 Längsverkehr 7 sonstiger, `ULICHTVERH` 0 Tag
1 Dämmerung 2 Dunkelheit, `IstRad/IstPKW/IstFuss/IstKrad/IstGkfz/IstSonstige` 0/1, `XGCSWGS84`/`YGCSWGS84`
lon/lat. Crop to the Zensus window `BBOX_WGS84 = (6.85, 51.33, 7.40, 51.56)`. Rows stored as compact lists
`[lat, lon, jahr, kat, typ, licht, rad, pkw, fuss, krad, gkfz]`.

Lookup (`radius_m` 300, equirectangular metres): `total`, `per_year`, `by_severity`
{getoetete, schwerverletzte, leichtverletzte}, `beteiligt` {rad, fuss, pkw, krad, gkfz}, `by_type`
{Fahrunfall: n, …}, `nachts` (licht 2), `nearest_m`, `per_year_avg`. Rating on per-year average within
300 m: ≤ 2 green "Wenige Unfälle", ≤ 6 yellow "Mäßig", ≤ 15 orange "Viele Unfälle", > 15 red
"Unfallschwerpunkt"; any Getötete lifts to at least orange. Copy: "nur Unfälle mit Personenschaden, Lage ist
der Unfallort, nicht die Adresse".

## Frontend/report conventions used by every card

Web partial receives `d` (data) inside the page scope (`plotSize`, `load(key)`, `sections` are reachable);
colour chips use `$store.app.getAirQualityColor(color)`. Report partial receives `d`, filters `fmt_int`,
`fmt_num`, `fmt_date`, `fmt_m`, `pct`, global `rating_class(color)`; it must render on `{}` without `None`
leaking (tests render every partial with `{}` and with the fixture).
