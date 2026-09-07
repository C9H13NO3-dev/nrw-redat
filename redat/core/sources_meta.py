"""Single source of truth for /quellen and the report footer (spec §6)."""
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class SourceMeta:
    section_keys: tuple[str, ...]
    name: str
    publisher: str
    licence: str
    endpoint: str
    tier: str          # "parcel" | "area"
    cadence: str       # how often the upstream changes / when we refresh


SOURCES: tuple[SourceMeta, ...] = (
    SourceMeta(("flurstueck",), "ALKIS Flurstücke & Gebäude · Baulasteninformation Essen", "Geobasis NRW · Stadt Essen", "dl-de/zero-2-0 · Stadt Essen (unverbindlich)",
               "https://www.wfs.nrw.de/geobasis/wfs_nw_alkis_vereinfacht (WFS 2.0, GML) · geo.essen.de Baulasteninformation (ArcGIS REST)", "parcel", "live (ALKIS fortlaufend, Baulasten wöchentlich)"),
    SourceMeta(("boris", "boris_trend"), "BORIS NRW Bodenrichtwerte", "Gutachterausschüsse NRW / Geobasis NRW", "dl-de/zero-2-0",
               "lokale Shapefiles unter source/boris (Stichtage 2011–2025)", "parcel", "jährlich (1.1.), Datei-Import"),
    SourceMeta(("irw",), "BORIS NRW Immobilienrichtwerte", "Gutachterausschüsse NRW / Geobasis NRW", "dl-de/zero-2-0",
               "https://www.wms.nrw.de/boris/wms_nw_irw (WMS GetFeatureInfo, Layer 9/12/15/18/21)", "parcel", "jährlich (1.1.), live WMS"),
    SourceMeta(("flood",), "Hochwassergefahrenkarten NRW (HWRM-RL)", "Land NRW, LANUV", "dl-de/by-2-0",
               "lokale GeoPackages unter source/flood/hwrm", "parcel", "6-Jahres-Zyklus, Datei-Import"),
    SourceMeta(("starkregen",), "Hinweiskarte Starkregengefahren", "BKG", "dl-de/by-2-0",
               "https://sgx.geodatenzentrum.de/wms_starkregen", "parcel", "live WMS"),
    SourceMeta(("noise",), "Umgebungslärmkartierung 2022", "Land NRW, LANUV", "dl-de/zero-2-0",
               "https://www.wms.nrw.de/umwelt/laerm", "area", "live WMS, 5-Jahres-Runde"),
    SourceMeta(("bergbau",), "NRW von unten (Bürgerversion)", "Geologischer Dienst NRW / BezReg Arnsberg", "dl-de/by-2-0",
               "ArcGIS REST, Layer 22 (500 m-Planquadrat) · lokal: redat/data/bergbauberechtigungen_nrw.geojson.gz (scripts/build_bergbauberechtigungen.py) · "
               "Copernicus EGMS 2020–2024 (lokal: redat/data/egms_vertical_velocity_nrw.npz)", "area", "live"),
    SourceMeta(("baugrund",), "IS BK50 Bodenkarte NRW · kf-Werte aus Bauanträgen (Essen)", "Geologischer Dienst NRW · Stadt Essen", "dl-de/by-2-0",
               "https://www.wms.nrw.de/gd/bk050 (WMS GetFeatureInfo text/html) · geo.essen.de Umwelt/0", "area", "live; BK50 fortlaufend"),
    SourceMeta(("radon",), "Radon in der Bodenluft · Radonpotenzial", "Bundesamt für Strahlenschutz (BfS)", "dl-de/by-2-0",
               "https://www.imis.bfs.de/ogc/opendata/ows (WFS 2.0, GeoJSON)", "area", "live, Karten 2023 (statisch)"),
    SourceMeta(("gfnp",), "Gemeinsamer Flächennutzungsplan", "Stadt Essen (geo.essen.de)", "dl-de/by-2-0",
               "ArcGIS REST identify (RVR-Städte) · WMS wms_nw_regionalplan (Bild im PDF)", "parcel", "live"),
    SourceMeta(("schutzgebiete",), "LINFOS Schutzgebiete + Wasserschutzgebiete", "LANUV NRW", "dl-de/by-2-0",
               "WFS 2.0 (EPSG:25832) + WSG WMS GetFeatureInfo", "area", "live"),
    SourceMeta(("planning_essen",), "Bauleitplanung Essen", "Stadt Essen (geo.essen.de)", "dl-de/by-2-0",
               "ArcGIS REST identify", "parcel", "live"),
    SourceMeta(("planning_bochum",), "Bauleitplanung Bochum", "RVR INSPIRE", "dl-de/by-2-0",
               "WMS GetFeatureInfo", "parcel", "live"),
    SourceMeta(("planning_nrw",), "Bauleitpläne NRW (INSPIRE geplante Bodennutzung)", "Land NRW / IT.NRW (kommunale Lieferung, freiwillig)",
               "Datenlizenz Deutschland (Kommune) — Anzeige unverbindlich", "OGC API Features: ogc-api.nrw.de/inspire-lu-bplan", "parcel", "live"),
    SourceMeta(("denkmal",), "Denkmalliste (INSPIRE Schutzgebiete)", "RVR / IT.NRW / Untere Denkmalbehörden", "dl-de/by-2-0",
               "WFS 2.0: geodaten.metropoleruhr.de (RVR) · wfs.nrw.de/wfs/wfs_nw_inspire-denkmal (Land)", "parcel", "live"),
    SourceMeta(("amenities",), "Geoapify Places", "Geoapify (OpenStreetMap-Daten)", "ODbL / Geoapify-Nutzungsbedingungen",
               "https://api.geoapify.com/v2/places", "area", "live"),
    SourceMeta(("schulen",), "Schulstandorte NRW + Schulsozialindex", "Ministerium für Schule und Bildung NRW · Geobasis NRW · Stadt Bochum", "dl-de/by-2-0",
               "lokal: redat/data/schulen_nrw.json.gz (scripts/build_schulen.py) · Bochum ArcGIS Grundschulbezirke", "area", "jährlich (Schuljahr), Datei-Import"),
    SourceMeta(("unfaelle",), "Unfallatlas — Straßenverkehrsunfälle mit Personenschaden", "Statistische Ämter des Bundes und der Länder", "dl-de/by-2-0",
               "lokal: redat/data/unfallatlas_2020_2025_nrw.npz (scripts/build_unfallatlas.py)", "area", "jährlich (Juli), Datei-Import"),
    SourceMeta(("oepnv",), "VRR EFA-Fahrplanauskunft", "Verkehrsverbund Rhein-Ruhr", "Nutzung gemäß VRR-Bedingungen",
               "https://efa.vrr.de/standard/ (rapidJSON)", "area", "live, Fahrplan-Stichtag nächster Dienstag 08:00"),
    SourceMeta(("zensus",), "Zensus 2022 — 100 m-Gitterdaten", "Statistische Ämter des Bundes und der Länder", "dl-de/by-2-0",
               "lokal: redat/data/zensus_2022_nrw.npz (scripts/build_zensus_grid.py)", "area", "Zensus 2022 (einmalig), Datei-Import"),
    SourceMeta(("stadtklima",), "Klimaanalyse NRW 2026 (Stadtklima)", "LANUV / LANUK NRW", "dl-de/by-2-0",
               "WMS GetFeatureInfo: wms.nrw.de/umwelt/klimaanpassung_klimaanalyse (Layer 59, 54, 52, 38, 29)", "area", "live"),
    SourceMeta(("energie",), "Solarkataster · Geothermie · Kommunale Wärmeplanung", "LANUK NRW · GD NRW · Städte Essen/Bochum", "dl-de/by-2-0",
               "ArcGIS REST + GT WMS GetFeatureInfo", "parcel", "live"),
    SourceMeta(("ladesaeulen",), "Ladesäulenregister", "Bundesnetzagentur", "CC BY 4.0",
               "lokal: redat/data/ladesaeulen_nrw.json.gz (scripts/build_ladesaeulen.py)", "area", "monatlich, Datei-Import"),
    SourceMeta(("breitband",), "Breitbandatlas", "Bundesnetzagentur", "© BNetzA, dl-de/by-2-0",
               "WMS, 100 m-Raster (EPSG:3035)", "area", "halbjährlich — Datenstand 12.2025"),
    SourceMeta(("infrastruktur",), "OpenStreetMap (Overpass) + EEA Industrial Emissions Portal", "OSM-Mitwirkende · EEA", "ODbL · EEA Standard Re-use Policy",
               "Overpass API + discodata SQL [IED].[latest].[SiteMap]", "area", "live"),
    SourceMeta(("air_quality",), "Luftqualität (EEA-Raster, UBA/LANUV, Sensor.Community, CAMS)", "EEA · Umweltbundesamt · LANUV · Sensor.Community · Copernicus", "EEA Standard Re-use Policy · dl-de/by-2-0 · ODbL · CC BY 4.0",
               "lokal: redat/data/eea_aq_grid_2023_nrw.json.gz + live APIs", "area", "EEA jährlich (2023) · Messwerte stündlich"),
    SourceMeta(("btw",), "Bundestagswahl 2025 (kerg2, Wahlkreisgeometrien)", "Die Bundeswahlleiterin", "dl-de/by-2-0",
               "lokal: source/elections/btw25", "area", "je Wahl, Datei-Import"),
    SourceMeta(("commute",), "Geoapify Routing", "Geoapify (OpenStreetMap-Daten)", "ODbL / Geoapify-Nutzungsbedingungen",
               "https://api.geoapify.com/v1/routing", "area", "live"),
)


def for_section(key: str) -> Optional[SourceMeta]:
    return next((s for s in SOURCES if key in s.section_keys), None)
