import base64
import io

from PIL import Image

from redat.report import history_maps as hm
from redat.report.noise_map import HEIGHT, WIDTH


def _png(color):
    buf = io.BytesIO()
    Image.new("RGB", (WIDTH, HEIGHT), color).save(buf, format="PNG")
    return buf.getvalue()


def test_four_panels_with_titles_and_fallback_year(monkeypatch):
    calls = []

    def fake(url, params):
        calls.append((url, params["LAYERS"]))
        if params["LAYERS"] == "nw_hist_dop_1952":
            return _png((255, 255, 255))      # blank tile → fall back to 1951
        return _png((120, 120, 120))
    monkeypatch.setattr(hm, "_get_png", fake)
    out = hm.render_history_maps(51.43, 7.005)
    assert [p["key"] for p in out["panels"]] == ["uraufnahme", "neuaufnahme", "dop_alt", "dop"]
    assert [p["title"] for p in out["panels"]] == ["Preußische Uraufnahme (1836–1850)", "Preußische Neuaufnahme (1891–1912)", "Luftbild 1951", "Luftbild heute"]
    assert all(Image.open(io.BytesIO(base64.b64decode(p["image"]))).size == (WIDTH, HEIGHT) for p in out["panels"])
    layers = [l for _, l in calls]
    assert "nw_uraufnahme_rw" in layers and "nw_neuaufnahme" in layers and "nw_dop_rgb" in layers
    assert layers.index("nw_hist_dop_1952") < layers.index("nw_hist_dop_1951")
    assert out["error"] is None and "Geobasis NRW" in out["attribution"]


def test_failed_panel_is_none_and_reported(monkeypatch):
    def fake(url, params):
        if "uraufnahme" in url:
            raise RuntimeError("WMS down")
        return _png((120, 120, 120))
    monkeypatch.setattr(hm, "_get_png", fake)
    out = hm.render_history_maps(51.43, 7.005)
    assert out["panels"][0]["image"] is None and "WMS down" in out["error"] and out["panels"][1]["image"]


def test_all_hist_dop_years_blank_gives_none_panel(monkeypatch):
    monkeypatch.setattr(hm, "_get_png", lambda url, params: _png((255, 255, 255)) if "hist_dop" in url else _png((90, 90, 90)))
    out = hm.render_history_maps(51.43, 7.005)
    dop_alt = out["panels"][2]
    assert dop_alt["image"] is None and dop_alt["title"] == "Luftbild 1950er" and "kein historisches Luftbild" in out["error"]


def test_is_blank():
    assert hm.is_blank(Image.new("RGBA", (10, 10), (255, 255, 255, 255)))
    assert not hm.is_blank(Image.new("RGBA", (10, 10), (100, 100, 100, 255)))
