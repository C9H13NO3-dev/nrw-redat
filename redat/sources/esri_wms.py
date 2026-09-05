"""The esri-flavoured WMS GetFeatureInfo every wms.nrw.de service speaks (uesg, irw, wsg, …).

`featureinfo_params` builds the request around the centre pixel of a 101×101 px tile that spans
2·d degrees (d = 0.001 ≈ 110 m → ~2 m/px, small enough for layers with a MinScaleDenominator);
WMS 1.3.0 wants EPSG:4326 BBOX as lat,lon. `parse_featureinfo` flattens
FeatureInfoResponse/FeatureInfoCollection/FeatureInfo/Field into (layername, {name: value}) pairs,
dropping blank and "Null" values.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

INFO_FORMAT = "application/vnd.esri.wms_featureinfo_xml"
_NS = {"w": "http://www.esri.com/wms"}


def featureinfo_params(lat: float, lon: float, layers: str, *, d: float = 0.001, feature_count: int = 10,
                       info_format: str = INFO_FORMAT) -> dict:
    # Six decimals (~0.1 m), never `:g` — six *significant* digits would round the bbox onto an ~11 m grid
    # and move the queried centre pixel off the address.
    return {
        "SERVICE": "WMS", "VERSION": "1.3.0", "REQUEST": "GetFeatureInfo", "LAYERS": layers, "QUERY_LAYERS": layers,
        "STYLES": "", "CRS": "EPSG:4326", "BBOX": f"{lat - d:.6f},{lon - d:.6f},{lat + d:.6f},{lon + d:.6f}",
        "WIDTH": 101, "HEIGHT": 101, "I": 50, "J": 50, "FEATURE_COUNT": feature_count, "INFO_FORMAT": info_format,
    }


def parse_featureinfo(xml_text: str) -> list[tuple[str, dict]]:
    root = ET.fromstring(xml_text)
    out = []
    for coll in root.findall("w:FeatureInfoCollection", _NS):
        layer = coll.get("layername", "")
        for fi in coll.findall("w:FeatureInfo", _NS):
            fields = {}
            for field in fi.findall("w:Field", _NS):
                name = field.findtext("w:FieldName", default="", namespaces=_NS)
                value = (field.findtext("w:FieldValue", default="", namespaces=_NS) or "").strip()
                if name and value and value != "Null":
                    fields[name] = value
            out.append((layer, fields))
    return out
