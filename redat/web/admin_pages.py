"""Admin page: usage statistics, users, invite links. Admin sessions only (page_admin)."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from redat.auth.csrf import check_csrf
from redat.auth.principal import Principal, client_ip, page_admin
from redat.settings import get_settings
from redat.web.pages import _render

router = APIRouter(prefix="/admin", include_in_schema=False)
KIND_LABELS = {"login": "Anmeldung", "logout": "Abmeldung", "login_failed": "Fehlgeschlagene Anmeldung", "invite_created": "Einladung erstellt",
               "invite_accepted": "Einladung angenommen", "password_changed": "Passwort geändert", "password_reset": "Passwort zurückgesetzt",
               "analyze": "Analyse", "pdf": "PDF-Export", "permalink_view": "Permalink aufgerufen"}
ACTIONS = ("disable", "enable", "delete", "reset")


def _ctx(request: Request, principal: Principal, *, new_invite_url: Optional[str] = None, error: Optional[str] = None) -> dict:
    users, events = request.app.state.users, request.app.state.events
    stats = events.stats(30)
    per_user = {r["user_id"]: r for r in stats["per_user"]}
    rows = [{**u, **per_user.get(u["id"], {})} for u in users.list_users()]
    return {"active": "admin", "stats": stats, "users": rows, "invites": users.list_invites(), "recent": events.recent(50),
            "kind_labels": KIND_LABELS, "new_invite_url": new_invite_url, "error": error, "me": principal.user_id}


@router.get("")
def admin_home(request: Request, principal: Principal = Depends(page_admin)):
    return _render(request, "admin.html", _ctx(request, principal), no_store=True)


@router.post("/invites")
def create_invite(request: Request, principal: Principal = Depends(page_admin), note: str = Form(""), role: str = Form("user"), csrf: str = Form("")):
    check_csrf(request, csrf)
    if role not in ("user", "admin"):
        raise HTTPException(status_code=400, detail="Unbekannte Rolle")
    tok = request.app.state.users.create_invite(principal.user_id, note=note.strip(), role=role)
    request.app.state.events.record("invite_created", user_id=principal.user_id, via="session", extra={"note": note.strip(), "role": role}, ip=client_ip(request))
    return _render(request, "admin.html", _ctx(request, principal, new_invite_url=f"{get_settings().public_url}/invite/{tok}"), no_store=True)


@router.post("/invites/{token_hash}/revoke")
def revoke_invite(request: Request, token_hash: str, principal: Principal = Depends(page_admin), csrf: str = Form("")):
    check_csrf(request, csrf)
    request.app.state.users.revoke_invite(token_hash)
    return RedirectResponse("/admin", status_code=303)


@router.post("/users/{user_id}/{action}")
def user_action(request: Request, user_id: int, action: str, principal: Principal = Depends(page_admin), csrf: str = Form("")):
    check_csrf(request, csrf)
    if action not in ACTIONS:
        raise HTTPException(status_code=404, detail="Unbekannte Aktion")
    users = request.app.state.users
    target = users.get(user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Unbekannter Benutzer")
    if user_id == principal.user_id and action != "reset":
        return _render(request, "admin.html", _ctx(request, principal, error="Sie können sich nicht selbst deaktivieren oder löschen."), status_code=400, no_store=True)
    if action == "disable":
        users.set_disabled(user_id, True)
    elif action == "enable":
        users.set_disabled(user_id, False)
    elif action == "delete":
        users.delete(user_id)
    else:
        tok = users.create_invite(principal.user_id, note=f"Passwort-Reset {target['username']}", role=target["role"], reset_user_id=user_id)
        request.app.state.events.record("invite_created", user_id=principal.user_id, via="session", extra={"reset_user": target["username"]}, ip=client_ip(request))
        return _render(request, "admin.html", _ctx(request, principal, new_invite_url=f"{get_settings().public_url}/invite/{tok}"), no_store=True)
    return RedirectResponse("/admin", status_code=303)
