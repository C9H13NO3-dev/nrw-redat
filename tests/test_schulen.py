import pytest

from redat.sources import schulen

# Rüttenscheid test point 51.4300, 7.0050. 1° lat ≈ 111.2 km, 1° lon ≈ 69.3 km here.
GRID = {"schuljahr": "2025/26", "schools": [
    {"nr": "1", "name": "Käthe-Kollwitz-Schule", "kurzname": "", "form": "Grundschule", "lat": 51.4330, "lon": 7.0050, "adresse": "Christinenstr. 4", "plz": "45131", "ort": "Essen", "schueler": 250, "sozialindex": 3},   # ~330 m N
    {"nr": "2", "name": "GS Süd", "kurzname": "", "form": "Grundschule", "lat": 51.4200, "lon": 7.0050, "adresse": None, "plz": None, "ort": "Essen", "schueler": None, "sozialindex": 7},                                # ~1110 m S
    {"nr": "3", "name": "GS Fern", "kurzname": "", "form": "Grundschule", "lat": 51.4600, "lon": 7.0050, "adresse": None, "plz": None, "ort": "Essen", "schueler": 100, "sozialindex": None},                              # ~3.3 km → out
    {"nr": "4", "name": "Goetheschule", "kurzname": "", "form": "Gymnasium", "lat": 51.4300, "lon": 7.0180, "adresse": None, "plz": None, "ort": "Essen", "schueler": 900, "sozialindex": 2},                              # ~900 m E
    {"nr": "5", "name": "Helmholtz", "kurzname": "", "form": "Gymnasium", "lat": 51.4300, "lon": 7.0260, "adresse": None, "plz": None, "ort": "Essen", "schueler": 800, "sozialindex": 3},                                 # ~1.5 km E (2nd Gym → count only)
    {"nr": "6", "name": "Gesamtschule Holsterhausen", "kurzname": "", "form": "Gesamtschule", "lat": 51.4400, "lon": 7.0050, "adresse": None, "plz": None, "ort": "Essen", "schueler": 1200, "sozialindex": 6},        # ~1.1 km N
    {"nr": "7", "name": "Förderschule X", "kurzname": "", "form": "Förderschule", "lat": 51.4310, "lon": 7.0050, "adresse": None, "plz": None, "ort": "Essen", "schueler": 80, "sozialindex": None},                     # ~110 m
    {"nr": "8", "name": "Berufskolleg Y", "kurzname": "", "form": "Berufskolleg", "lat": 51.4305, "lon": 7.0050, "adresse": None, "plz": None, "ort": "Essen", "schueler": 2000, "sozialindex": None},                   # ignored form
]}


@pytest.fixture(autouse=True)
def grid(monkeypatch):
    monkeypatch.setattr(schulen, "_load", lambda: GRID)
    monkeypatch.setattr(schulen, "_bochum_grundschulbezirk", lambda lat, lon: None)


def test_group_classification_uses_real_schulform_values():
    assert schulen._group("Grundschule") == "grundschulen" and schulen._group("Primus (Schulversuch)") == "grundschulen"
    assert schulen._group("Gymnasium") == schulen._group("Waldorfschule") == "weiterfuehrend"
    assert schulen._group("Förderschule") == "foerderschulen"
    assert schulen._group("Berufskolleg") is None and schulen._group("Weiterbildungskolleg") is None


def test_sozialindex_label():
    assert schulen.sozialindex_label(3) == "Stufe 3 von 9 (geringe soziale Herausforderungen)"
    assert schulen.sozialindex_label(5) == "Stufe 5 von 9 (mittlere soziale Herausforderungen)"
    assert schulen.sozialindex_label(8) == "Stufe 8 von 9 (hohe soziale Herausforderungen)"
    assert schulen.sozialindex_label(None) is None


def test_lookup_groups_sorts_and_counts():
    d = schulen.lookup(51.4300, 7.0050)
    assert d["radius_m"] == 2000 and d["schuljahr"] == "2025/26"
    assert [s["name"] for s in d["grundschulen"]] == ["Käthe-Kollwitz-Schule", "GS Süd"]
    assert 300 < d["grundschulen"][0]["distance_m"] < 360 and d["grundschulen"][0]["sozialindex"] == 3
    assert d["grundschulen"][0]["sozialindex_label"].startswith("Stufe 3")
    assert [s["form"] for s in d["weiterfuehrend"]] == ["Gymnasium", "Gesamtschule"]      # one per form, nearest first
    assert d["weiterfuehrend"][0]["name"] == "Goetheschule"
    assert [s["name"] for s in d["foerderschulen"]] == ["Förderschule X"]
    assert d["counts"] == {"grundschulen": 2, "weiterfuehrend": 3, "foerderschulen": 1}
    assert d["rating"] == "Grundschule fußläufig" and d["rating_color"] == "green"
    assert d["grundschulbezirk"] is None and d["grundschulbezirk_error"] is None


def test_rating_yellow_and_orange(monkeypatch):
    far = {**GRID, "schools": [s for s in GRID["schools"] if s["nr"] != "1"]}
    monkeypatch.setattr(schulen, "_load", lambda: far)
    d = schulen.lookup(51.4300, 7.0050)
    assert d["rating"] == "Grundschule im Umkreis von 2 km" and d["rating_color"] == "yellow"
    monkeypatch.setattr(schulen, "_load", lambda: {**GRID, "schools": []})
    d = schulen.lookup(51.4300, 7.0050)
    assert d["rating"] == "Keine Grundschule im Umkreis von 2 km" and d["rating_color"] == "orange" and d["grundschulen"] == []


def test_bochum_grundschulbezirk_only_in_bochum(monkeypatch):
    calls = []
    monkeypatch.setattr(schulen, "_bochum_grundschulbezirk", lambda lat, lon: calls.append(1) or {"schule": "Arnoldschule, Arnoldstr. 31, 44793 Bochum", "kapazitaet": 196})
    assert schulen.lookup(51.4300, 7.0050)["grundschulbezirk"] is None and calls == []      # Essen → not asked
    d = schulen.lookup(51.4818, 7.2162)                                                        # Bochum
    assert d["grundschulbezirk"] == {"schule": "Arnoldschule, Arnoldstr. 31, 44793 Bochum", "kapazitaet": 196}


def test_bochum_failure_is_isolated(monkeypatch):
    def boom(lat, lon):
        raise RuntimeError("down")
    monkeypatch.setattr(schulen, "_bochum_grundschulbezirk", boom)
    d = schulen.lookup(51.4818, 7.2162)
    assert d["grundschulbezirk"] is None and d["grundschulbezirk_error"] == "down"


def test_missing_grid_is_none(monkeypatch):
    monkeypatch.setattr(schulen, "_load", lambda: None)
    assert schulen.lookup(51.43, 7.0) is None


def test_parse_grundschulbezirk_response():
    assert schulen.parse_grundschulbezirk({"features": [{"attributes": {"SCHULNAME": "Arnoldschule, Arnoldstr. 31, 44793 Bochum", "KAP_20_21": 196}}]}) == \
        {"schule": "Arnoldschule, Arnoldstr. 31, 44793 Bochum", "kapazitaet": 196}
    assert schulen.parse_grundschulbezirk({"features": []}) is None
