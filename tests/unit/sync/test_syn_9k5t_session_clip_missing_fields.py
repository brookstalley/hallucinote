"""SYN-9K5T: session-clip pull must warn on a populated entry missing both
`name` and `length`, for parity with the arrangement-clip apply.

`_apply_arrangement_clips_for_track` warns ("entry missing start_beats or
length") when a probe entry lacks the fields it diffs on.
`_apply_session_clips_for_track` diffs on `name` + `length`; a populated
(`empty=False`) entry carrying neither used to silently no-op via the
`_floats_differ(None, X) -> False` / `name_in is not None` guards. This
test pins the explicit warning so the asymmetry is gone.
"""
from __future__ import annotations

import pytest

from hallucinote.db import init_db, mutations as M, queries as Q
from hallucinote.sync.pull._core import ApplyResult
from hallucinote.sync.pull.clips import _apply_session_clips_for_track


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "missing.db")
    yield c
    c.close()


def _track_with_clip(conn):
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
    return song, session, track, clip


def test_populated_entry_missing_name_and_length_warns(conn):
    song, session, track, clip = _track_with_clip(conn)
    out = ApplyResult()
    # Populated slot, but the probe omitted BOTH name and length.
    result = {"clips": [{"clip_index": 1, "empty": False}]}
    _apply_session_clips_for_track(
        conn, song_id=song, session_id=session, track_id=track,
        result=result, out=out, actor="sync", request_id=None, reason=None,
    )

    # No silent no-op: an explicit warning surfaces, and nothing mutated.
    assert out.mutations == 0
    assert any(
        "missing both 'name' and 'length'" in w for w in out.warnings
    )
    # The DB clip is untouched.
    rows = Q.get_clips_for_track(conn, track)
    assert len(rows) == 1
    assert rows[0]["name"] == "Verse"


def test_populated_entry_with_name_only_still_diffs(conn):
    """A populated entry carrying `name` (but no length) is NOT treated as
    fieldless — it still drift-matches on name as before."""
    song, session, track, clip = _track_with_clip(conn)
    out = ApplyResult()
    result = {"clips": [{"clip_index": 1, "empty": False, "name": "Chorus"}]}
    _apply_session_clips_for_track(
        conn, song_id=song, session_id=session, track_id=track,
        result=result, out=out, actor="sync", request_id=None, reason=None,
    )

    assert not any(
        "missing both 'name' and 'length'" in w for w in out.warnings
    )
    rows = Q.get_clips_for_track(conn, track)
    assert rows[0]["name"] == "Chorus"
