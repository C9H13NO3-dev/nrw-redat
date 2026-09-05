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
