"""Double-submit CSRF for the HTML forms: the `redat_csrf` cookie must equal the form's hidden `csrf` field.

The JSON API endpoints need no token: cross-site forms cannot send `Content-Type: application/json`, and the
session cookie is SameSite=Lax, so a cross-site POST carries neither the cookie nor the content type.
"""
from __future__ import annotations

import re
import secrets

from fastapi import HTTPException, Request

from redat.auth.principal import CSRF_COOKIE
from redat.auth.tokens import new_token

_VALID = re.compile(r"^[A-Za-z0-9_-]{16,64}$")


def ensure_csrf(request: Request) -> str:
    """The request's CSRF token; a fresh one is flagged on request.state.csrf_new so the response sets the cookie."""
    tok = getattr(request.state, "csrf", None)
    if tok:
        return tok
    tok = request.cookies.get(CSRF_COOKIE) or ""
    if not _VALID.match(tok):
        tok = new_token()
        request.state.csrf_new = tok
    request.state.csrf = tok
    return tok


def check_csrf(request: Request, submitted: str) -> None:
    expected = request.cookies.get(CSRF_COOKIE) or ""
    if not expected or not submitted or not secrets.compare_digest(expected.encode(), str(submitted).encode()):
        raise HTTPException(status_code=403, detail="Ungültiges Formular-Token (CSRF). Bitte Seite neu laden.")
