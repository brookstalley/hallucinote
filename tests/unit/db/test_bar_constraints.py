"""The 1-based bar convention is enforced in two layers, and this suite is the
regression gate for both:

1. **Mutator teaching error (primary).** Every bar-position mutator validates
   ``>= 1.0`` at the write boundary via ``_require_bar_floor`` and raises a
   ``ValueError`` explaining the convention — fired *before* any SQL, so the
   caller never sees a cryptic ``IntegrityError`` (or, for ``arrangement_clips``
   which had no CHECK, a far-away push-time crash in ``_position_bar_to_beats``).
2. **Schema CHECK (backstop).** ``sections`` / ``tempo_map`` /
   ``time_signature_map`` / ``cue_points`` / ``arrangement_clips`` all carry
   ``CHECK (start_bar >= 1.0)`` (or ``position_bar``) so a raw INSERT that
   bypasses the mutator path is still rejected.

The convention is documented in ``src/hallucinote/db/schema.sql``.
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


# ---------------------------------------------------------------------------
# Layer 1 — mutator teaching errors (the primary, user-facing contract)
# ---------------------------------------------------------------------------

_FLOOR = "must be >= 1.0"


@pytest.mark.parametrize("bad", [0.5, 0.0, -1.0])
def test_sections_reject_start_bar_below_one(conn, song, bad):
    with pytest.raises(ValueError, match=_FLOOR):
        M.create_section(conn, song_id=song, name="v", start_bar=bad, end_bar=8.0)


def test_sections_accept_start_bar_one(conn, song):
    sid = M.create_section(conn, song_id=song, name="v", start_bar=1.0, end_bar=9.0)
    assert isinstance(sid, str)


@pytest.mark.parametrize("bad", [0.5, 0.0, -1.0])
def test_tempo_map_rejects_start_bar_below_one(conn, song, bad):
    with pytest.raises(ValueError, match=_FLOOR):
        M.add_tempo_point(conn, song_id=song, start_bar=bad, tempo_bpm=120.0)


def test_tempo_map_accepts_start_bar_one(conn, song):
    pid = M.add_tempo_point(conn, song_id=song, start_bar=1.0, tempo_bpm=120.0)
    assert isinstance(pid, str)


@pytest.mark.parametrize("bad", [0.5, 0.0, -1.0])
def test_time_signature_map_rejects_start_bar_below_one(conn, song, bad):
    with pytest.raises(ValueError, match=_FLOOR):
        M.add_time_signature_point(
            conn, song_id=song, start_bar=bad, numerator=4, denominator=4
        )


def test_time_signature_map_accepts_start_bar_one(conn, song):
    pid = M.add_time_signature_point(
        conn, song_id=song, start_bar=1.0, numerator=4, denominator=4
    )
    assert isinstance(pid, str)


@pytest.mark.parametrize("bad", [0.5, 0.0, -1.0])
def test_cue_points_reject_position_bar_below_one(conn, song, bad):
    with pytest.raises(ValueError, match=_FLOOR):
        M.add_cue_point(conn, song_id=song, position_bar=bad, name="bad")


def test_cue_points_accept_position_bar_one(conn, song):
    pid = M.add_cue_point(conn, song_id=song, position_bar=1.0, name="ok")
    assert isinstance(pid, str)


@pytest.mark.parametrize("bad", [0.5, 0.0, -1.0])
def test_arrangement_clips_reject_start_bar_below_one(conn, song, bad):
    # The floor guard fires before any FK lookup, so dummy track/clip ids are
    # fine — we're pinning the boundary check, not a full insert.
    with pytest.raises(ValueError, match=_FLOOR):
        M.add_arrangement_clip(
            conn, song_id=song, track_id="t", clip_id="c",
            start_bar=bad, end_bar=8.0,
        )


def test_arrangement_clips_reject_end_bar_not_after_start(conn, song):
    with pytest.raises(ValueError, match="end_bar"):
        M.add_arrangement_clip(
            conn, song_id=song, track_id="t", clip_id="c",
            start_bar=4.0, end_bar=4.0,
        )


# ---------------------------------------------------------------------------
# Layer 2 — schema CHECK backstop (raw INSERT bypassing the mutator path)
# ---------------------------------------------------------------------------
# FKs are switched off so the CHECK (not a missing track/clip row) is what
# rejects the insert; CHECK constraints are evaluated regardless of the pragma.


def _raw_insert_rejected(conn, sql, params):
    conn.execute("PRAGMA foreign_keys=OFF")
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(sql, params)
    finally:
        conn.execute("PRAGMA foreign_keys=ON")


def test_schema_check_sections(conn, song):
    _raw_insert_rejected(
        conn,
        "INSERT INTO sections (id, song_id, name, start_bar, end_bar) "
        "VALUES (?,?,?,?,?)",
        ("s", song, "v", 0.5, 8.0),
    )


def test_schema_check_tempo_map(conn, song):
    _raw_insert_rejected(
        conn,
        "INSERT INTO tempo_map (id, song_id, start_bar, tempo_bpm) VALUES (?,?,?,?)",
        ("p", song, 0.5, 120.0),
    )


def test_schema_check_time_signature_map(conn, song):
    _raw_insert_rejected(
        conn,
        "INSERT INTO time_signature_map (id, song_id, start_bar, numerator, denominator) "
        "VALUES (?,?,?,?,?)",
        ("m", song, 0.5, 4, 4),
    )


def test_schema_check_cue_points(conn, song):
    _raw_insert_rejected(
        conn,
        "INSERT INTO cue_points (id, song_id, position_bar) VALUES (?,?,?)",
        ("q", song, 0.5),
    )


def test_schema_check_arrangement_clips_start_bar(conn, song):
    _raw_insert_rejected(
        conn,
        "INSERT INTO arrangement_clips (id, song_id, track_id, clip_id, start_bar, end_bar) "
        "VALUES (?,?,?,?,?,?)",
        ("a", song, "t", "c", 0.5, 8.0),
    )


def test_schema_check_arrangement_clips_end_bar_ordering(conn, song):
    _raw_insert_rejected(
        conn,
        "INSERT INTO arrangement_clips (id, song_id, track_id, clip_id, start_bar, end_bar) "
        "VALUES (?,?,?,?,?,?)",
        ("a", song, "t", "c", 4.0, 2.0),
    )
