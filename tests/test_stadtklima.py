"""redat/sources/stadtklima.py — LANUV Klimaanalyse NRW GetFeatureInfo, hermetic (`_featureinfo` stubbed per layer)."""
import pytest

from redat.sources import stadtklima as sk

LAT, LON = 50.7160, 7.0748   # Bonn, Am Käferberg

BONN = {
    "59": {"KT_R02_2": "5", "Klimatoptyp": "Vorstadtklima"},
    "54": {"Classify.Pixel Value": "38.290001", "Classify.Class value": "4"},
    "52": {"Classify.Pixel Value": "43.080002", "Classify.Class value": "5"},
    "38": {"Classify.Pixel Value": "16.180000", "Classify.Class value": "2"},
    "29": {"Classify.Pixel Value": "20.450001", "Classify.Class value": "5"},
}


def stub(monkeypatch, by_layer: dict):
    calls = []

    def fi(layer, lat, lon):
        calls.append(layer)          # list.append is atomic under the GIL; assertions use set(calls)
        v = by_layer.get(layer, {})
        if isinstance(v, Exception):
            raise v
        return v
    monkeypatch.setattr(sk, "_featureinfo", fi)
    return calls


def test_layers_cover_the_five_spec_layers():
    assert sk.LAYERS == {"klimatop": "59", "pet_typisch": "54", "pet_extrem": "52", "nacht_typisch": "38", "nacht_extrem": "29"}


def test_pet_classes_follow_the_lanuv_legend():
    assert sk.pet_class(45.0) == ("extrem starke Wärmebelastung", "red")
    assert sk.pet_class(41.0) == ("starke Wärmebelastung", "orange")
    assert sk.pet_class(38.3) == ("starke Wärmebelastung", "orange")
    assert sk.pet_class(30.0) == ("moderate Wärmebelastung", "yellow")
    assert sk.pet_class(25.0) == ("leichte Wärmebelastung", "green")
    assert sk.pet_class(20.0) == ("kein thermischer Stress", "green")
    assert sk.pet_class(15.0) == ("leichter Kältestress", "green")


def test_bonn_values_and_rating(monkeypatch):
    calls = stub(monkeypatch, BONN)
    d = sk.get_stadtklima(LAT, LON)
    assert set(calls) == {"59", "54", "52", "38", "29"}
    assert d["klimatop"] == "Vorstadtklima"
    assert d["pet_typisch"] == 38.3 and d["pet_extrem"] == 43.1
    assert d["nacht_typisch"] == 16.2 and d["nacht_extrem"] == 20.5
    assert d["klasse_typisch"] == "starke Wärmebelastung" and d["klasse_extrem"] == "extrem starke Wärmebelastung"
    assert d["rating"] == "starke Wärmebelastung" and d["rating_color"] == "orange"
    assert d["errors"] == {} and "kein Messwert" in d["hinweis"]


def test_nodata_and_missing_feature_are_none(monkeypatch):
    stub(monkeypatch, {"59": {}, "54": {"Classify.Pixel Value": "NoData"}, "52": {}, "38": {"Classify.Pixel Value": "NoData"}, "29": {}})
    d = sk.get_stadtklima(LAT, LON)
    assert d["klimatop"] is None and d["pet_typisch"] is None and d["klasse_typisch"] is None and d["nacht_extrem"] is None
    assert d["rating"] == "unbekannt" and d["rating_color"] == "gray" and d["errors"] == {}


def test_rating_falls_back_to_extreme_day(monkeypatch):
    stub(monkeypatch, {**BONN, "54": {"Classify.Pixel Value": "NoData"}})
    d = sk.get_stadtklima(LAT, LON)
    assert d["pet_typisch"] is None and d["rating"] == "extrem starke Wärmebelastung" and d["rating_color"] == "red"


def test_one_layer_failing_is_isolated(monkeypatch):
    stub(monkeypatch, {**BONN, "38": RuntimeError("503 Service Unavailable")})
    d = sk.get_stadtklima(LAT, LON)
    assert d["nacht_typisch"] is None and d["pet_typisch"] == 38.3
    assert list(d["errors"]) == ["nacht_typisch"] and "503" in d["errors"]["nacht_typisch"]


def test_outside_nrw_is_none_without_http(monkeypatch):
    calls = stub(monkeypatch, BONN)
    assert sk.get_stadtklima(52.37, 4.90) is None and calls == []


def test_featureinfo_request_shape(monkeypatch):
    seen = {}

    def get(url, params=None, headers=None, timeout=None):
        seen.update(url=url, params=params, headers=headers)

        class R:
            status_code = 200
            def raise_for_status(self): pass
            def json(self): return {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {"Klimatoptyp": "Stadtklima"}}]}
        return R()
    monkeypatch.setattr(sk.httpx, "get", get)
    assert sk._featureinfo("59", 51.43, 7.005) == {"Klimatoptyp": "Stadtklima"}
    p = seen["params"]
    assert seen["url"] == sk.WMS_URL and p["REQUEST"] == "GetFeatureInfo" and p["INFO_FORMAT"] == "application/geo+json"
    assert p["LAYERS"] == "59" and p["QUERY_LAYERS"] == "59" and p["CRS"] == "EPSG:25832" and p["I"] == 50 and p["J"] == 50
    xmin, ymin, xmax, ymax = (float(v) for v in p["BBOX"].split(","))
    assert 99 < xmax - xmin < 101 and 99 < ymax - ymin < 101 and "User-Agent" in seen["headers"]
