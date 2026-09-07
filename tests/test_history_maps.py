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
    seen_layers = set()  # stubbed _get_png now runs from worker threads: key by params, not call order

    def fake(url, params):
        seen_layers.add(params["LAYERS"])  # set.add() is a single atomic op under the GIL
        if params["LAYERS"] == "nw_hist_dop_1952":
            return _png((255, 255, 255))      # blank tile → 1951 wins instead
        return _png((120, 120, 120))
    monkeypatch.setattr(hm, "_get_png", fake)
    out = hm.render_history_maps(51.43, 7.005)
    assert [p["key"] for p in out["panels"]] == ["uraufnahme", "neuaufnahme", "dop_alt", "dop"]
    assert [p["title"] for p in out["panels"]] == ["Preußische Uraufnahme (1836–1850)", "Preußische Neuaufnahme (1891–1912)", "Luftbild 1951", "Luftbild heute"]
    assert all(Image.open(io.BytesIO(base64.b64decode(p["image"]))).size == (WIDTH, HEIGHT) for p in out["panels"])
    # both 1952 (blank) and 1951 (the winner) must have been requested — all years are fetched concurrently
    assert {"nw_uraufnahme_rw", "nw_neuaufnahme", "nw_dop_rgb", "nw_hist_dop_1951", "nw_hist_dop_1952", "nw_hist_dop_1957", "nw_hist_dop_1959"} <= seen_layers
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


def test_all_panels_fail_render_still_completes(monkeypatch):
    def fake(url, params):
        raise RuntimeError("WMS down")
    monkeypatch.setattr(hm, "_get_png", fake)
    out = hm.render_history_maps(51.43, 7.005)  # must not raise
    assert [p["key"] for p in out["panels"]] == ["uraufnahme", "neuaufnahme", "dop_alt", "dop"]
    assert [p["image"] for p in out["panels"]] == [None, None, None, None]
    assert out["error"] is not None and "WMS down" in out["error"]
