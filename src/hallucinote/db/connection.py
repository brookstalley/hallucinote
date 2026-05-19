"""SQLite connection + schema bootstrap."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"

# sqlite3.Connection doesn't allow attribute assignment, so we track nested
# transaction depth in a side table keyed by `id(conn)`. Depth entries are
# explicitly popped when the outermost block closes (success or exception),
# so connections that fully unwind leave no residue. Connections GC'd
# mid-transaction (rare, abnormal) can leak one int entry, which is fine
# at this scale — the connection's `id` doesn't recycle while it's live.
_TRANSACTION_DEPTH: dict[int, int] = {}


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Open a connection with sane defaults: row factory, FK enforcement, WAL.

    `isolation_level=None` puts the connection in autocommit mode — each
    statement commits immediately. This is the right default for the wide
    surface of single-statement mutators (which would otherwise need an
    explicit `conn.commit()` after every write); it does mean `with conn:`
    is a no-op for rollback. Callers that need atomicity must use the
    `transaction()` helper below, which issues explicit BEGIN/COMMIT/ROLLBACK.
    """
    conn = sqlite3.connect(str(db_path), isolation_level=None, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def init_db(db_path: str | Path) -> sqlite3.Connection:
    """Open + apply schema. Idempotent: schema uses IF NOT EXISTS throughout,
    plus an explicit column-add pass for ALTER cases that CREATE doesn't cover.
    """
    conn = connect(db_path)
    conn.executescript(_SCHEMA_PATH.read_text())
    _ensure_added_columns(conn)
    return conn


# Column additions that post-date the original schema CREATE statements.
# SQLite has no `ADD COLUMN IF NOT EXISTS` so we sniff `PRAGMA table_info`
# first. Each entry is (table, column_name, full_column_definition).
# Append new rows here when a future chunk needs an additive schema bump
# on existing DBs; never remove rows (removal is a destructive migration
# that needs its own one-shot tool).
_ADDED_COLUMNS: tuple[tuple[str, str, str], ...] = (
    # W8-B: requests gains cycle metadata. Existing rows get NULL kind /
    # duration_ms / outcome; mutators set them at request open + close.
    ("requests", "kind", "TEXT"),
    ("requests", "duration_ms", "INTEGER"),
    ("requests", "outcome", "TEXT"),
)


def _ensure_added_columns(conn: sqlite3.Connection) -> None:
    """Idempotent column-add migration. Safe to call on fresh + existing DBs."""
    by_table: dict[str, set[str]] = {}
    for table, _col, _defn in _ADDED_COLUMNS:
        by_table.setdefault(table, set())
    for table in by_table:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        by_table[table] = {r["name"] for r in rows}
    for table, col, defn in _ADDED_COLUMNS:
        if col in by_table[table]:
            continue
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {defn}")


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[None]:
    """Run a block in a real SQLite transaction with rollback on exception.

    `with conn:` is a no-op for connections opened in autocommit mode
    (`isolation_level=None`), so callers that need atomicity must drive
    BEGIN/COMMIT/ROLLBACK themselves. This helper is the canonical way.

    **Nesting**: nested `transaction()` blocks use SQLite SAVEPOINTs so a
    mutator that wraps its own atomicity (e.g. `M.replace_breakpoints`,
    `M.replace_clip_notes`) composes correctly when called from inside an
    outer transaction (e.g. `apply_pull_results`, `apply_push_results`).
    The outermost block drives BEGIN/COMMIT/ROLLBACK; inner blocks drive
    SAVEPOINT/RELEASE/ROLLBACK TO so an inner failure rolls back only the
    inner block, not the whole outer transaction. Reentrancy depth is
    tracked in the module-level `_TRANSACTION_DEPTH` dict keyed by
    `id(conn)` (sqlite3.Connection doesn't permit attribute assignment).

    Usage:
        with transaction(conn):
            conn.execute(...)
            conn.execute(...)
    """
    key = id(conn)
    depth = _TRANSACTION_DEPTH.get(key, 0)
    if depth == 0:
        conn.execute("BEGIN")
        _TRANSACTION_DEPTH[key] = 1
        try:
            yield
        except BaseException:  # prawduct:ok-broad-except
            # Roll back on ANY exception — including KeyboardInterrupt / SystemExit /
            # asyncio.CancelledError — then re-raise. The DB must not be left in a
            # half-written state because the user hit Ctrl-C mid-batch.
            conn.execute("ROLLBACK")
            _TRANSACTION_DEPTH.pop(key, None)
            raise
        conn.execute("COMMIT")
        _TRANSACTION_DEPTH.pop(key, None)
    else:
        # Nested call — use a SAVEPOINT so inner failures don't poison the
        # outer transaction. SAVEPOINT names must be unique within a
        # connection; depth makes them so.
        sp = f"sp_{depth}"
        conn.execute(f"SAVEPOINT {sp}")
        _TRANSACTION_DEPTH[key] = depth + 1
        try:
            yield
        except BaseException:  # prawduct:ok-broad-except
            conn.execute(f"ROLLBACK TO SAVEPOINT {sp}")
            conn.execute(f"RELEASE SAVEPOINT {sp}")
            _TRANSACTION_DEPTH[key] = depth
            raise
        conn.execute(f"RELEASE SAVEPOINT {sp}")
        _TRANSACTION_DEPTH[key] = depth
