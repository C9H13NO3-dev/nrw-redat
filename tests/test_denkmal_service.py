"""backend/denkmal_service.py — RVR Denkmal WFS, hermetic (`_wfs_features` stubbed)."""
import pytest

from redat.sources import denkmal as dk

POLY = "ms:denkmal_polygon"
POINT = "ms:denkmal_point_unclustered"

# Werden, Essen — a small square around the test point (51.3885, 7.0035), WGS84 lon/lat.
HOME_RING = [[7.0030, 51.3882], [7.0040, 51.3882], [7.0040, 51.3888], [7.0030, 51.3888], [7.0030, 51.3882]]
# ~150 m further north — not containing the point.
NEAR_RING = [[7.0030, 51.3896], [7.0040, 51.3896], [7.0040, 51.3900], [7.0030, 51.3900], [7.0030, 51.3896]]
# ~1 km away — outside the 300 m radius even though the WFS bbox may still return it.
FAR_RING = [[7.0030, 51.3975], [7.0040, 51.3975], [7.0040, 51.3980], [7.0030, 51.3980], [7.0030, 51.3975]]


def poly(inspire_id, ring, **props):
    base = {"bezeichnun": "Haus Fuhr", "inspire_id": inspire_id, "gemeinde": "Essen", "kategorie": "1000",
            "datum": "1985-06-18T00:00:00", "gesetz": "DSchG NRW",
            "merkmale": "https://geo.essen.de/webdaten/sta61/Denkmaeler/Foto_Htm_und_pdf/D123.htm", "denkmal_ei": ""}
    base.update(props)
    return {"type": "Feature", "properties": base, "geometry": {"type": "Polygon", "coordinates": [ring]}}


def point(inspire_id, lon, lat, **props):
    base = {"bezeichnun": "Hauptbahnhof", "inspire_id": inspire_id, "gemeinde": "Bochum", "kategorie": "1000",
            "datum": "1995-01-01T00:00:00",
            "merkmale": "https://geoinfo.bochum.de/61/Webdaten/Denkmalliste/Foto/A393.jpg",
            "denkmal_ei": "https://geoinfo.bochum.de/61/Webdaten/Denkmalliste/Begruendung/A393.pdf"}
    base.update(props)
    return {"type": "Feature", "properties": base, "geometry": {"type": "Point", "coordinates": [lon, lat]}}


def stub(monkeypatch, by_type: dict):
    calls = []

    def wfs(typename, bbox):
        calls.append((typename, bbox))
        v = by_type.get(typename, [])
        if isinstance(v, Exception):
            raise v
        return v
    monkeypatch.setattr(dk, "_wfs_features", wfs)
    return calls


def test_outside_rvr_returns_none_without_http(monkeypatch):
    calls = stub(monkeypatch, {})
    assert dk.get_denkmal(52.52, 13.40) is None
    assert calls == []


def test_no_features_is_green_kein_denkmalschutz(monkeypatch):
    calls = stub(monkeypatch, {})
    d = dk.get_denkmal(51.3885, 7.0035)
    assert d["rating"] == "Kein Denkmalschutz" and d["rating_color"] == "green"
    assert d["items"] == [] and d["on_site"] == [] and d["authority"] is None
    assert d["counts"] == {"A": 0, "B": 0, "C": 0, "D": 0}
    assert {t for t, _ in calls} == {POLY, POINT}
    xmin, ymin, xmax, ymax = calls[0][1]
    assert 590 < xmax - xmin < 610 and 590 < ymax - ymin < 610  # ±300 m in EPSG:25832


def test_polygon_containing_point_is_on_site_baudenkmal(monkeypatch):
    stub(monkeypatch, {POLY: [poly("DE_05113000_A_123", HOME_RING)]})
    d = dk.get_denkmal(51.3885, 7.0035)
    assert d["rating"] == "Baudenkmal" and d["rating_color"] == "orange"
    it = d["items"][0]
    assert it["on_site"] is True and it["distance_m"] == 0.0
    assert it["kind"] == "A" and it["kind_label"] == "Baudenkmal" and it["scope"] == "objekt"
    assert it["id"] == "DE_05113000_A_123" and it["city"] == "Essen" and it["listed_since"] == "1985-06-18"
    assert it["link"].endswith("D123.htm")  # Essen: denkmal_ei empty → merkmale htm
    assert d["on_site"] == [it]
    assert d["authority"]["name"] == "Untere Denkmalbehörde Essen"


def test_kind_and_scope_from_inspire_id_and_kategorie(monkeypatch):
    stub(monkeypatch, {POLY: [
        poly("DE_05113000_B_7", HOME_RING, kategorie="4000"),
        poly("DE_05911000_D_2", NEAR_RING, kategorie="2000", gemeinde="Bochum"),
        poly("DE_05911000_A_9", FAR_RING, kategorie="2000"),          # Siedlung: A but kategorie 2000 → gebiet
    ]})
    d = dk.get_denkmal(51.3885, 7.0035)
    by_id = {i["id"]: i for i in d["items"]}
    assert by_id["DE_05113000_B_7"]["kind_label"] == "Bodendenkmal" and by_id["DE_05113000_B_7"]["scope"] == "objekt"
    assert by_id["DE_05911000_D_2"]["kind_label"] == "Denkmalbereich" and by_id["DE_05911000_D_2"]["scope"] == "gebiet"
    assert "DE_05911000_A_9" not in by_id  # > 300 m
    assert d["rating"] == "Bodendenkmal"


def test_kind_falls_back_to_kategorie_when_id_unparseable(monkeypatch):
    stub(monkeypatch, {POLY: [poly("weird", NEAR_RING, kategorie="4000")]})
    d = dk.get_denkmal(51.3885, 7.0035)
    assert d["items"][0]["kind"] == "B"


def test_bochum_point_within_25m_is_on_site_and_prefers_pdf_link(monkeypatch):
    stub(monkeypatch, {POINT: [point("DE_05911000_A_393_376593_5704811", 7.22335, 51.47865)]})
    d = dk.get_denkmal(51.4786, 7.2233)
    it = d["items"][0]
    assert it["on_site"] is True and it["distance_m"] < 25
    assert it["id"] == "DE_05911000_A_393"  # coordinate suffix stripped
    assert it["link"].endswith("A393.pdf")
    assert d["authority"]["name"] == "Untere Denkmalbehörde Bochum"
    assert d["rating"] == "Baudenkmal"


def test_point_beyond_25m_is_neighbour_not_on_site(monkeypatch):
    stub(monkeypatch, {POINT: [point("DE_05911000_A_1", 7.2233, 51.4790)]})  # ~45 m north
    d = dk.get_denkmal(51.4786, 7.2233)
    it = d["items"][0]
    assert it["on_site"] is False and 40 < it["distance_m"] < 50
    assert d["rating"] == "Denkmal in unmittelbarer Nachbarschaft" and d["rating_color"] == "yellow"


def test_dedupe_prefers_polygon_over_point(monkeypatch):
    stub(monkeypatch, {
        POLY: [poly("DE_05911000_A_5", HOME_RING, gemeinde="Bochum")],
        POINT: [point("DE_05911000_A_5_1_2", 7.0035, 51.3885)],
    })
    d = dk.get_denkmal(51.3885, 7.0035)
    assert len(d["items"]) == 1 and d["counts"]["A"] == 1
    assert d["items"][0]["link"].endswith("D123.htm")  # the polygon's props won


def test_denkmalbereich_containing_point_is_yellow(monkeypatch):
    stub(monkeypatch, {POLY: [poly("DE_05911000_D_2", HOME_RING, kategorie="2000", bezeichnun="Stadtparkviertel")]})
    d = dk.get_denkmal(51.3885, 7.0035)
    assert d["rating"] == "Im Denkmalbereich" and d["rating_color"] == "yellow"
    assert d["on_site"][0]["scope"] == "gebiet"


def test_nearby_only_is_green_denkmaeler_in_der_naehe(monkeypatch):
    stub(monkeypatch, {POLY: [poly("DE_05113000_A_1", NEAR_RING)]})
    d = dk.get_denkmal(51.3885, 7.0035)
    assert 100 < d["items"][0]["distance_m"] < 200
    assert d["rating"] == "Denkmäler in der Nähe" and d["rating_color"] == "green"


def test_ordering_cap_and_counts(monkeypatch):
    feats = [poly("DE_05113000_A_0", HOME_RING)]
    for i in range(1, 20):
        lat = 51.3885 + 0.00012 * i  # ~13 m steps north
        feats.append(point(f"DE_05113000_A_{i}", 7.0035, lat, gemeinde="Essen"))
    stub(monkeypatch, {POLY: feats[:1], POINT: feats[1:]})
    d = dk.get_denkmal(51.3885, 7.0035)
    assert len(d["items"]) == dk._MAX_ITEMS
    assert d["items"][0]["on_site"] is True
    dists = [i["distance_m"] for i in d["items"] if not i["on_site"]]
    assert dists == sorted(dists)
    assert d["counts"]["A"] == 20  # counts are pre-cap


def test_wfs_failure_raises(monkeypatch):
    stub(monkeypatch, {POLY: RuntimeError("boom")})
    with pytest.raises(RuntimeError):
        dk.get_denkmal(51.3885, 7.0035)


def test_link_requires_http(monkeypatch):
    stub(monkeypatch, {POLY: [poly("DE_05113000_A_1", HOME_RING, merkmale="siehe Liste", denkmal_ei="")]})
    assert dk.get_denkmal(51.3885, 7.0035)["items"][0]["link"] is None


def test_wfs_retries_once_on_transient_error(monkeypatch):
    """The RVR server sometimes 400s a first request and serves the identical one fine."""
    seen = []

    class Resp:
        def __init__(self, status):
            self.status_code = status

        def json(self):
            return {"features": [{"id": "x"}]}

        def raise_for_status(self):
            raise RuntimeError(f"HTTP {self.status_code}")

    def get(url, params=None, timeout=None, headers=None):
        seen.append(params["TYPENAMES"])
        return Resp(400 if len(seen) == 1 else 200)
    monkeypatch.setattr(dk.httpx, "get", get)
    monkeypatch.setattr(dk.time, "sleep", lambda s: None)
    assert dk._wfs_features("ms:denkmal_polygon", (0, 0, 1, 1)) == [{"id": "x"}]
    assert seen == ["ms:denkmal_polygon"] * 2


def test_wfs_persistent_error_raises(monkeypatch):
    class Resp:
        status_code = 500

        def raise_for_status(self):
            raise RuntimeError("HTTP 500")
    monkeypatch.setattr(dk.httpx, "get", lambda *a, **k: Resp())
    monkeypatch.setattr(dk.time, "sleep", lambda s: None)
    with pytest.raises(RuntimeError, match="500"):
        dk._wfs_features("ms:denkmal_polygon", (0, 0, 1, 1))
