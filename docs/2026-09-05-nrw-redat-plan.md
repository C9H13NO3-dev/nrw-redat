# NRW-REDAT Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up NRW-REDAT — the `/analyze` location-analysis stack lifted out of house-hunter into its own repo `/srv/nrw-redat` (Gitea `jarvis/nrw-redat`), with a website, a `/api/v1` JSON+PDF API, stored shareable runs, and a Docker deployment answering on `:8200`.

**Architecture:** Package `redat/` = FastAPI app factory + `core/` (section registry, envelope runner, tiers, geocoding) + `sources/` (the 20 data-source modules, moved from `backend/*_service.py` with `_service` dropped) + `report/` (builder/render/pdf/noise_map/svg) + `store/` (SQLite runs, in-process TTL cache) + `api/v1.py` + `web/pages.py`. Settings come from env > `config/settings.yaml` > defaults. Large geodata (BORIS/flood/BTW, ~6 GB) lives outside git under `{REDAT_DATA_DIR}/source/` and is read with geopandas at call time.

**Tech Stack:** Python 3.12, FastAPI, Jinja2, httpx, Pillow, pyproj, shapely, geopandas (+pyogrio), Playwright headless Chromium (PDF), PyYAML, SQLite, Tailwind 3 (committed build), Alpine 3, Leaflet, Chart.js. Docker base `mcr.microsoft.com/playwright/python:v1.58.0-noble`.

**Spec:** `/srv/house-hunter/docs/superpowers/specs/2026-09-05-nrw-redat-design.md` (also copied into the new repo as `docs/DESIGN.md` in Task 8). The three 2026-09-04 card specs (`2026-09-04-analyze-rework-design.md`, `-analyze-risk-cards-design.md`, `-analyze-energy-cards-design.md`, `-analyze-batch3-design.md`, `-analysis-pdf-report-design.md`) document the per-source behaviour that moves unchanged.

**Scope of this plan:** spec §12 steps 1–6 + REDAT's docs (step 8, REDAT half). The house-hunter cutover (§11, step 7) gets its own plan once REDAT is live on `:8200`. **Nothing in `/srv/house-hunter` changes in this plan** except reading files from it.

## Global Constraints

- New repo lives at `/srv/nrw-redat`; remote `http://192.168.188.64:3333/jarvis/nrw-redat.git`; default branch `main`. Gitea credentials for agents: user `Jarvis`, password `Jarvis2026!` — used **only** through a throwaway `GIT_ASKPASS` script or `curl -u` in the scratchpad (`/tmp/claude-1000/-srv-house-hunter/97bbb76d-baf8-46d0-8934-6372bedf5c3c/scratchpad`), deleted right after; never a credential helper, `~/.git-credentials`, `.netrc` in `$HOME`, or a URL-embedded password.
- Commit trailers on every commit: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` and `Claude-Session: https://claude.ai/code/session_015HbDiczEViCdm3XmxC2ReC`.
- Package name `redat`; `redat.__version__ = "1.0.0"`; module renames drop the `_service` suffix; **public function names inside moved modules are unchanged**; the `_fetch_*`/`_get_png`/`_fetch_png` test seams stay where they are.
- Port `8200`. `REDAT_PUBLIC_URL` default `http://192.168.188.64:8200`. Every outbound HTTP call carries `User-Agent: nrw-redat/1.0 (+{REDAT_PUBLIC_URL})`.
- Env (§7): `GEOAPIFY_API_KEY` required — startup fails loudly without it; `REDAT_API_KEY` optional — when set, every `/api/*` route requires `X-Api-Key` (401 otherwise), never `/docs`, `/healthz`, or website pages; `REDAT_DATA_DIR` (default `./data` locally, `/data` in the container) holds `redat.db` at its root and geodata under `source/{boris,flood,elections}`; `REDAT_CACHE_TTL_S` default `21600`; `REDAT_LOG_LEVEL` default `INFO`. Precedence env > `config/settings.yaml` > code defaults.
- Envelope shape unchanged: `{key, tier, status: ok|empty|gated|error, data, message, source, took_ms}` (+ `cached: true` when served from cache). A section failure never fails a run. `/api/v1/analyze` and `GET /api/v1/report` → 422 unresolvable address, 502 when Geoapify **and** Nominatim failed, never 500 for a source failure. PDF renderer down → 503 `{detail: "PDF-Renderer nicht verfügbar"}`.
- `destinations` query/body param = JSON list `[{name, lat, lon, group}]`, ≤ 10 entries, feeds `commute` and `oepnv` only; absent → `settings.yaml` defaults (Essen Hbf, Bochum Hbf, Düsseldorf Hbf).
- Runs table: `runs(id TEXT PK, created_at, address, formatted_address, latitude, longitude, precision, plot_size_m2, living_space_m2, sections_json)`, WAL, id = 10-char base32 of `secrets.token_bytes(6)`. Cache key `(key, lat_r4, lon_r4, plot, force)`, only `ok|empty` cached.
- Tests hermetic: tmp SQLite, every HTTP seam stubbed, target ≈ 250 tests < 20 s. `requirements.txt` has **no** scikit-learn/scrapling/openai. Dockerfile `test` stage runs `pytest -q` so a red tree cannot build an image. `docker-compose.yml`: service `redat`, `ports: 8200:8200`, `env_file: .env`, volume `./data:/data`, `restart: unless-stopped`, `mem_limit: 2g`.
- Never write to house-hunter's live `house_search.db`. Never run `docker compose down -v` (the volume is a bind mount holding 6 GB of geodata — `down -v` is harmless to bind mounts but don't get in the habit).
- Tailwind is a committed content-scanned build: after adding utility classes run `npx tailwindcss@3 -c tailwind.config.js -i tailwind.input.css -o redat/static/redat.css --minify`.
- German UI copy stays byte-identical to hunter's where a partial/template is moved; new copy is German too (site chrome: "Analyse", "Quellen", "API", "Analysieren", "Alle gesperrten laden", "📄 PDF-Bericht", "Analyse vom dd.mm.yyyy hh:mm — neu laden").

---

## File structure (what gets created)

```
/srv/nrw-redat/
├── redat/__init__.py                 __version__ = "1.0.0"
├── redat/app.py                      create_app(), app = create_app(); /healthz; static mount; lifespan
├── redat/settings.py                 Settings, Destination, load_settings(), get_settings(), reset_settings(), SettingsError
├── redat/http.py                     user_agent() + default httpx headers helper
├── redat/templating.py               shared Jinja2 env (templates dir, filters registered by report.render)
├── redat/core/{__init__,sections,envelope,tiers,geocoding,sources_meta}.py
├── redat/sources/{__init__,airquality,airquality_grid,airquality_live,bergbau,boris,breitband,btw,
│                 denkmal,energie,flood,geoapify,gfnp,infrastruktur,noise,oepnv,
│                 planning_essen,planning_bochum,schutzgebiete,starkregen,zensus}.py
├── redat/report/{__init__,builder,render,pdf,noise_map,svg}.py
├── redat/store/{__init__,runs,cache}.py
├── redat/api/{__init__,v1,auth}.py
├── redat/web/{__init__,pages}.py
├── redat/data/{eea_aq_grid_2023.json,zensus_2022_grid.json.gz,certs/lencr_ye_chain.pem}
├── redat/templates/{base,index,run,quellen}.html + analysis/_*.html + report/report.html + report/_*.html
├── redat/static/{analysis.js,map-utils.js,charts.js,redat.css}
├── config/settings.yaml
├── scripts/{build_zensus_grid,build_eea_aq_grid,smoke_analyze}.py
├── tests/conftest.py + test_*.py
├── docs/{DESIGN.md, 2026-09-04-*.md, SOURCES.md}
├── Dockerfile · docker-compose.yml · .env.example · .gitignore · .dockerignore
├── requirements.txt · requirements-dev.txt · pyproject.toml · tailwind.config.js · tailwind.input.css · package.json (dev only)
└── README.md · HANDOVER.md · CLAUDE.md
```

Hunter source paths referenced below are all under `/srv/house-hunter/` (`H=/srv/house-hunter` in shell snippets).

---

### Task 1: Repo bootstrap — Gitea repo, skeleton, settings, app + `/healthz`, data copy

**Files:**
- Create: `/srv/nrw-redat/` (everything in this task), Gitea repo `jarvis/nrw-redat`
- Create: `redat/__init__.py`, `redat/settings.py`, `redat/http.py`, `redat/app.py`, `config/settings.yaml`, `requirements.txt`, `requirements-dev.txt`, `pyproject.toml`, `.gitignore`, `.dockerignore`, `.env.example`, `README.md`
- Test: `tests/conftest.py`, `tests/test_settings.py`, `tests/test_app.py`

**Interfaces:**
- Produces: `redat.settings.Settings` (frozen dataclass: `geoapify_api_key: str`, `api_key: str | None`, `data_dir: Path`, `cache_ttl_s: int`, `public_url: str`, `log_level: str`, `destinations: tuple[Destination, ...]`, `oepnv_stops: tuple[tuple[str, str], ...]`, `section_timeouts: dict[str, float]`; properties `source_dir -> Path` (= `data_dir / "source"`), `db_path -> Path` (= `data_dir / "redat.db"`)); `Destination(name: str, lat: float, lon: float, group: str = "custom", address: str = "")`; `load_settings(env: Mapping[str,str] | None = None, yaml_path: Path | None = None) -> Settings`; `get_settings() -> Settings` (cached); `reset_settings() -> None`; `SettingsError(RuntimeError)`.
- Produces: `redat.http.user_agent() -> str` and `redat.http.headers() -> dict` (`{"User-Agent": user_agent()}`), consumed by every moved source module.
- Produces: `redat.app.create_app() -> FastAPI`, module-level `app`; `GET /healthz` → `{status, version, chromium, sources_loaded}`.

- [ ] **Step 1: Create the Gitea repository (throwaway credentials file)**

```bash
S=/tmp/claude-1000/-srv-house-hunter/97bbb76d-baf8-46d0-8934-6372bedf5c3c/scratchpad
cat > "$S/gitea.netrc" <<'EOF'
machine 192.168.188.64 login Jarvis password Jarvis2026!
EOF
chmod 600 "$S/gitea.netrc"
curl -sS --netrc-file "$S/gitea.netrc" -X POST http://192.168.188.64:3333/api/v1/user/repos \
  -H 'Content-Type: application/json' \
  -d '{"name":"nrw-redat","description":"NRW Real Estate Data Aggregation Tool — Standortanalyse für Essen/Bochum (Website + API)","private":false,"default_branch":"main","auto_init":false}' \
  | python3 -c 'import json,sys; r=json.load(sys.stdin); print(r.get("clone_url") or r)'
rm -f "$S/gitea.netrc"
```
Expected: prints `http://192.168.188.64:3333/jarvis/nrw-redat.git`. (If the repo already exists the API returns 409 — fine, continue.)

- [ ] **Step 2: Skeleton + git init**

```bash
mkdir -p /srv/nrw-redat && cd /srv/nrw-redat && git init -b main
mkdir -p redat/{core,sources,report,store,api,web,data/certs,templates/analysis,templates/report,static} config scripts tests docs data
touch redat/__init__.py redat/core/__init__.py redat/sources/__init__.py redat/report/__init__.py redat/store/__init__.py redat/api/__init__.py redat/web/__init__.py
git remote add origin http://192.168.188.64:3333/jarvis/nrw-redat.git
```

`redat/__init__.py`:
```python
"""NRW-REDAT — Real Estate Data Aggregation Tool for Essen/Bochum."""
__version__ = "1.0.0"
```

`.gitignore`:
```
.venv/
__pycache__/
*.pyc
.pytest_cache/
.env
data/
node_modules/
.superpowers/
```

`.dockerignore`:
```
.venv
.git
data
node_modules
.superpowers
.pytest_cache
__pycache__
.env
```

`requirements.txt` (pinned to the versions verified on the host venv):
```
fastapi==0.128.0
uvicorn[standard]==0.34.0
jinja2==3.1.6
httpx==0.28.1
Pillow==12.1.0
pyproj==3.7.2
shapely==2.1.2
geopandas==1.1.2
pyogrio==0.12.1
numpy>=2.4.0,<3
pandas>=2.2,<3
playwright==1.58.0
pyyaml==6.0.2
python-multipart==0.0.20
```
(Check `uvicorn`, `jinja2`, `pyyaml`, `python-multipart` versions with `/srv/house-hunter/.venv/bin/pip show uvicorn jinja2 pyyaml python-multipart` and pin to what is installed there; if a package is absent in hunter's venv, pin the latest on PyPI.)

`requirements-dev.txt`:
```
pytest>=8.0
```

`pyproject.toml`:
```toml
[project]
name = "nrw-redat"
version = "1.0.0"
description = "NRW Real Estate Data Aggregation Tool"
requires-python = ">=3.12"

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-p no:cacheprovider"
filterwarnings = ["ignore::DeprecationWarning"]
```

`.env.example`:
```
# Required — Geoapify key (geocoding, autocomplete, amenities, commute)
GEOAPIFY_API_KEY=
# Optional — when set, /api/* requires the X-Api-Key header
REDAT_API_KEY=
# Where redat.db and source/{boris,flood,elections} live (container: /data)
REDAT_DATA_DIR=/data
REDAT_CACHE_TTL_S=21600
REDAT_PUBLIC_URL=http://192.168.188.64:8200
REDAT_LOG_LEVEL=INFO
```

`config/settings.yaml`:
```yaml
# Committed defaults — environment variables win (see redat/settings.py).
public_url: http://192.168.188.64:8200
cache_ttl_s: 21600
destinations:            # commute + ÖPNV targets when the caller passes none
  - {name: Essen Hbf, lat: 51.4508, lon: 7.0131, group: hbf}
  - {name: Bochum Hbf, lat: 51.4785, lon: 7.2233, group: hbf}
  - {name: Düsseldorf Hbf, lat: 51.2199, lon: 6.7943, group: hbf}
oepnv_stops:             # VRR EFA stop ids for the fixed ÖPNV trip targets
  - [Essen Hbf, "de:05113:9289"]
  - [Bochum Hbf, "de:05911:5194"]
  - [Düsseldorf Hbf, "de:05111:18235"]
section_timeouts: {}     # e.g. {infrastruktur: 90}
```

Create the venv: `cd /srv/nrw-redat && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements-dev.txt` (≈ 2 min; geopandas wheels only, no GDAL build).

- [ ] **Step 3: Write the failing settings tests**

`tests/conftest.py`:
```python
"""Hermetic defaults for every test: a fake Geoapify key, a tmp data dir, no API key."""
import pytest


@pytest.fixture(autouse=True)
def _redat_env(monkeypatch, tmp_path):
    from redat import settings as s
    monkeypatch.setenv("GEOAPIFY_API_KEY", "test-key")
    monkeypatch.setenv("REDAT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("REDAT_API_KEY", raising=False)
    monkeypatch.delenv("REDAT_CACHE_TTL_S", raising=False)
    monkeypatch.delenv("REDAT_PUBLIC_URL", raising=False)
    s.reset_settings()
    yield
    s.reset_settings()
```

`tests/test_settings.py`:
```python
from pathlib import Path

import pytest

from redat import settings as s


def test_defaults_from_yaml_when_env_empty(tmp_path):
    cfg = s.load_settings(env={"GEOAPIFY_API_KEY": "k"}, yaml_path=None)
    assert cfg.geoapify_api_key == "k"
    assert cfg.api_key is None
    assert cfg.cache_ttl_s == 21600
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
```

- [ ] **Step 4: Run to verify failure**

Run: `cd /srv/nrw-redat && .venv/bin/python -m pytest tests/test_settings.py -q`
Expected: FAIL / ImportError (`redat.settings` has no `load_settings`).

- [ ] **Step 5: Implement `redat/settings.py` and `redat/http.py`**

`redat/settings.py`:
```python
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
```

Note `test_defaults_from_yaml_when_env_empty` asserts `data_dir == Path("data").resolve()` — that holds because tests run from the repo root (`pytest` is invoked there) and the autouse fixture's `REDAT_DATA_DIR` is not in the explicit `env={}` mapping.

`redat/http.py`:
```python
"""Outbound HTTP conventions: every call identifies itself (spec §13)."""
from redat import __version__
from redat.settings import get_settings


def user_agent() -> str:
    return f"nrw-redat/{__version__.split('.')[0]}.0 (+{get_settings().public_url})"


def headers() -> dict:
    return {"User-Agent": user_agent()}
```

- [ ] **Step 6: Run settings tests**

Run: `.venv/bin/python -m pytest tests/test_settings.py -q`
Expected: 7 passed.

- [ ] **Step 7: Write the failing app test**

`tests/test_app.py`:
```python
from fastapi.testclient import TestClient

import redat
from redat import app as appmod


def test_healthz_is_open_and_reports_version(monkeypatch):
    monkeypatch.setattr(appmod, "chromium_available", lambda: False)
    client = TestClient(appmod.create_app())
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["version"] == redat.__version__
    assert body["chromium"] is False and isinstance(body["sources_loaded"], int)


def test_healthz_ignores_api_key(monkeypatch):
    monkeypatch.setenv("REDAT_API_KEY", "secret")
    from redat import settings as s
    s.reset_settings()
    monkeypatch.setattr(appmod, "chromium_available", lambda: True)
    client = TestClient(appmod.create_app())
    assert client.get("/healthz").status_code == 200


def test_docs_served():
    client = TestClient(appmod.create_app())
    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").json()["info"]["version"] == redat.__version__
```

- [ ] **Step 8: Implement `redat/app.py` (minimal — routers are added in later tasks)**

```python
"""FastAPI factory: website + /api/v1 + static files + /healthz (spec §3, §5.3)."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from redat import __version__
from redat.settings import get_settings

log = logging.getLogger("redat")
STATIC_DIR = Path(__file__).resolve().parent / "static"

DESCRIPTION = (
    "NRW-REDAT bündelt öffentliche Geodaten (BORIS, Hochwasser, Lärm, Luftqualität, ÖPNV, …) "
    "zu einer Standortanalyse für Essen und Bochum. Jede Karte ist eine eigene Sektion mit "
    "festem Envelope `{key, tier, status, data, message, source, took_ms}`."
)


@lru_cache(maxsize=1)
def chromium_available() -> bool:
    """One Playwright launch probe per process — /healthz reports it as `chromium`."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch()
            b.close()
        return True
    except Exception as e:  # noqa: BLE001 — any failure means "no PDF renderer"
        log.warning("Chromium probe failed: %s", e)
        return False


def sources_loaded() -> int:
    from redat.core.sections import SECTIONS
    return len(SECTIONS)


def create_app() -> FastAPI:
    settings = get_settings()  # raises SettingsError → uvicorn exits: fail loudly
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings.data_dir.mkdir(parents=True, exist_ok=True)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        from redat.store.runs import RunStore
        _app.state.runs = RunStore(settings.db_path)
        _app.state.runs.init()
        yield

    app = FastAPI(title="NRW-REDAT", version=__version__, description=DESCRIPTION, lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/healthz", include_in_schema=False)
    def healthz():
        return {"status": "ok", "version": __version__, "chromium": chromium_available(),
                "sources_loaded": sources_loaded()}

    from redat.api.v1 import router as api_router
    from redat.web.pages import router as web_router
    app.include_router(api_router)
    app.include_router(web_router)
    return app


app = create_app()
```

Until Tasks 5/7/8/9 exist, make the imports resolvable with stubs so Task 1's tests run:
- `redat/core/sections.py`: `SECTIONS: dict = {}` (replaced in Task 5).
- `redat/store/runs.py`: `class RunStore:\n    def __init__(self, path): self.path = path\n    def init(self): pass` (replaced in Task 7).
- `redat/api/v1.py`: `from fastapi import APIRouter\nrouter = APIRouter(prefix="/api/v1")` (replaced in Task 8).
- `redat/web/pages.py`: `from fastapi import APIRouter\nrouter = APIRouter()` (replaced in Task 9).
- `redat/static/.gitkeep` so `StaticFiles` finds the directory.

Also: the module-level `app = create_app()` runs at import in tests; `conftest.py`'s autouse fixture sets env *before* the test body but `import redat.app` inside a test function happens after — fine. Do **not** import `redat.app` at module level in any test file.

- [ ] **Step 9: Run app tests**

Run: `.venv/bin/python -m pytest tests -q`
Expected: 10 passed.

- [ ] **Step 10: One-time source data copy (host, ~6.2 GB, 2–5 min)**

```bash
mkdir -p /srv/nrw-redat/data/source
rsync -a --info=progress2 --exclude='*.zip' --exclude='*_Shape/' /srv/house-hunter/data/boris /srv/nrw-redat/data/source/
rsync -a --info=progress2 --exclude='*.zip' --exclude='*_Shape/' /srv/house-hunter/data/flood /srv/nrw-redat/data/source/
rsync -a --info=progress2 --exclude='*.zip' /srv/house-hunter/data/elections /srv/nrw-redat/data/source/
du -sh /srv/nrw-redat/data/source/*
ls /srv/nrw-redat/data/source/boris | head -3; ls /srv/nrw-redat/data/source/flood/hwrm
```
Expected: `boris` ≈ 5.3G with `BRW_2011 … BRW_2025`; `flood/hwrm/{HQhaeufig,HQ100,HQextrem}.gpkg`; `elections/btw25/wahlkreise_shp_geo/…/Wahlkreise_WGS84.shp`. `data/` is git-ignored.

- [ ] **Step 11: README stub + commit + push**

`README.md`:
```markdown
# NRW-REDAT

Real Estate Data Aggregation Tool — Standortanalyse für Essen/Bochum aus öffentlichen Geodaten.
Website (`/`), Permalinks (`/a/{id}`), Quellenübersicht (`/quellen`), JSON+PDF API (`/api/v1`, OpenAPI unter `/docs`).

## Betrieb

    cp .env.example .env            # GEOAPIFY_API_KEY eintragen
    docker compose up -d --build    # :8200 — der Build läuft pytest; ein roter Baum baut kein Image
    curl -s localhost:8200/healthz

Geodaten (BORIS, Hochwasser, Wahlkreise, ~6 GB, nicht im Git) liegen unter `data/source/{boris,flood,elections}` —
siehe `HANDOVER.md`.

## Entwicklung

    python3 -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements-dev.txt
    .venv/bin/python -m pytest -q
    GEOAPIFY_API_KEY=… .venv/bin/uvicorn redat.app:app --port 8200 --reload

Design: `docs/DESIGN.md`.
```

```bash
cd /srv/nrw-redat && git add -A && git commit -q -F - <<'EOF'
feat: bootstrap NRW-REDAT — settings, app factory, /healthz

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_015HbDiczEViCdm3XmxC2ReC
EOF
S=/tmp/claude-1000/-srv-house-hunter/97bbb76d-baf8-46d0-8934-6372bedf5c3c/scratchpad
printf '#!/bin/sh\ncase "$1" in *sername*) echo Jarvis;; *) echo "Jarvis2026!";; esac\n' > "$S/askpass.sh" && chmod 700 "$S/askpass.sh"
GIT_ASKPASS="$S/askpass.sh" GIT_TERMINAL_PROMPT=0 git push -u origin main; rm -f "$S/askpass.sh"
```
Expected: push succeeds; `git status` clean.

### Task 2: Move the self-contained source modules, their data files, and their tests

**Files:**
- Create (copied from `$H/backend/`): `redat/sources/airquality.py` (← `airquality_service.py`), `airquality_grid.py`, `airquality_live.py`, `bergbau.py` (← `bergbau_service.py`), `breitband.py`, `denkmal.py`, `energie.py`, `gfnp.py`, `infrastruktur.py`, `noise.py`, `planning_essen.py` (← `planning_service.py`), `planning_bochum.py` (← `planning_bochum_service.py`), `schutzgebiete.py`, `starkregen.py`, `zensus.py` (← `zensus_grid.py`)
- Create: `redat/data/eea_aq_grid_2023.json` (← `backend/eea_aq_grid_2023.json`), `redat/data/zensus_2022_grid.json.gz` (← `backend/zensus_2022_grid.json.gz`), `redat/data/certs/lencr_ye_chain.pem` (← `backend/certs/lencr_ye_chain.pem`)
- Create: `scripts/build_zensus_grid.py`, `scripts/build_eea_aq_grid.py` (← `$H/scripts/…`)
- Test (copied, imports rewritten): `tests/test_airquality_grid.py`, `test_airquality_live.py`, `test_airquality_service.py`, `test_bergbau_service.py`, `test_breitband_service.py`, `test_build_zensus_grid.py`, `test_denkmal_service.py`, `test_energie_service.py`, `test_infrastruktur_service.py`, `test_noise_service.py`, `test_schutzgebiete_service.py`, `test_starkregen_service.py`, `test_zensus_grid.py`

**Interfaces:**
- Consumes: `redat.http.headers()` (Task 1).
- Produces: module paths `redat.sources.<name>` with **unchanged public functions**: `airquality.get_air_quality_report(lat, lon)`, `bergbau.get_bergbau(lat, lon)`, `breitband.get_breitband(lat, lon)`, `denkmal.get_denkmal(lat, lon)`, `energie.get_energie(lat, lon)`, `gfnp` (whatever `sections._fetch_gfnp` calls today — check `grep -n gfnp_service $H/backend/analysis/sections.py`), `infrastruktur.get_infrastruktur(lat, lon)`, `noise.get_noise_levels(lat, lon)`, `planning_essen`/`planning_bochum` (same check against `sections.py`), `schutzgebiete.get_schutzgebiete(lat, lon)`, `starkregen.get_starkregen(lat, lon)`, `zensus.lookup(lat, lon)`.

- [ ] **Step 1: Copy modules and data**

```bash
H=/srv/house-hunter; R=/srv/nrw-redat; cd $R
for pair in airquality_service:airquality airquality_grid:airquality_grid airquality_live:airquality_live \
            bergbau_service:bergbau breitband_service:breitband denkmal_service:denkmal energie_service:energie \
            gfnp_service:gfnp infrastruktur_service:infrastruktur noise_service:noise planning_service:planning_essen \
            planning_bochum_service:planning_bochum schutzgebiete_service:schutzgebiete starkregen_service:starkregen \
            zensus_grid:zensus; do
  cp $H/backend/${pair%%:*}.py redat/sources/${pair##*:}.py
done
cp $H/backend/eea_aq_grid_2023.json $H/backend/zensus_2022_grid.json.gz redat/data/
cp $H/backend/certs/lencr_ye_chain.pem redat/data/certs/
cp $H/scripts/build_zensus_grid.py $H/scripts/build_eea_aq_grid.py scripts/
for t in airquality_grid airquality_live airquality_service bergbau_service breitband_service build_zensus_grid \
         denkmal_service energie_service infrastruktur_service noise_service schutzgebiete_service starkregen_service zensus_grid; do
  cp $H/tests/test_$t.py tests/
done
```

- [ ] **Step 2: Rewrite intra-module imports and data paths**

Apply these exact edits (use `Edit`, then `grep -rn "import airquality_grid\|schutzgebiete_service\|zensus_grid\|_service" redat/sources` must come back empty):

- `redat/sources/airquality.py` lines `import airquality_grid` / `import airquality_live` → `from redat.sources import airquality_grid` / `from redat.sources import airquality_live`.
- `redat/sources/energie.py`: `from schutzgebiete_service import _wsg_featureinfo, parse_wsg` → `from redat.sources.schutzgebiete import _wsg_featureinfo, parse_wsg`.
- `redat/sources/zensus.py`: `GRID_PATH = Path(__file__).resolve().parent / "zensus_2022_grid.json.gz"` → `GRID_PATH = Path(__file__).resolve().parent.parent / "data" / "zensus_2022_grid.json.gz"`.
- `redat/sources/airquality_grid.py`: `GRID_PATH = Path(__file__).resolve().parent / "eea_aq_grid_2023.json"` → `… .parent.parent / "data" / "eea_aq_grid_2023.json"`.
- `redat/sources/breitband.py`: `CA_BUNDLE = Path(__file__).resolve().parent / "certs" / "lencr_ye_chain.pem"` → `… .parent.parent / "data" / "certs" / "lencr_ye_chain.pem"`.
- `scripts/build_zensus_grid.py` / `scripts/build_eea_aq_grid.py`: wherever the default output path points at `backend/<grid file>`, point it at `redat/data/<grid file>` (grep `backend` in both scripts; there should be exactly one default per script).
- Module docstrings: replace the phrase `house-hunter`/`HouseHunter` with `NRW-REDAT` where it names the project (do not touch data-source names or URLs).

- [ ] **Step 3: User-Agent on every outbound call**

Rule (spec §13): each `httpx.get(`, `httpx.post(`, `httpx.Client(` in `redat/sources/*.py` passes `headers=headers()` from `redat.http`. Concretely:
- Add `from redat.http import headers` to every module that calls httpx (`grep -ln "httpx\." redat/sources/*.py`).
- Calls with no `headers=` kwarg: append `headers=headers()`.
- `breitband.py` (`headers={"User-Agent": "house-hunter/1.0"}`), `denkmal.py` (`headers={"User-Agent": "HouseHunter/1.0"}`): replace the literal dict with `headers()`.
- `infrastruktur.py`: delete `USER_AGENT = "HouseHunter/1.0"`; both `headers={"User-Agent": USER_AGENT}` → `headers=headers()`. If `tests/test_infrastruktur_service.py` references `inf.USER_AGENT`, change that assertion to `headers()["User-Agent"].startswith("nrw-redat/")`.
- `breitband.py`'s `_ssl_context()`/`verify=` argument stays exactly as is.

Verify: `grep -n "httpx\.\(get\|post\|Client\)(" redat/sources/*.py | grep -v "headers=" ` → empty.

- [ ] **Step 4: Rewrite test imports**

```bash
cd /srv/nrw-redat/tests
sed -i 's/^import airquality_service as A$/from redat.sources import airquality as A/;
        s/^    import airquality_grid, airquality_live$/    from redat.sources import airquality_grid, airquality_live/' test_airquality_service.py
sed -i 's/^import airquality_grid as G$/from redat.sources import airquality_grid as G/' test_airquality_grid.py
sed -i 's/^import airquality_live as L$/from redat.sources import airquality_live as L/' test_airquality_live.py
sed -i 's/^import bergbau_service as bb$/from redat.sources import bergbau as bb/' test_bergbau_service.py
sed -i 's/^import breitband_service as bb$/from redat.sources import breitband as bb/' test_breitband_service.py
sed -i 's/^import denkmal_service as dk$/from redat.sources import denkmal as dk/' test_denkmal_service.py
sed -i 's/^import energie_service as es$/from redat.sources import energie as es/' test_energie_service.py
sed -i 's/^import infrastruktur_service as inf$/from redat.sources import infrastruktur as inf/' test_infrastruktur_service.py
sed -i 's/^import noise_service as ns$/from redat.sources import noise as ns/' test_noise_service.py
sed -i 's/^import schutzgebiete_service as sg$/from redat.sources import schutzgebiete as sg/' test_schutzgebiete_service.py
sed -i 's/^import starkregen_service as srg$/from redat.sources import starkregen as srg/' test_starkregen_service.py
sed -i 's/^import zensus_grid as zg$/from redat.sources import zensus as zg/;s/^    import zensus_grid as zg$/    from redat.sources import zensus as zg/' test_zensus_grid.py test_build_zensus_grid.py
grep -n "^import \|^from \|^    import \|^    from " test_*.py | grep -v "redat\.\|pytest\|pathlib\|json\|io\b\|gzip\|importlib\|PIL\|datetime\|math\|unittest\|typing\|base64\|struct\|textwrap\|os\b\|sys\b\|fastapi\|numpy\|shapely\|pyproj\|httpx\|re\b\|threading\|time\b\|dataclasses\|contextlib\|collections\|copy\b\|zoneinfo\|__future__"
```
Expected: the final grep prints nothing (every remaining bare import is a stdlib/3rd-party name). Any `monkeypatch.setattr("noise_service.…")` string targets → `"redat.sources.noise.…"` (grep `setattr("` to check; today's tests use module objects, so likely none). Test modules with `import config` or `from enrichment_service` at module level do not exist in this batch (verified during planning).

- [ ] **Step 5: Run the moved tests**

Run: `cd /srv/nrw-redat && .venv/bin/python -m pytest tests -q`
Expected: all pass (≈ 200 collected including Task 1's 10). Failures here are import-rewrite misses or the `headers()` change; fix in place — do **not** alter assertion semantics.

- [ ] **Step 6: Commit**

```bash
cd /srv/nrw-redat && git add -A && git commit -q -F - <<'EOF'
feat(sources): move the self-contained source modules, grids and certs from house-hunter

airquality{,_grid,_live} bergbau breitband denkmal energie gfnp infrastruktur noise
planning_{essen,bochum} schutzgebiete starkregen zensus — public functions unchanged,
data paths now under redat/data/, every outbound call carries the nrw-redat User-Agent.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_015HbDiczEViCdm3XmxC2ReC
EOF
```

### Task 3: Core — tiers, Geoapify client (+ autocomplete), geocoding with Nominatim fallback

**Files:**
- Create: `redat/core/tiers.py`, `redat/core/geocoding.py`, `redat/sources/geoapify.py` (← `$H/backend/geoapify_service.py` + `geoapify_autocomplete.autocomplete_address` folded in)
- Test: `tests/test_tiers.py`, `tests/test_geocoding.py` (rewritten from `$H/tests/test_geocoding.py`), `tests/test_geoapify.py`

**Interfaces:**
- Consumes: `redat.settings.get_settings().geoapify_api_key`, `redat.http.headers()`.
- Produces: `tiers.SERVICE_TIER: dict[str, str]`, `tiers.enrichment_allowed(service_tier: str, *, precision: str | None, address_verified: bool) -> bool`; `geocoding.GeocodeResult(latitude, longitude, precision, formatted_address)`, `geocoding.parse_coordinates(text) -> tuple[float,float] | None`, `geocoding.geocode_with_precision(address) -> GeocodeResult | None` (None = unresolvable → 422), `geocoding.GeocoderUnavailable(RuntimeError)` (both geocoders errored → 502); `geoapify.geocode_address(address) -> dict | None`, `geoapify.get_driving_time(from_lat, from_lon, to_lat, to_lon) -> dict | None`, `geoapify.get_all_amenities(lat, lon)` (unchanged), `geoapify.autocomplete_address(text, limit=8, bias_lat=None, bias_lon=None) -> list[dict]`, `geoapify._api_key() -> str`.

- [ ] **Step 1: Tiers test + module**

`tests/test_tiers.py`:
```python
import pytest

from redat.core.tiers import SERVICE_TIER, enrichment_allowed


def test_every_section_has_a_tier():
    for key in ("boris", "boris_trend", "flood", "starkregen", "noise", "bergbau", "gfnp", "schutzgebiete", "planning_essen",
                "planning_bochum", "denkmal", "amenities", "oepnv", "zensus", "energie", "breitband", "infrastruktur",
                "air_quality", "btw", "commute"):
        assert SERVICE_TIER[key] in ("parcel", "area")


def test_parcel_tier_keys():
    assert {k for k, t in SERVICE_TIER.items() if t == "parcel"} == {
        "boris", "boris_trend", "flood", "starkregen", "gfnp", "planning_essen", "planning_bochum", "energie", "denkmal"}


@pytest.mark.parametrize("precision,verified,expected", [
    ("building", False, True), ("street", False, False), (None, False, False),
    ("street", True, True), (None, True, True), ("coordinates", False, False),
])
def test_parcel_gate(precision, verified, expected):
    assert enrichment_allowed("parcel", precision=precision, address_verified=verified) is expected


def test_area_always_allowed():
    assert enrichment_allowed("area", precision=None, address_verified=False) is True
```
(`"coordinates"` alone is not allowed at this layer — the envelope runner passes `address_verified = force or precision == "coordinates"`, exactly as hunter's `run_section` does.)

`redat/core/tiers.py`:
```python
"""Which cards need a house-number-exact location (parcel) and which work on the area."""
from __future__ import annotations

from typing import Optional

SERVICE_TIER: dict[str, str] = {
    "boris": "parcel", "boris_trend": "parcel", "flood": "parcel", "starkregen": "parcel", "gfnp": "parcel",
    "planning_essen": "parcel", "planning_bochum": "parcel", "energie": "parcel", "denkmal": "parcel",
    "amenities": "area", "air_quality": "area", "btw": "area", "commute": "area", "noise": "area", "bergbau": "area",
    "zensus": "area", "schutzgebiete": "area", "breitband": "area", "oepnv": "area", "infrastruktur": "area",
}


def enrichment_allowed(service_tier: str, *, precision: Optional[str], address_verified: bool) -> bool:
    """Parcel-tier sources only run on a verified address or a house-number-level geocode."""
    if service_tier == "area":
        return True
    if address_verified:
        return True
    return precision == "building"
```
Run `pytest tests/test_tiers.py -q` → 9 passed.

- [ ] **Step 2: Geoapify module**

```bash
cp /srv/house-hunter/backend/geoapify_service.py /srv/nrw-redat/redat/sources/geoapify.py
```
Edits in `redat/sources/geoapify.py`:
- Delete `GEOAPIFY_API_KEY = os.environ.get("GEOAPIFY_API_KEY", "")`; add
  ```python
  from redat.http import headers
  from redat.settings import get_settings


  def _api_key() -> str:
      return get_settings().geoapify_api_key
  ```
  and replace each of the four `"apiKey": GEOAPIFY_API_KEY` with `"apiKey": _api_key()`.
- Every `httpx.Client(timeout=…)` → `httpx.Client(timeout=…, headers=headers())`.
- Append the autocomplete helper (body from `$H/backend/geoapify_autocomplete.py`, `GEOAPIFY_API_KEY` → `_api_key()`, `httpx.Client(timeout=6.0, headers=headers())`):
  ```python
  AUTOCOMPLETE_URL = "https://api.geoapify.com/v1/geocode/autocomplete"


  def autocomplete_address(text: str, limit: int = 8, bias_lat: float | None = None, bias_lon: float | None = None) -> list[dict]:
      ...  # verbatim from geoapify_autocomplete.autocomplete_address
  ```
- Remove any `get_commute_times` docstring reference to `config.IMPORTANT_LOCATIONS` (function itself stays; REDAT's commute card uses `get_driving_time` directly — Task 5).

`tests/test_geoapify.py`:
```python
import httpx
import pytest

from redat.sources import geoapify as g


class _Resp:
    def __init__(self, payload, status=200):
        self._p, self.status_code = payload, status
    def json(self): return self._p
    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("boom", request=None, response=None)


def _client(monkeypatch, capture: dict, payload):
    class FakeClient:
        def __init__(self, *a, **kw):
            capture["headers"] = kw.get("headers")
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get(self, url, params=None, **kw):
            capture["url"], capture["params"] = url, params
            return _Resp(payload)
    monkeypatch.setattr(g.httpx, "Client", FakeClient)


def test_api_key_comes_from_settings_at_call_time(monkeypatch):
    cap = {}
    _client(monkeypatch, cap, {"features": []})
    assert g.geocode_address("Nirgendwo 1") is None
    assert cap["params"]["apiKey"] == "test-key"
    assert cap["headers"]["User-Agent"].startswith("nrw-redat/1.0 (+http://192.168.188.64:8200)")


def test_geocode_address_parses_feature(monkeypatch):
    feat = {"geometry": {"coordinates": [7.01, 51.45]},
            "properties": {"formatted": "Teststr. 1, 45127 Essen", "result_type": "building", "housenumber": "1",
                           "rank": {"confidence": 0.98}, "suburb": "Stadtkern"}}
    _client(monkeypatch, {}, {"features": [feat]})
    r = g.geocode_address("Teststr. 1, Essen")
    assert (r["lat"], r["lon"], r["precision"], r["housenumber"]) == (51.45, 7.01, "building", "1")


def test_autocomplete_maps_results_and_bias(monkeypatch):
    cap = {}
    _client(monkeypatch, cap, {"results": [{"formatted": "Kortumstraße 1, Bochum", "lat": 51.48, "lon": 7.22}]})
    out = g.autocomplete_address("Kortum", limit=3, bias_lat=51.5, bias_lon=7.1)
    assert cap["params"]["limit"] == 3 and cap["params"]["bias"] == "proximity:7.1,51.5"
    assert out and out[0]["lat"] == 51.48


def test_autocomplete_blank_is_empty():
    assert g.autocomplete_address("   ") == []
```
Adjust `test_geocode_address_parses_feature`'s feature shape to whatever `_parse_geocode_feature` in the copied module actually reads (open the function; the test must feed the keys it uses). Run `pytest tests/test_geoapify.py -q` → 4 passed.

- [ ] **Step 3: Geocoding test (rewritten seams)**

`tests/test_geocoding.py`:
```python
from unittest.mock import patch

import pytest

from redat.core.geocoding import GeocodeResult, GeocoderUnavailable, geocode_with_precision, parse_coordinates


@pytest.mark.parametrize("text,expected", [
    ("51.45, 7.01", (51.45, 7.01)), ("  51.4501 ,7.0123  ", (51.4501, 7.0123)), ("-33.9,151.2", (-33.9, 151.2)), ("51,7", (51.0, 7.0)),
])
def test_parse_coordinates_accepts_lat_lon(text, expected):
    assert parse_coordinates(text) == expected


@pytest.mark.parametrize("text", ["Rüttenscheider Str. 100, 45131 Essen", "45131 Essen", "51.45", "91.0, 7.0", "51.0, 181.0", ""])
def test_parse_coordinates_rejects_non_coordinates(text):
    assert parse_coordinates(text) is None


def test_coordinates_short_circuit_geocoders():
    with patch("redat.core.geocoding.geocode_address", side_effect=AssertionError("must not geocode")), \
         patch("redat.core.geocoding._nominatim", side_effect=AssertionError("must not geocode")):
        r = geocode_with_precision("51.45, 7.01")
    assert r == GeocodeResult(51.45, 7.01, "coordinates", "51.450000, 7.010000")


def test_geoapify_hit():
    geo = {"lat": 51.5, "lon": 7.1, "precision": "building", "address": "Teststr. 1, Essen"}
    with patch("redat.core.geocoding.geocode_address", return_value=geo), \
         patch("redat.core.geocoding._nominatim", side_effect=AssertionError("no fallback")):
        assert geocode_with_precision("Teststr. 1, Essen") == GeocodeResult(51.5, 7.1, "building", "Teststr. 1, Essen")


def test_nominatim_fallback_has_no_precision():
    with patch("redat.core.geocoding.geocode_address", return_value=None), \
         patch("redat.core.geocoding._nominatim", return_value=(51.6, 7.2, "Fallbackstr., Bochum")):
        r = geocode_with_precision("Fallbackstr., Bochum")
    assert (r.latitude, r.longitude, r.precision, r.formatted_address) == (51.6, 7.2, None, "Fallbackstr., Bochum")


def test_both_miss_returns_none():
    with patch("redat.core.geocoding.geocode_address", return_value=None), \
         patch("redat.core.geocoding._nominatim", return_value=None):
        assert geocode_with_precision("nirgendwo") is None


def test_geoapify_error_then_nominatim_hit_is_a_hit():
    with patch("redat.core.geocoding.geocode_address", side_effect=RuntimeError("geoapify down")), \
         patch("redat.core.geocoding._nominatim", return_value=(51.6, 7.2, "X")):
        assert geocode_with_precision("X").precision is None


def test_both_error_raises_unavailable():
    with patch("redat.core.geocoding.geocode_address", side_effect=RuntimeError("down")), \
         patch("redat.core.geocoding._nominatim", side_effect=RuntimeError("down too")):
        with pytest.raises(GeocoderUnavailable):
            geocode_with_precision("X")


def test_nominatim_request_shape(monkeypatch):
    from redat.core import geocoding as gc
    cap = {}
    class R:
        def raise_for_status(self): pass
        def json(self): return [{"lat": "51.6", "lon": "7.2", "display_name": "Fallbackstr., Bochum"}]
    def fake_get(url, params=None, headers=None, timeout=None):
        cap.update(url=url, params=params, headers=headers)
        return R()
    monkeypatch.setattr(gc.httpx, "get", fake_get)
    assert gc._nominatim("Fallbackstr., Bochum") == (51.6, 7.2, "Fallbackstr., Bochum")
    assert cap["url"] == "https://nominatim.openstreetmap.org/search"
    assert cap["params"] == {"q": "Fallbackstr., Bochum", "format": "json", "addressdetails": 1, "limit": 1, "countrycodes": "de"}
    assert cap["headers"]["User-Agent"].startswith("nrw-redat/")
```

- [ ] **Step 4: Run to verify failure**

Run: `pytest tests/test_geocoding.py -q` → ImportError (`redat.core.geocoding`).

- [ ] **Step 5: Implement `redat/core/geocoding.py`**

```python
"""Address → coordinates with a precision signal (Geoapify first, Nominatim fallback).

A bare "lat, lon" input is parsed directly and reported with precision="coordinates"
(treated like a verified address by the parcel-tier gate). Nominatim has no
result_type, so its hits carry precision=None and parcel-tier cards stay gated.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

import httpx

from redat.http import headers
from redat.sources.geoapify import geocode_address

logger = logging.getLogger(__name__)

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
_COORD_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$")


class GeocoderUnavailable(RuntimeError):
    """Geoapify *and* Nominatim errored — an outage, not an unknown address (→ 502)."""


@dataclass(frozen=True)
class GeocodeResult:
    latitude: float
    longitude: float
    precision: Optional[str]  # "building" | "street" | "suburb" | ... | "coordinates" | None
    formatted_address: str


def parse_coordinates(text: str) -> Optional[tuple[float, float]]:
    """Return (lat, lon) if `text` is a plain "lat, lon" pair within WGS84 bounds."""
    m = _COORD_RE.match(text or "")
    if not m:
        return None
    lat, lon = float(m.group(1)), float(m.group(2))
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return None
    return lat, lon


def _nominatim(address: str) -> Optional[tuple[float, float, str]]:
    """(lat, lon, display_name) from Nominatim, None when it has no result. Raises on transport errors."""
    resp = httpx.get(NOMINATIM_URL, params={"q": address, "format": "json", "addressdetails": 1, "limit": 1, "countrycodes": "de"},
                     headers=headers(), timeout=10.0)
    resp.raise_for_status()
    results = resp.json()
    if not results:
        return None
    r = results[0]
    return float(r["lat"]), float(r["lon"]), r.get("display_name") or address


def geocode_with_precision(address: str) -> Optional[GeocodeResult]:
    """Geocode `address`; None when no source knows it; GeocoderUnavailable when every source errored."""
    coords = parse_coordinates(address)
    if coords:
        lat, lon = coords
        return GeocodeResult(lat, lon, "coordinates", f"{lat:.6f}, {lon:.6f}")

    failures = 0
    try:
        geo = geocode_address(address)
    except Exception as exc:  # noqa: BLE001
        logger.warning("geoapify geocode failed for %r: %s", address, exc)
        geo, failures = None, failures + 1
    if geo and geo.get("lat") and geo.get("lon"):
        return GeocodeResult(float(geo["lat"]), float(geo["lon"]), geo.get("precision"), geo.get("address") or address)

    try:
        hit = _nominatim(address)
    except Exception as exc:  # noqa: BLE001
        logger.warning("nominatim geocode failed for %r: %s", address, exc)
        hit, failures = None, failures + 1
    if hit:
        lat, lon, name = hit
        logger.info("geocode: Geoapify miss for %r, Nominatim fallback (precision=None → parcel gated)", address)
        return GeocodeResult(lat, lon, None, name)
    if failures == 2:
        raise GeocoderUnavailable("Geoapify und Nominatim nicht erreichbar")
    return None
```
Note: `geocode_address` in hunter's module already swallows HTTP errors and returns None — check `$H/backend/geoapify_service.py:geocode_address`; if it does, `GeocoderUnavailable` can only trigger when Nominatim also errors *and* Geoapify returned None for a transport reason. Make `geocode_address` re-raise `httpx.HTTPError`/`httpx.TransportError` instead of returning None for them (keep returning None for "no features") so the 502 path is real. Add a test for that in `tests/test_geoapify.py`:
```python
def test_geocode_address_reraises_transport_errors(monkeypatch):
    class FakeClient:
        def __init__(self, *a, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get(self, *a, **kw): raise httpx.ConnectError("no route")
    monkeypatch.setattr(g.httpx, "Client", FakeClient)
    with pytest.raises(httpx.HTTPError):
        g.geocode_address("X")
```

- [ ] **Step 6: Run all tests, commit**

Run: `pytest tests -q` → all pass.
```bash
git add -A && git commit -q -F - <<'EOF'
feat(core): tiers, Geoapify client with autocomplete, geocoding with Nominatim fallback

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_015HbDiczEViCdm3XmxC2ReC
EOF
```

### Task 4: Local-geodata sources (BORIS, flood, BTW) and ÖPNV without hunter's config

**Files:**
- Create: `redat/sources/boris.py` (← `$H/backend/boris_service.py` + `get_boris_nrw` from `enrichment_service.py:220-275`), `redat/sources/flood.py` (← `flood_service.py`), `redat/sources/btw.py` (← `btw_service.py`), `redat/sources/oepnv.py` (← `oepnv_service.py`)
- Test: `tests/test_boris.py` (new), `tests/test_flood_service_finite.py` (← hunter's, adapted), `tests/test_btw.py` (new), `tests/test_oepnv_service.py` (← hunter's, `test_default_destinations_from_config` replaced)

**Interfaces:**
- Consumes: `get_settings().source_dir`, `get_settings().oepnv_stops`, `redat.http.headers()`.
- Produces: `boris.data_dir() -> Path` (= `source_dir/"boris"`), `boris.lookup_bodenrichtwert(lat, lon, year=2025) -> BorisResult | None`, `boris.get_historical_trend(lat, lon, years=None) -> BorisTrend | None`, `boris.get_boris_nrw(lat, lon) -> dict` (`{bodenrichtwert, date, zone, nutzung, gemeinde, raw}` or `{"error": …}`; `"BORIS timeout"` after 12 s), `boris.MissingData(RuntimeError)`; `flood.data_dir()`, `flood.flood_risk(lat, lon) -> dict` (raises `RuntimeError("Hochwasser-Daten fehlen unter …")` when `data_dir()` is absent), `flood.SCENARIOS()`/`flood._SCENARIOS_SHP()` become functions; `btw.data_dir()`, `btw.get_btw_wahlkreis_profile(lat, lon, top_n=5) -> dict`; `oepnv.get_oepnv(lat, lon, *, destinations: list[tuple[str, tuple]] | None = None) -> dict | None` (None destinations → `fixed_destinations()` only), `oepnv.fixed_destinations() -> list[tuple[str, str]]` (from `settings.oepnv_stops`).

- [ ] **Step 1: Copy the four modules**

```bash
H=/srv/house-hunter; cd /srv/nrw-redat
cp $H/backend/boris_service.py redat/sources/boris.py
cp $H/backend/flood_service.py redat/sources/flood.py
cp $H/backend/btw_service.py redat/sources/btw.py
cp $H/backend/oepnv_service.py redat/sources/oepnv.py
cp $H/tests/test_flood_service_finite.py $H/tests/test_oepnv_service.py tests/
```

- [ ] **Step 2: Failing BORIS tests**

`tests/test_boris.py`:
```python
import pytest

from redat.sources import boris


def test_data_dir_follows_settings():
    from redat.settings import get_settings
    assert boris.data_dir() == get_settings().source_dir / "boris"


def test_find_shapefile_none_when_missing():
    assert boris._find_shapefile(2025) is None


def test_lookup_raises_missing_data_with_path():
    with pytest.raises(boris.MissingData, match="BORIS-Daten fehlen unter .*source/boris"):
        boris.lookup_bodenrichtwert(51.45, 7.01)


def test_get_boris_nrw_maps_result(monkeypatch):
    res = boris.BorisResult(bodenrichtwert=410.0, stichtag="2025-01-01", nutzung="W", zone_name="Z1", gemeinde="Essen", year=2025, raw={"a": 1})
    monkeypatch.setattr(boris, "_lookup_in_subprocess", lambda lat, lon: res)
    assert boris.get_boris_nrw(51.45, 7.01) == {"bodenrichtwert": 410.0, "date": "2025-01-01", "zone": "Z1", "nutzung": "W", "gemeinde": "Essen", "raw": {"a": 1}}


def test_get_boris_nrw_no_data(monkeypatch):
    monkeypatch.setattr(boris, "_lookup_in_subprocess", lambda lat, lon: None)
    assert boris.get_boris_nrw(51.45, 7.01) == {"error": "No BORIS data for this location"}


def test_get_boris_nrw_error_passthrough(monkeypatch):
    monkeypatch.setattr(boris, "_lookup_in_subprocess", lambda lat, lon: {"__error__": "BORIS-Daten fehlen unter /x"})
    assert boris.get_boris_nrw(51.45, 7.01) == {"error": "BORIS-Daten fehlen unter /x"}


def test_get_boris_nrw_timeout(monkeypatch):
    monkeypatch.setattr(boris, "_lookup_in_subprocess", lambda lat, lon: boris._TIMEOUT)
    assert boris.get_boris_nrw(51.45, 7.01) == {"error": "BORIS timeout"}


def test_subprocess_wrapper_returns_missing_data_error_for_real():
    # end-to-end through the real subprocess against the (empty) tmp source dir
    out = boris.get_boris_nrw(51.45, 7.01)
    assert out["error"].startswith("BORIS-Daten fehlen unter")
```

- [ ] **Step 3: Edit `redat/sources/boris.py`**

- Replace `DATA_DIR = Path(__file__).parent.parent / "data" / "boris"` with
  ```python
  from redat.settings import get_settings


  class MissingData(RuntimeError):
      """The local BRW shapefiles are not where settings.source_dir says (deploy asset, not in git)."""


  def data_dir() -> Path:
      return get_settings().source_dir / "boris"
  ```
  and every `DATA_DIR` reference → `data_dir()` (`_find_shapefile`, `get_available_years`, anywhere else — `grep -n DATA_DIR`).
- In `lookup_bodenrichtwert`, before any shapefile read: `if not data_dir().exists(): raise MissingData(f"BORIS-Daten fehlen unter {data_dir()}")`. Same guard at the top of `_trend_uncached`.
- Append the subprocess wrapper (was `EnrichmentService.get_boris_nrw`):
  ```python
  _TIMEOUT = object()  # sentinel returned by _lookup_in_subprocess when the worker is killed


  def _worker(queue, lat: float, lon: float) -> None:
      try:
          queue.put(lookup_bodenrichtwert(lat, lon))
      except Exception as e:  # noqa: BLE001 — serialised back to the parent
          queue.put({"__error__": str(e)})


  def _lookup_in_subprocess(lat: float, lon: float):
      """Run the (memory-heavy) shapefile lookup in a child process with a 12 s hard cap."""
      from multiprocessing import Process, Queue
      q: Queue = Queue()
      p = Process(target=_worker, args=(q, lat, lon), daemon=True)
      p.start()
      p.join(timeout=12)
      if p.is_alive():
          p.kill()
          return _TIMEOUT
      return q.get() if not q.empty() else None


  def get_boris_nrw(lat: float, lon: float) -> dict:
      """{bodenrichtwert, date, zone, nutzung, gemeinde, raw} or {"error": …} — never raises."""
      try:
          out = _lookup_in_subprocess(lat, lon)
      except Exception as e:  # noqa: BLE001
          logger.error("BORIS error: %s", e)
          return {"error": str(e)}
      if out is _TIMEOUT:
          return {"error": "BORIS timeout"}
      if isinstance(out, dict) and out.get("__error__"):
          return {"error": out["__error__"]}
      if out:
          return {"bodenrichtwert": out.bodenrichtwert, "date": out.stichtag, "zone": out.zone_name,
                  "nutzung": out.nutzung, "gemeinde": out.gemeinde, "raw": out.raw}
      return {"error": "No BORIS data for this location"}
  ```
  `_worker` must be a module-level function (picklable under the `spawn`/`forkserver` start methods). The child inherits `REDAT_DATA_DIR` via the environment (or the forked settings cache), so `data_dir()` resolves identically there.

Run: `pytest tests/test_boris.py -q` → 8 passed (the last one spawns one real child process).

- [ ] **Step 4: Flood**

Edit `redat/sources/flood.py`:
- Replace the `DATA_DIR` constant and the two module-level dicts with functions:
  ```python
  from redat.settings import get_settings


  def data_dir() -> Path:
      return get_settings().source_dir / "flood" / "hwrm"


  def SCENARIOS() -> dict[str, Path]:
      d = data_dir()
      return {"HQhaeufig": d / "HQhaeufig.gpkg", "HQ100": d / "HQ100.gpkg", "HQextrem": d / "HQextrem.gpkg"}


  def _SCENARIOS_SHP() -> dict[str, Path]:
      d = data_dir()
      return {  # shapefile fallback (only the .gpkg files are copied to REDAT, but keep the lookup)
          "HQhaeufig": d / "HQhaeufig-Ueberschwemmungsgrenzen_EPSG25832_Shape" / "ueberflutungsgrenzen_hohe_wahrscheinlichkeit.shp",
          "HQ100": d / "HQ100-Ueberschwemmungsgrenzen_EPSG25832_Shape" / "ueberflutungsgrenzen_mittlere_wahrscheinlichkeit.shp",
          "HQextrem": d / "HQextrem-Ueberschwemmungsgrenzen_EPSG25832_Shape" / "ueberflutungsgrenzen_niedrige Wahrscheinlichkeit.shp",
      }
  ```
  `_hit_for_scenario`: `SCENARIOS.get(scenario)` → `SCENARIOS().get(scenario)`, `_SCENARIOS_SHP.get` → `_SCENARIOS_SHP().get`; iterate `SCENARIOS()` wherever the dict was iterated in `flood_risk`.
- Top of `flood_risk`: `if not data_dir().exists(): raise RuntimeError(f"Hochwasser-Daten fehlen unter {data_dir()}")`.
- Delete the `if __name__ == "__main__":` block (it imported `enrichment_service`).

`tests/test_flood_service_finite.py` becomes:
```python
"""flood must never emit float('inf') — FastAPI's JSON encoder rejects it (500)."""
import json

import pytest

from redat.sources import flood


def _empty_data_dir(tmp_path, monkeypatch):
    d = tmp_path / "hwrm"
    d.mkdir()
    monkeypatch.setattr(flood, "data_dir", lambda: d)
    return d


def test_hit_without_data_has_none_distance(tmp_path, monkeypatch):
    _empty_data_dir(tmp_path, monkeypatch)
    hit = flood._hit_for_scenario(51.45, 7.01, "HQ100")
    assert hit.hit is False and hit.min_distance_m is None


def test_flood_risk_is_json_serializable_without_files(tmp_path, monkeypatch):
    _empty_data_dir(tmp_path, monkeypatch)
    result = flood.flood_risk(51.45, 7.01)
    text = json.dumps(result, allow_nan=False)
    assert result["zone"] is None and result["risk_level"] == "low"
    for sc in ("HQhaeufig", "HQ100", "HQextrem"):
        assert result["hits"][sc]["min_distance_m"] is None
    assert "Infinity" not in text


def test_flood_risk_missing_dir_raises_precise_error(tmp_path, monkeypatch):
    monkeypatch.setattr(flood, "data_dir", lambda: tmp_path / "nope")
    with pytest.raises(RuntimeError, match="Hochwasser-Daten fehlen unter .*nope"):
        flood.flood_risk(51.45, 7.01)


def test_scenario_paths_follow_settings():
    from redat.settings import get_settings
    assert flood.SCENARIOS()["HQ100"] == get_settings().source_dir / "flood" / "hwrm" / "HQ100.gpkg"
```

- [ ] **Step 5: BTW**

Edit `redat/sources/btw.py`:
- Delete `BASE_DIR`, `DATA_DIR`, the import-time `DATA_DIR.mkdir(...)`, `SHP_FOLDER`, `SHP_PATH`; add
  ```python
  from redat.http import headers
  from redat.settings import get_settings


  def data_dir() -> Path:
      return get_settings().source_dir / "elections" / "btw25"


  def shp_path() -> Path:
      return data_dir() / "wahlkreise_shp_geo" / "btw25_geometrie_wahlkreise_vg250_shp_geo" / "Wahlkreise_WGS84.shp"
  ```
  `ensure_wahlkreis_shapefile()`: `SHP_PATH` → `shp_path()`, `SHP_FOLDER` → `data_dir() / "wahlkreise_shp_geo"`, and `mkdir(parents=True, exist_ok=True)` on `data_dir()` at the top of this function (it downloads into it). Wherever `kerg2.csv` is cached under `DATA_DIR`, use `data_dir()` (and mkdir there too). `httpx.Client(timeout=60.0, follow_redirects=True)` → add `headers=headers()`.
- Any `@lru_cache` on loaders that captured the old constant path stays — they key on nothing, which is fine because the path is settings-constant per process.

`tests/test_btw.py`:
```python
from redat.sources import btw


def test_paths_follow_settings():
    from redat.settings import get_settings
    assert btw.data_dir() == get_settings().source_dir / "elections" / "btw25"
    assert btw.shp_path().name == "Wahlkreise_WGS84.shp"


def test_import_does_not_create_directories():
    # the old module mkdir'ed at import; REDAT must not touch the filesystem on import
    assert not btw.data_dir().exists()
```

- [ ] **Step 6: ÖPNV — destinations come from the caller or settings**

Edit `redat/sources/oepnv.py`:
- Remove `import config` and `from geocoding import GeocodeResult, geocode_with_precision`.
- Replace `FIXED_DESTINATIONS = [...]` with
  ```python
  from redat.http import headers
  from redat.settings import get_settings


  def fixed_destinations() -> list[tuple[str, str]]:
      """(name, EFA stop id) of the fixed trip targets — settings.yaml `oepnv_stops`."""
      return list(get_settings().oepnv_stops)
  ```
- Delete `_config_destinations` entirely and `_MAX_CUSTOM_DESTINATIONS` (the API layer enforces ≤ 10 destinations).
- In `get_oepnv`: `dests = destinations if destinations is not None else [(n, ("stop", sid)) for n, sid in fixed_destinations()]`; `fixed_ids = {sid for _, sid in fixed_destinations()}`.
- `httpx.get(EFA_URL + endpoint, …)` → add `headers=headers()`.

`tests/test_oepnv_service.py`: `import oepnv_service as ov` → `from redat.sources import oepnv as ov`; delete `test_default_destinations_from_config` and replace with:
```python
def test_default_destinations_are_the_settings_stops(monkeypatch):
    calls = stub(monkeypatch)
    d = ov.get_oepnv(51.4378, 7.0053)
    assert [t["name"] for t in d["trips"]] == ["Essen Hbf", "Bochum Hbf", "Düsseldorf Hbf"]
    dests = [p["name_destination"] for e, p in calls if e == "XML_TRIP_REQUEST2"]
    assert dests == ["de:05113:9289", "de:05911:5194", "de:05111:18235"]
    assert all(t["kind"] == "fixed" for t in d["trips"])
```
(Check the trip dict's key for fixed/custom in the copied module — `grep -n '"fixed"' redat/sources/oepnv.py` — and use that key name in the last assertion.)

- [ ] **Step 7: Run everything, commit**

Run: `pytest tests -q` → all pass. `grep -rn "import config\|from geocoding\|enrichment_service" redat/` → empty.
```bash
git add -A && git commit -q -F - <<'EOF'
feat(sources): boris/flood/btw over settings.source_dir, oepnv destinations from settings

BORIS lookup keeps its 12 s subprocess cap as a plain function; missing geodata raises a
precise "…-Daten fehlen unter <path>" error instead of a silent "low"/traceback.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_015HbDiczEViCdm3XmxC2ReC
EOF
```

### Task 5: Section registry + envelope runner (with caller-supplied destinations)

**Files:**
- Create: `redat/core/sections.py` (← `$H/backend/analysis/sections.py`, replaces the Task 1 stub), `redat/core/envelope.py` (← `$H/backend/analysis/envelope.py`)
- Test: `tests/test_analysis_sections.py`, `tests/test_analysis_envelope.py` (← hunter's, adapted)

**Interfaces:**
- Consumes: every `redat.sources.*` public function (Tasks 2–4), `redat.core.tiers`, `Destination` (Task 1).
- Produces: `sections.Ctx(lat: float, lon: float, plot_size_m2: float | None = None, destinations: tuple[Destination, ...] = ())` (frozen dataclass); `sections.Empty(message)`; `sections.Section(key, title, icon, timeout_s, source, fetch)` with `.tier` property; `sections.SECTIONS: dict[str, Section]` in display order `boris, boris_trend, flood, starkregen, noise, bergbau, gfnp, schutzgebiete, planning_essen, planning_bochum, denkmal, amenities, oepnv, zensus, energie, breitband, infrastruktur, air_quality, btw, commute`; `sections.manifest() -> list[dict]` (`{key, title, icon, tier, timeout_s, source}`); `envelope.run_section(key, ctx, *, precision, force) -> dict`; `envelope.sanitize(obj)`; `envelope._gate_message(precision)`; `envelope.timeout_for(section) -> float` (settings override or `section.timeout_s`).

- [ ] **Step 1: Copy and rewrite imports**

```bash
H=/srv/house-hunter; cd /srv/nrw-redat
cp $H/backend/analysis/sections.py redat/core/sections.py
cp $H/backend/analysis/envelope.py redat/core/envelope.py
cp $H/tests/test_analysis_sections.py $H/tests/test_analysis_envelope.py tests/
```
In `redat/core/sections.py` rewrite each lazy import inside the `_fetch_*` bodies and `Section.tier`:

| old | new |
|---|---|
| `from enrichment_service import SERVICE_TIER` (in `tier`) | `from redat.core.tiers import SERVICE_TIER` |
| `from geoapify_service import get_all_amenities` | `from redat.sources.geoapify import get_all_amenities` |
| `import airquality_service` / `airquality_service.get_air_quality_report` | `from redat.sources import airquality` / `airquality.get_air_quality_report` |
| `from btw_service import get_btw_wahlkreis_profile` | `from redat.sources.btw import get_btw_wahlkreis_profile` |
| `from noise_service import get_noise_levels` | `from redat.sources.noise import get_noise_levels` |
| `from bergbau_service import …` | `from redat.sources.bergbau import …` |
| `from schutzgebiete_service import …` | `from redat.sources.schutzgebiete import …` |
| `from energie_service import …` | `from redat.sources.energie import …` |
| `from breitband_service import …` | `from redat.sources.breitband import …` |
| `from denkmal_service import …` | `from redat.sources.denkmal import …` |
| `from infrastruktur_service import …` | `from redat.sources.infrastruktur import …` |
| `from zensus_grid import lookup` | `from redat.sources.zensus import lookup` |
| `from boris_service import get_historical_trend` | `from redat.sources.boris import get_historical_trend` |
| `from flood_service import flood_risk` | `from redat.sources.flood import flood_risk` |
| `from starkregen_service import …` | `from redat.sources.starkregen import …` |
| `from gfnp_service import …` | `from redat.sources.gfnp import …` |
| `from planning_service import …` | `from redat.sources.planning_essen import …` |
| `from planning_bochum_service import …` | `from redat.sources.planning_bochum import …` |

Where hunter's code did `import xxx_service` and then `xxx_service.fn(...)`, use `from redat.sources import xxx` and `xxx.fn(...)` so tests can `monkeypatch.setattr(xxx, "fn", …)` on the module object.

- [ ] **Step 2: `Ctx.destinations`, commute via driving times, ÖPNV destinations, BORIS plain function**

In `redat/core/sections.py`:
```python
from redat.settings import Destination, get_settings


@dataclass(frozen=True)
class Ctx:
    lat: float
    lon: float
    plot_size_m2: Optional[float] = None
    destinations: tuple[Destination, ...] = ()   # caller-supplied; () → settings defaults


def _destinations(ctx: Ctx) -> tuple[Destination, ...]:
    return ctx.destinations or get_settings().destinations
```
Replace `_fetch_commute` with:
```python
def _fetch_commute(ctx: Ctx) -> dict:
    from redat.sources.geoapify import get_driving_time

    dests = _destinations(ctx)
    if not dests:
        raise Empty("Keine Zielorte konfiguriert (destinations)")
    rows = []
    for d in dests:
        try:
            r = get_driving_time(ctx.lat, ctx.lon, d.lat, d.lon) or {}
        except Exception as exc:  # noqa: BLE001 — one unreachable target must not blank the card
            logger.warning("commute: routing to %s failed: %s", d.name, exc)
            r = {}
        rows.append({"name": d.name, "address": d.address or None, "group": d.group,
                     "time_minutes": r.get("time_minutes"), "distance_km": r.get("distance_km")})
    return {"destinations": rows}
```
(`logger = logging.getLogger(__name__)` at module top if the file lacks one.)
Replace `_fetch_oepnv` with:
```python
def _fetch_oepnv(ctx: Ctx) -> dict:
    from redat.sources.oepnv import fixed_destinations, get_oepnv

    dests = [(n, ("stop", sid)) for n, sid in fixed_destinations()]
    dests += [(d.name, ("coord", d.lat, d.lon)) for d in ctx.destinations if d.group != "hbf"][:5]
    o = get_oepnv(ctx.lat, ctx.lon, destinations=dests)
    if o is None:
        raise Empty("Keine VRR-Haltestellen im Umkreis und keine Verbindung gefunden (außerhalb des VRR?)")
    return o
```
(The Hbf defaults are already covered by the fixed stop ids; only caller-supplied non-`hbf` places are added as coordinate trips, capped at 5 as before.)
Replace the body of `_fetch_boris` so it calls the plain function — keep the normalisation identical:
```python
def _fetch_boris(ctx: Ctx) -> Optional[dict]:
    from redat.sources.boris import get_boris_nrw

    b = get_boris_nrw(ctx.lat, ctx.lon)
    value = b.get("bodenrichtwert")
    if not value:
        err = b.get("error") or ""
        if not err or err.startswith("No BORIS data"):
            return None
        raise RuntimeError(err)
    ...  # unchanged from here (grundstueckswert = value * plot_size_m2 when given, else None)
```
`manifest()` gains `"source": s.source` per entry (spec §5.1).

- [ ] **Step 3: Envelope**

In `redat/core/envelope.py`: `from analysis import sections as _sections` → `from redat.core import sections as _sections`; `from analysis.sections import Ctx, Empty` → `from redat.core.sections import Ctx, Empty`; `from enrichment_service import enrichment_allowed` → `from redat.core.tiers import enrichment_allowed`. Add
```python
from redat.settings import get_settings


def timeout_for(section) -> float:
    """settings.yaml `section_timeouts` overrides the registry default."""
    return float(get_settings().section_timeouts.get(section.key, section.timeout_s))
```
and use `timeout_for(section)` where `run_section` reads `section.timeout_s` (both the `t.join(...)` and the `Timeout nach {…:g}s` message). Add one structured log line at the end of `run_section`: `log.info("section %s lat=%.5f lon=%.5f status=%s took_ms=%d", key, ctx.lat, ctx.lon, status, took_ms)`.

- [ ] **Step 4: Adapt the tests**

`tests/test_analysis_sections.py`:
- `from analysis import sections as S` → `from redat.core import sections as S`; `from analysis.sections import Ctx, Empty` → `from redat.core.sections import Ctx, Empty`.
- Every `import xxx_service` inside tests → `from redat.sources import xxx` with the `monkeypatch.setattr(xxx, …)` target renamed accordingly (`geoapify_service`→`geoapify`, `airquality_service`→`airquality`, `btw_service`→`btw`, `noise_service`→`noise`, `boris_service`→`boris`, `flood_service`→`flood`, `gfnp_service`→`gfnp`, `planning_service`→`planning_essen`, `planning_bochum_service`→`planning_bochum`, `starkregen_service`→`starkregen`, `bergbau_service`→`bergbau`, `zensus_grid`→`zensus`, `energie_service`→`energie`, `schutzgebiete_service`→`schutzgebiete`, `breitband_service`→`breitband`, `denkmal_service`→`denkmal`, `oepnv_service`→`oepnv`, `infrastruktur_service`→`infrastruktur`).
- `test_manifest_shape`: add `assert set(m[0]) == {"key", "title", "icon", "tier", "timeout_s", "source"}` (adjust the existing key-set assertion).
- Replace `_FakeSvc`/`_patch_boris` with `monkeypatch.setattr(boris, "get_boris_nrw", lambda lat, lon: payload)`; drop the `assert svc.closed` line.
- Replace the two commute tests with:
```python
def test_commute_uses_ctx_destinations_then_defaults(monkeypatch):
    from redat.sources import geoapify
    from redat.settings import Destination
    seen = []
    def fake(flat, flon, tlat, tlon):
        seen.append((tlat, tlon))
        return {"time_minutes": 12, "distance_km": 5.4} if tlat == 51.5 else None
    monkeypatch.setattr(geoapify, "get_driving_time", fake)
    ctx = Ctx(lat=51.4, lon=7.0, destinations=(Destination("Büro", 51.5, 7.1, "work", "Kettwiger Str. 1"), Destination("Oma", 51.6, 7.2)))
    assert S._fetch_commute(ctx) == {"destinations": [
        {"name": "Büro", "address": "Kettwiger Str. 1", "group": "work", "time_minutes": 12, "distance_km": 5.4},
        {"name": "Oma", "address": None, "group": "custom", "time_minutes": None, "distance_km": None},
    ]}
    assert seen == [(51.5, 7.1), (51.6, 7.2)]
    seen.clear()
    S._fetch_commute(Ctx(lat=51.4, lon=7.0))
    assert [n for n, _ in seen] == [51.4508, 51.4785, 51.2199]   # settings.yaml Hbf defaults


def test_commute_without_any_destinations_is_empty(monkeypatch):
    monkeypatch.setattr(S, "_destinations", lambda ctx: ())
    with pytest.raises(Empty) as ei:
        S._fetch_commute(Ctx(lat=51.4, lon=7.0))
    assert "Keine Zielorte" in ei.value.message


def test_oepnv_passes_fixed_stops_plus_custom_coords(monkeypatch):
    from redat.sources import oepnv
    from redat.settings import Destination
    seen = {}
    def fake(lat, lon, *, destinations=None):
        seen["d"] = destinations
        return {"stops": [], "trips": []}
    monkeypatch.setattr(oepnv, "get_oepnv", fake)
    ctx = Ctx(lat=51.4, lon=7.0, destinations=(Destination("Essen Hbf", 51.45, 7.01, "hbf"), Destination("Büro", 51.5, 7.1, "work")))
    S._fetch_oepnv(ctx)
    assert seen["d"] == [("Essen Hbf", ("stop", "de:05113:9289")), ("Bochum Hbf", ("stop", "de:05911:5194")),
                         ("Düsseldorf Hbf", ("stop", "de:05111:18235")), ("Büro", ("coord", 51.5, 7.1))]
```
- Keep `test_oepnv_passes_through_and_is_area`/`test_oepnv_none_is_empty` but their fake must accept `destinations=None` as a keyword.

`tests/test_analysis_envelope.py`: `from analysis import sections as S` → `from redat.core import sections as S`; `from analysis.envelope import run_section, sanitize` → `from redat.core.envelope import run_section, sanitize`; `import enrichment_service` + `monkeypatch.setitem(enrichment_service.SERVICE_TIER, …)` → `from redat.core import tiers` + `monkeypatch.setitem(tiers.SERVICE_TIER, …)`. Add:
```python
def test_settings_timeout_override(monkeypatch):
    from redat.core import envelope as E
    from redat.core.sections import SECTIONS
    monkeypatch.setattr(E, "get_settings", lambda: type("S", (), {"section_timeouts": {"noise": 1.5}})())
    assert E.timeout_for(SECTIONS["noise"]) == 1.5
    assert E.timeout_for(SECTIONS["boris"]) == SECTIONS["boris"].timeout_s
```

- [ ] **Step 5: Run, commit**

Run: `pytest tests -q` → all pass; `pytest tests/test_analysis_sections.py -q` alone shows ≈ 60. Then:
```bash
git add -A && git commit -q -F - <<'EOF'
feat(core): section registry + envelope runner; commute/ÖPNV take caller destinations

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_015HbDiczEViCdm3XmxC2ReC
EOF
```

### Task 6: Report package (builder, render, PDF, noise map, SVG) + report templates

**Files:**
- Create: `redat/templating.py`; `redat/report/{builder,render,pdf,noise_map,svg}.py` (← `$H/backend/report/*.py`); `redat/templates/report/report.html` + `redat/templates/report/_*.html` (← `$H/frontend/templates/report/`); `redat/templates/analysis/_*.html` (← `$H/frontend/templates/analysis/`, used by the website in Task 9 — copied now so the template dir is complete)
- Test: `tests/test_report_builder.py`, `test_report_render.py`, `test_report_svg.py`, `test_noise_map.py` (← hunter's, adapted), `tests/fixtures/report_envelopes.json` (← `$H/tests/fixtures/report_envelopes.json`)

**Interfaces:**
- Consumes: `redat.core.sections.SECTIONS`, `redat.http.headers()`.
- Produces: `templating.templates: Jinja2Templates` (directory `redat/templates`), `templating.env` (its `Environment`); `builder.ReportPayloadError`, `builder.build_report_context(payload, *, now=None) -> dict` (no `listing` kwarg / key), `builder.slugify(text) -> str`, `builder.fmt_int/fmt_num/fmt_date/fmt_m`; `render.render_report_html(ctx) -> str`, `render.render_section_html(key, data, **extra) -> str`; `pdf.html_to_pdf(html, *, header_address, generated_at) -> bytes`, `pdf.RendererUnavailable`; `noise_map.render_noise_maps(lat, lon) -> dict`, `noise_map.LEGEND_BANDS`; `svg.boris_trend_svg(history) -> str`.

- [ ] **Step 1: Copy**

```bash
H=/srv/house-hunter; cd /srv/nrw-redat
cp $H/backend/report/{builder,render,pdf,noise_map,svg}.py redat/report/
cp $H/frontend/templates/report/*.html redat/templates/report/
cp $H/frontend/templates/analysis/*.html redat/templates/analysis/
mkdir -p tests/fixtures && cp $H/tests/fixtures/report_envelopes.json tests/fixtures/
cp $H/tests/test_report_builder.py $H/tests/test_report_render.py $H/tests/test_report_svg.py $H/tests/test_noise_map.py tests/
```

- [ ] **Step 2: `redat/templating.py`**

```python
"""One Jinja environment for the website and the PDF report (filters registered by report.render)."""
from pathlib import Path

from fastapi.templating import Jinja2Templates

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
env = templates.env
```

- [ ] **Step 3: Edits in the copied report modules**

- `render.py`: `from app_config import templates` → `from redat.templating import templates`; `from report import builder` → `from redat.report import builder`.
- `builder.py`: `from analysis.sections import SECTIONS` → `from redat.core.sections import SECTIONS`; signature `build_report_context(payload: dict, *, now: Optional[datetime] = None)`; delete the `"listing": listing,` line. Add to the `_validate` helper nothing — it already rejects unknown keys / missing status. `_s_commute` stays (its rows still have `name`/`time_minutes`).
- `report.html`: delete lines 107–117 (the `{% if listing %} … {% endif %}` box) and the `.listing-box` CSS rule; the footer/source line that says "House Hunter" → "NRW-REDAT" (grep `House Hunter` / `house-hunter` in `redat/templates/report/`).
- `pdf.py`: header text `"Standortanalyse · House Hunter"` → `"Standortanalyse · NRW-REDAT"` (grep to find it).
- `noise_map.py`: `headers={"User-Agent": "house-hunter-report/1.0"}` → `headers=headers()` with `from redat.http import headers`.
- `redat/templates/analysis/_*.html`: no edits now (Alpine store functions they reference are provided by Task 9's `redat.js`).

- [ ] **Step 4: Adapt tests**

- Imports: `from analysis.sections import SECTIONS` → `from redat.core.sections import SECTIONS`; `from report import builder` → `from redat.report import builder`; `from report.builder import …` → `from redat.report.builder import …`; `from report.render import …` → `from redat.report.render import …`; `from report.svg import …` → `from redat.report.svg import …`; `from report import noise_map` / `from report.noise_map import …` → `from redat.report import noise_map` / `from redat.report.noise_map import …`.
- `test_report_builder.py`: delete `"listing_id": None,` from `_payload()`; replace `test_listing_block_and_meta` with
  ```python
  def test_context_has_no_listing_key():
      ctx = build_report_context(_payload())
      assert "listing" not in ctx
      assert ctx["generated_date"] and ctx["formatted_address"]
  ```
- `test_report_render.py`: drop `"listing_id": None,` from the payload; rename `test_full_report_appendix_and_listing` → `test_full_report_appendix` and remove its `listing=` kwarg and any assertion on the listing box (`"Reihenhaus in Werden"`, the URL); add `assert "NRW-REDAT" in html and "House Hunter" not in html`.
- The `@pytest.mark.parametrize` over `SECTIONS` × `{fixture, {}}` in `test_report_render.py` is already the collapsed form spec §9 asks for — keep it.

- [ ] **Step 5: Run, commit**

Run: `pytest tests -q` → all pass (`pytest tests/test_report_render.py -q` ≈ 43).
```bash
git add -A && git commit -q -F - <<'EOF'
feat(report): move builder/render/pdf/noise_map/svg + report and card templates; drop the listing box

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_015HbDiczEViCdm3XmxC2ReC
EOF
```

### Task 7: Store — saved runs (SQLite) + section cache

**Files:**
- Create: `redat/store/runs.py` (replaces the Task 1 stub), `redat/store/cache.py`
- Test: `tests/test_store_runs.py`, `tests/test_store_cache.py`

**Interfaces:**
- Produces: `RunStore(db_path: Path)` with `init() -> None` (creates table, WAL), `save(payload: dict) -> str` (returns run id), `get(run_id: str) -> dict | None` (payload + `id`, `created_at` ISO string), `new_run_id() -> str` (10 chars, base32 lower, no padding); `SectionCache(ttl_s: int)` with `key(section, lat, lon, plot_size_m2, force) -> tuple`, `get(k) -> dict | None`, `put(k, envelope) -> None` (stores only `status in ("ok", "empty")`), `clear()`.
- Consumed by Task 8.

- [ ] **Step 1: Tests**

`tests/test_store_runs.py`:
```python
import re
import sqlite3
from redat.store.runs import RunStore

PAYLOAD = {
    "address": "Brückstraße 1, Essen", "formatted_address": "Brückstraße 1, 45239 Essen",
    "latitude": 51.3878, "longitude": 7.0011, "precision": "house",
    "plot_size_m2": 400, "living_space_m2": 120,
    "sections": {"noise": {"key": "noise", "status": "ok", "data": {"day": None}}},
}


def _store(tmp_path):
    s = RunStore(tmp_path / "redat.db"); s.init(); return s


def test_new_run_id_shape(tmp_path):
    s = _store(tmp_path)
    ids = {s.new_run_id() for _ in range(50)}
    assert len(ids) == 50 and all(re.fullmatch(r"[a-z2-7]{10}", i) for i in ids)


def test_save_and_get_roundtrip(tmp_path):
    s = _store(tmp_path)
    rid = s.save(PAYLOAD)
    got = s.get(rid)
    assert got["id"] == rid and got["created_at"].endswith("Z")
    for k, v in PAYLOAD.items():
        assert got[k] == v


def test_get_unknown_is_none(tmp_path):
    assert _store(tmp_path).get("nope") is None


def test_init_is_idempotent_and_wal(tmp_path):
    s = _store(tmp_path); s.init()
    con = sqlite3.connect(s.db_path)
    assert con.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_save_requires_coordinates(tmp_path):
    import pytest
    with pytest.raises(ValueError):
        _store(tmp_path).save({**PAYLOAD, "latitude": None})
```

`tests/test_store_cache.py`:
```python
from redat.store.cache import SectionCache


def _env(status): return {"key": "noise", "status": status, "data": {}}


def test_key_rounds_coordinates_to_4_places():
    c = SectionCache(60)
    assert c.key("noise", 51.38784, 7.00106, None, False) == c.key("noise", 51.38781, 7.00109, None, False)
    assert c.key("noise", 51.3878, 7.0011, None, False) != c.key("noise", 51.3878, 7.0011, None, True)
    assert c.key("boris", 51.3878, 7.0011, 400, False) != c.key("boris", 51.3878, 7.0011, 500, False)


def test_put_get_only_ok_and_empty(monkeypatch):
    c = SectionCache(60)
    k = c.key("noise", 51.3878, 7.0011, None, False)
    c.put(k, _env("error")); assert c.get(k) is None
    c.put(k, _env("gated")); assert c.get(k) is None
    c.put(k, _env("empty")); assert c.get(k)["status"] == "empty"
    c.put(k, _env("ok")); assert c.get(k)["status"] == "ok"


def test_get_returns_copy_marked_cached():
    c = SectionCache(60)
    k = c.key("noise", 1, 2, None, False)
    env = _env("ok"); c.put(k, env)
    got = c.get(k)
    assert got["cached"] is True and "cached" not in env


def test_expiry(monkeypatch):
    import redat.store.cache as m
    now = [1000.0]
    monkeypatch.setattr(m.time, "monotonic", lambda: now[0])
    c = SectionCache(10)
    k = c.key("noise", 1, 2, None, False); c.put(k, _env("ok"))
    now[0] += 9; assert c.get(k) is not None
    now[0] += 2; assert c.get(k) is None


def test_ttl_zero_disables():
    c = SectionCache(0)
    k = c.key("noise", 1, 2, None, False); c.put(k, _env("ok"))
    assert c.get(k) is None
```

- [ ] **Step 2: Run** → `ModuleNotFoundError: redat.store.cache` / `RunStore` has no `save`.

- [ ] **Step 3: `redat/store/runs.py`**

```python
"""Saved analyses (permalinks). One SQLite file under REDAT_DATA_DIR."""
import base64
import json
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_DDL = """
CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  address TEXT NOT NULL,
  formatted_address TEXT,
  latitude REAL NOT NULL,
  longitude REAL NOT NULL,
  precision TEXT,
  plot_size_m2 REAL,
  living_space_m2 REAL,
  sections_json TEXT NOT NULL
);
"""
_COLS = ("address", "formatted_address", "latitude", "longitude", "precision",
         "plot_size_m2", "living_space_m2")


class RunStore:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path, timeout=10)
        con.row_factory = sqlite3.Row
        return con

    def init(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as con:
            con.execute("PRAGMA journal_mode=WAL")
            con.executescript(_DDL)

    @staticmethod
    def new_run_id() -> str:
        return base64.b32encode(secrets.token_bytes(6)).decode().rstrip("=").lower()

    def save(self, payload: dict) -> str:
        if payload.get("latitude") is None or payload.get("longitude") is None:
            raise ValueError("latitude/longitude required")
        if not payload.get("address"):
            raise ValueError("address required")
        rid = self.new_run_id()
        created = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        row = [rid, created] + [payload.get(c) for c in _COLS] + [json.dumps(payload.get("sections") or {}, ensure_ascii=False)]
        with self._connect() as con:
            con.execute(
                f"INSERT INTO runs (id, created_at, {', '.join(_COLS)}, sections_json) "
                f"VALUES ({', '.join('?' * (len(_COLS) + 3))})", row)
        return rid

    def get(self, run_id: str) -> Optional[dict]:
        with self._connect() as con:
            r = con.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if r is None:
            return None
        out = {k: r[k] for k in r.keys() if k != "sections_json"}
        out["sections"] = json.loads(r["sections_json"])
        return out
```

- [ ] **Step 4: `redat/store/cache.py`**

```python
"""In-process TTL cache for section envelopes. Only ok/empty results are kept (spec §7)."""
import copy
import threading
import time
from typing import Optional

_CACHEABLE = ("ok", "empty")


class SectionCache:
    def __init__(self, ttl_s: int):
        self.ttl_s = max(0, int(ttl_s))
        self._data: dict[tuple, tuple[float, dict]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def key(section: str, lat: float, lon: float, plot_size_m2, force: bool) -> tuple:
        plot = None if plot_size_m2 in (None, 0) else float(plot_size_m2)
        return (section, round(float(lat), 4), round(float(lon), 4), plot, bool(force))

    def get(self, k: tuple) -> Optional[dict]:
        if self.ttl_s == 0:
            return None
        with self._lock:
            hit = self._data.get(k)
            if hit is None:
                return None
            expires, env = hit
            if time.monotonic() >= expires:
                del self._data[k]
                return None
        out = copy.deepcopy(env)
        out["cached"] = True
        return out

    def put(self, k: tuple, envelope: dict) -> None:
        if self.ttl_s == 0 or envelope.get("status") not in _CACHEABLE:
            return
        with self._lock:
            self._data[k] = (time.monotonic() + self.ttl_s, copy.deepcopy(envelope))

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
```

- [ ] **Step 5: Run, commit**

`pytest tests/test_store_runs.py tests/test_store_cache.py -q` → 10 pass; `pytest tests -q` green.
```bash
git add -A && git commit -q -F - <<'EOF'
feat(store): RunStore (SQLite runs table, WAL, base32 ids) + SectionCache (TTL, ok/empty only)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_015HbDiczEViCdm3XmxC2ReC
EOF
```

### Task 8: API v1 — auth, orchestration, all routes

**Files:**
- Create: `redat/api/auth.py`, `redat/core/analyze.py`, `redat/report/service.py`
- Modify: `redat/api/v1.py` (replace Task 1 stub), `redat/app.py` (add `app.state.cache`)
- Test: `tests/test_api_auth.py`, `tests/test_analyze_core.py`, `tests/test_api_v1.py`

**Interfaces:**
- Consumes: `redat.core.envelope.run_section(key, ctx, precision=, force=)`, `redat.core.sections.SECTIONS/Ctx/manifest()`, `redat.core.geocoding.geocode_with_precision/GeocoderUnavailable/GeocodeResult`, `redat.sources.geoapify.autocomplete_address(text, limit=)`, `redat.settings.Destination/get_settings`, `redat.store.runs.RunStore`, `redat.store.cache.SectionCache`, `redat.report.builder.build_report_context/ReportPayloadError/slugify`, `redat.report.render.render_report_html`, `redat.report.noise_map.render_noise_maps`, `redat.report.svg.boris_trend_svg`, `redat.report.pdf.html_to_pdf/RendererUnavailable`.
- Produces: `auth.require_api_key(request)` FastAPI dependency; `analyze.parse_destinations(raw: str | None) -> tuple[Destination, ...]` (raises `ValueError`); `analyze.run_all(*, lat, lon, precision, plot_size_m2, force, destinations, cache) -> dict[str, dict]` (all sections, pool of 6, cache-aware); `analyze.geocode_or_raise(address) -> GeocodeResult` (raises `HTTPException` 422/502); `analyze.run_to_payload(run) -> dict` (stored run → report/POST-runs payload shape); `analyze.payload_to_run(payload) -> dict` (POST-runs body → `RunStore.save` shape); `report.service.render_pdf(payload) -> tuple[bytes, dict]` (ctx has `formatted_address`, `address`, `generated_date`); `report.service.pdf_filename(ctx) -> str`; `report.service.pdf_response(pdf, ctx) -> Response`.
- Routes (all under `/api/v1`, all behind `require_api_key`): `GET sections`, `GET geocode`, `GET autocomplete`, `GET section/{key}`, `GET analyze`, `POST runs`, `GET run/{id}`, `POST report`, `GET report`, `GET run/{id}/report.pdf`.

- [ ] **Step 1: Auth tests + `redat/api/auth.py`**

`tests/test_api_auth.py`:
```python
from fastapi.testclient import TestClient
from redat.settings import reset_settings


def _client():
    from redat.app import create_app
    return TestClient(create_app())


def test_api_open_when_no_key():
    r = _client().get("/api/v1/sections")
    assert r.status_code == 200


def test_api_requires_key_when_set(monkeypatch):
    monkeypatch.setenv("REDAT_API_KEY", "s3cret"); reset_settings()
    c = _client()
    assert c.get("/api/v1/sections").status_code == 401
    assert c.get("/api/v1/sections", headers={"X-Api-Key": "wrong"}).status_code == 401
    assert c.get("/api/v1/sections", headers={"X-Api-Key": "s3cret"}).status_code == 200
    assert c.get("/healthz").status_code == 200  # never gated
    assert c.get("/docs").status_code == 200
```

`redat/api/auth.py`:
```python
"""Optional API key: when REDAT_API_KEY is set, every /api/* route needs X-Api-Key (spec §5)."""
import secrets

from fastapi import HTTPException, Request

from redat.settings import get_settings


def require_api_key(request: Request) -> None:
    expected = get_settings().api_key
    if not expected:
        return
    given = request.headers.get("X-Api-Key") or ""
    if not secrets.compare_digest(given, expected):
        raise HTTPException(status_code=401, detail="X-Api-Key fehlt oder ist ungültig")
```

- [ ] **Step 2: `tests/test_analyze_core.py`**

```python
import json
import pytest
from fastapi import HTTPException

import redat.core.analyze as A
from redat.core.geocoding import GeocodeResult, GeocoderUnavailable
from redat.settings import Destination
from redat.store.cache import SectionCache


def test_parse_destinations_none_is_empty():
    assert A.parse_destinations(None) == ()
    assert A.parse_destinations("") == ()


def test_parse_destinations_ok():
    raw = json.dumps([{"name": "Arbeit", "lat": 51.45, "lon": 7.01, "group": "work"},
                      {"name": "Oma", "lat": 51.5, "lon": 7.2}])
    ds = A.parse_destinations(raw)
    assert ds == (Destination("Arbeit", 51.45, 7.01, "work"), Destination("Oma", 51.5, 7.2, "custom"))


@pytest.mark.parametrize("raw", [
    "not json", "{}", json.dumps([{"name": "x"}]), json.dumps([{"name": "", "lat": 1, "lon": 2}]),
    json.dumps([{"name": "x", "lat": "a", "lon": 2}]), json.dumps([{"name": "x", "lat": 91, "lon": 2}]),
    json.dumps([{"name": "x", "lat": 1, "lon": 2}] * 11),
])
def test_parse_destinations_rejects(raw):
    with pytest.raises(ValueError):
        A.parse_destinations(raw)


def test_run_all_uses_pool_and_cache(monkeypatch):
    calls = []

    def fake_run_section(key, ctx, precision=None, force=False):
        calls.append(key)
        return {"key": key, "tier": "area", "status": "ok" if key != "boris" else "error",
                "data": {}, "message": None, "source": "x", "took_ms": 1}
    monkeypatch.setattr(A, "run_section", fake_run_section)
    cache = SectionCache(60)
    out = A.run_all(lat=51.45, lon=7.01, precision="house", plot_size_m2=None, force=False,
                    destinations=(), cache=cache)
    assert set(out) == set(A.SECTIONS) and sorted(calls) == sorted(A.SECTIONS)
    assert "cached" not in out["noise"]
    calls.clear()
    out2 = A.run_all(lat=51.45, lon=7.01, precision="house", plot_size_m2=None, force=False,
                     destinations=(), cache=cache)
    assert calls == ["boris"]  # only the error result was not cached
    assert out2["noise"]["cached"] is True


def test_run_all_passes_ctx(monkeypatch):
    seen = {}

    def fake_run_section(key, ctx, precision=None, force=False):
        seen[key] = (ctx, precision, force)
        return {"key": key, "status": "empty", "data": None}
    monkeypatch.setattr(A, "run_section", fake_run_section)
    d = (Destination("Arbeit", 51.45, 7.01, "work"),)
    A.run_all(lat=1.0, lon=2.0, precision="street", plot_size_m2=300, force=True, destinations=d,
              cache=SectionCache(0))
    ctx, precision, force = seen["commute"]
    assert (ctx.lat, ctx.lon, ctx.plot_size_m2, ctx.destinations) == (1.0, 2.0, 300, d)
    assert precision == "street" and force is True


def test_geocode_or_raise(monkeypatch):
    monkeypatch.setattr(A, "geocode_with_precision", lambda a: None)
    with pytest.raises(HTTPException) as e:
        A.geocode_or_raise("nirgendwo")
    assert e.value.status_code == 422

    def boom(a): raise GeocoderUnavailable("both down")
    monkeypatch.setattr(A, "geocode_with_precision", boom)
    with pytest.raises(HTTPException) as e:
        A.geocode_or_raise("x")
    assert e.value.status_code == 502

    ok = GeocodeResult(formatted_address="F", latitude=1.0, longitude=2.0, precision="house")
    monkeypatch.setattr(A, "geocode_with_precision", lambda a: ok)
    assert A.geocode_or_raise("x") is ok


def test_payload_run_roundtrip():
    payload = {"address": "A", "geocode": {"formatted_address": "F", "latitude": 1.0, "longitude": 2.0,
               "precision": "house"}, "plot_size_m2": 400, "living_space_m2": None, "sections": {"noise": {"status": "ok"}}}
    run = A.payload_to_run(payload)
    assert run == {"address": "A", "formatted_address": "F", "latitude": 1.0, "longitude": 2.0,
                   "precision": "house", "plot_size_m2": 400, "living_space_m2": None,
                   "sections": {"noise": {"status": "ok"}}}
    back = A.run_to_payload({**run, "id": "abc", "created_at": "2026-09-05T10:00:00Z"})
    assert back == payload
```

Check the `GeocodeResult` field names against `redat/core/geocoding.py` (Task 3) before writing — it is a dataclass with `formatted_address, latitude, longitude, precision`; adjust the test constructor if the copy from hunter names them differently.

- [ ] **Step 3: `redat/core/analyze.py`**

```python
"""Orchestration shared by the API and the website: geocode, all sections, payload shapes."""
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from fastapi import HTTPException

from redat.core.envelope import run_section
from redat.core.geocoding import GeocodeResult, GeocoderUnavailable, geocode_with_precision
from redat.core.sections import SECTIONS, Ctx
from redat.settings import Destination
from redat.store.cache import SectionCache

logger = logging.getLogger(__name__)

POOL_SIZE = 6            # the concurrency the browser produced against hunter
MAX_DESTINATIONS = 10


def parse_destinations(raw: Optional[str]) -> tuple[Destination, ...]:
    """`destinations` query param: JSON list of {name, lat, lon, group?}. ValueError on anything off."""
    if not raw:
        return ()
    try:
        items = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"destinations: kein gültiges JSON ({exc.msg})")
    if not isinstance(items, list):
        raise ValueError("destinations: Liste erwartet")
    if len(items) > MAX_DESTINATIONS:
        raise ValueError(f"destinations: höchstens {MAX_DESTINATIONS} Einträge")
    out = []
    for i, it in enumerate(items):
        if not isinstance(it, dict) or not str(it.get("name") or "").strip():
            raise ValueError(f"destinations[{i}]: name fehlt")
        try:
            lat, lon = float(it["lat"]), float(it["lon"])
        except (KeyError, TypeError, ValueError):
            raise ValueError(f"destinations[{i}]: lat/lon fehlen oder sind keine Zahlen")
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError(f"destinations[{i}]: lat/lon außerhalb des gültigen Bereichs")
        out.append(Destination(str(it["name"]).strip(), lat, lon, str(it.get("group") or "custom"),
                               str(it.get("address") or "")))
    return tuple(out)


def geocode_or_raise(address: str) -> GeocodeResult:
    try:
        result = geocode_with_precision(address)
    except GeocoderUnavailable as exc:
        logger.error("geocoding unavailable: %s", exc)
        raise HTTPException(status_code=502, detail="Geocoding nicht erreichbar (Geoapify und Nominatim)")
    if result is None:
        raise HTTPException(status_code=422, detail="Adresse konnte nicht geocodiert werden")
    return result


def geocode_dict(address: str, g: GeocodeResult) -> dict:
    return {"address": address, "formatted_address": g.formatted_address,
            "latitude": g.latitude, "longitude": g.longitude, "precision": g.precision}


def run_all(*, lat: float, lon: float, precision: Optional[str], plot_size_m2, force: bool,
            destinations: tuple[Destination, ...], cache: SectionCache) -> dict[str, dict]:
    ctx = Ctx(lat=lat, lon=lon, plot_size_m2=plot_size_m2, destinations=tuple(destinations))
    # destinations are request-scoped: commute/oepnv results with custom destinations must not be cached
    custom = bool(destinations)

    def one(key: str) -> dict:
        cacheable = not (custom and key in ("commute", "oepnv"))
        k = cache.key(key, lat, lon, plot_size_m2, force)
        if cacheable:
            hit = cache.get(k)
            if hit is not None:
                return hit
        env = run_section(key, ctx, precision=precision, force=force)
        if cacheable:
            cache.put(k, env)
        return env

    keys = list(SECTIONS)
    with ThreadPoolExecutor(max_workers=POOL_SIZE) as pool:
        results = list(pool.map(one, keys))
    return dict(zip(keys, results))


def payload_to_run(payload: dict) -> dict:
    g = payload.get("geocode") or {}
    return {"address": payload.get("address"), "formatted_address": g.get("formatted_address"),
            "latitude": g.get("latitude"), "longitude": g.get("longitude"), "precision": g.get("precision"),
            "plot_size_m2": payload.get("plot_size_m2"), "living_space_m2": payload.get("living_space_m2"),
            "sections": payload.get("sections") or {}}


def run_to_payload(run: dict) -> dict:
    return {"address": run["address"],
            "geocode": {"formatted_address": run.get("formatted_address"), "latitude": run["latitude"],
                        "longitude": run["longitude"], "precision": run.get("precision")},
            "plot_size_m2": run.get("plot_size_m2"), "living_space_m2": run.get("living_space_m2"),
            "sections": run.get("sections") or {}}
```

Note on the cache: `test_run_all_uses_pool_and_cache` passes `destinations=()` so everything is cacheable; custom destinations bypass the cache only for `commute`/`oepnv` (the cache key does not include destinations — this is the deliberate simple rule; document it in a comment as above).

- [ ] **Step 4: `redat/report/service.py`**

```python
"""Payload → PDF bytes. Shared by POST /report, GET /report and /run/{id}/report.pdf."""
from fastapi import Response

from redat.report.builder import build_report_context, slugify
from redat.report.noise_map import render_noise_maps
from redat.report.pdf import html_to_pdf
from redat.report.render import render_report_html
from redat.report.svg import boris_trend_svg


def render_pdf(payload: dict) -> tuple[bytes, dict]:
    """Blocking: context → maps/SVG → HTML → Chromium PDF. Raises ReportPayloadError / RendererUnavailable."""
    ctx = build_report_context(payload)
    body_keys = {s["key"] for s in ctx["body"]}
    if "noise" in body_keys:
        ctx["noise_maps"] = render_noise_maps(ctx["lat"], ctx["lon"])
    if "boris_trend" in body_keys:
        data = next(s["data"] for s in ctx["body"] if s["key"] == "boris_trend")
        ctx["boris_trend_svg"] = boris_trend_svg(data.get("history") or [])
    html = render_report_html(ctx)
    pdf = html_to_pdf(html, header_address=ctx["formatted_address"] or ctx["address"],
                      generated_at=ctx["generated_at"])
    return pdf, ctx


def pdf_filename(ctx: dict) -> str:
    return f"Standortanalyse_{slugify(ctx['formatted_address'] or ctx['address'])}_{ctx['generated_date']}.pdf"


def pdf_response(pdf: bytes, ctx: dict) -> Response:
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{pdf_filename(ctx)}"'})
```

- [ ] **Step 5: `tests/test_api_v1.py`**

```python
import json
import pytest
from fastapi.testclient import TestClient

import redat.api.v1 as V
import redat.core.analyze as A
from redat.core.geocoding import GeocodeResult
from redat.report.builder import ReportPayloadError
from redat.report.pdf import RendererUnavailable

OK = GeocodeResult(formatted_address="Brückstraße 1, 45239 Essen", latitude=51.3878, longitude=7.0011, precision="house")


def _env(key, status="ok"):
    return {"key": key, "tier": "area", "status": status, "data": {} if status == "ok" else None,
            "message": None, "source": "x", "took_ms": 1}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(A, "geocode_with_precision", lambda a: OK if a != "nirgendwo" else None)
    monkeypatch.setattr(A, "run_section", lambda key, ctx, precision=None, force=False: _env(key))
    monkeypatch.setattr(V, "render_pdf", lambda payload: (b"%PDF-1.4 fake", {
        "formatted_address": payload["geocode"]["formatted_address"], "address": payload["address"],
        "generated_date": "2026-09-05"}))
    from redat.app import create_app
    with TestClient(create_app()) as c:
        yield c


def _payload():
    return {"address": "Brückstraße 1, Essen", "geocode": A.geocode_dict("Brückstraße 1, Essen", OK),
            "plot_size_m2": 400, "living_space_m2": None, "sections": {"noise": _env("noise")}}


def test_sections_manifest(client):
    r = client.get("/api/v1/sections"); assert r.status_code == 200
    first = r.json()[0]
    assert set(first) == {"key", "title", "icon", "tier", "timeout_s", "source"}
    assert [s["key"] for s in r.json()] == list(A.SECTIONS)


def test_geocode(client):
    r = client.get("/api/v1/geocode", params={"address": "Brückstraße 1, Essen"})
    assert r.status_code == 200 and r.json()["precision"] == "house" and r.json()["address"] == "Brückstraße 1, Essen"
    assert client.get("/api/v1/geocode", params={"address": "nirgendwo"}).status_code == 422


def test_autocomplete(client, monkeypatch):
    monkeypatch.setattr(V, "autocomplete_address", lambda text, limit=8: [{"formatted": text, "lat": 1, "lon": 2}])
    r = client.get("/api/v1/autocomplete", params={"text": "Brück", "limit": 3})
    assert r.status_code == 200 and r.json() == {"results": [{"formatted": "Brück", "lat": 1, "lon": 2}]}


def test_section_route(client):
    r = client.get("/api/v1/section/noise", params={"lat": 51.38, "lon": 7.0})
    assert r.status_code == 200 and r.json()["key"] == "noise"
    assert client.get("/api/v1/section/nope", params={"lat": 1, "lon": 2}).status_code == 404
    r = client.get("/api/v1/section/commute", params={"lat": 1, "lon": 2, "destinations": "nope"})
    assert r.status_code == 422


def test_analyze_and_save(client):
    r = client.get("/api/v1/analyze", params={"address": "Brückstraße 1, Essen", "plot_size_m2": 400})
    assert r.status_code == 200
    body = r.json()
    assert set(body["sections"]) == set(A.SECTIONS) and body["geocode"]["latitude"] == 51.3878
    assert "run_id" not in body
    r = client.get("/api/v1/analyze", params={"address": "Brückstraße 1, Essen", "save": 1})
    body = r.json()
    assert len(body["run_id"]) == 10 and body["permalink"].endswith(f"/a/{body['run_id']}")
    got = client.get(f"/api/v1/run/{body['run_id']}").json()
    assert got["address"] == "Brückstraße 1, Essen" and got["created_at"] and set(got["sections"]) == set(A.SECTIONS)
    assert got["plot_size_m2"] is None and got["geocode"]["precision"] == "house"


def test_analyze_unresolvable(client):
    assert client.get("/api/v1/analyze", params={"address": "nirgendwo"}).status_code == 422


def test_post_runs_and_get(client):
    r = client.post("/api/v1/runs", json=_payload())
    assert r.status_code == 200 and r.json()["permalink"].endswith("/a/" + r.json()["run_id"])
    assert client.get("/api/v1/run/zzzzzzzzzz").status_code == 404
    bad = _payload(); bad["sections"] = {"unknown_key": _env("unknown_key")}
    assert client.post("/api/v1/runs", json=bad).status_code == 422
    assert client.post("/api/v1/runs", json=[1, 2]).status_code == 422


def test_report_post(client):
    r = client.post("/api/v1/report", json=_payload())
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert r.headers["content-disposition"] == 'attachment; filename="Standortanalyse_Brueckstrasse-1-45239-Essen_2026-09-05.pdf"'
    assert "x-dossier-document-id" not in {k.lower() for k in r.headers}


def test_report_post_errors(client, monkeypatch):
    assert client.post("/api/v1/report", json={"address": "x"}).status_code == 422

    def boom(payload): raise RendererUnavailable("no chromium")
    monkeypatch.setattr(V, "render_pdf", boom)
    r = client.post("/api/v1/report", json=_payload())
    assert r.status_code == 503 and r.json()["detail"] == "PDF-Renderer nicht verfügbar"


def test_report_get_forces_and_renders(client, monkeypatch):
    seen = {}
    monkeypatch.setattr(A, "run_section", lambda key, ctx, precision=None, force=False: seen.setdefault("force", force) or _env(key))
    r = client.get("/api/v1/report", params={"address": "Brückstraße 1, Essen"})
    assert r.status_code == 200 and r.content.startswith(b"%PDF") and seen["force"] is True


def test_run_report_pdf(client):
    rid = client.post("/api/v1/runs", json=_payload()).json()["run_id"]
    r = client.get(f"/api/v1/run/{rid}/report.pdf")
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert client.get("/api/v1/run/zzzzzzzzzz/report.pdf").status_code == 404
```

Check `slugify("Brückstraße 1, 45239 Essen")` in `redat/report/builder.py` before trusting the exact filename assertion; hunter's transliterates `ü→ue`, `ß→ss`, non-alnum → `-` — if the produced slug differs, fix the assertion to what `slugify` actually returns (do not change `slugify`).

- [ ] **Step 6: `redat/api/v1.py`**

```python
"""REDAT public API (spec §5). Everything under /api/v1, all behind the optional API key."""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool

from redat.api.auth import require_api_key
from redat.core import analyze as A
from redat.core.envelope import run_section
from redat.core.sections import Ctx, manifest
from redat.report.builder import ReportPayloadError, build_report_context
from redat.report.pdf import RendererUnavailable
from redat.report.service import pdf_response, render_pdf
from redat.settings import get_settings
from redat.sources.geoapify import autocomplete_address

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_api_key)])


def _destinations(raw: Optional[str]):
    try:
        return A.parse_destinations(raw)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


def _permalink(run_id: str) -> str:
    return f"{get_settings().public_url}/a/{run_id}"


@router.get("/sections")
def api_sections():
    return manifest()


@router.get("/geocode")
def api_geocode(address: str):
    return A.geocode_dict(address, A.geocode_or_raise(address))


@router.get("/autocomplete")
def api_autocomplete(text: str, limit: int = 8):
    return {"results": autocomplete_address(text, limit=limit)}


@router.get("/section/{key}")
def api_section(key: str, lat: float, lon: float, precision: Optional[str] = None,
                plot_size_m2: Optional[float] = None, force: bool = False, destinations: Optional[str] = None):
    ctx = Ctx(lat=lat, lon=lon, plot_size_m2=plot_size_m2, destinations=_destinations(destinations))
    try:
        return run_section(key, ctx, precision=precision, force=force)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unbekannte Sektion: {key}")


def _analyze_sync(request: Request, address: str, plot_size_m2, force: bool, destinations) -> dict:
    g = A.geocode_or_raise(address)
    sections = A.run_all(lat=g.latitude, lon=g.longitude, precision=g.precision, plot_size_m2=plot_size_m2,
                         force=force, destinations=destinations, cache=request.app.state.cache)
    return {"geocode": A.geocode_dict(address, g), "sections": sections}


@router.get("/analyze")
async def api_analyze(request: Request, address: str, plot_size_m2: Optional[float] = None,
                      living_space_m2: Optional[float] = None, force: bool = False,
                      destinations: Optional[str] = None, save: bool = False):
    dests = _destinations(destinations)
    out = await run_in_threadpool(_analyze_sync, request, address, plot_size_m2, force, dests)
    if save:
        run = A.payload_to_run({"address": address, "geocode": out["geocode"], "plot_size_m2": plot_size_m2,
                                "living_space_m2": living_space_m2, "sections": out["sections"]})
        run_id = request.app.state.runs.save(run)
        out = {"run_id": run_id, "permalink": _permalink(run_id), **out}
    return out


@router.post("/runs")
async def api_post_run(request: Request):
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="Ungültiger Payload")
    try:
        build_report_context(payload)  # same validation as the report
    except ReportPayloadError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    run_id = request.app.state.runs.save(A.payload_to_run(payload))
    return {"run_id": run_id, "permalink": _permalink(run_id)}


def _get_run_or_404(request: Request, run_id: str) -> dict:
    run = request.app.state.runs.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Unbekannte Analyse: {run_id}")
    return run


@router.get("/run/{run_id}")
def api_get_run(request: Request, run_id: str):
    run = _get_run_or_404(request, run_id)
    p = A.run_to_payload(run)
    return {"run_id": run_id, "permalink": _permalink(run_id), "created_at": run["created_at"],
            "address": run["address"], "plot_size_m2": run.get("plot_size_m2"),
            "living_space_m2": run.get("living_space_m2"),
            "geocode": {"address": run["address"], **p["geocode"]}, "sections": p["sections"]}


async def _pdf(payload: dict):
    try:
        build_report_context(payload)  # validate before touching Chromium
    except ReportPayloadError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    try:
        pdf, ctx = await run_in_threadpool(render_pdf, payload)
    except RendererUnavailable as exc:
        logger.error("PDF renderer unavailable: %s", exc)
        raise HTTPException(status_code=503, detail="PDF-Renderer nicht verfügbar")
    return pdf_response(pdf, ctx)


@router.post("/report")
async def api_report_post(request: Request):
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="Ungültiger Bericht-Payload")
    return await _pdf(payload)


@router.get("/report")
async def api_report_get(request: Request, address: str, plot_size_m2: Optional[float] = None,
                         living_space_m2: Optional[float] = None, force: bool = True,
                         destinations: Optional[str] = None):
    dests = _destinations(destinations)
    out = await run_in_threadpool(_analyze_sync, request, address, plot_size_m2, force, dests)
    return await _pdf({"address": address, "geocode": out["geocode"], "plot_size_m2": plot_size_m2,
                       "living_space_m2": living_space_m2, "sections": out["sections"]})


@router.get("/run/{run_id}/report.pdf")
async def api_run_report(request: Request, run_id: str):
    run = _get_run_or_404(request, run_id)
    return await _pdf(A.run_to_payload(run))
```

`redat/app.py` lifespan: after `app.state.runs = RunStore(settings.db_path); app.state.runs.init()` add `app.state.cache = SectionCache(settings.cache_ttl_s)` (`from redat.store.cache import SectionCache`).

`build_report_context` must accept a `geocode` block that includes an extra `address` key (the `/run/{id}` response embeds one) — check `_validate`; it reads named keys, so extras are fine.

- [ ] **Step 7: Run, commit**

`pytest tests -q` → green (the three new files add ≈ 20 tests).
```bash
git add -A && git commit -q -F - <<'EOF'
feat(api): /api/v1 — sections, geocode, autocomplete, section, analyze(+save), runs, report (POST/GET/run), optional X-Api-Key

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_015HbDiczEViCdm3XmxC2ReC
EOF
```

### Task 9: Website — sources_meta, pages, templates, JS store, Tailwind build

**Files:**
- Create: `redat/core/sources_meta.py`; `redat/web/pages.py` (replace stub); `redat/templates/{base,index,quellen,404}.html` (`index.html` serves both `/` and `/a/{id}` — the stored run arrives via `page_config.run`); `redat/static/{redat.js,analysis.js,map-utils.js,charts.js,site.css}`; `tailwind.config.js`, `tailwind.input.css`, `package.json`; built `redat/static/redat.css`
- Test: `tests/test_sources_meta.py`, `tests/test_web_pages.py`

**Interfaces:**
- Consumes: `redat.core.sections.manifest()` (list of `{key,title,icon,tier,timeout_s,source}`), `redat.templating.templates`, `request.app.state.runs.get(run_id)`, `redat.core.analyze.run_to_payload`, `redat.__version__`.
- Produces: `sources_meta.SOURCES: tuple[SourceMeta, ...]` with `SourceMeta(section_keys: tuple[str, ...], name, publisher, licence, endpoint, tier, cadence)`; `sources_meta.for_section(key) -> SourceMeta | None`; pages `GET /`, `GET /a/{run_id}`, `GET /quellen`.
- Spec §6 rule: **the card partials under `redat/templates/analysis/` stay unchanged**, so the Alpine store keeps the name `app` (`$store.app.getAirQualityColor` etc. are referenced 16× in the partials).

- [ ] **Step 1: `tests/test_sources_meta.py` + `redat/core/sources_meta.py`**

```python
from redat.core.sections import SECTIONS
from redat.core.sources_meta import SOURCES, for_section


def test_every_section_has_exactly_one_source_row():
    seen = [k for s in SOURCES for k in s.section_keys]
    assert sorted(seen) == sorted(SECTIONS)


def test_rows_are_complete():
    for s in SOURCES:
        assert s.name and s.publisher and s.licence and s.endpoint and s.cadence
        assert s.tier in ("parcel", "area")


def test_for_section():
    assert for_section("noise").publisher.startswith("Land NRW")
    assert for_section("nope") is None
```

```python
"""Single source of truth for /quellen and the report footer (spec §6)."""
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class SourceMeta:
    section_keys: tuple[str, ...]
    name: str
    publisher: str
    licence: str
    endpoint: str
    tier: str          # "parcel" | "area"
    cadence: str       # how often the upstream changes / when we refresh


SOURCES: tuple[SourceMeta, ...] = (
    SourceMeta(("boris", "boris_trend"), "BORIS NRW Bodenrichtwerte", "Gutachterausschüsse NRW / Geobasis NRW", "dl-de/zero-2-0",
               "lokale Shapefiles unter source/boris (Stichtage 2011–2025)", "parcel", "jährlich (1.1.), Datei-Import"),
    SourceMeta(("flood",), "Hochwassergefahrenkarten NRW (HWRM-RL)", "Land NRW, LANUV", "dl-de/by-2-0",
               "lokale GeoPackages unter source/flood/hwrm", "parcel", "6-Jahres-Zyklus, Datei-Import"),
    SourceMeta(("starkregen",), "Hinweiskarte Starkregengefahren", "BKG", "dl-de/by-2-0",
               "https://sgx.geodatenzentrum.de/wms_starkregen", "parcel", "live WMS"),
    SourceMeta(("noise",), "Umgebungslärmkartierung 2022", "Land NRW, LANUV", "dl-de/zero-2-0",
               "https://www.wms.nrw.de/umwelt/laerm", "area", "live WMS, 5-Jahres-Runde"),
    SourceMeta(("bergbau",), "NRW von unten (Bürgerversion)", "Geologischer Dienst NRW / BezReg Arnsberg", "dl-de/by-2-0",
               "ArcGIS REST, Layer 22 (500 m-Planquadrat)", "area", "live"),
    SourceMeta(("gfnp",), "Gemeinsamer Flächennutzungsplan", "Stadt Essen (geo.essen.de)", "dl-de/by-2-0",
               "ArcGIS REST identify", "parcel", "live"),
    SourceMeta(("schutzgebiete",), "LINFOS Schutzgebiete + Wasserschutzgebiete", "LANUV NRW", "dl-de/by-2-0",
               "WFS 2.0 (EPSG:25832) + WSG WMS GetFeatureInfo", "area", "live"),
    SourceMeta(("planning_essen",), "Bauleitplanung Essen", "Stadt Essen (geo.essen.de)", "dl-de/by-2-0",
               "ArcGIS REST identify", "parcel", "live"),
    SourceMeta(("planning_bochum",), "Bauleitplanung Bochum", "RVR INSPIRE", "dl-de/by-2-0",
               "WMS GetFeatureInfo", "parcel", "live"),
    SourceMeta(("denkmal",), "Denkmalliste (INSPIRE Schutzgebiete)", "RVR / Städte Essen und Bochum", "dl-de/by-2-0",
               "https://geodaten.metropoleruhr.de/inspire/schutzgebiete/metropoleruhr (WFS 2.0)", "parcel", "live"),
    SourceMeta(("amenities",), "Geoapify Places", "Geoapify (OpenStreetMap-Daten)", "ODbL / Geoapify-Nutzungsbedingungen",
               "https://api.geoapify.com/v2/places", "area", "live"),
    SourceMeta(("oepnv",), "VRR EFA-Fahrplanauskunft", "Verkehrsverbund Rhein-Ruhr", "Nutzung gemäß VRR-Bedingungen",
               "https://efa.vrr.de/standard/ (rapidJSON)", "area", "live, Fahrplan-Stichtag nächster Dienstag 08:00"),
    SourceMeta(("zensus",), "Zensus 2022 — 100 m-Gitterdaten", "Statistische Ämter des Bundes und der Länder", "dl-de/by-2-0",
               "lokal: redat/data/zensus_2022_grid.json.gz", "area", "Zensus 2022 (einmalig), Datei-Import"),
    SourceMeta(("energie",), "Solarkataster · Geothermie · Kommunale Wärmeplanung", "LANUK NRW · GD NRW · Städte Essen/Bochum", "dl-de/by-2-0",
               "ArcGIS REST + GT WMS GetFeatureInfo", "parcel", "live"),
    SourceMeta(("breitband",), "Breitbandatlas", "Bundesnetzagentur", "© BNetzA, dl-de/by-2-0",
               "WMS, 100 m-Raster (EPSG:3035)", "area", "halbjährlich — Datenstand 12.2025"),
    SourceMeta(("infrastruktur",), "OpenStreetMap (Overpass) + EEA Industrial Emissions Portal", "OSM-Mitwirkende · EEA", "ODbL · EEA Standard Re-use Policy",
               "Overpass API + discodata SQL [IED].[latest].[SiteMap]", "area", "live"),
    SourceMeta(("air_quality",), "Luftqualität (EEA-Raster, UBA/LANUV, Sensor.Community, CAMS)", "EEA · Umweltbundesamt · LANUV · Sensor.Community · Copernicus", "EEA Standard Re-use Policy · dl-de/by-2-0 · ODbL · CC BY 4.0",
               "lokal: redat/data/eea_aq_grid_2023.json + live APIs", "area", "EEA jährlich (2023) · Messwerte stündlich"),
    SourceMeta(("btw",), "Bundestagswahl 2025 (kerg2, Wahlkreisgeometrien)", "Die Bundeswahlleiterin", "dl-de/by-2-0",
               "lokal: source/elections/btw25", "area", "je Wahl, Datei-Import"),
    SourceMeta(("commute",), "Geoapify Routing", "Geoapify (OpenStreetMap-Daten)", "ODbL / Geoapify-Nutzungsbedingungen",
               "https://api.geoapify.com/v1/routing", "area", "live"),
)


def for_section(key: str) -> Optional[SourceMeta]:
    return next((s for s in SOURCES if key in s.section_keys), None)
```

If `SECTIONS` in `redat/core/sections.py` contains a key not listed here (compare against the list in that file), add a row — the first test is the guard.

- [ ] **Step 2: Static assets**

```bash
H=/srv/house-hunter; cd /srv/nrw-redat
cp $H/frontend/static/js/map-utils.js $H/frontend/static/js/charts.js redat/static/
cp $H/frontend/static/js/analysis.js redat/static/analysis.js
rm redat/static/.gitkeep
```

`redat/static/site.css` — copy these rules from hunter's `frontend/static/css/app.css`: the `[x-cloak] { display: none !important; }` rule (line 7), the `.progress-bar` / `.progress-bar-fill` block (lines 564–575), and from the `@media print` block (line 637 ff.) only `nav, .no-print { display: none !important; }`, `body { background: white !important; }`, `.print-break-avoid {…}` and `#result-map { height: 380px !important; }`. Prepend `#result-map { height: 360px; } @media (min-width: 768px) { #result-map { height: 460px; } }` (moved out of hunter's `analyze.html` `<style>`).

`redat/static/redat.js` — the REDAT store + autocomplete widget:
```js
// Alpine store `app` — the name the card partials (templates/analysis/_*.html) reference.
document.addEventListener('alpine:init', () => {
    Alpine.store('app', {
        formatNumber(num) {
            if (!num && num !== 0) return '—';
            return new Intl.NumberFormat('de-DE').format(Math.round(num));
        },
        formatPrice(price) {
            if (!price && price !== 0) return '? €';
            return new Intl.NumberFormat('de-DE', { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 }).format(price);
        },
        formatDistance(meters) {
            if (!meters) return '—';
            if (meters < 1000) return `${Math.round(meters)}m`;
            return `${(meters / 1000).toFixed(1)}km`;
        },
        getFloodRiskClass(level) {
            switch (level) {
                case 'high': return 'bg-red-100 text-red-700';
                case 'medium': return 'bg-yellow-100 text-yellow-700';
                default: return 'bg-green-100 text-green-700';
            }
        },
        getAirQualityColor(ratingColor) {
            const colors = {
                green: 'bg-green-100 text-green-800', yellow: 'bg-yellow-100 text-yellow-800',
                orange: 'bg-orange-100 text-orange-800', red: 'bg-red-100 text-red-800', gray: 'bg-gray-100 text-gray-800',
            };
            return colors[ratingColor] || colors.gray;
        },
        wmsLayerConfigs: typeof MapUtils !== 'undefined' ? MapUtils.getWMSLayerConfigs() : {},
        toggleWMSLayer(map, wmsLayers, key, enabled) {
            if (typeof MapUtils !== 'undefined') MapUtils.toggleWMSLayer(map, wmsLayers, key, enabled);
        },
    });
});

function debounce(func, wait) {
    let timeout;
    return function (...args) {
        clearTimeout(timeout);
        timeout = setTimeout(() => func(...args), wait);
    };
}

// <PASTE hunter's frontend/static/js/site.js lines 1–112 here: the `attachAutocomplete(input)` function
//  (everything from its definition through the closing `document.addEventListener('click', …)` line),
//  with ONE change: the fetch URL becomes `/api/v1/autocomplete?` + new URLSearchParams({text:q, limit:'8'}) >
// Copy it verbatim from the file, not from memory; keep `items = (data.results || []).slice(0, 8)`.

window.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('input[data-geoapify-autocomplete="1"]').forEach(attachAutocomplete);
});
```
(The `<PASTE …>` line is an instruction to the implementer, not a placeholder that may remain: after the paste the file contains the full widget. Grep `attachAutocomplete` afterwards — two hits: definition + the `forEach`.)

`redat/static/analysis.js` edits (compared with hunter's file):
1. Header comment: `/api/analysis/section/{key}` → `/api/v1/section/{key}`; add "config.run (a stored run) renders without fetching".
2. State: delete `listingId: config.listing_id ?? null,`; add `runIdStored: config.run?.run_id ?? null,` and `createdAt: config.run?.created_at ?? null,`.
3. `init()`:
   ```js
   init() {
       this.initMap();
       if (config.run) { this.showStored(config.run); return; }
       if (config.auto_run && this.address) this.run();
   },
   showStored(run) {
       this.geocode = run.geocode;
       this.sections = { ...emptyState(), ...run.sections };
       this.placePin(run.geocode.latitude, run.geocode.longitude, run.geocode.formatted_address);
       this.$nextTick(() => manifest.forEach(s => { if (this.sections[s.key]?.status === 'ok') this.renderChart(s.key); }));
   },
   ```
4. `run()`: `'/api/analysis/geocode?address='` → `'/api/v1/geocode?address='`; after `await Promise.allSettled(...)` add `await this.saveRun();`. On a stored-run page (`this.runIdStored`) a re-run must land on a fresh id: `run()` begins with `if (this.runIdStored) { window.location = '/?' + new URLSearchParams({ address: this.address, ...(this.plotSize ? { plot_size_m2: this.plotSize } : {}), ...(this.livingSpace ? { living_space_m2: this.livingSpace } : {}), auto: '1' }); return; }`.
5. `load()`: `'/api/analysis/section/'` → `'/api/v1/section/'`.
6. New method (after `loadGated`):
   ```js
   // Persist the envelopes on screen; the URL becomes the permalink.
   async saveRun() {
       if (!this.hasResults) return;
       try {
           const resp = await fetch('/api/v1/runs', {
               method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(this.payload()),
           });
           if (!resp.ok) return;
           const { run_id } = await resp.json();
           this.runIdStored = run_id;
           this.createdAt = new Date().toISOString();
           history.replaceState(null, '', '/a/' + run_id);
       } catch (e) { /* the analysis is still on screen; only the permalink is missing */ }
   },
   payload() {
       const sections = {};
       manifest.forEach(s => {
           const env = this.sections[s.key];
           if (env && env.status !== 'loading') sections[s.key] = env;
       });
       return { address: this.address, geocode: this.geocode, plot_size_m2: this.plotSize || null,
                living_space_m2: this.livingSpace || null, sections };
   },
   ```
7. `exportPdf()`: replace the `const sections = {}; … const body = {…};` block with `const body = this.payload();`; URL `'/api/analysis/report'` → `'/api/v1/report'`; delete the `X-Dossier-Document-Id` / `X-Report-Warning` `if/else if` block; on a stored-run page use the stored PDF instead: at the top, `if (this.runIdStored && config.run) { window.location = '/api/v1/run/' + this.runIdStored + '/report.pdf'; return; }`.
8. Delete nothing else; `precisionBadge`, `tierBadge`, `renderChart` stay.

- [ ] **Step 3: Templates**

`redat/templates/base.html`:
```html
<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}NRW-REDAT{% endblock %}</title>
    <meta name="theme-color" content="#0f766e">
    <script defer src="https://cdn.jsdelivr.net/npm/alpinejs@3.14.9/dist/cdn.min.js"></script>
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <link rel="stylesheet" href="/static/site.css">
    <link rel="stylesheet" href="/static/redat.css">
    {% block head %}{% endblock %}
</head>
<body class="bg-slate-100 min-h-screen text-gray-900">
    <header class="bg-white border-b border-gray-200 no-print">
        <div class="max-w-6xl mx-auto px-4 py-3 flex items-center justify-between gap-4">
            <a href="/" class="flex items-center gap-2 font-bold text-teal-700">
                <span class="text-xl">🗺️</span> NRW-REDAT
                <span class="hidden sm:inline text-xs font-normal text-gray-500">Real Estate Data Aggregation Tool</span>
            </a>
            <nav class="flex items-center gap-4 text-sm">
                <a href="/" class="hover:text-teal-700 {{ 'font-semibold text-teal-700' if active == 'analyse' else 'text-gray-600' }}">Analyse</a>
                <a href="/quellen" class="hover:text-teal-700 {{ 'font-semibold text-teal-700' if active == 'quellen' else 'text-gray-600' }}">Quellen</a>
                <a href="/docs" class="text-gray-600 hover:text-teal-700">API</a>
            </nav>
        </div>
    </header>
    <main class="max-w-6xl mx-auto px-4 py-6">
        {% block content %}{% endblock %}
    </main>
    <footer class="max-w-6xl mx-auto px-4 py-6 text-xs text-gray-400 no-print">
        NRW-REDAT {{ version }} · Essen &amp; Bochum · Daten: siehe <a href="/quellen" class="underline">Quellen</a>
    </footer>
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"></script>
    <script src="/static/map-utils.js"></script>
    <script src="/static/charts.js"></script>
    <script src="/static/redat.js"></script>
    {% block scripts %}{% endblock %}
</body>
</html>
```
Pin the CDN versions exactly as written (Alpine 3.14.9, Chart.js 4.4.7, Leaflet 1.9.4) — verify each URL returns 200 with `curl -sI` before committing; if one 404s, pick the nearest existing patch version and note it in the commit message.

`redat/templates/index.html` — start from hunter's `frontend/templates/analyze.html` and make these changes:
- `{% block title %}Standort-Analyse — NRW-REDAT{% endblock %}`; delete the `{% block head %}` (Leaflet CSS + `#result-map` style now live in base/site.css) and the `{% block scripts %}` except `<script src="/static/analysis.js"></script>`.
- Input row: after the address input add two optional number inputs:
  ```html
  <input type="number" min="0" step="1" x-model.number="plotSize" placeholder="Grundstück m²"
         class="w-36 rounded-md border-gray-300 shadow-sm focus:border-teal-500 focus:ring-teal-500">
  <input type="number" min="0" step="1" x-model.number="livingSpace" placeholder="Wohnfläche m²"
         class="w-36 rounded-md border-gray-300 shadow-sm focus:border-teal-500 focus:ring-teal-500">
  ```
  Button colour `bg-purple-600/700` → `bg-teal-600/700`.
- Stored-run banner (directly under the input card, before the map):
  ```html
  <div x-show="runIdStored && createdAt" x-cloak class="p-3 bg-teal-50 border border-teal-200 rounded-lg text-sm text-teal-900 flex flex-wrap items-center justify-between gap-2">
      <span>🔗 Analyse vom <span x-text="new Date(createdAt).toLocaleString('de-DE', {dateStyle: 'medium', timeStyle: 'short'})"></span> — Link teilbar: <code x-text="location.origin + '/a/' + runIdStored"></code></span>
      <button @click="run()" class="px-3 py-1 border border-teal-400 rounded-md hover:bg-teal-100">↻ neu laden</button>
  </div>
  ```
- Delete the whole `<!-- Back to listing -->` block.
- Everything else (map card, geocode card with "Alle gesperrten laden" + "📄 PDF-Bericht", the `{% for s in sections %}` card loop with `{% include "analysis/_" ~ partial ~ ".html" %}`) stays byte-identical.

`redat/templates/quellen.html`:
```html
{% extends "base.html" %}
{% block title %}Datenquellen — NRW-REDAT{% endblock %}
{% block content %}
<div class="bg-white rounded-lg shadow p-6">
    <h1 class="text-xl font-bold mb-2">📚 Datenquellen &amp; Lizenzen</h1>
    <p class="text-sm text-gray-600 mb-4">Jede Karte der Analyse nennt ihre Quelle; hier stehen Herausgeber, Lizenz, Endpunkt und Aktualisierung gesammelt.
       <strong>Parzelle</strong> = nur bei hausnummerngenauer Adresse aussagekräftig, <strong>Umgebung</strong> = Umkreis-/Rasterdaten.</p>
    <div class="overflow-x-auto">
    <table class="w-full text-sm">
        <thead><tr class="text-left text-gray-500 border-b">
            <th class="py-2 pr-3">Karte(n)</th><th class="py-2 pr-3">Quelle</th><th class="py-2 pr-3">Herausgeber</th>
            <th class="py-2 pr-3">Lizenz</th><th class="py-2 pr-3">Endpunkt</th><th class="py-2 pr-3">Ebene</th><th class="py-2">Aktualisierung</th>
        </tr></thead>
        <tbody>
        {% for s in sources %}
        <tr class="border-b border-gray-100 align-top">
            <td class="py-2 pr-3">{% for k in s.section_keys %}<div>{{ titles[k] }}</div>{% endfor %}</td>
            <td class="py-2 pr-3 font-medium">{{ s.name }}</td>
            <td class="py-2 pr-3">{{ s.publisher }}</td>
            <td class="py-2 pr-3">{{ s.licence }}</td>
            <td class="py-2 pr-3 text-xs text-gray-600 break-all">{{ s.endpoint }}</td>
            <td class="py-2 pr-3">{{ 'Parzelle' if s.tier == 'parcel' else 'Umgebung' }}</td>
            <td class="py-2">{{ s.cadence }}</td>
        </tr>
        {% endfor %}
        </tbody>
    </table>
    </div>
</div>
{% endblock %}
```

`redat/templates/404.html`:
```html
{% extends "base.html" %}
{% block title %}Nicht gefunden — NRW-REDAT{% endblock %}
{% block content %}
<div class="bg-white rounded-lg shadow p-6 text-center">
    <h1 class="text-xl font-bold mb-2">Analyse nicht gefunden</h1>
    <p class="text-sm text-gray-600">{{ message }}</p>
    <a href="/" class="inline-block mt-4 px-4 py-2 bg-teal-600 text-white rounded-md">Neue Analyse</a>
</div>
{% endblock %}
```

- [ ] **Step 4: `tests/test_web_pages.py`**

```python
import json
import re
import pytest
from fastapi.testclient import TestClient

import redat.core.analyze as A
from redat.core.geocoding import GeocodeResult
from redat.settings import reset_settings

OK = GeocodeResult(formatted_address="Brückstraße 1, 45239 Essen", latitude=51.3878, longitude=7.0011, precision="building")


@pytest.fixture
def client():
    from redat.app import create_app
    with TestClient(create_app()) as c:
        yield c


def _config(html):
    m = re.search(r'<script type="application/json" id="analysis-config">(.*?)</script>', html, re.S)
    return json.loads(m.group(1))


def test_index_renders_manifest(client):
    r = client.get("/")
    assert r.status_code == 200 and "Standort-Analyse" in r.text
    cfg = _config(r.text)
    assert cfg["run"] is None and cfg["auto_run"] is False and [s["key"] for s in cfg["sections"]] == list(A.SECTIONS)
    assert 'id="card-noise"' in r.text and "Quellen" in r.text


def test_index_prefill_and_auto(client):
    r = client.get("/", params={"address": "Brückstraße 1, Essen", "plot_size_m2": 400, "auto": 1})
    cfg = _config(r.text)
    assert cfg["address"] == "Brückstraße 1, Essen" and cfg["plot_size_m2"] == 400.0 and cfg["auto_run"] is True
    assert _config(client.get("/", params={"auto": 1}).text)["auto_run"] is False  # no address → nothing to run


def test_stored_run_page(client):
    payload = {"address": "Brückstraße 1, Essen", "geocode": A.geocode_dict("Brückstraße 1, Essen", OK),
               "plot_size_m2": None, "living_space_m2": None,
               "sections": {"noise": {"key": "noise", "status": "ok", "data": {"below_threshold": True}}}}
    rid = client.post("/api/v1/runs", json=payload).json()["run_id"]
    r = client.get(f"/a/{rid}")
    assert r.status_code == 200
    cfg = _config(r.text)
    assert cfg["run"]["run_id"] == rid and cfg["run"]["sections"]["noise"]["status"] == "ok"
    assert cfg["run"]["geocode"]["latitude"] == 51.3878 and cfg["address"] == "Brückstraße 1, Essen"


def test_stored_run_404(client):
    r = client.get("/a/zzzzzzzzzz")
    assert r.status_code == 404 and "Analyse nicht gefunden" in r.text


def test_quellen(client):
    r = client.get("/quellen")
    assert r.status_code == 200 and "BORIS NRW" in r.text and "Bundesnetzagentur" in r.text and "Lärm" in r.text


def test_pages_never_need_api_key(monkeypatch):
    monkeypatch.setenv("REDAT_API_KEY", "k"); reset_settings()
    from redat.app import create_app
    with TestClient(create_app()) as c:
        assert c.get("/").status_code == 200 and c.get("/quellen").status_code == 200
```

- [ ] **Step 5: `redat/web/pages.py`**

```python
"""Server-rendered pages: analyzer, stored-run permalink, sources. Never behind the API key."""
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from redat import __version__
from redat.core import analyze as A
from redat.core.sections import manifest
from redat.core.sources_meta import SOURCES
from redat.templating import templates

router = APIRouter(include_in_schema=False)


def _render(request: Request, name: str, ctx: dict, status_code: int = 200) -> HTMLResponse:
    return templates.TemplateResponse(request, name, {"request": request, "version": __version__, **ctx},
                                      status_code=status_code)


def _page_config(address: str = "", plot_size_m2=None, living_space_m2=None, auto_run: bool = False, run=None) -> dict:
    return {"address": address, "plot_size_m2": plot_size_m2, "living_space_m2": living_space_m2,
            "auto_run": auto_run, "sections": manifest(), "run": run}


@router.get("/", response_class=HTMLResponse)
def index(request: Request, address: str = "", plot_size_m2: Optional[float] = None,
          living_space_m2: Optional[float] = None, auto: bool = False):
    cfg = _page_config(address, plot_size_m2, living_space_m2, auto_run=bool(auto and address))
    return _render(request, "index.html", {"active": "analyse", "page_config": cfg, "sections": cfg["sections"]})


@router.get("/a/{run_id}", response_class=HTMLResponse)
def stored_run(request: Request, run_id: str):
    run = request.app.state.runs.get(run_id)
    if run is None:
        return _render(request, "404.html", {"message": f"Es gibt keine gespeicherte Analyse mit der Kennung {run_id}."},
                       status_code=404)
    p = A.run_to_payload(run)
    stored = {"run_id": run_id, "created_at": run["created_at"],
              "geocode": {"address": run["address"], **p["geocode"]}, "sections": p["sections"]}
    cfg = _page_config(run["address"], run.get("plot_size_m2"), run.get("living_space_m2"), run=stored)
    return _render(request, "index.html", {"active": "analyse", "page_config": cfg, "sections": cfg["sections"]})


@router.get("/quellen", response_class=HTMLResponse)
def quellen(request: Request):
    titles = {s["key"]: f'{s["icon"]} {s["title"]}' for s in manifest()}
    return _render(request, "quellen.html", {"active": "quellen", "sources": SOURCES, "titles": titles})
```

- [ ] **Step 6: Tailwind build**

`tailwind.config.js`:
```js
module.exports = {
  content: ["./redat/templates/**/*.html", "./redat/static/*.js"],
  theme: { screens: { xs: "400px", sm: "640px", md: "768px", lg: "1024px", xl: "1280px" } },
  safelist: [
    // dynamic classes produced in redat.js / analysis.js
    "bg-red-100", "text-red-700", "text-red-800", "bg-yellow-100", "text-yellow-700", "text-yellow-800",
    "bg-green-100", "text-green-700", "text-green-800", "bg-orange-100", "text-orange-800",
    "bg-gray-100", "text-gray-700", "text-gray-800", "bg-blue-100", "text-blue-800",
    "bg-amber-50", "text-amber-800", "border-amber-200", "bg-sky-50", "text-sky-800", "border-sky-200",
    "bg-blue-100", "border-blue-500", "bg-white", "border-gray-200",
  ],
};
```
`tailwind.input.css`: `@tailwind base; @tailwind components; @tailwind utilities;` (three lines).
`package.json`: `{"name": "nrw-redat", "private": true, "scripts": {"css": "tailwindcss -c tailwind.config.js -i tailwind.input.css -o redat/static/redat.css --minify"}, "devDependencies": {"tailwindcss": "^3.4.17"}}`.
Build: `npx tailwindcss@3 -c tailwind.config.js -i tailwind.input.css -o redat/static/redat.css --minify` (uses the npx cache hunter already populated; `node_modules/` is git-ignored). Commit the built `redat/static/redat.css`. Sanity: `grep -c "progress-bar" redat/static/site.css` = 2 and `grep -o "bg-teal-600" redat/static/redat.css | head -1` non-empty.

- [ ] **Step 7: Run, commit**

`pytest tests -q` green.
```bash
git add -A && git commit -q -F - <<'EOF'
feat(web): analyzer page, /a/{id} permalinks, /quellen from sources_meta, REDAT Alpine store, Tailwind build

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_015HbDiczEViCdm3XmxC2ReC
EOF
```

### Task 10: Docker, compose, live verification, docs, push

**Files:**
- Create: `Dockerfile`, `docker-compose.yml`, `HANDOVER.md`, `CLAUDE.md`, `docs/2026-09-05-nrw-redat-design.md` (copy of the spec), `docs/2026-09-05-nrw-redat-plan.md` (copy of this plan)
- Modify: `README.md` (Task 1 stub → full), `.dockerignore` (must exclude `data/`), `/srv/README.md` (one service line, in the house-hunter host's README — outside the repo)

**Interfaces:** consumes everything; `GET /healthz` from Task 1 is the container health check.

- [ ] **Step 1: `Dockerfile`**

```dockerfile
# Playwright's image ships Chromium + its system libs; the tag must match the pinned playwright version.
FROM mcr.microsoft.com/playwright/python:v1.58.0-noble AS base
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .

# Deploy gate: the runtime stage copies a marker this stage only produces on a green suite.
FROM base AS test
COPY requirements-dev.txt .
RUN pip install -r requirements-dev.txt && pytest -q && touch /tests-passed

FROM base AS runtime
COPY --from=test /tests-passed /tests-passed
ENV REDAT_DATA_DIR=/data
EXPOSE 8200
HEALTHCHECK --interval=60s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8200/healthz', timeout=4).status == 200 else 1)"
CMD ["uvicorn", "redat.app:app", "--host", "0.0.0.0", "--port", "8200"]
```

`.dockerignore` must contain at least: `data/`, `.git/`, `node_modules/`, `.venv/`, `__pycache__/`, `.pytest_cache/`, `.env`, `.superpowers/`. Check with `cat .dockerignore`; the 6 GB `data/` going into the build context is the failure mode this prevents.

- [ ] **Step 2: `docker-compose.yml`**

```yaml
services:
  redat:
    build:
      context: .
      target: runtime
    image: nrw-redat:latest
    container_name: nrw-redat
    ports:
      - "8200:8200"
    env_file: .env
    environment:
      REDAT_DATA_DIR: /data
    volumes:
      - ./data:/data
    restart: unless-stopped
    mem_limit: 2g
    init: true
```

`.env` on the host: `cp .env.example .env`, then set `GEOAPIFY_API_KEY` to the value from `/srv/house-hunter/.env` (`grep ^GEOAPIFY_API_KEY /srv/house-hunter/.env`) and `REDAT_PUBLIC_URL=http://192.168.188.64:8200`. Leave `REDAT_API_KEY` empty for now (LAN-open, spec default). `.env` is git-ignored (Task 1).

- [ ] **Step 3: Build and start**

```bash
cd /srv/nrw-redat
docker compose build 2>&1 | tail -30      # the test stage prints the pytest summary; a red suite aborts the build
docker compose up -d
sleep 8; curl -s http://localhost:8200/healthz
```
Expected: `{"status":"ok","version":"1.0.0","chromium":true,"sources_loaded":<n>}` with `n` = `len(SECTIONS)`. If `chromium` is `false`, run `docker compose exec redat python -c "from playwright.sync_api import sync_playwright; p=sync_playwright().start(); b=p.chromium.launch(); print(b.version)"` and read the error (usually a missing lib → wrong base image tag).

- [ ] **Step 4: Live verification (spec §12 step 6)**

Run and record each result in the Task 10 report:
```bash
B=http://localhost:8200
curl -s "$B/api/v1/sections" | python -m json.tool | head -20
curl -s "$B/api/v1/geocode?address=Brückstraße+1,+Essen"
# Werden house-number address — parcel cards must be ok (not gated)
curl -s "$B/api/v1/analyze?address=Brückstraße+1,+45239+Essen&plot_size_m2=400&save=1" -o /tmp/claude-1000/-srv-house-hunter/*/scratchpad/werden.json
python - <<'EOF'
import json,glob; d=json.load(open(glob.glob('/tmp/claude-1000/-srv-house-hunter/*/scratchpad/werden.json')[0]))
print(d['run_id'], d['permalink'], d['geocode']['precision'])
for k,e in d['sections'].items(): print(f"{k:16} {e['status']:6} {e.get('took_ms')} {e.get('message') or ''}")
EOF
# Kortumstraße, Bochum (street-level, Bochum-specific cards planning_bochum/bergbau/energie Entwurf)
curl -s "$B/api/v1/analyze?address=Kortumstraße+100,+Bochum" | python -c "import json,sys; d=json.load(sys.stdin); print({k:v['status'] for k,v in d['sections'].items()})"
# permalink + stored-run JSON + PDF re-render
RID=<run_id from above>; curl -s -o /dev/null -w "%{http_code}\n" "$B/a/$RID"; curl -s "$B/api/v1/run/$RID" | head -c 300; echo
curl -s -D - -o /dev/null "$B/api/v1/run/$RID/report.pdf" | grep -i "content-\(type\|disposition\)"
# GET report (machine path)
curl -s -o /dev/null -w "%{http_code} %{size_download}\n" "$B/api/v1/report?address=Brückstraße+1,+45239+Essen"
# 422 / 404 paths
curl -s -w " %{http_code}\n" "$B/api/v1/analyze?address=xyzzy-nirgendwo-99999"
curl -s -w " %{http_code}\n" "$B/api/v1/run/zzzzzzzzzz"
```
Acceptance: Werden run has `boris`, `flood`, `noise`, `zensus`, `oepnv`, `commute` = `ok`; no section `error` other than a genuinely-down upstream (record which); the permalink page returns 200; the PDF is `application/pdf` with a `Standortanalyse_…pdf` filename; the unresolvable address returns 422.

API key on/off: set `REDAT_API_KEY=test123` in `.env`, `docker compose up -d` (recreates), then `curl -s -o /dev/null -w "%{http_code}\n" $B/api/v1/sections` → 401, with `-H "X-Api-Key: test123"` → 200, `$B/` and `$B/healthz` → 200 without the header. Then remove the key from `.env` and `docker compose up -d` again (LAN-open is the agreed default).

Browser check with the Playwright MCP tools (or `scripts/smoke_analyze.py` adapted to `http://192.168.188.64:8200/?address=Brückstraße 1, 45239 Essen&auto=1`): the page runs, the URL changes to `/a/<id>`, cards render, "📄 PDF-Bericht" downloads, `/quellen` lists every card.

- [ ] **Step 5: Docs**

- `README.md`: what REDAT is (one paragraph), quick start (clone, `.env`, `docker compose up -d --build`), the geodata rsync note (`data/source/{boris,flood,elections}` ≈ 6.2 GB, not in git, copied from hunter's `data/`), API overview table (the §5 routes, one line each), the `?address=…&auto=1` deep link, local dev (`python -m venv .venv && pip install -r requirements.txt -r requirements-dev.txt`, `uvicorn redat.app:app --reload --port 8200`, `pytest -q`), Tailwind rebuild command.
- `HANDOVER.md`: status (live on :8200 since 2026-09-05), the deploy runbook, "non-git deploy assets" (`data/source`, `.env`), known limitations (Störfallbetriebe note, Bochum air-quality fallback, BORIS 12 s cap, cache semantics incl. custom destinations bypass), work log with one entry per task commit, open items (hunter cutover §11 — separate plan).
- `CLAUDE.md`: commands (`pytest -q`, `uvicorn …`, `docker compose up -d --build`, Tailwind), architecture in ≤ 15 lines (settings → sources → core.sections/envelope → api.v1 + web.pages; store; report), the rules: `headers=headers()` on every outbound httpx call, no `verify=False`, German UI copy, partials unchanged contract with the `app` store name, `data_dir()` functions never module constants, only ok/empty envelopes cached.
- Copy the spec and this plan: `cp /srv/house-hunter/docs/superpowers/specs/2026-09-05-nrw-redat-design.md docs/2026-09-05-nrw-redat-design.md; cp /srv/house-hunter/docs/superpowers/plans/2026-09-05-nrw-redat.md docs/2026-09-05-nrw-redat-plan.md`.
- `/srv/README.md`: append one line to the service inventory (find the section listing house-hunter's :8000 service and add after it): `- **nrw-redat** — Standortanalyse-API + Website, Docker `nrw-redat` auf **:8200**, Checkout `/srv/nrw-redat`, Daten `/srv/nrw-redat/data` (SQLite + 6 GB Geodaten-Kopie von house-hunter). Update: `cd /srv/nrw-redat && git pull && docker compose up -d --build`.` Do not touch anything else in that file.

- [ ] **Step 6: Commit and push**

```bash
cd /srv/nrw-redat
git add -A && git commit -q -F - <<'EOF'
feat(deploy): Dockerfile with test gate, compose on :8200, README/HANDOVER/CLAUDE.md, spec+plan copies

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_015HbDiczEViCdm3XmxC2ReC
EOF
S=/tmp/claude-1000/-srv-house-hunter/97bbb76d-baf8-46d0-8934-6372bedf5c3c/scratchpad
printf '#!/bin/sh\ncase "$1" in *sername*) echo Jarvis;; *) echo "Jarvis2026!";; esac\n' > "$S/askpass.sh"; chmod 700 "$S/askpass.sh"
GIT_ASKPASS="$S/askpass.sh" GIT_TERMINAL_PROMPT=0 git push -u origin main; rm -f "$S/askpass.sh"
```
Then `git log --oneline origin/main | head -3` shows the deploy commit.

---

## Self-review notes (kept for executors)

- Spec §4 (package/geodata/`data_dir()`), §5 (all routes incl. `destinations`, 422/502/503), §6 (pages, permalink via `history.replaceState`, `/quellen` from `sources_meta`), §7 (settings precedence), §8 (runs table, base32 ids, cache semantics), §9 (test suite hermetic, Dockerfile test stage), §10 (Docker/compose) are each covered by Tasks 1–10. §11 (hunter cutover) is explicitly a later plan.
- Type threads to keep straight across tasks: `Ctx(lat, lon, plot_size_m2=None, destinations=())` (Task 5) is what `analyze.run_all` (Task 8) and `api_section` build; `run_section(key, ctx, precision=, force=)` keeps hunter's signature; `Destination(name, lat, lon, group="custom", address="")` (Task 1) is what `parse_destinations` (Task 8) constructs positionally — the test `Destination("Arbeit", 51.45, 7.01, "work")` relies on that order; `RunStore.save()` takes the **flat** shape (`payload_to_run` output), `RunStore.get()` returns flat + `id`/`created_at`; `build_report_context(payload)` takes the **nested** shape (`address`, `geocode{…}`, `sections`) — `run_to_payload` converts.
- `GeocodeResult` field names in Task 8/9 tests (`formatted_address, latitude, longitude, precision`) must match the dataclass copied in Task 3; the implementer of Task 8 checks the file first.
- The website store is named `app` on purpose (spec: partials unchanged).
