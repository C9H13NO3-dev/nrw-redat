"""Login, logout, invite acceptance and the account page (server-rendered forms, CSRF double-submit)."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from redat.auth.csrf import check_csrf
from redat.auth.passwords import PasswordPolicyError, check_policy, verify_password
from redat.auth.principal import (SESSION_COOKIE, Principal, client_ip, current_principal, page_principal, safe_next,
                                  session_cookie_kwargs)
from redat.auth.throttle import login_throttle
from redat.auth.tokens import token_hash
from redat.settings import get_settings
from redat.store.users import InvalidUsernameError, UsernameTakenError
from redat.web.pages import _render

router = APIRouter(include_in_schema=False)
INVALID_INVITE = "Dieser Einladungslink ist ungültig, abgelaufen oder wurde bereits verwendet."
# Never a real password hash — only verified against to burn the same scrypt cost as a real check,
# so an unknown username, a wrong password and a disabled account all take the same time.
_DUMMY_HASH = "scrypt$32768$8$1$AAAAAAAAAAAAAAAAAAAAAA==$AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="


def _login_response(request: Request, user: dict, target: str, *, record_login: bool = True) -> RedirectResponse:
    """Create the session cookie. `record_login=False` for invite acceptance / password reset, which already
    record their own event (`invite_accepted` / `password_reset`) — a bare `login` right after would double up."""
    users, events = request.app.state.users, request.app.state.events
    token = users.create_session(user["id"], user_agent=request.headers.get("user-agent", ""), ip=client_ip(request),
                                 days=get_settings().session_days)
    users.touch_login(user["id"])
    if record_login:
        events.record("login", user_id=user["id"], via="session", ip=client_ip(request))
    resp = RedirectResponse(safe_next(target), status_code=303)
    resp.set_cookie(SESSION_COOKIE, token, **session_cookie_kwargs())
    return resp


@router.get("/login")
def login_form(request: Request, next: str = "/"):
    p = current_principal(request)
    if p is not None and p.via == "session":
        return RedirectResponse(safe_next(next), status_code=303)
    return _render(request, "login.html", {"next": safe_next(next), "error": None, "username": ""}, no_store=True)


@router.post("/login")
def login_submit(request: Request, username: str = Form(""), password: str = Form(""), csrf: str = Form(""), next: str = Form("/")):
    check_csrf(request, csrf)
    users, events = request.app.state.users, request.app.state.events
    name = username.strip().lower()[:64]
    key = (client_ip(request), name)
    locked = login_throttle.check(key)
    if locked:
        return _render(request, "login.html", {"next": safe_next(next), "username": name,
                       "error": f"Zu viele Fehlversuche – bitte in {locked} Sekunden erneut versuchen."}, status_code=429, no_store=True)
    row = users.get_by_username(name)
    # Always run exactly one verify_password, win or lose, so a disabled account (which would
    # otherwise short-circuit before hashing) doesn't return faster than a wrong password or an
    # unknown username — that timing gap is itself a "this username exists and is disabled" oracle.
    verified = verify_password(password, row["password_hash"]) if row else verify_password(password, _DUMMY_HASH)
    ok = bool(row) and verified and row["disabled_at"] is None
    if not ok:
        login_throttle.failure(key)
        events.record("login_failed", extra={"username": name}, ip=client_ip(request))
        return _render(request, "login.html", {"next": safe_next(next), "username": name,
                       "error": "Benutzername oder Passwort falsch."}, status_code=401, no_store=True)
    login_throttle.success(key)
    return _login_response(request, row, next)


@router.post("/logout")
def logout(request: Request, csrf: str = Form("")):
    check_csrf(request, csrf)
    p = current_principal(request)
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        request.app.state.users.delete_session(token)
    if p is not None and p.via == "session":
        request.app.state.events.record("logout", user_id=p.user_id, via="session", ip=client_ip(request))
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(SESSION_COOKIE, path="/")
    return resp


def _invite_ctx(request: Request, token: str, inv: dict, error: Optional[str], username: str = "") -> dict:
    reset_user = request.app.state.users.get(inv["reset_user_id"]) if inv.get("reset_user_id") else None
    return {"token": token, "invite": inv, "reset_user": reset_user, "error": error, "username": username}


@router.get("/invite/{token}")
def invite_form(request: Request, token: str):
    inv = request.app.state.users.get_invite(token)
    if inv is None:
        return _render(request, "404.html", {"message": INVALID_INVITE}, status_code=404, no_store=True)
    return _render(request, "invite.html", _invite_ctx(request, token, inv, None), no_store=True)


@router.post("/invite/{token}")
def invite_submit(request: Request, token: str, username: str = Form(""), password: str = Form(""), password2: str = Form(""), csrf: str = Form("")):
    check_csrf(request, csrf)
    users, events = request.app.state.users, request.app.state.events
    inv = users.get_invite(token)
    if inv is None:
        return _render(request, "404.html", {"message": INVALID_INVITE}, status_code=404, no_store=True)

    def fail(msg: str):
        return _render(request, "invite.html", _invite_ctx(request, token, inv, msg, username), status_code=400, no_store=True)
    if password != password2:
        return fail("Die Passwörter stimmen nicht überein.")
    try:
        check_policy(password)
    except PasswordPolicyError as exc:
        return fail(str(exc))
    if inv.get("reset_user_id"):
        user = users.get(inv["reset_user_id"])
        if user is None:
            return _render(request, "404.html", {"message": INVALID_INVITE}, status_code=404, no_store=True)
        users.set_password(user["id"], password)
        users.delete_user_sessions(user["id"])
        users.use_invite(token, user["id"])
        events.record("password_reset", user_id=user["id"], via="session", ip=client_ip(request))
    else:
        try:
            user = users.create(username, password, role=inv["role"], invited_by=inv["created_by"])
        except (InvalidUsernameError, UsernameTakenError) as exc:
            return fail(str(exc))
        users.use_invite(token, user["id"])
        events.record("invite_accepted", user_id=user["id"], via="session", extra={"note": inv.get("note") or ""}, ip=client_ip(request))
    return _login_response(request, user, "/", record_login=False)


@router.get("/konto")
def konto(request: Request, principal: Principal = Depends(page_principal), ok: str = ""):
    users = request.app.state.users
    current = token_hash(request.cookies.get(SESSION_COOKIE, ""))
    sessions = [{**s, "current": s["token_hash"] == current} for s in users.list_sessions(principal.user_id)]
    msg = {"passwort": "Passwort geändert; andere Geräte wurden abgemeldet.", "geraete": "Andere Geräte wurden abgemeldet."}.get(ok)
    return _render(request, "konto.html", {"active": "konto", "sessions": sessions, "error": None, "message": msg}, no_store=True)


@router.post("/konto/password")
def change_password(request: Request, principal: Principal = Depends(page_principal), current: str = Form(""),
                    password: str = Form(""), password2: str = Form(""), csrf: str = Form("")):
    check_csrf(request, csrf)
    users, events = request.app.state.users, request.app.state.events
    row = users.get_by_username(principal.username)

    def fail(msg: str):
        sessions = users.list_sessions(principal.user_id)
        return _render(request, "konto.html", {"active": "konto", "sessions": sessions, "error": msg, "message": None}, status_code=400, no_store=True)
    if not verify_password(current, row["password_hash"]):
        return fail("Das aktuelle Passwort ist falsch.")
    if password != password2:
        return fail("Die neuen Passwörter stimmen nicht überein.")
    try:
        check_policy(password)
    except PasswordPolicyError as exc:
        return fail(str(exc))
    users.set_password(principal.user_id, password)
    users.delete_user_sessions(principal.user_id, keep_token=request.cookies.get(SESSION_COOKIE))
    events.record("password_changed", user_id=principal.user_id, via="session", ip=client_ip(request))
    return RedirectResponse("/konto?ok=passwort", status_code=303)


@router.post("/konto/logout-others")
def logout_others(request: Request, principal: Principal = Depends(page_principal), csrf: str = Form("")):
    check_csrf(request, csrf)
    request.app.state.users.delete_user_sessions(principal.user_id, keep_token=request.cookies.get(SESSION_COOKIE))
    return RedirectResponse("/konto?ok=geraete", status_code=303)
