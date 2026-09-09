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
