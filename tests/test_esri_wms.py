from redat.sources import esri_wms

XML = """<?xml version="1.0" encoding="UTF-8"?>
<FeatureInfoResponse xmlns="http://www.esri.com/wms" xmlns:esri_wms="http://www.esri.com/wms" version="1.3.0">
 <FeatureInfoCollection layername="Festgesetzte Überschwemmungsgebiete">
  <FeatureInfo>
   <Field><FieldName>OBJECTID</FieldName><FieldValue>9064</FieldValue></Field>
   <Field><FieldName>name</FieldName><FieldValue>Ruhr</FieldValue></Field>
   <Field><FieldName>BR</FieldName><FieldValue> </FieldValue></Field>
   <Field><FieldName>gewkz</FieldName><FieldValue>Null</FieldValue></Field>
  </FeatureInfo>
 </FeatureInfoCollection>
 <FeatureInfoCollection layername="leer"/>
</FeatureInfoResponse>"""


def test_parse_featureinfo_drops_blanks_and_nulls():
    assert esri_wms.parse_featureinfo(XML) == [("Festgesetzte Überschwemmungsgebiete", {"OBJECTID": "9064", "name": "Ruhr"})]


def test_parse_empty_response():
    assert esri_wms.parse_featureinfo('<?xml version="1.0"?><FeatureInfoResponse xmlns="http://www.esri.com/wms" version="1.3.0"/>') == []


def test_params_center_pixel_and_lat_lon_axis_order():
    p = esri_wms.featureinfo_params(51.44, 7.085, "3,5,6")
    assert p["LAYERS"] == p["QUERY_LAYERS"] == "3,5,6" and p["CRS"] == "EPSG:4326"
    assert p["BBOX"] == "51.439000,7.084000,51.441000,7.086000" and p["I"] == p["J"] == 50 and p["WIDTH"] == p["HEIGHT"] == 101
    assert p["INFO_FORMAT"] == "application/vnd.esri.wms_featureinfo_xml" and p["FEATURE_COUNT"] == 10


def test_bbox_keeps_full_precision():
    """`:g` would round 51.455789 to 51.4558 (~11 m) and query the wrong pixel."""
    assert esri_wms.featureinfo_params(51.456789, 7.0, "1")["BBOX"].startswith("51.455789,")


def test_info_format_override():
    assert esri_wms.featureinfo_params(51.44, 7.085, "1", info_format="text/html")["INFO_FORMAT"] == "text/html"
