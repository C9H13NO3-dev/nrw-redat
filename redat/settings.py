"""Configuration: environment > config/settings.yaml > code defaults (spec §7)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Optional

import yaml

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_YAML = ROOT / "config" / "settings.yaml"

_DEFAULTS = {
    "cache_ttl_s": 21600,
    "public_url": "http://192.168.188.64:8200",
    "log_level": "INFO",
    "destinations": [
        {"name": "Essen Hbf", "lat": 51.4508, "lon": 7.0131, "group": "hbf"},
        {"name": "Bochum Hbf", "lat": 51.4785, "lon": 7.2233, "group": "hbf"},
        {"name": "Düsseldorf Hbf", "lat": 51.2199, "lon": 6.7943, "group": "hbf"},
    ],
    "oepnv_stops": [
        ["Essen Hbf", "de:05113:9289"], ["Bochum Hbf", "de:05911:5194"], ["Düsseldorf Hbf", "de:05111:18235"],
    ],
    "section_timeouts": {},
}


class SettingsError(RuntimeError):
    """Raised at startup for a missing/invalid setting — fail loudly, never guess."""


@dataclass(frozen=True)
class Destination:
    name: str
    lat: float
    lon: float
    group: str = "custom"
    address: str = ""


@dataclass(frozen=True)
class Settings:
    geoapify_api_key: str
    api_key: Optional[str]
    data_dir: Path
    cache_ttl_s: int
    public_url: str
    log_level: str
    destinations: tuple[Destination, ...] = ()
    oepnv_stops: tuple[tuple[str, str], ...] = ()
    section_timeouts: dict = field(default_factory=dict)

    @property
    def source_dir(self) -> Path:
        return self.data_dir / "source"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "redat.db"


def _read_yaml(path: Optional[Path]) -> dict:
    if path is None or not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise SettingsError(f"{path}: top level must be a mapping")
    return data


def _int(env: Mapping[str, str], key: str, fallback: int) -> int:
    raw = env.get(key)
    if raw is None or raw == "":
        return int(fallback)
    try:
        return int(raw)
    except ValueError as e:
        raise SettingsError(f"{key} must be an integer, got {raw!r}") from e


def load_settings(env: Optional[Mapping[str, str]] = None, yaml_path: Optional[Path] = DEFAULT_YAML) -> Settings:
    env = os.environ if env is None else env
    y = {**_DEFAULTS, **_read_yaml(yaml_path)}
    key = (env.get("GEOAPIFY_API_KEY") or "").strip()
    if not key:
        raise SettingsError("GEOAPIFY_API_KEY is not set — REDAT cannot geocode without it")
    data_dir = Path(env.get("REDAT_DATA_DIR") or "data")
    if not data_dir.is_absolute():
        data_dir = (Path.cwd() / data_dir).resolve()
    dests = tuple(
        Destination(name=str(d["name"]), lat=float(d["lat"]), lon=float(d["lon"]),
                    group=str(d.get("group", "custom")), address=str(d.get("address", "")))
        for d in (y.get("destinations") or [])
    )
    stops = tuple((str(n), str(sid)) for n, sid in (y.get("oepnv_stops") or []))
    timeouts = {str(k): float(v) for k, v in (y.get("section_timeouts") or {}).items()}
    return Settings(
        geoapify_api_key=key,
        api_key=(env.get("REDAT_API_KEY") or "").strip() or None,
        data_dir=data_dir,
        cache_ttl_s=_int(env, "REDAT_CACHE_TTL_S", int(y["cache_ttl_s"])),
        public_url=(env.get("REDAT_PUBLIC_URL") or y["public_url"]).rstrip("/"),
        log_level=(env.get("REDAT_LOG_LEVEL") or y["log_level"]).upper(),
        destinations=dests,
        oepnv_stops=stops,
        section_timeouts=timeouts,
    )


_cached: Optional[Settings] = None


def get_settings() -> Settings:
    global _cached
    if _cached is None:
        _cached = load_settings()
    return _cached


def reset_settings() -> None:
    global _cached
    _cached = None
