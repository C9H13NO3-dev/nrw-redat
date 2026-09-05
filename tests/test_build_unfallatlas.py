import importlib.util
import io
from pathlib import Path

_spec = importlib.util.spec_from_file_location("build_unfallatlas", Path(__file__).resolve().parent.parent / "scripts" / "build_unfallatlas.py")
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)

CSV_2020 = (
    "﻿OBJECTID;UIDENTSTLAE;ULAND;UREGBEZ;UKREIS;UGEMEINDE;UJAHR;UMONAT;USTUNDE;UWOCHENTAG;UKATEGORIE;UART;UTYP1;ULICHTVERH;IstRad;IstPKW;IstFuss;IstKrad;IstGkfz;IstSonstige;LINREFX;LINREFY;XGCSWGS84;YGCSWGS84;STRZUSTAND\n"
    "1;x;05;1;13;000;2020;01;11;5;2;1;7;0;1;1;0;0;0;0;361000,1;5699000,2;7,005000000000000;51,430000000000000;0\n"   # inside
    "2;y;12;0;68;468;2020;01;11;5;3;1;6;2;0;1;0;0;1;0;735840,4;5887204,8;12,521519179000052;53,082132832000070;0\n"   # outside bbox
    "3;z;05;1;13;000;2020;02;08;2;1;5;4;1;0;0;1;0;0;0;361100,0;5699100,0;7,006;51,431;1\n"                              # inside, Getötete, Fußgänger
)
CSV_2025 = (
    "﻿UIDENTSTLAE;ULAND;UREGBEZ;UKREIS;UGEMEINDE;UJAHR;UMONAT;USTUNDE;UWOCHENTAG;UKATEGORIE;UART;UTYP1;ULICHTVERH;IstStrassenzustand;IstRad;IstPKW;IstFuss;IstKrad;IstGkfz;IstSonstige;LINREFX;LINREFY;XGCSWGS84;YGCSWGS84;PLST\n"
    "a;05;1;13;000;2025;05;15;6;3;5;3;0;0;0;1;0;0;0;0;361000,0;5699000,0;7,0050;51,4300;1\n"
)


def test_parse_rows_crops_and_maps_fields():
    rows = mod.parse_rows(io.StringIO(CSV_2020), mod.BBOX_WGS84)
    assert rows == [
        [51.43, 7.005, 2020, 2, 7, 0, 1, 1, 0, 0, 0],
        [51.431, 7.006, 2020, 1, 4, 1, 0, 0, 1, 0, 0],
    ]


def test_parse_rows_handles_2025_layout_without_objectid():
    rows = mod.parse_rows(io.StringIO(CSV_2025), mod.BBOX_WGS84)
    assert rows == [[51.43, 7.005, 2025, 3, 3, 0, 0, 1, 0, 0, 0]]


def test_fields_order():
    assert mod.FIELDS == ["lat", "lon", "jahr", "kat", "typ", "licht", "rad", "pkw", "fuss", "krad", "gkfz"]
