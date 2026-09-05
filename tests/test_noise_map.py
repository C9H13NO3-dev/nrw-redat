"""Tests for report.noise_map — WMS composites for the PDF (HTTP stubbed)."""
import base64
import io

import pytest
from PIL import Image

from redat.report import noise_map
from redat.report.noise_map import HEIGHT, WIDTH, bbox_25832, render_noise_maps


def _png(color, mode="RGBA"):
    buf = io.BytesIO()
    Image.new(mode, (WIDTH, HEIGHT), color).save(buf, format="PNG")
    return buf.getvalue()


def test_bbox_is_600_by_450_m_around_the_point():
    minx, miny, maxx, maxy = bbox_25832(51.3885, 7.0035)
    assert maxx - minx == pytest.approx(600, abs=1e-6)
    assert maxy - miny == pytest.approx(450, abs=1e-6)
    assert 360_000 < minx < 361_500 and 5_694_000 < miny < 5_696_000  # UTM32 Essen-Werden


def test_composites_have_expected_size_and_legend(monkeypatch):
    calls = []

    def fake_get(url, params):
        calls.append((url, params))
        return _png((200, 200, 200, 255)) if "basemapde" in url else _png((205, 70, 62, 255))

    monkeypatch.setattr(noise_map, "_get_png", fake_get)
    out = render_noise_maps(51.3885, 7.0035)
    assert out["error"] is None
    for key in ("day", "night"):
        im = Image.open(io.BytesIO(base64.b64decode(out[key])))
        assert im.size == (WIDTH, HEIGHT)
        assert im.mode == "RGB"
    layers = [p["LAYERS"] for _, p in calls if "laerm" in _]
    assert "STR_DEN,SCB_DEN,SCS_DEN,IND_DEN,FLG_DEN" in layers and "STR_NGT,SCB_NGT,SCS_NGT,IND_NGT,FLG_NGT" in layers
    assert all(p["CRS"] == "EPSG:25832" and p["WIDTH"] == WIDTH for _, p in calls)
    assert len(out["legend"]) >= 6 and out["legend"][0]["color"].startswith("#")
    assert "basemap.de" in out["attribution"]


def test_overlay_failure_yields_none_for_that_map_but_keeps_the_other(monkeypatch):
    def fake_get(url, params):
        if "basemapde" in url:
            return _png((200, 200, 200, 255))
        if "_NGT" in params["LAYERS"]:
            raise RuntimeError("WMS down")
        return _png((205, 70, 62, 255))

    monkeypatch.setattr(noise_map, "_get_png", fake_get)
    out = render_noise_maps(51.3885, 7.0035)
    assert out["day"] is not None
    assert out["night"] is None
    assert "WMS down" in out["error"]


def test_basemap_failure_draws_overlay_on_white(monkeypatch):
    def fake_get(url, params):
        if "basemapde" in url:
            raise RuntimeError("no basemap")
        return _png((255, 255, 255, 0))  # fully transparent overlay

    monkeypatch.setattr(noise_map, "_get_png", fake_get)
    out = render_noise_maps(51.3885, 7.0035)
    assert out["day"] is not None
    im = Image.open(io.BytesIO(base64.b64decode(out["day"]))).convert("RGB")
    assert im.getpixel((5, 5)) == (255, 255, 255)
    assert "no basemap" in out["error"]
