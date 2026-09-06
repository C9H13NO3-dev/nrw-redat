import pytest

from redat.sources import bergrechte


def feat(name, art, ring, **props):
    base = {"feld": name, "art": art, "bodenschatz": "Steinkohle", "inhaber": "RAG AKTIENGESELLSCHAFT", "seit": "01.01.1900", "bis": None,
            "erloschen": False, "groesse": "1 000 m²", "nummer": "1"}
    base.update(props)
    return {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [ring]}, "properties": base}


BIG = [[6.99, 51.42], [7.02, 51.42], [7.02, 51.44], [6.99, 51.44], [6.99, 51.42]]
FAR = [[7.20, 51.48], [7.21, 51.48], [7.21, 51.49], [7.20, 51.49], [7.20, 51.48]]
GRID = {"type": "FeatureCollection", "features": [
    feat("Metropole Ruhr", "Erlaubnis zu gewerblichen Zwecken", BIG, bodenschatz="Erdwärme", inhaber="Deutsche ErdWärme GmbH & Co. KG; DMT GmbH", seit=None),
    feat("Neu Essen", "aufrechterhaltenes Bergwerkseigentum", BIG, bodenschatz="Eisenerz", inhaber="TRATON SE", seit="23.01.1791"),
    feat("Fern", "Bewilligung", FAR),
]}


def test_kurz_labels():
    assert bergrechte.kurz("aufrechterhaltenes Bergwerkseigentum") == "Bergwerkseigentum"
    assert bergrechte.kurz("Erlaubnis zu gewerblichen Zwecken") == "Erlaubnis (Aufsuchung)"
    assert bergrechte.kurz("Bewilligung") == "Bewilligung"
    assert bergrechte.kurz("irgendwas") == "irgendwas"


def test_lookup_returns_containing_fields_ownership_first(monkeypatch):
    monkeypatch.setattr(bergrechte, "_load", lambda: GRID)
    items = bergrechte.lookup(51.4300, 7.0050)
    assert [i["feld"] for i in items] == ["Neu Essen", "Metropole Ruhr"]
    assert items[0] == {"feld": "Neu Essen", "art": "aufrechterhaltenes Bergwerkseigentum", "kurz": "Bergwerkseigentum", "bodenschatz": "Eisenerz",
                        "inhaber": "TRATON SE", "seit": "23.01.1791", "erloschen": False, "groesse": "1 000 m²"}
    assert items[1]["kurz"] == "Erlaubnis (Aufsuchung)" and items[1]["seit"] is None


def test_lookup_empty_list_when_nothing_contains_point_and_none_without_grid(monkeypatch):
    monkeypatch.setattr(bergrechte, "_load", lambda: GRID)
    assert bergrechte.lookup(51.30, 6.90) == []
    monkeypatch.setattr(bergrechte, "_load", lambda: None)
    assert bergrechte.lookup(51.43, 7.0) is None
