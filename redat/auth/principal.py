"""Who is calling: a session cookie (website + its fetches) or X-Api-Key (machine clients).

Resolution is cached on `request.state.principal` for the request. Dependencies: `require_principal` (API, 401),
`require_session_user` (account page, 401), `require_admin` (403), `page_principal` (website, 303 → /login?next=),
`optional_principal` (public pages that still show the navigation state). `safe_next` accepts only same-origin
relative paths and never the login page itself.
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Optional
from urllib.parse import quote

from fastapi import HTTPException, Request

from redat.settings import get_settings

SESSION_COOKIE = "redat_session"
CSRF_COOKIE = "redat_csrf"
_UNSET = object()


@dataclass(frozen=True)
class Principal:
    user: Optional[dict]       # public user row; None for the API key
    role: str                  # "admin" | "user"
    via: str                   # "session" | "api_key"

    @property
    def username(self) -> str:
        return self.user["username"] if self.user else "api"

    @property
    def user_id(self) -> Optional[int]:
        return self.user["id"] if self.user else None

    @property
    def is_admin(self) -> bool:
        return self.via == "session" and self.role == "admin"


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else ""


def _api_key_ok(request: Request) -> bool:
    expected = get_settings().api_key
    if not expected:
        return False
    given = request.headers.get("X-Api-Key") or ""
    return secrets.compare_digest(given.encode("utf-8", "surrogateescape"), expected.encode("utf-8"))


def current_principal(request: Request) -> Optional[Principal]:
    cached = getattr(request.state, "principal", _UNSET)
    if cached is not _UNSET:
        return cached
    principal = None
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        users = request.app.state.users
        row = users.resolve_session(token)
        if row is not None:
            users.touch_session(token, days=get_settings().session_days)
            principal = Principal(user={k: v for k, v in row.items() if not k.startswith("session_")}, role=row["role"], via="session")
    if principal is None and _api_key_ok(request):
        principal = Principal(user=None, role="user", via="api_key")
    request.state.principal = principal
    return principal


def require_principal(request: Request) -> Principal:
    p = current_principal(request)
    if p is None:
        raise HTTPException(status_code=401, detail="Anmeldung erforderlich")
    return p


def require_session_user(request: Request) -> Principal:
    p = require_principal(request)
    if p.via != "session":
        raise HTTPException(status_code=401, detail="Anmeldung erforderlich")
    return p


def require_admin(request: Request) -> Principal:
    p = require_session_user(request)
    if not p.is_admin:
        raise HTTPException(status_code=403, detail="Nur für Administratoren")
    return p


def safe_next(value) -> str:
    v = str(value or "")
    if not v.startswith("/") or v.startswith("//") or "\\" in v or v.startswith("/login"):
        return "/"
    return v


def page_principal(request: Request) -> Principal:
    """Website pages: redirect to the login page instead of a bare 401."""
    p = current_principal(request)
    if p is None or p.via != "session":
        target = request.url.path + (f"?{request.url.query}" if request.url.query else "")
        raise HTTPException(status_code=303, headers={"Location": f"/login?next={quote(target, safe='')}"})
    return p


def page_admin(request: Request) -> Principal:
    p = page_principal(request)
    if not p.is_admin:
        raise HTTPException(status_code=403, detail="Nur für Administratoren")
    return p


def optional_principal(request: Request) -> Optional[Principal]:
    return current_principal(request)


def session_cookie_kwargs(settings=None) -> dict:
    s = settings or get_settings()
    return {"httponly": True, "samesite": "lax", "secure": s.cookie_secure, "path": "/", "max_age": s.session_days * 86400}


def csrf_cookie_kwargs(settings=None) -> dict:
    s = settings or get_settings()
    return {"httponly": False, "samesite": "lax", "secure": s.cookie_secure, "path": "/", "max_age": 365 * 86400}
