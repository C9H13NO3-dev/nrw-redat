"""backend/energie_service.py — Solarkataster + GD Geothermie + Wärmeplanung, hermetic (all HTTP points stubbed)."""
import pytest

from redat.sources import energie as es

# Kettwig house (live shape 2026-09-04) — 211 m² outline just south-west of the geocoded point.
HOUSE_RING = [[6.940711, 51.361508], [6.940747, 51.361591], [6.940838, 51.361577], [6.940776, 51.361434],
              [6.940716, 51.361294], [6.940626, 51.361309], [6.940687, 51.361450], [6.940711, 51.361508]]
BLOCK_RING = [[6.9420, 51.3610], [6.9430, 51.3610], [6.9430, 51.3620], [6.9420, 51.3620], [6.9420, 51.3610]]
SHED_RING = [[6.94100, 51.36160], [6.94104, 51.36160], [6.94104, 51.36163], [6.94100, 51.36163], [6.94100, 51.36160]]
SEGMENTS = [
    {"mod_id": "M1", "himmel_kat": "Ost", "neigung": 20, "radabs": 923, "modanetto_int": 8, "kw": 1.74, "str": 1298.284, "dachtyp": "geneigt", "jahr": "2020", "richtung": 116},
    {"mod_id": "M2", "himmel_kat": "West", "neigung": 17, "radabs": 870, "modanetto_int": 16, "kw": 3.48, "str": 2447.623, "dachtyp": "geneigt", "jahr": "2020", "richtung": 269},
    {"mod_id": "M3", "himmel_kat": "Flach", "neigung": 0, "radabs": 1060, "modanetto_int": 10, "kw": 2.175, "str": 1863.921, "dachtyp": "flach", "jahr": "2020", "richtung": -1},
]
GT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<FeatureInfoResponse xmlns="http://www.esri.com/wms" version="1.3.0">
 <FeatureInfoCollection layername="100 m Sondenlaenge"><FeatureInfo>
  <Field><FieldName>klasse_wlf100</FieldName><FieldValue>3</FieldValue></Field>
  <Field><FieldName>klassen_wertebereich</FieldName><FieldValue>2,5 - 2,9</FieldValue></Field>
 </FeatureInfo></FeatureInfoCollection>
 <FeatureInfoCollection layername="80 m Sondenlaenge"><FeatureInfo>
  <Field><FieldName>klasse_wlf80</FieldName><FieldValue>3</FieldValue></Field>
  <Field><FieldName>klassen_wertebereich</FieldName><FieldValue>2,5 - 2,9</FieldValue></Field>
 </FeatureInfo></FeatureInfoCollection>
 <FeatureInfoCollection layername="60 m Sondenlaenge"><FeatureInfo>
  <Field><FieldName>klasse_wlf60</FieldName><FieldValue>4</FieldValue></Field>
  <Field><FieldName>klassen_wertebereich</FieldName><FieldValue>2,0 - 2,4</FieldValue></Field>
 </FeatureInfo></FeatureInfoCollection>
 <FeatureInfoCollection layername="Hydrologisch sensible Bereiche"><FeatureInfo>
  <Field><FieldName>OBJECTID</FieldName><FieldValue>1</FieldValue></Field>
 </FeatureInfo></FeatureInfoCollection>
 <FeatureInfoCollection layername="1800 (2400) Betriebsstunden/Jahr"><FeatureInfo>
  <Field><FieldName>ewk_wert</FieldName><FieldValue>mittel</FieldValue></Field>
 </FeatureInfo></FeatureInfoCollection>
</FeatureInfoResponse>"""
GT_EMPTY = '<?xml version="1.0"?><FeatureInfoResponse xmlns="http://www.esri.com/wms" version="1.3.0"/>'
ESSEN_ATTRS = {"GEBIETSEINTEILUNG": "Wärmenetzausbaugebiet", "PREFERENCE_AREA": "Wärmenetzausbaugebiet - sehr wahrscheinlich geeignet",
               "HAS_HEAT_GRID_2024": 1, "HAS_HEAT_GRID_2045": 1, "HEAT_GRID_CLASS": "Sehr wahrscheinlich geeignet"}


def bld(ring, geb_id="Geb1", area=211.6, name="DENW22AL900008T2"):
    return {"attributes": {"geb_id": geb_id, "name": name, "Shape_Area": area}, "geometry": {"rings": [ring]}}


class Stub:
    """Routes the three HTTP points; records every ArcGIS query."""

    def __init__(self, monkeypatch, *, buildings_contains=(), buildings_near=(), segments=(), gt_xml=GT_EMPTY,
                 essen=(), bochum=(), wsg=()):
        self.calls = []
        self.cfg = dict(buildings_contains=list(buildings_contains), buildings_near=list(buildings_near),
                        segments=list(segments), essen=list(essen), bochum=list(bochum))

        def query(url, params):
            self.calls.append((url, params))
            if isinstance(self.cfg.get("raise_for"), str) and self.cfg["raise_for"] in url:
                raise RuntimeError("down")
            if url == f"{es.SOLAR_URL}/{es.SOLAR_BUILDINGS_LAYER}":
                feats = self.cfg["buildings_near"] if "distance" in params else self.cfg["buildings_contains"]
                return {"features": feats}
            if url == f"{es.SOLAR_URL}/{es.SOLAR_PV_LAYER}":
                return {"features": [{"attributes": s} for s in self.cfg["segments"]]}
            if url == es.ESSEN_KWP_URL:
                return {"features": [{"attributes": a} for a in self.cfg["essen"]]}
            raise AssertionError(url)

        def identify(url, params):
            self.calls.append((url, params))
            return {"results": self.cfg["bochum"]}

        monkeypatch.setattr(es, "_arcgis_query", query)
        monkeypatch.setattr(es, "_arcgis_identify", identify)
        monkeypatch.setattr(es, "_gt_featureinfo", lambda lat, lon: gt_xml)
        monkeypatch.setattr(es, "_wsg_zones", lambda lat, lon: list(wsg))


def test_pv_prefers_containing_building_and_queries_segments_with_contains(monkeypatch):
    st = Stub(monkeypatch, buildings_contains=[bld(HOUSE_RING)], buildings_near=[bld(BLOCK_RING, "Geb9", 5000)], segments=SEGMENTS)
    pv = es.get_energie(51.36150, 6.94072)["pv"]
    assert pv["building"] == {"geb_id": "Geb1", "alkis_id": "DENW22AL900008T2", "area_m2": 211.6, "picked": "contains"}
    seg_call = next(p for u, p in st.calls if u.endswith(f"/{es.SOLAR_PV_LAYER}"))
    assert seg_call["spatialRel"] == "esriSpatialRelContains" and seg_call["geometryType"] == "esriGeometryPolygon"
    assert '"rings"' in seg_call["geometry"]
    assert pv["total_kwp"] == 7.4 and pv["total_kwh_a"] == 5610 and pv["module_area_m2"] == 34
    assert pv["segment_count"] == 3 and [s["orientation"] for s in pv["segments"]] == ["West", "Flach", "Ost"]
    assert pv["segments"][0] == {"orientation": "West", "tilt_deg": 17, "area_m2": 16, "kwp": 3.5, "kwh_a": 2448,
                                 "radiation_kwh_m2": 870, "roof": "geneigt"}
    assert pv["best_orientation"] == "West" and pv["household_equivalents"] == 1.4 and pv["survey_year"] == "2020"
    assert pv["rating"] == "Gut" and pv["rating_color"] == "green"


def test_pv_nearest_building_skips_sheds_and_prefers_closest_not_largest(monkeypatch):
    # point on the street: the small house is ~10 m away, the big block ~90 m, the shed 5 m but 9 m²
    Stub(monkeypatch, buildings_near=[bld(BLOCK_RING, "Block", 5000), bld(HOUSE_RING, "House", 211.6), bld(SHED_RING, "Shed", 9)],
         segments=SEGMENTS)
    pv = es.get_energie(51.3616, 6.9411)["pv"]
    assert pv["building"]["geb_id"] == "House" and pv["building"]["picked"] == "nearest"


def test_pv_none_without_building_and_ratings(monkeypatch):
    Stub(monkeypatch)
    d = es.get_energie(51.4586, 7.1934)
    assert d is None  # nothing at all → Empty upstream

    Stub(monkeypatch, buildings_contains=[bld(HOUSE_RING)], segments=[])
    pv = es.get_energie(51.3615, 6.9407)["pv"]
    assert pv["segment_count"] == 0 and pv["rating"] == "Keine geeigneten Dachflächen" and pv["rating_color"] == "gray"

    for kwh, expect in [(9000, ("Sehr gut", "green")), (4500, ("Gut", "green")), (2500, ("Mäßig", "yellow")), (500, ("Gering", "orange"))]:
        assert es._rate_pv(kwh) == expect


def test_erdwaerme_parse_and_rating(monkeypatch):
    Stub(monkeypatch, gt_xml=GT_XML)
    ew = es.get_energie(51.4378, 7.0053)["erdwaerme"]
    assert ew["probes"] == [
        {"depth": "100 m", "class": 3, "range": "2,5 – 2,9", "lower_w_mk": 2.5},
        {"depth": "80 m", "class": 3, "range": "2,5 – 2,9", "lower_w_mk": 2.5},
        {"depth": "60 m", "class": 4, "range": "2,0 – 2,4", "lower_w_mk": 2.0},
    ]
    assert ew["collector"] == "mittel" and ew["hydro_sensitive"] is True and ew["high_groundwater_flow"] is False
    assert ew["rating"] == "Gut" and ew["rating_color"] == "green" and ew["wsg_note"] is None
    assert es._rate_erdwaerme(2.0) == ("Mittel", "yellow") and es._rate_erdwaerme(1.5) == ("Gering", "orange")


def test_erdwaerme_wsg_note_downgrades(monkeypatch):
    Stub(monkeypatch, gt_xml=GT_XML, wsg=[{"name": "Essen-Burgaltendorf/Horst", "zone": "II", "status": "geplant"}])
    ew = es.get_energie(51.44, 7.085)["erdwaerme"]
    assert ew["rating_color"] == "red" and "Zone II" in ew["wsg_note"] and "unzulässig" in ew["wsg_note"]
    assert ew["rating"] == "Unzulässig (Wasserschutzgebiet)"
    Stub(monkeypatch, gt_xml=GT_XML, wsg=[{"name": "Witten", "zone": "III", "status": "festgesetzt"}])
    ew = es.get_energie(51.437, 7.33)["erdwaerme"]
    assert ew["rating_color"] == "orange" and "Genehmigung" in ew["wsg_note"]
    assert ew["rating"] == "Gut, genehmigungspflichtig"


def test_waermeplanung_essen_mapping(monkeypatch):
    st = Stub(monkeypatch, essen=[ESSEN_ATTRS])
    wp = es.get_energie(51.4378, 7.0053)["waermeplanung"]
    assert wp["city"] == "Essen" and wp["status"] == "beschlossen" and wp["target_year"] == 2045
    assert wp["category"] == "fernwaerme_bestand" and wp["label"] == "Wärmenetzausbaugebiet"
    assert wp["detail"] == "sehr wahrscheinlich geeignet" and wp["has_grid_2024"] is True and wp["has_grid_2045"] is True
    assert wp["color"] == "green" and wp["link"].startswith("https://")
    essen_call = next(p for u, p in st.calls if u == es.ESSEN_KWP_URL)
    assert essen_call["distance"] == 30 and essen_call["units"] == "esriSRUnit_Meter"
    # Bochum is not asked when Essen answers
    assert not any(u.startswith(es.BOCHUM_KWP_URL) for u, _ in st.calls)

    for g, has24, cat, color in [("Wärmenetzausbaugebiet", 0, "fernwaerme_ausbau", "green"), ("Prüfgebiet Wärmenetze", 0, "pruefgebiet_waermenetz", "yellow"),
                                 ("Prüfgebiet Wasserstoff", 0, "pruefgebiet_wasserstoff", "yellow"), ("Dezentral", 0, "dezentral", "gray"),
                                 ("Sonderfall", 0, "sonstiges", "gray")]:
        Stub(monkeypatch, essen=[{"GEBIETSEINTEILUNG": g, "HAS_HEAT_GRID_2024": has24, "HAS_HEAT_GRID_2045": 0, "PREFERENCE_AREA": g}])
        wp = es.get_energie(51.4, 7.0)["waermeplanung"]
        assert (wp["category"], wp["color"], wp["detail"]) == (cat, color, None)


def test_waermeplanung_bochum_fallback_lowest_layer_wins(monkeypatch):
    Stub(monkeypatch, bochum=[
        {"layerId": 2, "layerName": "Prüfgebiete", "attributes": {"Zielbild": "Prüfgebiet"}},
        {"layerId": 0, "layerName": "Fernwärme Bestands- und Verdichtungsgebiet", "attributes": {"Zielbild": "Fernwärme Bestands- und Verdichtungsgebiet"}},
    ])
    wp = es.get_energie(51.4818, 7.2162)["waermeplanung"]
    assert wp["city"] == "Bochum" and wp["status"] == "Entwurf" and wp["category"] == "fernwaerme_bestand"
    assert wp["label"] == "Fernwärme Bestands- und Verdichtungsgebiet" and wp["has_grid_2024"] is None

    Stub(monkeypatch, bochum=[{"layerId": 6, "layerName": "Neubaugebiete", "attributes": {"Name": "Ostpark"}}])
    wp = es.get_energie(51.48, 7.25)["waermeplanung"]
    assert wp["category"] == "sonstiges" and wp["label"] == "Neubaugebiete" and wp["detail"] == "Ostpark"

    Stub(monkeypatch)
    assert es.get_energie(51.48, 7.25) is None


def test_part_failure_is_isolated(monkeypatch):
    st = Stub(monkeypatch, gt_xml=GT_XML, essen=[ESSEN_ATTRS])
    st.cfg["raise_for"] = es.SOLAR_URL
    d = es.get_energie(51.4378, 7.0053)
    assert d["pv"] is None and d["erdwaerme"]["rating"] == "Gut" and d["waermeplanung"]["city"] == "Essen"
    assert d["errors"] == {"pv": "down"}


def test_all_parts_failing_raises(monkeypatch):
    st = Stub(monkeypatch)
    st.cfg["raise_for"] = "https://"
    monkeypatch.setattr(es, "_gt_featureinfo", lambda lat, lon: (_ for _ in ()).throw(RuntimeError("gt down")))
    monkeypatch.setattr(es, "_arcgis_identify", lambda url, params: (_ for _ in ()).throw(RuntimeError("down")))
    with pytest.raises(RuntimeError):
        es.get_energie(51.4378, 7.0053)
