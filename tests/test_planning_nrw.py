"""redat/sources/planning_nrw.py — Bauleitpläne NRW via OGC API Features, hermetic (`_items` stubbed)."""
import pytest

from redat.sources import planning_nrw as pn

LAT, LON = 50.7160, 7.0748   # Bonn, Am Käferberg


def feature(title, plan_type="Bebauungsplan", step="rechtsverbindlich oder in Kraft (In Kraft getreten)", valid="1999-06-25",
            doc="https://example.org/plan.pdf", text=None, kommune="Bonn", ring=None):
    ring = ring or [[LON - 0.001, LAT - 0.001], [LON + 0.001, LAT - 0.001], [LON + 0.001, LAT + 0.001], [LON - 0.001, LAT + 0.001], [LON - 0.001, LAT - 0.001]]
    return {"type": "Feature", "geometry": {"type": "MultiPolygon", "coordinates": [[ring]]},
            "properties": {"officialTitle": title, "planTypeName.title": plan_type, "processStepGeneral.title": step,
                           "validFrom": valid, "officialDocument": doc, "texturl": text, "kommune": kommune, "gkz": "05314000"}}


def test_items_bbox_and_headers(monkeypatch):
    seen = {}

    def get(url, params=None, headers=None, timeout=None, follow_redirects=None):
        seen.update(url=url, params=params, headers=headers, follow=follow_redirects)

        class R:
            def raise_for_status(self): pass
            def json(self): return {"features": [feature("x")]}
        return R()
    monkeypatch.setattr(pn.httpx, "get", get)
    assert len(pn._items((7.07, 50.71, 7.08, 50.72))) == 1
    assert seen["url"] == pn.API_URL and seen["params"]["f"] == "json" and seen["params"]["bbox"] == "7.070000,50.710000,7.080000,50.720000"
    assert seen["headers"]["Accept"] == "application/json" and "User-Agent" in seen["headers"] and seen["follow"] is True


def test_only_plans_containing_the_point_are_listed(monkeypatch):
    far = [[LON + 0.01, LAT], [LON + 0.02, LAT], [LON + 0.02, LAT + 0.01], [LON + 0.01, LAT + 0.01], [LON + 0.01, LAT]]
    monkeypatch.setattr(pn, "_items", lambda bbox: [feature("Hier"), feature("Dort", ring=far)])
    p = pn.get_planning_nrw(LAT, LON)
    assert p["ok"] and p["found"] and [i["name"] for i in p["items"]] == ["Hier (in Kraft, ab 25.06.1999)"]
    assert p["items"][0]["category"] == "Bebauungsplan" and p["items"][0]["link"] == "https://example.org/plan.pdf" and p["kommune"] == "Bonn"


def test_ordering_bplan_first_then_newest_and_unknown_date_omitted(monkeypatch):
    monkeypatch.setattr(pn, "_items", lambda bbox: [
        feature("FNP Bonn", plan_type="Flächennutzungsplan", valid="1900-01-01", doc="https://stadtplan.bonn.de/x"),
        feature("B 12/85", valid="1985-08-02"), feature("B 3/20", valid="2020-01-15", step="im Verfahren (Aufstellungsbeschluss)"),
    ])
    p = pn.get_planning_nrw(LAT, LON)
    assert [i["name"] for i in p["items"]] == ["B 3/20 (im Verfahren, ab 15.01.2020)", "B 12/85 (in Kraft, ab 02.08.1985)", "FNP Bonn (in Kraft)"]


def test_link_falls_back_to_texturl_and_requires_http(monkeypatch):
    monkeypatch.setattr(pn, "_items", lambda bbox: [feature("A", doc="", text="https://example.org/text.pdf"), feature("B", doc="n/a", text=None),
                                                     feature("C", valid=1999)])
    items = pn.get_planning_nrw(LAT, LON)["items"]
    assert items[0]["link"] == "https://example.org/text.pdf" and items[1]["link"] is None
    assert [i["name"] for i in items if i["name"].startswith("C")] == ["C (in Kraft)"]  # non-string validFrom: no crash, no "ab" part


def test_null_or_unrecognized_geometry_is_skipped_not_fatal(monkeypatch):
    null_geom = feature("Null-Geometrie")
    null_geom["geometry"] = None
    bad_type = feature("Unbekannter Geometrietyp")
    bad_type["geometry"] = {"type": "Blob", "coordinates": []}
    monkeypatch.setattr(pn, "_items", lambda bbox: [null_geom, bad_type, None, "not-a-feature", feature("Gültig")])
    p = pn.get_planning_nrw(LAT, LON)
    assert p["ok"] and [i["name"] for i in p["items"]] == ["Gültig (in Kraft, ab 25.06.1999)"]


def test_non_string_link_field_does_not_crash(monkeypatch):
    """Important 2: _http() must not raise AttributeError on a dict/int field value."""
    monkeypatch.setattr(pn, "_items", lambda bbox: [feature("D", doc={"href": "x"}, text=123)])
    p = pn.get_planning_nrw(LAT, LON)
    assert p["ok"] and p["items"][0]["link"] is None


def test_no_features_is_not_found(monkeypatch):
    monkeypatch.setattr(pn, "_items", lambda bbox: [])
    p = pn.get_planning_nrw(LAT, LON)
    assert p == {"ok": True, "found": False, "items": [], "kommune": None}


def test_http_failure_is_not_ok(monkeypatch):
    def boom(bbox):
        raise RuntimeError("502")
    monkeypatch.setattr(pn, "_items", boom)
    assert pn.get_planning_nrw(LAT, LON) == {"ok": False, "error": "502"}
