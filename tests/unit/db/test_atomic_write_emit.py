"""EVT-6H9R chunk 1: state-write + event-emit are one atomic unit.

Connections are autocommit (`isolation_level=None`), so before the `_atomic`
wrapper each statement inside a mutator committed individually — a crash
between the state write and `_emit()` left a state row with no event. These
tests simulate the crash by raising between write and emit (and after emit):
an exception is transactionally equivalent to a process kill, since a killed
process simply never reaches COMMIT and SQLite discards the open WAL
transaction on next open.
"""
from __future__ import annotations

import pytest

from hallucinote.db import init_db, mutations as M
from hallucinote.db import events as E
from hallucinote.db.connection import transaction
from hallucinote.db.mutations import tracks as tracks_mod
from hallucinote.db.mutations import notes as notes_mod


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "atomic.db")
    yield c
    c.close()


@pytest.fixture
def song(conn):
    return M.create_song(conn, name="atomic-test", key="Dm")


def _count(conn, table, **where):
    clauses = " AND ".join(f"{k} = ?" for k in where) or "1=1"
    return conn.execute(
        f"SELECT COUNT(*) AS n FROM {table} WHERE {clauses}",
        tuple(where.values()),
    ).fetchone()["n"]


class _Boom(RuntimeError):
    pass


def _raise_boom(*_args, **_kwargs):
    raise _Boom("injected crash")


def test_crash_between_write_and_emit_leaves_no_state_row(
    conn, song, monkeypatch,
):
    """Killed between the tracks INSERT and its _emit: the INSERT must not
    survive alone — no state-row-without-event."""
    monkeypatch.setattr(tracks_mod, "_emit", _raise_boom)
    with pytest.raises(_Boom):
        M.create_track(conn, song_id=song, track_index=1, name="Drums")
    assert _count(conn, "tracks") == 0
    assert _count(conn, "events", kind=E.TRACK_CREATED) == 0


def test_crash_after_emit_leaves_no_event_without_state(
    conn, song, monkeypatch,
):
    """Killed after _emit but before the mutator finishes (_touch_song):
    the event must not survive without... anything — the whole mutation
    rolls back, state row and event together."""
    monkeypatch.setattr(tracks_mod, "_touch_song", _raise_boom)
    with pytest.raises(_Boom):
        M.create_track(conn, song_id=song, track_index=1, name="Drums")
    assert _count(conn, "tracks") == 0
    assert _count(conn, "events", kind=E.TRACK_CREATED) == 0


def test_multi_statement_mutator_is_all_or_nothing(conn, song):
    """insert_notes writes one INSERT per note; a mid-batch validation
    failure (note 3 has a negative start) must roll back the notes already
    inserted. Pre-EVT-6H9R autocommit committed notes 1-2 and lost the
    event — a desynced half-write."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Keys")
    cid = M.create_clip(conn, track_id=tid, slot=1, length_beats=4.0)
    good = {"pitch": 60, "start_beats": 0.0, "duration_beats": 1.0, "velocity": 90}
    bad = {"pitch": 64, "start_beats": -0.5, "duration_beats": 1.0, "velocity": 90}
    with pytest.raises(ValueError, match="negative"):
        M.insert_notes(conn, clip_id=cid, notes=[good, dict(good, pitch=62), bad])
    assert _count(conn, "notes") == 0
    assert _count(conn, "events", kind=E.NOTES_INSERTED) == 0


def test_failed_inner_mutator_does_not_poison_outer_transaction(
    conn, song, monkeypatch,
):
    """Mutators nest via SAVEPOINTs: a caller batching mutators in its own
    transaction() keeps the work of the successful calls when it catches a
    failing one — only the failed mutator's writes roll back."""
    with transaction(conn):
        tid = M.create_track(conn, song_id=song, track_index=1, name="Bass")
        monkeypatch.setattr(tracks_mod, "_emit", _raise_boom)
        with pytest.raises(_Boom):
            M.set_track_mixer(conn, track_id=tid, volume=0.5)
        monkeypatch.undo()
    assert _count(conn, "tracks") == 1
    assert _count(conn, "events", kind=E.TRACK_CREATED) == 1
    row = conn.execute(
        "SELECT volume FROM tracks WHERE id = ?", (tid,)
    ).fetchone()
    assert row["volume"] is None  # mixer write rolled back with its event
    assert _count(conn, "events", kind=E.TRACK_MIXER_SET) == 0


def test_kill_before_commit_discards_on_next_open(tmp_path):
    """The WAL half of the story: an open transaction that never COMMITs is
    invisible to a fresh connection — what a killed process leaves behind."""
    db_path = tmp_path / "killed.db"
    c1 = init_db(db_path)
    sid = M.create_song(c1, name="killed-song")
    c1.execute("BEGIN")
    c1.execute(
        "INSERT INTO tracks (id, song_id, track_index, name, kind) "
        "VALUES ('deadbeef', ?, 1, 'orphan', 'midi')",
        (sid,),
    )
    # No COMMIT — simulate the kill by abandoning the connection.
    c1.close()  # sqlite rolls back the open transaction on close, same as a kill
    c2 = init_db(db_path)
    try:
        assert _count(c2, "tracks") == 0
        assert _count(c2, "events", kind="song_created") == 1
    finally:
        c2.close()


def test_replace_clip_notes_still_atomic_under_wrapper(conn, song, monkeypatch):
    """replace_clip_notes had its own transaction() pre-EVT-6H9R; under the
    wrapper that block becomes a SAVEPOINT. The delete+reinsert must still
    be all-or-nothing when the emit fails."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Keys")
    cid = M.create_clip(conn, track_id=tid, slot=1, length_beats=4.0)
    note = {"pitch": 60, "start_beats": 0.0, "duration_beats": 1.0, "velocity": 90}
    M.insert_notes(conn, clip_id=cid, notes=[note])
    monkeypatch.setattr(notes_mod, "_emit", _raise_boom)
    with pytest.raises(_Boom):
        M.replace_clip_notes(
            conn, clip_id=cid, notes=[dict(note, pitch=72), dict(note, pitch=76)],
        )
    monkeypatch.undo()
    rows = conn.execute("SELECT pitch FROM notes ORDER BY pitch").fetchall()
    assert [r["pitch"] for r in rows] == [60]  # original note survives intact
