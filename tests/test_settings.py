from pathlib import Path

import pytest

from redat import settings as s


def test_defaults_from_yaml_when_env_empty(tmp_path):
    cfg = s.load_settings(env={"GEOAPIFY_API_KEY": "k"}, yaml_path=None)
    assert cfg.geoapify_api_key == "k"
    assert cfg.api_key is None
    assert cfg.cache_ttl_s == 30 * 86400          # 30 days: the cache is persistent and per-section now
    assert cfg.cache_ttls == {} and cfg.cache_max_entries == 100_000 and cfg.cache_max_bytes == 256 * 1024 * 1024
    assert cfg.public_url == "http://192.168.188.64:8200"
    assert cfg.log_level == "INFO"
    assert [d.name for d in cfg.destinations] == ["Essen Hbf", "Bochum Hbf", "Düsseldorf Hbf"]
    assert cfg.destinations[0].group == "hbf" and cfg.destinations[0].lat == pytest.approx(51.4508)
    assert cfg.oepnv_stops == (("Essen Hbf", "de:05113:9289"), ("Bochum Hbf", "de:05911:5194"), ("Düsseldorf Hbf", "de:05111:18235"))
    assert cfg.data_dir == Path("data").resolve()
    assert cfg.source_dir == cfg.data_dir / "source" and cfg.db_path == cfg.data_dir / "redat.db"


def test_env_overrides_yaml(tmp_path):
    y = tmp_path / "s.yaml"
    y.write_text("cache_ttl_s: 5\npublic_url: http://yaml\ndestinations: []\noepnv_stops: []\n")
    cfg = s.load_settings(env={"GEOAPIFY_API_KEY": "k", "REDAT_CACHE_TTL_S": "9", "REDAT_PUBLIC_URL": "http://env",
                               "REDAT_API_KEY": "secret", "REDAT_DATA_DIR": str(tmp_path / "d"), "REDAT_LOG_LEVEL": "debug"},
                          yaml_path=y)
    assert cfg.cache_ttl_s == 9 and cfg.public_url == "http://env" and cfg.api_key == "secret"
    assert cfg.data_dir == tmp_path / "d" and cfg.log_level == "DEBUG"
    assert cfg.destinations == () and cfg.oepnv_stops == ()


def test_yaml_used_when_env_missing(tmp_path):
    y = tmp_path / "s.yaml"
    y.write_text("cache_ttl_s: 5\nsection_timeouts: {infrastruktur: 90}\n")
    cfg = s.load_settings(env={"GEOAPIFY_API_KEY": "k"}, yaml_path=y)
    assert cfg.cache_ttl_s == 5 and cfg.section_timeouts == {"infrastruktur": 90.0}


def test_missing_geoapify_key_fails_loudly():
    with pytest.raises(s.SettingsError, match="GEOAPIFY_API_KEY"):
        s.load_settings(env={}, yaml_path=None)


def test_bad_ttl_fails_loudly():
    with pytest.raises(s.SettingsError, match="REDAT_CACHE_TTL_S"):
        s.load_settings(env={"GEOAPIFY_API_KEY": "k", "REDAT_CACHE_TTL_S": "soon"}, yaml_path=None)


def test_empty_api_key_env_means_unset():
    cfg = s.load_settings(env={"GEOAPIFY_API_KEY": "k", "REDAT_API_KEY": ""}, yaml_path=None)
    assert cfg.api_key is None


def test_get_settings_is_cached_and_resettable(monkeypatch):
    a = s.get_settings()
    assert a is s.get_settings()
    s.reset_settings()
    assert a is not s.get_settings()


def test_cache_bounds_and_per_section_ttls_from_yaml_and_env(tmp_path):
    y = tmp_path / "s.yaml"
    y.write_text("cache_ttls: {air_quality: 1800, oepnv: 0}\ncache_max_entries: 10\ncache_max_bytes: 2048\n")
    cfg = s.load_settings(env={"GEOAPIFY_API_KEY": "k"}, yaml_path=y)
    assert cfg.cache_ttls == {"air_quality": 1800, "oepnv": 0}
    assert cfg.cache_max_entries == 10 and cfg.cache_max_bytes == 2048
    cfg = s.load_settings(env={"GEOAPIFY_API_KEY": "k", "REDAT_CACHE_MAX_ENTRIES": "5", "REDAT_CACHE_MAX_BYTES": "1024"}, yaml_path=y)
    assert cfg.cache_max_entries == 5 and cfg.cache_max_bytes == 1024


def test_bad_cache_bounds_fail_loudly():
    with pytest.raises(s.SettingsError, match="REDAT_CACHE_MAX_BYTES"):
        s.load_settings(env={"GEOAPIFY_API_KEY": "k", "REDAT_CACHE_MAX_BYTES": "lots"}, yaml_path=None)
