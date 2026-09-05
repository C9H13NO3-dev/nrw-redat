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
    SourceMeta(("boris", "boris_trend"), "BORIS NRW Bodenrichtwerte", "Gutachterausschüsse NRW / Geobasis NRW", "dl-de/zero-2-0",
               "lokale Shapefiles unter source/boris (Stichtage 2011–2025)", "parcel", "jährlich (1.1.), Datei-Import"),
    SourceMeta(("flood",), "Hochwassergefahrenkarten NRW (HWRM-RL)", "Land NRW, LANUV", "dl-de/by-2-0",
               "lokale GeoPackages unter source/flood/hwrm", "parcel", "6-Jahres-Zyklus, Datei-Import"),
    SourceMeta(("starkregen",), "Hinweiskarte Starkregengefahren", "BKG", "dl-de/by-2-0",
               "https://sgx.geodatenzentrum.de/wms_starkregen", "parcel", "live WMS"),
    SourceMeta(("noise",), "Umgebungslärmkartierung 2022", "Land NRW, LANUV", "dl-de/zero-2-0",
               "https://www.wms.nrw.de/umwelt/laerm", "area", "live WMS, 5-Jahres-Runde"),
    SourceMeta(("bergbau",), "NRW von unten (Bürgerversion)", "Geologischer Dienst NRW / BezReg Arnsberg", "dl-de/by-2-0",
               "ArcGIS REST, Layer 22 (500 m-Planquadrat)", "area", "live"),
    SourceMeta(("gfnp",), "Gemeinsamer Flächennutzungsplan", "Stadt Essen (geo.essen.de)", "dl-de/by-2-0",
               "ArcGIS REST identify", "parcel", "live"),
    SourceMeta(("schutzgebiete",), "LINFOS Schutzgebiete + Wasserschutzgebiete", "LANUV NRW", "dl-de/by-2-0",
               "WFS 2.0 (EPSG:25832) + WSG WMS GetFeatureInfo", "area", "live"),
    SourceMeta(("planning_essen",), "Bauleitplanung Essen", "Stadt Essen (geo.essen.de)", "dl-de/by-2-0",
               "ArcGIS REST identify", "parcel", "live"),
    SourceMeta(("planning_bochum",), "Bauleitplanung Bochum", "RVR INSPIRE", "dl-de/by-2-0",
               "WMS GetFeatureInfo", "parcel", "live"),
    SourceMeta(("denkmal",), "Denkmalliste (INSPIRE Schutzgebiete)", "RVR / Städte Essen und Bochum", "dl-de/by-2-0",
               "https://geodaten.metropoleruhr.de/inspire/schutzgebiete/metropoleruhr (WFS 2.0)", "parcel", "live"),
    SourceMeta(("amenities",), "Geoapify Places", "Geoapify (OpenStreetMap-Daten)", "ODbL / Geoapify-Nutzungsbedingungen",
               "https://api.geoapify.com/v2/places", "area", "live"),
    SourceMeta(("oepnv",), "VRR EFA-Fahrplanauskunft", "Verkehrsverbund Rhein-Ruhr", "Nutzung gemäß VRR-Bedingungen",
               "https://efa.vrr.de/standard/ (rapidJSON)", "area", "live, Fahrplan-Stichtag nächster Dienstag 08:00"),
    SourceMeta(("zensus",), "Zensus 2022 — 100 m-Gitterdaten", "Statistische Ämter des Bundes und der Länder", "dl-de/by-2-0",
               "lokal: redat/data/zensus_2022_grid.json.gz", "area", "Zensus 2022 (einmalig), Datei-Import"),
    SourceMeta(("energie",), "Solarkataster · Geothermie · Kommunale Wärmeplanung", "LANUK NRW · GD NRW · Städte Essen/Bochum", "dl-de/by-2-0",
               "ArcGIS REST + GT WMS GetFeatureInfo", "parcel", "live"),
    SourceMeta(("breitband",), "Breitbandatlas", "Bundesnetzagentur", "© BNetzA, dl-de/by-2-0",
               "WMS, 100 m-Raster (EPSG:3035)", "area", "halbjährlich — Datenstand 12.2025"),
    SourceMeta(("infrastruktur",), "OpenStreetMap (Overpass) + EEA Industrial Emissions Portal", "OSM-Mitwirkende · EEA", "ODbL · EEA Standard Re-use Policy",
               "Overpass API + discodata SQL [IED].[latest].[SiteMap]", "area", "live"),
    SourceMeta(("air_quality",), "Luftqualität (EEA-Raster, UBA/LANUV, Sensor.Community, CAMS)", "EEA · Umweltbundesamt · LANUV · Sensor.Community · Copernicus", "EEA Standard Re-use Policy · dl-de/by-2-0 · ODbL · CC BY 4.0",
               "lokal: redat/data/eea_aq_grid_2023.json + live APIs", "area", "EEA jährlich (2023) · Messwerte stündlich"),
    SourceMeta(("btw",), "Bundestagswahl 2025 (kerg2, Wahlkreisgeometrien)", "Die Bundeswahlleiterin", "dl-de/by-2-0",
               "lokal: source/elections/btw25", "area", "je Wahl, Datei-Import"),
    SourceMeta(("commute",), "Geoapify Routing", "Geoapify (OpenStreetMap-Daten)", "ODbL / Geoapify-Nutzungsbedingungen",
               "https://api.geoapify.com/v1/routing", "area", "live"),
)


def for_section(key: str) -> Optional[SourceMeta]:
    return next((s for s in SOURCES if key in s.section_keys), None)
