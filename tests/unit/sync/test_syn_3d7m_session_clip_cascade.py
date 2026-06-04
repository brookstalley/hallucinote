"""SYN-3D7M: session-clip pull must make the `arrangement_clips` cascade
observable, not silent.

`_apply_session_clips_for_track` deletes a DB clip when its session slot is
cleared (or falls out of Ableton's reported range). Deleting a `clips` row
cascades to every `arrangement_clips` placement that referenced it
(`clip_id REFERENCES clips ON DELETE CASCADE`). Per the "never silently
drop" discipline, that cross-domain side effect must surface in
`out.details`. This test pins that the cascaded count is reported.
"""
from __future__ import annotations

import pytest

from hallucinote.db import init_db, mutations as M, queries as Q
from hallucinote.sync.pull._core import ApplyResult
from hallucinote.sync.pull.clips import _apply_session_clips_for_track


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "cascade.db")
    yield c
    c.close()


def _setup_track_with_session_and_arrangement_clip(conn):
    song = M.create_song(conn, name="t", key="Dm")
    session = M.create_ableton_session(conn, song_id=song, name="draft")
    track = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=track,
        ableton_index=1,
    )
    clip = M.create_clip(
        conn, track_id=track, slot=1, length_beats=4.0, name="Verse"
    )
    # Two arrangement placements both reference the one session clip.
    M.add_arrangement_clip(
        conn, song_id=song, track_id=track, clip_id=clip,
        start_bar=1.0, end_bar=2.0,
    )
    M.add_arrangement_clip(
        conn, song_id=song, track_id=track, clip_id=clip,
        start_bar=5.0, end_bar=6.0,
    )
    return song, session, track, clip


def test_empty_slot_delete_reports_cascaded_arrangement_placements(conn):
    song, session, track, clip = (
        _setup_track_with_session_and_arrangement_clip(conn)
    )
    assert Q.count_arrangement_clips_for_clip(conn, clip) == 2

    out = ApplyResult()
    # Ableton reports the slot as empty -> the DB clip must be deleted, and
    # the two arrangement placements cascade away.
    result = {"clips": [{"clip_index": 1, "empty": True}]}
    _apply_session_clips_for_track(
        conn, song_id=song, session_id=session, track_id=track,
        result=result, out=out, actor="sync", request_id=None, reason=None,
    )

    # The clip and its arrangement placements are gone.
    assert Q.get_clips_for_track(conn, track) == []
    assert Q.count_arrangement_clips_for_clip(conn, clip) == 0

    # The cascade is observable in details — not silent.
    cascade_lines = [d for d in out.details if "cascade removed" in d]
    assert len(cascade_lines) == 1
    assert "2 arrangement placements" in cascade_lines[0]


def test_delete_without_arrangement_placements_omits_cascade_note(conn):
    """A clip with no arrangement placements deletes cleanly with no
    cascade note (the note appears only when something actually cascaded)."""
    song = M.create_song(conn, name="t", key="Dm")
    session = M.create_ableton_session(conn, song_id=song, name="draft")
    track = M.create_track(conn, song_id=song, track_index=1, name="Bass")
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=track,
        ableton_index=1,
    )
    M.create_clip(conn, track_id=track, slot=1, length_beats=4.0, name="A")

    out = ApplyResult()
    result = {"clips": [{"clip_index": 1, "empty": True}]}
    _apply_session_clips_for_track(
        conn, song_id=song, session_id=session, track_id=track,
        result=result, out=out, actor="sync", request_id=None, reason=None,
    )

    assert out.mutations == 1
    assert not any("cascade removed" in d for d in out.details)
