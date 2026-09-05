import pytest

from redat.sources import uesg

XML_HIT = """<?xml version="1.0" encoding="UTF-8"?>
<FeatureInfoResponse xmlns="http://www.esri.com/wms" version="1.3.0">
 <FeatureInfoCollection layername="Festgesetzte Überschwemmungsgebiete">
  <FeatureInfo>
   <Field><FieldName>Typ</FieldName><FieldValue>1</FieldValue></Field>
   <Field><FieldName>gewkz</FieldName><FieldValue>276</FieldValue></Field>
   <Field><FieldName>name</FieldName><FieldValue>Ruhr</FieldValue></Field>
   <Field><FieldName>uesg_pdf</FieldName><FieldValue>Amtsblatt Nr. 27 vom 06.07.2023</FieldValue></Field>
   <Field><FieldName>datum</FieldName><FieldValue>14.4.2016</FieldValue></Field>
   <Field><FieldName>BR</FieldName><FieldValue>BR Düsseldorf</FieldValue></Field>
  </FeatureInfo>
 </FeatureInfoCollection>
 <FeatureInfoCollection layername="Ermittelte Überschwemmungsgebiete">
  <FeatureInfo>
   <Field><FieldName>name</FieldName><FieldValue>Ruhr</FieldValue></Field>
  </FeatureInfo>
 </FeatureInfoCollection>
</FeatureInfoResponse>"""
XML_NONE = '<?xml version="1.0"?><FeatureInfoResponse xmlns="http://www.esri.com/wms" version="1.3.0"/>'


def test_parse_hit_orders_legal_first():
    zones = uesg.parse_uesg(XML_HIT)
    assert zones == [
        {"kind": "festgesetzt", "kind_label": "Festgesetztes Überschwemmungsgebiet", "name": "Ruhr",
         "amtsblatt": "Amtsblatt Nr. 27 vom 06.07.2023", "date": "14.4.2016", "authority": "BR Düsseldorf"},
        {"kind": "ermittelt", "kind_label": "Ermitteltes Überschwemmungsgebiet", "name": "Ruhr", "amtsblatt": None, "date": None, "authority": None},
    ]


def test_vorlaeufig_is_legal_too():
    xml = XML_HIT.replace("Festgesetzte Überschwemmungsgebiete", "vorläufig gesicherte Überschwemmungsgebiete")
    z = uesg.parse_uesg(xml)
    assert z[0]["kind"] == "vorlaeufig" and z[0]["kind_label"] == "Vorläufig gesichertes Überschwemmungsgebiet"


def test_get_uesg(monkeypatch):
    monkeypatch.setattr(uesg, "_featureinfo", lambda lat, lon: XML_HIT)
    d = uesg.get_uesg(51.44, 7.085)
    assert d["legal"] is True and [z["kind"] for z in d["zones"]] == ["festgesetzt", "ermittelt"]
    monkeypatch.setattr(uesg, "_featureinfo", lambda lat, lon: XML_NONE)
    assert uesg.get_uesg(51.43, 7.0) == {"zones": [], "legal": False}


def test_unknown_layer_is_ignored():
    xml = XML_HIT.replace("Ermittelte Überschwemmungsgebiete", "Rückgewinnbare Rückhalteflächen")
    assert [z["kind"] for z in uesg.parse_uesg(xml)] == ["festgesetzt"]
