"""SQLite connection + schema bootstrap."""
from __future__ import annotations

import shutil
import sqlite3
import subprocess
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from hallucinote.workspace import resolve_song_dir

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


class _ThreadLocalDepth:
    """Per-thread map of `id(conn)` -> nested-transaction depth.

    sqlite3.Connection doesn't allow attribute assignment, so reentrant
    `transaction()` tracks SAVEPOINT depth in a side mapping keyed by
    `id(conn)`. The mapping is backed by `threading.local`, so each thread
    sees only its own depth counter for a given connection. This matters
    because sqlite3 connections are not safe to share across threads
    *while a transaction is open*; even when a future caller hands a
    connection to a worker thread, the depth bookkeeping must not interleave
    with another thread's BEGIN/SAVEPOINT sequence on a different connection
    whose `id()` happens to collide (Python recycles `id()` once an object
    is GC'd). Single-threaded behavior is byte-identical to the old plain
    dict — `.get(id(conn), 0)` returns the calling thread's depth.

    Only the three operations `transaction()` uses are exposed:
    ``get(key, default)``, ``__setitem__``, and ``pop(key, default)``.
    """

    def __init__(self) -> None:
        self._local = threading.local()

    def _store(self) -> dict[int, int]:
        store = getattr(self._local, "depth", None)
        if store is None:
            store = {}
            self._local.depth = store
        return store

    def get(self, key: int, default: int = 0) -> int:
        return self._store().get(key, default)

    def __setitem__(self, key: int, value: int) -> None:
        self._store()[key] = value

    def pop(self, key: int, default: int | None = None) -> int | None:
        return self._store().pop(key, default)


# Per-thread nested-transaction depth keyed by `id(conn)`. Entries are
# explicitly popped when the outermost block closes (success or exception),
# so threads that fully unwind leave no residue. A connection GC'd
# mid-transaction (rare, abnormal) can leak one int entry in its thread's
# store, which is fine at this scale.
_TRANSACTION_DEPTH = _ThreadLocalDepth()


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
    _rebuild_disposable_tables(conn)
    _migrate_events_drop_fks(conn)
    conn.executescript(_SCHEMA_PATH.read_text())
    _ensure_added_columns(conn)
    return conn


def _rebuild_disposable_tables(conn: sqlite3.Connection) -> None:
    """One-shot rebuilds for DISPOSABLE sync-state tables whose shape changed
    in a way ``ALTER TABLE`` can't express (constraint changes). Dropping
    here is safe by design — these tables cache re-derivable sync state,
    never authored content. Runs before ``schema.sql`` so the CREATE TABLE
    IF NOT EXISTS recreates the new shape.

    - ``performed_automation`` pre-session-keying (ENV-7G4K): the original
      table was UNIQUE(envelope_id) — session-blind, so a second Live set
      false-skipped every arc. Rebuilt as UNIQUE(envelope_id, session_id);
      dropped fingerprints just mean the next push re-performs each arc
      (slower, never wrong).
    - ``markdown_refs`` pre-attempt-ledger (ATL-7K3M): the ``kind`` CHECK
      gained ``'attempt'`` and two columns (``outcome``/``resolution``) — a
      CHECK-domain change ALTER can't express, so an existing DB would reject
      every ``kind='attempt'`` row. markdown_refs is a rebuildable projection
      of the on-disk markdown corpus (reindex_corpus repopulates it on the next
      recall-on-read), so dropping it loses no authored content — only the
      cached projection, which is re-derived from disk. Staleness signal: the
      table exists but lacks the ``outcome`` column. Drop the paired FTS5 index
      too; both are recreated by schema.sql's CREATE ... IF NOT EXISTS.
    """
    rows = conn.execute("PRAGMA table_info(performed_automation)").fetchall()
    if rows and "session_id" not in {r["name"] for r in rows}:
        conn.execute("DROP TABLE performed_automation")
    md_rows = conn.execute("PRAGMA table_info(markdown_refs)").fetchall()
    if md_rows and "outcome" not in {r["name"] for r in md_rows}:
        conn.execute("DROP TABLE markdown_refs")
        conn.execute("DROP TABLE IF EXISTS markdown_refs_fts")


def _migrate_events_drop_fks(conn: sqlite3.Connection) -> None:
    """EVT-6H9R: drop the ON DELETE SET NULL FKs from a legacy `events` table.

    The audit log is append-only and must not lose lineage to a cascade: the
    original ``song_id`` / ``clip_id`` / ``request_id`` columns were live FKs
    with ``ON DELETE SET NULL``, so deleting a clip nulled ``clip_id`` on
    every event that ever touched it. The new shape (see ``schema.sql``)
    carries stable ids with NO foreign keys — the ids may dangle after the
    referenced row is deleted; that is the point.

    SQLite cannot ALTER a foreign key away, so this is the table-recreate
    pattern: build the new-shape table, copy every row byte-for-byte (same
    ids, seqs, timestamps, payloads), drop the old table, rename, recreate
    the indexes. Runs before ``schema.sql``'s ``CREATE TABLE IF NOT EXISTS``
    so a fresh DB never enters here (no ``events`` table yet) and a migrated
    DB is already final-shape when the script runs.

    Detection: ``PRAGMA foreign_key_list(events)`` non-empty. Idempotent —
    the migrated table has no FKs, so re-open is a no-op. Safe with
    ``PRAGMA foreign_keys=ON``: no table references ``events``, and the new
    table has no outgoing FKs to check during the copy. The whole rebuild is
    one transaction, so a crash mid-migration leaves the legacy table intact.
    """
    fks = conn.execute("PRAGMA foreign_key_list(events)").fetchall()
    if not fks:
        return  # fresh DB (no table -> empty list) or already migrated
    # Guard: the copy below names exactly the 10 legacy columns. If a legacy
    # events table ever carries anything else (a fork, a hand-patched DB),
    # migrating would silently drop that column's data — fail loudly instead.
    expected = ["id", "seq", "ts", "kind", "payload_json", "song_id",
                "clip_id", "actor", "reason", "request_id"]
    actual = [
        r["name"]
        for r in conn.execute("PRAGMA table_info(events)").fetchall()
    ]
    if sorted(actual) != sorted(expected):
        raise RuntimeError(
            "events FK migration refused: the legacy table's columns "
            f"({actual}) don't match the expected 10 ({expected}). "
            "Migrating would silently drop data in the unexpected "
            "column(s) — extend _migrate_events_drop_fks to carry them."
        )
    with transaction(conn):
        conn.execute(
            """CREATE TABLE events_new (
                   id              TEXT PRIMARY KEY,
                   seq             INTEGER NOT NULL UNIQUE,
                   ts              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                   kind            TEXT NOT NULL,
                   payload_json    TEXT NOT NULL,
                   song_id         TEXT,
                   clip_id         TEXT,
                   actor           TEXT NOT NULL,
                   reason          TEXT,
                   request_id      TEXT
               )"""
        )
        conn.execute(
            """INSERT INTO events_new
                   (id, seq, ts, kind, payload_json, song_id, clip_id,
                    actor, reason, request_id)
               SELECT id, seq, ts, kind, payload_json, song_id, clip_id,
                      actor, reason, request_id
               FROM events"""
        )
        conn.execute("DROP TABLE events")
        conn.execute("ALTER TABLE events_new RENAME TO events")
        # Self-contained: the old indexes died with the old table. schema.sql
        # would recreate them right after, but the migration must leave a
        # complete table regardless of what runs next.
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_seq ON events(seq)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_kind ON events(kind)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_song ON events(song_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_clip ON events(clip_id)")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_request ON events(request_id)"
        )


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
    # Audio-analysis MVP follow-on: sends gains a per-send composer-declared
    # RT60 intent. NULL on non-reverb sends (delays, parallel comp, undeclared).
    # The audio analyzer reads non-NULL rows to verify per-return RT60 from
    # the captured ring-out. CHECK matches schema.sql.
    (
        "sends",
        "intended_rt60_s",
        "REAL CHECK (intended_rt60_s IS NULL OR intended_rt60_s > 0.0)",
    ),
    # ARR-7M3D: sections gains the authored per-section energy intent (0..1
    # ordinal). NULL on pre-column DBs and on sections authored without an
    # energy declaration. The energy-realization lens reads non-NULL rows to
    # rank declared intent vs measured per-section intensity. CHECK matches
    # schema.sql.
    (
        "sections",
        "energy",
        "REAL CHECK (energy IS NULL OR (energy >= 0.0 AND energy <= 1.0))",
    ),
    # CLP-AUD1 (AUD-1M4V stage 0a): clips gain the kind discriminator +
    # wave-1 audio fields. Existing rows are all MIDI — the DEFAULT keeps
    # them valid with audio columns NULL. start/end markers carry Live's
    # dual unit (beats when warping=1, seconds when warping=0); see the
    # clips block in schema.sql for full column semantics.
    ("clips", "kind", "TEXT NOT NULL DEFAULT 'midi'"),
    ("clips", "audio_file", "TEXT"),
    ("clips", "audio_gain", "REAL"),
    ("clips", "pitch_coarse", "INTEGER"),
    ("clips", "pitch_fine", "REAL"),
    ("clips", "warping", "INTEGER"),
    ("clips", "warp_mode", "INTEGER"),
    ("clips", "start_marker", "REAL"),
    ("clips", "end_marker", "REAL"),
    # SMP-7K2D: devices gain a sample-instrument assignment — the song-relative
    # (assets/) or absolute path of a sampler's assigned sample, stored as
    # authored and resolved at push via paths.resolve_audio_path (the SAME
    # resolver clips.audio_file uses). NULL for every non-sampler device. Window
    # / reverse / pitch / gain stay device_parameters + envelopes, not columns.
    # See .prawduct/artifacts/plans/SMP-7K2D/design.md.
    ("devices", "audio_file", "TEXT"),
    # SDC-7K3M: device sidechain SOURCE routing (symmetric with track input
    # routing) — a semantic FK to the source track + the input channel. Existing
    # devices get NULL (no sidechain source). Resolved to/from Live's
    # display_name at push/pull; the S/C On/Gain/Mix params round-trip separately
    # as device_parameters. target FK self-references tracks ON DELETE SET NULL.
    ("devices", "sidechain_source_track_id",
     "TEXT REFERENCES tracks(id) ON DELETE SET NULL"),
    ("devices", "sidechain_source_channel", "TEXT"),
    # AUD-7R3M / SMP-7K2D: clips gain `reverse` — the missing playback-param
    # sibling of the CLP-AUD1 family (NULL/0 = forward, 1 = reversed). Existing
    # rows get NULL (forward). Materialized at push as Live's clip reverse, a
    # playback parameter, not a derived file.
    ("clips", "reverse", "INTEGER"),
    # RTE-1K9T: track signal routing (output + input) + monitor switch (D6).
    # Existing rows get NULL across all seven (no routing authored) -- the
    # DEFAULT-NULL keeps every pre-column track valid. The routing target is a
    # SEMANTIC reference (kind + FK target_id + channel), never Live's
    # display_name; see the tracks block in schema.sql + set_track_routing.
    # target_id self-FKs `tracks` (the requests.parent_id precedent — a
    # self-referential FK added via ALTER) with ON DELETE SET NULL.
    # CHECK asymmetry: output_routing_kind + monitoring_state are CHECK-
    # constrained (closed domains); input_routing_kind is plain TEXT (open
    # hardware-bound domain — the mutator validates). Keep each CHECK clause
    # in sync with schema.sql's CREATE TABLE by hand: the canary only verifies
    # column *presence* (PRAGMA table_info names), NOT the CHECK-clause text,
    # so a divergent CHECK between the fresh-DB (schema.sql) and migrated-DB
    # (this ALTER) paths would NOT be caught here.
    (
        "tracks",
        "output_routing_kind",
        "TEXT CHECK (output_routing_kind IS NULL OR "
        "output_routing_kind IN ('master','track','sends_only','ext_out'))",
    ),
    ("tracks", "output_routing_target_id", "TEXT REFERENCES tracks(id) ON DELETE SET NULL"),
    ("tracks", "output_routing_channel", "TEXT"),
    ("tracks", "input_routing_kind", "TEXT"),
    ("tracks", "input_routing_target_id", "TEXT REFERENCES tracks(id) ON DELETE SET NULL"),
    ("tracks", "input_routing_channel", "TEXT"),
    (
        "tracks",
        "monitoring_state",
        "TEXT CHECK (monitoring_state IS NULL OR "
        "monitoring_state IN ('In','Auto','Off'))",
    ),
    # NODE-ADDR Chunk C: per-DrumChain authorship. Both nullable — NULL on every
    # non-drum chain (a plain Chain has neither attribute) and on drum chains at
    # the Live default (choke 0 / out_note == in_note). Existing rows get NULL.
    # `choke_group` = Live's choke-group id (0 = none); `out_note` = the MIDI
    # transpose target. Set via the set_chain_properties mutator at capture/pull.
    ("device_chains", "choke_group", "INTEGER"),
    ("device_chains", "out_note", "INTEGER"),
    # NODE-ADDR Chunk F: per-chain mixer state — present on EVERY chain (not just
    # DrumChains). All nullable, NULL = the chain's preset/Live default (unmuted /
    # unsoloed / unity volume / centre pan). `mute`/`solo` = 0/1 bools; `volume`
    # (0..1) / `pan` (-1..1) = the ChainMixerDevice volume/panning param values.
    ("device_chains", "mute", "INTEGER"),
    ("device_chains", "solo", "INTEGER"),
    ("device_chains", "volume", "REAL"),
    ("device_chains", "pan", "REAL"),
    # DEV-4P7R: the raw continuous channel on device params + nested overrides.
    # UNCLAMPED (no [0,1] CHECK, unlike value_normalized) — the only authorable
    # form for a quantized continuous param whose raw range != [0,1] and whose
    # display is non-monotonic (Wavetable LFO S. Rate). Existing rows get NULL.
    # Set by set_device_parameter / replace_device_param_overrides; pushed via
    # set_parameter's raw `value`. Keep in sync with schema.sql's CREATE TABLEs.
    ("device_parameters", "value_raw", "REAL"),
    ("device_param_overrides", "value_raw", "REAL"),
    # MICROTUNE (TUN-4Q7W): songs gain the alternate-tuning bolt-on columns. Both
    # nullable, NULL = 12-TET (every existing song migrates to NULL, untouched).
    # `tuning_ref` = song-relative path to the cached `.ascl`; `tuning_data` = the
    # derived JSON blob the mapper / writer / drift-verify read. Set together by
    # set_song_tuning; the core path reads neither. See hallucinote.tuning.
    ("songs", "tuning_ref", "TEXT"),
    ("songs", "tuning_data", "TEXT"),
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
_ROOT_RESOLVE = object()  # sentinel: "resolve the song dir via env/marker/legacy"


def resolve_db_path(
    slug: str,
    *,
    root: Path | str = _ROOT_RESOLVE,  # type: ignore[assignment]
    branch: str | None = _BRANCH_PROBE_GIT,  # type: ignore[assignment]
) -> Path:
    """Per-branch DB filename: `<song_dir>/<slug>-<branch>.db` inside a repo,
    falling back to `<song_dir>/<slug>.db` outside a repo or on detached HEAD.

    The song directory comes from one of two paths:

    - **explicit `root`** — `<root>/<slug>/…`. `build.py` passes
      `root=Path(__file__).parent.parent`, so a song resolves its own DB
      relative to its file regardless of cwd.
    - **resolved `root`** (the default) — the song dir is resolved via the
      project-root contract (`HALLUCINOTE_SONGS_ROOT` → a `hallucinote.toml`
      marker → legacy `songs/<slug>`; see `hallucinote.workspace`). This is
      what lets a long-running MCP server, launched with cwd ≠ the song's repo,
      still find a song that lives in its own repo.

    **Either way the branch is probed in the resolved song dir** — the song's
    own repo — falling back to the process cwd only when that dir does not
    exist yet. So the two forms return the same filename for the same song, and
    neither depends on where the process was launched from.

    The branch name is sanitized by replacing `/` with `--` so `feature/foo`
    becomes `feature--foo` — mirrors `.prawduct/.pr-reviews/` naming so
    behavior is predictable for the canonical "feature/X" gitflow shape.

    `branch` is an escape hatch primarily for testing — pass `None` to force
    the no-branch fallback, or a literal string to skip the git probe. Default
    triggers the real git probe.
    """
    if root is _ROOT_RESOLVE:
        song_dir = resolve_song_dir(slug)
    else:
        song_dir = Path(root) / slug
    # Probe the song's OWN repo (it may differ from the process cwd), but only
    # if it already exists — a not-yet-built song dir falls back to the process
    # cwd so a fresh `build.py --reset` still gets the branch.
    #
    # BOTH root paths probe the same place, deliberately: the explicit-root
    # branch used to probe the process cwd instead, which broke the very
    # guarantee `root=` exists to provide. `build.py` passes
    # `root=Path(__file__).parent.parent` so a song resolves its DB relative to
    # its own file regardless of cwd — but with a cwd probe the *filename* was
    # still cwd-dependent, so running a song's build.py from a checkout of
    # another repo minted `<slug>-<that-repo's-branch>.db` while every reader
    # looked for `<slug>-<songs-repo-branch>.db`. Two DBs for one song, plus
    # duplicated sibling push-state files, split by which shell you happened to
    # be in. Keeping the two paths identical is what makes
    # `resolve_db_path(slug)` and `resolve_db_path(slug, root=...)` agree.
    probe_cwd = song_dir if song_dir.is_dir() else None
    if branch is _BRANCH_PROBE_GIT:
        resolved_branch = _git_current_branch(cwd=probe_cwd)
    else:
        resolved_branch = branch
    if resolved_branch is None:
        return song_dir / f"{slug}.db"
    sanitized = resolved_branch.replace("/", "--")
    return song_dir / f"{slug}-{sanitized}.db"


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
    tracked in the module-level `_TRANSACTION_DEPTH` per-thread map keyed by
    `id(conn)` (sqlite3.Connection doesn't permit attribute assignment); the
    per-thread backing keeps the counter from interleaving across threads.

    **BEGIN IMMEDIATE, not DEFERRED** (EVT-6H9R hardening): every mutator
    reads before it writes (validation SELECTs, `_emit`'s MAX(seq)). Under a
    DEFERRED BEGIN in WAL, another connection committing between that read
    and the first write makes the read-to-write snapshot upgrade fail
    IMMEDIATELY with "database is locked" — `busy_timeout` is never consulted
    for a stale-snapshot upgrade. IMMEDIATE takes the write lock at BEGIN, so
    a concurrent writer queues on the busy handler instead (the MCP-server +
    build.py two-writer topology). `transaction()` is write-path-only, so
    the earlier lock costs no read concurrency (WAL readers never block on
    the writer).

    Usage:
        with transaction(conn):
            conn.execute(...)
            conn.execute(...)
    """
    key = id(conn)
    depth = _TRANSACTION_DEPTH.get(key, 0)
    if depth == 0:
        conn.execute("BEGIN IMMEDIATE")
        _TRANSACTION_DEPTH[key] = 1
        # The depth counter is popped in a `finally`: if COMMIT (or even
        # ROLLBACK) itself raises, a leaked depth>=1 would make every later
        # mutator on this connection SAVEPOINT into a transaction nobody
        # commits — silent write loss. With the pop guaranteed, a broken
        # connection fails LOUDLY on its next BEGIN instead.
        try:
            try:
                yield
            except BaseException:  # prawduct:allow prawduct/broad-except -- ROLLBACK must run for KeyboardInterrupt/SystemExit/CancelledError too — a Ctrl-C mid-batch must not leave a half-written DB. Re-raises.
                # Roll back on ANY exception — including KeyboardInterrupt /
                # SystemExit / asyncio.CancelledError — then re-raise. The DB
                # must not be left in a half-written state because the user
                # hit Ctrl-C mid-batch.
                conn.execute("ROLLBACK")
                raise
            try:
                conn.execute("COMMIT")
            except BaseException:  # prawduct:allow prawduct/broad-except -- a failed COMMIT (e.g. disk I/O) leaves the transaction open; roll back so the connection stays usable, then surface the COMMIT failure. Re-raises.
                # A failed COMMIT (e.g. disk I/O error) leaves the
                # transaction open — roll it back so the connection stays
                # usable, then surface the COMMIT failure.
                conn.execute("ROLLBACK")
                raise
        finally:
            _TRANSACTION_DEPTH.pop(key, None)
    else:
        # Nested call — use a SAVEPOINT so inner failures don't poison the
        # outer transaction. SAVEPOINT names must be unique within a
        # connection; depth makes them so. Depth restore mirrors the
        # outermost branch's finally (a failed RELEASE must not leak depth).
        sp = f"sp_{depth}"
        conn.execute(f"SAVEPOINT {sp}")
        _TRANSACTION_DEPTH[key] = depth + 1
        try:
            try:
                yield
            except BaseException:  # prawduct:allow prawduct/broad-except -- the nested-SAVEPOINT unwind must run for BaseException too, or an inner failure poisons the outer transaction. Re-raises.
                conn.execute(f"ROLLBACK TO SAVEPOINT {sp}")
                conn.execute(f"RELEASE SAVEPOINT {sp}")
                raise
            conn.execute(f"RELEASE SAVEPOINT {sp}")
        finally:
            _TRANSACTION_DEPTH[key] = depth
