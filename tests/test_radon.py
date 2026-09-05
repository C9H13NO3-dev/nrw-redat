import pytest

from redat.sources import radon


def cell(ring, **props):
    return {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [ring]}, "properties": props}


# Two neighbouring ~3 km cells (lon/lat), the point 51.4300/7.0050 lies in the southern one.
SOUTH = [[6.99, 51.41], [7.03, 51.41], [7.03, 51.435], [6.99, 51.435], [6.99, 51.41]]
NORTH = [[6.99, 51.435], [7.03, 51.435], [7.03, 51.46], [6.99, 51.46], [6.99, 51.435]]
BODEN = [cell(NORTH, descript="AC137", geo_unit="Kreide", rn_max=6.3), cell(SOUTH, descript="AC138", geo_unit="Karbon", rn_max=57)]
POT = [cell([[6.9, 51.35], [7.1, 51.35], [7.1, 51.5], [6.9, 51.5], [6.9, 51.35]], gid=1762, grp_pb_=36.5)]


def stub(monkeypatch, by_type):
    calls = []

    def fake(typename, lat, lon):
        calls.append(typename)
        v = by_type.get(typename, [])
        if isinstance(v, Exception):
            raise v
        return v
    monkeypatch.setattr(radon, "_wfs_features", fake)
    return calls


def test_classes():
    assert radon.classify_bodenluft(6.3) == ("gering", "green")
    assert radon.classify_bodenluft(25) == ("mittel", "yellow")
    assert radon.classify_bodenluft(57) == ("erhöht", "orange")
    assert radon.classify_bodenluft(120) == ("hoch", "red")
    assert radon.classify_potenzial(5) == ("gering", "green")
    assert radon.classify_potenzial(20) == ("mittel", "yellow")
    assert radon.classify_potenzial(36.5) == ("hoch", "orange")


def test_point_in_cell_and_rating(monkeypatch):
    calls = stub(monkeypatch, {radon.TYPE_BODEN: BODEN, radon.TYPE_POTENZIAL: POT})
    d = radon.get_radon(51.4300, 7.0050)
    assert calls == [radon.TYPE_BODEN, radon.TYPE_POTENZIAL]
    assert d["bodenluft"] == {"kbq_m3": 57.0, "klasse": "erhöht", "klasse_color": "orange", "geologie": "Karbon", "zelle": "AC138"}
    assert d["potenzial"] == {"wert": 36.5, "klasse": "hoch", "klasse_color": "orange"}
    assert d["rating"] == "Erhöhtes Radonpotenzial" and d["rating_color"] == "orange"


def test_low_values_are_green(monkeypatch):
    stub(monkeypatch, {radon.TYPE_BODEN: BODEN, radon.TYPE_POTENZIAL: [cell(POT[0]["geometry"]["coordinates"][0], grp_pb_=8)]})
    d = radon.get_radon(51.45, 7.0050)          # northern cell, Kreide 6.3
    assert d["bodenluft"]["klasse"] == "gering" and d["rating"] == "Geringes Radonpotenzial" and d["rating_color"] == "green"


def test_partial_and_empty(monkeypatch):
    stub(monkeypatch, {radon.TYPE_BODEN: RuntimeError("down"), radon.TYPE_POTENZIAL: POT})
    d = radon.get_radon(51.4300, 7.0050)
    assert d["bodenluft"] is None and d["potenzial"]["klasse"] == "hoch" and d["errors"] == {"bodenluft": "down"}
    stub(monkeypatch, {})
    assert radon.get_radon(51.4300, 7.0050) is None


def test_total_failure_raises(monkeypatch):
    stub(monkeypatch, {radon.TYPE_BODEN: RuntimeError("a"), radon.TYPE_POTENZIAL: RuntimeError("b")})
    with pytest.raises(RuntimeError):
        radon.get_radon(51.43, 7.0)
