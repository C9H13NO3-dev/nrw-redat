from redat.sources import irw


def coll(layer, **fields):
    rows = "".join(f"<Field><FieldName>{k}</FieldName><FieldValue>{v}</FieldValue></Field>" for k, v in fields.items())
    return f'<FeatureInfoCollection layername="{layer}"><FeatureInfo>{rows}</FeatureInfo></FeatureInfoCollection>'


def xml(*colls):
    return ('<?xml version="1.0" encoding="UTF-8"?><FeatureInfoResponse xmlns="http://www.esri.com/wms" version="1.3.0">'
            + "".join(colls) + "</FeatureInfoResponse>")


RH = coll("irw_reihen_doppelhaeuser", GENA="Essen", GABE="Der Gutachterausschuss für Grundstückswerte in der Stadt Essen", ORTST="Rüttenscheid",
          PLZ="45131", IMRW="3950", STAG="01.01.2026", TEILMA="3", EGART="2", BJ="1962", WHNFL="130", FLAE="300", WHNLA=" ",
          UDOK_URL="https://www.boris.nrw.de/borisfachdaten/lgd/irw/2026/LGDIR_3_0510900_2026.pdf")
ETW = coll("irw_eigentumswohnungen", GENA="Essen", GABE="GA Essen", ORTST="Rüttenscheid", PLZ="45131", IMRW="2800", STAG="01.01.2026",
           TEILMA="1", BJ="1962", WHNFL="69", ANZEGEB="7-12", WHNLA="3", UDOK_URL="https://x/LGDIR_1.pdf")
EFH = coll("irw_ein_zweifamilienhaeuser", GENA="Bochum", GABE="GA Bochum", ORTST=" ", IMRW="3350", STAG="01.01.2026", TEILMA="2", BJ="1965",
           WHNFL="151-175", FLAE="601-800", UDOK_URL="https://x/LGDIR_2.pdf")


def test_parse_sorted_by_teilmarkt_with_normobjekt():
    w = irw.parse_irw(xml(RH, ETW, EFH))
    assert [x["teilmarkt"] for x in w] == [1, 2, 3]
    etw, efh, rh = w
    assert etw == {"teilmarkt": 1, "teilmarkt_label": "Eigentumswohnungen", "eur_m2": 2800, "stichtag": "2026-01-01",
                   "ortsteil": "Rüttenscheid", "plz": "45131", "wohnlage": "gut", "gutachterausschuss": "GA Essen",
                   "normobjekt": {"baujahr": "1962", "wohnflaeche_m2": "69", "grundstueck_m2": None, "anbauweise": None, "wohnungen": "7-12"},
                   "doku_url": "https://x/LGDIR_1.pdf"}
    assert rh["normobjekt"]["anbauweise"] == "Doppelhaushälfte" and rh["normobjekt"]["grundstueck_m2"] == "300" and rh["wohnlage"] is None
    assert efh["ortsteil"] is None and efh["normobjekt"]["wohnflaeche_m2"] == "151-175"


def test_get_irw_and_empty(monkeypatch):
    monkeypatch.setattr(irw, "_featureinfo", lambda lat, lon: xml(RH, ETW))
    d = irw.get_irw(51.43, 7.005)
    assert d["stichtag"] == "2026-01-01" and d["gutachterausschuss"] == "GA Essen" and len(d["werte"]) == 2   # sorted → ETW first
    monkeypatch.setattr(irw, "_featureinfo", lambda lat, lon: xml())
    assert irw.get_irw(51.48, 7.216) is None


def test_bad_number_is_skipped():
    assert irw.parse_irw(xml(coll("irw_mehrfamilienhaeuser", IMRW="n/a", TEILMA="4", STAG="01.01.2026"))) == []
