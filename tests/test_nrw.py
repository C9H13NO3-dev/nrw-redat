from redat.core import nrw


def test_bboxes_are_lon_lat_ordered():
    for b in (nrw.NRW_BBOX_WGS84, nrw.RVR_BBOX_WGS84, nrw.ESSEN_BBOX_WGS84, nrw.BOCHUM_BBOX_WGS84):
        assert b[0] < b[2] and b[1] < b[3]


def test_in_bbox_points():
    assert nrw.in_bbox(50.7160, 7.0748)                       # Bonn
    assert nrw.in_bbox(51.4300, 7.0050, nrw.ESSEN_BBOX_WGS84)
    assert not nrw.in_bbox(52.37, 4.90)                       # Amsterdam
    assert not nrw.in_bbox(50.7160, 7.0748, nrw.RVR_BBOX_WGS84)


def test_bbox_3035_covers_nrw_and_is_stable():
    xmin, ymin, xmax, ymax = nrw.bbox_3035()
    assert 4_018_000 < xmin < 4_019_000 and 4_293_000 < xmax < 4_294_000
    assert 3_014_000 < ymin < 3_015_000 and 3_287_000 < ymax < 3_288_000
    exmin, eymin, exmax, eymax = nrw.bbox_25832(nrw.ESSEN_BBOX_WGS84)
    assert exmin < exmax and eymin < eymax and 350_000 < exmin < 380_000
