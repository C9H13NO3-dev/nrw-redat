"""Persistent TTL cache: section envelopes plus small key/value namespaces, one table in redat.db.

Why SQLite and not a dict: a 30-day TTL is meaningless in memory that dies with every redeploy; a
file survives restarts, can be bounded (rows + bytes, LRU eviction), inspected (stats, per-section
purge) and shares the WAL-mode database RunStore already keeps. The process is single-worker by
design (see HANDOVER), so one connection behind a lock is all the concurrency control needed - the
section threads spend their time in HTTP calls, not here.

Semantics (README "Cache semantics"): only ok/empty envelopes are stored; TTL is per section
(registry default, settings.yaml `cache_ttls` override, global `cache_ttl_s` fallback; 0 disables);
the key carries the section's `cache_version` so a card can invalidate its own entries by bumping it;
expiry is wall-clock. Eviction order when over a bound: expired rows first, then least recently used.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

_CACHEABLE = ("ok", "empty")
NS_SECTION = "section"

_DDL = """
CREATE TABLE IF NOT EXISTS cache (
  ns         TEXT NOT NULL,
  k          TEXT NOT NULL,
  section    TEXT,
  payload    TEXT NOT NULL,
  size       INTEGER NOT NULL,
  created_at REAL NOT NULL,
  expires_at REAL NOT NULL,
  last_hit   REAL NOT NULL,
  PRIMARY KEY (ns, k)
);
CREATE INDEX IF NOT EXISTS cache_expires_at ON cache(expires_at);
CREATE INDEX IF NOT EXISTS cache_last_hit ON cache(last_hit);
CREATE INDEX IF NOT EXISTS cache_section ON cache(ns, section);
"""


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class SectionCache:
    def __init__(self, ttl_s: int, *, db_path: Optional[Path] = None, ttl_overrides: Optional[dict] = None,
                 max_entries: int = 100_000, max_bytes: int = 256 * 1024 * 1024):
        self.ttl_s = max(0, int(ttl_s))
        self.ttl_overrides = {str(k): max(0, int(v)) for k, v in (ttl_overrides or {}).items()}
        self.max_entries = max(1, int(max_entries))
        self.max_bytes = max(1, int(max_bytes))
        self.db_path = Path(db_path) if db_path else None
        self._lock = threading.Lock()
        if self.db_path:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # isolation_level=None -> autocommit; every public method is one short statement sequence under the lock.
        self._con = sqlite3.connect(str(self.db_path) if self.db_path else ":memory:", timeout=10,
                                    check_same_thread=False, isolation_level=None)
        with self._lock:
            if self.db_path:
                self._con.execute("PRAGMA journal_mode=WAL")
                self._con.execute("PRAGMA synchronous=NORMAL")
            self._con.executescript(_DDL)
            n, b = self._con.execute("SELECT COUNT(*), COALESCE(SUM(size), 0) FROM cache").fetchone()
        # Running totals so bounds checks never scan the table. Exact for the single writer this
        # process is; a second instance on the same file (tests) would only make eviction approximate.
        self._entries, self._bytes = int(n), int(b)

    # ------------------------------------------------------------------ keys & policy
    @staticmethod
    def key(section: str, lat: float, lon: float, plot_size_m2, force: bool, version: int = 1) -> tuple:
        plot = None if plot_size_m2 in (None, 0) else float(plot_size_m2)
        return (section, round(float(lat), 4), round(float(lon), 4), plot, bool(force), int(version))

    def ttl_for(self, section: str) -> int:
        return self.ttl_overrides.get(section, self.ttl_s)

    @staticmethod
    def _kstr(k: tuple) -> str:
        return json.dumps(list(k), separators=(",", ":"))

    # ------------------------------------------------------------------ section envelopes
    def get(self, k: tuple) -> Optional[dict]:
        if self.ttl_for(k[0]) == 0:
            return None
        hit = self._fetch(NS_SECTION, self._kstr(k))
        if hit is None:
            return None
        payload, created_at = hit
        env = json.loads(payload)
        env["cached"] = True
        env["cached_at"] = _iso(created_at)
        return env

    def put(self, k: tuple, envelope: dict) -> None:
        if envelope.get("status") not in _CACHEABLE:
            return
        ttl = self.ttl_for(k[0])
        if ttl <= 0:
            return
        self._store(NS_SECTION, self._kstr(k), k[0], json.dumps(envelope, ensure_ascii=False), ttl)

    # ------------------------------------------------------------------ key/value namespaces
    def kv_get(self, ns: str, key: str, default: Any = None) -> Any:
        hit = self._fetch(ns, key)
        return default if hit is None else json.loads(hit[0])

    def kv_put(self, ns: str, key: str, value: Any, *, ttl_s: int) -> None:
        if ttl_s <= 0:
            return
        self._store(ns, key, None, json.dumps(value, ensure_ascii=False), int(ttl_s))

    # ------------------------------------------------------------------ maintenance & introspection
    def purge_expired(self) -> int:
        with self._lock:
            return self._delete("expires_at <= ?", (time.time(),))

    def invalidate(self, section: Optional[str] = None) -> int:
        """Drop one section's envelopes, or (section=None) everything in every namespace."""
        with self._lock:
            if section is None:
                return self._delete("1=1", ())
            return self._delete("ns = ? AND section = ?", (NS_SECTION, section))

    def clear(self) -> None:
        self.invalidate()

    def stats(self) -> dict:
        with self._lock:
            by_section = dict(self._con.execute(
                "SELECT section, COUNT(*) FROM cache WHERE ns = ? GROUP BY section ORDER BY section", (NS_SECTION,)).fetchall())
            by_ns = dict(self._con.execute(
                "SELECT ns, COUNT(*) FROM cache WHERE ns != ? GROUP BY ns ORDER BY ns", (NS_SECTION,)).fetchall())
            expired = self._con.execute("SELECT COUNT(*) FROM cache WHERE expires_at <= ?", (time.time(),)).fetchone()[0]
            return {"entries": self._entries, "bytes": self._bytes, "expired": int(expired),
                    "max_entries": self.max_entries, "max_bytes": self.max_bytes,
                    "by_section": by_section, "by_namespace": by_ns, "db_path": str(self.db_path) if self.db_path else None}

    def close(self) -> None:
        with self._lock:
            self._con.close()

    # ------------------------------------------------------------------ internals (caller holds no lock)
    def _fetch(self, ns: str, key: str) -> Optional[tuple[str, float]]:
        now = time.time()
        with self._lock:
            row = self._con.execute("SELECT payload, created_at, expires_at FROM cache WHERE ns = ? AND k = ?", (ns, key)).fetchone()
            if row is None:
                return None
            payload, created_at, expires_at = row
            if now >= expires_at:
                self._delete("ns = ? AND k = ?", (ns, key))
                return None
            self._con.execute("UPDATE cache SET last_hit = ? WHERE ns = ? AND k = ?", (now, ns, key))
        return payload, created_at

    def _store(self, ns: str, key: str, section: Optional[str], payload: str, ttl: int) -> None:
        now = time.time()
        size = len(payload.encode("utf-8"))
        with self._lock:
            old = self._con.execute("SELECT size FROM cache WHERE ns = ? AND k = ?", (ns, key)).fetchone()
            if old is not None:
                self._entries -= 1
                self._bytes -= int(old[0])
            self._con.execute(
                "INSERT OR REPLACE INTO cache (ns, k, section, payload, size, created_at, expires_at, last_hit) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (ns, key, section, payload, size, now, now + ttl, now))
            self._entries += 1
            self._bytes += size
            self._enforce_bounds(now)

    def _delete(self, where: str, params: tuple) -> int:
        """DELETE matching rows, keep the running totals in step. Caller holds the lock."""
        rows = self._con.execute(f"DELETE FROM cache WHERE {where} RETURNING size", params).fetchall()
        self._entries -= len(rows)
        self._bytes -= sum(int(r[0]) for r in rows)
        return len(rows)

    def _over(self) -> bool:
        return self._entries > self.max_entries or self._bytes > self.max_bytes

    def _enforce_bounds(self, now: float) -> None:
        """Caller holds the lock. Expired rows go first, then least-recently-used in small batches."""
        if not self._over():
            return
        self._delete("expires_at <= ?", (now,))
        while self._over() and self._entries > 0:
            batch = max(1, self._entries // 50)
            self._delete("rowid IN (SELECT rowid FROM cache ORDER BY last_hit ASC LIMIT ?)", (batch,))
