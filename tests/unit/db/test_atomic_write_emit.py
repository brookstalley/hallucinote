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

import sqlite3

import pytest

from hallucinote.db import init_db, mutations as M
from hallucinote.db import events as E
from hallucinote.db.connection import _TRANSACTION_DEPTH, connect, transaction
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


# ---------------------------------------------------------------------------
# Critic round: BEGIN IMMEDIATE (snapshot-upgrade exposure) + depth-counter
# leak on COMMIT failure.
# ---------------------------------------------------------------------------


def test_concurrent_writer_queues_instead_of_failing_fast(tmp_path, monkeypatch):
    """Two-writer topology (MCP server + build.py): the mutator transaction
    must take the write lock at BEGIN (IMMEDIATE), not at its first write.

    Under the old plain-DEFERRED BEGIN, conn A's mutator read (validation
    SELECT / _emit's MAX(seq)) pinned a snapshot; conn B committing a write
    in between made A's read-to-write upgrade fail IMMEDIATELY with
    "database is locked" (busy_timeout is never consulted for a
    stale-snapshot upgrade). With IMMEDIATE, the roles invert: B is the one
    that queues on the busy handler while A completes.

    The hook runs inside conn A's open mutator transaction (after BEGIN,
    before A's writes) and attempts B's write there. Deterministic: pre-fix
    B's write SUCCEEDED in the hook and A's own INSERT then failed fast;
    post-fix B gets BUSY (50 ms cap) and A succeeds.
    """
    db_path = tmp_path / "two-writers.db"
    conn_a = init_db(db_path)
    song = M.create_song(conn_a, name="two-writer-song")
    conn_b = connect(db_path)
    conn_b.execute("PRAGMA busy_timeout = 50")
    outcome: dict[str, str] = {}
    real = tracks_mod._resolve_actor_and_request

    def hooked(actor, request_id):
        # Inside conn A's transaction: A has BEGUN but not yet written.
        try:
            conn_b.execute(
                "UPDATE songs SET key = 'Zz' WHERE id = ?", (song,)
            )
            outcome["b"] = "wrote"
        except sqlite3.OperationalError:
            outcome["b"] = "busy"
        return real(actor, request_id)

    monkeypatch.setattr(tracks_mod, "_resolve_actor_and_request", hooked)
    tid = M.create_track(conn_a, song_id=song, track_index=1, name="Drums")
    monkeypatch.undo()

    # A held the write lock from BEGIN: B queued and timed out, A succeeded.
    assert outcome["b"] == "busy"
    assert _count(conn_a, "tracks") == 1
    assert _count(conn_a, "events", kind=E.TRACK_CREATED) == 1
    assert tid
    conn_b.close()
    conn_a.close()


class _CommitBoomConn:
    """Stub connection: transaction() only needs `.execute` + a stable id().
    COMMIT raises once, like a disk I/O error at commit time."""

    def __init__(self):
        self.calls: list[str] = []

    def execute(self, sql, *args):
        self.calls.append(sql)
        if sql == "COMMIT":
            raise sqlite3.OperationalError("disk I/O error")


def test_commit_failure_does_not_leak_transaction_depth():
    """If COMMIT itself raises, the depth counter must still unwind (a
    leaked depth>=1 would make every later mutator on this connection
    SAVEPOINT into a transaction nobody commits — silent write loss), and
    the open transaction must be rolled back so the connection stays usable."""
    fake = _CommitBoomConn()
    with pytest.raises(sqlite3.OperationalError, match="disk I/O"):
        with transaction(fake):
            pass
    assert _TRANSACTION_DEPTH.get(id(fake), 0) == 0
    assert fake.calls == ["BEGIN IMMEDIATE", "COMMIT", "ROLLBACK"]
    # The connection is reusable: a fresh transaction BEGINs at depth 0
    # (it would raise "cannot start a transaction within a transaction"
    # against a real connection had the rollback not happened).
    fake2_calls_before = len(fake.calls)
    with pytest.raises(sqlite3.OperationalError):
        with transaction(fake):
            pass
    assert fake.calls[fake2_calls_before] == "BEGIN IMMEDIATE"
    assert _TRANSACTION_DEPTH.get(id(fake), 0) == 0
