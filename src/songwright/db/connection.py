"""SQLite connection + schema bootstrap."""
from __future__ import annotations

import sqlite3
from pathlib import Path

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Open a connection with sane defaults: row factory, FK enforcement, WAL."""
    conn = sqlite3.connect(str(db_path), isolation_level=None, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def init_db(db_path: str | Path) -> sqlite3.Connection:
    """Open + apply schema. Idempotent: schema uses IF NOT EXISTS throughout."""
    conn = connect(db_path)
    conn.executescript(_SCHEMA_PATH.read_text())
    return conn
