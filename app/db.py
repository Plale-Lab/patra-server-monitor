from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS subscribers (
  chat_id TEXT PRIMARY KEY,
  username TEXT,
  first_name TEXT,
  last_name TEXT,
  subscribed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  is_active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS monitor_state (
  target_name TEXT PRIMARY KEY,
  severity TEXT NOT NULL,
  status_text TEXT NOT NULL,
  latency_ms REAL,
  last_checked_at TEXT NOT NULL,
  last_changed_at TEXT NOT NULL,
  consecutive_failures INTEGER NOT NULL DEFAULT 0,
  consecutive_successes INTEGER NOT NULL DEFAULT 0,
  last_alerted_at TEXT,
  details_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS telegram_offsets (
  singleton_key TEXT PRIMARY KEY,
  update_offset INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS monitor_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  target_name TEXT NOT NULL,
  severity TEXT NOT NULL,
  status_text TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  details_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS monitor_targets (
  target_name TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  config_json TEXT NOT NULL DEFAULT '{}',
  is_active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


class Database:
    def __init__(self, db_path: str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._initialize()

    def _initialize(self) -> None:
        with self.connection() as conn:
            conn.executescript(SCHEMA_SQL)
            self._ensure_column(conn, "subscribers", "email", "TEXT")
            self._ensure_column(conn, "subscribers", "email_notifications_enabled", "INTEGER NOT NULL DEFAULT 0")
            conn.commit()

    def _ensure_column(self, conn: sqlite3.Connection, table_name: str, column_name: str, column_sql: str) -> None:
        columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}
        if column_name not in columns:
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_sql}")

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            try:
                yield conn
            finally:
                conn.close()
