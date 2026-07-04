"""EVT-6H9R chunk 2: the `events` table carries stable ids, not live FKs.

An append-only audit log must not lose lineage to a cascade — the legacy
``song_id`` / ``clip_id`` / ``request_id`` columns were ``REFERENCES ... ON
DELETE SET NULL``, so deleting a clip nulled ``clip_id`` on every event that
ever touched it. ``init_db`` now runs a table-recreate migration
(``connection._migrate_events_drop_fks``) on legacy DBs; fresh DBs get the
FK-free shape straight from ``schema.sql``.
"""
from __future__ import annotations

import sqlite3

import pytest

from hallucinote.db import init_db, mutations as M
from hallucinote.db import events as E


# Legacy pre-EVT-6H9R shape, verbatim from the old schema.sql. Used to
# manufacture a legacy DB for the migration tests (raw DDL is the point here:
# init_db can no longer produce this shape).
_LEGACY_EVENTS_DDL = """
CREATE TABLE events (
    id              TEXT PRIMARY KEY,
    seq             INTEGER NOT NULL UNIQUE,
    ts              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    kind            TEXT NOT NULL,
    payload_json    TEXT NOT NULL,
    song_id         TEXT REFERENCES songs(id) ON DELETE SET NULL,
    clip_id         TEXT REFERENCES clips(id) ON DELETE SET NULL,
    actor           TEXT NOT NULL,
    reason          TEXT,
    request_id      TEXT REFERENCES requests(id) ON DELETE SET NULL
)
"""

_ALL_COLUMNS = (
    "id, seq, ts, kind, payload_json, song_id, clip_id, actor, reason, "
    "request_id"
)


def _fk_list(conn: sqlite3.Connection) -> list:
    return conn.execute("PRAGMA foreign_key_list(events)").fetchall()


def _dump_events(conn: sqlite3.Connection) -> list[tuple]:
    return [
        tuple(r)
        for r in conn.execute(
            f"SELECT {_ALL_COLUMNS} FROM events ORDER BY seq"
        ).fetchall()
    ]


def _make_legacy_db(db_path) -> list[tuple]:
    """Build a real song DB, then regress its events table to the legacy
    FK shape. Returns the event-row dump for byte-for-byte comparison."""
    conn = init_db(db_path)
    song = M.create_song(conn, name="legacy-song", key="Am")
    track = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    clip = M.create_clip(conn, track_id=track, slot=1, length_beats=8.0)
    with M.request(conn, actor="llm", intent="notes") as rid:
        M.insert_notes(
            conn,
            clip_id=clip,
            notes=[{"pitch": 60, "start_beats": 0.0, "duration_beats": 1.0,
                    "velocity": 100}],
            request_id=rid,
        )
    # Regress: recreate events with the legacy FK DDL (test-only surgery —
    # init_db can't produce this shape anymore, which is the point).
    conn.execute("ALTER TABLE events RENAME TO events_current")
    conn.execute(_LEGACY_EVENTS_DDL)
    conn.execute(
        f"INSERT INTO events ({_ALL_COLUMNS}) "
        f"SELECT {_ALL_COLUMNS} FROM events_current"
    )
    conn.execute("DROP TABLE events_current")
    assert _fk_list(conn), "legacy fixture must actually carry FKs"
    dump = _dump_events(conn)
    conn.close()
    return dump


def test_fresh_db_events_has_no_foreign_keys(tmp_path):
    conn = init_db(tmp_path / "fresh.db")
    try:
        assert _fk_list(conn) == []
    finally:
        conn.close()


def test_legacy_db_migrates_on_open_preserving_rows(tmp_path):
    db_path = tmp_path / "legacy.db"
    before = _make_legacy_db(db_path)
    assert len(before) >= 5  # song/track/clip/request open+close/notes

    conn = init_db(db_path)
    try:
        assert _fk_list(conn) == [], "migration must drop every events FK"
        # Byte-for-byte: same ids, seqs, timestamps, payloads, provenance.
        assert _dump_events(conn) == before
        # Indexes survived the table recreate.
        idx = {
            r["name"] for r in conn.execute(
                "PRAGMA index_list(events)"
            ).fetchall()
        }
        assert {
            "idx_events_seq", "idx_events_kind", "idx_events_song",
            "idx_events_clip", "idx_events_request",
        } <= idx
    finally:
        conn.close()


def test_migration_is_idempotent(tmp_path):
    db_path = tmp_path / "legacy2.db"
    before = _make_legacy_db(db_path)
    for _ in range(2):
        conn = init_db(db_path)
        conn.close()
    conn = init_db(db_path)
    try:
        assert _fk_list(conn) == []
        assert _dump_events(conn) == before
    finally:
        conn.close()


def test_migrated_db_still_writes_events(tmp_path):
    """The recreated table keeps working end-to-end: seq continues
    monotonically and new emits land."""
    db_path = tmp_path / "legacy3.db"
    before = _make_legacy_db(db_path)
    conn = init_db(db_path)
    try:
        song = conn.execute("SELECT id FROM songs").fetchone()["id"]
        M.create_track(conn, song_id=song, track_index=2, name="Bass")
        rows = _dump_events(conn)
        assert len(rows) == len(before) + 1
        assert rows[-1][1] == before[-1][1] + 1  # seq monotonic across migration
    finally:
        conn.close()


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "lineage.db")
    yield c
    c.close()


def test_deleting_clip_no_longer_nulls_event_lineage(conn):
    """The reason the FKs had to go: a cascade must not rewrite history."""
    song = M.create_song(conn, name="lineage-song")
    track = M.create_track(conn, song_id=song, track_index=1, name="Keys")
    clip = M.create_clip(conn, track_id=track, slot=1, length_beats=4.0)
    M.insert_notes(
        conn,
        clip_id=clip,
        notes=[{"pitch": 64, "start_beats": 0.0, "duration_beats": 1.0,
                "velocity": 96}],
    )
    M.delete_clip(conn, clip_id=clip)
    rows = conn.execute(
        "SELECT kind, clip_id FROM events WHERE clip_id IS NOT NULL "
        "ORDER BY seq"
    ).fetchall()
    kinds = [r["kind"] for r in rows]
    # Every clip-touching event keeps the stable id after the delete —
    # including the delete event itself (stampable now that the FK is gone).
    assert E.CLIP_CREATED in kinds
    assert E.NOTES_INSERTED in kinds
    assert E.CLIP_DELETED in kinds
    assert all(r["clip_id"] == clip for r in rows)


def test_deleting_song_no_longer_nulls_event_lineage(conn):
    song = M.create_song(conn, name="doomed-song")
    M.create_track(conn, song_id=song, track_index=1, name="Keys")
    conn.execute("DELETE FROM songs WHERE id = ?", (song,))  # cascade path
    rows = conn.execute(
        "SELECT song_id FROM events ORDER BY seq"
    ).fetchall()
    assert rows and all(r["song_id"] == song for r in rows)


def test_migration_refuses_unexpected_legacy_columns(tmp_path):
    """The copy list names exactly the 10 legacy columns; a legacy table
    carrying anything else must fail LOUDLY instead of silently dropping
    that column's data during the recreate."""
    db_path = tmp_path / "rogue.db"
    _make_legacy_db(db_path)
    raw = sqlite3.connect(db_path)  # test-only surgery on the legacy shape
    raw.execute("ALTER TABLE events ADD COLUMN rogue_notes TEXT")
    raw.commit()
    raw.close()
    with pytest.raises(RuntimeError, match="rogue_notes|don't match"):
        init_db(db_path)
