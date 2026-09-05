from redat.sources import btw


def test_paths_follow_settings():
    from redat.settings import get_settings
    assert btw.data_dir() == get_settings().source_dir / "elections" / "btw25"
    assert btw.shp_path().name == "btw25_geometrie_wahlkreise_vg250_shp_geo.shp"


def test_import_does_not_create_directories():
    # the old module mkdir'ed at import; REDAT must not touch the filesystem on import
    assert not btw.data_dir().exists()
