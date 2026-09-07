import pytest

from redat.sources import bergrechte


@pytest.fixture(autouse=True)
def _clear_geoms_cache():
    yield
    bergrechte._geoms.cache_clear()
    bergrechte._tree.cache_clear()


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
    bergrechte._geoms.cache_clear()
    bergrechte._tree.cache_clear()
    items = bergrechte.lookup(51.4300, 7.0050)
    assert [i["feld"] for i in items] == ["Neu Essen", "Metropole Ruhr"]
    assert items[0] == {"feld": "Neu Essen", "art": "aufrechterhaltenes Bergwerkseigentum", "kurz": "Bergwerkseigentum", "bodenschatz": "Eisenerz",
                        "inhaber": "TRATON SE", "seit": "23.01.1791", "erloschen": False, "groesse": "1 000 m²"}
    assert items[1]["kurz"] == "Erlaubnis (Aufsuchung)" and items[1]["seit"] is None


def test_lookup_empty_list_when_nothing_contains_point_and_none_without_grid(monkeypatch):
    monkeypatch.setattr(bergrechte, "_load", lambda: GRID)
    bergrechte._geoms.cache_clear()
    bergrechte._tree.cache_clear()
    assert bergrechte.lookup(51.30, 6.90) == []
    monkeypatch.setattr(bergrechte, "_load", lambda: None)
    bergrechte._geoms.cache_clear()
    bergrechte._tree.cache_clear()
    assert bergrechte.lookup(51.43, 7.0) is None


def test_lookup_empty_list_when_grid_has_no_features(monkeypatch):
    """A present-but-empty grid is `[]` (no rights here), not None ("not installed") — see _geoms()."""
    monkeypatch.setattr(bergrechte, "_load", lambda: {"type": "FeatureCollection", "features": []})
    bergrechte._geoms.cache_clear()
    bergrechte._tree.cache_clear()
    assert bergrechte.lookup(51.43, 7.0) == []


def test_geoms_are_parsed_once_across_two_lookups(monkeypatch):
    """`shape()` must only run once per feature across repeated `lookup()` calls (Important 1)."""
    monkeypatch.setattr(bergrechte, "_load", lambda: GRID)
    bergrechte._geoms.cache_clear()
    bergrechte._tree.cache_clear()
    calls = []
    real_shape = bergrechte.shape

    def counting_shape(geom):
        calls.append(geom)
        return real_shape(geom)

    monkeypatch.setattr(bergrechte, "shape", counting_shape)
    bergrechte.lookup(51.4300, 7.0050)
    bergrechte.lookup(51.4300, 7.0050)
    bergrechte.lookup(51.30, 6.90)
    assert len(calls) == len(GRID["features"])


def test_tree_only_checks_candidates(monkeypatch):
    monkeypatch.setattr(bergrechte, "_load", lambda: GRID)
    bergrechte._geoms.cache_clear(); bergrechte._tree.cache_clear()
    tree = bergrechte._tree()
    assert tree is not None and len(bergrechte._geoms()) == len(GRID["features"])
    assert bergrechte.lookup(51.4818, 7.2162) is not None
