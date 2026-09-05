from redat.report.svg import boris_trend_svg


def test_svg_has_one_point_per_year_and_labels():
    svg = boris_trend_svg([{"year": 2022, "value": 600.0}, {"year": 2024, "value": 650.0}, {"year": 2025, "value": 670.0}])
    assert svg.startswith("<svg")
    assert svg.count("<polyline") == 1
    assert svg.count("<circle") == 3
    for label in ("2022", "2024", "2025", "600", "670"):
        assert label in svg


def test_svg_flat_series_does_not_divide_by_zero():
    svg = boris_trend_svg([{"year": 2022, "value": 670.0}, {"year": 2025, "value": 670.0}])
    assert "<polyline" in svg and "nan" not in svg.lower()


def test_svg_ignores_null_values_and_returns_none_when_too_few():
    assert boris_trend_svg([]) is None
    assert boris_trend_svg([{"year": 2022, "value": None}, {"year": 2025, "value": 670.0}]) is None
    assert boris_trend_svg(None) is None
