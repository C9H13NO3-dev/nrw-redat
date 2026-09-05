import pytest

from redat.sources import baugrund as bg

# Verbatim structure of the BK50 text/html GetFeatureInfo (Rüttenscheid, 2026-09-05), reduced to the rows we read.
HTML = """<html><head><style>td{}</style></head><body><table>
<tr><th colspan="5">Basisinformationen</th></tr>
<tr> <td><a href="https://www.gd.nrw.de/wms_html/bk50_wms/pdf/TYP.pdf" target="_blank">Bodentyp</a></td><td align="middle" colspan="4">Parabraunerde</td> </tr>
<tr> <td><a href="https://www.gd.nrw.de/wms_html/bk50_wms/pdf/GW.pdf" target="_blank">Grundwasserstufe</a></td><td colspan="4" align="middle">Stufe 0 - ohne Grundwasser</td> </tr>
<tr> <td><a href="https://www.gd.nrw.de/wms_html/bk50_wms/pdf/SN.pdf" target="_blank">Staun&auml;ssegrad</a></td><td colspan="4" align="middle">Stufe 0 - ohne Staun&auml;sse</td> </tr>
<tr> <td><a href="x">Bodenartengruppe des Oberbodens</a></td><td>Bodenart nach<br>Kartieranleitung<br>(und Gruppe nach GD NRW)</td><td colspan="3">stark toniger Schluff<br>(3 - tonig-schluffig)</td> </tr>
<tr> <td><a href="x">Hauptbodenart<br> nach BBodSchG</a></td><td colspan="4">Lehm/Schluff</td> </tr>
<tr> <td><a href="x">Schutzw&uuml;rdigkeit der B&ouml;den<br>(Auflage 3.2)</a></td><td colspan="4">fruchtbare B&ouml;den mit sehr hoher Funktionserf&uuml;llung</td> </tr>
<tr> <td><a href="https://www.gd.nrw.de/wms_html/bk50_wms/pdf/VER.pdf" target="_blank">Verdichtungsempfindlichkeit</a></td><td colspan="4" align="middle">mittel</td> </tr>
<tr> <td><a href="x">Erodierbarkeit des Oberbodens</a></td><td>0,48</td><td></td><td colspan="2">hoch</td> </tr>
<tr> <td><a href="https://www.gd.nrw.de/wms_html/bk50_wms/pdf/KF.pdf" target="_blank">ges&auml;ttigte Wasserleitf&auml;higkeit</a> <br> im 2-Meter-Raum</td><td align="middle">15</td><td align="middle">cm/d</td><td colspan="2" align="middle">mittel</td> </tr>
<tr> <td><a href="https://www.gd.nrw.de/wms_html/bk50_wms/pdf/SIC.pdf" target="_blank">Versickerungseignung</a> <br> in 2-Meter-Raum</td><td colspan="4" align="middle">ungeeignet - VSA, Mulden-Rigolen-Systeme (Bewirtschaftung mit gedrosselter Ableitung)</td> </tr>
<tr> <td><a href="https://www.gd.nrw.de/wms_html/bk50_wms/pdf/GBK.pdf" target="_blank">Grabbarkeit</a> <br> in 2-Meter-Raum</td><td colspan="4" align="middle">im 1. Meter : mittel grabbar <br> im 2. Meter : mittel grabbar <br> nicht grundnass und nicht staunass</td> </tr>
<tr> <td><a href="https://www.gd.nrw.de/wms_html/bk50_wms/pdf/ERD.pdf" target="_blank">Eignung f&uuml;r Erdw&auml;rmekollektoren</a> <br> Grundwasserstufe beachten!</td><td align="middle">im 1. Meter <br> im 2. Meter</td><td align="middle">1,37 <br> 2,7367</td><td align="middle">W/m/K <br> W/m/K</td><td align="middle">mittel <br> extrem hoch</td> </tr>
</table></body></html>"""
HTML_EMPTY = "<html><body><table><tr><td>FeatureInfo - BK50-WMS</td></tr></table></body></html>"
KF = {"features": [{"attributes": {"GUTACHTEN": "UCON", "KF_WERT": "<1x10-7", "GEEIGNET": "nein", "JAHR": 2000, "ANMERKUNG": "Auffüllung bis zu 1,9m Mächtigkeit"}},
                   {"attributes": {"GUTACHTEN": "Siedek+Kügler", "KF_WERT": "<3x10-6", "GEEIGNET": "nein", "JAHR": 1997, "ANMERKUNG": None}}]}


def stub(monkeypatch, html=HTML, kf=KF):
    monkeypatch.setattr(bg, "_featureinfo_html", lambda lat, lon: html)

    def kfq(lat, lon):
        if isinstance(kf, Exception):
            raise kf
        return kf
    monkeypatch.setattr(bg, "_kf_query", kfq)


def test_parse_rows_by_label():
    rows = bg.parse_bk50_html(HTML)
    assert rows["Bodentyp"] == ["Parabraunerde"]
    assert rows["Staunässegrad"] == ["Stufe 0 - ohne Staunässe"]
    assert rows["gesättigte Wasserleitfähigkeit"] == ["15", "cm/d", "mittel"]
    assert rows["Grabbarkeit"] == ["im 1. Meter : mittel grabbar im 2. Meter : mittel grabbar nicht grundnass und nicht staunass"]
    assert rows["Eignung für Erdwärmekollektoren"] == ["im 1. Meter im 2. Meter", "1,37 2,7367", "W/m/K W/m/K", "mittel extrem hoch"]
    assert "Basisinformationen" not in rows


def test_get_baugrund_essen(monkeypatch):
    stub(monkeypatch)
    d = bg.get_baugrund(51.4300, 7.0050)
    assert d["bodentyp"] == "Parabraunerde" and d["bodenart"] == "stark toniger Schluff (3 - tonig-schluffig)" and d["hauptbodenart"] == "Lehm/Schluff"
    assert d["grundwasser"] == "Stufe 0 - ohne Grundwasser" and d["staunaesse"] == "Stufe 0 - ohne Staunässe"
    assert d["kf_cm_d"] == 15.0 and d["kf_klasse"] == "mittel"
    assert d["versickerung"].startswith("ungeeignet - VSA") and d["versickerung_klasse"] == "ungeeignet"
    assert d["grabbarkeit"].startswith("im 1. Meter : mittel grabbar") and d["verdichtung"] == "mittel" and d["erodierbarkeit"] == "hoch"
    assert d["erdwaerme"] == {"m1_w_mk": 1.37, "m1_klasse": "mittel", "m2_w_mk": 2.7367, "m2_klasse": "extrem hoch"}
    assert d["kf_gutachten"] == [{"gutachten": "UCON", "kf": "<1x10-7", "geeignet": "nein", "jahr": 2000, "anmerkung": "Auffüllung bis zu 1,9m Mächtigkeit"},
                                 {"gutachten": "Siedek+Kügler", "kf": "<3x10-6", "geeignet": "nein", "jahr": 1997, "anmerkung": None}]
    assert d["rating"] == "Schwer versickerbarer Boden" and d["rating_color"] == "orange"


def test_versickerung_classes_and_rating():
    assert bg.versickerung_klasse("geeignet - Versickerung über die Fläche") == "geeignet"
    assert bg.versickerung_klasse("bedingt geeignet - Mulden") == "bedingt geeignet"
    assert bg.versickerung_klasse("ungeeignet - VSA") == "ungeeignet"
    assert bg.versickerung_klasse(None) is None
    assert bg.rate("geeignet", "Stufe 0 - ohne Grundwasser", "Stufe 0 - ohne Staunässe") == ("Unauffälliger Baugrund (BK50)", "green")
    assert bg.rate("bedingt geeignet", "Stufe 0 - ohne Grundwasser", "Stufe 1 - schwach staunass") == ("Eingeschränkte Versickerung", "yellow")
    assert bg.rate("geeignet", "Stufe 3 - mittlerer Grundwassereinfluss", "Stufe 0") == ("Nasser Boden (Grundwasser/Staunässe)", "orange")
    assert bg.rate(None, None, None) == ("Keine Bewertung", "gray")


def test_outside_essen_skips_kf(monkeypatch):
    calls = []
    monkeypatch.setattr(bg, "_featureinfo_html", lambda lat, lon: HTML)
    monkeypatch.setattr(bg, "_kf_query", lambda lat, lon: calls.append(1) or KF)
    d = bg.get_baugrund(51.4818, 7.2162)      # Bochum
    assert d["kf_gutachten"] == [] and calls == []


def test_kf_failure_isolated(monkeypatch):
    stub(monkeypatch, kf=RuntimeError("essen down"))
    d = bg.get_baugrund(51.4300, 7.0050)
    assert d["kf_gutachten"] == [] and d["kf_gutachten_error"] == "essen down" and d["bodentyp"] == "Parabraunerde"


def test_no_soil_unit_is_none(monkeypatch):
    stub(monkeypatch, html=HTML_EMPTY)
    assert bg.get_baugrund(51.4300, 7.0050) is None
