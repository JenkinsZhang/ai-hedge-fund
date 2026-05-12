"""SQLite-backed cache for provider responses.

Single-table design. Values are pickled. ttl_seconds=0 means never expire.
"""

from __future__ import annotations

import pickle
import sqlite3
import time
from pathlib import Path
from typing import Any


_SCHEMA = """
CREATE TABLE IF NOT EXISTS cache (
    key         TEXT PRIMARY KEY,
    value       BLOB NOT NULL,
    fetched_at  INTEGER NOT NULL,
    ttl_seconds INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_fetched_at ON cache(fetched_at);
"""


class Cache:
    """Thread-safe SQLite cache.

    `ttl_seconds=0` means the entry never expires.
    """

    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            str(db_path), check_same_thread=False, isolation_level=None
        )
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)

    def get(self, key: str) -> Any | None:
        row = self._conn.execute(
            "SELECT value, fetched_at, ttl_seconds FROM cache WHERE key = ?",
            (key,),
        ).fetchone()
        if row is None:
            return None
        value_blob, fetched_at, ttl_seconds = row
        if ttl_seconds > 0 and time.time() - fetched_at > ttl_seconds:
            return None
        return pickle.loads(value_blob)

    def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        blob = pickle.dumps(value)
        self._conn.execute(
            "INSERT OR REPLACE INTO cache(key, value, fetched_at, ttl_seconds) "
            "VALUES (?, ?, ?, ?)",
            (key, blob, int(time.time()), ttl_seconds),
        )

    def close(self) -> None:
        self._conn.close()
