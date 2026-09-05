# CLAUDE.md

Guidance for Claude Code (claude.ai/code) working in this repository.

> **Start here for current status:** [`HANDOVER.md`](HANDOVER.md) is the living source of truth for
> project state, the deploy runbook, and the work log. Read it before starting work.

## Commands

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/python -m pytest -q                     # 439 tests, hermetic, ~6.5s
GEOAPIFY_API_KEY=… .venv/bin/uvicorn redat.app:app --port 8200 --reload
docker compose up -d --build                      # build gate: the test stage runs `pytest -q` and aborts the image on a red suite
npx tailwindcss@3 -c tailwind.config.js -i tailwind.input.css -o redat/static/redat.css --minify
```

## Architecture

Package `redat`. Config precedence (`redat/settings.py`): env > `config/settings.yaml` > code defaults;
`Destination`/`get_settings()` live here. `redat/sources/` wraps each external geodata source (BORIS,
flood, Lärm, Zensus, Denkmal, ÖPNV, …), one module per source. `redat/core/sections.py` declares the
20-card `SECTIONS` registry (`Section(key, title, icon, tier, timeout_s, source, fetch)`); `core/envelope.py`'s
`run_section()` runs one card under its timeout and returns the fixed `{key, tier, status, data, message,
source, took_ms}` envelope, gating parcel-tier cards unless precision is house-number/coordinates/`force`;
`core/analyze.py` orchestrates geocode + all cards concurrently and the payload shapes shared by the API
and the website. `redat/api/v1.py` is the versioned JSON+PDF API (`/api/v1/*`, optional `X-Api-Key` via
`api/auth.py`); `redat/web/pages.py` serves `/`, `/a/{id}`, `/quellen`. `redat/store/` is SQLite: `runs.py`
(persisted analyses, base32 ids) and `cache.py` (`SectionCache`, TTL-based). `redat/report/` builds and
renders the PDF (Jinja2 → Playwright Chromium).

## Rules

- Every outbound HTTP call passes `headers=headers()` from `redat/http.py` (identifies the service by User-Agent) — never a bare `httpx.get(...)`.
- Never `verify=False`; a host needing a non-standard chain ships its cert under `redat/data/certs/` (see `backend/breitband_service` pattern carried over from house-hunter).
- All UI copy (website + PDF report) is German.
- Website partials (`redat/templates/analysis/_*.html`) keep the store name `app` — an intentional carry-over from the house-hunter partials' Alpine store contract; do not rename it.
- `data_dir()` (in each `sources/*.py` module) is always a function, never a module-level constant — it must re-read `REDAT_DATA_DIR` per call so tests can monkeypatch it.
- Only `ok`/`empty` envelopes are cached (`SectionCache`); `error`/`gated` are always recomputed. A `destinations` param on `/analyze`/`/section` bypasses the cache entirely (custom commute destinations are per-request, not shared).
