import importlib.util
import io
from pathlib import Path

_spec = importlib.util.spec_from_file_location("build_ls", Path(__file__).resolve().parent.parent / "scripts" / "build_ladesaeulen.py")
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)

CSV = (
    "﻿Ladesäulenregister Bundesnetzagentur;;;;;;;;;;;;;;;;\n"
    ";;;;;;;;;;;;;;;;\n"
    "Letzte Aktualisierung vom: 01.09.2026;;;;;;;;;;;;;;;;\n"
    "Allgemeine Informationen;;;;;;;;;;;;;;;;\n"
    "Ladeeinrichtungs-ID;Betreiber;Anzeigename (Karte);Status;Art der Ladeeinrichtung;Anzahl Ladepunkte;Nennleistung Ladeeinrichtung [kW];Inbetriebnahmedatum;Straße;Hausnummer;Adresszusatz;Postleitzahl;Ort;Kreis/kreisfreie Stadt;Bundesland;Breitengrad;Längengrad\n"
    "1;E.ON Drive Germany GmbH;E.ON;In Betrieb;Normalladeeinrichtung;2;22;25.01.2021;Rüttenscheider Str.;1;;45131;Essen;Kreisfreie Stadt Essen;Nordrhein-Westfalen;51,430500;7,005500\n"
    "2;Fastned;Fastned;In Betrieb;Schnellladeeinrichtung;4;300;01.01.2024;A40;;;45141;Essen;Kreisfreie Stadt Essen;Nordrhein-Westfalen;51,460000;7,010000\n"
    "3;X;X;In Betrieb;Normalladeeinrichtung;1;11;01.01.2021;Grunerstraße;20;;10179;Essen;Kreisfreie Stadt Berlin;Berlin;52,519366;13,416644\n"   # Ort 'Essen' but Berlin → bbox drops it
    "4;Y;Y;In Wartung;Normalladeeinrichtung;1;11;01.01.2021;Weg;1;;45131;Essen;Kreisfreie Stadt Essen;Nordrhein-Westfalen;51,431000;7,006000\n"   # not in Betrieb → dropped
)


def test_parse_rows_crops_by_bbox_and_keeps_only_operating():
    rows = mod.parse_rows(io.StringIO(CSV), mod.BBOX_WGS84)
    assert rows == [[51.4305, 7.0055, "E.ON Drive Germany GmbH", 0, 2, 22.0, "Rüttenscheider Str. 1, 45131 Essen"],
                    [51.46, 7.01, "Fastned", 1, 4, 300.0, "A40, 45141 Essen"]]
    mod.sort_rows(rows)
    assert rows == sorted(rows, key=lambda r: r[0])


def test_stand_is_read_from_the_preamble():
    assert mod.read_stand(io.StringIO(CSV)) == "2026-09-01"


def test_bbox_is_statewide():
    assert mod.BBOX_WGS84 == (5.753, 50.242, 9.589, 52.619)
