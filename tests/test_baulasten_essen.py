"""redat/sources/baulasten_essen.py — Essen Baulasteninformation ArcGIS layers 0/1, hermetic."""
import pytest

from redat.sources import baulasten_essen as bl


def feat(art, fsk, blatt="9 / 604 / 1"):
    return {"attributes": {"ART": art, "FSK": fsk, "BAULAST": blatt, "TYP_BL": "baulasten_aktuell", "ALKIS_AMTL_FLAECHE": 538.0}}


def stub(monkeypatch, by_layer: dict):
    calls = []

    def fake(layer, lat, lon, distance_m):
        calls.append((layer, distance_m))
        v = by_layer.get(layer, [])
        if isinstance(v, Exception):
            raise v
        return {"features": v}
    monkeypatch.setattr(bl, "_query", fake)
    return calls


def test_in_essen_bbox():
    assert bl.in_essen(51.4300, 7.0050) is True      # Rüttenscheid
    assert bl.in_essen(51.4818, 7.2162) is False     # Bochum Innenstadt


def test_parse_art():
    assert bl.parse_art("BauOrdnungsrecht / Zufahrt") == ("BauOrdnungsrecht", "Zufahrt")
    assert bl.parse_art("BauOrdnungsrecht /") == ("BauOrdnungsrecht", None)
    assert bl.parse_art("/") == (None, None) and bl.parse_art(None) == (None, None)


def test_outside_essen_is_none_without_query(monkeypatch):
    calls = stub(monkeypatch, {})
    assert bl.get_baulasten(51.4818, 7.2162, "05911001234567") is None and calls == []


def test_on_parcel_vs_nearby_and_status_vorhanden(monkeypatch):
    calls = stub(monkeypatch, {0: [feat("BauOrdnungsrecht / Zufahrt", "05314403900040"),
                                   feat("BauOrdnungsrecht / Abstandfläche", "05314403800349", "9 / 1126 / 1")],
                               1: []})
    d = bl.get_baulasten(51.4300, 7.0050, "05314403900040")
    assert calls == [(0, bl.RADIUS_M), (1, bl.RADIUS_M)]
    assert d["status"] == "vorhanden" and d["radius_m"] == 50
    assert d["on_parcel"] == [{"rechtsgrund": "BauOrdnungsrecht", "art": "Zufahrt", "blatt": "9 / 604 / 1",
                               "kennzeichen": "05314403900040", "status": "vorhanden"}]
    assert d["nearby"] == [{"rechtsgrund": "BauOrdnungsrecht", "art": "Abstandfläche", "blatt": "9 / 1126 / 1",
                            "kennzeichen": "05314403800349", "status": "vorhanden"}]


def test_moeglich_only_on_parcel(monkeypatch):
    stub(monkeypatch, {0: [], 1: [feat("BauOrdnungsrecht /", "05314403900040", "0 / 0 / 0")]})
    d = bl.get_baulasten(51.4300, 7.0050, "05314403900040")
    assert d["status"] == "moeglich" and d["on_parcel"][0]["art"] is None and d["on_parcel"][0]["status"] == "moeglich"


def test_nothing_is_keine_and_dedupes(monkeypatch):
    stub(monkeypatch, {0: [feat("BauOrdnungsrecht / Zufahrt", "05314403800222"), feat("BauOrdnungsrecht / Zufahrt", "05314403800222")], 1: []})
    d = bl.get_baulasten(51.4300, 7.0050, "05314403900040")
    assert d["status"] == "keine" and d["on_parcel"] == [] and len(d["nearby"]) == 1


def test_unknown_kennzeichen_puts_everything_nearby(monkeypatch):
    stub(monkeypatch, {0: [feat("BauOrdnungsrecht / Zufahrt", "05314403900040")], 1: []})
    d = bl.get_baulasten(51.4300, 7.0050, None)
    assert d["status"] == "unbekannt" and d["on_parcel"] == [] and len(d["nearby"]) == 1


def test_malformed_kennzeichen_is_unbekannt(monkeypatch):
    """An 18-char key (Nenner-Flurstück from another Gemarkung) cannot be matched against Essen's 14-char FSK."""
    stub(monkeypatch, {0: [feat("BauOrdnungsrecht / Zufahrt", "05314403900040")], 1: []})
    d = bl.get_baulasten(51.4300, 7.0050, "053144039000400012")
    assert d["status"] == "unbekannt" and d["on_parcel"] == [] and len(d["nearby"]) == 1


def test_two_baulasten_on_one_blatt_both_survive(monkeypatch):
    """Same FSK and BAULAST, different ART — Zufahrt and Abstandfläche are two Baulasten, not a duplicate."""
    stub(monkeypatch, {0: [feat("BauOrdnungsrecht / Zufahrt", "05314403900040"),
                           feat("BauOrdnungsrecht / Abstandfläche", "05314403900040")], 1: []})
    d = bl.get_baulasten(51.4300, 7.0050, "05314403900040")
    assert [i["art"] for i in d["on_parcel"]] == ["Zufahrt", "Abstandfläche"] and d["nearby"] == []


def test_query_failure_propagates(monkeypatch):
    stub(monkeypatch, {0: RuntimeError("503")})
    with pytest.raises(RuntimeError):
        bl.get_baulasten(51.4300, 7.0050, "05314403900040")
