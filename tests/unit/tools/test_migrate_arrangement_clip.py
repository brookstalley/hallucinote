"""Tests for tools/migrate_arrangement_clip.py.

One-shot migration that renames the legacy `arrangement` table to
`arrangement_clips`, recreates its indexes, renames the two ARRANGEMENT_*
event kinds, rewrites the JSON1 payload key, and updates
`ableton_links.db_kind`. PR review #19 / #24 left this tool without
automated coverage; the round-trip was verified manually on
falling-walking's real DB but the JSON1 payload-key rewrite and the
both-tables-present idempotency guard had no regression net.

Fixtures here seed a legacy-shape DB by initializing the live schema and
then running the inverse `ALTER TABLE` to recreate the pre-rename world —
mirrors `test_migrate_returns_strip_prefix.py`'s pattern of seeding raw
legacy data via `sqlite3` directly.
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import uuid
from pathlib import Path

import pytest

from hallucinote.db import init_db, mutations as M


_ROOT = Path(__file__).resolve().parents[3]
_MIGRATE_PATH = _ROOT / "tools" / "migrate_arrangement_clip.py"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "migrate_arrangement_clip", _MIGRATE_PATH,
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "song.db"


def _seed_post_rename_db(db_path: Path) -> tuple[str, str, str]:
    """Initialize a DB with the current schema and seed a song + track + clip.
    Returns (song_id, track_id, clip_id) for callers that need to attach an
    arrangement-clip row.
    """
    conn = init_db(db_path)
    sid = M.create_song(conn, name="t", key="Dm")
    tid = M.create_track(conn, song_id=sid, track_index=1, name="Drums",
                         instrument_uri="x")
    cid = M.create_clip(conn, track_id=tid, slot=1, length_beats=16.0,
                        name="verse")
    conn.commit()
    conn.close()
    return sid, tid, cid


def _downgrade_to_legacy_shape(db_path: Path) -> None:
    """Invert the migration: rename `arrangement_clips` -> `arrangement`,
    recreate the legacy indexes. Used to seed a pre-rename DB shape.
    The events + ableton_links downgrades are issued by the per-test
    seeders since not every test needs them.
    """
    conn = sqlite3.connect(str(db_path), timeout=10.0)
    try:
        conn.execute("BEGIN")
        conn.execute("ALTER TABLE arrangement_clips RENAME TO arrangement")
        for new_idx, old_idx, col in (
            ("idx_arrangement_clips_song",  "idx_arrangement_song",  "song_id"),
            ("idx_arrangement_clips_track", "idx_arrangement_track", "track_id"),
            ("idx_arrangement_clips_clip",  "idx_arrangement_clip",  "clip_id"),
        ):
            conn.execute(f"DROP INDEX IF EXISTS {new_idx}")
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS {old_idx} ON arrangement({col})"
            )
        conn.commit()
    finally:
        conn.close()


def _insert_legacy_event(
    conn: sqlite3.Connection,
    *,
    kind: str,
    payload: dict,
    actor: str = "build",
) -> str:
    """Insert an event row with the legacy `kind` + `payload` keys directly,
    so the migration sees pre-rename data shaped like an ALPHA-era DB.
    """
    event_id = uuid.uuid4().hex
    seq = conn.execute(
        "SELECT COALESCE(MAX(seq), 0) + 1 FROM events"
    ).fetchone()[0]
    conn.execute(
        """INSERT INTO events
               (id, seq, kind, payload_json, actor)
           VALUES (?, ?, ?, ?, ?)""",
        (event_id, seq, kind, json.dumps(payload, separators=(",", ":")), actor),
    )
    return event_id


def _legacy_ableton_links_row(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    db_id: str,
) -> None:
    """Insert an ableton_links row carrying the legacy db_kind='arrangement'."""
    # Need a session_id for the FK; mint one inline.
    session_id = uuid.uuid4().hex
    conn.execute(
        """INSERT INTO ableton_sessions (id, song_id, name)
           VALUES (?, ?, 'test-session')""",
        (session_id, song_id),
    )
    conn.execute(
        """INSERT INTO ableton_links
               (session_id, db_kind, db_id, ableton_index)
           VALUES (?, 'arrangement', ?, 1)""",
        (session_id, db_id),
    )


def test_table_and_indexes_renamed(db_path):
    """Step 1 + 2: table renames, three indexes recreated under new names."""
    _seed_post_rename_db(db_path)
    _downgrade_to_legacy_shape(db_path)

    counts = _load_module().migrate(db_path)
    assert counts["table_renamed"] == 1
    assert counts["indexes_recreated"] == 3

    conn = sqlite3.connect(str(db_path))
    try:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        assert "arrangement_clips" in tables
        assert "arrangement" not in tables
        indexes = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
            " AND name LIKE 'idx_arrangement%'"
        )}
        assert indexes == {
            "idx_arrangement_clips_song",
            "idx_arrangement_clips_track",
            "idx_arrangement_clips_clip",
        }
    finally:
        conn.close()


def test_event_kind_rename(db_path):
    """Step 3: arrangement_added -> arrangement_clip_added, ditto _removed."""
    _seed_post_rename_db(db_path)
    _downgrade_to_legacy_shape(db_path)

    conn = sqlite3.connect(str(db_path))
    try:
        _insert_legacy_event(conn, kind="arrangement_added",
                             payload={"foo": "bar"})
        _insert_legacy_event(conn, kind="arrangement_added",
                             payload={"foo": "baz"})
        _insert_legacy_event(conn, kind="arrangement_removed",
                             payload={"foo": "qux"})
        conn.commit()
    finally:
        conn.close()

    counts = _load_module().migrate(db_path)
    assert counts["events_kind_added"] == 2
    assert counts["events_kind_removed"] == 1

    conn = sqlite3.connect(str(db_path))
    try:
        kinds = sorted(r[0] for r in conn.execute(
            "SELECT kind FROM events WHERE kind LIKE 'arrangement%'"
        ))
        assert kinds == [
            "arrangement_clip_added",
            "arrangement_clip_added",
            "arrangement_clip_removed",
        ]
        # Pre-rename kinds must be gone (no `arrangement_added` / `arrangement_removed`).
        legacy = conn.execute(
            "SELECT COUNT(*) FROM events"
            " WHERE kind IN ('arrangement_added','arrangement_removed')"
        ).fetchone()[0]
        assert legacy == 0
    finally:
        conn.close()


def test_json1_payload_key_rewrite(db_path):
    """Step 4: payload key `arrangement_id` -> `arrangement_clip_id`. Only
    rows whose payload carries the old key are touched; other keys preserved.
    """
    _seed_post_rename_db(db_path)
    _downgrade_to_legacy_shape(db_path)

    conn = sqlite3.connect(str(db_path))
    try:
        _insert_legacy_event(
            conn, kind="arrangement_added",
            payload={"arrangement_id": "abc123", "start_bar": 0, "end_bar": 4},
        )
        _insert_legacy_event(
            conn, kind="arrangement_removed",
            payload={"arrangement_id": "def456"},
        )
        # An unrelated event with no arrangement_id — must be untouched.
        # Use a sentinel kind so it can't collide with seed-emitted events.
        _insert_legacy_event(
            conn, kind="test_sentinel_unrelated",
            payload={"foo": "bar", "baz": 42},
        )
        conn.commit()
    finally:
        conn.close()

    counts = _load_module().migrate(db_path)
    assert counts["events_payload_rewritten"] == 2

    conn = sqlite3.connect(str(db_path))
    try:
        # Renamed events carry the new payload key with the preserved value.
        added = [json.loads(r[0]) for r in conn.execute(
            "SELECT payload_json FROM events"
            " WHERE kind = 'arrangement_clip_added'"
        )]
        assert added == [
            {"arrangement_clip_id": "abc123", "start_bar": 0, "end_bar": 4}
        ]
        removed = [json.loads(r[0]) for r in conn.execute(
            "SELECT payload_json FROM events"
            " WHERE kind = 'arrangement_clip_removed'"
        )]
        assert removed == [{"arrangement_clip_id": "def456"}]
        # Unrelated rows must not have gained the new key.
        unrelated = [json.loads(r[0]) for r in conn.execute(
            "SELECT payload_json FROM events"
            " WHERE kind = 'test_sentinel_unrelated'"
        )]
        assert unrelated == [{"foo": "bar", "baz": 42}]
        assert "arrangement_clip_id" not in unrelated[0]
        # No legacy `arrangement_id` keys survive anywhere in the table.
        legacy_keys = conn.execute(
            "SELECT COUNT(*) FROM events"
            " WHERE json_extract(payload_json, '$.arrangement_id') IS NOT NULL"
        ).fetchone()[0]
        assert legacy_keys == 0
    finally:
        conn.close()


def test_ableton_links_db_kind_rename(db_path):
    """Step 5: ableton_links.db_kind = 'arrangement' -> 'arrangement_clip'."""
    sid, _, cid = _seed_post_rename_db(db_path)
    _downgrade_to_legacy_shape(db_path)

    conn = sqlite3.connect(str(db_path))
    try:
        _legacy_ableton_links_row(conn, song_id=sid, db_id=cid)
        conn.commit()
    finally:
        conn.close()

    counts = _load_module().migrate(db_path)
    assert counts["ableton_links_updated"] == 1

    conn = sqlite3.connect(str(db_path))
    try:
        kinds = [r[0] for r in conn.execute(
            "SELECT db_kind FROM ableton_links"
        )]
        assert kinds == ["arrangement_clip"]
    finally:
        conn.close()


def test_idempotent_second_run_is_noop(db_path):
    """Re-running on a DB already on the new schema is a clean no-op:
    no rows updated, no exception, exit cleanly. This is what the script
    promises in its docstring + the user-facing CLI prints.
    """
    _seed_post_rename_db(db_path)
    _downgrade_to_legacy_shape(db_path)

    # First run does the work.
    counts1 = _load_module().migrate(db_path)
    assert counts1["table_renamed"] == 1

    # Second run on the already-migrated DB returns all-zero counters.
    counts2 = _load_module().migrate(db_path)
    assert counts2 == {
        "table_renamed": 0,
        "indexes_recreated": 0,
        "events_kind_added": 0,
        "events_kind_removed": 0,
        "events_payload_rewritten": 0,
        "ableton_links_updated": 0,
    }


def test_both_tables_present_raises(db_path):
    """Step 0 guard: if both `arrangement` and `arrangement_clips` exist
    (operator created the new table by hand without dropping the legacy
    one), refuse rather than silently merging or duplicating rows.
    """
    _seed_post_rename_db(db_path)
    # New table exists from the seed. Now also create the legacy `arrangement`
    # table by hand to simulate a half-finished manual migration.
    conn = sqlite3.connect(str(db_path), timeout=10.0)
    try:
        conn.execute(
            """CREATE TABLE arrangement (
                id              TEXT PRIMARY KEY,
                song_id         TEXT NOT NULL,
                track_id        TEXT NOT NULL,
                clip_id         TEXT NOT NULL,
                start_bar       REAL NOT NULL,
                end_bar         REAL NOT NULL
            )"""
        )
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(RuntimeError, match="both .* tables exist"):
        _load_module().migrate(db_path)


def test_migrate_rolls_back_on_failure(db_path, monkeypatch):
    """The migrate() body wraps every step in a single transaction. If a
    step partway through raises, the rollback must leave the DB on the
    original (legacy) shape — no partial rename. Force a failure by
    monkeypatching conn.execute to raise on the ableton_links UPDATE.
    """
    _seed_post_rename_db(db_path)
    _downgrade_to_legacy_shape(db_path)

    mod = _load_module()
    real_connect = sqlite3.connect

    class _FailingConn:
        """Proxy that injects a failure on a specific SQL substring."""
        def __init__(self, inner):
            self._inner = inner
            self.row_factory = inner.row_factory

        def __setattr__(self, name, value):
            if name in ("_inner",):
                object.__setattr__(self, name, value)
            else:
                object.__setattr__(self, name, value)
                # also propagate row_factory etc. to the inner conn
                if name == "row_factory":
                    self._inner.row_factory = value

        def execute(self, sql, *args):
            if "ableton_links SET db_kind" in sql:
                raise sqlite3.OperationalError("simulated failure")
            return self._inner.execute(sql, *args)

        def commit(self):
            return self._inner.commit()

        def rollback(self):
            return self._inner.rollback()

        def close(self):
            return self._inner.close()

    def _wrap_connect(*args, **kwargs):
        return _FailingConn(real_connect(*args, **kwargs))

    monkeypatch.setattr(mod.sqlite3, "connect", _wrap_connect)

    with pytest.raises(sqlite3.OperationalError, match="simulated failure"):
        mod.migrate(db_path)

    # Post-rollback: legacy table still present, new table not created.
    conn = sqlite3.connect(str(db_path))
    try:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        assert "arrangement" in tables
        assert "arrangement_clips" not in tables
    finally:
        conn.close()
