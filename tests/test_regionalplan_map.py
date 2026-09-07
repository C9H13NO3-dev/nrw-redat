import base64
import io

from PIL import Image

from redat.report import regionalplan_map as rm


def _png(size, color):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def test_panel_over_2km_window(monkeypatch):
    seen = {}

    def fake(url, params):
        seen.update(url=url, params=params)
        return _png((rm.WIDTH, rm.HEIGHT), (229, 204, 115))
    monkeypatch.setattr(rm, "_get_png", fake)
    out = rm.render_regionalplan_map(50.716, 7.075)
    assert out["error"] is None and out["legend_url"] == rm.LEGEND_URL
    im = Image.open(io.BytesIO(base64.b64decode(out["image"])))
    assert im.size == (rm.WIDTH, rm.HEIGHT)
    assert seen["url"] == rm.WMS_URL and seen["params"]["LAYERS"] == "regionalplan" and seen["params"]["CRS"] == "EPSG:25832"
    xmin, ymin, xmax, ymax = (float(v) for v in seen["params"]["BBOX"].split(","))
    assert 1990 < xmax - xmin < 2010


def test_failure_is_none_with_german_error(monkeypatch):
    def boom(url, params):
        raise RuntimeError("WMS down")
    monkeypatch.setattr(rm, "_get_png", boom)
    out = rm.render_regionalplan_map(50.716, 7.075)
    assert out["image"] is None and "Regionalplan" in out["error"] and "WMS down" in out["error"]
