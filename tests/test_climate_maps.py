import base64
import io

from PIL import Image

from redat.report import climate_maps as cm


def _png(size, color):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def test_two_panels_with_legends_over_2km(monkeypatch):
    calls = []

    def fake(url, params):
        calls.append(params)  # list.append() is a single atomic op under the GIL
        if params.get("REQUEST") == "GetLegendGraphic":
            return _png((88, 50), (200, 50, 50))
        return _png((cm.WIDTH, cm.HEIGHT), (120, 160, 120))
    monkeypatch.setattr(cm, "_get_png", fake)
    out = cm.render_climate_maps(51.43, 7.005)
    assert [p["key"] for p in out["panels"]] == ["beschirmung", "oberflaechentemperatur"]
    assert all(p["image"] and p["legend"] for p in out["panels"]) and out["error"] is None
    maps = [p for p in calls if p.get("REQUEST") == "GetMap"]
    xmin, ymin, xmax, ymax = (float(v) for v in maps[0]["BBOX"].split(","))
    assert abs((xmax - xmin) - 2000) < 0.01 and maps[0]["CRS"] == "EPSG:25832"
    legends = [p for p in calls if p.get("REQUEST") == "GetLegendGraphic"]
    assert all(p["SLD_VERSION"] == "1.1.0" for p in legends) and {p["STYLE"] for p in legends} == {"default", "day"}
    assert Image.open(io.BytesIO(base64.b64decode(out["panels"][0]["image"]))).size == (cm.WIDTH, cm.HEIGHT)


def test_legend_failure_keeps_panel(monkeypatch):
    def fake(url, params):
        if params.get("REQUEST") == "GetLegendGraphic":
            raise RuntimeError("no legend")
        return _png((cm.WIDTH, cm.HEIGHT), (120, 160, 120))
    monkeypatch.setattr(cm, "_get_png", fake)
    out = cm.render_climate_maps(51.43, 7.005)
    assert out["panels"][0]["image"] and out["panels"][0]["legend"] is None and "no legend" in out["error"]


def test_map_failure_is_none(monkeypatch):
    def fake(url, params):
        if params.get("LAYERS") == "beschirmungsgrad":
            raise RuntimeError("down")
        return _png((88, 50), (1, 2, 3))
    monkeypatch.setattr(cm, "_get_png", fake)
    out = cm.render_climate_maps(51.43, 7.005)
    assert out["panels"][0]["image"] is None and "down" in out["error"]
