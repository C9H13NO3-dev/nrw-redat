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


def test_non_image_response_does_not_leak_raw_body_into_the_report(monkeypatch):
    """Minor 5: the WMS response body must never reach the German error string in the PDF."""
    class R:
        status_code = 200
        headers = {"content-type": "text/xml"}
        text = "<ServiceExceptionReport><ServiceException>secret internal detail</ServiceException>"

        def raise_for_status(self):
            pass

    monkeypatch.setattr(rm.httpx, "get", lambda url, params, timeout, headers: R())
    warnings = []
    monkeypatch.setattr(rm.logger, "warning", lambda *a, **k: warnings.append((a, k)))
    out = rm.render_regionalplan_map(50.716, 7.075)
    assert out["image"] is None
    assert "secret internal detail" not in out["error"]
    assert out["error"] == "Regionalplan-Ausschnitt nicht verfügbar (WMS lieferte kein Bild)"
    assert any("secret internal detail" in repr(a) for a, k in warnings)
