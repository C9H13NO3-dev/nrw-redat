"""GD NRW "NRW von unten" (GDU) Bürgerversion — hermetic: `_query` is
monkeypatched with the live Planquadrat payload shape (2026-09-04)."""
import pytest

from redat.sources import bergbau as bb


def cell(**over) -> dict:
    base = {
        "OBJECTID": 58981, "b_taoe_p": 0, "b_tabr_p": 0, "b_beba_f": 0, "g_beba_f": 0, "g_erdf_p": 0,
        "g_hoeh_p": None, "g_kars_f": 0, "g_erb1_f": 0, "g_erb2_f": 0, "g_subs_f": 0, "g_aust_f": 0,
        "pq_name": "58981", "g_ausl_f": "", "gb_meth_p": 0, "gb_meth_f": 0, "status_endbearbeitet": "false",
        "zeitstempel": "2026-08-01 00:01:06", "status_bb_gd": 1, "SHAPE_Length": 2000, "SHAPE_Area": 250000,
    }
    base.update(over)
    return base


def patch(monkeypatch, attrs):
    calls = []

    def fake(layer_id, params):
        calls.append((layer_id, params))
        return {"features": [{"attributes": a} for a in attrs]}

    monkeypatch.setattr(bb, "_query", fake)
    return calls


def test_query_uses_planquadrat_layer_with_point(monkeypatch):
    calls = patch(monkeypatch, [cell()])
    bb.get_bergbau(51.388, 7.008)
    (layer_id, params), = calls
    assert layer_id == bb.PLANQUADRAT_LAYER == 22
    assert params["geometry"] == "7.008,51.388"
    assert params["geometryType"] == "esriGeometryPoint" and params["inSR"] == 4326
    assert params["returnGeometry"] == "false"


def test_werden_cell_items_and_rating(monkeypatch):
    patch(monkeypatch, [cell(b_taoe_p=5, b_beba_f=1, g_beba_f=1, g_aust_f=1, status_bb_gd=2)])
    r = bb.get_bergbau(51.388, 7.008)
    assert r["cell_id"] == "58981" and r["cell_size_m"] == 500
    assert r["authority"] == "Bezirksregierung Arnsberg"
    assert r["updated"] == "2026-08-01"
    assert [(i["key"], i["count"], i["weight"]) for i in r["items"]] == [
        ("tagesoeffnung", 5, "red"), ("bergbau_belegt", None, "orange"),
        ("bergbau_moeglich", None, "yellow"), ("gasaustritt", None, "info"),
    ]
    assert all(i["present"] and i["label"] for i in r["items"])
    assert (r["rating"], r["rating_color"]) == ("Tagesbrüche / Tagesöffnungen", "red")


def test_clean_cell(monkeypatch):
    patch(monkeypatch, [cell(g_aust_f=1)])
    r = bb.get_bergbau(51.48, 7.21)
    assert r["authority"] == "Geologischer Dienst NRW"
    assert [i["key"] for i in r["items"]] == ["gasaustritt"]
    assert (r["rating"], r["rating_color"]) == ("Keine Hinweise", "green")


@pytest.mark.parametrize("over,expected", [
    ({}, ("Keine Hinweise", "green")),
    ({"g_erb1_f": 1}, ("Keine Hinweise", "green")),
    ({"g_beba_f": 1}, ("Bergbau möglich", "yellow")),
    ({"g_kars_f": 1}, ("Bergbau möglich", "yellow")),
    ({"b_beba_f": 1}, ("Bergbau belegt", "orange")),
    ({"gb_meth_f": 1}, ("Bergbau belegt", "orange")),
    ({"g_erdf_p": 2}, ("Bergbau belegt", "orange")),
    ({"b_tabr_p": 1, "g_beba_f": 1}, ("Tagesbrüche / Tagesöffnungen", "red")),
])
def test_rating_is_worst_weight(monkeypatch, over, expected):
    patch(monkeypatch, [cell(**over)])
    r = bb.get_bergbau(51.44, 7.01)
    assert (r["rating"], r["rating_color"]) == expected


def test_methan_combines_point_and_area(monkeypatch):
    patch(monkeypatch, [cell(gb_meth_p=3, gb_meth_f=1)])
    (item,) = bb.get_bergbau(51.44, 7.01)["items"]
    assert item["key"] == "methan" and item["count"] == 3 and item["present"]


def test_erdbeben_either_flag(monkeypatch):
    patch(monkeypatch, [cell(g_erb2_f=1)])
    assert [i["key"] for i in bb.get_bergbau(51.44, 7.01)["items"]] == ["erdbeben"]


def test_status_3_is_also_arnsberg(monkeypatch):
    patch(monkeypatch, [cell(status_bb_gd=3)])
    assert bb.get_bergbau(51.44, 7.01)["authority"] == "Bezirksregierung Arnsberg"


def test_no_feature_is_none(monkeypatch):
    patch(monkeypatch, [])
    assert bb.get_bergbau(52.52, 13.40) is None


def test_arcgis_error_payload_raises(monkeypatch):
    monkeypatch.setattr(bb, "_query", lambda layer_id, params: {"error": {"code": 400, "message": "Invalid query"}})
    with pytest.raises(RuntimeError, match="Invalid query"):
        bb.get_bergbau(51.44, 7.01)


def test_http_error_propagates(monkeypatch):
    def boom(layer_id, params):
        raise RuntimeError("timeout")

    monkeypatch.setattr(bb, "_query", boom)
    with pytest.raises(RuntimeError, match="timeout"):
        bb.get_bergbau(51.44, 7.01)
