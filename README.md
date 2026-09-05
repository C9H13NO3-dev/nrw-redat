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
