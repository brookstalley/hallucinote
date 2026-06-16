"""tuning_ref/tuning_data through the real DB: mutator, query, bridge, inertness."""
from __future__ import annotations

import sqlite3

import pytest

from hallucinote.db import events as E
from hallucinote.db import init_db
from hallucinote.db import mutations as M
from hallucinote.db import queries as Q
from hallucinote.tuning.model import TuningData
from hallucinote.tuning.store import load_song_tuning, persist_tuning

from .fixtures import EDO_19


# Pre-MICROTUNE songs table: no tuning_ref / tuning_data columns. Used to prove
# an existing song DB migrates to NULL (the additive ALTER path, not just fresh).
_PRE_MICROTUNE_SONGS = """
CREATE TABLE songs (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    title       TEXT,
    key         TEXT,
    timing_mode TEXT NOT NULL DEFAULT 'native',
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
"""


def test_existing_db_migrates_to_null_columns_untouched(tmp_path):
    # An old DB with a song row but no tuning columns...
    db_path = tmp_path / "old.db"
    old = sqlite3.connect(db_path)
    old.execute(_PRE_MICROTUNE_SONGS)
    old.execute("INSERT INTO songs (id, name, key) VALUES ('s1', 'old', 'Dm')")
    old.commit()
    old.close()

    # ...gains the columns on the next init_db (additive ALTER), and the
    # pre-existing row reads back NULL for both — untouched.
    conn = init_db(db_path)
    try:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(songs)")}
        assert {"tuning_ref", "tuning_data"} <= cols
        row = Q.get_song_tuning(conn, "s1")
        assert row["tuning_ref"] is None
        assert row["tuning_data"] is None
        assert conn.execute("SELECT key FROM songs WHERE id='s1'").fetchone()[0] == "Dm"
    finally:
        conn.close()


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "test.db")
    yield c
    c.close()


@pytest.fixture
def song(conn):
    return M.create_song(conn, name="t", key="Dm")


def _events_of_kind(conn, kind):
    return conn.execute(
        "SELECT payload_json FROM events WHERE kind = ? ORDER BY seq", (kind,)
    ).fetchall()


# ---------- the 99.99%: NULL path is untouched ----------


def test_fresh_song_is_12tet_both_columns_null(conn, song):
    row = Q.get_song_tuning(conn, song)
    assert row["tuning_ref"] is None
    assert row["tuning_data"] is None
    assert load_song_tuning(conn, song) is None


def test_get_song_tuning_unknown_song_is_none(conn):
    assert Q.get_song_tuning(conn, "nope") is None
    assert load_song_tuning(conn, "nope") is None


def test_creating_a_song_emits_no_tuning_event(conn, song):
    assert _events_of_kind(conn, E.SONG_TUNING_SET) == []


# ---------- the 0.01%: mutator + query round-trip ----------


def test_set_song_tuning_persists_both_columns(conn, song):
    M.set_song_tuning(
        conn, song_id=song, tuning_ref="tunings/19-edo.ascl",
        tuning_data=EDO_19.to_blob(),
    )
    row = Q.get_song_tuning(conn, song)
    assert row["tuning_ref"] == "tunings/19-edo.ascl"
    assert TuningData.from_blob(row["tuning_data"]) == EDO_19


def test_set_song_tuning_emits_event(conn, song):
    M.set_song_tuning(
        conn, song_id=song, tuning_ref="tunings/19-edo.ascl",
        tuning_data=EDO_19.to_blob(), actor="llm",
    )
    events = _events_of_kind(conn, E.SONG_TUNING_SET)
    assert len(events) == 1


def test_set_song_tuning_is_idempotent(conn, song):
    args = dict(
        song_id=song, tuning_ref="tunings/19-edo.ascl", tuning_data=EDO_19.to_blob(),
    )
    M.set_song_tuning(conn, **args)
    M.set_song_tuning(conn, **args)  # identical → no-op, no second event
    assert len(_events_of_kind(conn, E.SONG_TUNING_SET)) == 1


def test_set_song_tuning_can_clear_back_to_12tet(conn, song):
    M.set_song_tuning(
        conn, song_id=song, tuning_ref="tunings/x.ascl", tuning_data=EDO_19.to_blob(),
    )
    M.set_song_tuning(conn, song_id=song, tuning_ref=None, tuning_data=None)
    assert load_song_tuning(conn, song) is None
    assert len(_events_of_kind(conn, E.SONG_TUNING_SET)) == 2


# ---------- the bridge: cache + persist + load end-to-end ----------


def test_persist_tuning_caches_file_and_records_ref(conn, song, tmp_path):
    ref = persist_tuning(conn, song_id=song, song_dir=str(tmp_path), tuning=EDO_19)
    assert ref == "tunings/19-edo.ascl"
    assert (tmp_path / ref).is_file()              # cached .ascl on disk
    assert Q.get_song_tuning(conn, song)["tuning_ref"] == ref
    assert load_song_tuning(conn, song) == EDO_19  # blob round-trips back


def test_set_song_tuning_does_not_disturb_other_song_fields(conn, song):
    before = dict(Q.get_song(conn, song))
    M.set_song_tuning(
        conn, song_id=song, tuning_ref="tunings/x.ascl", tuning_data=EDO_19.to_blob(),
    )
    after = dict(Q.get_song(conn, song))
    # Only the two tuning columns + updated_at change; identity/key/timing intact.
    for field in ("id", "name", "title", "key", "timing_mode"):
        assert before[field] == after[field]
