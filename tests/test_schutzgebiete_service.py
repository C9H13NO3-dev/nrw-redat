"""backend/schutzgebiete_service.py — LINFOS WFS + WSG GFI, hermetic (both HTTP points stubbed)."""
import pytest

from redat.sources import schutzgebiete as sg

# Heisinger Ruhraue NSG polygon (simplified) — a box south of the Ruhr, WGS84 lon/lat.
NSG_RING = [[7.070, 51.398], [7.080, 51.398], [7.080, 51.404], [7.070, 51.404], [7.070, 51.398]]
LSG_RING = [[7.066, 51.405], [7.080, 51.405], [7.080, 51.412], [7.066, 51.412], [7.066, 51.405]]


def feat(kind_id, ring, **props):
    base = {"GmlID": f"x.{kind_id}", "kennung": "E-003", "gebietsname": "NSG Heisinger Ruhraue",
            "schutz_agg": "NSG, bestehend", "hyperlink": "https://www.wms.nrw.de/html/7680100/E-003.html",
            "inkraft": 1992.0, "fl_anz": 1.0}
    base.update(props)
    return {"type": "Feature", "properties": base,
            "geometry": {"type": "MultiPolygon", "coordinates": [[ring]]}}


WSG_XML = """<?xml version="1.0" encoding="UTF-8"?>
<FeatureInfoResponse xmlns="http://www.esri.com/wms" version="1.3.0">
 <FeatureInfoCollection layername="Trinkwasser festgesetzt">
  <FeatureInfo>
   <Field><FieldName>zone_</FieldName><FieldValue>3</FieldValue></Field>
   <Field><FieldName>zone_roemisch</FieldName><FieldValue>III</FieldValue></Field>
   <Field><FieldName>name</FieldName><FieldValue>Verbund-Wasserwerk Witten</FieldValue></Field>
   <Field><FieldName>status</FieldName><FieldValue>F</FieldValue></Field>
   <Field><FieldName>datum_verordnung</FieldName><FieldValue>28.8.1981</FieldValue></Field>
   <Field><FieldName>gueltig_seit</FieldName><FieldValue>1.10.1981</FieldValue></Field>
   <Field><FieldName>flaeche_km2</FieldName><FieldValue>10,823</FieldValue></Field>
  </FeatureInfo>
 </FeatureInfoCollection>
 <FeatureInfoCollection layername="Trinkwasser geplant">
  <FeatureInfo>
   <Field><FieldName>zone_roemisch</FieldName><FieldValue>II</FieldValue></Field>
   <Field><FieldName>name</FieldName><FieldValue>Essen-Burgaltendorf/Horst</FieldValue></Field>
   <Field><FieldName>status</FieldName><FieldValue>P</FieldValue></Field>
   <Field><FieldName>gueltig_seit</FieldName><FieldValue>Null</FieldValue></Field>
  </FeatureInfo>
 </FeatureInfoCollection>
</FeatureInfoResponse>"""
WSG_EMPTY = '<?xml version="1.0"?><FeatureInfoResponse xmlns="http://www.esri.com/wms" version="1.3.0"/>'


def stub(monkeypatch, by_type: dict, wsg_xml: str = WSG_EMPTY):
    calls = []

    def wfs(typename, bbox):
        calls.append((typename, bbox))
        v = by_type.get(typename, [])
        if isinstance(v, Exception):
            raise v
        return v
    monkeypatch.setattr(sg, "_wfs_features", wfs)
    monkeypatch.setattr(sg, "_wsg_featureinfo", lambda lat, lon: wsg_xml)
    return calls


def test_bbox_is_utm32_metres_around_point():
    xmin, ymin, xmax, ymax = sg._bbox_25832(51.4130, 7.0730, 500)
    assert abs((xmax - xmin) - 1000) < 0.01 and abs((ymax - ymin) - 1000) < 0.01
    assert 360_000 < xmin < 370_000 and 5_697_000 < ymin < 5_699_000


def test_inside_nsg_is_red_and_lists_distance_zero(monkeypatch):
    calls = stub(monkeypatch, {"wfs_linfos:nsg_polygon": [feat(1, NSG_RING)],
                               "wfs_linfos:lsg_polygon": [feat(2, LSG_RING, kennung="LSG-1", gebietsname="LSG Ruhrtal", schutz_agg="LSG, bestehend")]})
    d = sg.get_schutzgebiete(51.401, 7.075)
    assert {t for t, _ in calls} == {t for _, t, _ in sg.LINFOS_TYPES}
    assert d["rating"] == "Im Naturschutzgebiet" and d["rating_color"] == "red"
    assert d["areas"][0]["kind"] == "nsg" and d["areas"][0]["inside"] and d["areas"][0]["distance_m"] == 0
    assert d["areas"][0]["name"] == "NSG Heisinger Ruhraue" and d["areas"][0]["kind_label"] == "Naturschutzgebiet"
    assert d["areas"][0]["link"].endswith("E-003.html") and d["areas"][0]["since"] == 1992
    lsg = d["areas"][1]
    assert lsg["kind"] == "lsg" and not lsg["inside"] and 0 < lsg["distance_m"] <= 500
    assert d["radius_m"] == 500 and d["wsg"] == [] and d["errors"] == {}


def test_nearby_only_is_yellow_and_far_areas_dropped(monkeypatch):
    far = [[7.30, 51.40], [7.31, 51.40], [7.31, 51.41], [7.30, 51.41], [7.30, 51.40]]
    stub(monkeypatch, {"wfs_linfos:nsg_polygon": [feat(1, NSG_RING), feat(3, far, gebietsname="weit weg")]})
    d = sg.get_schutzgebiete(51.4070, 7.075)  # ~330 m north of the NSG box
    assert d["rating"] == "Schutzgebiet in der Nähe" and d["rating_color"] == "yellow"
    assert [a["name"] for a in d["areas"]] == ["NSG Heisinger Ruhraue"]
    assert 250 < d["areas"][0]["distance_m"] < 400


def test_inside_lsg_is_orange(monkeypatch):
    stub(monkeypatch, {"wfs_linfos:lsg_polygon": [feat(2, LSG_RING, schutz_agg="LSG, bestehend")]})
    d = sg.get_schutzgebiete(51.408, 7.070)
    assert d["rating"] == "Im Landschaftsschutzgebiet" and d["rating_color"] == "orange"


def test_nothing_is_green(monkeypatch):
    stub(monkeypatch, {})
    d = sg.get_schutzgebiete(51.44, 7.00)
    assert d["rating"] == "Keine Schutzgebiete" and d["rating_color"] == "green" and d["areas"] == []


def test_wsg_parsed_and_rated(monkeypatch):
    stub(monkeypatch, {}, WSG_XML)
    d = sg.get_schutzgebiete(51.437, 7.33)
    assert d["wsg"] == [
        {"name": "Verbund-Wasserwerk Witten", "zone": "III", "status": "festgesetzt", "kind": "Trinkwasser",
         "since": "1.10.1981", "ordinance": "28.8.1981", "area_km2": 10.823},
        {"name": "Essen-Burgaltendorf/Horst", "zone": "II", "status": "geplant", "kind": "Trinkwasser",
         "since": None, "ordinance": None, "area_km2": None},
    ]
    # zone II present → red even though the fixed one is only zone III
    assert d["rating"] == "Wasserschutzgebiet Zone II" and d["rating_color"] == "red"


def test_wsg_zone3_is_orange_and_beats_nearby(monkeypatch):
    xml = WSG_XML.replace("<FieldValue>II</FieldValue>", "<FieldValue>III B</FieldValue>")
    stub(monkeypatch, {"wfs_linfos:nsg_polygon": [feat(1, NSG_RING)]}, xml)
    d = sg.get_schutzgebiete(51.4070, 7.075)
    assert d["rating"] == "Wasserschutzgebiet Zone III" and d["rating_color"] == "orange"


def test_partial_wfs_failure_tolerated_total_failure_raises(monkeypatch):
    stub(monkeypatch, {"wfs_linfos:nsg_polygon": [feat(1, NSG_RING)], "wfs_linfos:ffh_polygon": RuntimeError("timeout")})
    d = sg.get_schutzgebiete(51.401, 7.075)
    assert d["rating_color"] == "red" and d["errors"] == {"ffh": "timeout"}

    stub(monkeypatch, {t: RuntimeError("down") for _, t, _ in sg.LINFOS_TYPES})
    with pytest.raises(RuntimeError):
        sg.get_schutzgebiete(51.401, 7.075)


def test_biotopes_capped_per_kind_with_counts(monkeypatch):
    biotopes = [feat(10 + i, [[7.076 + i * 0.0005, 51.405], [7.0762 + i * 0.0005, 51.405], [7.0762 + i * 0.0005, 51.4052],
                              [7.076 + i * 0.0005, 51.4052], [7.076 + i * 0.0005, 51.405]],
                     gebietsname=None, kennung=None, schutz_agg="") for i in range(8)]
    stub(monkeypatch, {"wfs_linfos:gbt_polygon": biotopes, "wfs_linfos:nsg_polygon": [feat(1, NSG_RING)]})
    d = sg.get_schutzgebiete(51.4045, 7.0765)
    assert d["counts"] == {"gbt": 8, "nsg": 1}
    assert sum(1 for a in d["areas"] if a["kind"] == "gbt") == sg._MAX_PER_KIND
    assert all(a["name"] == "Geschützter Biotop" for a in d["areas"] if a["kind"] == "gbt")


def test_wsg_failure_is_isolated(monkeypatch):
    stub(monkeypatch, {})

    def boom(lat, lon):
        raise RuntimeError("wsg down")
    monkeypatch.setattr(sg, "_wsg_featureinfo", boom)
    d = sg.get_schutzgebiete(51.44, 7.00)
    assert d["wsg"] == [] and d["errors"] == {"wsg": "wsg down"} and d["rating_color"] == "green"
