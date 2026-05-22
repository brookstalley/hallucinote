"""SQLite connection + schema bootstrap."""
from __future__ import annotations

import shutil
import sqlite3
import subprocess
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
    _check_schema_canary()
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
    # Sweep B: devices gain a compose-time portable preset selector.
    # JSON-serialized {root, pattern, mode?, path_prefix?, case_sensitive?}.
    # Existing devices get NULL; mutators set it when build.py / the
    # snapshot uses preset_query instead of preset_uri.
    ("devices", "preset_query", "TEXT"),
    # Arc 2 / B3: requests gains the provenance rationale columns the
    # original W8-B chunk didn't ship. `prompt_text` carries the verbatim
    # seed prompt for compose / push / pull cycles. `parent_id` self-FKs
    # so an MCP auto-`mutate` request can chain to its enclosing
    # `compose` parent (degraded but always-present provenance). `metadata_json`
    # holds `{model, git_sha, branch, session_id, hostname, ...}` — a
    # bag of contextual signals that vary per call but aren't worth
    # individual columns. Existing rows get NULL across all three;
    # mutators populate them at create_request time.
    ("requests", "prompt_text", "TEXT"),
    ("requests", "parent_id", "TEXT REFERENCES requests(id) ON DELETE SET NULL"),
    ("requests", "metadata_json", "TEXT"),
    # Arc 4 / D4: devices gain a class_name field holding Live's internal
    # class (e.g. 'Compressor2', 'PhaserNew', 'PluginDevice'). The
    # `kind` column shifts from "internal class" to "browser display
    # name" (= Live's device.class_display_name); `class_name` carries
    # the internal identifier for plugin discrimination + informational
    # reads. Existing rows get NULL — pre-D4 callers stored the
    # internal class in `kind`; a clean re-pull rewrites both fields.
    ("devices", "class_name", "TEXT"),
    # Arc 7-tail / E1: device_parameters gains the enum cardinality —
    # JSON array of value_items in Live's order (index = numeric value).
    # NULL for continuous params. Captured at pull time from
    # ableton_device(action='get_parameters', detail='full'). Used by
    # M.create_enum_envelope to resolve enum-name breakpoints into
    # numeric values without forcing build.py authors to hand-list the
    # cardinality on every call.
    ("device_parameters", "value_items_json", "TEXT"),
    # Arc 7-tail / E3 (W13-A v1.0): devices gain the resolved browser
    # path segments — JSON array of strings from the browser root to the
    # loaded item (e.g. ["instruments", "Operator", "Bass", "Sub Bass"]
    # or ["plug-ins", "Native Instruments", "Massive X", "FatBass"]).
    # NULL when the device pre-dates E3 capture or was created without a
    # browser walk. Used by the push planner's fallback identity path:
    # when preset_uri (per-machine FileId) fails to resolve, the
    # resolver re-queries ableton_browser(action='search') scoped by
    # path[0] (root) + path[1:-1] (path_prefix) with pattern=display_name.
    # The path captures vendor / pack as path segments — unambiguous
    # across browser-tree depths (third-party plugins, Live packs, suite
    # instruments all carry vendor / pack at different depths).
    ("devices", "browser_path_json", "TEXT"),
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


_SCHEMA_CANARY_CHECKED = False


def _check_schema_canary() -> None:
    """Verify ``_ADDED_COLUMNS`` is also declared in ``schema.sql``.

    Every additive column lift gets two declarations by convention:
    ``schema.sql`` (fresh-DB CREATE TABLE) and ``_ADDED_COLUMNS`` (the
    ALTER pass for existing DBs). The two can drift silently because
    ``_ensure_added_columns`` papers over a missing ``schema.sql`` entry
    by ALTERing the column in after CREATE TABLE — so a fresh DB ends
    up correct even though ``schema.sql`` lies. This canary runs against
    an in-memory DB seeded only from ``schema.sql`` (no migration pass)
    and flags any ``_ADDED_COLUMNS`` entry the fresh DB is missing.

    First-call-per-process; results cached via module-level flag so the
    canary runs once regardless of how many DBs ``init_db`` opens.
    """
    global _SCHEMA_CANARY_CHECKED
    if _SCHEMA_CANARY_CHECKED:
        return
    _SCHEMA_CANARY_CHECKED = True
    canary_conn = sqlite3.connect(":memory:")
    try:
        canary_conn.executescript(_SCHEMA_PATH.read_text())
        missing: list[str] = []
        cache: dict[str, set[str]] = {}
        for table, col, _defn in _ADDED_COLUMNS:
            if table not in cache:
                rows = canary_conn.execute(
                    f"PRAGMA table_info({table})"
                ).fetchall()
                cache[table] = {r[1] for r in rows}
            if col not in cache[table]:
                missing.append(f"{table}.{col}")
    finally:
        canary_conn.close()
    if missing:
        raise RuntimeError(
            "schema canary: _ADDED_COLUMNS declares column(s) that aren't "
            f"in schema.sql: {', '.join(missing)}. Add the matching column "
            "declarations to schema.sql's CREATE TABLE block — fresh DBs "
            "and existing DBs must agree on the same final shape."
        )


def _git_current_branch(cwd: Path | None = None) -> str | None:
    """Current git branch name, or None if outside a repo or on detached HEAD.

    Used by `resolve_db_path` to produce per-branch DB filenames (W12-A) so
    branch switches don't silently leave the agent looking at a stale DB.
    Returns None in three cases:
      - `git` binary not on PATH
      - cwd isn't inside a git working tree
      - HEAD is detached (no symbolic ref)

    All three fall back to the legacy `<slug>.db` path at the callsite.
    """
    if shutil.which("git") is None:
        return None
    try:
        result = subprocess.run(
            ["git", "symbolic-ref", "--short", "HEAD"],
            capture_output=True, text=True, cwd=cwd, check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    branch = result.stdout.strip()
    return branch or None


_BRANCH_PROBE_GIT = object()  # sentinel: "probe git" (vs explicit None/str)


def resolve_db_path(
    slug: str,
    *,
    root: Path | str = "songs",
    branch: str | None = _BRANCH_PROBE_GIT,  # type: ignore[assignment]
) -> Path:
    """Per-branch DB filename. `songs/<slug>/<slug>-<branch>.db` inside a repo,
    falling back to `songs/<slug>/<slug>.db` outside a repo or on detached HEAD.

    The branch name is sanitized by replacing `/` with `--` so `feature/foo`
    becomes `feature--foo` — mirrors `.prawduct/.pr-reviews/` naming so
    behavior is predictable for the canonical "feature/X" gitflow shape.

    `branch` is an escape hatch primarily for testing — pass `None` to force
    the no-branch fallback, or a literal string to skip the git probe. Default
    triggers the real git probe.
    """
    if branch is _BRANCH_PROBE_GIT:
        resolved_branch = _git_current_branch()
    else:
        resolved_branch = branch
    root_path = Path(root)
    if resolved_branch is None:
        return root_path / slug / f"{slug}.db"
    sanitized = resolved_branch.replace("/", "--")
    return root_path / slug / f"{slug}-{sanitized}.db"


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
