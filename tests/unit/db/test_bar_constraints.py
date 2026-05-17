"""Schema CHECK constraints enforcing the 1-based bar convention.

The convention is documented in `src/hallucinote/db/schema.sql` and
`docs/mcp-requirements.md`. Before J-6 it was unenforced; this suite is the
regression gate for the four score-half tables.
"""
from __future__ import annotations

import sqlite3

import pytest

from hallucinote.db import init_db, mutations as M


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "bar_constraints.db")
    yield c
    c.close()


@pytest.fixture
def song(conn):
    return M.create_song(conn, name="t", key="Dm")


def test_sections_reject_start_bar_below_one(conn, song):
    with pytest.raises(sqlite3.IntegrityError):
        M.create_section(conn, song_id=song, name="v", start_bar=0.5, end_bar=8.0)


def test_sections_reject_start_bar_zero(conn, song):
    with pytest.raises(sqlite3.IntegrityError):
        M.create_section(conn, song_id=song, name="v", start_bar=0.0, end_bar=8.0)


def test_sections_accept_start_bar_one(conn, song):
    sid = M.create_section(conn, song_id=song, name="v", start_bar=1.0, end_bar=9.0)
    assert isinstance(sid, str)


def test_tempo_map_rejects_start_bar_below_one(conn, song):
    with pytest.raises(sqlite3.IntegrityError):
        M.add_tempo_point(conn, song_id=song, start_bar=0.5, tempo_bpm=120.0)


def test_tempo_map_rejects_start_bar_zero(conn, song):
    with pytest.raises(sqlite3.IntegrityError):
        M.add_tempo_point(conn, song_id=song, start_bar=0.0, tempo_bpm=120.0)


def test_tempo_map_accepts_start_bar_one(conn, song):
    pid = M.add_tempo_point(conn, song_id=song, start_bar=1.0, tempo_bpm=120.0)
    assert isinstance(pid, str)


def test_time_signature_map_rejects_start_bar_below_one(conn, song):
    with pytest.raises(sqlite3.IntegrityError):
        M.add_time_signature_point(
            conn, song_id=song, start_bar=0.5, numerator=4, denominator=4
        )


def test_time_signature_map_rejects_start_bar_zero(conn, song):
    with pytest.raises(sqlite3.IntegrityError):
        M.add_time_signature_point(
            conn, song_id=song, start_bar=0.0, numerator=4, denominator=4
        )


def test_time_signature_map_accepts_start_bar_one(conn, song):
    pid = M.add_time_signature_point(
        conn, song_id=song, start_bar=1.0, numerator=4, denominator=4
    )
    assert isinstance(pid, str)


def test_cue_points_reject_position_bar_below_one(conn, song):
    with pytest.raises(sqlite3.IntegrityError):
        M.add_cue_point(conn, song_id=song, position_bar=0.5, name="bad")


def test_cue_points_reject_position_bar_zero(conn, song):
    with pytest.raises(sqlite3.IntegrityError):
        M.add_cue_point(conn, song_id=song, position_bar=0.0, name="bad")


def test_cue_points_accept_position_bar_one(conn, song):
    pid = M.add_cue_point(conn, song_id=song, position_bar=1.0, name="ok")
    assert isinstance(pid, str)
