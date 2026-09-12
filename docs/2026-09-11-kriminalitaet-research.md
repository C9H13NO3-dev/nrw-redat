# Kriminalitätsdaten für die Standortanalyse — Recherche

**Date:** 2026-09-11 · **Status:** research only, no card built · **Decision:** if a card is built, use the
free BKA district table; do not buy commercial data.

## 1. Question

Can the report show crime information for an address? The owner asked for the finest available data and
whether paid sources go below what the police publish.

## 2. Public data (free)

### 2.1 BKA — PKS Kreis-Falltabelle T01 (the usable source)

Bundeskriminalamt, "Polizeiliche Kriminalstatistik", table T01 "Fälle mit Häufigkeitszahl — Kreise", one
xlsx per reporting year, published around April of the following year (the 2025 table is V1.1 of
2026-04-01, 2 MB):

<https://www.bka.de/DE/AktuelleInformationen/StatistikenLagebilder/PolizeilicheKriminalstatistik/PKS2025/pksTabellen_Interpretationshilfen/KreisFalltabellen/kreisfalltabellen.html>
(download: `/SharedDocs/Downloads/DE/Publikationen/PolizeilicheKriminalstatistik/2025/Kreis/Faelle/KR-F-01-T01-Kreise-Faelle-HZ_xls.xlsx?__blob=publicationFile`)

Verified structure (parsed 2026-09-11, sheet 1, 16,409 rows, header on row 5, data from row 9):

| Column | Content |
|---|---|
| Schlüssel | PKS offence key (`------` = Straftaten insgesamt; wildcard keys like `435*00` Wohnungseinbruch, `***300` Fahrraddiebstahl, `892000` Gewaltkriminalität, `899000` Straßenkriminalität) |
| Straftat | offence label |
| Gemeinde-schlüssel | 5-digit district key (`05314` Bonn, `05113` Essen, `05382` Rhein-Sieg-Kreis) — NRW = prefix `05`, 53 districts |
| Stadt-/Landkreis, Kreisart | name, `KfS`/`K`/`LK`/`SK`/`RV` |
| Anzahl erfasste Fälle, HZ | cases, cases per 100,000 inhabitants |
| Versuche (Anzahl, %), Schusswaffe (gedroht, geschossen), Aufklärung (Anzahl Fälle, %) | further columns |

42 offence groups per district. Sample 2025 totals: Essen 51,797 cases / HZ 9,013; Bonn 27,785 / 8,593;
Rhein-Sieg-Kreis 30,295 / 5,004. NRW total 2025: 1,356,972 cases (−2.98 % vs. 2024, per the IM NRW handout).

Licence: Datenlizenz Deutschland – Namensnennung 2.0, attribution "Quelle: Bundeskriminalamt, PKS 2025"
required. A companion "Städte" table covers cities ≥ 100,000 inhabitants and Landeshauptstädte only, with
the same city-wide resolution — no Stadtteil breakdown anywhere in the BKA tables.

### 2.2 NRW sources (same resolution, worse formats)

- LKA NRW PKS-Jahrbuch (PDF): Häufigkeitszahlen per Kreispolizeibehörde —
  <https://polizei.nrw/sites/default/files/2025-10/PKS-Jahrbuch2024.pdf>; 2010–2019 also as CSV in the
  archive (<https://polizei.nrw/polizeiliche-kriminalstatistik/pks-nrw-das-archiv/2010-bis-2019>).
- Per-Kreispolizeibehörde handouts on open.nrw, e.g. Bonn 2023+ (PDF only, city total):
  <https://open.nrw/dataset/polizeiliche_kriminalstatistik_f__r_bonn_1765969298>.
- City data: Köln 2018 CSV set is city-wide only (<https://open.nrw/dataset/kriminalstatistik-stadtgebiet-koeln-2018-k>);
  Köln's Stadtbezirk figures exist only inside the police PDF; Düsseldorf publishes 2020 figures per
  Polizeiinspektion (<https://opendata.duesseldorf.de/dataset/polizeiliche-kriminalstatistiken-f%C3%BCr-die-jeweiligen-polizeiinspektionen-mitte-nord-und-s%C3%BCd>).
  Not worth automating.

**Bottom line:** the finest machine-readable public resolution is the Kreis / kreisfreie Stadt.

## 3. Commercial sources (checked 2026-09-11)

| Provider | Offer | Resolution | Verdict |
|---|---|---|---|
| Nexiga "Crime" package (<https://nexiga.com/en/daten-sicherheit-wohnungseinbrueche/>) | six offence types, assault to burglary | Kreis, Gemeinde, PLZ | PLZ values are downscaled from the same PKS district data — a model, not a measurement; file licence, price on request |
| microm / infas360 (<https://www.microm.de/daten/geodaten>, <https://www.infas360.de/gebaeudedaten/>) | building typology (CASA, 98 classes), PLZ8 area types; infas360 describes burglary prediction from building types | address / PLZ8 | modelled risk; no crime dataset in the public catalogue; custom quote |
| PriceHubble Location Scores API (<https://docs.pricehubble.com/international/location_scores/>) | family, location, noise, nuisance, shopping, view, catering, health, leisure; DE supported | point | **no safety/crime score at all** |
| Insurers' Hausrat tariff zones | burglary risk classes per PLZ from real claims | PLZ | not sold as data; every insurer keeps its own zoning |

**Decision:** do not buy. Every paid product below district level is derived or modelled; the free BKA
table carries the same information with an honest resolution label.

## 4. If a card is built ("Kriminalität (PKS)")

- Static grid like the other statewide files: `redat/data/pks_<year>_nrw.json.gz` built by a
  `scripts/build_pks_grid.py` from the BKA xlsx (rows with `Gemeinde-schlüssel` prefix `05` only; keep the
  offence keys listed below), refreshed each April; optionally the previous year too for a trend arrow.
- District lookup: the app knows only the geocoder's city name today. Add a district polygon file
  (`dvg1krs` from `ogc-api.nrw.de`, or BKG VG250, both dl-de/by-2.0) as `redat/data/kreise_nrw.geojson.gz`
  with an STRtree point-in-polygon lookup (pattern: `bergrechte.py`).
- Card: tier `area`, source string "Bundeskriminalamt — PKS <year>, Kreisdaten"; show the district, HZ
  total vs. NRW and federal averages, and the buyer-relevant groups `435*00` Wohnungseinbruch, `***300`
  Fahrraddiebstahl, `*50*00` Diebstahl an/aus Kfz, `892000` Gewaltkriminalität, `899000` Straßenkriminalität,
  `674000` Sachbeschädigung, plus the Aufklärungsquote. Rating from the total HZ relative to the NRW median.
- Mandatory copy: "Kreisweite Statistik — sagt nichts über die Straße aus" and "Die PKS zählt den Tatort,
  nicht den Wohnort: Innenstädte mit Pendlern und Einkaufsverkehr liegen systematisch höher als Vororte."
