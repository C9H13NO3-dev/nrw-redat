"""redat/sources/denkmal_nrw.py — statewide INSPIRE Denkmal WFS, hermetic (`_wfs_gml` stubbed with real-shaped GML)."""
import pytest

from redat.sources import denkmal as dk
from redat.sources import denkmal_nrw as nrw

LAT, LON = 50.7350, 7.1000                    # Bonn Zentrum
X, Y = dk._TO_25832.transform(LON, LAT)

_HEAD = ('<?xml version="1.0" encoding="utf-8" ?><wfs:FeatureCollection xmlns:wfs="http://www.opengis.net/wfs/2.0" '
         'xmlns:gml="http://www.opengis.net/gml/3.2" xmlns:ps="http://inspire.ec.europa.eu/schemas/ps/4.0" numberMatched="1" numberReturned="1">')


def point_gml(nummer="DE_05314000_A_00749", name="Fassade eines Wohngebäudes", x=X + 10, y=Y + 5, date="1985-01-23"):
    return (f'<wfs:member><ps:ProtectedSites_Cultural_Point gml:id="p.1"><ps:OBJECTID>1</ps:OBJECTID>'
            f'<ps:SHAPE><gml:Point gml:id="p.1.g" srsName="urn:ogc:def:crs:EPSG::25832"><gml:pos>{x:.4f} {y:.4f}</gml:pos></gml:Point></ps:SHAPE>'
            f'<ps:nummer>{nummer}</ps:nummer><ps:sitename>{name}</ps:sitename><ps:designation>Baudenkmal</ps:designation>'
            f'<ps:legalfoundationdate>{date}</ps:legalfoundationdate><ps:protclass>cultural</ps:protclass></ps:ProtectedSites_Cultural_Point></wfs:member>')


def surface_gml(nummer="DE_05314000_D_00012", name="Denkmalbereich Südstadt", half=40.0, cx=X, cy=Y, typename="Cultural_Surface"):
    ring = f"{cx - half:.2f} {cy - half:.2f} {cx + half:.2f} {cy - half:.2f} {cx + half:.2f} {cy + half:.2f} {cx - half:.2f} {cy + half:.2f} {cx - half:.2f} {cy - half:.2f}"
    return (f'<wfs:member><ps:ProtectedSites_{typename} gml:id="s.1"><ps:SHAPE><gml:MultiSurface gml:id="s.1.g" srsName="urn:ogc:def:crs:EPSG::25832">'
            f'<gml:surfaceMember><gml:Polygon gml:id="s.1.g.0"><gml:exterior><gml:LinearRing><gml:posList>{ring}</gml:posList></gml:LinearRing></gml:exterior></gml:Polygon>'
            f'</gml:surfaceMember></gml:MultiSurface></ps:SHAPE><ps:nummer>{nummer}</ps:nummer><ps:sitename>{name}</ps:sitename>'
            f'<ps:designation>Denkmalbereich</ps:designation><ps:legalfoundationdate>2001-07-01</ps:legalfoundationdate></ps:ProtectedSites_{typename}></wfs:member>')


def collection(*members):
    return _HEAD + "".join(members) + "</wfs:FeatureCollection>"


def stub(monkeypatch, by_type: dict):
    calls = []

    def wfs(typename, bbox, count=500):
        calls.append((typename, bbox))
        v = by_type.get(typename, collection())
        if isinstance(v, Exception):
            raise v
        return v
    monkeypatch.setattr(nrw, "_wfs_gml", wfs)
    return calls


def test_parse_members_reads_point_and_surface():
    feats = nrw.parse_members(collection(point_gml(), surface_gml()))
    assert [f["id"] for f in feats] == ["DE_05314000_A_00749", "DE_05314000_D_00012"]
    assert feats[0]["geom"].geom_type == "Point" and feats[1]["geom"].geom_type in ("Polygon", "MultiPolygon")
    assert feats[0]["name"] == "Fassade eines Wohngebäudes" and feats[0]["date"] == "1985-01-23"
    assert feats[1]["geom"].contains(feats[0]["geom"])


def test_parse_members_skips_geometry_less_member():
    broken = '<wfs:member><ps:ProtectedSites_Cultural_Point gml:id="x"><ps:nummer>DE_1_A_1</ps:nummer></ps:ProtectedSites_Cultural_Point></wfs:member>'
    assert nrw.parse_members(collection(broken)) == []


def test_all_eight_typenames_queried_with_25832_bbox(monkeypatch):
    calls = stub(monkeypatch, {})
    d = nrw.get_denkmal_nrw(LAT, LON)
    assert {t for t, _ in calls} == set(nrw.CULTURAL) | set(nrw.ARCHAEO)
    xmin, ymin, xmax, ymax = calls[0][1]
    assert 590 < xmax - xmin < 610 and 590 < ymax - ymin < 610
    assert d["rating"] == "Kein Denkmalschutz" and d["items"] == [] and d["source"] == "nrw" and "freiwillig" in d["hinweis"]
    assert d["authority"] is None and d["counts"] == {"A": 0, "B": 0, "C": 0, "D": 0}


def test_point_within_25m_is_on_site_baudenkmal(monkeypatch):
    stub(monkeypatch, {"ps:ProtectedSites_Cultural_Point": collection(point_gml())})
    d = nrw.get_denkmal_nrw(LAT, LON)
    it = d["items"][0]
    assert it["on_site"] and it["kind"] == "A" and it["kind_label"] == "Baudenkmal" and it["scope"] == "objekt"
    assert it["listed_since"] == "1985-01-23" and it["link"] is None and it["city"] is None
    assert d["rating"] == "Baudenkmal" and d["rating_color"] == "orange"


def test_surface_containing_point_is_denkmalbereich_yellow(monkeypatch):
    stub(monkeypatch, {"ps:ProtectedSites_Cultural_Surface": collection(surface_gml())})
    d = nrw.get_denkmal_nrw(LAT, LON)
    assert d["items"][0]["scope"] == "gebiet" and d["items"][0]["on_site"] and d["rating"] == "Im Denkmalbereich"


def test_archaeological_surface_is_bodendenkmal(monkeypatch):
    stub(monkeypatch, {"ps:ProtectedSites_Archaeological_Surface": collection(surface_gml(nummer="DE_05314000_B_00003", name="Römerlager", typename="Archaeological_Surface"))})
    d = nrw.get_denkmal_nrw(LAT, LON)
    assert d["items"][0]["kind"] == "B" and d["rating"] == "Bodendenkmal"


def test_far_feature_is_dropped_and_dedupe_prefers_surface(monkeypatch):
    stub(monkeypatch, {
        "ps:ProtectedSites_Cultural_Point": collection(point_gml(nummer="DE_05314000_A_1", x=X + 900, y=Y), point_gml(nummer="DE_05314000_A_2", x=X + 100, y=Y)),
        "ps:ProtectedSites_Cultural_Surface": collection(surface_gml(nummer="DE_05314000_A_2", cx=X + 100, cy=Y, half=10)),
    })
    d = nrw.get_denkmal_nrw(LAT, LON)
    assert [i["id"] for i in d["items"]] == ["DE_05314000_A_2"]
    assert d["items"][0]["distance_m"] == pytest.approx(90, abs=1) and d["rating"] == "Denkmäler in der Nähe"


def test_wfs_failure_raises(monkeypatch):
    stub(monkeypatch, {"ps:ProtectedSites_Cultural_Point": RuntimeError("503")})
    with pytest.raises(RuntimeError):
        nrw.get_denkmal_nrw(LAT, LON)
