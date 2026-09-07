import base64
import io
import math

from PIL import Image

from redat.report import climate_maps as cm

BONN = (50.7160, 7.0748)


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


def test_outside_rvr_uses_copernicus_and_klimaanalyse_panels(monkeypatch):
    calls = []

    def fake(url, params):
        calls.append((url, params))
        if params.get("REQUEST") == "GetLegendGraphic":
            return _png((276, 126), (200, 50, 50))
        return _png((cm.WIDTH, cm.HEIGHT), (120, 160, 120))
    monkeypatch.setattr(cm, "_get_png", fake)
    out = cm.render_climate_maps(*BONN)
    assert out["variant"] == "nrw" and [p["key"] for p in out["panels"]] == ["baumkronen", "pet"]
    assert "Copernicus" in out["attribution"] and "Klimaanalyse" in out["attribution"] and out["error"] is None
    by_layer = {p["LAYERS"]: (u, p) for u, p in calls if p.get("REQUEST") == "GetMap"}
    hrl_url, hrl = by_layer["HRL_TreeCoverDensity_2018:TCD_MosaicSymbology"]
    assert hrl_url == cm.HRL_URL and hrl["CRS"] == "EPSG:3857"
    xmin, ymin, xmax, ymax = (float(v) for v in hrl["BBOX"].split(","))
    assert abs((xmax - xmin) - 2000 / math.cos(math.radians(BONN[0]))) < 1.0
    pet_url, pet = by_layer["54"]
    assert pet_url == cm.KLIMA_URL and pet["CRS"] == "EPSG:25832"
    legends = [p for u, p in calls if p.get("REQUEST") == "GetLegendGraphic"]
    assert [p["LAYER"] for p in legends] == ["54"]                       # the Copernicus ramp legend is skipped on purpose
    assert out["panels"][0]["legend"] is None and out["panels"][1]["legend"]


def test_inside_rvr_keeps_the_rvr_panels(monkeypatch):
    monkeypatch.setattr(cm, "_get_png", lambda url, params: _png((cm.WIDTH, cm.HEIGHT), (1, 2, 3)))
    out = cm.render_climate_maps(51.43, 7.005)
    assert out["variant"] == "rvr" and [p["key"] for p in out["panels"]] == ["beschirmung", "oberflaechentemperatur"]


def test_bbox_2km_3857_scales_with_latitude():
    xmin, ymin, xmax, ymax = cm.bbox_2km_3857(*BONN)
    assert abs((xmax - xmin) - 2000 / math.cos(math.radians(BONN[0]))) < 1.0
    assert abs((ymax - ymin) - 1500 / math.cos(math.radians(BONN[0]))) < 1.0


def test_transparent_pixels_are_flattened_onto_white(monkeypatch):
    def fake(url, params):
        if params.get("REQUEST") == "GetLegendGraphic":
            return _png((276, 126), (200, 50, 50))
        buf = io.BytesIO()
        Image.new("RGBA", (cm.WIDTH, cm.HEIGHT), (0, 0, 0, 0)).save(buf, format="PNG")   # fully transparent tile
        return buf.getvalue()
    monkeypatch.setattr(cm, "_get_png", fake)
    out = cm.render_climate_maps(*BONN)
    im = Image.open(io.BytesIO(base64.b64decode(out["panels"][0]["image"]))).convert("RGB")
    assert im.getpixel((cm.WIDTH - 5, cm.HEIGHT // 2)) == (255, 255, 255)
