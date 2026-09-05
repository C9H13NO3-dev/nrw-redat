"""Saved analyses (permalinks). One SQLite file under REDAT_DATA_DIR."""
import base64
import json
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_DDL = """
CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  address TEXT NOT NULL,
  formatted_address TEXT,
  latitude REAL NOT NULL,
  longitude REAL NOT NULL,
  precision TEXT,
  plot_size_m2 REAL,
  living_space_m2 REAL,
  sections_json TEXT NOT NULL
);
"""
_COLS = ("address", "formatted_address", "latitude", "longitude", "precision",
         "plot_size_m2", "living_space_m2")


class RunStore:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path, timeout=10)
        con.row_factory = sqlite3.Row
        return con

    def init(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as con:
            con.execute("PRAGMA journal_mode=WAL")
            con.executescript(_DDL)

    @staticmethod
    def new_run_id() -> str:
        return base64.b32encode(secrets.token_bytes(6)).decode().rstrip("=").lower()

    def save(self, payload: dict) -> str:
        if payload.get("latitude") is None or payload.get("longitude") is None:
            raise ValueError("latitude/longitude required")
        if not payload.get("address"):
            raise ValueError("address required")
        rid = self.new_run_id()
        created = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        row = [rid, created] + [payload.get(c) for c in _COLS] + [json.dumps(payload.get("sections") or {}, ensure_ascii=False)]
        with self._connect() as con:
            con.execute(
                f"INSERT INTO runs (id, created_at, {', '.join(_COLS)}, sections_json) "
                f"VALUES ({', '.join('?' * (len(_COLS) + 3))})", row)
        return rid

    def get(self, run_id: str) -> Optional[dict]:
        with self._connect() as con:
            r = con.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if r is None:
            return None
        out = {k: r[k] for k in r.keys() if k != "sections_json"}
        out["sections"] = json.loads(r["sections_json"])
        return out
