# User management, sessions and usage statistics: Design

**Date:** 2026-09-09 · **Status:** approved by the owner (approach 1, "go on until finished and verified") ·
**Plan:** `docs/superpowers/plans/2026-09-09-user-management.md`

## 1. Problem

The site at `https://redat.ares-hud.com` is gated by a single Traefik BasicAuth user (`test`) declared in the
host-only `docker-compose.override.yml`. The owner wants to share the tool with friends, give each of them an
account, and see how much the tool is used. The app has no notion of a user: `REDAT_API_KEY` protects `/api/v1/*`
for machine clients only and, when set, breaks the website's own same-origin fetches (HANDOVER "API key vs.
website"). Decisions taken in the brainstorm: **invite links** (no public sign-up), **per-user activity including
addresses** in an admin dashboard, **permalinks stay public** (anyone with a `/a/{id}` link, including its PDF).

## 2. Approach

App-native login with server-side sessions, in the existing SQLite database. Traefik keeps TLS, the HTTP→HTTPS
redirect and the security headers; the BasicAuth middleware is removed from the router in the same deploy. No
new Python dependency: passwords use `hashlib.scrypt`, session tokens are random 256-bit values stored hashed,
forms carry a double-submit CSRF token. `REDAT_API_KEY` stays as the credential for machine clients.

## 3. Access rules

| Path | Rule |
|---|---|
| `GET /login`, `POST /login`, `POST /logout`, `GET/POST /invite/{token}`, `GET /healthz`, `/static/*` | public |
| `GET /a/{run_id}`, `GET /api/v1/run/{run_id}`, `GET /api/v1/run/{run_id}/report.pdf`, `GET /quellen` | public (permalink sharing; the sources page carries no data) |
| everything else (`/`, `/konto`, `/docs`, `/openapi.json`, `/redoc`, `/api/v1/*`) | needs a principal: a valid session cookie **or** a valid `X-Api-Key` |
| `/admin` and `/admin/*` | needs a session whose user has role `admin` (an API key is never admin) |

Website routes without a principal redirect to `/login?next=<path>` (only same-origin relative `next` values are
honoured); API routes answer `401 {"detail": "Anmeldung erforderlich"}`. A disabled user's sessions are rejected
on the next request and deleted.

## 4. Data model (`redat.db`, created by `UserStore.init()` / `EventStore.init()`; `runs` gains `user_id`)

```
users     (id INTEGER PK, username TEXT UNIQUE, password_hash TEXT, role TEXT 'admin'|'user',
           created_at TEXT, disabled_at TEXT NULL, last_login_at TEXT NULL, invited_by INTEGER NULL)
sessions  (token_hash TEXT PK, user_id INTEGER, created_at TEXT, last_seen_at TEXT, expires_at TEXT,
           user_agent TEXT, ip TEXT)
invites   (token_hash TEXT PK, created_by INTEGER, created_at TEXT, expires_at TEXT, note TEXT,
           role TEXT, reset_user_id INTEGER NULL, used_at TEXT NULL, used_by INTEGER NULL)
events    (id INTEGER PK AUTOINCREMENT, ts TEXT, kind TEXT, user_id INTEGER NULL, via TEXT,
           address TEXT NULL, lat REAL NULL, lon REAL NULL, run_id TEXT NULL, extra TEXT NULL, ip TEXT NULL)
runs      + user_id INTEGER NULL   (ALTER TABLE on init when the column is missing)
```

Timestamps are ISO-8601 UTC. `token_hash` is `sha256(token)` so a copied database yields no usable session or
invite. Usernames: 3–32 characters, `[a-z0-9._-]`, stored lowercase, unique. Passwords: at least 8 characters,
at most 200. `via` is `session` or `api_key`.

## 5. Mechanics

**Passwords.** `scrypt(password, salt=16 random bytes, n=2**15, r=8, p=1, dklen=32)`, stored as
`scrypt$32768$8$1$<salt b64>$<hash b64>`; verification parses the parameters (so they can be raised later) and
compares with `secrets.compare_digest`.

**Sessions.** `secrets.token_urlsafe(32)` in the cookie `redat_session` (HttpOnly, SameSite=Lax, Path=/,
`Secure` when `public_url` starts with `https`, Max-Age = `REDAT_SESSION_DAYS` days, default 30). The row stores
the hash and a sliding expiry: `last_seen_at` is touched at most once per hour and `expires_at` moves with it.
Logout deletes the row and clears the cookie. "Alle Geräte abmelden" deletes every row of the user.

**CSRF.** Every HTML form carries a hidden `csrf` field that must equal the value of the non-HttpOnly cookie
`redat_csrf` (random 128-bit, set on first page load; SameSite=Lax). JSON API mutations (`POST /api/v1/runs`,
`POST /api/v1/report`) are protected by the Lax cookie plus the requirement of `Content-Type: application/json`
(cross-site forms cannot send that content type without a CORS preflight, which the app does not answer).

**Login throttling.** In-memory, per process: after 5 failed logins for the same `(client IP, username)` within
10 minutes, further attempts are refused for 60 seconds with a German message; a successful login clears the
counter. The client IP is `X-Forwarded-For`'s first entry when the request came through the proxy, otherwise the
peer address.

**Principal resolution** (`redat/auth/principal.py`): `current_principal(request) -> Principal | None` reads
the cookie first, then `X-Api-Key`; a `Principal` has `user` (a users row as dict, `None` for the API key),
`role`, `via`, `username` ("api" for the key). FastAPI dependencies `require_principal`, `require_user`
(session only), `require_admin`; the website uses `page_principal` which redirects instead of raising.

**Bootstrap.** On startup, when the `users` table is empty and `REDAT_BOOTSTRAP_ADMIN_PASSWORD` is set, an
`admin` user with that password is created (logged as a warning to change it); when unset, the app starts with
no users and `scripts/users.py create-admin` creates one (prompts for the password). The owner's requested first
credentials (`admin` / `test123!`) are provided through that env variable in the host's `.env`, not in git.

## 6. Pages

- `/login`: username, password, CSRF; error line; note that usage is recorded per user (§8).
- `/invite/{token}`: valid unused invite → form (username, password, repeat) → creates the user, marks the invite
  used, logs in, redirects to `/`. A reset invite (`reset_user_id` set) shows only the password fields and sets
  the existing user's password, then deletes that user's other sessions. Invalid/expired/used → 404 page copy.
- `/konto`: change password (current, new, repeat), list of the user's sessions (device, last seen) with "alle
  anderen Geräte abmelden", logout button.
- `/admin` (admin only): KPI tiles (users active/total, analyses 7 d / 30 d / total, PDFs 30 d, permalink views
  30 d), a bar chart of analyses per day for the last 30 days (Chart.js, already loaded site-wide, via a JSON
  block in the page), users table (username, role, status, analyses total / 30 d, PDFs, last active, actions:
  deaktivieren/aktivieren, Passwort-Link, löschen — an admin cannot disable or delete themselves), invites table
  (pending with note/expiry/revoke, used with who/when), "Neuer Einladungslink" form (note, role) whose result
  URL is shown once, recent activity table (last 50 events: time, user, kind, address/run link).
- Navigation (`base.html`): logged-in → username link to `/konto`, "Admin" link for admins, "Abmelden" button
  (POST form); logged-out pages show a "Anmelden" link. The footer text drops "Essen & Bochum".

All copy German.

## 7. Usage events

| kind | where | fields |
|---|---|---|
| `login` / `logout` / `login_failed` | auth pages | user (failed: username in `extra`), ip |
| `invite_created` / `invite_accepted` / `password_changed` / `password_reset` | admin/invite/account | user, extra (note / target user) |
| `analyze` | `POST /api/v1/runs` (the website saves every completed analysis here) and `GET /api/v1/analyze` | address, lat, lon, run_id, extra `{"ok": n, "error": n, "empty": n}` |
| `pdf` | `POST /api/v1/report`, `GET /api/v1/report`, `GET /api/v1/run/{id}/report.pdf` | address, run_id |
| `permalink_view` | `GET /a/{run_id}` | run_id, address, user (nullable) |

`runs.user_id` is set on save. Events are append-only; `EventStore.stats(days)` returns the dashboard numbers
with plain SQL (`GROUP BY date(ts)`, `GROUP BY user_id`). Nothing is deleted automatically; `scripts/users.py
prune-events --days N` exists for the owner.

## 8. Privacy and security notes

- The login page states in one sentence that analyses, addresses and PDF exports are recorded per account and
  visible to the administrator.
- No e-mail addresses are stored; there is no self-service password reset (the admin sends a reset link).
- Security headers stay with Traefik (`sec-headers@docker`); the app adds `Cache-Control: no-store` to `/admin`,
  `/konto` and `/login` responses.
- `/healthz` stays public and unchanged (uptime probes).

## 9. Deployment

1. Deploy the image with `REDAT_BOOTSTRAP_ADMIN_PASSWORD` in `.env` (host); the app creates `admin`.
2. Edit the host-only `docker-compose.override.yml`: remove the two `redat-auth` middleware labels and change
   the router middlewares to `sec-headers@docker` only; `docker compose up -d` again. Verify over HTTPS: `/` →
   302 to `/login`, login as admin → `/`, `/api/v1/sections` 401 without cookie, `/a/<id>` public, `/admin`
   loads, an invite link round-trips in a private browser session.
3. Recovery if locked out: `docker compose exec redat python scripts/users.py create-admin` or
   `… reset --username admin`.

## 10. Non-goals

E-mail, OAuth/SSO, 2FA, per-user quotas, sharing permissions on runs, deleting a user's runs with the user.
