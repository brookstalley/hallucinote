"""SQLite connection + schema bootstrap."""
from __future__ import annotations

import sqlite3
import weakref
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"

# sqlite3.Connection doesn't allow attribute assignment, so we track nested
# transaction depth in a side table keyed by `id(conn)`. `weakref.finalize`
# cleans up the entry when the connection is GC'd; defensive `pop(.., None)`
# in the outermost block tolerates an exception that interrupted a previous
# transaction before depth reset.
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
    """Open + apply schema. Idempotent: schema uses IF NOT EXISTS throughout."""
    conn = connect(db_path)
    conn.executescript(_SCHEMA_PATH.read_text())
    return conn


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
    inner block, not the whole outer transaction. Reentrancy is tracked
    on a `_transaction_depth` attribute on the connection.

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
