"""Live's clip slots are 1-based; the mutator refuses slot 0 at author time.

A slot-0 row is accepted silently and halts the clips push phase mid-way
through, after every earlier clip was already created (#473). The floor
belongs where the author is, as ``_require_bar_floor`` already does for
arrangement bars. The schema carries the same floor as a CHECK for fresh DBs.
"""
from __future__ import annotations

import sqlite3

import pytest

from hallucinote.db import init_db
from hallucinote.db import mutations as M


@pytest.fixture
def song(tmp_path):
    conn = init_db(tmp_path / "floor.db")
    sid = M.create_song(conn, name="floor", key="Dm")
    midi = M.create_track(conn, song_id=sid, track_index=1, name="midi", kind="midi")
    audio = M.create_track(conn, song_id=sid, track_index=2, name="audio", kind="audio")
    try:
        yield conn, midi, audio
    finally:
        conn.close()


def test_create_clip_refuses_slot_zero_with_the_reason(song):
    conn, midi, _ = song
    with pytest.raises(ValueError, match=r"slot must be >= 1.*1-based.*enumerate"):
        M.create_clip(conn, track_id=midi, slot=0, length_beats=4.0)
    assert conn.execute("SELECT COUNT(*) FROM clips").fetchone()[0] == 0


def test_create_audio_clip_refuses_slot_zero(song):
    conn, _, audio = song
    with pytest.raises(ValueError, match=r"slot must be >= 1"):
        M.create_audio_clip(
            conn, track_id=audio, slot=0, length_beats=4.0, audio_file="assets/x.wav"
        )


def test_slot_one_is_the_floor(song):
    conn, midi, _ = song
    cid = M.create_clip(conn, track_id=midi, slot=1, length_beats=4.0)
    assert conn.execute("SELECT slot FROM clips WHERE id = ?", (cid,)).fetchone()[0] == 1


def test_schema_check_holds_the_same_floor(song):
    """A write that bypassed the mutator would still be refused by the schema."""
    conn, midi, _ = song
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO clips (id, track_id, slot, length_beats) VALUES ('x', ?, 0, 4.0)",
            (midi,),
        )
