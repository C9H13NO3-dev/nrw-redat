# User Management, Sessions and Usage Statistics — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Traefik BasicAuth gate with app-native accounts: invite-link onboarding, server-side sessions, an account page, an admin page with per-user usage statistics, and public permalinks — with no new Python dependency.

**Architecture:** Three new stores in the existing SQLite file (`UserStore`: users/sessions/invites; `EventStore`: append-only usage events; `runs.user_id`), a small `redat/auth/` package (scrypt passwords, tokens, principal resolution, CSRF, login throttle), FastAPI dependencies that gate the API (401) and the website (303 → `/login`), new server-rendered pages under `redat/web/`, and the existing `X-Api-Key` kept as a second credential for machine clients.

**Tech Stack:** Python 3.12 stdlib (`hashlib.scrypt`, `secrets`, `sqlite3`), FastAPI/Starlette, Jinja2, Alpine.js + Tailwind (existing), Chart.js (already loaded site-wide), pytest + `TestClient`.

**Spec:** `docs/superpowers/specs/2026-09-09-user-management-design.md` — read it first; every path, table column, cookie name and message comes from it.

## Global Constraints

- No new runtime dependency. Passwords: `hashlib.scrypt`; tokens: `secrets`; CSRF: double-submit cookie.
- All UI copy German. Website templates extend `base.html`; keep the card style (`bg-white rounded-lg shadow p-6`, teal buttons).
- Access rules exactly as spec §3: public = `/login`, `/logout`, `/invite/*`, `/healthz`, `/static/*`, `GET /a/{id}`, `GET /api/v1/run/{id}`, `GET /api/v1/run/{id}/report.pdf`, `GET /quellen`; everything else needs a principal (session cookie or `X-Api-Key`); `/admin*` needs an admin session.
- Cookies: `redat_session` HttpOnly, SameSite=Lax, Path=/, Secure iff `public_url` starts with `https://`, Max-Age = `session_days × 86400`; `redat_csrf` not HttpOnly, SameSite=Lax, Path=/, same Secure rule.
- Tokens are never stored in clear: `sessions.token_hash` / `invites.token_hash` = sha256 hex of the token.
- Tests hermetic: every test that needs a logged-in client uses `tests/helpers_auth.py` (creates the user + session through the stores and sets the cookie on the `TestClient`); no network.
- The existing suite must stay green at every task; `tests/conftest.py` must also unset `REDAT_BOOTSTRAP_ADMIN_PASSWORD` and `REDAT_SESSION_DAYS` per test.
- Session facts: `.venv/bin/python -m pytest -q` (735 tests green at baseline — verify at start); commit trailer lines
  `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>` and `Claude-Session: https://claude.ai/code/session_01ELQWyFxDQjrqLebFT6rmks`;
  work on a branch, never on main, never push.

---

## File Structure

| File | Responsibility |
|---|---|
| `redat/auth/passwords.py` (T1) | scrypt hash/verify, password policy |
| `redat/auth/tokens.py` (T1) | random tokens and their sha256 |
| `redat/store/users.py` (T1) | `UserStore`: users, sessions, invites |
| `redat/store/events.py` (T1) | `EventStore`: record, recent, stats, prune |
| `redat/store/runs.py` (T1) | `runs.user_id` column |
| `redat/auth/principal.py`, `redat/auth/throttle.py` (T2) | who is calling; dependencies; login throttle |
| `redat/api/auth.py`, `redat/api/v1.py`, `redat/app.py`, `redat/settings.py` (T2) | gating, public run routes, store wiring, bootstrap admin |
| `tests/helpers_auth.py` (T2) | `login(client, ...)` for every test that needs a session |
| `redat/auth/csrf.py`, `redat/web/auth_pages.py`, templates `login.html`, `invite.html`, `konto.html`, `base.html` (T3) | login, logout, invite acceptance, account page, navigation |
| `redat/web/admin_pages.py`, `redat/templates/admin.html`, event hooks in `api/v1.py` and `web/pages.py` (T4) | usage recording and the admin dashboard |
| `scripts/users.py`, docs, CSS (T5) | operations |

---

### Task 1: Stores — passwords, tokens, users/sessions/invites, events, `runs.user_id`

**Files:**
- Create: `redat/auth/__init__.py` (empty docstring module), `redat/auth/passwords.py`, `redat/auth/tokens.py`, `redat/store/users.py`, `redat/store/events.py`, `tests/test_auth_passwords.py`, `tests/test_store_users.py`, `tests/test_store_events.py`
- Modify: `redat/store/runs.py`, `tests/test_store_runs.py`
- Test: the four test files

**Interfaces (produced):**
- `passwords.hash_password(pw) -> str`, `passwords.verify_password(pw, stored) -> bool`, `passwords.check_policy(pw)` raising `PasswordPolicyError(ValueError)` with a German message; `MIN_LEN = 8`, `MAX_LEN = 200`.
- `tokens.new_token() -> str` (43 chars, urlsafe), `tokens.token_hash(token) -> str` (64 hex).
- `UserStore(db_path)`: `init()`, `count()`, `create(username, password, role="user", invited_by=None) -> dict`, `get(user_id)`, `get_by_username(username)`, `list_users()`, `set_password(user_id, password)`, `set_disabled(user_id, disabled: bool)`, `delete(user_id)`, `touch_login(user_id)`, `create_session(user_id, *, user_agent="", ip="", days=30) -> token`, `resolve_session(token) -> dict | None` (user row incl. `session_token_hash`, `session_last_seen_at`), `touch_session(token, days)`, `delete_session(token)`, `delete_user_sessions(user_id, keep_token=None) -> int`, `list_sessions(user_id) -> list[dict]`, `create_invite(created_by, *, note="", role="user", reset_user_id=None, days=7) -> token`, `get_invite(token) -> dict | None` (only valid: unused, unexpired), `use_invite(token, used_by)`, `list_invites() -> list[dict]`, `revoke_invite(token_hash) -> bool`. Errors: `UsernameTakenError`, `InvalidUsernameError` (both `ValueError`). `USERNAME_RE = r"^[a-z0-9._-]{3,32}$"`.
- `EventStore(db_path)`: `init()`, `record(kind, *, user_id=None, via=None, address=None, lat=None, lon=None, run_id=None, extra=None, ip=None) -> int`, `recent(limit=50) -> list[dict]` (with `username`), `stats(days=30) -> dict` (shape in Step 3), `prune(days) -> int`.
- `RunStore.save(payload, user_id=None)`; `RunStore.init()` adds `user_id` to an existing table; `get()` returns `user_id`.

- [ ] **Step 1: Write the failing tests**

`tests/test_auth_passwords.py`:

```python
import pytest

from redat.auth import passwords as pw


def test_hash_and_verify_roundtrip():
    h = pw.hash_password("korrekt-pferd-batterie")
    assert h.startswith("scrypt$32768$8$1$") and h.count("$") == 5
    assert pw.verify_password("korrekt-pferd-batterie", h)
    assert not pw.verify_password("korrekt-pferd-batteri", h)


def test_hashes_are_salted():
    assert pw.hash_password("abcdefgh") != pw.hash_password("abcdefgh")


def test_verify_parses_parameters_from_the_stored_string():
    h = pw.hash_password("abcdefgh", n=2 ** 14)
    assert h.startswith("scrypt$16384$8$1$") and pw.verify_password("abcdefgh", h)


def test_verify_never_raises_on_garbage():
    for bad in ("", "plain", "scrypt$x$8$1$a$b", "scrypt$16384$8$1$!!!$???", None):
        assert pw.verify_password("abcdefgh", bad) is False


def test_policy():
    with pytest.raises(pw.PasswordPolicyError, match="mindestens 8"):
        pw.check_policy("kurz")
    with pytest.raises(pw.PasswordPolicyError, match="höchstens 200"):
        pw.check_policy("x" * 201)
    with pytest.raises(pw.PasswordPolicyError):
        pw.hash_password("kurz")
    pw.check_policy("test123!")
```

`tests/test_store_users.py`:

```python
"""redat/store/users.py — users, sessions, invites in a temp SQLite file."""
from datetime import datetime, timedelta, timezone

import pytest

from redat.auth.tokens import token_hash
from redat.store.users import InvalidUsernameError, UsernameTakenError, UserStore


@pytest.fixture
def store(tmp_path):
    s = UserStore(tmp_path / "redat.db")
    s.init()
    s.init()          # idempotent
    return s


def test_create_get_and_list(store):
    u = store.create("Mitja", "test123!", role="admin")
    assert u["username"] == "mitja" and u["role"] == "admin" and u["id"] == 1 and "password_hash" not in u
    assert store.count() == 1 and store.get(1)["username"] == "mitja" and store.get(99) is None
    assert store.get_by_username("MITJA")["password_hash"].startswith("scrypt$")
    assert [x["username"] for x in store.list_users()] == ["mitja"]


def test_username_rules(store):
    store.create("a.b-c_1", "test123!")
    for bad in ("ab", "x" * 33, "mit ja", "ümlaut", "admin!"):
        with pytest.raises(InvalidUsernameError):
            store.create(bad, "test123!")
    with pytest.raises(UsernameTakenError):
        store.create("A.B-C_1", "test123!")


def test_password_change_and_disable(store):
    u = store.create("mitja", "test123!")
    store.set_password(u["id"], "neuesPasswort9")
    from redat.auth.passwords import verify_password
    assert verify_password("neuesPasswort9", store.get_by_username("mitja")["password_hash"])
    store.set_disabled(u["id"], True)
    assert store.get(u["id"])["disabled_at"] is not None
    store.set_disabled(u["id"], False)
    assert store.get(u["id"])["disabled_at"] is None


def test_sessions_resolve_touch_expire_and_delete(store):
    u = store.create("mitja", "test123!")
    tok = store.create_session(u["id"], user_agent="pytest", ip="127.0.0.1", days=30)
    assert len(tok) >= 40
    row = store.resolve_session(tok)
    assert row["username"] == "mitja" and row["session_token_hash"] == token_hash(tok) and "password_hash" not in row
    assert store.resolve_session("nope") is None
    assert [s["user_agent"] for s in store.list_sessions(u["id"])] == ["pytest"]
    # expired sessions are rejected and removed
    with store._connect() as con:
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        con.execute("UPDATE sessions SET expires_at = ?", (past,))
    assert store.resolve_session(tok) is None and store.list_sessions(u["id"]) == []
    # a disabled user's session resolves to None and is deleted
    tok2 = store.create_session(u["id"])
    store.set_disabled(u["id"], True)
    assert store.resolve_session(tok2) is None and store.list_sessions(u["id"]) == []
    store.set_disabled(u["id"], False)
    t3, t4 = store.create_session(u["id"]), store.create_session(u["id"])
    assert store.delete_user_sessions(u["id"], keep_token=t3) == 1
    assert store.resolve_session(t3) and store.resolve_session(t4) is None
    store.delete_session(t3)
    assert store.resolve_session(t3) is None


def test_touch_session_slides_expiry_at_most_hourly(store):
    u = store.create("mitja", "test123!")
    tok = store.create_session(u["id"], days=30)
    with store._connect() as con:
        old = (datetime.now(timezone.utc) - timedelta(days=2)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        con.execute("UPDATE sessions SET last_seen_at = ?, expires_at = ?", (old, old))
    store.touch_session(tok, days=30)
    s = store.list_sessions(u["id"])[0]
    assert s["last_seen_at"] > old and s["expires_at"] > old
    seen = s["last_seen_at"]
    store.touch_session(tok, days=30)            # within the hour → unchanged
    assert store.list_sessions(u["id"])[0]["last_seen_at"] == seen


def test_delete_user_cascades_sessions(store):
    u = store.create("mitja", "test123!")
    tok = store.create_session(u["id"])
    store.delete(u["id"])
    assert store.get(u["id"]) is None and store.resolve_session(tok) is None


def test_invites_lifecycle(store):
    admin = store.create("admin", "test123!", role="admin")
    tok = store.create_invite(admin["id"], note="Anna", role="user", days=7)
    inv = store.get_invite(tok)
    assert inv["note"] == "Anna" and inv["role"] == "user" and inv["reset_user_id"] is None and inv["used_at"] is None
    assert store.get_invite("nope") is None
    anna = store.create("anna", "test123!", invited_by=admin["id"])
    store.use_invite(tok, anna["id"])
    assert store.get_invite(tok) is None                       # used → no longer valid
    rows = store.list_invites()
    assert rows[0]["used_by_username"] == "anna" and rows[0]["created_by_username"] == "admin"
    tok2 = store.create_invite(admin["id"], note="Bob")
    assert store.revoke_invite(token_hash(tok2)) is True and store.get_invite(tok2) is None
    assert store.revoke_invite("nope") is False
    tok3 = store.create_invite(admin["id"], note="alt", days=0)   # expires immediately
    assert store.get_invite(tok3) is None
    reset = store.create_invite(admin["id"], note="Reset anna", reset_user_id=anna["id"])
    assert store.get_invite(reset)["reset_user_id"] == anna["id"]
```

`tests/test_store_events.py`:

```python
"""redat/store/events.py — append-only usage events and the dashboard statistics."""
from datetime import datetime, timedelta, timezone

import pytest

from redat.store.events import EventStore
from redat.store.users import UserStore


@pytest.fixture
def stores(tmp_path):
    db = tmp_path / "redat.db"
    u, e = UserStore(db), EventStore(db)
    u.init(); e.init(); e.init()
    return u, e


def _backdate(e: EventStore, event_id: int, days: int) -> None:
    ts = (datetime.now(timezone.utc) - timedelta(days=days)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    with e._connect() as con:
        con.execute("UPDATE events SET ts = ? WHERE id = ?", (ts, event_id))


def test_record_and_recent(stores):
    u, e = stores
    admin = u.create("admin", "test123!", role="admin")
    i = e.record("analyze", user_id=admin["id"], via="session", address="Am Käferberg 12, Bonn", lat=50.716, lon=7.075,
                 run_id="abc", extra={"ok": 26, "error": 0, "empty": 2}, ip="10.0.0.1")
    e.record("login_failed", extra={"username": "nobody"}, ip="10.0.0.2")
    r = e.recent(limit=10)
    assert [x["kind"] for x in r] == ["login_failed", "analyze"]              # newest first
    assert r[1]["id"] == i and r[1]["username"] == "admin" and r[1]["extra"] == {"ok": 26, "error": 0, "empty": 2}
    assert r[0]["username"] is None and r[0]["extra"] == {"username": "nobody"}


def test_stats_counts_windows_users_and_days(stores):
    u, e = stores
    a = u.create("admin", "test123!", role="admin")
    b = u.create("bob", "test123!")
    e.record("analyze", user_id=a["id"], address="x")
    old = e.record("analyze", user_id=a["id"], address="y")
    _backdate(e, old, 10)
    older = e.record("analyze", user_id=b["id"], address="z")
    _backdate(e, older, 40)
    e.record("pdf", user_id=b["id"], run_id="r1")
    e.record("permalink_view", run_id="r1")
    e.record("login", user_id=b["id"])
    s = e.stats(days=30)
    assert s["users_total"] == 2 and s["users_active_30d"] == 2
    assert s["analyses"] == {"7d": 1, "30d": 2, "total": 3}
    assert s["pdf_30d"] == 1 and s["views_30d"] == 1
    assert len(s["per_day"]) == 30 and s["per_day"][-1]["analyses"] == 1 and sum(d["analyses"] for d in s["per_day"]) == 2
    assert all(set(d) == {"date", "analyses"} for d in s["per_day"])
    by = {r["username"]: r for r in s["per_user"]}
    assert by["admin"]["analyses_total"] == 2 and by["admin"]["analyses_30d"] == 2 and by["admin"]["pdf_total"] == 0
    assert by["bob"]["analyses_total"] == 1 and by["bob"]["analyses_30d"] == 0 and by["bob"]["pdf_total"] == 1
    assert by["bob"]["last_active"] is not None and by["bob"]["role"] == "user" and by["bob"]["disabled"] is False


def test_prune(stores):
    u, e = stores
    keep = e.record("login")
    old = e.record("login")
    _backdate(e, old, 400)
    assert e.prune(days=365) == 1
    assert [x["id"] for x in e.recent()] == [keep]
```

`tests/test_store_runs.py` — add:

```python
def test_save_records_user_id_and_init_adds_the_column_to_old_databases(tmp_path):
    import sqlite3
    db = tmp_path / "redat.db"
    con = sqlite3.connect(db)
    con.executescript("""CREATE TABLE runs (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, address TEXT NOT NULL,
        formatted_address TEXT, latitude REAL NOT NULL, longitude REAL NOT NULL, precision TEXT, plot_size_m2 REAL,
        living_space_m2 REAL, sections_json TEXT NOT NULL);""")
    con.commit(); con.close()
    s = RunStore(db)
    s.init()                                                     # adds user_id to the pre-existing table
    rid = s.save({"address": "A", "latitude": 51.0, "longitude": 7.0, "sections": {}}, user_id=7)
    assert s.get(rid)["user_id"] == 7
    rid2 = s.save({"address": "B", "latitude": 51.0, "longitude": 7.0, "sections": {}})
    assert s.get(rid2)["user_id"] is None
```

(Use the file's existing import of `RunStore`.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest -q tests/test_auth_passwords.py tests/test_store_users.py tests/test_store_events.py tests/test_store_runs.py`
Expected: FAIL — `ModuleNotFoundError: redat.auth`, `redat.store.users`, `redat.store.events`; `TypeError: save() got an unexpected keyword argument 'user_id'`.

- [ ] **Step 3: `redat/auth/passwords.py` and `redat/auth/tokens.py`**

`redat/auth/__init__.py`: `"""Authentication: passwords, tokens, principal resolution, CSRF, login throttle."""`

```python
"""Password hashing with the standard library (scrypt) — no external dependency.

Format `scrypt$<n>$<r>$<p>$<salt b64>$<hash b64>`; the parameters are parsed on verify so they can be raised
later without invalidating stored hashes. 2^15/8/1 needs ~34 MB per hash (OpenSSL's default maxmem is 32 MB,
hence the explicit `maxmem`).
"""
from __future__ import annotations

import base64
import hashlib
import secrets

MIN_LEN, MAX_LEN = 8, 200
_N, _R, _P, _DKLEN, _SALT_LEN = 2 ** 15, 8, 1, 32, 16
_MAXMEM = 128 * 1024 * 1024


class PasswordPolicyError(ValueError):
    pass


def check_policy(password: str) -> None:
    if not isinstance(password, str) or len(password) < MIN_LEN:
        raise PasswordPolicyError(f"Das Passwort muss mindestens {MIN_LEN} Zeichen lang sein.")
    if len(password) > MAX_LEN:
        raise PasswordPolicyError(f"Das Passwort darf höchstens {MAX_LEN} Zeichen lang sein.")


def _derive(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=_DKLEN, maxmem=_MAXMEM)


def hash_password(password: str, *, n: int = _N, r: int = _R, p: int = _P) -> str:
    check_policy(password)
    salt = secrets.token_bytes(_SALT_LEN)
    dk = _derive(password, salt, n, r, p)
    return "$".join(("scrypt", str(n), str(r), str(p), base64.b64encode(salt).decode("ascii"), base64.b64encode(dk).decode("ascii")))


def verify_password(password: str, stored) -> bool:
    """Constant-time check; any malformed stored value is simply False."""
    try:
        algo, n, r, p, salt_b64, hash_b64 = str(stored).split("$")
        if algo != "scrypt":
            return False
        salt, expected = base64.b64decode(salt_b64, validate=True), base64.b64decode(hash_b64, validate=True)
        dk = _derive(str(password), salt, int(n), int(r), int(p))
    except (ValueError, TypeError, AttributeError):
        return False
    return secrets.compare_digest(dk, expected)
```

```python
"""Opaque random tokens for sessions and invites; only their sha256 is stored."""
import hashlib
import secrets


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()
```

- [ ] **Step 4: `redat/store/users.py`**

```python
"""Users, sessions and invites in redat.db (same file as runs and the section cache; WAL mode).

Usernames are lowercase `[a-z0-9._-]{3,32}`. Tokens (sessions, invites) are stored as sha256 only. Sessions
carry a sliding expiry: `touch_session` moves `last_seen_at`/`expires_at` at most once per hour. Every method is
one short transaction; the store is safe to share between the app and `scripts/users.py`.
"""
from __future__ import annotations

import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator, Optional

from redat.auth.passwords import hash_password
from redat.auth.tokens import new_token, token_hash

USERNAME_RE = re.compile(r"^[a-z0-9._-]{3,32}$")
_TOUCH_INTERVAL = timedelta(hours=1)

_DDL = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'user',
  created_at TEXT NOT NULL,
  disabled_at TEXT,
  last_login_at TEXT,
  invited_by INTEGER
);
CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  user_agent TEXT NOT NULL DEFAULT '',
  ip TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id);
CREATE TABLE IF NOT EXISTS invites (
  token_hash TEXT PRIMARY KEY,
  created_by INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  note TEXT NOT NULL DEFAULT '',
  role TEXT NOT NULL DEFAULT 'user',
  reset_user_id INTEGER,
  used_at TEXT,
  used_by INTEGER
);
"""
_USER_COLS = ("id", "username", "role", "created_at", "disabled_at", "last_login_at", "invited_by")


class UsernameTakenError(ValueError):
    pass


class InvalidUsernameError(ValueError):
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _in_days(days: float) -> str:
    return _iso(datetime.now(timezone.utc) + timedelta(days=days))


def public_user(row) -> dict:
    return {k: row[k] for k in _USER_COLS}


class UserStore:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        con = sqlite3.connect(self.db_path, timeout=10)
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def init(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as con:
            con.execute("PRAGMA journal_mode=WAL")
            con.executescript(_DDL)

    # ---- users
    def count(self) -> int:
        with self._connect() as con:
            return int(con.execute("SELECT COUNT(*) FROM users").fetchone()[0])

    def create(self, username: str, password: str, role: str = "user", invited_by: Optional[int] = None) -> dict:
        name = (username or "").strip().lower()
        if not USERNAME_RE.match(name):
            raise InvalidUsernameError("Benutzername: 3–32 Zeichen aus a–z, 0–9, Punkt, Bindestrich, Unterstrich.")
        if role not in ("user", "admin"):
            raise ValueError(f"unknown role {role!r}")
        h = hash_password(password)
        with self._connect() as con:
            try:
                cur = con.execute("INSERT INTO users (username, password_hash, role, created_at, invited_by) VALUES (?, ?, ?, ?, ?)",
                                  (name, h, role, now_iso(), invited_by))
            except sqlite3.IntegrityError as exc:
                raise UsernameTakenError("Dieser Benutzername ist bereits vergeben.") from exc
            row = con.execute("SELECT * FROM users WHERE id = ?", (cur.lastrowid,)).fetchone()
        return public_user(row)

    def get(self, user_id: int) -> Optional[dict]:
        with self._connect() as con:
            row = con.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return public_user(row) if row else None

    def get_by_username(self, username: str) -> Optional[dict]:
        """Full row incl. password_hash — for login only."""
        with self._connect() as con:
            row = con.execute("SELECT * FROM users WHERE username = ?", ((username or "").strip().lower(),)).fetchone()
        return dict(row) if row else None

    def list_users(self) -> list[dict]:
        with self._connect() as con:
            rows = con.execute("SELECT * FROM users ORDER BY id").fetchall()
        return [public_user(r) for r in rows]

    def set_password(self, user_id: int, password: str) -> None:
        h = hash_password(password)
        with self._connect() as con:
            con.execute("UPDATE users SET password_hash = ? WHERE id = ?", (h, user_id))

    def set_disabled(self, user_id: int, disabled: bool) -> None:
        with self._connect() as con:
            con.execute("UPDATE users SET disabled_at = ? WHERE id = ?", (now_iso() if disabled else None, user_id))
            if disabled:
                con.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))

    def delete(self, user_id: int) -> None:
        with self._connect() as con:
            con.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
            con.execute("DELETE FROM users WHERE id = ?", (user_id,))

    def touch_login(self, user_id: int) -> None:
        with self._connect() as con:
            con.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (now_iso(), user_id))

    # ---- sessions
    def create_session(self, user_id: int, *, user_agent: str = "", ip: str = "", days: float = 30) -> str:
        tok = new_token()
        now = now_iso()
        with self._connect() as con:
            con.execute("INSERT INTO sessions (token_hash, user_id, created_at, last_seen_at, expires_at, user_agent, ip) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (token_hash(tok), user_id, now, now, _in_days(days), (user_agent or "")[:200], ip or ""))
        return tok

    def resolve_session(self, token: str) -> Optional[dict]:
        """The session's user (public columns + session_token_hash/session_last_seen_at), or None (expired, unknown, disabled → row deleted)."""
        th = token_hash(token)
        with self._connect() as con:
            row = con.execute("SELECT u.*, s.token_hash AS session_token_hash, s.last_seen_at AS session_last_seen_at, s.expires_at AS session_expires_at "
                              "FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token_hash = ?", (th,)).fetchone()
            if row is None:
                return None
            if row["session_expires_at"] <= now_iso() or row["disabled_at"] is not None:
                con.execute("DELETE FROM sessions WHERE token_hash = ?", (th,))
                return None
        out = public_user(row)
        out["session_token_hash"], out["session_last_seen_at"] = row["session_token_hash"], row["session_last_seen_at"]
        return out

    def touch_session(self, token: str, days: float = 30) -> None:
        th = token_hash(token)
        with self._connect() as con:
            row = con.execute("SELECT last_seen_at FROM sessions WHERE token_hash = ?", (th,)).fetchone()
            if row is None:
                return
            seen = datetime.fromisoformat(row["last_seen_at"].replace("Z", "+00:00"))
            if datetime.now(timezone.utc) - seen < _TOUCH_INTERVAL:
                return
            con.execute("UPDATE sessions SET last_seen_at = ?, expires_at = ? WHERE token_hash = ?", (now_iso(), _in_days(days), th))

    def delete_session(self, token: str) -> None:
        with self._connect() as con:
            con.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash(token),))

    def delete_user_sessions(self, user_id: int, keep_token: Optional[str] = None) -> int:
        with self._connect() as con:
            if keep_token:
                cur = con.execute("DELETE FROM sessions WHERE user_id = ? AND token_hash != ?", (user_id, token_hash(keep_token)))
            else:
                cur = con.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
            return cur.rowcount

    def list_sessions(self, user_id: int) -> list[dict]:
        with self._connect() as con:
            rows = con.execute("SELECT token_hash, created_at, last_seen_at, expires_at, user_agent, ip FROM sessions WHERE user_id = ? ORDER BY last_seen_at DESC", (user_id,)).fetchall()
        return [dict(r) for r in rows]

    # ---- invites
    def create_invite(self, created_by: int, *, note: str = "", role: str = "user", reset_user_id: Optional[int] = None, days: float = 7) -> str:
        tok = new_token()
        with self._connect() as con:
            con.execute("INSERT INTO invites (token_hash, created_by, created_at, expires_at, note, role, reset_user_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (token_hash(tok), created_by, now_iso(), _in_days(days), (note or "")[:80], role, reset_user_id))
        return tok

    def get_invite(self, token: str) -> Optional[dict]:
        """A still-valid invite (unused, unexpired) or None."""
        with self._connect() as con:
            row = con.execute("SELECT * FROM invites WHERE token_hash = ?", (token_hash(token),)).fetchone()
        if row is None or row["used_at"] is not None or row["expires_at"] <= now_iso():
            return None
        return dict(row)

    def use_invite(self, token: str, used_by: int) -> None:
        with self._connect() as con:
            con.execute("UPDATE invites SET used_at = ?, used_by = ? WHERE token_hash = ?", (now_iso(), used_by, token_hash(token)))

    def list_invites(self) -> list[dict]:
        with self._connect() as con:
            rows = con.execute("SELECT i.*, c.username AS created_by_username, u.username AS used_by_username, r.username AS reset_username "
                               "FROM invites i LEFT JOIN users c ON c.id = i.created_by LEFT JOIN users u ON u.id = i.used_by "
                               "LEFT JOIN users r ON r.id = i.reset_user_id ORDER BY i.created_at DESC").fetchall()
        now = now_iso()
        out = []
        for r in rows:
            d = dict(r)
            d["status"] = "verwendet" if d["used_at"] else ("abgelaufen" if d["expires_at"] <= now else "offen")
            out.append(d)
        return out

    def revoke_invite(self, th: str) -> bool:
        with self._connect() as con:
            return con.execute("DELETE FROM invites WHERE token_hash = ? AND used_at IS NULL", (th,)).rowcount > 0
```

- [ ] **Step 5: `redat/store/events.py`**

```python
"""Append-only usage events (who did what, when) and the admin dashboard statistics.

Same redat.db as users/runs; `stats()` joins `users` for the per-user table. Nothing is deleted automatically —
`scripts/users.py prune-events --days N` calls `prune()`.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator, Optional

_DDL = """
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  kind TEXT NOT NULL,
  user_id INTEGER,
  via TEXT,
  address TEXT,
  lat REAL,
  lon REAL,
  run_id TEXT,
  extra TEXT,
  ip TEXT
);
CREATE INDEX IF NOT EXISTS events_ts ON events(ts);
CREATE INDEX IF NOT EXISTS events_user_kind ON events(user_id, kind);
"""
KINDS = ("login", "logout", "login_failed", "invite_created", "invite_accepted", "password_changed", "password_reset",
         "analyze", "pdf", "permalink_view")


def _iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _ago(days: int) -> str:
    return _iso(datetime.now(timezone.utc) - timedelta(days=days))


class EventStore:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        con = sqlite3.connect(self.db_path, timeout=10)
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def init(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as con:
            con.execute("PRAGMA journal_mode=WAL")
            con.executescript(_DDL)

    def record(self, kind: str, *, user_id: Optional[int] = None, via: Optional[str] = None, address: Optional[str] = None,
               lat: Optional[float] = None, lon: Optional[float] = None, run_id: Optional[str] = None,
               extra: Optional[dict] = None, ip: Optional[str] = None) -> int:
        with self._connect() as con:
            cur = con.execute("INSERT INTO events (ts, kind, user_id, via, address, lat, lon, run_id, extra, ip) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                              (_iso(datetime.now(timezone.utc)), kind, user_id, via, address, lat, lon, run_id,
                               json.dumps(extra, ensure_ascii=False) if extra is not None else None, ip))
            return int(cur.lastrowid)

    def recent(self, limit: int = 50) -> list[dict]:
        with self._connect() as con:
            rows = con.execute("SELECT e.*, u.username FROM events e LEFT JOIN users u ON u.id = e.user_id ORDER BY e.id DESC LIMIT ?", (limit,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["extra"] = json.loads(d["extra"]) if d["extra"] else None
            out.append(d)
        return out

    def stats(self, days: int = 30) -> dict:
        since_7, since_n = _ago(7), _ago(days)
        with self._connect() as con:
            q = lambda sql, *a: con.execute(sql, a).fetchone()[0]  # noqa: E731
            users_total = q("SELECT COUNT(*) FROM users")
            users_active = q("SELECT COUNT(DISTINCT user_id) FROM events WHERE user_id IS NOT NULL AND ts >= ?", since_n)
            analyses = {"7d": q("SELECT COUNT(*) FROM events WHERE kind = 'analyze' AND ts >= ?", since_7),
                        "30d": q("SELECT COUNT(*) FROM events WHERE kind = 'analyze' AND ts >= ?", since_n),
                        "total": q("SELECT COUNT(*) FROM events WHERE kind = 'analyze'")}
            pdf_n = q("SELECT COUNT(*) FROM events WHERE kind = 'pdf' AND ts >= ?", since_n)
            views_n = q("SELECT COUNT(*) FROM events WHERE kind = 'permalink_view' AND ts >= ?", since_n)
            per_day_rows = con.execute("SELECT substr(ts, 1, 10) AS d, COUNT(*) AS n FROM events WHERE kind = 'analyze' AND ts >= ? GROUP BY d", (since_n,)).fetchall()
            per_user_rows = con.execute(
                "SELECT u.id, u.username, u.role, u.disabled_at, "
                "  SUM(CASE WHEN e.kind = 'analyze' THEN 1 ELSE 0 END) AS analyses_total, "
                "  SUM(CASE WHEN e.kind = 'analyze' AND e.ts >= ? THEN 1 ELSE 0 END) AS analyses_30d, "
                "  SUM(CASE WHEN e.kind = 'pdf' THEN 1 ELSE 0 END) AS pdf_total, "
                "  MAX(e.ts) AS last_active "
                "FROM users u LEFT JOIN events e ON e.user_id = u.id GROUP BY u.id ORDER BY u.id", (since_n,)).fetchall()
        counts = {r["d"]: int(r["n"]) for r in per_day_rows}
        today = datetime.now(timezone.utc).date()
        per_day = [{"date": (today - timedelta(days=i)).isoformat(), "analyses": counts.get((today - timedelta(days=i)).isoformat(), 0)}
                   for i in range(days - 1, -1, -1)]
        per_user = [{"user_id": r["id"], "username": r["username"], "role": r["role"], "disabled": r["disabled_at"] is not None,
                     "analyses_total": int(r["analyses_total"] or 0), "analyses_30d": int(r["analyses_30d"] or 0),
                     "pdf_total": int(r["pdf_total"] or 0), "last_active": r["last_active"]} for r in per_user_rows]
        return {"days": days, "users_total": int(users_total), "users_active_30d": int(users_active), "analyses": analyses,
                "pdf_30d": int(pdf_n), "views_30d": int(views_n), "per_day": per_day, "per_user": per_user}

    def prune(self, days: int) -> int:
        with self._connect() as con:
            return con.execute("DELETE FROM events WHERE ts < ?", (_ago(days),)).rowcount
```

- [ ] **Step 6: `redat/store/runs.py`**

In `init()`, after `executescript(_DDL)`:

```python
            cols = {r[1] for r in con.execute("PRAGMA table_info(runs)").fetchall()}
            if "user_id" not in cols:
                con.execute("ALTER TABLE runs ADD COLUMN user_id INTEGER")
```

`save(self, payload: dict, user_id: Optional[int] = None) -> str`: append `user_id` to the INSERT (`INSERT INTO runs (id, created_at, …, sections_json, user_id) VALUES (…)` with one more placeholder and `row + [user_id]`). `get()` already returns every column.

- [ ] **Step 7: Run the suite, commit**

Run: `.venv/bin/python -m pytest -q` → green (735 + new).

```bash
git add redat/auth redat/store/users.py redat/store/events.py redat/store/runs.py tests/test_auth_passwords.py tests/test_store_users.py tests/test_store_events.py tests/test_store_runs.py
git commit -m "feat(auth): user, session, invite and usage-event stores with scrypt passwords"
```

---

### Task 2: Principal resolution, gating, settings, bootstrap admin, test login helper

**Files:**
- Create: `redat/auth/principal.py`, `redat/auth/throttle.py`, `tests/helpers_auth.py`, `tests/test_auth_principal.py`, `tests/test_auth_throttle.py`
- Modify: `redat/api/auth.py`, `redat/api/v1.py`, `redat/app.py`, `redat/settings.py`, `.env.example`, `tests/conftest.py`, `tests/test_api_auth.py`, `tests/test_api_v1.py`, `tests/test_web_pages.py`, `tests/test_app.py`, `tests/test_settings.py`
- Test: as listed

**Interfaces:**
- Consumes: Task 1 stores.
- Produces: `Principal(user, role, via)` with `.username`, `.user_id`, `.is_admin`; `SESSION_COOKIE = "redat_session"`, `CSRF_COOKIE = "redat_csrf"`; `client_ip(request)`, `current_principal(request) -> Principal | None`, `require_principal`, `require_session_user`, `require_admin` (FastAPI dependencies raising 401/403), `page_principal` (303 → `/login?next=…`), `optional_principal`, `safe_next(value) -> str`, `session_cookie_kwargs(settings) -> dict`; `throttle.LoginThrottle` with module instance `login_throttle`; `Settings.session_days`, `Settings.bootstrap_admin_password`, `Settings.cookie_secure`; `app.state.users`, `app.state.events`; `redat.app.bootstrap_admin(users, settings) -> bool`; `tests.helpers_auth.login(client, *, username="tester", role="user", password="test123!") -> dict` (creates the user if missing, a session, sets the cookie; returns the user dict) and `csrf(client) -> str` (Task 3 uses it).

- [ ] **Step 1: Write the failing tests**

`tests/helpers_auth.py`:

```python
"""Log a TestClient in without going through the login page: create the user + session via the stores."""
from redat.auth.principal import CSRF_COOKIE, SESSION_COOKIE


def login(client, *, username="tester", role="user", password="test123!") -> dict:
    users = client.app.state.users
    user = users.get_by_username(username)
    if user is None:
        user = users.create(username, password, role=role)
    token = users.create_session(user["id"], user_agent="pytest", ip="testclient")
    client.cookies.set(SESSION_COOKIE, token)
    return users.get(user["id"])


def csrf(client) -> str:
    """The double-submit token: read the cookie the app set, or plant one."""
    tok = client.cookies.get(CSRF_COOKIE)
    if not tok:
        tok = "test-csrf-token-0123456789abcdef"
        client.cookies.set(CSRF_COOKIE, tok)
    return tok
```

`tests/conftest.py` — inside `_redat_env` add `monkeypatch.delenv("REDAT_BOOTSTRAP_ADMIN_PASSWORD", raising=False)` and `monkeypatch.delenv("REDAT_SESSION_DAYS", raising=False)`.

`tests/test_auth_throttle.py`:

```python
from redat.auth.throttle import LoginThrottle


def test_locks_after_five_failures_and_clears_on_success():
    t = LoginThrottle(max_failures=5, window_s=600, lock_s=60, clock=lambda: 1000.0)
    key = ("10.0.0.1", "admin")
    for _ in range(4):
        t.failure(key)
    assert t.check(key) is None
    t.failure(key)
    assert 0 < t.check(key) <= 60
    t.success(key)
    assert t.check(key) is None


def test_lock_expires_and_window_is_sliding():
    now = [1000.0]
    t = LoginThrottle(max_failures=2, window_s=100, lock_s=30, clock=lambda: now[0])
    key = ("ip", "u")
    t.failure(key); t.failure(key)
    assert t.check(key) == 30
    now[0] += 31
    assert t.check(key) is None
    t.failure(key)                      # the two old failures are outside the window now? one is within 100 s
    now[0] += 200
    t.failure(key)
    assert t.check(key) is None         # only one failure inside the window
```

`tests/test_auth_principal.py`:

```python
"""Gating: session cookie or X-Api-Key for the API, 303 → /login for pages, public permalinks, admin role."""
import pytest
from fastapi.testclient import TestClient

from redat.auth.principal import SESSION_COOKIE, safe_next
from tests.helpers_auth import login


@pytest.fixture
def client():
    from redat.app import create_app
    with TestClient(create_app(), follow_redirects=False) as c:
        yield c


def test_api_requires_a_principal(client):
    r = client.get("/api/v1/sections")
    assert r.status_code == 401 and r.json()["detail"] == "Anmeldung erforderlich"


def test_session_cookie_grants_access(client):
    login(client)
    assert client.get("/api/v1/sections").status_code == 200


def test_api_key_is_still_a_credential(client, monkeypatch):
    from redat import settings as s
    monkeypatch.setenv("REDAT_API_KEY", "geheim-123")
    s.reset_settings()
    assert client.get("/api/v1/sections", headers={"X-Api-Key": "geheim-123"}).status_code == 200
    assert client.get("/api/v1/sections", headers={"X-Api-Key": "falsch"}).status_code == 401
    assert client.get("/api/v1/sections").status_code == 401


def test_unknown_expired_or_disabled_session_is_rejected(client):
    client.cookies.set(SESSION_COOKIE, "not-a-session")
    assert client.get("/api/v1/sections").status_code == 401
    u = login(client, username="anna")
    client.app.state.users.set_disabled(u["id"], True)
    assert client.get("/api/v1/sections").status_code == 401
    assert client.app.state.users.list_sessions(u["id"]) == []


def test_pages_redirect_to_login_with_next(client):
    r = client.get("/?address=Musterstr")
    assert r.status_code == 303 and r.headers["location"] == "/login?next=%2F%3Faddress%3DMusterstr"
    assert client.get("/docs").status_code in (303, 401)
    login(client)
    assert client.get("/").status_code == 200


def test_public_routes_need_no_login(client):
    assert client.get("/healthz").status_code == 200
    assert client.get("/quellen").status_code == 200
    assert client.get("/a/nope").status_code == 404
    assert client.get("/api/v1/run/nope").status_code == 404           # public: 404, not 401
    assert client.get("/api/v1/run/nope/report.pdf").status_code == 404
    assert client.get("/login").status_code == 200


def test_admin_routes_need_the_admin_role(client):
    assert client.get("/admin").status_code == 303
    login(client, username="bob")
    assert client.get("/admin").status_code == 403
    login(client, username="root", role="admin")
    assert client.get("/admin").status_code == 200


def test_safe_next():
    assert safe_next("/a/xyz?x=1") == "/a/xyz?x=1"
    for bad in ("", None, "https://evil.example", "//evil.example", "javascript:alert(1)", "/login"):
        assert safe_next(bad) == "/"
```

(`/admin` returns 200 only once Task 4 adds the page; until then the last assertion may be 404 — write the test as `assert client.get("/admin").status_code != 403` for this task and tighten it to `== 200` in Task 4. `/login` 200 requires Task 3 — in this task assert `client.get("/login").status_code in (200, 404)` and tighten in Task 3.)

`tests/test_settings.py` — add:

```python
def test_session_and_bootstrap_settings(tmp_path):
    from redat.settings import load_settings
    s = load_settings({"GEOAPIFY_API_KEY": "k", "REDAT_SESSION_DAYS": "7", "REDAT_BOOTSTRAP_ADMIN_PASSWORD": "test123!",
                       "REDAT_PUBLIC_URL": "https://redat.example"}, yaml_path=None)
    assert s.session_days == 7 and s.bootstrap_admin_password == "test123!" and s.cookie_secure is True
    s2 = load_settings({"GEOAPIFY_API_KEY": "k", "REDAT_PUBLIC_URL": "http://192.168.1.2:8200"}, yaml_path=None)
    assert s2.session_days == 30 and s2.bootstrap_admin_password is None and s2.cookie_secure is False
```

`tests/test_app.py` — add:

```python
def test_bootstrap_admin_only_when_no_users(monkeypatch, tmp_path):
    from redat import settings as s
    monkeypatch.setenv("REDAT_BOOTSTRAP_ADMIN_PASSWORD", "test123!")
    s.reset_settings()
    from redat.app import create_app
    app = create_app()
    u = app.state.users.get_by_username("admin")
    assert u and u["role"] == "admin"
    app.state.users.set_password(u["id"], "geaendert99")
    create_app()                                          # second start: no reset, no duplicate
    from redat.auth.passwords import verify_password
    assert verify_password("geaendert99", app.state.users.get_by_username("admin")["password_hash"])
    assert app.state.users.count() == 1
```

Existing fixtures: in `tests/test_api_v1.py::client` and `tests/test_web_pages.py::client` (and any other fixture constructing a `TestClient` for gated routes, e.g. `tests/test_app.py`, `tests/test_api_auth.py`) call `login(c)` after entering the `with TestClient(...)` block, before `yield c`. `tests/test_api_auth.py` tests of the old `require_api_key` semantics ("no key configured → open") are rewritten: with no key configured and no session → 401; with key configured → the header works. Keep its non-ASCII-header test (must be a clean 401, never 500).

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest -q tests/test_auth_principal.py tests/test_auth_throttle.py tests/test_settings.py tests/test_app.py`
Expected: FAIL — `ModuleNotFoundError: redat.auth.principal`, `tests.helpers_auth`; `AttributeError: session_days`.

- [ ] **Step 3: `redat/settings.py`, `.env.example`**

`Settings` gains `session_days: int = 30` and `bootstrap_admin_password: Optional[str] = None` (dataclass fields with defaults, after `section_timeouts`) and

```python
    @property
    def cookie_secure(self) -> bool:
        return self.public_url.lower().startswith("https://")
```

`load_settings` passes `session_days=_int(env, "REDAT_SESSION_DAYS", 30)` and `bootstrap_admin_password=(env.get("REDAT_BOOTSTRAP_ADMIN_PASSWORD") or "").strip() or None`. `.env.example` gains:

```
# First start only: creates the user "admin" with this password when the users table is empty. Change it after login.
REDAT_BOOTSTRAP_ADMIN_PASSWORD=
# Session lifetime in days (sliding); default 30
#REDAT_SESSION_DAYS=30
```

- [ ] **Step 4: `redat/auth/throttle.py`**

```python
"""In-memory login throttle: 5 failures per (client IP, username) within 10 minutes → 60 s lock."""
from __future__ import annotations

import threading
import time
from typing import Callable, Optional


class LoginThrottle:
    def __init__(self, max_failures: int = 5, window_s: int = 600, lock_s: int = 60, clock: Callable[[], float] = time.monotonic):
        self.max_failures, self.window_s, self.lock_s, self._clock = max_failures, window_s, lock_s, clock
        self._failures: dict[tuple, list[float]] = {}
        self._locked_until: dict[tuple, float] = {}
        self._lock = threading.Lock()

    def check(self, key: tuple) -> Optional[int]:
        """Seconds the key stays locked, or None when a login attempt may proceed."""
        with self._lock:
            until = self._locked_until.get(key)
            if until is None:
                return None
            remaining = until - self._clock()
            if remaining <= 0:
                del self._locked_until[key]
                self._failures.pop(key, None)
                return None
            return max(1, int(round(remaining)))

    def failure(self, key: tuple) -> None:
        now = self._clock()
        with self._lock:
            hits = [t for t in self._failures.get(key, []) if now - t < self.window_s] + [now]
            self._failures[key] = hits
            if len(hits) >= self.max_failures:
                self._locked_until[key] = now + self.lock_s
                self._failures[key] = []

    def success(self, key: tuple) -> None:
        with self._lock:
            self._failures.pop(key, None)
            self._locked_until.pop(key, None)


login_throttle = LoginThrottle()
```

- [ ] **Step 5: `redat/auth/principal.py`**

```python
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
    if not v.startswith("/") or v.startswith("//") or v.startswith("/login"):
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
```

(`HTTPException(status_code=303, headers=…)` is delivered by FastAPI as a 303 with the Location header and a JSON body; browsers follow it. Verify with the test.)

- [ ] **Step 6: `redat/api/auth.py`, `redat/api/v1.py`, `redat/app.py`**

`redat/api/auth.py` becomes a two-line shim: docstring "Kept for imports; the credential logic lives in redat.auth.principal." and `from redat.auth.principal import require_principal  # noqa: F401`.

`redat/api/v1.py`: `from redat.auth.principal import require_principal`; `router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_principal)])` and a second `public_router = APIRouter(prefix="/api/v1")`; move `api_get_run` and `api_run_report` (and `_get_run_or_404`, `_pdf` stay shared) onto `public_router`. Module docstring: which two routes are public and why (permalinks).

`redat/app.py`: after `app.state.cache = build_cache(settings)`:

```python
    from redat.store.events import EventStore
    from redat.store.users import UserStore
    app.state.users = UserStore(settings.db_path)
    app.state.users.init()
    app.state.events = EventStore(settings.db_path)
    app.state.events.init()
    bootstrap_admin(app.state.users, settings)
```

and include `public_router` next to `api_router`. Add at module level:

```python
def bootstrap_admin(users, settings) -> bool:
    """First start: create `admin` from REDAT_BOOTSTRAP_ADMIN_PASSWORD when the users table is empty."""
    if users.count() > 0 or not settings.bootstrap_admin_password:
        return False
    users.create("admin", settings.bootstrap_admin_password, role="admin")
    log.warning("bootstrap: user 'admin' created from REDAT_BOOTSTRAP_ADMIN_PASSWORD — change the password after the first login")
    return True
```

Gate the OpenAPI docs: create the app with `docs_url=None, redoc_url=None, openapi_url=None` and register them on a small router with `dependencies=[Depends(page_principal)]`:

```python
    from fastapi.openapi.docs import get_swagger_ui_html
    from fastapi.responses import JSONResponse

    @app.get("/openapi.json", include_in_schema=False, dependencies=[Depends(page_principal)])
    def openapi_json():
        return JSONResponse(app.openapi())

    @app.get("/docs", include_in_schema=False, dependencies=[Depends(page_principal)])
    def docs():
        return get_swagger_ui_html(openapi_url="/openapi.json", title="NRW-REDAT API")
```

`redat/web/pages.py`: `index` and `stored_run`/`quellen` get their dependencies in Task 3 (this task only needs `/` to redirect): add `principal: Principal = Depends(page_principal)` to `index` now (import from `redat.auth.principal`); leave `stored_run`, `quellen` public.

- [ ] **Step 7: Suite, commit**

Run: `.venv/bin/python -m pytest -q` → green.

```bash
git add redat/auth redat/api redat/app.py redat/settings.py redat/web/pages.py .env.example tests/
git commit -m "feat(auth): principal resolution — session cookie or API key; pages redirect to /login; bootstrap admin"
```

---

### Task 3: Login, logout, invite acceptance, account page, navigation, CSRF

**Files:**
- Create: `redat/auth/csrf.py`, `redat/web/auth_pages.py`, `redat/templates/login.html`, `redat/templates/invite.html`, `redat/templates/konto.html`, `tests/test_auth_pages.py`
- Modify: `redat/web/pages.py` (`_render` with principal/CSRF/no-store; `stored_run`, `quellen` use `optional_principal`), `redat/templates/base.html` (navigation, footer), `redat/app.py` (include the auth router), `tests/test_auth_principal.py` (tighten `/login` to 200), `tests/test_web_pages.py` (nav assertions)
- Test: `tests/test_auth_pages.py`

**Interfaces:**
- Consumes: Task 1 stores, Task 2 principal/cookies/throttle, `tests.helpers_auth.login/csrf`.
- Produces: `csrf.ensure_csrf(request) -> str` (token from cookie or a fresh one flagged on `request.state.csrf_new`), `csrf.check_csrf(request, submitted)` (403 "Ungültiges Formular-Token (CSRF). Bitte Seite neu laden."), `pages._render(request, name, ctx, status_code=200, no_store=False)` adding `principal`, `csrf_token` to every template context and setting the CSRF cookie when new; routes `GET/POST /login`, `POST /logout`, `GET/POST /invite/{token}`, `GET /konto`, `POST /konto/password`, `POST /konto/logout-others`.

- [ ] **Step 1: Write the failing tests** (`tests/test_auth_pages.py`)

```python
"""Login / logout / invite / account pages — hermetic TestClient flows."""
import pytest
from fastapi.testclient import TestClient

from redat.auth.principal import CSRF_COOKIE, SESSION_COOKIE
from tests.helpers_auth import csrf, login


@pytest.fixture
def client():
    from redat.app import create_app
    with TestClient(create_app(), follow_redirects=False) as c:
        yield c


def _admin(client):
    return client.app.state.users.create("admin", "test123!", role="admin")


def test_login_page_sets_csrf_cookie_and_states_the_recording(client):
    r = client.get("/login")
    assert r.status_code == 200 and 'name="csrf"' in r.text and "aufgezeichnet" in r.text
    assert CSRF_COOKIE in r.cookies and r.headers["cache-control"] == "no-store"


def test_login_needs_matching_csrf(client):
    _admin(client)
    client.get("/login")
    r = client.post("/login", data={"username": "admin", "password": "test123!", "csrf": "wrong"})
    assert r.status_code == 403


def test_wrong_password_is_401_and_recorded(client):
    _admin(client)
    r = client.post("/login", data={"username": "admin", "password": "nope", "csrf": csrf(client)})
    assert r.status_code == 401 and "Benutzername oder Passwort falsch" in r.text
    ev = client.app.state.events.recent(5)
    assert ev[0]["kind"] == "login_failed" and ev[0]["extra"] == {"username": "admin"}


def test_login_sets_session_cookie_and_redirects_to_next(client):
    _admin(client)
    r = client.post("/login", data={"username": "Admin", "password": "test123!", "csrf": csrf(client), "next": "/a/xyz"})
    assert r.status_code == 303 and r.headers["location"] == "/a/xyz"
    cookie = r.headers.get("set-cookie", "")
    assert SESSION_COOKIE in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie.replace("SameSite=Lax", "SameSite=lax")
    assert client.get("/api/v1/sections").status_code == 200
    assert client.app.state.events.recent(1)[0]["kind"] == "login"
    assert client.app.state.users.get_by_username("admin")["last_login_at"] is not None


def test_open_redirects_are_neutralised(client):
    _admin(client)
    r = client.post("/login", data={"username": "admin", "password": "test123!", "csrf": csrf(client), "next": "https://evil.example"})
    assert r.headers["location"] == "/"


def test_disabled_user_cannot_log_in(client):
    u = _admin(client)
    client.app.state.users.set_disabled(u["id"], True)
    r = client.post("/login", data={"username": "admin", "password": "test123!", "csrf": csrf(client)})
    assert r.status_code == 401


def test_five_failures_lock_the_account_for_a_minute(client):
    from redat.auth import throttle as th
    th.login_throttle.__init__()                      # fresh throttle for this test
    _admin(client)
    for _ in range(5):
        client.post("/login", data={"username": "admin", "password": "nope", "csrf": csrf(client)})
    r = client.post("/login", data={"username": "admin", "password": "test123!", "csrf": csrf(client)})
    assert r.status_code == 429 and "Zu viele Fehlversuche" in r.text
    th.login_throttle.__init__()


def test_logout_deletes_the_session(client):
    u = login(client)
    r = client.post("/logout", data={"csrf": csrf(client)})
    assert r.status_code == 303 and r.headers["location"] == "/login"
    assert client.app.state.users.list_sessions(u["id"]) == []
    assert client.get("/api/v1/sections").status_code == 401


def test_invite_flow_creates_user_and_logs_in(client):
    admin = _admin(client)
    tok = client.app.state.users.create_invite(admin["id"], note="Anna", role="user")
    r = client.get(f"/invite/{tok}")
    assert r.status_code == 200 and 'name="username"' in r.text and "Anna" in r.text
    r = client.post(f"/invite/{tok}", data={"username": "anna", "password": "test123!", "password2": "test123!", "csrf": csrf(client)})
    assert r.status_code == 303 and r.headers["location"] == "/" and SESSION_COOKIE in r.headers.get("set-cookie", "")
    anna = client.app.state.users.get_by_username("anna")
    assert anna["role"] == "user" and anna["invited_by"] == admin["id"]
    assert client.app.state.users.get_invite(tok) is None
    assert client.get(f"/invite/{tok}").status_code == 404
    assert client.app.state.events.recent(1)[0]["kind"] == "invite_accepted"


def test_invite_validation_errors_stay_on_the_form(client):
    admin = _admin(client)
    tok = client.app.state.users.create_invite(admin["id"])
    r = client.post(f"/invite/{tok}", data={"username": "ok", "password": "test123!", "password2": "test123!", "csrf": csrf(client)})
    assert r.status_code == 400 and "Benutzername" in r.text
    r = client.post(f"/invite/{tok}", data={"username": "anna", "password": "test123!", "password2": "anders123", "csrf": csrf(client)})
    assert r.status_code == 400 and "stimmen nicht überein" in r.text
    r = client.post(f"/invite/{tok}", data={"username": "admin", "password": "test123!", "password2": "test123!", "csrf": csrf(client)})
    assert r.status_code == 400 and "bereits vergeben" in r.text
    assert client.app.state.users.get_invite(tok) is not None          # still usable


def test_reset_invite_sets_password_and_ends_other_sessions(client):
    admin = _admin(client)
    bob = client.app.state.users.create("bob", "test123!")
    old = client.app.state.users.create_session(bob["id"])
    tok = client.app.state.users.create_invite(admin["id"], note="Reset bob", reset_user_id=bob["id"])
    r = client.get(f"/invite/{tok}")
    assert r.status_code == 200 and 'name="username"' not in r.text and "bob" in r.text
    r = client.post(f"/invite/{tok}", data={"password": "neuesPasswort9", "password2": "neuesPasswort9", "csrf": csrf(client)})
    assert r.status_code == 303
    from redat.auth.passwords import verify_password
    assert verify_password("neuesPasswort9", client.app.state.users.get_by_username("bob")["password_hash"])
    assert client.app.state.users.resolve_session(old) is None
    assert client.app.state.events.recent(1)[0]["kind"] == "password_reset"


def test_konto_password_change_and_logout_others(client):
    u = login(client, username="carla")
    other = client.app.state.users.create_session(u["id"])
    r = client.get("/konto")
    assert r.status_code == 200 and "carla" in r.text and r.text.count("pytest") >= 1
    r = client.post("/konto/password", data={"current": "falsch", "password": "neuesPasswort9", "password2": "neuesPasswort9", "csrf": csrf(client)})
    assert r.status_code == 400 and "aktuelle Passwort" in r.text
    r = client.post("/konto/password", data={"current": "test123!", "password": "neuesPasswort9", "password2": "neuesPasswort9", "csrf": csrf(client)})
    assert r.status_code == 303 and r.headers["location"] == "/konto?ok=passwort"
    assert client.app.state.users.resolve_session(other) is None            # other devices signed out
    assert client.get("/konto").status_code == 200                           # this session survives
    other2 = client.app.state.users.create_session(u["id"])
    r = client.post("/konto/logout-others", data={"csrf": csrf(client)})
    assert r.status_code == 303 and client.app.state.users.resolve_session(other2) is None


def test_navigation_reflects_login_state(client):
    r = client.get("/quellen")
    assert "Anmelden" in r.text and "Abmelden" not in r.text
    login(client, username="root", role="admin")
    r = client.get("/quellen")
    assert "root" in r.text and "Abmelden" in r.text and 'href="/admin"' in r.text and 'href="/konto"' in r.text
```

In `tests/test_auth_principal.py::test_public_routes_need_no_login` tighten `/login` to `== 200`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest -q tests/test_auth_pages.py`
Expected: FAIL — 404 on `/login` etc.

- [ ] **Step 3: `redat/auth/csrf.py`**

```python
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
```

- [ ] **Step 4: `redat/web/pages.py`**

```python
from redat.auth.csrf import ensure_csrf
from redat.auth.principal import CSRF_COOKIE, Principal, csrf_cookie_kwargs, optional_principal, page_principal


def _render(request: Request, name: str, ctx: dict, status_code: int = 200, no_store: bool = False) -> HTMLResponse:
    token = ensure_csrf(request)
    resp = templates.TemplateResponse(request, name, {"request": request, "version": __version__,
                                                      "principal": optional_principal(request), "csrf_token": token, **ctx},
                                      status_code=status_code)
    if getattr(request.state, "csrf_new", None):
        resp.set_cookie(CSRF_COOKIE, token, **csrf_cookie_kwargs())
    if no_store:
        resp.headers["Cache-Control"] = "no-store"
    return resp
```

`index(request, …, principal: Principal = Depends(page_principal))` (already from Task 2); `stored_run` and `quellen` take `principal: Optional[Principal] = Depends(optional_principal)` (unused variable is fine — it primes the navigation state). `stored_run` records the `permalink_view` event in Task 4.

- [ ] **Step 5: `redat/web/auth_pages.py`**

```python
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


def _login_response(request: Request, user: dict, target: str) -> RedirectResponse:
    users, events = request.app.state.users, request.app.state.events
    token = users.create_session(user["id"], user_agent=request.headers.get("user-agent", ""), ip=client_ip(request),
                                 days=get_settings().session_days)
    users.touch_login(user["id"])
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
    ok = bool(row) and row["disabled_at"] is None and verify_password(password, row["password_hash"])
    if not ok:
        if not row:
            verify_password(password, "scrypt$32768$8$1$AAAAAAAAAAAAAAAAAAAAAA==$AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")  # equalise timing
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
    return _login_response(request, user, "/")


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
```

`redat/app.py`: `from redat.web.auth_pages import router as auth_router` and `app.include_router(auth_router)`.

- [ ] **Step 6: Templates**

`redat/templates/login.html`:

```jinja
{% extends "base.html" %}
{% block title %}Anmelden — NRW-REDAT{% endblock %}
{% block content %}
<div class="max-w-md mx-auto bg-white rounded-lg shadow p-6">
    <h1 class="text-xl font-bold text-gray-900 mb-1">🔐 Anmelden</h1>
    <p class="text-sm text-gray-600 mb-4">NRW-REDAT ist ein privates Werkzeug. Zugang gibt es nur per Einladung.</p>
    {% if error %}<div class="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">⚠️ {{ error }}</div>{% endif %}
    <form method="post" action="/login" class="space-y-4">
        <input type="hidden" name="csrf" value="{{ csrf_token }}">
        <input type="hidden" name="next" value="{{ next }}">
        <label class="block text-sm"><span class="text-gray-700">Benutzername</span>
            <input name="username" value="{{ username }}" autocomplete="username" autofocus required
                   class="mt-1 w-full rounded-md border-gray-300 shadow-sm focus:border-teal-500 focus:ring-teal-500"></label>
        <label class="block text-sm"><span class="text-gray-700">Passwort</span>
            <input name="password" type="password" autocomplete="current-password" required
                   class="mt-1 w-full rounded-md border-gray-300 shadow-sm focus:border-teal-500 focus:ring-teal-500"></label>
        <button type="submit" class="w-full px-6 py-2 bg-teal-600 text-white rounded-md hover:bg-teal-700 transition">Anmelden</button>
    </form>
    <p class="mt-4 text-xs text-gray-500">Hinweis: Analysen, Adressen und PDF-Exporte werden pro Konto aufgezeichnet und sind für den Administrator einsehbar.</p>
</div>
{% endblock %}
```

`redat/templates/invite.html`:

```jinja
{% extends "base.html" %}
{% block title %}Einladung — NRW-REDAT{% endblock %}
{% block content %}
<div class="max-w-md mx-auto bg-white rounded-lg shadow p-6">
    {% if reset_user %}
    <h1 class="text-xl font-bold text-gray-900 mb-1">🔑 Neues Passwort für {{ reset_user.username }}</h1>
    <p class="text-sm text-gray-600 mb-4">Der Administrator hat einen Passwort-Link erstellt. Nach dem Speichern sind alle anderen Geräte abgemeldet.</p>
    {% else %}
    <h1 class="text-xl font-bold text-gray-900 mb-1">👋 Willkommen bei NRW-REDAT</h1>
    <p class="text-sm text-gray-600 mb-4">Einladung{% if invite.note %} für <strong>{{ invite.note }}</strong>{% endif %} — bitte Benutzername und Passwort wählen.</p>
    {% endif %}
    {% if error %}<div class="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">⚠️ {{ error }}</div>{% endif %}
    <form method="post" action="/invite/{{ token }}" class="space-y-4">
        <input type="hidden" name="csrf" value="{{ csrf_token }}">
        {% if not reset_user %}
        <label class="block text-sm"><span class="text-gray-700">Benutzername</span>
            <input name="username" value="{{ username }}" autocomplete="username" required pattern="[a-z0-9._-]{3,32}"
                   class="mt-1 w-full rounded-md border-gray-300 shadow-sm focus:border-teal-500 focus:ring-teal-500">
            <span class="text-xs text-gray-500">3–32 Zeichen: a–z, 0–9, Punkt, Bindestrich, Unterstrich</span></label>
        {% endif %}
        <label class="block text-sm"><span class="text-gray-700">Passwort (mindestens 8 Zeichen)</span>
            <input name="password" type="password" autocomplete="new-password" required minlength="8"
                   class="mt-1 w-full rounded-md border-gray-300 shadow-sm focus:border-teal-500 focus:ring-teal-500"></label>
        <label class="block text-sm"><span class="text-gray-700">Passwort wiederholen</span>
            <input name="password2" type="password" autocomplete="new-password" required minlength="8"
                   class="mt-1 w-full rounded-md border-gray-300 shadow-sm focus:border-teal-500 focus:ring-teal-500"></label>
        <button type="submit" class="w-full px-6 py-2 bg-teal-600 text-white rounded-md hover:bg-teal-700 transition">{% if reset_user %}Passwort speichern{% else %}Konto anlegen{% endif %}</button>
    </form>
    <p class="mt-4 text-xs text-gray-500">Analysen, Adressen und PDF-Exporte werden pro Konto aufgezeichnet und sind für den Administrator einsehbar.</p>
</div>
{% endblock %}
```

`redat/templates/konto.html`:

```jinja
{% extends "base.html" %}
{% block title %}Konto — NRW-REDAT{% endblock %}
{% block content %}
<div class="max-w-2xl mx-auto space-y-4">
    <div class="bg-white rounded-lg shadow p-6">
        <h1 class="text-xl font-bold text-gray-900 mb-1">👤 Konto: {{ principal.username }}</h1>
        <p class="text-sm text-gray-500 mb-4">Rolle: {{ "Administrator" if principal.is_admin else "Benutzer" }}</p>
        {% if message %}<div class="mb-4 p-3 bg-teal-50 border border-teal-200 rounded-lg text-teal-900 text-sm">✅ {{ message }}</div>{% endif %}
        {% if error %}<div class="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">⚠️ {{ error }}</div>{% endif %}
        <h2 class="font-semibold text-gray-900 mb-2">Passwort ändern</h2>
        <form method="post" action="/konto/password" class="space-y-3">
            <input type="hidden" name="csrf" value="{{ csrf_token }}">
            <input name="current" type="password" autocomplete="current-password" required placeholder="Aktuelles Passwort" class="w-full rounded-md border-gray-300 shadow-sm">
            <input name="password" type="password" autocomplete="new-password" required minlength="8" placeholder="Neues Passwort (mind. 8 Zeichen)" class="w-full rounded-md border-gray-300 shadow-sm">
            <input name="password2" type="password" autocomplete="new-password" required minlength="8" placeholder="Neues Passwort wiederholen" class="w-full rounded-md border-gray-300 shadow-sm">
            <button type="submit" class="px-6 py-2 bg-teal-600 text-white rounded-md hover:bg-teal-700 transition">Passwort speichern</button>
        </form>
    </div>
    <div class="bg-white rounded-lg shadow p-6">
        <h2 class="font-semibold text-gray-900 mb-2">Angemeldete Geräte</h2>
        <table class="w-full text-sm">
            <thead><tr class="text-left text-xs text-gray-500"><th class="py-1">Gerät</th><th class="py-1">Zuletzt aktiv</th><th class="py-1">Angemeldet seit</th></tr></thead>
            <tbody>
            {% for s in sessions %}
            <tr class="border-t border-gray-100"><td class="py-1">{{ s.user_agent[:60] or "—" }}{% if s.current %} <span class="text-xs text-teal-700">(dieses Gerät)</span>{% endif %}</td>
                <td class="py-1">{{ s.last_seen_at|fmt_datetime }}</td><td class="py-1">{{ s.created_at|fmt_datetime }}</td></tr>
            {% endfor %}
            </tbody>
        </table>
        <form method="post" action="/konto/logout-others" class="mt-3">
            <input type="hidden" name="csrf" value="{{ csrf_token }}">
            <button type="submit" class="px-4 py-2 border border-gray-300 rounded-md hover:bg-gray-50 text-sm">Alle anderen Geräte abmelden</button>
        </form>
    </div>
</div>
{% endblock %}
```

Add the Jinja filter `fmt_datetime` (ISO Z → `dd.mm.yyyy HH:MM`, `"—"` for None) next to the existing `fmt_date` registration in `redat/report/render.py` (the website and the PDF share the environment); check how `fmt_date` is registered and mirror it.

`redat/templates/base.html` navigation:

```jinja
            <nav class="flex items-center gap-4 text-sm">
                <a href="/" class="hover:text-teal-700 {{ 'font-semibold text-teal-700' if active == 'analyse' else 'text-gray-600' }}">Analyse</a>
                <a href="/quellen" class="hover:text-teal-700 {{ 'font-semibold text-teal-700' if active == 'quellen' else 'text-gray-600' }}">Quellen</a>
                {% if principal and principal.via == "session" %}
                <a href="/docs" class="text-gray-600 hover:text-teal-700">API</a>
                {% if principal.is_admin %}<a href="/admin" class="hover:text-teal-700 {{ 'font-semibold text-teal-700' if active == 'admin' else 'text-gray-600' }}">Admin</a>{% endif %}
                <a href="/konto" class="hover:text-teal-700 {{ 'font-semibold text-teal-700' if active == 'konto' else 'text-gray-600' }}">👤 {{ principal.username }}</a>
                <form method="post" action="/logout" class="inline"><input type="hidden" name="csrf" value="{{ csrf_token }}"><button type="submit" class="text-gray-600 hover:text-teal-700">Abmelden</button></form>
                {% else %}
                <a href="/login" class="text-gray-600 hover:text-teal-700">Anmelden</a>
                {% endif %}
            </nav>
```

Footer: `NRW-REDAT {{ version }} · Nordrhein-Westfalen · Daten: siehe <a href="/quellen" class="underline">Quellen</a>`.

- [ ] **Step 7: Suite, commit**

```bash
.venv/bin/python -m pytest -q
git add redat/auth/csrf.py redat/web/auth_pages.py redat/web/pages.py redat/app.py redat/report/render.py redat/templates/login.html redat/templates/invite.html redat/templates/konto.html redat/templates/base.html tests/test_auth_pages.py tests/test_auth_principal.py tests/test_web_pages.py
git commit -m "feat(auth): login, logout, invite acceptance and account pages with CSRF"
```

---

### Task 4: Usage events and the admin page

**Files:**
- Create: `redat/web/admin_pages.py`, `redat/templates/admin.html`, `tests/test_admin_pages.py`, `tests/test_usage_events.py`
- Modify: `redat/api/v1.py` (record `analyze`/`pdf`, `runs.user_id`), `redat/web/pages.py` (`permalink_view`), `redat/app.py` (include the admin router), `tests/test_auth_principal.py` (tighten `/admin` to 200)
- Test: the two new files

**Interfaces:**
- Consumes: `EventStore.record/stats/recent`, `UserStore` admin methods, `page_admin`, `check_csrf`, `client_ip`.
- Produces: routes `GET /admin`, `POST /admin/invites`, `POST /admin/invites/{token_hash}/revoke`, `POST /admin/users/{user_id}/{action}` (`disable|enable|delete|reset`); `v1._status_counts(sections) -> dict`.

- [ ] **Step 1: Write the failing tests**

`tests/test_usage_events.py`:

```python
"""Usage events are recorded where the spec says, with the user attached."""
import pytest
from fastapi.testclient import TestClient

import redat.api.v1 as V
import redat.core.analyze as A
from redat.core.geocoding import GeocodeResult
from tests.helpers_auth import login

OK = GeocodeResult(formatted_address="Am Käferberg 12, 53127 Bonn", latitude=50.716, longitude=7.0748, precision="house")


def _env(key, status="ok"):
    return {"key": key, "tier": "area", "status": status, "data": {} if status == "ok" else None, "message": None, "source": "x", "took_ms": 1}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(A, "geocode_with_precision", lambda a: OK)
    monkeypatch.setattr(A, "run_section", lambda key, ctx, precision=None, force=False: _env(key))
    monkeypatch.setattr(V, "render_pdf", lambda payload: (b"%PDF-1.4 fake", {"formatted_address": "x", "address": payload["address"], "generated_date": "2026-09-09"}))
    from redat.app import create_app
    with TestClient(create_app()) as c:
        yield c


def _payload():
    return {"address": "Am Käferberg 12, Bonn", "geocode": A.geocode_dict("Am Käferberg 12, Bonn", OK), "plot_size_m2": None,
            "living_space_m2": None, "sections": {"noise": _env("noise"), "boris": _env("boris", "error"), "zensus": _env("zensus", "empty")}}


def test_saving_a_run_records_analyze_with_user_and_counts(client):
    u = login(client, username="anna")
    r = client.post("/api/v1/runs", json=_payload())
    rid = r.json()["run_id"]
    assert client.app.state.runs.get(rid)["user_id"] == u["id"]
    ev = client.app.state.events.recent(1)[0]
    assert ev["kind"] == "analyze" and ev["username"] == "anna" and ev["run_id"] == rid and ev["via"] == "session"
    assert ev["address"] == "Am Käferberg 12, Bonn" and abs(ev["lat"] - 50.716) < 1e-6
    assert ev["extra"] == {"ok": 1, "error": 1, "empty": 1, "gated": 0}


def test_machine_analyze_records_too(client, monkeypatch):
    from redat import settings as s
    monkeypatch.setenv("REDAT_API_KEY", "k"); s.reset_settings()
    r = client.get("/api/v1/analyze", params={"address": "Am Käferberg 12, Bonn", "save": 1}, headers={"X-Api-Key": "k"})
    ev = client.app.state.events.recent(1)[0]
    assert ev["kind"] == "analyze" and ev["via"] == "api_key" and ev["user_id"] is None and ev["run_id"] == r.json()["run_id"]


def test_pdf_and_permalink_views_are_recorded(client):
    login(client, username="bob")
    rid = client.post("/api/v1/runs", json=_payload()).json()["run_id"]
    assert client.post("/api/v1/report", json=_payload()).status_code == 200
    assert client.app.state.events.recent(1)[0]["kind"] == "pdf"
    client.cookies.clear()                                   # anonymous visitor with the link
    assert client.get(f"/a/{rid}").status_code == 200
    ev = client.app.state.events.recent(1)[0]
    assert ev["kind"] == "permalink_view" and ev["user_id"] is None and ev["run_id"] == rid and "Käferberg" in ev["address"]
    assert client.get(f"/api/v1/run/{rid}/report.pdf").status_code == 200
    assert client.app.state.events.recent(1)[0]["kind"] == "pdf"
```

`tests/test_admin_pages.py`:

```python
"""/admin — dashboard, invites, user actions; admin only."""
import pytest
from fastapi.testclient import TestClient

from redat.auth.tokens import token_hash
from tests.helpers_auth import csrf, login


@pytest.fixture
def client():
    from redat.app import create_app
    with TestClient(create_app(), follow_redirects=False) as c:
        yield c


def test_dashboard_shows_stats_users_and_activity(client):
    admin = login(client, username="root", role="admin")
    bob = client.app.state.users.create("bob", "test123!")
    ev = client.app.state.events
    ev.record("analyze", user_id=bob["id"], via="session", address="Musterstraße 1, Essen", run_id="r1")
    ev.record("pdf", user_id=bob["id"], run_id="r1")
    r = client.get("/admin")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    assert "Musterstraße 1, Essen" in r.text and "bob" in r.text and 'id="usage-per-day"' in r.text
    assert "Analysen" in r.text and "Einladungslink" in r.text


def test_create_invite_shows_the_url_once_and_records(client):
    login(client, username="root", role="admin")
    r = client.post("/admin/invites", data={"note": "Anna", "role": "user", "csrf": csrf(client)})
    assert r.status_code == 200 and "/invite/" in r.text and "Anna" in r.text
    assert client.app.state.events.recent(1)[0]["kind"] == "invite_created"
    inv = client.app.state.users.list_invites()[0]
    assert inv["status"] == "offen" and inv["note"] == "Anna"
    r = client.post(f"/admin/invites/{inv['token_hash']}/revoke", data={"csrf": csrf(client)})
    assert r.status_code == 303 and client.app.state.users.list_invites() == []


def test_user_actions(client):
    admin = login(client, username="root", role="admin")
    bob = client.app.state.users.create("bob", "test123!")
    tok = client.app.state.users.create_session(bob["id"])
    assert client.post(f"/admin/users/{bob['id']}/disable", data={"csrf": csrf(client)}).status_code == 303
    assert client.app.state.users.get(bob["id"])["disabled_at"] and client.app.state.users.resolve_session(tok) is None
    assert client.post(f"/admin/users/{bob['id']}/enable", data={"csrf": csrf(client)}).status_code == 303
    r = client.post(f"/admin/users/{bob['id']}/reset", data={"csrf": csrf(client)})
    assert r.status_code == 200 and "/invite/" in r.text
    assert client.app.state.users.list_invites()[0]["reset_user_id"] == bob["id"]
    assert client.post(f"/admin/users/{bob['id']}/delete", data={"csrf": csrf(client)}).status_code == 303
    assert client.app.state.users.get(bob["id"]) is None
    for action in ("disable", "delete"):
        assert client.post(f"/admin/users/{admin['id']}/{action}", data={"csrf": csrf(client)}).status_code == 400
    assert client.post(f"/admin/users/{bob['id']}/explode", data={"csrf": csrf(client)}).status_code == 404
    assert client.post(f"/admin/users/{admin['id']}/disable", data={"csrf": "wrong"}).status_code == 403


def test_non_admin_is_forbidden(client):
    login(client, username="bob")
    assert client.get("/admin").status_code == 403
    assert client.post("/admin/invites", data={"note": "x", "role": "user", "csrf": csrf(client)}).status_code == 403
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest -q tests/test_usage_events.py tests/test_admin_pages.py`
Expected: FAIL — no events recorded; `/admin` 404.

- [ ] **Step 3: Event hooks (`redat/api/v1.py`, `redat/web/pages.py`)**

`v1.py`:

```python
from redat.auth.principal import client_ip, current_principal, require_principal


def _status_counts(sections) -> dict:
    counts = {"ok": 0, "error": 0, "empty": 0, "gated": 0}
    for env in (sections or {}).values() if isinstance(sections, dict) else []:
        st = (env or {}).get("status")
        if st in counts:
            counts[st] += 1
    return counts


def _record_analyze(request: Request, payload: dict, run_id: Optional[str]) -> None:
    p = current_principal(request)
    g = payload.get("geocode") or {}
    request.app.state.events.record("analyze", user_id=p.user_id if p else None, via=p.via if p else None,
                                    address=payload.get("address"), lat=g.get("latitude"), lon=g.get("longitude"),
                                    run_id=run_id, extra=_status_counts(payload.get("sections")), ip=client_ip(request))


def _record_pdf(request: Request, payload: dict, run_id: Optional[str]) -> None:
    p = current_principal(request)
    request.app.state.events.record("pdf", user_id=p.user_id if p else None, via=p.via if p else None,
                                    address=payload.get("address"), run_id=run_id, ip=client_ip(request))
```

- `api_analyze`: after computing `out`, `run_id = None`; when `save`: `run_id = request.app.state.runs.save(run, user_id=(current_principal(request).user_id if current_principal(request) else None))`; then `_record_analyze(request, {"address": address, "geocode": out["geocode"], "sections": out["sections"]}, run_id)` in both cases.
- `api_post_run`: `p = current_principal(request)`; `run_id = …save(A.payload_to_run(payload), user_id=p.user_id if p else None)`; `_record_analyze(request, payload, run_id)`.
- `_pdf(payload, request, run_id=None)`: after a successful render call `_record_pdf(request, payload, run_id)`; update the three callers (`api_report_post` → `run_id=None`; `api_report_get` → `None`; `api_run_report` → `run_id`).

`pages.py::stored_run`: after loading the run, `request.app.state.events.record("permalink_view", user_id=principal.user_id if principal else None, via=principal.via if principal else None, address=run["address"], lat=run["latitude"], lon=run["longitude"], run_id=run_id, ip=client_ip(request))`.

- [ ] **Step 4: `redat/web/admin_pages.py`**

```python
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
```

`redat/app.py`: include `redat.web.admin_pages.router`.

- [ ] **Step 5: `redat/templates/admin.html`**

Sections in order (card style): title "🛠️ Verwaltung"; `{% if error %}` alert; `{% if new_invite_url %}` a teal box "Einladungslink (wird nur einmal angezeigt):" with the URL in a read-only `<input>` plus a "Kopieren" button (`navigator.clipboard.writeText`); KPI tiles (`grid grid-cols-2 md:grid-cols-5 gap-3`): Benutzer (`stats.users_total`, subline "aktiv 30 d: …"), Analysen 7 d, Analysen 30 d, Analysen gesamt, PDF-Exporte 30 d + Permalink-Aufrufe 30 d; chart card:

```jinja
<div class="bg-white rounded-lg shadow p-6">
    <h2 class="font-semibold text-gray-900 mb-2">Analysen pro Tag (letzte 30 Tage)</h2>
    <script type="application/json" id="usage-per-day">{{ stats.per_day|tojson }}</script>
    <div style="height: 180px"><canvas id="usage-chart" aria-label="Analysen pro Tag" role="img"></canvas></div>
    <details class="mt-2 text-xs text-gray-500"><summary>Als Tabelle</summary>
        <table class="mt-1"><tbody>{% for d in stats.per_day if d.analyses %}<tr><td class="pr-3">{{ d.date }}</td><td>{{ d.analyses }}</td></tr>{% endfor %}</tbody></table>
    </details>
</div>
```

and in `{% block scripts %}`:

```html
<script>
(function () {
    const data = JSON.parse(document.getElementById('usage-per-day').textContent);
    const ctx = document.getElementById('usage-chart');
    if (!ctx || !window.Chart) return;
    new Chart(ctx, {
        type: 'bar',
        data: { labels: data.map(d => d.date.slice(5)), datasets: [{ data: data.map(d => d.analyses), backgroundColor: '#0d9488', borderRadius: 4, maxBarThickness: 18 }] },
        options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } },
                   scales: { x: { grid: { display: false }, ticks: { maxTicksLimit: 10 } }, y: { beginAtZero: true, ticks: { precision: 0 }, grid: { color: '#e5e7eb' } } } }
    });
})();
</script>
```

Users table columns: Benutzer, Rolle, Status (aktiv/deaktiviert), Analysen gesamt / 30 d, PDFs, Zuletzt aktiv (`fmt_datetime`), Aktionen (POST forms with hidden csrf: Deaktivieren/Aktivieren, Passwort-Link, Löschen with `onclick="return confirm('Benutzer wirklich löschen?')"`; the buttons are omitted for `u.id == me` except Passwort-Link). Invite form (note, role select, "Einladungslink erstellen"). Invites table: Notiz, Rolle, Erstellt von, Gültig bis, Status, used by, Aktion (Widerrufen for `offen`). Recent activity table: Zeit, Benutzer (or "—"), Ereignis (`kind_labels`), Details (address or run link `/a/{run_id}` or `extra.username` for failed logins). All timestamps through `fmt_datetime`.

- [ ] **Step 6: Suite, commit**

```bash
.venv/bin/python -m pytest -q
git add redat/api/v1.py redat/web/pages.py redat/web/admin_pages.py redat/app.py redat/templates/admin.html tests/test_usage_events.py tests/test_admin_pages.py tests/test_auth_principal.py
git commit -m "feat(admin): usage events and the admin page — statistics, users, invite links"
```

---

### Task 5: CLI, docs, CSS rebuild, local verification

**Files:** `scripts/users.py`, `tests/test_users_cli.py`, `README.md`, `HANDOVER.md`, `CLAUDE.md`, `redat/static/redat.css`

- [ ] **Step 1: `scripts/users.py`** — argparse CLI over `UserStore`/`EventStore` on `Path(os.environ.get("REDAT_DATA_DIR", "data")) / "redat.db"` (no `get_settings()`, so it runs without the Geoapify key): `list` (table: id, username, role, status, created, last login), `create-admin --username admin` (password from `--password-env VAR` or `getpass` twice), `reset --username X` (same), `disable --username X`, `enable --username X`, `prune-events --days N`. Exit code 1 with a message on unknown user / policy error. Test `tests/test_users_cli.py` drives `main([...])` with `REDAT_DATA_DIR` pointing at `tmp_path` and `--password-env`.
- [ ] **Step 2: README** — new section "Zugang & Benutzer" after "Quick start": accounts via invite links, roles, sessions (30 d sliding, "Abmelden"), the admin page and what it records (privacy sentence), `X-Api-Key` stays for machine clients, bootstrap (`REDAT_BOOTSTRAP_ADMIN_PASSWORD` on first start) and lockout recovery (`docker compose exec redat python scripts/users.py …`), the public permalink rule. `.env` table gains the two new keys; the old "REDAT_API_KEY breaks the website" remark is replaced by "works alongside sessions".
- [ ] **Step 3: HANDOVER** — Status paragraph (auth in the app, Traefik BasicAuth removed on this host); runbook: the override edit (drop `redat-auth` labels, router middlewares `sec-headers@docker` only), first-start bootstrap, verification checklist (spec §9); "Known limitations": remove the "API key vs. website" entry, add "login throttle is per process"; work-log entry naming the five tasks and commits.
- [ ] **Step 4: CLAUDE.md** — test count from `pytest -q`; Rules: the access rules one-liner (public paths), "gated tests log in with `tests/helpers_auth.login`", "forms need the CSRF double-submit (`ensure_csrf`/`check_csrf`), JSON API mutations rely on SameSite=Lax + JSON content type", "`page_principal` for pages (303), `require_principal` for the API (401)".
- [ ] **Step 5: CSS** — `npx tailwindcss@3 -c tailwind.config.js -i tailwind.input.css -o redat/static/redat.css --minify` (new classes in four templates → the file will change; commit it).
- [ ] **Step 6: Verification** — full suite; then with the key from `/home/mitja/nrw-redat/.env` (`set -a; source …; set +a`, never print it) and `REDAT_BOOTSTRAP_ADMIN_PASSWORD=test123!`, start `REDAT_DATA_DIR=<scratch> .venv/bin/uvicorn redat.app:app --port 8201`, then with `curl -c jar -b jar`: `GET /` → 303 `/login?next=%2F`; `GET /login` → 200 (csrf cookie in jar); `POST /login` (username admin, password test123!, csrf from jar) → 303 `/`, session cookie `HttpOnly`; `GET /` → 200 with "admin" in the nav; `GET /api/v1/sections` → 200; `GET /admin` → 200; create an invite via `POST /admin/invites` and accept it in a second cookie jar as user `anna`; `GET /admin` shows anna; `GET /a/nope` → 404 without cookies; `GET /api/v1/sections` without cookies → 401; `POST /logout` → 303. Stop the server. Record every status line in the report.
- [ ] **Step 7: Commit** — `git commit -m "docs: user management — README access section, HANDOVER runbook, CLAUDE.md rules; users CLI; rebuild CSS"` plus trailers.
