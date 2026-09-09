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
