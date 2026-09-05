from redat.sources import planning_bochum as pb


def stub(monkeypatch, by_layer: dict):
    def fake(layer, lat, lon):
        v = by_layer.get(layer, [])
        if isinstance(v, Exception):
            raise v
        return {"features": [{"attributes": a} for a in v]}
    monkeypatch.setattr(pb, "_arcgis_query", fake)


def test_stadterneuerung_items(monkeypatch):
    stub(monkeypatch, {
        7: [{"Titel": "ISEK Hamme", "Fördergebi": "Soziale Stadt Hamme", "Förderprog": "Sozialer  Zusammenhalt",
             "Homepage": "https://www.bochum.de/…/Stadterneuerung-Hamme", "Start": 0, "Ende": 2028, "Kategorie": "Stadterneuerungsgebiet"}],
        16: [{"Name": "STEK Wattenscheid-Mitte"}],
        20: [{"FID": 3, "ID": 1}],
    })
    items, errors = pb.stadterneuerung(51.4818, 7.2162)
    assert errors == {}
    assert items == [
        {"official_name": "ISEK Hamme", "plan_type": "Stadterneuerungsgebiet", "legal_status": "Sozialer Zusammenhalt, bis 2028",
         "plan_link": "https://www.bochum.de/…/Stadterneuerung-Hamme"},
        {"official_name": "STEK Wattenscheid-Mitte", "plan_type": "Stadtteilentwicklungskonzept"},
        {"official_name": "1036 S - Laer West", "plan_type": "Stadtumbausatzung"},
    ]


def test_layer_failure_is_isolated(monkeypatch):
    stub(monkeypatch, {8: RuntimeError("timeout"), 9: [{"Titel": "Stadtumbau Laer", "Förderprog": "Stadtumbau West", "Ende": 0, "Kategorie": "Stadterneuerungsgebiet"}]})
    items, errors = pb.stadterneuerung(51.4818, 7.2162)
    assert [i["official_name"] for i in items] == ["Stadtumbau Laer"] and items[0]["legal_status"] == "Stadtumbau West"
    assert errors == {8: "timeout"}


def test_outline_merges_stadterneuerung(monkeypatch):
    monkeypatch.setattr(pb, "_wms_getfeatureinfo_html", lambda lat, lon: "<html></html>")
    stub(monkeypatch, {7: [{"Titel": "ISEK Hamme", "Kategorie": "Stadterneuerungsgebiet", "Ende": 2028}]})
    d = pb.get_bochum_bplan_outline(51.4818, 7.2162)
    assert d["ok"] and d["found"] and d["items"][0]["official_name"] == "ISEK Hamme" and d["errors"] == {}
