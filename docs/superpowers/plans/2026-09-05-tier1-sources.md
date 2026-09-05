# Tier-1 Sources Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add six new analysis cards (Flurstück/ALKIS, Immobilienrichtwerte, Baugrund BK50, Radon, Schulen, Unfälle) and extend three existing cards (Flood + Überschwemmungsgebiete, Bauleitplanung Essen + Satzungen/Sanierung, Bauleitplanung Bochum + Stadterneuerung) from open NRW/Bund geodata.

**Architecture:** Each card is one module in `redat/sources/` with a single HTTP function as monkeypatch point, one `_fetch_*` normaliser and `Section` entry in `redat/core/sections.py`, one web partial (Alpine) and one report partial (Jinja), a summary function in `redat/report/builder.py`, a `SourceMeta` row and a tier entry. Live cards call WFS/WMS/ArcGIS endpoints per request and rely on the 30-day section cache; two cards (Schulen, Unfälle) read small gzipped JSON grids that a `scripts/build_*.py` produces once from open downloads and that are committed under `redat/data/`.

**Tech Stack:** Python 3.12, httpx, shapely 2, pyproj, geopandas (build scripts only), FastAPI + Jinja2, Alpine.js partials, pytest (hermetic, every HTTP point stubbed).

**Spec:** `docs/superpowers/specs/2026-09-05-tier1-sources-design.md` — read it first; every endpoint, field and sample value in this plan comes from it.

## Global Constraints

- Every outbound call passes `headers=headers()` from `redat/http.py`; never a bare `httpx.get(...)`; never `verify=False`.
- All UI copy (web partials, report partials, messages) is German.
- Web partials keep the Alpine store name `app` (`$store.app.…`).
- `data_dir()` stays a function; new static data lives in `redat/data/` (committed, like `zensus_2022_grid.json.gz`).
- Cache contract: bump `Section.cache_version` when a card's `data` shape or meaning changes (`flood`, `planning_essen`, `planning_bochum` → 2). New cards start at 1 and use the default TTL.
- Envelope contract unchanged: a fetch returns the normalised dict, returns `None` / raises `Empty("…")` for "nothing here", raises for hard failures.
- Tests are hermetic: stub the module's HTTP function with `monkeypatch.setattr(module, "_name", fake)`; never hit the network in `pytest`.
- Run the suite with `.venv/bin/python -m pytest -q` (create the venv per CLAUDE.md if missing). Every task ends green.
- Commit per task with the trailer lines from the session (`Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>` and the `Claude-Session:` line shown in the session's attribution reminder).

---

## File Structure

| File | Responsibility |
|---|---|
| `redat/sources/esri_wms.py` (new, Task 4) | Shared esri-flavoured WMS GetFeatureInfo params + XML parser used by `uesg.py`, `irw.py` |
| `redat/sources/alkis.py` (new, Task 1) | ALKIS WFS: parcel, buildings, Nutzung; GML 3.2 parsing |
| `redat/sources/baulasten_essen.py` (new, Task 2) | Essen Baulasteninformation ArcGIS layers 0/1 |
| `redat/sources/uesg.py` (new, Task 4) | Überschwemmungsgebiete WMS GetFeatureInfo |
| `redat/sources/irw.py` (new, Task 5) | Immobilienrichtwerte WMS GetFeatureInfo |
| `redat/sources/planning_essen.py` (modify, Task 6) | + Sonstige Satzungen, Sanierung/Untersuchung |
| `redat/sources/planning_bochum.py` (modify, Task 7) | + Stadtplanung ArcGIS (ISEK, Stadtumbau) |
| `scripts/build_schulen.py` (new, Task 8) | Shape + Sozialindex CSV → `redat/data/schulen_nrw.json.gz` |
| `redat/sources/schulen.py` (new, Task 9) | Nearest schools per form + Bochum Grundschulbezirk |
| `scripts/build_unfallatlas.py` (new, Task 10) | Unfallatlas CSV zips → `redat/data/unfallatlas_2020_2025.json.gz` |
| `redat/sources/unfaelle.py` (new, Task 11) | Accidents within 300 m |
| `redat/sources/radon.py` (new, Task 12) | BfS radon WFS |
| `redat/sources/baugrund.py` (new, Task 13) | BK50 HTML GetFeatureInfo + Essen kf-Werte |
| `redat/core/sections.py`, `redat/core/tiers.py`, `redat/core/sources_meta.py` | Registry entries (every card task) |
| `redat/templates/analysis/_<key>.html`, `redat/templates/report/_<key>.html` | Card partials (every card task) |
| `redat/report/builder.py` | `SUMMARY[<key>]` (every card task) |
| `tests/fixtures/report_envelopes.json` | One `ok` envelope per new key (every card task) |
| `tests/test_<module>.py` | One test file per new module; registry tests updated per task |

---

### Task 1: ALKIS source module (`redat/sources/alkis.py`)

**Files:**
- Create: `redat/sources/alkis.py`
- Test: `tests/test_alkis.py`

**Interfaces:**
- Consumes: `redat.http.headers`
- Produces: `alkis.get_flurstueck(lat: float, lon: float) -> Optional[dict]` with keys `flurstueck`, `gebaeude`, `grundflaeche_m2`, `ueberbauung_pct`, `nutzung_am_punkt` (shape in spec §1, without `baulasten*`); `alkis._wfs_gml(typename, bbox25832, count=50) -> str` is the HTTP/monkeypatch point; `alkis.parse_members(gml_text) -> list[{"props": dict, "geom": shapely|None}]`; `alkis.parse_tntxt(text) -> list[{"art", "m2"}]`.

- [ ] **Step 1: Write the failing tests**

`tests/test_alkis.py`:

```python
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
    assert types == ["ave:Flurstueck", "ave:GebaeudeBauwerk", "ave:Nutzung"]
    assert calls[0][1] == (CX - 1, CY - 1, CX + 1, CY + 1)             # ±1 m bbox around the point
    assert calls[1][1] == (CX - 10, CY - 10, CX + 10, CY + 10)         # buildings are fetched with the parcel bounds


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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_alkis.py -q`
Expected: FAIL / ERROR with `ModuleNotFoundError: No module named 'redat.sources.alkis'`

- [ ] **Step 3: Implement the module**

`redat/sources/alkis.py`:

```python
"""Flurstück & Gebäude — ALKIS (vereinfacht) from the Geobasis NRW WFS.

Source: https://www.wfs.nrw.de/geobasis/wfs_nw_alkis_vereinfacht (WFS 2.0.0, dl-de/zero-2-0), feature
types `ave:Flurstueck`, `ave:GebaeudeBauwerk`, `ave:Nutzung`. The service sits behind an "OGC Proxy"
that rejects OUTPUTFORMAT=json, CQL_FILTER and SRSNAME (verified 2026-09-05) — the only request that
works is TYPENAMES + BBOX in EPSG:25832, answered as GML 3.2. Geometry is
<geometrie><gml:MultiSurface><gml:surfaceMember><gml:Polygon>… with posList "x y x y" in EPSG:25832.

Properties used — Flurstueck: idflurst, flstkennz ("05314403900040______", 14 significant chars),
gemarkung, gemaschl, flur, flstnrzae (+ flstnrnen), gemeinde, aktualit ("2026-02-17Z"), flaeche (m²),
lagebeztxt ("Herthastr. 4"), tntxt ("Wohnbaufläche;538" — `|`-separated entries of "Nutzung;m²").
GebaeudeBauwerk: funktion ("Wohngebäude"), lagebeztxt. Nutzung: nutzart.

Lookup: the parcel that contains the point, else the nearest within _SNAP_M (geocodes land on the
street edge). Buildings are fetched with the parcel bounds; one is "on the parcel" when more than
_ON_PARCEL_SHARE of its footprint lies inside. `_wfs_gml` is the single HTTP call and monkeypatch point.
"""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from typing import Optional

import httpx
from pyproj import Transformer
from shapely.geometry import MultiPolygon, Point, Polygon
from shapely.geometry.base import BaseGeometry

from redat.http import headers

logger = logging.getLogger(__name__)

ALKIS_WFS_URL = "https://www.wfs.nrw.de/geobasis/wfs_nw_alkis_vereinfacht"
_NS = {
    "ave": "http://repository.gdi-de.org/schemas/adv/produkt/alkis-vereinfacht/2.0",
    "gml": "http://www.opengis.net/gml/3.2",
    "wfs": "http://www.opengis.net/wfs/2.0",
}
_TO_25832 = Transformer.from_crs("EPSG:4326", "EPSG:25832", always_xy=True)
_TIMEOUT_S = 25
_POINT_BUFFER_M = 1.0    # half-width of the bbox around the geocoded point
_SNAP_M = 5.0            # accept a parcel this far from a street-edge geocode
_ON_PARCEL_SHARE = 0.5   # footprint share inside the parcel that makes a building "on" it


def _wfs_gml(typename: str, bbox: tuple[float, float, float, float], count: int = 50) -> str:
    """Raw GML 3.2 of one feature type inside the EPSG:25832 bbox — HTTP/monkeypatch point."""
    xmin, ymin, xmax, ymax = bbox
    params = {
        "SERVICE": "WFS", "VERSION": "2.0.0", "REQUEST": "GetFeature", "TYPENAMES": typename,
        "BBOX": f"{xmin},{ymin},{xmax},{ymax},urn:ogc:def:crs:EPSG::25832", "COUNT": count,
    }
    resp = httpx.get(ALKIS_WFS_URL, params=params, timeout=_TIMEOUT_S, headers=headers())
    resp.raise_for_status()
    return resp.text


def _ring(elem) -> list[tuple[float, float]]:
    pos = elem.findtext("gml:LinearRing/gml:posList", default="", namespaces=_NS).split()
    return [(float(pos[i]), float(pos[i + 1])) for i in range(0, len(pos) - 1, 2)]


def _geom_from_gml(geometrie) -> Optional[BaseGeometry]:
    """<geometrie> holding a MultiSurface/Polygon (with holes) or a Point → shapely geometry (EPSG:25832)."""
    polys = []
    for poly in geometrie.iter(f"{{{_NS['gml']}}}Polygon"):
        ext = poly.find("gml:exterior", _NS)
        if ext is None:
            continue
        polys.append(Polygon(_ring(ext), [_ring(h) for h in poly.findall("gml:interior", _NS)]))
    if polys:
        return polys[0] if len(polys) == 1 else MultiPolygon(polys)
    pos = geometrie.findtext(".//gml:Point/gml:pos", default="", namespaces=_NS).split()
    return Point(float(pos[0]), float(pos[1])) if len(pos) >= 2 else None


def parse_members(gml_text: str) -> list[dict]:
    """Every wfs:member → {"props": {local tag: text}, "geom": shapely geometry | None}."""
    root = ET.fromstring(gml_text)
    out = []
    for member in root.findall("wfs:member", _NS):
        feat = next(iter(member), None)
        if feat is None:
            continue
        props, geom = {}, None
        for child in feat:
            tag = child.tag.split("}")[-1]
            if tag == "geometrie":
                geom = _geom_from_gml(child)
            elif len(child) == 0 and child.text is not None:
                props[tag] = child.text.strip()
        out.append({"props": props, "geom": geom})
    return out


def parse_tntxt(text: Optional[str]) -> list[dict]:
    """'Wohnbaufläche;380|Straßenverkehr;20' → [{"art": "Wohnbaufläche", "m2": 380}, …]."""
    out = []
    for part in (text or "").split("|"):
        art, _, m2 = part.partition(";")
        if not art.strip():
            continue
        try:
            m2_val: Optional[int] = int(round(float(m2.replace(",", "."))))
        except ValueError:
            m2_val = None
        out.append({"art": art.strip(), "m2": m2_val})
    return out


def _nummer(p: dict) -> str:
    zaehler, nenner = p.get("flstnrzae") or "", p.get("flstnrnen")
    return f"{zaehler}/{nenner}" if nenner else zaehler


def _pick_parcel(members: list[dict], point_m: Point) -> Optional[tuple[dict, float]]:
    best = None
    for m in members:
        g = m["geom"]
        if g is None:
            continue
        dist = 0.0 if g.contains(point_m) else g.distance(point_m)
        if dist <= _SNAP_M and (best is None or dist < best[1]):
            best = (m, dist)
    return best


def get_flurstueck(lat: float, lon: float) -> Optional[dict]:
    """Parcel at (lat, lon) with its buildings, or None when no parcel lies within _SNAP_M (outside NRW)."""
    x, y = _TO_25832.transform(lon, lat)
    point_m = Point(x, y)
    bbox = (x - _POINT_BUFFER_M, y - _POINT_BUFFER_M, x + _POINT_BUFFER_M, y + _POINT_BUFFER_M)
    picked = _pick_parcel(parse_members(_wfs_gml("ave:Flurstueck", bbox)), point_m)
    if picked is None:
        return None
    parcel, dist = picked
    p, geom = parcel["props"], parcel["geom"]
    flaeche = float(p["flaeche"]) if p.get("flaeche") else round(geom.area, 1)

    buildings, on_parcel_area = [], 0.0
    for b in parse_members(_wfs_gml("ave:GebaeudeBauwerk", geom.bounds)):
        bg = b["geom"]
        if bg is None or bg.area == 0:
            continue
        inside = bg.intersection(geom).area
        if inside < 1.0:
            continue
        on = inside / bg.area > _ON_PARCEL_SHARE
        if on:
            on_parcel_area += bg.area
        buildings.append({"funktion": b["props"].get("funktion") or "Gebäude", "lage": b["props"].get("lagebeztxt") or None,
                          "grundflaeche_m2": round(bg.area, 1), "on_parcel": on})
    buildings.sort(key=lambda b: (not b["on_parcel"], -b["grundflaeche_m2"]))

    nutzung_pt = None
    for n in parse_members(_wfs_gml("ave:Nutzung", bbox)):
        if n["geom"] is not None and n["geom"].contains(point_m):
            nutzung_pt = n["props"].get("nutzart") or None
            break

    flur = p.get("flur") or ""
    return {
        "flurstueck": {
            "id": p.get("idflurst"), "kennzeichen": (p.get("flstkennz") or "").replace("_", ""),
            "gemarkung": p.get("gemarkung"), "gemarkung_nr": p.get("gemaschl"),
            "flur": int(flur) if flur.isdigit() else (flur or None), "nummer": _nummer(p),
            "flaeche_m2": flaeche, "lage": p.get("lagebeztxt") or None, "gemeinde": p.get("gemeinde"),
            "stand": (p.get("aktualit") or "").rstrip("Z") or None, "nutzung": parse_tntxt(p.get("tntxt")),
            "distance_m": round(dist, 1),
        },
        "gebaeude": buildings,
        "grundflaeche_m2": round(on_parcel_area, 1),
        "ueberbauung_pct": round(100 * on_parcel_area / flaeche, 1) if flaeche else None,
        "nutzung_am_punkt": nutzung_pt,
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_alkis.py -q`
Expected: `8 passed`

- [ ] **Step 5: Commit**

```bash
git add redat/sources/alkis.py tests/test_alkis.py
git commit -m "feat(alkis): parcel, buildings and Nutzung from the Geobasis NRW ALKIS WFS"
```

---

### Task 2: Essen Baulasten source module (`redat/sources/baulasten_essen.py`)

**Files:**
- Create: `redat/sources/baulasten_essen.py`
- Test: `tests/test_baulasten_essen.py`

**Interfaces:**
- Consumes: `redat.http.headers`
- Produces: `baulasten_essen.get_baulasten(lat, lon, kennzeichen: Optional[str]) -> Optional[dict]` with keys `status` (`vorhanden`|`moeglich`|`keine`), `on_parcel`, `nearby` (lists of `{"rechtsgrund","art","blatt","kennzeichen","status"}`), `radius_m`; `None` outside Essen. `baulasten_essen._query(layer: int, lat, lon, distance_m) -> dict` is the HTTP/monkeypatch point. `baulasten_essen.in_essen(lat, lon) -> bool`, `baulasten_essen.parse_art(text) -> tuple[Optional[str], Optional[str]]`.

- [ ] **Step 1: Write the failing tests**

`tests/test_baulasten_essen.py`:

```python
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
    assert d["status"] == "keine" and len(d["nearby"]) == 1


def test_query_failure_propagates(monkeypatch):
    stub(monkeypatch, {0: RuntimeError("503")})
    with pytest.raises(RuntimeError):
        bl.get_baulasten(51.4300, 7.0050, "05314403900040")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_baulasten_essen.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'redat.sources.baulasten_essen'`

- [ ] **Step 3: Implement the module**

`redat/sources/baulasten_essen.py`:

```python
"""Baulasten on and next to the parcel — Stadt Essen "Baulasteninformation" (Essen only).

Source: https://geo.essen.de/arcgis/rest/services/essen/Baulasteninformation/MapServer, layer 0
"Baulasten vorhanden" (21,410 Flurstück polygons) and layer 1 "Baulasten ggf. vorhanden" (207). Fields
(verified 2026-09-05): FSK "05314403900040" — the 14 significant characters of the ALKIS
Flurstückskennzeichen, so a parcel from redat.sources.alkis matches by string equality; ART
"BauOrdnungsrecht / Zufahrt" (Rechtsgrund " / " Art, Art may be empty); BAULAST "9 / 604 / 1" (Blatt).
The city calls the data kostenlos, unverbindlich, ohne Gewähr, wöchentlich aktualisiert — the card must
say so; a binding Auskunft is a written request to the Bauaufsicht.
Layer 2 (Blatt/Vermerk per Flurstück, mostly blank) is not used. `_query` is the single HTTP call and
monkeypatch point.
"""
from __future__ import annotations

import logging
from typing import Optional

import httpx

from redat.http import headers

logger = logging.getLogger(__name__)

BL_URL = "https://geo.essen.de/arcgis/rest/services/essen/Baulasteninformation/MapServer"
ESSEN_BBOX = (6.89, 51.35, 7.14, 51.53)   # lon_min, lat_min, lon_max, lat_max — Essen city, coarse
RADIUS_M = 50
_LAYERS = ((0, "vorhanden"), (1, "moeglich"))
_TIMEOUT_S = 25


def in_essen(lat: float, lon: float) -> bool:
    lon_min, lat_min, lon_max, lat_max = ESSEN_BBOX
    return lon_min <= lon <= lon_max and lat_min <= lat <= lat_max


def _query(layer: int, lat: float, lon: float, distance_m: float) -> dict:
    """ArcGIS point query with a metre buffer — HTTP/monkeypatch point."""
    params = {
        "f": "json", "where": "1=1", "geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint", "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects", "distance": distance_m, "units": "esriSRUnit_Meter",
        "outFields": "ART,FSK,BAULAST,TYP_BL,ALKIS_AMTL_FLAECHE", "returnGeometry": "false", "resultRecordCount": 50,
    }
    resp = httpx.get(f"{BL_URL}/{layer}/query", params=params, timeout=_TIMEOUT_S, headers=headers())
    resp.raise_for_status()
    return resp.json()


def parse_art(text: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """'BauOrdnungsrecht / Zufahrt' → ('BauOrdnungsrecht', 'Zufahrt'); blanks → None."""
    rechtsgrund, _, art = (text or "").partition("/")
    return rechtsgrund.strip() or None, art.strip() or None


def get_baulasten(lat: float, lon: float, kennzeichen: Optional[str]) -> Optional[dict]:
    """Baulasten within RADIUS_M split into this parcel / neighbours, or None outside Essen."""
    if not in_essen(lat, lon):
        return None
    items, seen = [], set()
    for layer, status in _LAYERS:
        for f in _query(layer, lat, lon, RADIUS_M).get("features") or []:
            a = f.get("attributes") or {}
            fsk, blatt = str(a.get("FSK") or "").strip(), str(a.get("BAULAST") or "").strip() or None
            if (fsk, blatt, status) in seen:
                continue
            seen.add((fsk, blatt, status))
            rechtsgrund, art = parse_art(a.get("ART"))
            items.append({"rechtsgrund": rechtsgrund, "art": art, "blatt": blatt, "kennzeichen": fsk or None, "status": status})
    on_parcel = [i for i in items if kennzeichen and i["kennzeichen"] == kennzeichen]
    nearby = [i for i in items if i not in on_parcel]
    if any(i["status"] == "vorhanden" for i in on_parcel):
        status = "vorhanden"
    elif on_parcel:
        status = "moeglich"
    else:
        status = "keine"
    return {"status": status, "on_parcel": on_parcel, "nearby": nearby, "radius_m": RADIUS_M}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_baulasten_essen.py -q`
Expected: `8 passed`

- [ ] **Step 5: Commit**

```bash
git add redat/sources/baulasten_essen.py tests/test_baulasten_essen.py
git commit -m "feat(baulasten): Essen Baulasteninformation lookup per Flurstück"
```

---

### Task 3: `flurstueck` card — registry, partials, report, fixture

**Files:**
- Modify: `redat/core/sections.py` (new `_fetch_flurstueck`, first `Section` in `SECTIONS`)
- Modify: `redat/core/tiers.py` (`"flurstueck": "parcel"`)
- Modify: `redat/core/sources_meta.py` (new `SourceMeta` row)
- Modify: `redat/report/builder.py` (`_s_flurstueck`, `SUMMARY`)
- Create: `redat/templates/analysis/_flurstueck.html`, `redat/templates/report/_flurstueck.html`
- Modify: `tests/fixtures/report_envelopes.json` (add `flurstueck`)
- Modify: `tests/test_analysis_sections.py`, `tests/test_tiers.py`, `tests/test_report_render.py`, `tests/test_web_pages.py`

**Interfaces:**
- Consumes: `alkis.get_flurstueck`, `baulasten_essen.get_baulasten` (Tasks 1–2)
- Produces: section key `flurstueck` with `data` = Task 1 dict + `baulasten` (Task 2 dict | None) + `baulasten_error` (str | None)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_analysis_sections.py` (and change the two key lists):

```python
# in test_registry_keys_and_order: the expected list becomes
        "flurstueck", "boris", "boris_trend", "flood", "starkregen", "noise", "bergbau", "gfnp", "schutzgebiete", "planning_essen",
        "planning_bochum", "denkmal", "amenities", "oepnv", "zensus", "energie", "breitband", "infrastruktur",
        "air_quality", "btw", "commute",
```

```python
FLURSTUECK_RAW = {
    "flurstueck": {"id": "DENW22AL800005He", "kennzeichen": "05314403900040", "gemarkung": "Rüttenscheid", "gemarkung_nr": "053144",
                   "flur": 39, "nummer": "40", "flaeche_m2": 538.0, "lage": "Herthastr. 4", "gemeinde": "Essen", "stand": "2026-02-17",
                   "nutzung": [{"art": "Wohnbaufläche", "m2": 538}], "distance_m": 0.0},
    "gebaeude": [{"funktion": "Wohngebäude", "lage": "Herthastr. 4", "grundflaeche_m2": 118.4, "on_parcel": True}],
    "grundflaeche_m2": 118.4, "ueberbauung_pct": 22.0, "nutzung_am_punkt": "Wohnbaufläche",
}
BAULASTEN_RAW = {"status": "vorhanden", "radius_m": 50, "nearby": [],
                 "on_parcel": [{"rechtsgrund": "BauOrdnungsrecht", "art": "Zufahrt", "blatt": "9 / 604 / 1", "kennzeichen": "05314403900040", "status": "vorhanden"}]}


def test_flurstueck_merges_baulasten(monkeypatch):
    from redat.sources import alkis, baulasten_essen
    monkeypatch.setattr(alkis, "get_flurstueck", lambda lat, lon: dict(FLURSTUECK_RAW))
    seen = {}
    monkeypatch.setattr(baulasten_essen, "get_baulasten", lambda lat, lon, kz: seen.setdefault("kz", kz) and BAULASTEN_RAW)
    d = S._fetch_flurstueck(CTX)
    assert seen["kz"] == "05314403900040" and d["baulasten"] == BAULASTEN_RAW and d["baulasten_error"] is None
    assert d["flurstueck"]["flaeche_m2"] == 538.0


def test_flurstueck_baulasten_failure_is_isolated(monkeypatch):
    from redat.sources import alkis, baulasten_essen
    monkeypatch.setattr(alkis, "get_flurstueck", lambda lat, lon: dict(FLURSTUECK_RAW))

    def boom(lat, lon, kz):
        raise RuntimeError("essen down")
    monkeypatch.setattr(baulasten_essen, "get_baulasten", boom)
    d = S._fetch_flurstueck(CTX)
    assert d["baulasten"] is None and d["baulasten_error"] == "essen down"


def test_flurstueck_none_is_empty(monkeypatch):
    from redat.sources import alkis
    monkeypatch.setattr(alkis, "get_flurstueck", lambda lat, lon: None)
    with pytest.raises(Empty) as ei:
        S._fetch_flurstueck(CTX)
    assert "Kein Flurstück" in ei.value.message
```

`tests/test_tiers.py`: add `"flurstueck"` to the list in `test_every_section_has_a_tier` and to the parcel set in `test_parcel_tier_keys`.

`tests/test_report_render.py::test_fixture_content_is_present`: add `"flurstueck": ["538 m²", "Rüttenscheid", "Zufahrt"],` to `checks`.

`tests/test_web_pages.py::test_index_renders_manifest`: extend the last assert with `and 'id="card-flurstueck"' in r.text and "Als Grundstücksgröße übernehmen" in r.text`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_analysis_sections.py tests/test_tiers.py tests/test_report_render.py tests/test_web_pages.py tests/test_sources_meta.py -q`
Expected: failures — `AttributeError: module … has no attribute '_fetch_flurstueck'`, order mismatch, `KeyError: 'flurstueck'` in tiers/fixtures.

- [ ] **Step 3: Registry entries**

`redat/core/sections.py` — add before `# ---- parcel tier` section functions (it is parcel tier; put it right after `_fetch_boris_trend`):

```python
def _fetch_flurstueck(ctx: Ctx) -> dict:
    from redat.sources import alkis, baulasten_essen

    f = alkis.get_flurstueck(ctx.lat, ctx.lon)
    if f is None:
        raise Empty("Kein Flurstück an diesem Punkt (außerhalb NRW?)")
    f["baulasten"], f["baulasten_error"] = None, None
    try:
        f["baulasten"] = baulasten_essen.get_baulasten(ctx.lat, ctx.lon, f["flurstueck"].get("kennzeichen"))
    except Exception as exc:  # noqa: BLE001 — the Essen server being down must not blank the parcel
        logger.warning("baulasten: %s", exc)
        f["baulasten_error"] = str(exc)
    return f
```

and as the **first** entry of the `SECTIONS` list:

```python
    Section("flurstueck", "Flurstück & Gebäude (ALKIS)", "📐", 30,
            "Geobasis NRW, ALKIS vereinfacht (dl-de/zero-2-0) · Stadt Essen, Baulasteninformation (unverbindlich, wöchentlich)", _fetch_flurstueck),
```

`redat/core/tiers.py`: add `"flurstueck": "parcel",` as the first entry of `SERVICE_TIER`.

`redat/core/sources_meta.py`: add as the first row of `SOURCES`:

```python
    SourceMeta(("flurstueck",), "ALKIS Flurstücke & Gebäude · Baulasteninformation Essen", "Geobasis NRW · Stadt Essen", "dl-de/zero-2-0 · Stadt Essen (unverbindlich)",
               "https://www.wfs.nrw.de/geobasis/wfs_nw_alkis_vereinfacht (WFS 2.0, GML) · geo.essen.de Baulasteninformation (ArcGIS REST)", "parcel", "live (ALKIS fortlaufend, Baulasten wöchentlich)"),
```

- [ ] **Step 4: Report summary**

`redat/report/builder.py` — add after `_s_boris_trend`:

```python
def _s_flurstueck(d):
    fl = d.get("flurstueck") or {}
    if fl.get("flaeche_m2") is None:
        return None, "gray", None
    fig = f"{fmt_int(fl['flaeche_m2'])} m²"
    if d.get("grundflaeche_m2"):
        fig += f" · {fmt_int(d['grundflaeche_m2'])} m² überbaut"
        if d.get("ueberbauung_pct") is not None:
            fig += f" ({fmt_num(d['ueberbauung_pct'], 0)} %)"
    bl = d.get("baulasten") or {}
    rating, color = {"vorhanden": ("Baulast eingetragen", "orange"), "moeglich": ("Baulast möglich", "yellow"),
                     "keine": ("Keine Baulast (Essen)", "green")}.get(bl.get("status"), (None, "gray"))
    return rating, color, fig
```

and `"flurstueck": _s_flurstueck,` as the first entry of `SUMMARY`.

- [ ] **Step 5: Web partial**

`redat/templates/analysis/_flurstueck.html`:

```html
<div class="grid grid-cols-1 md:grid-cols-3 gap-4 text-sm">
    <div>
        <div class="text-gray-500">Amtliche Fläche</div>
        <div class="text-2xl font-bold text-gray-900"><span x-text="$store.app.formatNumber(d.flurstueck.flaeche_m2)"></span> m²</div>
        <div class="text-xs text-gray-500">Gemarkung <span x-text="d.flurstueck.gemarkung"></span>, Flur <span x-text="d.flurstueck.flur"></span>, Flurstück <span x-text="d.flurstueck.nummer"></span></div>
    </div>
    <div>
        <div class="text-gray-500">Überbaut</div>
        <div class="text-2xl font-bold text-gray-900"><span x-text="$store.app.formatNumber(d.grundflaeche_m2)"></span> m²</div>
        <div class="text-xs text-gray-500" x-show="d.ueberbauung_pct != null" x-text="d.ueberbauung_pct + ' % der Grundstücksfläche'"></div>
    </div>
    <div>
        <div class="text-gray-500">Tatsächliche Nutzung</div>
        <div class="font-medium text-gray-900" x-text="d.nutzung_am_punkt || (d.flurstueck.nutzung[0] && d.flurstueck.nutzung[0].art) || '—'"></div>
        <div class="text-xs text-gray-500" x-show="d.flurstueck.lage" x-text="d.flurstueck.lage"></div>
    </div>
</div>
<button type="button" x-show="!plotSize && d.flurstueck.flaeche_m2"
        @click="plotSize = Math.round(d.flurstueck.flaeche_m2); load('boris')"
        class="mt-3 text-xs px-2 py-1 rounded border border-gray-300 hover:bg-gray-50">Als Grundstücksgröße übernehmen (Bodenrichtwert × Fläche)</button>

<template x-if="d.gebaeude.length">
    <ul class="mt-4 space-y-1 text-sm">
        <template x-for="(g, i) in d.gebaeude" :key="i">
            <li class="flex items-center gap-2">
                <span class="px-1.5 py-0.5 rounded text-xs" :class="g.on_parcel ? 'bg-gray-800 text-white' : 'bg-gray-100 text-gray-600'" x-text="g.on_parcel ? 'auf dem Flurstück' : 'angrenzend'"></span>
                <span class="text-gray-900" x-text="g.funktion"></span>
                <span class="text-gray-500" x-text="$store.app.formatNumber(g.grundflaeche_m2) + ' m² Grundfläche'"></span>
            </li>
        </template>
    </ul>
</template>

<template x-if="d.baulasten">
    <div class="mt-4 text-sm">
        <div class="flex items-center gap-2">
            <span class="font-semibold text-gray-900">Baulasten (Essen)</span>
            <span class="px-2 py-0.5 rounded-full text-xs font-bold"
                  :class="$store.app.getAirQualityColor({vorhanden: 'orange', moeglich: 'yellow', keine: 'green'}[d.baulasten.status])"
                  x-text="{vorhanden: 'eingetragen', moeglich: 'möglicherweise eingetragen', keine: 'keine auf dem Flurstück'}[d.baulasten.status]"></span>
        </div>
        <ul class="mt-1 space-y-0.5" x-show="d.baulasten.on_parcel.length">
            <template x-for="(b, i) in d.baulasten.on_parcel" :key="'p' + i">
                <li class="text-gray-800"><span x-text="b.art || 'Baulast'"></span> <span class="text-gray-500" x-text="'(' + (b.rechtsgrund || '—') + (b.blatt ? ', Blatt ' + b.blatt : '') + ')'"></span></li>
            </template>
        </ul>
        <p class="mt-1 text-xs text-gray-500" x-show="d.baulasten.nearby.length"
           x-text="d.baulasten.nearby.length + ' weitere Baulast(en) auf Nachbarflurstücken im Umkreis von ' + d.baulasten.radius_m + ' m — ' + d.baulasten.nearby.map(b => b.art || 'Baulast').join(', ')"></p>
        <p class="mt-1 text-xs text-gray-500">Unverbindliche Online-Auskunft der Stadt Essen (wöchentlich aktualisiert). Rechtsverbindlich ist nur die schriftliche Auskunft aus dem Baulastenverzeichnis.</p>
    </div>
</template>
<p class="mt-4 text-xs text-gray-500" x-show="!d.baulasten && !d.baulasten_error">Baulastenauskunft online nur für Essen verfügbar — in anderen Städten schriftlich bei der Bauaufsicht anfragen.</p>
<p class="mt-4 text-xs text-red-700" x-show="d.baulasten_error">Baulasten (Essen) derzeit nicht abrufbar.</p>

<p class="mt-3 text-xs text-gray-500">
    Amtliches Liegenschaftskataster (ALKIS), Stand <span x-text="d.flurstueck.stand || '—'"></span>. Ohne Eigentümer — das Grundbuch bleibt Sache des Notars.
    <span x-show="d.flurstueck.distance_m > 0" x-text="'Die Adresse wurde ' + d.flurstueck.distance_m + ' m neben dem Flurstück geocodiert.'"></span>
</p>
```

- [ ] **Step 6: Report partial**

`redat/templates/report/_flurstueck.html`:

```html
{% set fl = d.get("flurstueck") or {} %}
{% set bl = d.get("baulasten") %}
<div class="kpis">
  <div class="kpi">
    <div class="label">Amtliche Fläche</div>
    <div class="value">{{ (fl.flaeche_m2|fmt_int ~ " m²") if fl.get("flaeche_m2") is not none else "—" }}</div>
    <div class="sub">{% if fl.get("gemarkung") %}Gemarkung {{ fl.gemarkung }}, Flur {{ fl.get("flur") or "—" }}, Flurstück {{ fl.get("nummer") or "—" }}{% endif %}</div>
  </div>
  <div class="kpi">
    <div class="label">Überbaut</div>
    <div class="value">{{ (d.grundflaeche_m2|fmt_int ~ " m²") if d.get("grundflaeche_m2") is not none else "—" }}</div>
    {% if d.get("ueberbauung_pct") is not none %}<div class="sub">{{ d.ueberbauung_pct|fmt_num(0) }} % der Grundstücksfläche</div>{% endif %}
  </div>
  <div class="kpi">
    <div class="label">Tatsächliche Nutzung</div>
    <div class="value" style="font-size: 11pt">{{ d.get("nutzung_am_punkt") or ((fl.get("nutzung") or [{}])[0].get("art")) or "—" }}</div>
    {% if fl.get("lage") %}<div class="sub">{{ fl.lage }}</div>{% endif %}
  </div>
</div>
{% set geb = d.get("gebaeude") or [] %}
{% if geb %}
<table class="mt">
  <thead><tr><th>Gebäude</th><th>Lage</th><th class="num">Grundfläche</th></tr></thead>
  <tbody>
  {% for g in geb %}
    <tr>
      <td>{{ g.get("funktion") or "Gebäude" }}</td>
      <td>{{ "auf dem Flurstück" if g.get("on_parcel") else "angrenzend" }}</td>
      <td class="num">{{ (g.grundflaeche_m2|fmt_int ~ " m²") if g.get("grundflaeche_m2") is not none else "—" }}</td>
    </tr>
  {% endfor %}
  </tbody>
</table>
{% endif %}
{% if bl %}
{% set labels = {"vorhanden": ("Baulast eingetragen", "orange"), "moeglich": ("Baulast möglich", "yellow"), "keine": ("Keine Baulast auf dem Flurstück", "green")} %}
{% set lab = labels.get(bl.get("status")) %}
<h3>Baulasten (Stadt Essen)</h3>
{% if lab %}<p><span class="chip {{ rating_class(lab[1]) }}">{{ lab[0] }}</span></p>{% endif %}
{% if bl.get("on_parcel") %}
<table>
  <thead><tr><th>Art</th><th>Rechtsgrund</th><th>Blatt</th></tr></thead>
  <tbody>
  {% for b in bl.on_parcel %}<tr><td>{{ b.get("art") or "Baulast" }}</td><td>{{ b.get("rechtsgrund") or "—" }}</td><td>{{ b.get("blatt") or "—" }}</td></tr>{% endfor %}
  </tbody>
</table>
{% endif %}
{% if bl.get("nearby") %}<p class="footnote">{{ bl.nearby|length }} weitere Baulast(en) auf Nachbarflurstücken im Umkreis von {{ bl.get("radius_m") or 50 }} m.</p>{% endif %}
<p class="footnote">Unverbindliche Online-Auskunft der Stadt Essen; rechtsverbindlich ist nur die schriftliche Auskunft aus dem Baulastenverzeichnis.</p>
{% elif d.get("baulasten_error") %}
<p class="footnote">Baulasten (Essen) waren nicht abrufbar.</p>
{% else %}
<p class="footnote">Baulastenauskunft online nur für Essen verfügbar.</p>
{% endif %}
<p class="footnote">Amtliches Liegenschaftskataster (ALKIS){% if fl.get("stand") %}, Stand {{ fl.stand|fmt_date }}{% endif %}; ohne Eigentümerangaben.</p>
```

- [ ] **Step 7: Fixture**

Add to `tests/fixtures/report_envelopes.json` (top-level key `"flurstueck"`):

```json
"flurstueck": {"key": "flurstueck", "tier": "parcel", "status": "ok", "message": null, "took_ms": 812,
  "source": "Geobasis NRW, ALKIS vereinfacht (dl-de/zero-2-0) · Stadt Essen, Baulasteninformation (unverbindlich, wöchentlich)",
  "data": {"flurstueck": {"id": "DENW22AL800005He", "kennzeichen": "05314403900040", "gemarkung": "Rüttenscheid", "gemarkung_nr": "053144",
                          "flur": 39, "nummer": "40", "flaeche_m2": 538.0, "lage": "Herthastr. 4", "gemeinde": "Essen", "stand": "2026-02-17",
                          "nutzung": [{"art": "Wohnbaufläche", "m2": 538}], "distance_m": 0.0},
           "gebaeude": [{"funktion": "Wohngebäude", "lage": "Herthastr. 4", "grundflaeche_m2": 118.4, "on_parcel": true},
                        {"funktion": "Garage", "lage": null, "grundflaeche_m2": 24.0, "on_parcel": false}],
           "grundflaeche_m2": 118.4, "ueberbauung_pct": 22.0, "nutzung_am_punkt": "Wohnbaufläche",
           "baulasten": {"status": "vorhanden", "radius_m": 50,
                         "on_parcel": [{"rechtsgrund": "BauOrdnungsrecht", "art": "Zufahrt", "blatt": "9 / 604 / 1", "kennzeichen": "05314403900040", "status": "vorhanden"}],
                         "nearby": [{"rechtsgrund": "BauOrdnungsrecht", "art": "Abstandfläche", "blatt": "9 / 1126 / 1", "kennzeichen": "05314403800349", "status": "vorhanden"}]},
           "baulasten_error": null}}
```

- [ ] **Step 8: Run the whole suite**

Run: `.venv/bin/python -m pytest -q`
Expected: all green (the fixture-driven render tests now include `flurstueck`).

- [ ] **Step 9: Commit**

```bash
git add redat/core/sections.py redat/core/tiers.py redat/core/sources_meta.py redat/report/builder.py \
        redat/templates/analysis/_flurstueck.html redat/templates/report/_flurstueck.html \
        tests/fixtures/report_envelopes.json tests/test_analysis_sections.py tests/test_tiers.py tests/test_report_render.py tests/test_web_pages.py
git commit -m "feat(flurstueck): Flurstück & Gebäude card with Essen Baulasten"
```

---

### Task 4: Überschwemmungsgebiete — shared esri helper, `uesg.py`, flood card extension

**Files:**
- Create: `redat/sources/esri_wms.py`, `redat/sources/uesg.py`
- Modify: `redat/core/sections.py` (`_fetch_flood`, `Section("flood", …, cache_version=2)`)
- Modify: `redat/report/builder.py` (`_s_flood`)
- Modify: `redat/templates/analysis/_flood.html`, `redat/templates/report/_flood.html`
- Modify: `tests/fixtures/report_envelopes.json` (flood data gains `uesg`), `tests/test_analysis_sections.py`, `tests/test_report_render.py`
- Test: `tests/test_esri_wms.py`, `tests/test_uesg.py`

**Interfaces:**
- Produces: `esri_wms.featureinfo_params(lat, lon, layers: str, *, d=0.001, feature_count=10) -> dict`, `esri_wms.parse_featureinfo(xml_text) -> list[tuple[str, dict]]` (layername, fields; blank/"Null" dropped); `uesg.get_uesg(lat, lon) -> {"zones": [...], "legal": bool}`, `uesg._featureinfo(lat, lon) -> str` (HTTP point), `uesg.parse_uesg(xml_text) -> list[dict]`.
- Consumes (Task 5 reuses): `esri_wms.*`.

- [ ] **Step 1: Write the failing tests**

`tests/test_esri_wms.py`:

```python
from redat.sources import esri_wms

XML = """<?xml version="1.0" encoding="UTF-8"?>
<FeatureInfoResponse xmlns="http://www.esri.com/wms" xmlns:esri_wms="http://www.esri.com/wms" version="1.3.0">
 <FeatureInfoCollection layername="Festgesetzte Überschwemmungsgebiete">
  <FeatureInfo>
   <Field><FieldName>OBJECTID</FieldName><FieldValue>9064</FieldValue></Field>
   <Field><FieldName>name</FieldName><FieldValue>Ruhr</FieldValue></Field>
   <Field><FieldName>BR</FieldName><FieldValue> </FieldValue></Field>
   <Field><FieldName>gewkz</FieldName><FieldValue>Null</FieldValue></Field>
  </FeatureInfo>
 </FeatureInfoCollection>
 <FeatureInfoCollection layername="leer"/>
</FeatureInfoResponse>"""


def test_parse_featureinfo_drops_blanks_and_nulls():
    assert esri_wms.parse_featureinfo(XML) == [("Festgesetzte Überschwemmungsgebiete", {"OBJECTID": "9064", "name": "Ruhr"})]


def test_parse_empty_response():
    assert esri_wms.parse_featureinfo('<?xml version="1.0"?><FeatureInfoResponse xmlns="http://www.esri.com/wms" version="1.3.0"/>') == []


def test_params_center_pixel_and_lat_lon_axis_order():
    p = esri_wms.featureinfo_params(51.44, 7.085, "3,5,6")
    assert p["LAYERS"] == p["QUERY_LAYERS"] == "3,5,6" and p["CRS"] == "EPSG:4326"
    assert p["BBOX"] == "51.439,7.084,51.441,7.086" and p["I"] == p["J"] == 50 and p["WIDTH"] == p["HEIGHT"] == 101
    assert p["INFO_FORMAT"] == "application/vnd.esri.wms_featureinfo_xml" and p["FEATURE_COUNT"] == 10
```

`tests/test_uesg.py`:

```python
import pytest

from redat.sources import uesg

XML_HIT = """<?xml version="1.0" encoding="UTF-8"?>
<FeatureInfoResponse xmlns="http://www.esri.com/wms" version="1.3.0">
 <FeatureInfoCollection layername="Festgesetzte Überschwemmungsgebiete">
  <FeatureInfo>
   <Field><FieldName>Typ</FieldName><FieldValue>1</FieldValue></Field>
   <Field><FieldName>gewkz</FieldName><FieldValue>276</FieldValue></Field>
   <Field><FieldName>name</FieldName><FieldValue>Ruhr</FieldValue></Field>
   <Field><FieldName>uesg_pdf</FieldName><FieldValue>Amtsblatt Nr. 27 vom 06.07.2023</FieldValue></Field>
   <Field><FieldName>datum</FieldName><FieldValue>14.4.2016</FieldValue></Field>
   <Field><FieldName>BR</FieldName><FieldValue>BR Düsseldorf</FieldValue></Field>
  </FeatureInfo>
 </FeatureInfoCollection>
 <FeatureInfoCollection layername="Ermittelte Überschwemmungsgebiete">
  <FeatureInfo>
   <Field><FieldName>name</FieldName><FieldValue>Ruhr</FieldValue></Field>
  </FeatureInfo>
 </FeatureInfoCollection>
</FeatureInfoResponse>"""
XML_NONE = '<?xml version="1.0"?><FeatureInfoResponse xmlns="http://www.esri.com/wms" version="1.3.0"/>'


def test_parse_hit_orders_legal_first():
    zones = uesg.parse_uesg(XML_HIT)
    assert zones == [
        {"kind": "festgesetzt", "kind_label": "Festgesetztes Überschwemmungsgebiet", "name": "Ruhr",
         "amtsblatt": "Amtsblatt Nr. 27 vom 06.07.2023", "date": "14.4.2016", "authority": "BR Düsseldorf"},
        {"kind": "ermittelt", "kind_label": "Ermitteltes Überschwemmungsgebiet", "name": "Ruhr", "amtsblatt": None, "date": None, "authority": None},
    ]


def test_vorlaeufig_is_legal_too():
    xml = XML_HIT.replace("Festgesetzte Überschwemmungsgebiete", "vorläufig gesicherte Überschwemmungsgebiete")
    z = uesg.parse_uesg(xml)
    assert z[0]["kind"] == "vorlaeufig" and z[0]["kind_label"] == "Vorläufig gesichertes Überschwemmungsgebiet"


def test_get_uesg(monkeypatch):
    monkeypatch.setattr(uesg, "_featureinfo", lambda lat, lon: XML_HIT)
    d = uesg.get_uesg(51.44, 7.085)
    assert d["legal"] is True and [z["kind"] for z in d["zones"]] == ["festgesetzt", "ermittelt"]
    monkeypatch.setattr(uesg, "_featureinfo", lambda lat, lon: XML_NONE)
    assert uesg.get_uesg(51.43, 7.0) == {"zones": [], "legal": False}


def test_unknown_layer_is_ignored():
    xml = XML_HIT.replace("Ermittelte Überschwemmungsgebiete", "Rückgewinnbare Rückhalteflächen")
    assert [z["kind"] for z in uesg.parse_uesg(xml)] == ["festgesetzt"]
```

Changes to `tests/test_analysis_sections.py::test_flood_normalizer` — the fetch now also calls `uesg.get_uesg`; stub it and extend the expectation, plus one new test:

```python
def test_flood_normalizer(monkeypatch):
    from redat.sources import flood, uesg
    raw = {"zone": "HQextrem", "risk_level": "medium", "hits": {
        "HQhaeufig": {"hit": False, "min_distance_m": 812.5, "raw": None},
        "HQ100": {"hit": False, "min_distance_m": None, "raw": None},
        "HQextrem": {"hit": True, "min_distance_m": 0.0, "raw": {"name": "Ruhr"}},
    }}
    monkeypatch.setattr(flood, "flood_risk", lambda lat, lon: raw)
    monkeypatch.setattr(uesg, "get_uesg", lambda lat, lon: {"zones": [], "legal": False})
    d = S._fetch_flood(CTX)
    assert d == {"flood_zone": "HQextrem", "flood_risk_level": "medium", "hits": {
        "HQhaeufig": {"hit": False, "min_distance_m": 812.5},
        "HQ100": {"hit": False, "min_distance_m": None},
        "HQextrem": {"hit": True, "min_distance_m": 0.0},
    }, "uesg": {"zones": [], "legal": False, "error": None}}


def test_flood_legal_uesg_lifts_level_and_failure_is_isolated(monkeypatch):
    from redat.sources import flood, uesg
    monkeypatch.setattr(flood, "flood_risk", lambda lat, lon: {"zone": None, "risk_level": "low", "hits": {}})
    zone = {"kind": "festgesetzt", "kind_label": "Festgesetztes Überschwemmungsgebiet", "name": "Ruhr", "amtsblatt": None, "date": None, "authority": None}
    monkeypatch.setattr(uesg, "get_uesg", lambda lat, lon: {"zones": [zone], "legal": True})
    d = S._fetch_flood(CTX)
    assert d["flood_risk_level"] == "high" and d["uesg"]["zones"] == [zone]

    def boom(lat, lon):
        raise RuntimeError("wms down")
    monkeypatch.setattr(uesg, "get_uesg", boom)
    d = S._fetch_flood(CTX)
    assert d["flood_risk_level"] == "low" and d["uesg"] == {"zones": [], "legal": False, "error": "wms down"}


def test_flood_cache_version_bumped():
    assert S.SECTIONS["flood"].cache_version == 2
```

`tests/test_report_render.py`: change the `"flood"` needles to `["HQ100", "180 m", "Ermitteltes Überschwemmungsgebiet", "Ruhr"]`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_esri_wms.py tests/test_uesg.py tests/test_analysis_sections.py -q`
Expected: `ModuleNotFoundError` for the two new modules; flood tests fail on the missing `uesg` key.

- [ ] **Step 3: Implement `esri_wms.py`**

```python
"""The esri-flavoured WMS GetFeatureInfo every wms.nrw.de service speaks (uesg, irw, wsg, …).

`featureinfo_params` builds the request around the centre pixel of a 101×101 px tile that spans
2·d degrees (d = 0.001 ≈ 110 m → ~2 m/px, small enough for layers with a MinScaleDenominator);
WMS 1.3.0 wants EPSG:4326 BBOX as lat,lon. `parse_featureinfo` flattens
FeatureInfoResponse/FeatureInfoCollection/FeatureInfo/Field into (layername, {name: value}) pairs,
dropping blank and "Null" values.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

INFO_FORMAT = "application/vnd.esri.wms_featureinfo_xml"
_NS = {"w": "http://www.esri.com/wms"}


def featureinfo_params(lat: float, lon: float, layers: str, *, d: float = 0.001, feature_count: int = 10) -> dict:
    return {
        "SERVICE": "WMS", "VERSION": "1.3.0", "REQUEST": "GetFeatureInfo", "LAYERS": layers, "QUERY_LAYERS": layers,
        "STYLES": "", "CRS": "EPSG:4326", "BBOX": f"{lat - d:g},{lon - d:g},{lat + d:g},{lon + d:g}",
        "WIDTH": 101, "HEIGHT": 101, "I": 50, "J": 50, "FEATURE_COUNT": feature_count, "INFO_FORMAT": INFO_FORMAT,
    }


def parse_featureinfo(xml_text: str) -> list[tuple[str, dict]]:
    root = ET.fromstring(xml_text)
    out = []
    for coll in root.findall("w:FeatureInfoCollection", _NS):
        layer = coll.get("layername", "")
        for fi in coll.findall("w:FeatureInfo", _NS):
            fields = {}
            for field in fi.findall("w:Field", _NS):
                name = field.findtext("w:FieldName", default="", namespaces=_NS)
                value = (field.findtext("w:FieldValue", default="", namespaces=_NS) or "").strip()
                if name and value and value != "Null":
                    fields[name] = value
            out.append((layer, fields))
    return out
```

Note on `:g` formatting: `51.44 - 0.001` prints as `51.439`, which the test asserts; `:g` also avoids `51.438999999`.

- [ ] **Step 4: Implement `uesg.py`**

```python
"""Überschwemmungsgebiete NRW (rechtlich) — the §78 WHG layer the HWRM hazard maps are not.

Source: https://www.wms.nrw.de/umwelt/wasser/uesg (Land NRW, open data), WMS 1.3.0 GetFeatureInfo,
query layers 6 "Festgesetzte Überschwemmungsgebiete" (Rechtsverordnung der Bezirksregierung), 5 "vorläufig
gesicherte Überschwemmungsgebiete" (same legal effect until the Verordnung is issued), 3 "Ermittelte
Überschwemmungsgebiete" (Fachplanung, HQ100 basis, no direct legal effect). Fields (verified 2026-09-05 on
the Ruhr at Essen-Steele): name "Ruhr", uesg_pdf "Amtsblatt Nr. 27 vom 06.07.2023", datum "14.4.2016",
BR "BR Düsseldorf". Inside a festgesetztes/vorläufig gesichertes ÜSG new buildings need an Ausnahme
(§78 WHG) and Heizöltanks are prohibited (§78c). `_featureinfo` is the single HTTP call and monkeypatch point.
"""
from __future__ import annotations

from typing import Optional

import httpx

from redat.http import headers
from redat.sources.esri_wms import featureinfo_params, parse_featureinfo

UESG_WMS_URL = "https://www.wms.nrw.de/umwelt/wasser/uesg"
LAYERS = "3,5,6"
_TIMEOUT_S = 20
# (layername prefix, kind, label) — legal kinds first so the zone list reads in order of consequence.
_KINDS = (
    ("festgesetzte", "festgesetzt", "Festgesetztes Überschwemmungsgebiet"),
    ("vorläufig", "vorlaeufig", "Vorläufig gesichertes Überschwemmungsgebiet"),
    ("ermittelte", "ermittelt", "Ermitteltes Überschwemmungsgebiet"),
)
LEGAL_KINDS = {"festgesetzt", "vorlaeufig"}


def _featureinfo(lat: float, lon: float) -> str:
    """Raw esri featureinfo XML for the three ÜSG layers at the point — HTTP/monkeypatch point."""
    resp = httpx.get(UESG_WMS_URL, params=featureinfo_params(lat, lon, LAYERS), timeout=_TIMEOUT_S, headers=headers())
    resp.raise_for_status()
    return resp.text


def _kind(layername: str) -> Optional[tuple[str, str]]:
    low = layername.lower()
    for prefix, kind, label in _KINDS:
        if low.startswith(prefix):
            return kind, label
    return None


def parse_uesg(xml_text: str) -> list[dict]:
    zones = []
    for layername, f in parse_featureinfo(xml_text):
        k = _kind(layername)
        if k is None:
            continue
        kind, label = k
        zones.append({"kind": kind, "kind_label": label, "name": f.get("name"), "amtsblatt": f.get("uesg_pdf"),
                      "date": f.get("datum"), "authority": f.get("BR")})
    order = {kind: i for i, (_, kind, _) in enumerate(_KINDS)}
    zones.sort(key=lambda z: order[z["kind"]])
    return zones


def get_uesg(lat: float, lon: float) -> dict:
    zones = parse_uesg(_featureinfo(lat, lon))
    return {"zones": zones, "legal": any(z["kind"] in LEGAL_KINDS for z in zones)}
```

- [ ] **Step 5: Extend `_fetch_flood` and bump the cache version**

In `redat/core/sections.py` replace `_fetch_flood`:

```python
def _fetch_flood(ctx: Ctx) -> dict:
    from redat.sources import flood, uesg

    fr = flood.flood_risk(ctx.lat, ctx.lon)
    level = fr.get("risk_level") or "low"
    ue: dict = {"zones": [], "legal": False, "error": None}
    try:
        ue.update(uesg.get_uesg(ctx.lat, ctx.lon))
    except Exception as exc:  # noqa: BLE001 — the ÜSG WMS must not blank the HWRM result
        logger.warning("uesg: %s", exc)
        ue["error"] = str(exc)
    if ue["legal"]:
        level = "high"   # §78 WHG Bauverbot is the strongest signal this card has
    return {
        "flood_zone": fr.get("zone"),
        "flood_risk_level": level,
        "hits": {sc: {"hit": bool(h.get("hit")), "min_distance_m": h.get("min_distance_m")} for sc, h in (fr.get("hits") or {}).items()},
        "uesg": ue,
    }
```

and the registry line:

```python
    Section("flood", "Hochwasserrisiko", "🌊", 15,
            "Land NRW, Hochwassergefahrenkarten (HQhäufig / HQ100 / HQextrem) · Überschwemmungsgebiete NRW (§ 78 WHG)", _fetch_flood,
            cache_version=2),
```

- [ ] **Step 6: Partials and summary**

Append to `redat/templates/analysis/_flood.html` (before the last `<p>`):

```html
<template x-if="d.uesg && d.uesg.zones.length">
    <div class="mt-4 text-sm">
        <div class="font-semibold text-gray-900">⚖️ Überschwemmungsgebiet (Wasserhaushaltsgesetz)</div>
        <ul class="mt-1 space-y-0.5">
            <template x-for="(z, i) in d.uesg.zones" :key="i">
                <li class="text-gray-700">
                    <span class="font-medium" x-text="z.kind_label"></span> — <span x-text="z.name || '—'"></span>
                    <span class="text-gray-500" x-show="z.amtsblatt || z.date" x-text="'(' + [z.amtsblatt, z.date ? 'Datenstand ' + z.date : null].filter(Boolean).join(', ') + ')'"></span>
                </li>
            </template>
        </ul>
        <p class="mt-1 text-xs text-gray-500" x-show="d.uesg.legal">Festgesetzt/vorläufig gesichert: Neubauten und Erweiterungen nur mit Ausnahmegenehmigung (§ 78 WHG), keine neuen Heizöltanks (§ 78c WHG), hochwasserangepasstes Bauen Pflicht.</p>
    </div>
</template>
<p class="mt-2 text-xs text-red-700" x-show="d.uesg && d.uesg.error">Überschwemmungsgebiete NRW derzeit nicht abrufbar.</p>
```

Append to `redat/templates/report/_flood.html` (before the footnote):

```html
{% set ue = d.get("uesg") or {} %}
{% if ue.get("zones") %}
<h3>Überschwemmungsgebiet (§ 78 WHG)</h3>
<table>
  <thead><tr><th>Status</th><th>Gewässer</th><th>Verordnung</th></tr></thead>
  <tbody>
  {% for z in ue.zones %}
    <tr><td class="strong">{{ z.get("kind_label") or "—" }}</td><td>{{ z.get("name") or "—" }}</td><td>{{ z.get("amtsblatt") or "—" }}</td></tr>
  {% endfor %}
  </tbody>
</table>
{% if ue.get("legal") %}<p class="footnote">Neubauten nur mit Ausnahmegenehmigung (§ 78 WHG), keine neuen Heizöltanks (§ 78c WHG).</p>{% endif %}
{% endif %}
```

`redat/report/builder.py::_s_flood`:

```python
def _s_flood(d):
    rating, color = FLOOD_LEVELS.get(d.get("flood_risk_level"), (None, "gray"))
    zone = d.get("flood_zone")
    fig = f"Zone {zone}" if zone else "außerhalb aller Szenarien"
    legal = [z for z in ((d.get("uesg") or {}).get("zones") or []) if z.get("kind") in ("festgesetzt", "vorlaeufig")]
    if legal:
        fig += f" · ÜSG {legal[0].get('name') or ''} (§ 78 WHG)".rstrip()
    return rating, color, fig
```

Fixture: in `tests/fixtures/report_envelopes.json` add to the `flood` `data`:

```json
"uesg": {"zones": [{"kind": "ermittelt", "kind_label": "Ermitteltes Überschwemmungsgebiet", "name": "Ruhr", "amtsblatt": null, "date": "14.4.2016", "authority": "BR Düsseldorf"}], "legal": false, "error": null}
```

(an *ermitteltes* ÜSG is not legal, so the fixture's `flood_risk_level` stays `"low"` and `tests/test_report_builder.py`'s "Gering"/green assertion on the flood row keeps holding).

- [ ] **Step 7: Run the whole suite**

Run: `.venv/bin/python -m pytest -q`
Expected: green.

- [ ] **Step 8: Commit**

```bash
git add redat/sources/esri_wms.py redat/sources/uesg.py redat/core/sections.py redat/report/builder.py \
        redat/templates/analysis/_flood.html redat/templates/report/_flood.html tests/
git commit -m "feat(flood): legal Überschwemmungsgebiete (§78 WHG) via NRW WMS; shared esri featureinfo helper"
```

---

### Task 5: `irw` card — Immobilienrichtwerte

**Files:**
- Create: `redat/sources/irw.py`, `redat/templates/analysis/_irw.html`, `redat/templates/report/_irw.html`
- Modify: `redat/core/sections.py`, `redat/core/tiers.py`, `redat/core/sources_meta.py`, `redat/report/builder.py`
- Modify: `tests/fixtures/report_envelopes.json`, `tests/test_analysis_sections.py`, `tests/test_tiers.py`, `tests/test_report_render.py`
- Test: `tests/test_irw.py`

**Interfaces:**
- Consumes: `esri_wms.featureinfo_params`, `esri_wms.parse_featureinfo` (Task 4)
- Produces: `irw.get_irw(lat, lon) -> Optional[dict]` `{"stichtag": "2026-01-01", "gutachterausschuss": str|None, "werte": [...]}`; `irw._featureinfo(lat, lon) -> str` (HTTP point); `irw.parse_irw(xml_text) -> list[dict]`; section key `irw` (parcel) placed right after `boris_trend`.

- [ ] **Step 1: Write the failing tests**

`tests/test_irw.py`:

```python
import pytest

from redat.sources import irw


def coll(layer, **fields):
    rows = "".join(f"<Field><FieldName>{k}</FieldName><FieldValue>{v}</FieldValue></Field>" for k, v in fields.items())
    return f'<FeatureInfoCollection layername="{layer}"><FeatureInfo>{rows}</FeatureInfo></FeatureInfoCollection>'


def xml(*colls):
    return ('<?xml version="1.0" encoding="UTF-8"?><FeatureInfoResponse xmlns="http://www.esri.com/wms" version="1.3.0">'
            + "".join(colls) + "</FeatureInfoResponse>")


RH = coll("irw_reihen_doppelhaeuser", GENA="Essen", GABE="Der Gutachterausschuss für Grundstückswerte in der Stadt Essen", ORTST="Rüttenscheid",
          PLZ="45131", IMRW="3950", STAG="01.01.2026", TEILMA="3", EGART="2", BJ="1962", WHNFL="130", FLAE="300", WHNLA=" ",
          UDOK_URL="https://www.boris.nrw.de/borisfachdaten/lgd/irw/2026/LGDIR_3_0510900_2026.pdf")
ETW = coll("irw_eigentumswohnungen", GENA="Essen", GABE="GA Essen", ORTST="Rüttenscheid", PLZ="45131", IMRW="2800", STAG="01.01.2026",
           TEILMA="1", BJ="1962", WHNFL="69", ANZEGEB="7-12", WHNLA="3", UDOK_URL="https://x/LGDIR_1.pdf")
EFH = coll("irw_ein_zweifamilienhaeuser", GENA="Bochum", GABE="GA Bochum", ORTST=" ", IMRW="3350", STAG="01.01.2026", TEILMA="2", BJ="1965",
           WHNFL="151-175", FLAE="601-800", UDOK_URL="https://x/LGDIR_2.pdf")


def test_parse_sorted_by_teilmarkt_with_normobjekt():
    w = irw.parse_irw(xml(RH, ETW, EFH))
    assert [x["teilmarkt"] for x in w] == [1, 2, 3]
    etw, efh, rh = w
    assert etw == {"teilmarkt": 1, "teilmarkt_label": "Eigentumswohnungen", "eur_m2": 2800, "stichtag": "2026-01-01",
                   "ortsteil": "Rüttenscheid", "plz": "45131", "wohnlage": "gut", "gutachterausschuss": "GA Essen",
                   "normobjekt": {"baujahr": "1962", "wohnflaeche_m2": "69", "grundstueck_m2": None, "anbauweise": None, "wohnungen": "7-12"},
                   "doku_url": "https://x/LGDIR_1.pdf"}
    assert rh["normobjekt"]["anbauweise"] == "Doppelhaushälfte" and rh["normobjekt"]["grundstueck_m2"] == "300" and rh["wohnlage"] is None
    assert efh["ortsteil"] is None and efh["normobjekt"]["wohnflaeche_m2"] == "151-175"


def test_get_irw_and_empty(monkeypatch):
    monkeypatch.setattr(irw, "_featureinfo", lambda lat, lon: xml(RH, ETW))
    d = irw.get_irw(51.43, 7.005)
    assert d["stichtag"] == "2026-01-01" and d["gutachterausschuss"] == "GA Essen" and len(d["werte"]) == 2   # sorted → ETW first
    monkeypatch.setattr(irw, "_featureinfo", lambda lat, lon: xml())
    assert irw.get_irw(51.48, 7.216) is None


def test_bad_number_is_skipped():
    assert irw.parse_irw(xml(coll("irw_mehrfamilienhaeuser", IMRW="n/a", TEILMA="4", STAG="01.01.2026"))) == []
```

Registry/tier/render test updates: insert `"irw"` after `"boris_trend"` in `test_registry_keys_and_order`, in `test_tiers.py::test_every_section_has_a_tier` and in the parcel set; add to `tests/test_analysis_sections.py`:

```python
def test_irw_passthrough_and_empty(monkeypatch):
    from redat.sources import irw
    monkeypatch.setattr(irw, "get_irw", lambda lat, lon: {"stichtag": "2026-01-01", "gutachterausschuss": "GA", "werte": []})
    assert S._fetch_irw(CTX)["stichtag"] == "2026-01-01"
    monkeypatch.setattr(irw, "get_irw", lambda lat, lon: None)
    with pytest.raises(Empty):
        S._fetch_irw(CTX)
```

`tests/test_report_render.py` checks: `"irw": ["Reihen-/Doppelhäuser", "3.950 €/m²", "Baujahr 1962"],`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_irw.py tests/test_analysis_sections.py -q`
Expected: `ModuleNotFoundError: redat.sources.irw`; registry order test fails.

- [ ] **Step 3: Implement `irw.py`**

```python
"""Immobilienrichtwerte (IRW) — €/m² Wohnfläche per Teilmarkt from BORIS NRW.

Source: https://www.wms.nrw.de/boris/wms_nw_irw (Gutachterausschüsse NRW, dl-de/zero-2-0), WMS 1.3.0
GetFeatureInfo on the value layers 9 gemischt genutzt, 12 Mehrfamilienhäuser, 15 Reihen-/Doppelhäuser,
18 Ein-/Zweifamilienhäuser, 21 Eigentumswohnungen (Büro/Gewerbe are not asked). The layers have a
MinScaleDenominator of ~1:57,000, so the request must be a small tile (esri_wms default ≈ 2 m/px).
Fields (IRW_Datenmodell.pdf, verified live 2026-09-05): IMRW €/m², STAG "01.01.2026", TEILMA 1–7,
ORTST, PLZ, WHNLA Wohnlage 1–8, BJ/WHNFL/FLAE of the Normobjekt (single values or ranges "111-130"),
EGART Anbauweise, ANZEGEB Wohnungen im Gebäude, GABE Gutachterausschuss, UDOK_URL PDF with the
Umrechnungskoeffizienten. Essen and Bochum both publish IRW; dense inner-city points may lie in no zone.
`_featureinfo` is the single HTTP call and monkeypatch point.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import httpx

from redat.http import headers
from redat.sources.esri_wms import featureinfo_params, parse_featureinfo

IRW_WMS_URL = "https://www.wms.nrw.de/boris/wms_nw_irw"
LAYERS = "9,12,15,18,21"
_TIMEOUT_S = 20
TEILMARKT = {1: "Eigentumswohnungen", 2: "Ein-/Zweifamilienhäuser (freistehend)", 3: "Reihen-/Doppelhäuser",
             4: "Mehrfamilienhäuser", 5: "Gemischt genutzte Gebäude", 6: "Büro-/Geschäftsgebäude", 7: "Gewerbe/Industrie"}
WOHNLAGE = {1: "sehr gut", 2: "gut – sehr gut", 3: "gut", 4: "mittel – gut", 5: "mittel", 6: "einfach – mittel", 7: "einfach", 8: "sehr einfach"}
ANBAUWEISE = {1: "freistehend", 2: "Doppelhaushälfte", 4: "Reihenmittelhaus", 5: "Reihenendhaus"}


def _featureinfo(lat: float, lon: float) -> str:
    resp = httpx.get(IRW_WMS_URL, params=featureinfo_params(lat, lon, LAYERS), timeout=_TIMEOUT_S, headers=headers())
    resp.raise_for_status()
    return resp.text


def _int(v: Optional[str]) -> Optional[int]:
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def _iso(d: Optional[str]) -> Optional[str]:
    try:
        return datetime.strptime((d or "").strip(), "%d.%m.%Y").date().isoformat()
    except ValueError:
        return None


def parse_irw(xml_text: str) -> list[dict]:
    werte = []
    for _layer, f in parse_featureinfo(xml_text):
        eur, teilmarkt = _int(f.get("IMRW")), _int(f.get("TEILMA"))
        if eur is None or teilmarkt is None:
            continue
        werte.append({
            "teilmarkt": teilmarkt, "teilmarkt_label": TEILMARKT.get(teilmarkt, f"Teilmarkt {teilmarkt}"),
            "eur_m2": eur, "stichtag": _iso(f.get("STAG")),
            "ortsteil": f.get("ORTST"), "plz": f.get("PLZ"),
            "wohnlage": WOHNLAGE.get(_int(f.get("WHNLA"))),
            "gutachterausschuss": f.get("GABE"),
            "normobjekt": {"baujahr": f.get("BJ"), "wohnflaeche_m2": f.get("WHNFL"), "grundstueck_m2": f.get("FLAE"),
                           "anbauweise": ANBAUWEISE.get(_int(f.get("EGART"))), "wohnungen": f.get("ANZEGEB")},
            "doku_url": f.get("UDOK_URL"),
        })
    werte.sort(key=lambda w: w["teilmarkt"])
    return werte


def get_irw(lat: float, lon: float) -> Optional[dict]:
    """IRW per Teilmarkt at the point, or None when no value zone covers it."""
    werte = parse_irw(_featureinfo(lat, lon))
    if not werte:
        return None
    return {"stichtag": werte[0]["stichtag"], "gutachterausschuss": werte[0]["gutachterausschuss"], "werte": werte}
```

- [ ] **Step 4: Registry, summary, partials, fixture**

`redat/core/sections.py` — after `_fetch_boris_trend`:

```python
def _fetch_irw(ctx: Ctx) -> dict:
    from redat.sources.irw import get_irw

    d = get_irw(ctx.lat, ctx.lon)
    if d is None:
        raise Empty("Keine Immobilienrichtwerte für diesen Ort (keine Richtwertzone oder Gutachterausschuss ohne IRW)")
    return d
```

Registry, directly after the `boris_trend` line:

```python
    Section("irw", "Immobilienrichtwerte", "🏠", 25, "BORIS NRW — Immobilienrichtwerte der Gutachterausschüsse (€/m² Wohnfläche, Normobjekt)", _fetch_irw),
```

`tiers.py`: `"irw": "parcel",` after `boris_trend`. `sources_meta.py` row (after the BORIS row):

```python
    SourceMeta(("irw",), "BORIS NRW Immobilienrichtwerte", "Gutachterausschüsse NRW / Geobasis NRW", "dl-de/zero-2-0",
               "https://www.wms.nrw.de/boris/wms_nw_irw (WMS GetFeatureInfo, Layer 9/12/15/18/21)", "parcel", "jährlich (1.1.), live WMS"),
```

`builder.py`:

```python
def _s_irw(d):
    w = [x for x in (d.get("werte") or []) if x.get("eur_m2") is not None]
    if not w:
        return None, "gray", None
    parts = [f"{x.get('teilmarkt_label')} {fmt_int(x['eur_m2'])} €/m²" for x in w[:3]]
    return None, "gray", " · ".join(parts)
```

with `"irw": _s_irw,` after `"boris_trend"` in `SUMMARY`.

`redat/templates/analysis/_irw.html`:

```html
<table class="w-full text-sm">
    <thead><tr class="text-left text-gray-500"><th class="py-1">Teilmarkt</th><th class="py-1 text-right">€/m² Wohnfl.</th><th class="py-1">Normobjekt</th></tr></thead>
    <tbody>
        <template x-for="w in d.werte" :key="w.teilmarkt">
            <tr class="border-t align-top">
                <td class="py-1.5 font-medium text-gray-900" x-text="w.teilmarkt_label"></td>
                <td class="py-1.5 text-right text-lg font-bold text-gray-900" x-text="$store.app.formatNumber(w.eur_m2)"></td>
                <td class="py-1.5 text-xs text-gray-600">
                    <span x-show="w.normobjekt.baujahr" x-text="'Baujahr ' + w.normobjekt.baujahr"></span>
                    <span x-show="w.normobjekt.wohnflaeche_m2" x-text="' · ' + w.normobjekt.wohnflaeche_m2 + ' m² Wohnfläche'"></span>
                    <span x-show="w.normobjekt.grundstueck_m2" x-text="' · ' + w.normobjekt.grundstueck_m2 + ' m² Grundstück'"></span>
                    <span x-show="w.normobjekt.anbauweise" x-text="' · ' + w.normobjekt.anbauweise"></span>
                    <span x-show="w.normobjekt.wohnungen" x-text="' · ' + w.normobjekt.wohnungen + ' Wohnungen im Haus'"></span>
                    <span x-show="w.wohnlage" x-text="' · Wohnlage ' + w.wohnlage"></span>
                    <a x-show="w.doku_url" :href="w.doku_url" target="_blank" rel="noopener" class="ml-1 text-blue-600 hover:underline">Umrechnung ↗</a>
                </td>
            </tr>
        </template>
    </tbody>
</table>
<p class="mt-3 text-xs text-gray-500">
    Stichtag <span x-text="d.stichtag"></span><span x-show="d.gutachterausschuss" x-text="' · ' + d.gutachterausschuss"></span>.
    Der Richtwert gilt für das beschriebene Normobjekt; Abweichungen (Baujahr, Größe, Zustand, Lage) werden mit den Umrechnungskoeffizienten des Gutachterausschusses angepasst. Kein Verkehrswert.
</p>
```

`redat/templates/report/_irw.html`:

```html
{% set w = d.get("werte") or [] %}
{% if w %}
<table>
  <thead><tr><th>Teilmarkt</th><th class="num">€/m² Wohnfläche</th><th>Normobjekt</th></tr></thead>
  <tbody>
  {% for x in w %}
    {% set n = x.get("normobjekt") or {} %}
    <tr>
      <td class="strong">{{ x.get("teilmarkt_label") or "—" }}</td>
      <td class="num">{{ (x.eur_m2|fmt_int ~ " €/m²") if x.get("eur_m2") is not none else "—" }}</td>
      <td class="xs">{% if n.get("baujahr") %}Baujahr {{ n.baujahr }}{% endif %}{% if n.get("wohnflaeche_m2") %} · {{ n.wohnflaeche_m2 }} m² Wohnfläche{% endif %}{% if n.get("grundstueck_m2") %} · {{ n.grundstueck_m2 }} m² Grundstück{% endif %}{% if n.get("anbauweise") %} · {{ n.anbauweise }}{% endif %}{% if n.get("wohnungen") %} · {{ n.wohnungen }} Wohnungen{% endif %}{% if x.get("wohnlage") %} · Wohnlage {{ x.wohnlage }}{% endif %}</td>
    </tr>
  {% endfor %}
  </tbody>
</table>
{% else %}
<p class="muted">Keine Immobilienrichtwerte für diesen Ort.</p>
{% endif %}
<p class="footnote">Immobilienrichtwerte der Gutachterausschüsse NRW{% if d.get("stichtag") %}, Stichtag {{ d.stichtag|fmt_date }}{% endif %}{% if d.get("gutachterausschuss") %} — {{ d.gutachterausschuss }}{% endif %}. Gilt für das Normobjekt; Umrechnung nach den örtlichen Fachinformationen. Kein Verkehrswert.</p>
```

Fixture `"irw"`:

```json
"irw": {"key": "irw", "tier": "parcel", "status": "ok", "message": null, "took_ms": 640,
  "source": "BORIS NRW — Immobilienrichtwerte der Gutachterausschüsse (€/m² Wohnfläche, Normobjekt)",
  "data": {"stichtag": "2026-01-01", "gutachterausschuss": "Der Gutachterausschuss für Grundstückswerte in der Stadt Essen",
           "werte": [
             {"teilmarkt": 1, "teilmarkt_label": "Eigentumswohnungen", "eur_m2": 2800, "stichtag": "2026-01-01", "ortsteil": "Rüttenscheid", "plz": "45131", "wohnlage": null, "gutachterausschuss": "Der Gutachterausschuss für Grundstückswerte in der Stadt Essen", "normobjekt": {"baujahr": "1962", "wohnflaeche_m2": "69", "grundstueck_m2": null, "anbauweise": null, "wohnungen": "7-12"}, "doku_url": "https://www.boris.nrw.de/borisfachdaten/lgd/irw/2026/LGDIR_1_0510900_2026.pdf"},
             {"teilmarkt": 2, "teilmarkt_label": "Ein-/Zweifamilienhäuser (freistehend)", "eur_m2": 4400, "stichtag": "2026-01-01", "ortsteil": "Rüttenscheid", "plz": "45131", "wohnlage": null, "gutachterausschuss": "Der Gutachterausschuss für Grundstückswerte in der Stadt Essen", "normobjekt": {"baujahr": "1962", "wohnflaeche_m2": "200", "grundstueck_m2": "700", "anbauweise": null, "wohnungen": null}, "doku_url": "https://www.boris.nrw.de/borisfachdaten/lgd/irw/2026/LGDIR_2_0510900_2026.pdf"},
             {"teilmarkt": 3, "teilmarkt_label": "Reihen-/Doppelhäuser", "eur_m2": 3950, "stichtag": "2026-01-01", "ortsteil": "Rüttenscheid", "plz": "45131", "wohnlage": null, "gutachterausschuss": "Der Gutachterausschuss für Grundstückswerte in der Stadt Essen", "normobjekt": {"baujahr": "1962", "wohnflaeche_m2": "130", "grundstueck_m2": "300", "anbauweise": "Doppelhaushälfte", "wohnungen": null}, "doku_url": "https://www.boris.nrw.de/borisfachdaten/lgd/irw/2026/LGDIR_3_0510900_2026.pdf"}]}}
```

- [ ] **Step 5: Run the whole suite**

Run: `.venv/bin/python -m pytest -q` → green.

- [ ] **Step 6: Commit**

```bash
git add redat/sources/irw.py redat/templates/analysis/_irw.html redat/templates/report/_irw.html redat/core redat/report/builder.py tests/
git commit -m "feat(irw): Immobilienrichtwerte card from BORIS NRW WMS"
```

---

### Task 6: Bauleitplanung Essen — Satzungen und Sanierungsgebiete

**Files:**
- Modify: `redat/sources/planning_essen.py` (`_query` gains `base`, two new queries, two new keys)
- Modify: `redat/core/sections.py` (`_ESSEN_LISTS`, `cache_version=2`)
- Test: `tests/test_planning_essen.py` (new), `tests/test_analysis_sections.py`

**Interfaces:**
- Produces: `get_planning_signals(...)` result gains `satzung: [{"nr", "name", "date", "link"}]` and `sanierung: [{"name", "plan_type"}]` (`name` = ORT, `plan_type` = ART); `planning_essen._query(layer, lat, lon, out_fields, record_count=25, base=PB_BASE)`; `SANIERUNG_BASE` constant.

- [ ] **Step 1: Write the failing tests**

`tests/test_planning_essen.py`:

```python
from redat.sources import planning_essen as pe


def stub(monkeypatch, responses: dict):
    calls = []

    def fake(layer, lat, lon, out_fields, record_count=25, base=pe.PB_BASE):
        calls.append((base, layer, out_fields))
        return {"features": [{"attributes": a} for a in responses.get((base, layer), [])]}
    monkeypatch.setattr(pe, "_query", fake)
    return calls


def test_satzung_and_sanierung_are_returned(monkeypatch):
    calls = stub(monkeypatch, {
        (pe.PB_BASE, pe.L_SATZUNG): [{"NR": "S22", "NAME": "Gestaltungssatzung  und Erhaltungssatzung  Langenbrahm - Siedlung vom 07.11.1980",
                                      "DATUM": "07.11.1980", "PLANID": "DE_05113000_S22_0_2", "BEGRUNDURL": "", "ERKLAERURL": "https://e/s22.pdf"}],
        (pe.SANIERUNG_BASE, 0): [{"ART": "Sanierung abgeschlossen, Ausgleichsbetrag", "ORT": "Werden"}],
    })
    d = pe.get_planning_signals(51.39, 7.00)
    assert d["ok"] and d["found"]
    assert d["satzung"] == [{"nr": "S22", "name": "Gestaltungssatzung und Erhaltungssatzung Langenbrahm - Siedlung vom 07.11.1980",
                             "date": "07.11.1980", "plan_id": "DE_05113000_S22_0_2", "link": {"label": "Satzung (PDF)", "url": "https://e/s22.pdf"}}]
    assert d["sanierung"] == [{"name": "Werden", "plan_type": "Sanierung abgeschlossen, Ausgleichsbetrag"}]
    assert (pe.SANIERUNG_BASE, 0, "ART,ORT") in calls and (pe.PB_BASE, pe.L_SATZUNG, "NR,NAME,DATUM,PLANID,BEGRUNDURL,ERKLAERURL") in calls


def test_nothing_found(monkeypatch):
    stub(monkeypatch, {})
    d = pe.get_planning_signals(51.39, 7.00)
    assert d["ok"] and not d["found"] and d["satzung"] == [] and d["sanierung"] == []
```

Add to `tests/test_analysis_sections.py`:

```python
def test_planning_essen_includes_satzung_and_sanierung(monkeypatch):
    from redat.sources import planning_essen
    monkeypatch.setattr(planning_essen, "get_planning_signals", lambda lat, lon: {
        "ok": True, "found": True, "bplan": [], "vhbplan": [], "veraenderungssperre": [], "aufstellungsbeschluss": [],
        "auslegungsbeschluss": [], "aufhebungsbeschluss": [],
        "satzung": [{"nr": "S22", "name": "Erhaltungssatzung Langenbrahm", "date": "07.11.1980", "link": {"label": "Satzung (PDF)", "url": "https://e/s22.pdf"}}],
        "sanierung": [{"name": "Werden", "plan_type": "Sanierung abgeschlossen, Ausgleichsbetrag"}]})
    d = S._fetch_planning_essen(CTX)
    assert d["items"] == [
        {"category": "Satzung", "name": "S22 Erhaltungssatzung Langenbrahm", "link": {"label": "Satzung (PDF)", "url": "https://e/s22.pdf"}},
        {"category": "Sanierungsgebiet", "name": "Werden (Sanierung abgeschlossen, Ausgleichsbetrag)", "link": None},
    ]
    assert S.SECTIONS["planning_essen"].cache_version == 2
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_planning_essen.py tests/test_analysis_sections.py -k "planning" -q`
Expected: `AttributeError: … has no attribute 'L_SATZUNG'` / `SANIERUNG_BASE`; cache_version 1 ≠ 2.

- [ ] **Step 3: Implement**

In `redat/sources/planning_essen.py`:

```python
SANIERUNG_BASE = "https://geo.essen.de/arcgis/rest/services/essen/Sanierung_Untersuchung/MapServer"
L_SATZUNG = 3          # "Sonstige Satzungen": Gestaltungs-/Erhaltungssatzungen, Vorkaufsrechtssatzungen
L_SANIERUNG = 0        # Sanierung_Untersuchung: ART ∈ Sanierung | Sanierung abgeschlossen, Ausgleichsbetrag | Untersuchung; ORT
```

Change `_query` signature to `def _query(layer: int, lat: float, lon: float, out_fields: str, record_count: int = 25, base: str = PB_BASE) -> dict:` and build `url = f"{base}/{layer}/query"`. Add a link helper and the two queries inside `get_planning_signals` (before `found = …`):

```python
def _satzung_link(item: dict[str, Any]) -> dict[str, Any]:
    """Move the ERKLAERURL/BEGRUNDURL columns into the card's `link` shape (Erklärung preferred)."""
    erklaer, begruend = item.pop("erklaer_url", None), item.pop("begruend_url", None)
    url = erklaer or begruend
    if url:
        item["link"] = {"label": "Satzung (PDF)", "url": url}
    if item.get("name"):
        item["name"] = re.sub(r"\s+", " ", item["name"]).strip()
    return item
```

```python
        satzung = [_satzung_link(it) for it in _simplify_features(
            _query(L_SATZUNG, lat, lon, out_fields="NR,NAME,DATUM,PLANID,BEGRUNDURL,ERKLAERURL"),
            {"NR": "nr", "NAME": "name", "DATUM": "date", "PLANID": "plan_id", "BEGRUNDURL": "begruend_url", "ERKLAERURL": "erklaer_url"})]

        sanierung = _simplify_features(
            _query(L_SANIERUNG, lat, lon, out_fields="ART,ORT", base=SANIERUNG_BASE),
            {"ORT": "name", "ART": "plan_type"},
        )
```

(`import re` at the top.) Extend `found = any([bplan, vhbp, vsperre, aufstellung, auslegung, aufhebung, satzung, sanierung])` and the returned dict with `"satzung": satzung, "sanierung": sanierung`. Note `_simplify_features` skips blank ORT/ART values already.

In `redat/core/sections.py` extend `_ESSEN_LISTS`:

```python
    ("satzung", "Satzung"),
    ("sanierung", "Sanierungsgebiet"),
```

and give the section `cache_version=2`:

```python
    Section("planning_essen", "Bauleitplanung Essen", "🏗️", 30, "geo.essen.de — Planen und Bauen · Satzungen · Sanierungsgebiete", _fetch_planning_essen,
            cache_version=2),
```

- [ ] **Step 4: Run the suite**

Run: `.venv/bin/python -m pytest -q` → green.

- [ ] **Step 5: Commit**

```bash
git add redat/sources/planning_essen.py redat/core/sections.py tests/test_planning_essen.py tests/test_analysis_sections.py
git commit -m "feat(planning-essen): Erhaltungs-/Gestaltungssatzungen and Sanierungsgebiete"
```

---

### Task 7: Bauleitplanung Bochum — Stadterneuerungsgebiete

**Files:**
- Modify: `redat/sources/planning_bochum.py`
- Modify: `redat/core/sections.py` (`cache_version=2`, source string)
- Test: `tests/test_planning_bochum.py` (new), `tests/test_analysis_sections.py`

**Interfaces:**
- Produces: `planning_bochum._arcgis_query(layer: int, lat, lon) -> dict` (HTTP point), `planning_bochum.stadterneuerung(lat, lon) -> tuple[list[dict], dict]` (items, errors); `get_bochum_bplan_outline` result gains items with `plan_type` "Stadterneuerungsgebiet" / "Stadtumbausatzung" / "Stadtteilentwicklungskonzept" and a top-level `errors` dict.

- [ ] **Step 1: Write the failing tests**

`tests/test_planning_bochum.py`:

```python
from redat.sources import planning_bochum as pb


def stub(monkeypatch, by_layer: dict):
    def fake(layer, lat, lon):
        v = by_layer.get(layer, [])
        if isinstance(v, Exception):
            raise v
        return {"features": [{"attributes": a} for a in v]}
    monkeypatch.setattr(pb, "_arcgis_query", fake)


def test_stadterneuerung_items(monkeypatch):
    stub(monkeypatch, {
        7: [{"Titel": "ISEK Hamme", "Fördergebi": "Soziale Stadt Hamme", "Förderprog": "Sozialer  Zusammenhalt",
             "Homepage": "https://www.bochum.de/…/Stadterneuerung-Hamme", "Start": 0, "Ende": 2028, "Kategorie": "Stadterneuerungsgebiet"}],
        16: [{"Name": "STEK Wattenscheid-Mitte"}],
        20: [{"FID": 3, "ID": 1}],
    })
    items, errors = pb.stadterneuerung(51.4818, 7.2162)
    assert errors == {}
    assert items == [
        {"official_name": "ISEK Hamme", "plan_type": "Stadterneuerungsgebiet", "legal_status": "Sozialer Zusammenhalt, bis 2028",
         "plan_link": "https://www.bochum.de/…/Stadterneuerung-Hamme"},
        {"official_name": "STEK Wattenscheid-Mitte", "plan_type": "Stadtteilentwicklungskonzept"},
        {"official_name": "1036 S - Laer West", "plan_type": "Stadtumbausatzung"},
    ]


def test_layer_failure_is_isolated(monkeypatch):
    stub(monkeypatch, {8: RuntimeError("timeout"), 9: [{"Titel": "Stadtumbau Laer", "Förderprog": "Stadtumbau West", "Ende": 0, "Kategorie": "Stadterneuerungsgebiet"}]})
    items, errors = pb.stadterneuerung(51.4818, 7.2162)
    assert [i["official_name"] for i in items] == ["Stadtumbau Laer"] and items[0]["legal_status"] == "Stadtumbau West"
    assert errors == {8: "timeout"}


def test_outline_merges_stadterneuerung(monkeypatch):
    monkeypatch.setattr(pb, "_wms_getfeatureinfo_html", lambda lat, lon: "<html></html>")
    stub(monkeypatch, {7: [{"Titel": "ISEK Hamme", "Kategorie": "Stadterneuerungsgebiet", "Ende": 2028}]})
    d = pb.get_bochum_bplan_outline(51.4818, 7.2162)
    assert d["ok"] and d["found"] and d["items"][0]["official_name"] == "ISEK Hamme" and d["errors"] == {}
```

Add to `tests/test_analysis_sections.py`:

```python
def test_planning_bochum_cache_version_bumped():
    assert S.SECTIONS["planning_bochum"].cache_version == 2
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_planning_bochum.py -q`
Expected: `AttributeError: … no attribute '_arcgis_query'`.

- [ ] **Step 3: Implement**

Add to `redat/sources/planning_bochum.py` (imports: `import httpx`, `from redat.http import headers`, `import logging`):

```python
STADTPLANUNG_URL = "https://geoservicekkm.bochum.de/arcgis/rest/services/maponline/Stadtplanung/MapServer"
# layer id -> plan_type. Layers 7–11 carry Titel/Förderprog/Ende/Homepage (ISEK Hamme, ISEK Innenstadt,
# Stadtumbau Laer, Wattenscheid, WLAB); 16 = Gebiete der Stadtteilentwicklungskonzepte (Name);
# 20 = Stadtumbausatzung "1036 S - Laer West" (no name field). Verified 2026-09-05.
STADTERNEUERUNG_LAYERS = {7: "Stadterneuerungsgebiet", 8: "Stadterneuerungsgebiet", 9: "Stadterneuerungsgebiet",
                          10: "Stadterneuerungsgebiet", 11: "Stadterneuerungsgebiet",
                          16: "Stadtteilentwicklungskonzept", 20: "Stadtumbausatzung"}
_FIXED_NAMES = {20: "1036 S - Laer West"}
_ARCGIS_TIMEOUT_S = 20


def _arcgis_query(layer: int, lat: float, lon: float) -> dict:
    """Point query on one Stadtplanung layer — HTTP/monkeypatch point."""
    params = {"f": "json", "where": "1=1", "geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint", "inSR": 4326,
              "spatialRel": "esriSpatialRelIntersects", "outFields": "*", "returnGeometry": "false", "resultRecordCount": 10}
    resp = httpx.get(f"{STADTPLANUNG_URL}/{layer}/query", params=params, timeout=_ARCGIS_TIMEOUT_S, headers=headers())
    resp.raise_for_status()
    return resp.json()


def _erneuerung_item(layer: int, a: dict[str, Any]) -> dict[str, Any]:
    plan_type = STADTERNEUERUNG_LAYERS[layer]
    name = _FIXED_NAMES.get(layer) or a.get("Titel") or a.get("Name") or plan_type
    item: dict[str, Any] = {"official_name": re.sub(r"\s+", " ", str(name)).strip(), "plan_type": a.get("Kategorie") or plan_type}
    status = [re.sub(r"\s+", " ", str(a.get("Förderprog") or "")).strip()]
    if a.get("Ende"):
        status.append(f"bis {a['Ende']}")
    status = ", ".join(s for s in status if s)
    if status:
        item["legal_status"] = status
    if a.get("Homepage"):
        item["plan_link"] = a["Homepage"]
    return item


def stadterneuerung(lat: float, lon: float) -> tuple[list[dict[str, Any]], dict[int, str]]:
    """Stadterneuerungs-/Stadtumbau areas at the point; one failing layer never hides the others."""
    items, errors = [], {}
    for layer in STADTERNEUERUNG_LAYERS:
        try:
            for f in _arcgis_query(layer, lat, lon).get("features") or []:
                items.append(_erneuerung_item(layer, f.get("attributes") or {}))
        except Exception as e:  # noqa: BLE001
            logger.warning("Bochum Stadtplanung layer %s failed: %s", layer, e)
            errors[layer] = str(e)
    return items, errors
```

and in `get_bochum_bplan_outline`, after `items = _extract_blocks(html)`:

```python
        extra, errors = stadterneuerung(lat, lon)
        items = items + extra
        return {
            "ok": True,
            "found": bool(items),
            "items": items,
            "errors": errors,
            "source": "RVR INSPIRE bodennutzung/metropoleruhr (WMS GetFeatureInfo bplan) · Stadt Bochum Stadtplanung (ArcGIS REST)",
        }
```

`redat/core/sections.py`:

```python
    Section("planning_bochum", "Bauleitplanung Bochum", "🏗️", 30, "RVR INSPIRE Bauleitplanung (WMS GetFeatureInfo) · Stadt Bochum, Stadterneuerung", _fetch_planning_bochum,
            cache_version=2),
```

(`_fetch_planning_bochum` needs no change: it already renders `official_name`, `plan_type`, `legal_status`, `plan_link`.)

- [ ] **Step 4: Run the suite**

Run: `.venv/bin/python -m pytest -q` → green.

- [ ] **Step 5: Commit**

```bash
git add redat/sources/planning_bochum.py redat/core/sections.py tests/test_planning_bochum.py tests/test_analysis_sections.py
git commit -m "feat(planning-bochum): Stadterneuerungsgebiete, Stadtumbausatzung and STEK areas"
```

---

### Task 8: `scripts/build_schulen.py` — NRW schools grid with Sozialindex

**Files:**
- Create: `scripts/build_schulen.py`, `redat/data/schulen_nrw.json.gz` (build output, committed)
- Test: `tests/test_build_schulen.py`

**Interfaces:**
- Produces: `redat/data/schulen_nrw.json.gz` = `{"schuljahr": "2025/26", "built": "YYYY-MM-DD", "schools": [{"nr", "name", "kurzname", "form", "lat", "lon", "adresse", "plz", "ort", "schueler", "sozialindex"}]}`; script functions `read_sozialindex(fh) -> dict[str, int]`, `rows_from_gdf(gdf) -> list[dict]`, `merge(rows, index) -> list[dict]`, `main()`.

- [ ] **Step 1: Write the failing tests**

`tests/test_build_schulen.py`:

```python
"""scripts/build_schulen.py — Sozialindex CSV + Schulen shapefile → schools list (unit tests, in-memory)."""
import importlib.util
import io
from pathlib import Path

import geopandas as gpd
from shapely.geometry import Point

_spec = importlib.util.spec_from_file_location("build_schulen", Path(__file__).resolve().parent.parent / "scripts" / "build_schulen.py")
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)

CSV = ("Schulnummer;Kurzbezeichnung;Bezirksregierung;Kreis;Gemeinde;Sozialindexstufe\n"
       "100011;Haan, GE Walder Straße;BR Düsseldorf;Kreis Mettmann;Haan;4\n"
       "102416;Essen, GG Käthe-Kollwitz;BR Düsseldorf;Stadt Essen;Essen;\n"
       "100000;Bochum, WBK KOL Studienkolleg;BR Arnsberg;Stadt Bochum;Bochum;9\n")


def test_read_sozialindex_skips_blank():
    assert mod.read_sozialindex(io.StringIO(CSV)) == {"100011": 4, "100000": 9}


def test_rows_from_gdf_reprojects_and_parses_schueler():
    gdf = gpd.GeoDataFrame(
        {"Schulnumme": ["102416", "100000"], "Schulform": ["Grundschule", "Weiterbildungskolleg"],
         "Name": ["Käthe-Kollwitz-Schule", "Studienkolleg"], "Kurzname": ["Essen, GG KKS", "Bochum, WBK"],
         "Adresse": ["Christinenstr. 4", "Girondelle 80"], "Postleitza": ["45131", "44799"], "Ort": ["Essen", "Bochum"],
         "Schueler": ["250", "0"]},
        geometry=[Point(361370.16, 5699486.35), Point(375000.0, 5702000.0)], crs="EPSG:25832")   # first = 7.0058 E, 51.4296 N
    rows = mod.rows_from_gdf(gdf)
    assert rows[0]["nr"] == "102416" and rows[0]["form"] == "Grundschule" and rows[0]["schueler"] == 250
    assert abs(rows[0]["lat"] - 51.4296) < 0.0001 and abs(rows[0]["lon"] - 7.0058) < 0.0001
    assert rows[1]["schueler"] is None       # "0" means "not reported"
    assert rows[0]["adresse"] == "Christinenstr. 4" and rows[0]["plz"] == "45131" and rows[0]["ort"] == "Essen"


def test_merge_attaches_index_or_none():
    rows = [{"nr": "100011", "name": "GE Haan"}, {"nr": "102416", "name": "KKS"}]
    out = mod.merge(rows, {"100011": 4})
    assert out[0]["sozialindex"] == 4 and out[1]["sozialindex"] is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_build_schulen.py -q`
Expected: FAIL — file `scripts/build_schulen.py` does not exist.

- [ ] **Step 3: Implement the script**

`scripts/build_schulen.py`:

```python
"""Build redat/data/schulen_nrw.json.gz — every NRW school with coordinates, Schulform and Sozialindex.

Inputs (both open data, dl-de/by-2-0):
- Schulstandorte in NRW als Shape (Geobasis/Schulministerium, point geometry EPSG:25832, DBF fields
  Schulnumme, Schulform, Name, Kurzname, Adresse, Postleitza, Ort, Schueler, Rufnummer, Email):
  https://www.opengeodata.nrw.de/produkte/bildung_wissenschaft/schulen/SchulenNRW_EPSG25832_Shape.zip
- Schulliste mit Sozialindexstufe (Schulministerium NRW, ';'-separated, **cp850** (DOS codepage — cp1252
  fails on byte 0x81 in "Düsseldorf", verified 2026-09-05); columns
  Schulnummer;Kurzbezeichnung;Bezirksregierung;Kreis;Gemeinde;Sozialindexstufe — Stufe 1 = geringe,
  9 = hohe soziale Herausforderungen, blank for schools without an index):
  https://www.schulministerium.nrw/system/files/media/document/file/schulliste_sj_25_26_open_data.csv

Usage:
    .venv/bin/python scripts/build_schulen.py --shape /tmp/SchulenNRW_EPSG25832_Shape.zip \
        --sozialindex /tmp/schulliste_sj_25_26_open_data.csv --schuljahr 2025/26
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
from datetime import date
from pathlib import Path
from typing import IO, Optional

import geopandas as gpd

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "redat" / "data" / "schulen_nrw.json.gz"


def read_sozialindex(fh: IO[str]) -> dict[str, int]:
    """Schulnummer → Sozialindexstufe (1–9); rows without a Stufe are skipped."""
    out = {}
    for row in csv.DictReader(fh, delimiter=";"):
        nr, stufe = (row.get("Schulnummer") or "").strip(), (row.get("Sozialindexstufe") or "").strip()
        if nr and stufe.isdigit():
            out[nr] = int(stufe)
    return out


def _int_or_none(v) -> Optional[int]:
    try:
        n = int(float(str(v).strip()))
    except (TypeError, ValueError):
        return None
    return n or None   # the shapefile writes 0 for "not reported"


def rows_from_gdf(gdf: gpd.GeoDataFrame) -> list[dict]:
    g = gdf.to_crs("EPSG:4326")
    rows = []
    for _, r in g.iterrows():
        if r.geometry is None or r.geometry.is_empty:
            continue
        rows.append({
            "nr": str(r["Schulnumme"]).strip(), "name": str(r.get("Name") or "").strip(), "kurzname": str(r.get("Kurzname") or "").strip(),
            "form": str(r.get("Schulform") or "").strip(), "lat": round(float(r.geometry.y), 6), "lon": round(float(r.geometry.x), 6),
            "adresse": str(r.get("Adresse") or "").strip() or None, "plz": str(r.get("Postleitza") or "").strip() or None,
            "ort": str(r.get("Ort") or "").strip() or None, "schueler": _int_or_none(r.get("Schueler")),
        })
    return rows


def merge(rows: list[dict], index: dict[str, int]) -> list[dict]:
    return [{**r, "sozialindex": index.get(r["nr"])} for r in rows]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--shape", required=True, help="SchulenNRW_EPSG25832_Shape.zip")
    ap.add_argument("--sozialindex", required=True, help="schulliste_sj_25_26_open_data.csv")
    ap.add_argument("--schuljahr", default="2025/26")
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args()
    with open(a.sozialindex, encoding="cp850", newline="") as fh:
        index = read_sozialindex(fh)
    rows = merge(rows_from_gdf(gpd.read_file(f"zip://{a.shape}")), index)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(a.out, "wt", encoding="utf-8") as fh:
        json.dump({"schuljahr": a.schuljahr, "built": date.today().isoformat(), "schools": rows}, fh, ensure_ascii=False, separators=(",", ":"))
    with_index = sum(1 for r in rows if r["sozialindex"] is not None)
    print(f"wrote {a.out} — {len(rows)} schools, {with_index} with Sozialindex")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests, then build the real file**

Run: `.venv/bin/python -m pytest tests/test_build_schulen.py -q` → `3 passed`.

```bash
curl -sSL -o /tmp/schulen.zip https://www.opengeodata.nrw.de/produkte/bildung_wissenschaft/schulen/SchulenNRW_EPSG25832_Shape.zip
curl -sSL -o /tmp/schulliste.csv https://www.schulministerium.nrw/system/files/media/document/file/schulliste_sj_25_26_open_data.csv
.venv/bin/python scripts/build_schulen.py --shape /tmp/schulen.zip --sozialindex /tmp/schulliste.csv
ls -la redat/data/schulen_nrw.json.gz      # verified 2026-09-05: 5,427 schools, 4,136 with Sozialindex, ~260 KB; Schulform values include
                                           # Grundschule 2819, Gymnasium 630, Förderschule 513, Gesamtschule 381, Realschule 363, Berufskolleg 354,
                                           # Hauptschule 157, Sekundarschule 111, Waldorfschule 56, Weiterbildungskolleg 36, "Primus (Schulversuch)" 5, Volksschule 2
```

- [ ] **Step 5: Commit**

```bash
git add scripts/build_schulen.py tests/test_build_schulen.py redat/data/schulen_nrw.json.gz
git commit -m "feat(schulen): build script and NRW schools grid with Sozialindex"
```

---

### Task 9: `schulen` card — nearest schools per form, Sozialindex, Bochum Grundschulbezirk

**Files:**
- Create: `redat/sources/schulen.py`, `redat/templates/analysis/_schulen.html`, `redat/templates/report/_schulen.html`
- Modify: `redat/core/sections.py`, `redat/core/tiers.py`, `redat/core/sources_meta.py`, `redat/report/builder.py`
- Modify: `tests/fixtures/report_envelopes.json`, `tests/test_analysis_sections.py`, `tests/test_tiers.py`, `tests/test_report_render.py`
- Test: `tests/test_schulen.py`

**Interfaces:**
- Consumes: `redat/data/schulen_nrw.json.gz` (Task 8)
- Produces: `schulen.lookup(lat, lon) -> Optional[dict]` (None when the grid file is missing) with keys `radius_m`, `schuljahr`, `grundschulen`, `weiterfuehrend`, `foerderschulen` (lists of `{"name","form","distance_m","sozialindex","sozialindex_label","schueler","adresse","plz","ort"}`), `counts`, `grundschulbezirk` (`{"schule","kapazitaet"}`|None), `grundschulbezirk_error`, `rating`, `rating_color`; `schulen._load() -> Optional[dict]` (lru_cached loader, monkeypatch point for the grid); `schulen._bochum_grundschulbezirk(lat, lon) -> Optional[dict]` (HTTP point); `schulen.sozialindex_label(stufe) -> Optional[str]`. Section key `schulen` (area) placed right after `amenities`.

- [ ] **Step 1: Write the failing tests**

`tests/test_schulen.py`:

```python
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
```

Registry/tier/render updates: insert `"schulen"` after `"amenities"` in `test_registry_keys_and_order`; add `"schulen"` to the list in `test_tiers.py::test_every_section_has_a_tier` (area — not in the parcel set); add `"schulen": ["Käthe-Kollwitz-Schule", "Stufe 3 von 9", "Goetheschule"],` to the render checks; and to `tests/test_analysis_sections.py`:

```python
def test_schulen_passthrough_and_empty(monkeypatch):
    from redat.sources import schulen
    monkeypatch.setattr(schulen, "lookup", lambda lat, lon: {"radius_m": 2000, "grundschulen": []})
    assert S._fetch_schulen(CTX)["radius_m"] == 2000
    monkeypatch.setattr(schulen, "lookup", lambda lat, lon: None)
    with pytest.raises(Empty):
        S._fetch_schulen(CTX)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_schulen.py -q` → `ModuleNotFoundError: redat.sources.schulen`.

- [ ] **Step 3: Implement `schulen.py`**

```python
"""Schulen & Sozialindex — nearest schools per Schulform from the NRW school list.

Data: redat/data/schulen_nrw.json.gz, built by scripts/build_schulen.py from the open "Schulstandorte in
NRW" shapefile (coordinates, Schulform, Schülerzahl) and the Schulministerium's Schulliste with the
schulscharfe Sozialindex (Stufe 1 = geringe … 9 = hohe soziale Herausforderungen; explicitly *not* a
quality ranking — it steers resources). Bochum publishes Grundschulbezirke (Einzugsbereich + Kapazität)
on its ArcGIS server; Essen has none (freie Grundschulwahl). `_load` reads the grid (monkeypatch point),
`_bochum_grundschulbezirk` is the single HTTP call (monkeypatch point).
"""
from __future__ import annotations

import gzip
import json
import logging
import math
from functools import lru_cache
from pathlib import Path
from typing import Optional

import httpx

from redat.http import headers

logger = logging.getLogger(__name__)

GRID_PATH = Path(__file__).resolve().parent.parent / "data" / "schulen_nrw.json.gz"
RADIUS_M = 2000
PRIMAR_KEYWORDS = ("grundschule", "primus", "volksschule")   # matched case-insensitively: "Primus (Schulversuch)" is Klasse 1–10
SEK_FORMS = ("Gymnasium", "Gesamtschule", "Realschule", "Hauptschule", "Sekundarschule", "Gemeinschaftsschule", "Waldorfschule")
FOERDER_KEYWORD = "Förderschule"
_MAX_GRUNDSCHULEN = 3
_MAX_FOERDER = 2
BOCHUM_BBOX = (7.10, 51.40, 7.35, 51.53)   # lon_min, lat_min, lon_max, lat_max
BOCHUM_GSB_URL = "https://geoservicekkm.bochum.de/arcgis/rest/services/maponline/Grundschulen/MapServer/3/query"
_TIMEOUT_S = 15


@lru_cache(maxsize=1)
def _load() -> Optional[dict]:
    try:
        with gzip.open(GRID_PATH, "rt", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _dist_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Equirectangular metres — fine for a 2 km radius."""
    k = math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot((lat2 - lat1) * 111_195, (lon2 - lon1) * 111_195 * k)


def sozialindex_label(stufe: Optional[int]) -> Optional[str]:
    if stufe is None:
        return None
    band = "geringe" if stufe <= 3 else "mittlere" if stufe <= 6 else "hohe"
    return f"Stufe {stufe} von 9 ({band} soziale Herausforderungen)"


def _group(form: str) -> Optional[str]:
    if any(k in form.lower() for k in PRIMAR_KEYWORDS):
        return "grundschulen"
    if FOERDER_KEYWORD in form:
        return "foerderschulen"
    if any(form.startswith(f) for f in SEK_FORMS):
        return "weiterfuehrend"
    return None


def _item(s: dict, dist: float) -> dict:
    return {"name": s.get("name") or s.get("kurzname") or "—", "form": s.get("form"), "distance_m": round(dist),
            "sozialindex": s.get("sozialindex"), "sozialindex_label": sozialindex_label(s.get("sozialindex")),
            "schueler": s.get("schueler"), "adresse": s.get("adresse"), "plz": s.get("plz"), "ort": s.get("ort")}


def _bochum_grundschulbezirk(lat: float, lon: float) -> Optional[dict]:
    """Bochum Grundschulbezirk containing the point — HTTP/monkeypatch point."""
    params = {"f": "json", "where": "1=1", "geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint", "inSR": 4326,
              "spatialRel": "esriSpatialRelIntersects", "outFields": "SCHULNAME,KAP_20_21", "returnGeometry": "false"}
    resp = httpx.get(BOCHUM_GSB_URL, params=params, timeout=_TIMEOUT_S, headers=headers())
    resp.raise_for_status()
    return parse_grundschulbezirk(resp.json())


def parse_grundschulbezirk(payload: dict) -> Optional[dict]:
    feats = payload.get("features") or []
    if not feats:
        return None
    a = feats[0].get("attributes") or {}
    return {"schule": a.get("SCHULNAME"), "kapazitaet": a.get("KAP_20_21")}


def _in_bochum(lat: float, lon: float) -> bool:
    lon_min, lat_min, lon_max, lat_max = BOCHUM_BBOX
    return lon_min <= lon <= lon_max and lat_min <= lat <= lat_max


def _rate(grundschulen: list[dict]) -> tuple[str, str]:
    if grundschulen and grundschulen[0]["distance_m"] <= 1000:
        return "Grundschule fußläufig", "green"
    if grundschulen:
        return "Grundschule im Umkreis von 2 km", "yellow"
    return "Keine Grundschule im Umkreis von 2 km", "orange"


def lookup(lat: float, lon: float) -> Optional[dict]:
    grid = _load()
    if not grid:
        return None
    groups: dict[str, list[tuple[float, dict]]] = {"grundschulen": [], "weiterfuehrend": [], "foerderschulen": []}
    for s in grid.get("schools") or []:
        g = _group(s.get("form") or "")
        if g is None:
            continue
        dist = _dist_m(lat, lon, s["lat"], s["lon"])
        if dist <= RADIUS_M:
            groups[g].append((dist, s))
    for g in groups.values():
        g.sort(key=lambda t: t[0])
    grundschulen = [_item(s, d) for d, s in groups["grundschulen"][:_MAX_GRUNDSCHULEN]]
    seen_forms, weiterfuehrend = set(), []
    for d, s in groups["weiterfuehrend"]:
        form = next((f for f in SEK_FORMS if (s.get("form") or "").startswith(f)), s.get("form"))
        if form in seen_forms:
            continue
        seen_forms.add(form)
        weiterfuehrend.append(_item(s, d))
    foerder = [_item(s, d) for d, s in groups["foerderschulen"][:_MAX_FOERDER]]

    bezirk, bezirk_error = None, None
    if _in_bochum(lat, lon):
        try:
            bezirk = _bochum_grundschulbezirk(lat, lon)
        except Exception as exc:  # noqa: BLE001 — Bochum down must not blank the card
            logger.warning("Bochum Grundschulbezirk: %s", exc)
            bezirk_error = str(exc)
    rating, color = _rate(grundschulen)
    return {
        "radius_m": RADIUS_M, "schuljahr": grid.get("schuljahr"),
        "grundschulen": grundschulen, "weiterfuehrend": weiterfuehrend, "foerderschulen": foerder,
        "counts": {k: len(v) for k, v in groups.items()},
        "grundschulbezirk": bezirk, "grundschulbezirk_error": bezirk_error,
        "rating": rating, "rating_color": color,
    }
```

- [ ] **Step 4: Registry, summary, partials, fixture**

`redat/core/sections.py` (area tier, after `_fetch_amenities`):

```python
def _fetch_schulen(ctx: Ctx) -> dict:
    from redat.sources import schulen

    d = schulen.lookup(ctx.lat, ctx.lon)
    if d is None:
        raise Empty("Schuldaten nicht verfügbar (redat/data/schulen_nrw.json.gz fehlt)")
    return d
```

Registry line, directly after `amenities`:

```python
    Section("schulen", "Schulen & Sozialindex", "🎒", 20,
            "Schulministerium NRW, Schulliste 2025/26 mit Sozialindex · Geobasis NRW Schulstandorte (dl-de/by-2-0) · Stadt Bochum, Grundschulbezirke", _fetch_schulen),
```

`tiers.py`: `"schulen": "area",`. `sources_meta.py`:

```python
    SourceMeta(("schulen",), "Schulstandorte NRW + Schulsozialindex", "Ministerium für Schule und Bildung NRW · Geobasis NRW · Stadt Bochum", "dl-de/by-2-0",
               "lokal: redat/data/schulen_nrw.json.gz (scripts/build_schulen.py) · Bochum ArcGIS Grundschulbezirke", "area", "jährlich (Schuljahr), Datei-Import"),
```

`builder.py`:

```python
def _s_schulen(d):
    rating, color = _rated(d)
    gs = (d.get("grundschulen") or [{}])[0]
    parts = []
    if gs.get("name"):
        parts.append(f"Grundschule {fmt_m(gs['distance_m'])}" + (f" (Sozialindex {gs['sozialindex']})" if gs.get("sozialindex") else ""))
    for w in (d.get("weiterfuehrend") or [])[:2]:
        parts.append(f"{w.get('form')} {fmt_m(w['distance_m'])}")
    return rating, color, " · ".join(parts) or None
```

with `"schulen": _s_schulen,` after `"amenities"` in `SUMMARY`.

`redat/templates/analysis/_schulen.html`:

```html
<div class="flex items-center gap-4">
    <span class="px-3 py-1 rounded-full font-bold" :class="$store.app.getAirQualityColor(d.rating_color)" x-text="d.rating"></span>
    <div class="text-sm text-gray-500">Schulen im Umkreis von <span x-text="d.radius_m / 1000"></span> km, Schuljahr <span x-text="d.schuljahr"></span></div>
</div>
<template x-for="[label, list] in [['Grundschulen', d.grundschulen], ['Weiterführende Schulen (je Schulform die nächste)', d.weiterfuehrend], ['Förderschulen', d.foerderschulen]]" :key="label">
    <div class="mt-4" x-show="list.length">
        <div class="text-sm font-semibold text-gray-900" x-text="label"></div>
        <ul class="mt-1 space-y-1 text-sm">
            <template x-for="(s, i) in list" :key="i">
                <li class="flex items-start gap-2">
                    <span class="text-gray-500 w-14 flex-shrink-0 text-right" x-text="$store.app.formatDistance(s.distance_m)"></span>
                    <span>
                        <span class="text-gray-900" x-text="s.name"></span>
                        <span class="text-gray-500" x-text="' · ' + s.form + (s.schueler ? ' · ' + s.schueler + ' Schüler' : '')"></span>
                        <span class="block text-xs text-gray-500" x-show="s.sozialindex_label" x-text="'Sozialindex ' + s.sozialindex_label"></span>
                    </span>
                </li>
            </template>
        </ul>
    </div>
</template>
<p class="mt-3 text-sm text-gray-600" x-show="!d.grundschulen.length && !d.weiterfuehrend.length && !d.foerderschulen.length">Keine Schule im Umkreis.</p>
<template x-if="d.grundschulbezirk">
    <p class="mt-3 text-sm text-gray-700">🏫 Bochumer Grundschulbezirk: <span class="font-medium" x-text="d.grundschulbezirk.schule"></span><span x-show="d.grundschulbezirk.kapazitaet" x-text="' (Kapazität ' + d.grundschulbezirk.kapazitaet + ' Plätze)'"></span></p>
</template>
<p class="mt-3 text-xs text-gray-500">
    Der schulscharfe Sozialindex NRW (1 = geringe, 9 = hohe soziale Herausforderungen) steuert die Ressourcenzuweisung und ist ausdrücklich kein Qualitätsurteil über die Schule.
    In Essen gilt freie Grundschulwahl; in Bochum entscheidet der Grundschulbezirk über den Anspruch auf einen Platz.
    <span x-show="d.grundschulbezirk_error"> · Grundschulbezirk Bochum nicht abrufbar</span>
</p>
```

`redat/templates/report/_schulen.html`:

```html
<div class="kpis">
  <div class="kpi">
    <div class="label">Schulen im Umkreis von {{ ((d.get("radius_m") or 2000) / 1000)|fmt_num(0) }} km</div>
    <div class="value"><span class="chip {{ rating_class(d.get('rating_color')) }}">{{ d.get("rating") or "—" }}</span></div>
  </div>
</div>
{% for label, key in [("Grundschulen", "grundschulen"), ("Weiterführende Schulen (je Schulform die nächste)", "weiterfuehrend"), ("Förderschulen", "foerderschulen")] %}
{% set list = d.get(key) or [] %}
{% if list %}
<h3>{{ label }}</h3>
<table>
  <thead><tr><th class="num">Abstand</th><th>Schule</th><th>Schulform</th><th class="num">Schüler</th><th>Sozialindex</th></tr></thead>
  <tbody>
  {% for s in list %}
    <tr>
      <td class="num">{{ (s.distance_m|fmt_m) if s.get("distance_m") is not none else "—" }}</td>
      <td>{{ s.get("name") or "—" }}</td>
      <td>{{ s.get("form") or "—" }}</td>
      <td class="num">{{ s.schueler|fmt_int if s.get("schueler") else "—" }}</td>
      <td>{{ s.get("sozialindex_label") or "—" }}</td>
    </tr>
  {% endfor %}
  </tbody>
</table>
{% endif %}
{% endfor %}
{% if d.get("grundschulbezirk") %}
<p>Bochumer Grundschulbezirk: <strong>{{ d.grundschulbezirk.get("schule") or "—" }}</strong>{% if d.grundschulbezirk.get("kapazitaet") %} (Kapazität {{ d.grundschulbezirk.kapazitaet }} Plätze){% endif %}</p>
{% endif %}
<p class="footnote">Schulliste NRW{% if d.get("schuljahr") %} {{ d.schuljahr }}{% endif %} mit schulscharfem Sozialindex (1 = geringe, 9 = hohe soziale Herausforderungen; kein Qualitätsurteil). Essen: freie Grundschulwahl; Bochum: Grundschulbezirke.</p>
```

Fixture `"schulen"`:

```json
"schulen": {"key": "schulen", "tier": "area", "status": "ok", "message": null, "took_ms": 21,
  "source": "Schulministerium NRW, Schulliste 2025/26 mit Sozialindex · Geobasis NRW Schulstandorte (dl-de/by-2-0) · Stadt Bochum, Grundschulbezirke",
  "data": {"radius_m": 2000, "schuljahr": "2025/26",
           "grundschulen": [{"name": "Käthe-Kollwitz-Schule", "form": "Grundschule", "distance_m": 330, "sozialindex": 3, "sozialindex_label": "Stufe 3 von 9 (geringe soziale Herausforderungen)", "schueler": 250, "adresse": "Christinenstr. 4", "plz": "45131", "ort": "Essen"}],
           "weiterfuehrend": [{"name": "Goetheschule", "form": "Gymnasium", "distance_m": 900, "sozialindex": 2, "sozialindex_label": "Stufe 2 von 9 (geringe soziale Herausforderungen)", "schueler": 900, "adresse": null, "plz": null, "ort": "Essen"}],
           "foerderschulen": [], "counts": {"grundschulen": 2, "weiterfuehrend": 3, "foerderschulen": 0},
           "grundschulbezirk": null, "grundschulbezirk_error": null, "rating": "Grundschule fußläufig", "rating_color": "green"}}
```

- [ ] **Step 5: Run the whole suite**

Run: `.venv/bin/python -m pytest -q` → green.

- [ ] **Step 6: Commit**

```bash
git add redat/sources/schulen.py redat/templates/analysis/_schulen.html redat/templates/report/_schulen.html redat/core redat/report/builder.py tests/
git commit -m "feat(schulen): nearest schools per Schulform with Sozialindex and Bochum Grundschulbezirk"
```

---

### Task 10: `scripts/build_unfallatlas.py` — accidents 2020–2025 cropped to Essen/Bochum

**Files:**
- Create: `scripts/build_unfallatlas.py`, `redat/data/unfallatlas_2020_2025.json.gz`
- Test: `tests/test_build_unfallatlas.py`

**Interfaces:**
- Produces: grid `{"years": [2020, …, 2025], "bbox": [6.85, 51.33, 7.40, 51.56], "fields": ["lat","lon","jahr","kat","typ","licht","rad","pkw","fuss","krad","gkfz"], "rows": [[…], …]}`; functions `parse_rows(fh, bbox) -> list[list]`, `read_zip(path, bbox) -> list[list]`, `main()`; `FIELDS`, `BBOX_WGS84`.

- [ ] **Step 1: Write the failing tests**

`tests/test_build_unfallatlas.py`:

```python
import importlib.util
import io
from pathlib import Path

_spec = importlib.util.spec_from_file_location("build_unfallatlas", Path(__file__).resolve().parent.parent / "scripts" / "build_unfallatlas.py")
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)

CSV_2020 = (
    "\ufeffOBJECTID;UIDENTSTLAE;ULAND;UREGBEZ;UKREIS;UGEMEINDE;UJAHR;UMONAT;USTUNDE;UWOCHENTAG;UKATEGORIE;UART;UTYP1;ULICHTVERH;IstRad;IstPKW;IstFuss;IstKrad;IstGkfz;IstSonstige;LINREFX;LINREFY;XGCSWGS84;YGCSWGS84;STRZUSTAND\n"
    "1;x;05;1;13;000;2020;01;11;5;2;1;7;0;1;1;0;0;0;0;361000,1;5699000,2;7,005000000000000;51,430000000000000;0\n"   # inside
    "2;y;12;0;68;468;2020;01;11;5;3;1;6;2;0;1;0;0;1;0;735840,4;5887204,8;12,521519179000052;53,082132832000070;0\n"   # outside bbox
    "3;z;05;1;13;000;2020;02;08;2;1;5;4;1;0;0;1;0;0;0;361100,0;5699100,0;7,006;51,431;1\n"                              # inside, Getötete, Fußgänger
)
CSV_2025 = (
    "\ufeffUIDENTSTLAE;ULAND;UREGBEZ;UKREIS;UGEMEINDE;UJAHR;UMONAT;USTUNDE;UWOCHENTAG;UKATEGORIE;UART;UTYP1;ULICHTVERH;IstStrassenzustand;IstRad;IstPKW;IstFuss;IstKrad;IstGkfz;IstSonstige;LINREFX;LINREFY;XGCSWGS84;YGCSWGS84;PLST\n"
    "a;05;1;13;000;2025;05;15;6;3;5;3;0;0;0;1;0;0;0;0;361000,0;5699000,0;7,0050;51,4300;1\n"
)


def test_parse_rows_crops_and_maps_fields():
    rows = mod.parse_rows(io.StringIO(CSV_2020), mod.BBOX_WGS84)
    assert rows == [
        [51.43, 7.005, 2020, 2, 7, 0, 1, 1, 0, 0, 0],
        [51.431, 7.006, 2020, 1, 4, 1, 0, 0, 1, 0, 0],
    ]


def test_parse_rows_handles_2025_layout_without_objectid():
    rows = mod.parse_rows(io.StringIO(CSV_2025), mod.BBOX_WGS84)
    assert rows == [[51.43, 7.005, 2025, 3, 3, 0, 0, 1, 0, 0, 0]]


def test_fields_order():
    assert mod.FIELDS == ["lat", "lon", "jahr", "kat", "typ", "licht", "rad", "pkw", "fuss", "krad", "gkfz"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_build_unfallatlas.py -q` → FAIL, script missing.

- [ ] **Step 3: Implement the script**

`scripts/build_unfallatlas.py`:

```python
"""Crop the Unfallatlas (Verkehrsunfälle mit Personenschaden) to the Essen/Bochum window.

Input: one zip per year from https://www.opengeodata.nrw.de/produkte/transport_verkehr/unfallatlas/
`Unfallorte<YYYY>_EPSG25832_CSV.zip` (Statistische Ämter des Bundes und der Länder, dl-de/by-2-0). The
inner CSV name varies by year (csv/Unfallorte2020_LinRef.csv, csv/Unfallorte_2025_LR_BasisDLM.csv), the
layout is ';'-separated with decimal comma and a BOM; columns used: UJAHR, UKATEGORIE (1 Getötete,
2 Schwerverletzte, 3 Leichtverletzte), UTYP1 (1 Fahrunfall, 2 Abbiegen, 3 Einbiegen/Kreuzen,
4 Überschreiten, 5 ruhender Verkehr, 6 Längsverkehr, 7 sonstiger), ULICHTVERH (0 Tag, 1 Dämmerung,
2 Dunkelheit), IstRad/IstPKW/IstFuss/IstKrad/IstGkfz (0/1), XGCSWGS84/YGCSWGS84 (lon/lat).

Output: redat/data/unfallatlas_2020_2025.json.gz with compact rows in FIELDS order, read at runtime by
redat/sources/unfaelle.py.

Usage:
    .venv/bin/python scripts/build_unfallatlas.py --src /dir/with/Unfallorte*_EPSG25832_CSV.zip
"""
from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import re
import zipfile
from pathlib import Path
from typing import IO

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "redat" / "data" / "unfallatlas_2020_2025.json.gz"
YEARS = list(range(2020, 2026))
BBOX_WGS84 = (6.85, 51.33, 7.40, 51.56)   # lon_min, lat_min, lon_max, lat_max — same window as the Zensus grid
FIELDS = ["lat", "lon", "jahr", "kat", "typ", "licht", "rad", "pkw", "fuss", "krad", "gkfz"]
_INT_COLS = {"jahr": "UJAHR", "kat": "UKATEGORIE", "typ": "UTYP1", "licht": "ULICHTVERH",
             "rad": "IstRad", "pkw": "IstPKW", "fuss": "IstFuss", "krad": "IstKrad", "gkfz": "IstGkfz"}


def _num(s: str) -> float:
    return float((s or "").strip().replace(",", "."))


def parse_rows(fh: IO[str], bbox: tuple[float, float, float, float]) -> list[list]:
    lon_min, lat_min, lon_max, lat_max = bbox
    rows = []
    reader = csv.DictReader(fh, delimiter=";")
    reader.fieldnames = [f.lstrip("\ufeff") for f in reader.fieldnames or []]   # BOM survives when a caller passes a plain StringIO
    for r in reader:
        try:
            lon, lat = _num(r["XGCSWGS84"]), _num(r["YGCSWGS84"])
        except (KeyError, ValueError):
            continue
        if not (lon_min <= lon <= lon_max and lat_min <= lat <= lat_max):
            continue
        row = [round(lat, 6), round(lon, 6)]
        try:
            row += [int(_num(r[col])) for col in _INT_COLS.values()]
        except (KeyError, ValueError):
            continue
        rows.append(row)
    return rows


def read_zip(path: Path, bbox: tuple[float, float, float, float]) -> list[list]:
    with zipfile.ZipFile(path) as z:
        name = next(n for n in z.namelist() if n.lower().endswith(".csv"))
        with z.open(name) as raw:
            return parse_rows(io.TextIOWrapper(raw, encoding="utf-8-sig", errors="replace"), bbox)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", type=Path, required=True, help="directory holding Unfallorte<YYYY>_EPSG25832_CSV.zip")
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args()
    rows, years = [], []
    for y in YEARS:
        zips = sorted(a.src.glob(f"Unfallorte{y}_EPSG25832_CSV.zip"))
        if not zips:
            print(f"skip {y}: no zip in {a.src}")
            continue
        got = read_zip(zips[0], BBOX_WGS84)
        print(f"{y}: {len(got)} accidents in window")
        rows += got
        years.append(y)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(a.out, "wt", encoding="utf-8") as fh:
        json.dump({"years": years, "bbox": list(BBOX_WGS84), "fields": FIELDS, "rows": rows}, fh, separators=(",", ":"))
    print(f"wrote {a.out}: {len(rows)} rows, years {years}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests, then build the real file**

Run: `.venv/bin/python -m pytest tests/test_build_unfallatlas.py -q` → `3 passed`.

```bash
mkdir -p /tmp/unfallatlas && cd /tmp/unfallatlas
for y in 2020 2021 2022 2023 2024 2025; do curl -sSL -O "https://www.opengeodata.nrw.de/produkte/transport_verkehr/unfallatlas/Unfallorte${y}_EPSG25832_CSV.zip"; done
cd - && .venv/bin/python scripts/build_unfallatlas.py --src /tmp/unfallatlas
ls -la redat/data/unfallatlas_2020_2025.json.gz     # expect ~300 KB; ~5,000–6,200 accidents per year in the window (2020: 4,873, 2025: 6,185 verified) → ~35k rows
```

- [ ] **Step 5: Commit**

```bash
git add scripts/build_unfallatlas.py tests/test_build_unfallatlas.py redat/data/unfallatlas_2020_2025.json.gz
git commit -m "feat(unfaelle): Unfallatlas build script and Essen/Bochum accident grid 2020-2025"
```

---

### Task 11: `unfaelle` card — accidents within 300 m

**Files:**
- Create: `redat/sources/unfaelle.py`, `redat/templates/analysis/_unfaelle.html`, `redat/templates/report/_unfaelle.html`
- Modify: `redat/core/sections.py`, `redat/core/tiers.py`, `redat/core/sources_meta.py`, `redat/report/builder.py`
- Modify: `tests/fixtures/report_envelopes.json`, `tests/test_analysis_sections.py`, `tests/test_tiers.py`, `tests/test_report_render.py`
- Test: `tests/test_unfaelle.py`

**Interfaces:**
- Consumes: `redat/data/unfallatlas_2020_2025.json.gz` (Task 10)
- Produces: `unfaelle.lookup(lat, lon) -> Optional[dict]` with `radius_m`, `years`, `total`, `per_year`, `per_year_avg`, `by_severity`, `beteiligt`, `by_type`, `nachts`, `nearest_m`, `rating`, `rating_color`; `unfaelle._load()` (lru_cached, monkeypatch point). Section key `unfaelle` (area) after `schulen`.

- [ ] **Step 1: Write the failing tests**

`tests/test_unfaelle.py`:

```python
import pytest

from redat.sources import unfaelle

F = ["lat", "lon", "jahr", "kat", "typ", "licht", "rad", "pkw", "fuss", "krad", "gkfz"]
# Point 51.4300, 7.0050. 0.001° lat ≈ 111 m; 0.001° lon ≈ 69 m.
ROWS = [
    [51.4305, 7.0050, 2020, 3, 6, 0, 0, 1, 0, 0, 0],   #  56 m, Leichtverletzte, Längsverkehr, PKW
    [51.4310, 7.0050, 2021, 2, 4, 2, 0, 1, 1, 0, 0],   # 111 m, Schwerverletzte, Überschreiten, nachts, Fuß+PKW
    [51.4300, 7.0080, 2022, 3, 1, 0, 1, 0, 0, 0, 0],   # 208 m, Rad, Fahrunfall
    [51.4300, 7.0090, 2023, 1, 3, 1, 0, 1, 0, 0, 1],   # 277 m, Getötete, Einbiegen/Kreuzen, Gkfz
    [51.4340, 7.0050, 2024, 3, 6, 0, 0, 1, 0, 1, 0],   # 445 m → outside
]
GRID = {"years": [2020, 2021, 2022, 2023, 2024, 2025], "bbox": [6.85, 51.33, 7.40, 51.56], "fields": F, "rows": ROWS}


@pytest.fixture(autouse=True)
def grid(monkeypatch):
    monkeypatch.setattr(unfaelle, "_load", lambda: GRID)


def test_lookup_counts():
    d = unfaelle.lookup(51.4300, 7.0050)
    assert d["radius_m"] == 300 and d["years"] == [2020, 2021, 2022, 2023, 2024, 2025] and d["total"] == 4
    assert d["per_year"] == {"2020": 1, "2021": 1, "2022": 1, "2023": 1, "2024": 0, "2025": 0}
    assert d["per_year_avg"] == 0.7
    assert d["by_severity"] == {"getoetete": 1, "schwerverletzte": 1, "leichtverletzte": 2}
    assert d["beteiligt"] == {"rad": 1, "fuss": 1, "pkw": 3, "krad": 0, "gkfz": 1}
    assert d["by_type"] == {"Fahrunfall": 1, "Einbiegen/Kreuzen": 1, "Überschreiten": 1, "Längsverkehr": 1}
    assert d["nachts"] == 1 and 50 < d["nearest_m"] < 60


def test_rating_bands(monkeypatch):
    d = unfaelle.lookup(51.4300, 7.0050)
    assert d["rating"] == "Viele Unfälle" and d["rating_color"] == "orange"      # 0.7/a is green, but a Getöteter lifts to orange
    no_fatal = {**GRID, "rows": [r for r in ROWS if r[3] != 1]}
    monkeypatch.setattr(unfaelle, "_load", lambda: no_fatal)
    d = unfaelle.lookup(51.4300, 7.0050)
    assert d["rating"] == "Wenige Unfälle" and d["rating_color"] == "green"
    assert unfaelle._rate(4.0, 0) == ("Mäßig viele Unfälle", "yellow")
    assert unfaelle._rate(10.0, 0) == ("Viele Unfälle", "orange")
    assert unfaelle._rate(20.0, 0) == ("Unfallschwerpunkt", "red")


def test_outside_window_and_missing_grid(monkeypatch):
    d = unfaelle.lookup(51.0, 7.0)          # outside the grid bbox
    assert d is None
    monkeypatch.setattr(unfaelle, "_load", lambda: None)
    assert unfaelle.lookup(51.43, 7.0) is None


def test_zero_accidents_inside_window_is_data_not_empty(monkeypatch):
    monkeypatch.setattr(unfaelle, "_load", lambda: {**GRID, "rows": []})
    d = unfaelle.lookup(51.4300, 7.0050)
    assert d["total"] == 0 and d["nearest_m"] is None and d["rating_color"] == "green"
```

Registry/tier/render updates: insert `"unfaelle"` after `"schulen"` in the order test; add to the tier list (area); render checks `"unfaelle": ["Getötete", "Überschreiten", "300 m"],`; and:

```python
def test_unfaelle_passthrough_and_empty(monkeypatch):
    from redat.sources import unfaelle
    monkeypatch.setattr(unfaelle, "lookup", lambda lat, lon: {"total": 3})
    assert S._fetch_unfaelle(CTX) == {"total": 3}
    monkeypatch.setattr(unfaelle, "lookup", lambda lat, lon: None)
    with pytest.raises(Empty) as ei:
        S._fetch_unfaelle(CTX)
    assert "Unfallatlas" in ei.value.message
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_unfaelle.py -q` → `ModuleNotFoundError`.

- [ ] **Step 3: Implement `unfaelle.py`**

```python
"""Verkehrsunfälle mit Personenschaden around the point — Unfallatlas der Statistischen Ämter.

Data: redat/data/unfallatlas_2020_2025.json.gz (scripts/build_unfallatlas.py), compact rows in FIELDS
order cropped to the Essen/Bochum window. Only accidents with injured persons are recorded; the location
is the accident spot on the road, never an address. `_load` is the monkeypatch point.
"""
from __future__ import annotations

import gzip
import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Optional

GRID_PATH = Path(__file__).resolve().parent.parent / "data" / "unfallatlas_2020_2025.json.gz"
RADIUS_M = 300
SEVERITY = {1: "getoetete", 2: "schwerverletzte", 3: "leichtverletzte"}
TYPES = {1: "Fahrunfall", 2: "Abbiegeunfall", 3: "Einbiegen/Kreuzen", 4: "Überschreiten", 5: "Ruhender Verkehr", 6: "Längsverkehr", 7: "Sonstiger"}
_NIGHT = 2


@lru_cache(maxsize=1)
def _load() -> Optional[dict]:
    try:
        with gzip.open(GRID_PATH, "rt", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _dist_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    k = math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot((lat2 - lat1) * 111_195, (lon2 - lon1) * 111_195 * k)


def _rate(per_year_avg: float, fatal: int) -> tuple[str, str]:
    if per_year_avg > 15:
        rating, color = "Unfallschwerpunkt", "red"
    elif per_year_avg > 6:
        rating, color = "Viele Unfälle", "orange"
    elif per_year_avg > 2:
        rating, color = "Mäßig viele Unfälle", "yellow"
    else:
        rating, color = "Wenige Unfälle", "green"
    if fatal and color in ("green", "yellow"):
        rating, color = "Viele Unfälle", "orange"   # a fatality within 300 m outweighs a low count
    return rating, color


def lookup(lat: float, lon: float) -> Optional[dict]:
    """Accident statistics within RADIUS_M, or None outside the data window / without the grid file."""
    grid = _load()
    if not grid:
        return None
    lon_min, lat_min, lon_max, lat_max = grid["bbox"]
    if not (lon_min <= lon <= lon_max and lat_min <= lat <= lat_max):
        return None
    idx = {name: i for i, name in enumerate(grid["fields"])}
    years = [int(y) for y in grid["years"]]
    per_year = {str(y): 0 for y in years}
    severity = {v: 0 for v in SEVERITY.values()}
    beteiligt = {"rad": 0, "fuss": 0, "pkw": 0, "krad": 0, "gkfz": 0}
    by_type: dict[str, int] = {}
    nachts, nearest = 0, None
    dlat = RADIUS_M / 111_195 * 1.05
    for r in grid["rows"]:
        rlat, rlon = r[idx["lat"]], r[idx["lon"]]
        if abs(rlat - lat) > dlat:
            continue
        dist = _dist_m(lat, lon, rlat, rlon)
        if dist > RADIUS_M:
            continue
        nearest = dist if nearest is None else min(nearest, dist)
        per_year[str(r[idx["jahr"]])] = per_year.get(str(r[idx["jahr"]]), 0) + 1
        sev = SEVERITY.get(r[idx["kat"]])
        if sev:
            severity[sev] += 1
        for k in beteiligt:
            beteiligt[k] += 1 if r[idx[k]] else 0
        t = TYPES.get(r[idx["typ"]], "Sonstiger")
        by_type[t] = by_type.get(t, 0) + 1
        if r[idx["licht"]] == _NIGHT:
            nachts += 1
    total = sum(per_year.values())
    avg = round(total / len(years), 1) if years else 0.0
    rating, color = _rate(avg, severity["getoetete"])
    return {
        "radius_m": RADIUS_M, "years": years, "total": total, "per_year": per_year, "per_year_avg": avg,
        "by_severity": severity, "beteiligt": beteiligt,
        "by_type": dict(sorted(by_type.items(), key=lambda kv: -kv[1])),
        "nachts": nachts, "nearest_m": round(nearest, 1) if nearest is not None else None,
        "rating": rating, "rating_color": color,
    }
```

- [ ] **Step 4: Registry, summary, partials, fixture**

`sections.py` (after `_fetch_schulen`):

```python
def _fetch_unfaelle(ctx: Ctx) -> dict:
    from redat.sources import unfaelle

    d = unfaelle.lookup(ctx.lat, ctx.lon)
    if d is None:
        raise Empty("Keine Unfallatlas-Daten für diesen Ort (außerhalb Essen/Bochum oder Datei fehlt)")
    return d
```

Registry line after `schulen`:

```python
    Section("unfaelle", "Verkehrsunfälle (Unfallatlas)", "🚧", 10,
            "Statistische Ämter des Bundes und der Länder, Unfallatlas 2020–2025 (dl-de/by-2-0) — nur Unfälle mit Personenschaden", _fetch_unfaelle),
```

`tiers.py`: `"unfaelle": "area",`. `sources_meta.py`:

```python
    SourceMeta(("unfaelle",), "Unfallatlas — Straßenverkehrsunfälle mit Personenschaden", "Statistische Ämter des Bundes und der Länder", "dl-de/by-2-0",
               "lokal: redat/data/unfallatlas_2020_2025.json.gz (scripts/build_unfallatlas.py)", "area", "jährlich (Juli), Datei-Import"),
```

`builder.py`:

```python
def _s_unfaelle(d):
    rating, color = _rated(d)
    if d.get("total") is None:
        return rating, color, None
    sev = d.get("by_severity") or {}
    fig = f"{d['total']} Unfälle ≤ {d.get('radius_m') or 300} m in {len(d.get('years') or [])} Jahren"
    if sev.get("getoetete"):
        fig += f" · {sev['getoetete']} Getötete"
    if sev.get("schwerverletzte"):
        fig += f" · {sev['schwerverletzte']} Schwerverletzte"
    return rating, color, fig
```

`"unfaelle": _s_unfaelle,` after `"schulen"`.

`redat/templates/analysis/_unfaelle.html`:

```html
<div class="flex items-center gap-4">
    <span class="px-3 py-1 rounded-full font-bold" :class="$store.app.getAirQualityColor(d.rating_color)" x-text="d.rating"></span>
    <div class="text-sm">
        <div class="text-gray-500">Unfälle mit Personenschaden im Umkreis von <span x-text="d.radius_m"></span> m, <span x-text="d.years[0] + '–' + d.years[d.years.length - 1]"></span></div>
        <div class="font-medium text-gray-900"><span x-text="d.total"></span> Unfälle · Ø <span x-text="d.per_year_avg"></span> pro Jahr<span x-show="d.nearest_m != null" x-text="' · nächster ' + $store.app.formatDistance(d.nearest_m)"></span></div>
    </div>
</div>
<div class="mt-4 grid grid-cols-1 md:grid-cols-3 gap-4 text-sm" x-show="d.total">
    <div>
        <div class="text-gray-500">Schwere</div>
        <ul class="mt-1">
            <li x-show="d.by_severity.getoetete" class="text-red-700 font-medium" x-text="d.by_severity.getoetete + ' Unfälle mit Getöteten'"></li>
            <li x-text="d.by_severity.schwerverletzte + ' mit Schwerverletzten'"></li>
            <li x-text="d.by_severity.leichtverletzte + ' mit Leichtverletzten'"></li>
        </ul>
    </div>
    <div>
        <div class="text-gray-500">Beteiligte</div>
        <ul class="mt-1">
            <li x-text="'🚲 Rad: ' + d.beteiligt.rad"></li>
            <li x-text="'🚶 Fußgänger: ' + d.beteiligt.fuss"></li>
            <li x-text="'🚗 Pkw: ' + d.beteiligt.pkw + ' · 🏍 Krad: ' + d.beteiligt.krad + ' · 🚚 Lkw: ' + d.beteiligt.gkfz"></li>
            <li class="text-gray-500" x-text="d.nachts + ' bei Dunkelheit'"></li>
        </ul>
    </div>
    <div>
        <div class="text-gray-500">Unfalltypen</div>
        <ul class="mt-1">
            <template x-for="[t, n] in Object.entries(d.by_type)" :key="t"><li><span x-text="t"></span>: <span x-text="n"></span></li></template>
        </ul>
    </div>
</div>
<div class="mt-3 flex items-end gap-1 h-12" x-show="d.total" title="Unfälle pro Jahr">
    <template x-for="[y, n] in Object.entries(d.per_year)" :key="y">
        <div class="flex-1 flex flex-col items-center text-xs text-gray-500">
            <div class="w-full bg-gray-300 rounded-t" :style="'height:' + Math.max(2, 36 * n / Math.max(1, ...Object.values(d.per_year))) + 'px'"></div>
            <span x-text="String(y).slice(2)"></span>
        </div>
    </template>
</div>
<p class="mt-3 text-xs text-gray-500">Nur polizeilich erfasste Unfälle mit Personenschaden; der Punkt ist der Unfallort auf der Straße. Viele Unfälle im Umkreis heißen viel Verkehr vor der Tür — relevant für Kinder, Rad und Lärm.</p>
```

`redat/templates/report/_unfaelle.html`:

```html
{% set sev = d.get("by_severity") or {} %}
{% set bet = d.get("beteiligt") or {} %}
{% set years = d.get("years") or [] %}
<div class="kpis">
  <div class="kpi">
    <div class="label">Unfälle mit Personenschaden ≤ {{ d.get("radius_m") or 300 }} m{% if years %}, {{ years[0] }}–{{ years[-1] }}{% endif %}</div>
    <div class="value"><span class="chip {{ rating_class(d.get('rating_color')) }}">{{ d.get("rating") or "—" }}</span></div>
  </div>
  <div class="kpi">
    <div class="label">Gesamt · pro Jahr</div>
    <div class="value">{{ d.get("total") if d.get("total") is not none else "—" }} · Ø {{ d.per_year_avg|fmt_num(1) if d.get("per_year_avg") is not none else "—" }}</div>
    {% if d.get("nearest_m") is not none %}<div class="sub">nächster Unfallort {{ d.nearest_m|fmt_m }}</div>{% endif %}
  </div>
</div>
{% if d.get("total") %}
<table class="mt">
  <thead><tr><th>Schwere</th><th class="num">Unfälle</th><th>Beteiligte</th><th class="num">Unfälle</th></tr></thead>
  <tbody>
    <tr><td>mit Getöteten</td><td class="num">{{ sev.get("getoetete", 0) }}</td><td>Rad</td><td class="num">{{ bet.get("rad", 0) }}</td></tr>
    <tr><td>mit Schwerverletzten</td><td class="num">{{ sev.get("schwerverletzte", 0) }}</td><td>Fußgänger</td><td class="num">{{ bet.get("fuss", 0) }}</td></tr>
    <tr><td>mit Leichtverletzten</td><td class="num">{{ sev.get("leichtverletzte", 0) }}</td><td>Pkw / Krad / Lkw</td><td class="num">{{ bet.get("pkw", 0) }} / {{ bet.get("krad", 0) }} / {{ bet.get("gkfz", 0) }}</td></tr>
  </tbody>
</table>
{% set types = d.get("by_type") or {} %}
{% if types %}<p class="xs">Unfalltypen: {% for t, n in types.items() %}{{ t }} {{ n }}{% if not loop.last %} · {% endif %}{% endfor %}{% if d.get("nachts") %} · {{ d.nachts }} bei Dunkelheit{% endif %}</p>{% endif %}
{% endif %}
<p class="footnote">Unfallatlas der Statistischen Ämter: nur polizeilich erfasste Unfälle mit Personenschaden, Lage = Unfallort auf der Straße.</p>
```

Fixture `"unfaelle"`:

```json
"unfaelle": {"key": "unfaelle", "tier": "area", "status": "ok", "message": null, "took_ms": 9,
  "source": "Statistische Ämter des Bundes und der Länder, Unfallatlas 2020–2025 (dl-de/by-2-0) — nur Unfälle mit Personenschaden",
  "data": {"radius_m": 300, "years": [2020, 2021, 2022, 2023, 2024, 2025], "total": 4, "per_year": {"2020": 1, "2021": 1, "2022": 1, "2023": 1, "2024": 0, "2025": 0},
           "per_year_avg": 0.7, "by_severity": {"getoetete": 1, "schwerverletzte": 1, "leichtverletzte": 2},
           "beteiligt": {"rad": 1, "fuss": 1, "pkw": 3, "krad": 0, "gkfz": 1},
           "by_type": {"Fahrunfall": 1, "Einbiegen/Kreuzen": 1, "Überschreiten": 1, "Längsverkehr": 1},
           "nachts": 1, "nearest_m": 55.6, "rating": "Viele Unfälle", "rating_color": "orange"}}
```

- [ ] **Step 5: Run the whole suite**

Run: `.venv/bin/python -m pytest -q` → green.

- [ ] **Step 6: Commit**

```bash
git add redat/sources/unfaelle.py redat/templates/analysis/_unfaelle.html redat/templates/report/_unfaelle.html redat/core redat/report/builder.py tests/
git commit -m "feat(unfaelle): accidents within 300 m from the Unfallatlas grid"
```

---

### Task 12: `radon` card — BfS radon in soil air and radon potential

**Files:**
- Create: `redat/sources/radon.py`, `redat/templates/analysis/_radon.html`, `redat/templates/report/_radon.html`
- Modify: `redat/core/sections.py`, `redat/core/tiers.py`, `redat/core/sources_meta.py`, `redat/report/builder.py`
- Modify: `tests/fixtures/report_envelopes.json`, `tests/test_analysis_sections.py`, `tests/test_tiers.py`, `tests/test_report_render.py`
- Test: `tests/test_radon.py`

**Interfaces:**
- Produces: `radon.get_radon(lat, lon) -> Optional[dict]` `{"bodenluft": {...}|None, "potenzial": {...}|None, "rating", "rating_color"}`; `radon._wfs_features(typename, lat, lon) -> list[dict]` (HTTP point, GeoJSON features); `radon.classify_bodenluft(kbq) -> (label, color)`, `radon.classify_potenzial(value) -> (label, color)`. Section key `radon` (area) placed right after `bergbau`.

- [ ] **Step 1: Write the failing tests**

`tests/test_radon.py`:

```python
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
```

Registry/tier/render updates: insert `"radon"` after `"bergbau"` in the order test; add to the tier list (area); render checks `"radon": ["57", "Karbon", "erhöht"],`; and:

```python
def test_radon_passthrough_and_empty(monkeypatch):
    from redat.sources import radon
    monkeypatch.setattr(radon, "get_radon", lambda lat, lon: {"rating": "x"})
    assert S._fetch_radon(CTX) == {"rating": "x"}
    monkeypatch.setattr(radon, "get_radon", lambda lat, lon: None)
    with pytest.raises(Empty):
        S._fetch_radon(CTX)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_radon.py -q` → `ModuleNotFoundError`.

- [ ] **Step 3: Implement `radon.py`**

```python
"""Radon — the BfS soil-air prognosis and geogenic radon potential for the point.

Source: Bundesamt für Strahlenschutz open-data WFS https://www.imis.bfs.de/ogc/opendata/ows (WFS 2.0.0,
GeoJSON, dl-de/by-2-0). Types: `opendata:radon222_boden_rfv_risikokommunikation` — ~3 km cells with
`rn_max` = 90th percentile of the radon activity concentration in soil air at 1 m depth in kBq/m³,
`geo_unit` ("Karbon", "Kreide", "Quartär"), `descript` cell id; `opendata:radonpotential` — ~10 km cells
with `grp_pb_`, the geogenic radon potential (radon concentration combined with gas permeability,
dimensionless). The bbox parameter must be **lon,lat** order (lat,lon returns nothing — verified
2026-09-05); geometries are WGS84 lon/lat, so shapely works on them directly.

Classes — Bodenluft per the BfS map legend: < 20 gering, 20–40 mittel, 40–100 erhöht, > 100 hoch
(kBq/m³). Potenzial per the Neznal classification the BfS uses: < 10 gering, 10–35 mittel, > 35 hoch.
Both are regional prognoses, never a measurement at the house; NRW has designated no
Radonvorsorgegebiete. `_wfs_features` is the single HTTP call and monkeypatch point.
"""
from __future__ import annotations

import logging
from typing import Optional

import httpx
from shapely.geometry import Point, shape

from redat.http import headers

logger = logging.getLogger(__name__)

BFS_WFS_URL = "https://www.imis.bfs.de/ogc/opendata/ows"
TYPE_BODEN = "opendata:radon222_boden_rfv_risikokommunikation"
TYPE_POTENZIAL = "opendata:radonpotential"
_BBOX_DEG = 0.01
_TIMEOUT_S = 20
_COLOR_RANK = {"green": 0, "yellow": 1, "orange": 2, "red": 3}


def _wfs_features(typename: str, lat: float, lon: float) -> list[dict]:
    """GeoJSON features of one type around the point — HTTP/monkeypatch point (bbox is lon,lat!)."""
    params = {
        "service": "WFS", "version": "2.0.0", "request": "GetFeature", "typeNames": typename,
        "outputFormat": "application/json", "srsName": "EPSG:4326",
        "bbox": f"{lon - _BBOX_DEG},{lat - _BBOX_DEG},{lon + _BBOX_DEG},{lat + _BBOX_DEG},EPSG:4326", "count": 20,
    }
    resp = httpx.get(BFS_WFS_URL, params=params, timeout=_TIMEOUT_S, headers=headers())
    resp.raise_for_status()
    return resp.json().get("features", [])


def classify_bodenluft(kbq: float) -> tuple[str, str]:
    if kbq > 100:
        return "hoch", "red"
    if kbq > 40:
        return "erhöht", "orange"
    if kbq >= 20:
        return "mittel", "yellow"
    return "gering", "green"


def classify_potenzial(value: float) -> tuple[str, str]:
    if value > 35:
        return "hoch", "orange"
    if value >= 10:
        return "mittel", "yellow"
    return "gering", "green"


def _cell_at(features: list[dict], pt: Point) -> Optional[dict]:
    for f in features:
        try:
            if shape(f["geometry"]).contains(pt):
                return f.get("properties") or {}
        except (KeyError, TypeError, ValueError):
            continue
    return None


def get_radon(lat: float, lon: float) -> Optional[dict]:
    """Soil-air radon and radon potential at the point; None when neither dataset covers it."""
    pt = Point(lon, lat)
    out: dict = {"bodenluft": None, "potenzial": None, "errors": {}}
    for key, typename in (("bodenluft", TYPE_BODEN), ("potenzial", TYPE_POTENZIAL)):
        try:
            props = _cell_at(_wfs_features(typename, lat, lon), pt)
        except Exception as exc:  # noqa: BLE001 — one type failing must not blank the other
            logger.warning("BfS %s: %s", typename, exc)
            out["errors"][key] = str(exc)
            continue
        if props is None:
            continue
        if key == "bodenluft" and props.get("rn_max") is not None:
            kbq = float(props["rn_max"])
            label, color = classify_bodenluft(kbq)
            out["bodenluft"] = {"kbq_m3": kbq, "klasse": label, "klasse_color": color, "geologie": props.get("geo_unit"), "zelle": props.get("descript")}
        elif key == "potenzial" and props.get("grp_pb_") is not None:
            val = float(props["grp_pb_"])
            label, color = classify_potenzial(val)
            out["potenzial"] = {"wert": val, "klasse": label, "klasse_color": color}
    if len(out["errors"]) == 2:
        raise RuntimeError(f"BfS-WFS nicht erreichbar: {out['errors']['bodenluft']}")
    if out["bodenluft"] is None and out["potenzial"] is None:
        return None
    colors = [b["klasse_color"] for b in (out["bodenluft"], out["potenzial"]) if b]
    worst = max(colors, key=_COLOR_RANK.get)
    out["rating"] = {"green": "Geringes Radonpotenzial", "yellow": "Mittleres Radonpotenzial",
                     "orange": "Erhöhtes Radonpotenzial", "red": "Hohes Radonpotenzial"}[worst]
    out["rating_color"] = worst
    return out
```

- [ ] **Step 4: Registry, summary, partials, fixture**

`sections.py` (area tier, after `_fetch_bergbau`):

```python
def _fetch_radon(ctx: Ctx) -> dict:
    from redat.sources.radon import get_radon

    d = get_radon(ctx.lat, ctx.lon)
    if d is None:
        raise Empty("Keine Radon-Prognose für diesen Ort (außerhalb Deutschlands)")
    return d
```

Registry line after `bergbau`:

```python
    Section("radon", "Radon", "☢️", 20, "Bundesamt für Strahlenschutz — Radon in der Bodenluft (1 km-Prognose) und Radonpotenzial (dl-de/by-2-0)", _fetch_radon),
```

`tiers.py`: `"radon": "area",`. `sources_meta.py`:

```python
    SourceMeta(("radon",), "Radon in der Bodenluft · Radonpotenzial", "Bundesamt für Strahlenschutz (BfS)", "dl-de/by-2-0",
               "https://www.imis.bfs.de/ogc/opendata/ows (WFS 2.0, GeoJSON)", "area", "live, Karten 2023 (statisch)"),
```

`builder.py`:

```python
def _s_radon(d):
    rating, color = _rated(d)
    b, p = d.get("bodenluft") or {}, d.get("potenzial") or {}
    parts = []
    if b.get("kbq_m3") is not None:
        parts.append(f"Bodenluft {fmt_num(b['kbq_m3'], 0)} kBq/m³ ({b.get('klasse')})" + (f", {b['geologie']}" if b.get("geologie") else ""))
    if p.get("wert") is not None:
        parts.append(f"Potenzial {fmt_num(p['wert'], 0)} ({p.get('klasse')})")
    return rating, color, " · ".join(parts) or None
```

`"radon": _s_radon,` after `"bergbau"`.

`redat/templates/analysis/_radon.html`:

```html
<div class="flex items-center gap-4">
    <span class="px-3 py-1 rounded-full font-bold" :class="$store.app.getAirQualityColor(d.rating_color)" x-text="d.rating"></span>
    <div class="text-sm text-gray-500">BfS-Prognose für die Umgebung (1-km- bzw. 10-km-Raster), kein Messwert am Haus</div>
</div>
<div class="mt-4 grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
    <div x-show="d.bodenluft">
        <div class="text-gray-500">Radon in der Bodenluft (90. Perzentil, 1 m Tiefe)</div>
        <div class="text-2xl font-bold text-gray-900"><span x-text="d.bodenluft && Math.round(d.bodenluft.kbq_m3)"></span> <span class="text-base font-normal">kBq/m³</span>
            <span class="ml-2 px-2 py-0.5 rounded-full text-xs font-bold" :class="$store.app.getAirQualityColor(d.bodenluft && d.bodenluft.klasse_color)" x-text="d.bodenluft && d.bodenluft.klasse"></span></div>
        <div class="text-xs text-gray-500" x-show="d.bodenluft && d.bodenluft.geologie" x-text="'Geologische Einheit: ' + (d.bodenluft && d.bodenluft.geologie)"></div>
    </div>
    <div x-show="d.potenzial">
        <div class="text-gray-500">Geogenes Radonpotenzial</div>
        <div class="text-2xl font-bold text-gray-900"><span x-text="d.potenzial && Math.round(d.potenzial.wert)"></span>
            <span class="ml-2 px-2 py-0.5 rounded-full text-xs font-bold" :class="$store.app.getAirQualityColor(d.potenzial && d.potenzial.klasse_color)" x-text="d.potenzial && d.potenzial.klasse"></span></div>
        <div class="text-xs text-gray-500">Radongehalt × Gasdurchlässigkeit des Untergrunds (unter 10 gering, 10–35 mittel, über 35 hoch)</div>
    </div>
</div>
<p class="mt-3 text-xs text-gray-500">
    Klassen Bodenluft: unter 20 gering, 20–40 mittel, 40–100 erhöht, über 100 kBq/m³ hoch. Das Karbon des Ruhrgebiets liegt oft in der erhöhten Klasse.
    NRW hat keine Radonvorsorgegebiete ausgewiesen; bei Wohnnutzung im Keller/Erdgeschoss eine Radonmessung (Referenzwert 300 Bq/m³ Raumluft) einplanen.
    <span x-show="d.errors && Object.keys(d.errors).length" x-text="' · nicht abrufbar: ' + Object.keys(d.errors || {}).join(', ')"></span>
</p>
```

`redat/templates/report/_radon.html`:

```html
{% set b = d.get("bodenluft") or {} %}
{% set p = d.get("potenzial") or {} %}
<div class="kpis">
  <div class="kpi">
    <div class="label">Radon (BfS-Prognose, Raster)</div>
    <div class="value"><span class="chip {{ rating_class(d.get('rating_color')) }}">{{ d.get("rating") or "—" }}</span></div>
  </div>
  <div class="kpi">
    <div class="label">Radon in der Bodenluft (90. Perzentil)</div>
    <div class="value">{{ (b.kbq_m3|fmt_num(0) ~ " kBq/m³") if b.get("kbq_m3") is not none else "—" }}</div>
    <div class="sub">{% if b.get("klasse") %}Klasse {{ b.klasse }}{% endif %}{% if b.get("geologie") %} · {{ b.geologie }}{% endif %}</div>
  </div>
  <div class="kpi">
    <div class="label">Geogenes Radonpotenzial</div>
    <div class="value">{{ p.wert|fmt_num(0) if p.get("wert") is not none else "—" }}</div>
    <div class="sub">{% if p.get("klasse") %}Klasse {{ p.klasse }}{% endif %}</div>
  </div>
</div>
<p class="footnote">Bundesamt für Strahlenschutz: Bodenluft unter 20 gering, 20–40 mittel, 40–100 erhöht, über 100 kBq/m³ hoch; Potenzial unter 10 gering, 10–35 mittel, über 35 hoch. Regionale Prognose, kein Messwert am Gebäude; Referenzwert Raumluft 300 Bq/m³.</p>
```

Fixture `"radon"`:

```json
"radon": {"key": "radon", "tier": "area", "status": "ok", "message": null, "took_ms": 480,
  "source": "Bundesamt für Strahlenschutz — Radon in der Bodenluft (1 km-Prognose) und Radonpotenzial (dl-de/by-2-0)",
  "data": {"bodenluft": {"kbq_m3": 57.0, "klasse": "erhöht", "klasse_color": "orange", "geologie": "Karbon", "zelle": "AC138"},
           "potenzial": {"wert": 36.5, "klasse": "hoch", "klasse_color": "orange"}, "errors": {},
           "rating": "Erhöhtes Radonpotenzial", "rating_color": "orange"}}
```

- [ ] **Step 5: Run the whole suite**

Run: `.venv/bin/python -m pytest -q` → green.

- [ ] **Step 6: Commit**

```bash
git add redat/sources/radon.py redat/templates/analysis/_radon.html redat/templates/report/_radon.html redat/core redat/report/builder.py tests/
git commit -m "feat(radon): BfS soil-air radon and radon potential card"
```

---

### Task 13: `baugrund` card — BK50 soil unit (HTML GetFeatureInfo) + Essen kf-Werte

**Files:**
- Create: `redat/sources/baugrund.py`, `redat/templates/analysis/_baugrund.html`, `redat/templates/report/_baugrund.html`
- Modify: `redat/core/sections.py`, `redat/core/tiers.py`, `redat/core/sources_meta.py`, `redat/report/builder.py`
- Modify: `tests/fixtures/report_envelopes.json`, `tests/test_analysis_sections.py`, `tests/test_tiers.py`, `tests/test_report_render.py`
- Test: `tests/test_baugrund.py`

**Interfaces:**
- Produces: `baugrund.get_baugrund(lat, lon) -> Optional[dict]` (spec §4 shape); `baugrund._featureinfo_html(lat, lon) -> str` (HTTP point A); `baugrund._kf_query(lat, lon) -> dict` (HTTP point B, Essen ArcGIS); `baugrund.parse_bk50_html(html) -> dict[str, list[str]]` (label → cell texts); `baugrund.in_essen(lat, lon)`. Section key `baugrund` (area) placed right after `bergbau` (before `radon`).

- [ ] **Step 1: Write the failing tests**

`tests/test_baugrund.py`:

```python
import pytest

from redat.sources import baugrund as bg

# Verbatim structure of the BK50 text/html GetFeatureInfo (Rüttenscheid, 2026-09-05), reduced to the rows we read.
HTML = """<html><head><style>td{}</style></head><body><table>
<tr><th colspan="5">Basisinformationen</th></tr>
<tr> <td><a href="https://www.gd.nrw.de/wms_html/bk50_wms/pdf/TYP.pdf" target="_blank">Bodentyp</a></td><td align="middle" colspan="4">Parabraunerde</td> </tr>
<tr> <td><a href="https://www.gd.nrw.de/wms_html/bk50_wms/pdf/GW.pdf" target="_blank">Grundwasserstufe</a></td><td colspan="4" align="middle">Stufe 0 - ohne Grundwasser</td> </tr>
<tr> <td><a href="https://www.gd.nrw.de/wms_html/bk50_wms/pdf/SN.pdf" target="_blank">Staun&auml;ssegrad</a></td><td colspan="4" align="middle">Stufe 0 - ohne Staun&auml;sse</td> </tr>
<tr> <td><a href="x">Bodenartengruppe des Oberbodens</a></td><td>Bodenart nach<br>Kartieranleitung<br>(und Gruppe nach GD NRW)</td><td colspan="3">stark toniger Schluff<br>(3 - tonig-schluffig)</td> </tr>
<tr> <td><a href="x">Hauptbodenart<br> nach BBodSchG</a></td><td colspan="4">Lehm/Schluff</td> </tr>
<tr> <td><a href="x">Schutzw&uuml;rdigkeit der B&ouml;den<br>(Auflage 3.2)</a></td><td colspan="4">fruchtbare B&ouml;den mit sehr hoher Funktionserf&uuml;llung</td> </tr>
<tr> <td><a href="https://www.gd.nrw.de/wms_html/bk50_wms/pdf/VER.pdf" target="_blank">Verdichtungsempfindlichkeit</a></td><td colspan="4" align="middle">mittel</td> </tr>
<tr> <td><a href="x">Erodierbarkeit des Oberbodens</a></td><td>0,48</td><td></td><td colspan="2">hoch</td> </tr>
<tr> <td><a href="https://www.gd.nrw.de/wms_html/bk50_wms/pdf/KF.pdf" target="_blank">ges&auml;ttigte Wasserleitf&auml;higkeit</a> <br> im 2-Meter-Raum</td><td align="middle">15</td><td align="middle">cm/d</td><td colspan="2" align="middle">mittel</td> </tr>
<tr> <td><a href="https://www.gd.nrw.de/wms_html/bk50_wms/pdf/SIC.pdf" target="_blank">Versickerungseignung</a> <br> in 2-Meter-Raum</td><td colspan="4" align="middle">ungeeignet - VSA, Mulden-Rigolen-Systeme (Bewirtschaftung mit gedrosselter Ableitung)</td> </tr>
<tr> <td><a href="https://www.gd.nrw.de/wms_html/bk50_wms/pdf/GBK.pdf" target="_blank">Grabbarkeit</a> <br> in 2-Meter-Raum</td><td colspan="4" align="middle">im 1. Meter : mittel grabbar <br> im 2. Meter : mittel grabbar <br> nicht grundnass und nicht staunass</td> </tr>
<tr> <td><a href="https://www.gd.nrw.de/wms_html/bk50_wms/pdf/ERD.pdf" target="_blank">Eignung f&uuml;r Erdw&auml;rmekollektoren</a> <br> Grundwasserstufe beachten!</td><td align="middle">im 1. Meter <br> im 2. Meter</td><td align="middle">1,37 <br> 2,7367</td><td align="middle">W/m/K <br> W/m/K</td><td align="middle">mittel <br> extrem hoch</td> </tr>
</table></body></html>"""
HTML_EMPTY = "<html><body><table><tr><td>FeatureInfo - BK50-WMS</td></tr></table></body></html>"
KF = {"features": [{"attributes": {"GUTACHTEN": "UCON", "KF_WERT": "<1x10-7", "GEEIGNET": "nein", "JAHR": 2000, "ANMERKUNG": "Auffüllung bis zu 1,9m Mächtigkeit"}},
                   {"attributes": {"GUTACHTEN": "Siedek+Kügler", "KF_WERT": "<3x10-6", "GEEIGNET": "nein", "JAHR": 1997, "ANMERKUNG": None}}]}


def stub(monkeypatch, html=HTML, kf=KF):
    monkeypatch.setattr(bg, "_featureinfo_html", lambda lat, lon: html)

    def kfq(lat, lon):
        if isinstance(kf, Exception):
            raise kf
        return kf
    monkeypatch.setattr(bg, "_kf_query", kfq)


def test_parse_rows_by_label():
    rows = bg.parse_bk50_html(HTML)
    assert rows["Bodentyp"] == ["Parabraunerde"]
    assert rows["Staunässegrad"] == ["Stufe 0 - ohne Staunässe"]
    assert rows["gesättigte Wasserleitfähigkeit"] == ["15", "cm/d", "mittel"]
    assert rows["Grabbarkeit"] == ["im 1. Meter : mittel grabbar im 2. Meter : mittel grabbar nicht grundnass und nicht staunass"]
    assert rows["Eignung für Erdwärmekollektoren"] == ["im 1. Meter im 2. Meter", "1,37 2,7367", "W/m/K W/m/K", "mittel extrem hoch"]
    assert "Basisinformationen" not in rows


def test_get_baugrund_essen(monkeypatch):
    stub(monkeypatch)
    d = bg.get_baugrund(51.4300, 7.0050)
    assert d["bodentyp"] == "Parabraunerde" and d["bodenart"] == "stark toniger Schluff (3 - tonig-schluffig)" and d["hauptbodenart"] == "Lehm/Schluff"
    assert d["grundwasser"] == "Stufe 0 - ohne Grundwasser" and d["staunaesse"] == "Stufe 0 - ohne Staunässe"
    assert d["kf_cm_d"] == 15.0 and d["kf_klasse"] == "mittel"
    assert d["versickerung"].startswith("ungeeignet - VSA") and d["versickerung_klasse"] == "ungeeignet"
    assert d["grabbarkeit"].startswith("im 1. Meter : mittel grabbar") and d["verdichtung"] == "mittel" and d["erodierbarkeit"] == "hoch"
    assert d["erdwaerme"] == {"m1_w_mk": 1.37, "m1_klasse": "mittel", "m2_w_mk": 2.7367, "m2_klasse": "extrem hoch"}
    assert d["kf_gutachten"] == [{"gutachten": "UCON", "kf": "<1x10-7", "geeignet": "nein", "jahr": 2000, "anmerkung": "Auffüllung bis zu 1,9m Mächtigkeit"},
                                 {"gutachten": "Siedek+Kügler", "kf": "<3x10-6", "geeignet": "nein", "jahr": 1997, "anmerkung": None}]
    assert d["rating"] == "Schwer versickerbarer Boden" and d["rating_color"] == "orange"


def test_versickerung_classes_and_rating():
    assert bg.versickerung_klasse("geeignet - Versickerung über die Fläche") == "geeignet"
    assert bg.versickerung_klasse("bedingt geeignet - Mulden") == "bedingt geeignet"
    assert bg.versickerung_klasse("ungeeignet - VSA") == "ungeeignet"
    assert bg.versickerung_klasse(None) is None
    assert bg.rate("geeignet", "Stufe 0 - ohne Grundwasser", "Stufe 0 - ohne Staunässe") == ("Unauffälliger Baugrund (BK50)", "green")
    assert bg.rate("bedingt geeignet", "Stufe 0 - ohne Grundwasser", "Stufe 1 - schwach staunass") == ("Eingeschränkte Versickerung", "yellow")
    assert bg.rate("geeignet", "Stufe 3 - mittlerer Grundwassereinfluss", "Stufe 0") == ("Nasser Boden (Grundwasser/Staunässe)", "orange")
    assert bg.rate(None, None, None) == ("Keine Bewertung", "gray")


def test_outside_essen_skips_kf(monkeypatch):
    calls = []
    monkeypatch.setattr(bg, "_featureinfo_html", lambda lat, lon: HTML)
    monkeypatch.setattr(bg, "_kf_query", lambda lat, lon: calls.append(1) or KF)
    d = bg.get_baugrund(51.4818, 7.2162)      # Bochum
    assert d["kf_gutachten"] == [] and calls == []


def test_kf_failure_isolated(monkeypatch):
    stub(monkeypatch, kf=RuntimeError("essen down"))
    d = bg.get_baugrund(51.4300, 7.0050)
    assert d["kf_gutachten"] == [] and d["kf_gutachten_error"] == "essen down" and d["bodentyp"] == "Parabraunerde"


def test_no_soil_unit_is_none(monkeypatch):
    stub(monkeypatch, html=HTML_EMPTY)
    assert bg.get_baugrund(51.4300, 7.0050) is None
```

Registry/tier/render updates: insert `"baugrund"` after `"bergbau"` (before `"radon"`) in the order test; add to the tier list (area); render checks `"baugrund": ["Parabraunerde", "ungeeignet", "Auffüllung"],`; and:

```python
def test_baugrund_passthrough_and_empty(monkeypatch):
    from redat.sources import baugrund
    monkeypatch.setattr(baugrund, "get_baugrund", lambda lat, lon: {"bodentyp": "x"})
    assert S._fetch_baugrund(CTX) == {"bodentyp": "x"}
    monkeypatch.setattr(baugrund, "get_baugrund", lambda lat, lon: None)
    with pytest.raises(Empty):
        S._fetch_baugrund(CTX)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_baugrund.py -q` → `ModuleNotFoundError`.

- [ ] **Step 3: Implement `baugrund.py`**

```python
"""Baugrund & Versickerung — the BK50 soil unit under the point, plus real kf values from Essen Baugrundgutachten.

Source A: GD NRW "IS BK50 Bodenkarte 1:50.000" WMS https://www.wms.nrw.de/gd/bk050 (dl-de/by-2-0).
GetFeatureInfo with INFO_FORMAT=text/html returns one 37-row HTML table for the soil unit with
human-readable values (the esri XML carries only codes) — the same table for every layer, so we ask one
layer (Versickerungseignung). Rows read (label = text of the <a> in the first cell; verified 2026-09-05):
Bodentyp, Grundwasserstufe, Staunässegrad, Bodenartengruppe des Oberbodens, Hauptbodenart nach BBodSchG,
Schutzwürdigkeit der Böden, Verdichtungsempfindlichkeit, Erodierbarkeit des Oberbodens (value, class),
gesättigte Wasserleitfähigkeit (value, "cm/d", class), Versickerungseignung ("ungeeignet - VSA, …"),
Grabbarkeit, Eignung für Erdwärmekollektoren (two depths: values, unit, classes). Versickerung classes
per GD NRW: geeignet ≥ 1·10⁻⁵ m/s, bedingt geeignet 5·10⁻⁶–1·10⁻⁵, ungeeignet below (or staunass).
Scale 1:50,000 → area statement, never grundstücksscharf.

Source B (Essen only): https://geo.essen.de/arcgis/rest/services/essen/Umwelt/MapServer/0 "kf Werte aus
Bauanträgen" — points with GUTACHTEN, KF_WERT ("<1x10-7" m/s), GEEIGNET (ja/nein for Versickerung),
JAHR, ANMERKUNG ("Auffüllung bis zu 1,9m Mächtigkeit"); the Ruhrgebiet-typical hint at Auffüllungen.
`_featureinfo_html` and `_kf_query` are the HTTP calls and monkeypatch points.
"""
from __future__ import annotations

import html as htmlmod
import logging
import re
from typing import Optional

import httpx

from redat.http import headers

logger = logging.getLogger(__name__)

BK50_WMS_URL = "https://www.wms.nrw.de/gd/bk050"
BK50_LAYER = "Versickerungseignung"
KF_URL = "https://geo.essen.de/arcgis/rest/services/essen/Umwelt/MapServer/0/query"
ESSEN_BBOX = (6.89, 51.35, 7.14, 51.53)
KF_RADIUS_M = 300
_TIMEOUT_S = 20
_LABELS = ("Bodentyp", "Grundwasserstufe", "Staunässegrad", "Bodenartengruppe des Oberbodens", "Hauptbodenart",
           "Schutzwürdigkeit der Böden", "Verdichtungsempfindlichkeit", "Erodierbarkeit des Oberbodens",
           "gesättigte Wasserleitfähigkeit", "Versickerungseignung", "Grabbarkeit", "Eignung für Erdwärmekollektoren")


def in_essen(lat: float, lon: float) -> bool:
    lon_min, lat_min, lon_max, lat_max = ESSEN_BBOX
    return lon_min <= lon <= lon_max and lat_min <= lat <= lat_max


def _featureinfo_html(lat: float, lon: float) -> str:
    """BK50 GetFeatureInfo as HTML — HTTP/monkeypatch point."""
    d = 0.001
    params = {"SERVICE": "WMS", "VERSION": "1.3.0", "REQUEST": "GetFeatureInfo", "LAYERS": BK50_LAYER, "QUERY_LAYERS": BK50_LAYER,
              "STYLES": "", "CRS": "EPSG:4326", "BBOX": f"{lat - d:g},{lon - d:g},{lat + d:g},{lon + d:g}", "WIDTH": 101, "HEIGHT": 101,
              "I": 50, "J": 50, "FEATURE_COUNT": 1, "INFO_FORMAT": "text/html"}
    resp = httpx.get(BK50_WMS_URL, params=params, timeout=_TIMEOUT_S, headers=headers())
    resp.raise_for_status()
    return resp.text


def _kf_query(lat: float, lon: float) -> dict:
    """Essen kf-Werte within KF_RADIUS_M — HTTP/monkeypatch point."""
    params = {"f": "json", "where": "1=1", "geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint", "inSR": 4326,
              "spatialRel": "esriSpatialRelIntersects", "distance": KF_RADIUS_M, "units": "esriSRUnit_Meter",
              "outFields": "GUTACHTEN,KF_WERT,GEEIGNET,JAHR,ANMERKUNG", "returnGeometry": "false", "resultRecordCount": 10}
    resp = httpx.get(KF_URL, params=params, timeout=_TIMEOUT_S, headers=headers())
    resp.raise_for_status()
    return resp.json()


def _text(cell_html: str) -> str:
    t = re.sub(r"<br\s*/?>", " ", cell_html)
    t = re.sub(r"<[^>]+>", "", t)
    return re.sub(r"\s+", " ", htmlmod.unescape(t)).strip()


def parse_bk50_html(text: str) -> dict[str, list[str]]:
    """label (text of the <a> in the first cell, matched against _LABELS) → the remaining cells as text."""
    text = re.sub(r"<style.*?</style>", "", text, flags=re.S)
    rows: dict[str, list[str]] = {}
    for tr in re.findall(r"<tr.*?</tr>", text, flags=re.S):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", tr, flags=re.S)
        if len(cells) < 2:
            continue
        m = re.search(r"<a[^>]*>(.*?)</a>", cells[0], flags=re.S)
        label = _text(m.group(1) if m else cells[0])
        key = next((lab for lab in _LABELS if label.startswith(lab)), None)
        if key and key not in rows:
            rows[key] = [_text(c) for c in cells[1:] if _text(c)]
    return rows


def versickerung_klasse(text: Optional[str]) -> Optional[str]:
    low = (text or "").lower()
    if not low:
        return None
    if low.startswith("bedingt"):
        return "bedingt geeignet"
    if low.startswith("ungeeignet"):
        return "ungeeignet"
    if low.startswith("geeignet"):
        return "geeignet"
    return None


def _stufe(text: Optional[str]) -> int:
    m = re.search(r"Stufe\s+(\d)", text or "")
    return int(m.group(1)) if m else 0


def rate(vers: Optional[str], grundwasser: Optional[str], staunaesse: Optional[str]) -> tuple[str, str]:
    if vers is None and not grundwasser and not staunaesse:
        return "Keine Bewertung", "gray"
    wet = max(_stufe(grundwasser), _stufe(staunaesse))
    if wet >= 3:
        return "Nasser Boden (Grundwasser/Staunässe)", "orange"
    if vers == "ungeeignet":
        return "Schwer versickerbarer Boden", "orange"
    if vers == "bedingt geeignet" or wet >= 1:
        return "Eingeschränkte Versickerung", "yellow"
    return "Unauffälliger Baugrund (BK50)", "green"


def _float(s: Optional[str]) -> Optional[float]:
    try:
        return float(str(s).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _first(rows: dict, label: str, i: int = 0) -> Optional[str]:
    cells = rows.get(label) or []
    return cells[i] if len(cells) > i else None


def _erdwaerme(rows: dict) -> Optional[dict]:
    cells = rows.get("Eignung für Erdwärmekollektoren") or []
    if len(cells) < 4:
        return None
    vals, klassen = cells[1].split(), cells[3]
    m = re.match(r"(\S+)\s+(.*)", klassen)
    return {"m1_w_mk": _float(vals[0]) if vals else None, "m1_klasse": m.group(1) if m else klassen,
            "m2_w_mk": _float(vals[1]) if len(vals) > 1 else None, "m2_klasse": m.group(2) if m else None}


def get_baugrund(lat: float, lon: float) -> Optional[dict]:
    rows = parse_bk50_html(_featureinfo_html(lat, lon))
    if not rows.get("Bodentyp"):
        return None
    vers_text = _first(rows, "Versickerungseignung")
    vers = versickerung_klasse(vers_text)
    gw, sn = _first(rows, "Grundwasserstufe"), _first(rows, "Staunässegrad")
    kf_cells = rows.get("gesättigte Wasserleitfähigkeit") or []
    kf_val = _float(kf_cells[0]) if kf_cells else None
    kf_klasse = kf_cells[-1] if len(kf_cells) >= 2 and kf_cells[-1] != "cm/d" else None
    erod = rows.get("Erodierbarkeit des Oberbodens") or []
    bodenart_cells = rows.get("Bodenartengruppe des Oberbodens") or []

    kf_gutachten, kf_error = [], None
    if in_essen(lat, lon):
        try:
            for f in _kf_query(lat, lon).get("features") or []:
                a = f.get("attributes") or {}
                kf_gutachten.append({"gutachten": a.get("GUTACHTEN"), "kf": a.get("KF_WERT"), "geeignet": a.get("GEEIGNET"),
                                     "jahr": a.get("JAHR"), "anmerkung": a.get("ANMERKUNG") or None})
        except Exception as exc:  # noqa: BLE001 — Essen down must not blank the BK50 result
            logger.warning("Essen kf-Werte: %s", exc)
            kf_error = str(exc)

    rating, color = rate(vers, gw, sn)
    return {
        "bodentyp": _first(rows, "Bodentyp"),
        "bodenart": bodenart_cells[-1] if bodenart_cells else None,
        "hauptbodenart": _first(rows, "Hauptbodenart"),
        "grundwasser": gw, "staunaesse": sn,
        "kf_cm_d": kf_val, "kf_klasse": kf_klasse,
        "versickerung": vers_text, "versickerung_klasse": vers,
        "grabbarkeit": _first(rows, "Grabbarkeit"),
        "verdichtung": _first(rows, "Verdichtungsempfindlichkeit"),
        "schutzwuerdigkeit": _first(rows, "Schutzwürdigkeit der Böden"),
        "erodierbarkeit": erod[-1] if erod else None,
        "erdwaerme": _erdwaerme(rows),
        "kf_gutachten": kf_gutachten, "kf_gutachten_error": kf_error,
        "rating": rating, "rating_color": color,
    }
```

- [ ] **Step 4: Registry, summary, partials, fixture**

`sections.py` (area tier, after `_fetch_bergbau`, before `_fetch_radon`):

```python
def _fetch_baugrund(ctx: Ctx) -> dict:
    from redat.sources.baugrund import get_baugrund

    d = get_baugrund(ctx.lat, ctx.lon)
    if d is None:
        raise Empty("Keine Bodeneinheit der BK50 an diesem Punkt (Gewässer oder außerhalb NRW)")
    return d
```

Registry line after `bergbau` (before `radon`):

```python
    Section("baugrund", "Baugrund & Versickerung (BK50)", "🪨", 25,
            "Geologischer Dienst NRW, Bodenkarte 1:50.000 (dl-de/by-2-0) · Stadt Essen, kf-Werte aus Bauanträgen", _fetch_baugrund),
```

`tiers.py`: `"baugrund": "area",`. `sources_meta.py`:

```python
    SourceMeta(("baugrund",), "IS BK50 Bodenkarte NRW · kf-Werte aus Bauanträgen (Essen)", "Geologischer Dienst NRW · Stadt Essen", "dl-de/by-2-0",
               "https://www.wms.nrw.de/gd/bk050 (WMS GetFeatureInfo text/html) · geo.essen.de Umwelt/0", "area", "live; BK50 fortlaufend"),
```

`builder.py`:

```python
def _s_baugrund(d):
    rating, color = _rated(d)
    parts = [p for p in (d.get("bodentyp"), d.get("versickerung_klasse") and f"Versickerung {d['versickerung_klasse']}") if p]
    if d.get("kf_gutachten"):
        parts.append(f"{len(d['kf_gutachten'])} Baugrundgutachten ≤ 300 m")
    return rating, color, " · ".join(parts) or None
```

`"baugrund": _s_baugrund,` after `"bergbau"`.

`redat/templates/analysis/_baugrund.html`:

```html
<div class="flex items-center gap-4">
    <span class="px-3 py-1 rounded-full font-bold" :class="$store.app.getAirQualityColor(d.rating_color)" x-text="d.rating"></span>
    <div class="text-sm text-gray-500">Bodenkarte 1 : 50 000 — Aussage für die Bodeneinheit, nicht grundstücksscharf</div>
</div>
<dl class="mt-4 grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-1 text-sm">
    <template x-for="[k, v] in [['Bodentyp', d.bodentyp], ['Bodenart Oberboden', d.bodenart], ['Hauptbodenart (BBodSchG)', d.hauptbodenart], ['Grundwasser', d.grundwasser], ['Staunässe', d.staunaesse], ['Verdichtungsempfindlichkeit', d.verdichtung], ['Erodierbarkeit', d.erodierbarkeit]]" :key="k">
        <div class="flex justify-between gap-2 border-b border-gray-100 py-0.5" x-show="v"><dt class="text-gray-500" x-text="k"></dt><dd class="text-gray-900 text-right" x-text="v"></dd></div>
    </template>
</dl>
<div class="mt-4 text-sm">
    <div class="font-semibold text-gray-900">💧 Versickerung von Regenwasser</div>
    <p class="text-gray-800" x-text="d.versickerung || 'keine Angabe'"></p>
    <p class="text-xs text-gray-500" x-show="d.kf_cm_d != null" x-text="'Gesättigte Wasserleitfähigkeit im 2-Meter-Raum: ' + d.kf_cm_d + ' cm/d (' + (d.kf_klasse || '—') + '). Geeignet ab ca. 86 cm/d, bedingt geeignet ab ca. 43 cm/d.'"></p>
</div>
<div class="mt-3 text-sm" x-show="d.grabbarkeit">
    <div class="font-semibold text-gray-900">⛏ Grabbarkeit</div>
    <p class="text-gray-800" x-text="d.grabbarkeit"></p>
</div>
<div class="mt-3 text-sm" x-show="d.erdwaerme">
    <div class="font-semibold text-gray-900">🌡 Erdwärmekollektoren</div>
    <p class="text-gray-800" x-text="d.erdwaerme && ('1. Meter ' + d.erdwaerme.m1_w_mk + ' W/(m·K) (' + d.erdwaerme.m1_klasse + '), 2. Meter ' + d.erdwaerme.m2_w_mk + ' W/(m·K) (' + d.erdwaerme.m2_klasse + ')')"></p>
</div>
<template x-if="d.kf_gutachten && d.kf_gutachten.length">
    <div class="mt-4 text-sm">
        <div class="font-semibold text-gray-900">📄 Baugrundgutachten in der Nachbarschaft (Stadt Essen, ≤ 300 m)</div>
        <ul class="mt-1 space-y-0.5">
            <template x-for="(g, i) in d.kf_gutachten" :key="i">
                <li class="text-gray-700"><span class="font-medium" x-text="'kf ' + g.kf + ' m/s'"></span><span x-text="' · Versickerung ' + (g.geeignet === 'ja' ? 'geeignet' : 'nicht geeignet') + (g.jahr ? ' · ' + g.jahr : '') + (g.gutachten ? ' · ' + g.gutachten : '')"></span><span class="text-orange-700" x-show="g.anmerkung" x-text="' · ' + g.anmerkung"></span></li>
            </template>
        </ul>
    </div>
</template>
<p class="mt-3 text-xs text-gray-500">
    Quelle: Geologischer Dienst NRW, IS BK50. Auffüllungen, Bergbau-Halden und verdichtete Böden sind im Ruhrgebiet häufig — vor dem Kauf ein Baugrundgutachten (DIN 4020) einholen, wenn Anbau, Keller oder Versickerung geplant sind.
    <span x-show="d.kf_gutachten_error"> · Essener kf-Werte nicht abrufbar</span>
</p>
```

`redat/templates/report/_baugrund.html`:

```html
<div class="kpis">
  <div class="kpi">
    <div class="label">Baugrund (BK50, nicht grundstücksscharf)</div>
    <div class="value"><span class="chip {{ rating_class(d.get('rating_color')) }}">{{ d.get("rating") or "—" }}</span></div>
  </div>
  <div class="kpi">
    <div class="label">Bodentyp</div>
    <div class="value" style="font-size: 11pt">{{ d.get("bodentyp") or "—" }}</div>
    {% if d.get("bodenart") %}<div class="sub">{{ d.bodenart }}</div>{% endif %}
  </div>
</div>
<table class="mt">
  <tbody>
    {% for label, key in [("Hauptbodenart (BBodSchG)", "hauptbodenart"), ("Grundwasser", "grundwasser"), ("Staunässe", "staunaesse"), ("Versickerungseignung", "versickerung"), ("Grabbarkeit", "grabbarkeit"), ("Verdichtungsempfindlichkeit", "verdichtung"), ("Erodierbarkeit", "erodierbarkeit")] %}
    {% if d.get(key) %}<tr><td class="muted">{{ label }}</td><td>{{ d[key] }}</td></tr>{% endif %}
    {% endfor %}
    {% if d.get("kf_cm_d") is not none %}<tr><td class="muted">Gesättigte Wasserleitfähigkeit</td><td>{{ d.kf_cm_d|fmt_num(0) }} cm/d{% if d.get("kf_klasse") %} ({{ d.kf_klasse }}){% endif %}</td></tr>{% endif %}
    {% set e = d.get("erdwaerme") %}
    {% if e and e.get("m1_w_mk") is not none %}<tr><td class="muted">Erdwärmekollektoren</td><td>1. Meter {{ e.m1_w_mk|fmt_num(2) }} W/(m·K) ({{ e.get("m1_klasse") or "—" }}){% if e.get("m2_w_mk") is not none %}, 2. Meter {{ e.m2_w_mk|fmt_num(2) }} W/(m·K) ({{ e.get("m2_klasse") or "—" }}){% endif %}</td></tr>{% endif %}
  </tbody>
</table>
{% set kf = d.get("kf_gutachten") or [] %}
{% if kf %}
<h3>Baugrundgutachten in der Nachbarschaft (Stadt Essen, ≤ 300 m)</h3>
<table>
  <thead><tr><th>kf-Wert</th><th>Versickerung</th><th>Jahr</th><th>Gutachter</th><th>Anmerkung</th></tr></thead>
  <tbody>
  {% for g in kf %}<tr><td>{{ g.get("kf") or "—" }} m/s</td><td>{{ "geeignet" if g.get("geeignet") == "ja" else "nicht geeignet" }}</td><td>{{ g.get("jahr") or "—" }}</td><td>{{ g.get("gutachten") or "—" }}</td><td>{{ g.get("anmerkung") or "" }}</td></tr>{% endfor %}
  </tbody>
</table>
{% endif %}
<p class="footnote">Geologischer Dienst NRW, IS BK50 (1 : 50 000) — Aussage für die Bodeneinheit. Versickerung: geeignet ab ca. 86 cm/d, bedingt geeignet ab ca. 43 cm/d. Vor Anbau, Keller oder Versickerungsanlage ein Baugrundgutachten einholen.</p>
```

Fixture `"baugrund"`:

```json
"baugrund": {"key": "baugrund", "tier": "area", "status": "ok", "message": null, "took_ms": 910,
  "source": "Geologischer Dienst NRW, Bodenkarte 1:50.000 (dl-de/by-2-0) · Stadt Essen, kf-Werte aus Bauanträgen",
  "data": {"bodentyp": "Parabraunerde", "bodenart": "stark toniger Schluff (3 - tonig-schluffig)", "hauptbodenart": "Lehm/Schluff",
           "grundwasser": "Stufe 0 - ohne Grundwasser", "staunaesse": "Stufe 0 - ohne Staunässe", "kf_cm_d": 15.0, "kf_klasse": "mittel",
           "versickerung": "ungeeignet - VSA, Mulden-Rigolen-Systeme (Bewirtschaftung mit gedrosselter Ableitung)", "versickerung_klasse": "ungeeignet",
           "grabbarkeit": "im 1. Meter : mittel grabbar im 2. Meter : mittel grabbar nicht grundnass und nicht staunass", "verdichtung": "mittel",
           "schutzwuerdigkeit": "fruchtbare Böden mit sehr hoher Funktionserfüllung", "erodierbarkeit": "hoch",
           "erdwaerme": {"m1_w_mk": 1.37, "m1_klasse": "mittel", "m2_w_mk": 2.7367, "m2_klasse": "extrem hoch"},
           "kf_gutachten": [{"gutachten": "UCON", "kf": "<1x10-7", "geeignet": "nein", "jahr": 2000, "anmerkung": "Auffüllung bis zu 1,9m Mächtigkeit"}],
           "kf_gutachten_error": null, "rating": "Schwer versickerbarer Boden", "rating_color": "orange"}}
```

- [ ] **Step 5: Run the whole suite**

Run: `.venv/bin/python -m pytest -q` → green.

- [ ] **Step 6: Commit**

```bash
git add redat/sources/baugrund.py redat/templates/analysis/_baugrund.html redat/templates/report/_baugrund.html redat/core redat/report/builder.py tests/
git commit -m "feat(baugrund): BK50 soil unit and Essen kf-Werte card"
```

---

### Task 14: Documentation, CSS build, final verification

**Files:**
- Modify: `README.md` (static data + build scripts, new cards), `HANDOVER.md` (work log entry, card count), `CLAUDE.md` (card/test counts, data files), `redat/static/redat.css` (rebuilt)

- [ ] **Step 1: README**

In the README's geodata section add a subsection after the `data/source/` table:

```markdown
### Static grids in the repo (`redat/data/`)

Small, gzipped JSON extracts that ship with the code (no download at deploy time):

| File | Built by | Source | Refresh |
|---|---|---|---|
| `zensus_2022_grid.json.gz` | `scripts/build_zensus_grid.py` | Destatis Zensus 2022 Gitterdaten | one-off |
| `eea_aq_grid_2023.json` | `scripts/build_eea_aq_grid.py` | EEA 1 km air-quality maps | yearly |
| `schulen_nrw.json.gz` | `scripts/build_schulen.py --shape … --sozialindex …` | opengeodata Schulstandorte NRW + Schulministerium Schulliste (Sozialindex) | each Schuljahr (autumn) |
| `unfallatlas_2020_2025.json.gz` | `scripts/build_unfallatlas.py --src …` | Unfallatlas CSV zips (opengeodata.nrw.de) | yearly (July), extend `YEARS` and rename the file |

The build scripts' module docstrings carry the download URLs and the exact commands.
```

Also list the six new cards in the README's card overview (wherever the 20 cards are listed) with one line each: Flurstück & Gebäude (ALKIS + Baulasten Essen), Immobilienrichtwerte, Baugrund & Versickerung (BK50), Radon (BfS), Schulen & Sozialindex, Verkehrsunfälle (Unfallatlas); and note the flood/planning extensions.

- [ ] **Step 2: HANDOVER work log**

Append under the work log:

```markdown
- **Tier-1 sources** (2026-09-05, plan `docs/superpowers/plans/2026-09-05-tier1-sources.md`, spec
  `docs/superpowers/specs/2026-09-05-tier1-sources-design.md`) — six new cards (`flurstueck`, `irw`, `baugrund`,
  `radon`, `schulen`, `unfaelle`) and three extensions (`flood` + ÜSG §78 WHG, `planning_essen` + Satzungen/
  Sanierung, `planning_bochum` + Stadterneuerung; all three at `cache_version=2`). New shared helper
  `redat/sources/esri_wms.py`. Two new static grids under `redat/data/` with build scripts. The ALKIS WFS proxy
  only accepts TYPENAMES+BBOX(EPSG:25832) and answers GML — no JSON, no CQL. The BfS WFS bbox is lon,lat.
  The BK50 WMS is read as HTML because only the HTML carries readable class labels.
```

Update the "Status" line's card and test counts to the numbers `pytest -q` prints.

- [ ] **Step 3: CLAUDE.md**

Change "the 20-card `SECTIONS` registry" to "the 26-card `SECTIONS` registry", the test count in the `pytest` comment to the current number, and add `alkis.py` style hints to the Rules list:

```markdown
- WFS/WMS quirks that cost a day each: the ALKIS WFS proxy accepts only `TYPENAMES` + `BBOX` in EPSG:25832 and returns GML (no JSON/CQL/SRSNAME); LINFOS wants an EPSG:25832 bbox; the BfS WFS wants `bbox` in lon,lat; wms.nrw.de GetFeatureInfo uses lat,lon (WMS 1.3.0) — reuse `redat/sources/esri_wms.py`.
```

- [ ] **Step 4: Rebuild Tailwind CSS**

New partials use only utility classes already present elsewhere (`bg-gray-800`, `text-orange-700`, `w-14`, `h-12`, `rounded-t` may be new) — rebuild so the minified sheet contains them:

```bash
npx tailwindcss@3 -c tailwind.config.js -i tailwind.input.css -o redat/static/redat.css --minify
git diff --stat redat/static/redat.css
```

- [ ] **Step 5: Full verification**

```bash
.venv/bin/python -m pytest -q                      # all green; note the count for HANDOVER/CLAUDE.md
GEOAPIFY_API_KEY=… .venv/bin/python scripts/smoke_analyze.py "Herthastraße 4, 45131 Essen"   # if the smoke script takes an address; otherwise start uvicorn and open /?address=Herthastraße 4, Essen&auto=1
```

Check by hand in the browser: the Flurstück card shows 538 m² and offers "Als Grundstücksgröße übernehmen"; the flood card shows the ÜSG block for an address on the Ruhr (e.g. "Bochumer Landstraße 300, Essen"); IRW lists three Teilmärkte in Rüttenscheid; Baugrund shows "Parabraunerde"; Radon shows the Karbon cell; Schulen lists the Käthe-Kollwitz-Schule; Unfälle renders the per-year bars; the PDF report renders every new card (`/api/v1/report`).

- [ ] **Step 6: Commit**

```bash
git add README.md HANDOVER.md CLAUDE.md redat/static/redat.css
git commit -m "docs: Tier-1 sources — README data grids, HANDOVER log, CLAUDE.md counts; rebuild CSS"
```
