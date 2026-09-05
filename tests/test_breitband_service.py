"""backend/breitband_service.py — Breitbandatlas tile classification, hermetic (tiles are stubbed)."""
import ssl

import pytest
from PIL import Image

from redat.sources import breitband as bb


def _tile(rgb, alpha=255, size=21, borders=False):
    """A uniform tile; with borders=True the outer ring is the atlas' dark grid-line colour."""
    img = Image.new("RGBA", (size, size), rgb + (alpha,))
    if borders:
        px = img.load()
        for i in range(size):
            for j in (0, size - 1):
                px[i, j] = (37, 42, 45, 255)
                px[j, i] = (37, 42, 45, 255)
    return img


def _stub(mapping):
    """mapping: logical key (ftth_1000/hh_1000/…/telekom/…) -> tile image."""
    by_layer = {**{bb.FIXED_LAYERS[k]: v for k, v in mapping.items() if k in bb.FIXED_LAYERS},
                **{bb.MOBILE_LAYERS[k]: v for k, v in mapping.items() if k in bb.MOBILE_LAYERS}}

    def fake(layer, lat, lon):
        if layer not in by_layer:
            return _tile((0, 0, 0), alpha=0)
        return by_layer[layer]
    return fake


def test_cell_center_snaps_to_100m_grid():
    lat, lon = bb.cell_center(51.4378, 7.0053)
    # same cell → same centre; a point 100 m east → different centre
    assert bb.cell_center(51.43781, 7.00531) == (lat, lon)
    assert bb.cell_center(51.4378, 7.0073) != (lat, lon)
    assert abs(lat - 51.4378) < 0.001 and abs(lon - 7.0053) < 0.002


def test_dominant_ignores_grid_lines_and_transparent():
    assert bb._dominant(_tile((51, 111, 145), borders=True), bb.COVERAGE_CLASSES) == bb.COVERAGE_CLASSES[0]
    assert bb._dominant(_tile((0, 0, 0), alpha=0), bb.COVERAGE_CLASSES) is None
    assert bb._dominant(_tile((37, 42, 45)), bb.COVERAGE_CLASSES) is None  # only borders → no data


def test_full_fibre_cell(monkeypatch):
    monkeypatch.setattr(bb, "_get_tile", _stub({
        "ftth_1000": _tile((51, 111, 145)), "hh_1000": _tile((51, 111, 145)),
        "hh_400": _tile((51, 111, 145)), "hh_100": _tile((51, 111, 145)),
        "telekom": _tile((247, 187, 61)), "vodafone": _tile((247, 187, 61)),
        "o2": _tile((247, 187, 61)), "1u1": _tile((251, 221, 158)),
    }))
    d = bb.get_breitband(51.4378, 7.0053)
    assert d["rating"] == "Glasfaser verfügbar" and d["rating_color"] == "green"
    assert d["fixed"]["ftth_1000"] == {"label": "> 95 %", "min_pct": 95, "step": 5}
    assert d["mobile_5g"] == {"telekom": "5G", "vodafone": "5G", "o2": "5G", "1u1": "5G-Roaming"}
    assert d["cell_m"] == 100 and d["datenstand"] == bb.DATENSTAND and d["errors"] == {}


def test_rating_ladder(monkeypatch):
    def run(ftth, hh1000, hh100):
        monkeypatch.setattr(bb, "_get_tile", _stub({"ftth_1000": ftth, "hh_1000": hh1000, "hh_100": hh100}))
        d = bb.get_breitband(51.4, 7.0)
        return d["rating"], d["rating_color"]
    none = _tile((0, 0, 0), alpha=0)
    assert run(_tile((204, 230, 232)), none, none) == ("Glasfaser teilweise", "yellow")       # 50–75 %
    assert run(_tile((254, 249, 216)), _tile((51, 111, 145)), none) == ("Gigabit (Kabel), kein Glasfaser", "yellow")
    assert run(none, _tile((252, 228, 177)), _tile((102, 179, 185))) == ("≥ 100 Mbit/s, kein Gigabit", "orange")
    assert run(none, none, _tile((252, 228, 177))) == ("Unterversorgt", "red")
    # a missing layer is None in the payload, not an error
    monkeypatch.setattr(bb, "_get_tile", _stub({"hh_100": _tile((252, 228, 177))}))
    d = bb.get_breitband(51.4, 7.0)
    assert d["fixed"]["ftth_1000"] is None and d["mobile_5g"]["telekom"] is None


def test_all_transparent_is_none(monkeypatch):
    monkeypatch.setattr(bb, "_get_tile", _stub({}))
    assert bb.get_breitband(52.52, 13.40) is None


def test_layer_failure_is_isolated(monkeypatch):
    good = _stub({"ftth_1000": _tile((51, 111, 145))})

    def flaky(layer, lat, lon):
        if layer == bb.MOBILE_LAYERS["telekom"]:
            raise RuntimeError("boom")
        return good(layer, lat, lon)
    monkeypatch.setattr(bb, "_get_tile", flaky)
    d = bb.get_breitband(51.4, 7.0)
    assert d["rating_color"] == "green" and "telekom" in d["errors"] and d["mobile_5g"]["telekom"] is None


def test_all_layers_failing_raises(monkeypatch):
    def broken(layer, lat, lon):
        raise RuntimeError("down")
    monkeypatch.setattr(bb, "_get_tile", broken)
    with pytest.raises(RuntimeError):
        bb.get_breitband(51.4, 7.0)


def test_ssl_context_loads_bundle():
    assert bb.CA_BUNDLE.exists()
    ctx = bb._ssl_context()
    assert isinstance(ctx, ssl.SSLContext) and ctx.verify_mode == ssl.CERT_REQUIRED
    subjects = {tuple(dict(x[0] for x in c["subject"]).items()) for c in ctx.get_ca_certs()}
    assert any(("commonName", "YE2") in s for s in subjects)
    assert any(("commonName", "Root YE") in s for s in subjects)
