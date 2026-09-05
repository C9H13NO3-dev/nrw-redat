"""redat/sources/alkis.py — ALKIS vereinfacht WFS, hermetic (GML fixtures, _wfs_gml stubbed)."""
import pytest

from redat.sources import alkis

# Test point 51.4300 N, 7.0050 E (Essen-Rüttenscheid) → UTM32 ≈ (361315.8, 5699532.4). Rings are built
# around that projected centre so the fixture never depends on hand-typed coordinates.
CX, CY = alkis._TO_25832.transform(7.0050, 51.4300)


def ring(x0, y0, x1, y1) -> str:
    return f"{x0} {y0} {x1} {y0} {x1} {y1} {x0} {y1} {x0} {y0}"


PARCEL_RING = ring(CX - 10, CY - 10, CX + 10, CY + 10)               # 20 m × 20 m = 400 m²
HOUSE_RING = ring(CX - 8, CY - 8, CX + 2, CY + 2)                    # 100 m², fully inside
NEIGHBOUR_RING = ring(CX + 9, CY - 8, CX + 19, CY + 2)               # 100 m², only 10 m² (10 %) inside


def gml(members: str) -> str:
    return ('<?xml version="1.0" encoding="utf-8"?>'
            '<wfs:FeatureCollection xmlns="http://repository.gdi-de.org/schemas/adv/produkt/alkis-vereinfacht/2.0" '
            'xmlns:gml="http://www.opengis.net/gml/3.2" xmlns:wfs="http://www.opengis.net/wfs/2.0" numberReturned="1">'
            f"{members}</wfs:FeatureCollection>")


def polygon(ring: str, holes: tuple[str, ...] = ()) -> str:
    interior = "".join(f"<gml:interior><gml:LinearRing><gml:posList>{h}</gml:posList></gml:LinearRing></gml:interior>" for h in holes)
    return ('<geometrie><gml:MultiSurface srsName="urn:ogc:def:crs:EPSG::25832" srsDimension="2"><gml:surfaceMember>'
            f"<gml:Polygon><gml:exterior><gml:LinearRing><gml:posList>{ring}</gml:posList></gml:LinearRing></gml:exterior>{interior}"
            "</gml:Polygon></gml:surfaceMember></gml:MultiSurface></geometrie>")


FLURSTUECK = gml(
    '<wfs:member><Flurstueck gml:id="DENW22AL800005HeFL">'
    "<idflurst>DENW22AL800005He</idflurst><flstkennz>05314403900040______</flstkennz>"
    "<gemarkung>Rüttenscheid</gemarkung><gemaschl>053144</gemaschl><flur>39</flur><flstnrzae>40</flstnrzae>"
    "<gemeinde>Essen</gemeinde><gmdschl>05113000</gmdschl><aktualit>2026-02-17Z</aktualit>"
    f"{polygon(PARCEL_RING)}<flaeche>400.0</flaeche><lagebeztxt>Herthastr. 4</lagebeztxt>"
    "<tntxt>Wohnbaufläche;380|Straßenverkehr;20</tntxt></Flurstueck></wfs:member>")

GEBAEUDE = gml(
    '<wfs:member><GebaeudeBauwerk gml:id="a"><oid>a</oid><funktion>Wohngebäude</funktion><lagebeztxt>Herthastr. 4</lagebeztxt>'
    f"{polygon(HOUSE_RING)}</GebaeudeBauwerk></wfs:member>"
    '<wfs:member><GebaeudeBauwerk gml:id="b"><oid>b</oid><funktion>Garage</funktion>'
    f"{polygon(NEIGHBOUR_RING)}</GebaeudeBauwerk></wfs:member>")

NUTZUNG = gml(f'<wfs:member><Nutzung gml:id="n"><nutzart>Wohnbaufläche</nutzart>{polygon(PARCEL_RING)}</Nutzung></wfs:member>')
EMPTY = gml("")


def stub(monkeypatch, by_type: dict):
    calls = []

    def fake(typename, bbox, count=50):
        calls.append((typename, bbox))
        return by_type.get(typename, EMPTY)
    monkeypatch.setattr(alkis, "_wfs_gml", fake)
    return calls


def test_parse_members_reads_props_and_polygon_with_hole():
    hole = ring(CX - 5, CY - 5, CX - 3, CY - 3)                        # 4 m² hole inside the parcel
    text = gml(f'<wfs:member><Flurstueck gml:id="x"><flur>1</flur>{polygon(PARCEL_RING, (hole,))}<flaeche>396</flaeche></Flurstueck></wfs:member>')
    m = alkis.parse_members(text)
    assert len(m) == 1 and m[0]["props"] == {"flur": "1", "flaeche": "396"}
    assert abs(m[0]["geom"].area - 396) < 0.01     # 400 minus the 4 m² hole


def test_parse_tntxt():
    assert alkis.parse_tntxt("Wohnbaufläche;380|Straßenverkehr;20") == [{"art": "Wohnbaufläche", "m2": 380}, {"art": "Straßenverkehr", "m2": 20}]
    assert alkis.parse_tntxt("Wohnbaufläche;538") == [{"art": "Wohnbaufläche", "m2": 538}]
    assert alkis.parse_tntxt(None) == [] and alkis.parse_tntxt("Wald;") == [{"art": "Wald", "m2": None}]


def test_parcel_buildings_and_nutzung(monkeypatch):
    calls = stub(monkeypatch, {"ave:Flurstueck": FLURSTUECK, "ave:GebaeudeBauwerk": GEBAEUDE, "ave:Nutzung": NUTZUNG})
    d = alkis.get_flurstueck(51.4300, 7.0050)
    f = d["flurstueck"]
    assert f["kennzeichen"] == "05314403900040" and f["gemarkung"] == "Rüttenscheid" and f["flur"] == 39 and f["nummer"] == "40"
    assert f["flaeche_m2"] == 400.0 and f["lage"] == "Herthastr. 4" and f["stand"] == "2026-02-17" and f["distance_m"] == 0.0
    assert f["nutzung"] == [{"art": "Wohnbaufläche", "m2": 380}, {"art": "Straßenverkehr", "m2": 20}]
    assert [b["funktion"] for b in d["gebaeude"]] == ["Wohngebäude", "Garage"]
    assert d["gebaeude"][0]["on_parcel"] is True and d["gebaeude"][0]["grundflaeche_m2"] == 100.0
    assert d["gebaeude"][1]["on_parcel"] is False                       # only 10 % of its footprint is inside
    assert d["grundflaeche_m2"] == 100.0 and d["ueberbauung_pct"] == 25.0
    assert d["nutzung_am_punkt"] == "Wohnbaufläche"
    types = [t for t, _ in calls]
    assert types[0] == "ave:Flurstueck"                                # the parcel first, it defines the other bboxes
    assert sorted(types[1:]) == ["ave:GebaeudeBauwerk", "ave:Nutzung"]  # then both concurrently, in any order
    bboxes = dict(calls)
    assert bboxes["ave:Flurstueck"] == (CX - 5, CY - 5, CX + 5, CY + 5)          # ±5 m, as wide as the snap tolerance
    assert bboxes["ave:Nutzung"] == (CX - 5, CY - 5, CX + 5, CY + 5)
    assert bboxes["ave:GebaeudeBauwerk"] == (CX - 10, CY - 10, CX + 10, CY + 10)  # buildings use the parcel bounds


def test_point_just_outside_snaps_to_parcel_within_5m(monkeypatch):
    stub(monkeypatch, {"ave:Flurstueck": FLURSTUECK})
    d = alkis.get_flurstueck(51.4300 - 0.00011, 7.0050)   # ≈ 12.2 m south of the centre → ≈ 2.2 m outside the 20 m square
    assert d is not None and 0 < d["flurstueck"]["distance_m"] <= 5


def test_point_too_far_from_parcel_is_none(monkeypatch):
    stub(monkeypatch, {"ave:Flurstueck": FLURSTUECK})
    assert alkis.get_flurstueck(51.4300 - 0.00014, 7.0050) is None      # ≈ 5.6 m outside > _SNAP_M


def test_no_parcel_returns_none(monkeypatch):
    stub(monkeypatch, {})
    assert alkis.get_flurstueck(51.0, 7.0) is None


def test_flaeche_falls_back_to_geometry_and_nutzung_empty(monkeypatch):
    text = gml(f'<wfs:member><Flurstueck gml:id="x"><flstkennz>05314403900040______</flstkennz>{polygon(PARCEL_RING)}</Flurstueck></wfs:member>')
    stub(monkeypatch, {"ave:Flurstueck": text})
    d = alkis.get_flurstueck(51.4300, 7.0050)
    assert d["flurstueck"]["flaeche_m2"] == 400.0 and d["flurstueck"]["nutzung"] == [] and d["gebaeude"] == []
    assert d["grundflaeche_m2"] == 0.0 and d["ueberbauung_pct"] == 0.0 and d["nutzung_am_punkt"] is None


def test_wfs_failure_propagates(monkeypatch):
    def boom(typename, bbox, count=50):
        raise RuntimeError("502")
    monkeypatch.setattr(alkis, "_wfs_gml", boom)
    with pytest.raises(RuntimeError):
        alkis.get_flurstueck(51.43, 7.0)
