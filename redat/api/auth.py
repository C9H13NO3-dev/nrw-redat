"""Optional API key: when REDAT_API_KEY is set, every /api/* route needs X-Api-Key (spec §5)."""
import secrets

from fastapi import HTTPException, Request

from redat.settings import get_settings


def require_api_key(request: Request) -> None:
    expected = get_settings().api_key
    if not expected:
        return
    given = request.headers.get("X-Api-Key") or ""
    # Starlette decodes header values as latin-1, so a non-ASCII byte in the header survives as a
    # surrogate-escaped str; secrets.compare_digest(str, str) raises TypeError on those (a 500, not a
    # clean 401). Compare bytes instead — encode() with surrogateescape round-trips the original byte.
    given_b = given.encode("utf-8", "surrogateescape")
    expected_b = expected.encode("utf-8")
    if not secrets.compare_digest(given_b, expected_b):
        raise HTTPException(status_code=401, detail="X-Api-Key fehlt oder ist ungültig")
