"""AUD-5M8H — the capture audit event.

`ableton_render` recorded the DB seq in the capture manifest but emitted no
event, so "when was this take captured" could only be answered by listing
`captures/`. `record_audio_capture` puts capture timestamps into the audit log,
queryable through the existing `queries.get_events_for_song`.
"""
from __future__ import annotations

import json

from hallucinote.db import events as E, init_db, mutations as M, queries as Q


def _song(conn):
    return M.create_song(conn, name="take-song", title="Take Song")


def test_record_audio_capture_emits_a_queryable_event(tmp_path):
    conn = init_db(tmp_path / "t.db")
    song_id = _song(conn)

    event_id = M.record_audio_capture(
        conn,
        song_id=song_id,
        captures_dir="/songs/take-song/captures/20260811-120000",
        manifest_seq=41,
        track_count=4,
    )
    assert event_id is not None

    events = [
        e for e in Q.get_events_for_song(conn, song_id)
        if e["kind"] == E.AUDIO_CAPTURED
    ]
    assert len(events) == 1
    payload = json.loads(events[0]["payload_json"])
    assert payload == {
        "captures_dir": "/songs/take-song/captures/20260811-120000",
        "manifest_seq": 41,
        "track_count": 4,
    }
    assert events[0]["ts"], "the timestamp is the whole point of the event"


def test_re_recording_the_same_captures_dir_is_a_no_op(tmp_path):
    """The caller is a POLL: the agent polls render status until it reads
    `done`, and every poll after that reads `done` again. Without dedupe a
    single take would write one event per poll."""
    conn = init_db(tmp_path / "t.db")
    song_id = _song(conn)
    kwargs = dict(
        song_id=song_id,
        captures_dir="/songs/take-song/captures/20260811-120000",
        manifest_seq=41,
        track_count=4,
    )

    first = M.record_audio_capture(conn, **kwargs)
    second = M.record_audio_capture(conn, **kwargs)
    third = M.record_audio_capture(conn, **kwargs)

    assert first is not None
    assert second is None and third is None, "repeat polls must not re-emit"
    events = [
        e for e in Q.get_events_for_song(conn, song_id)
        if e["kind"] == E.AUDIO_CAPTURED
    ]
    assert len(events) == 1


def test_a_second_take_records_its_own_event(tmp_path):
    """Dedupe is per captures_dir, not per song — a later take is a new take."""
    conn = init_db(tmp_path / "t.db")
    song_id = _song(conn)

    M.record_audio_capture(
        conn, song_id=song_id,
        captures_dir="/songs/take-song/captures/20260811-120000",
        manifest_seq=41, track_count=4,
    )
    M.record_audio_capture(
        conn, song_id=song_id,
        captures_dir="/songs/take-song/captures/20260811-131500",
        manifest_seq=58, track_count=5,
    )

    events = [
        e for e in Q.get_events_for_song(conn, song_id)
        if e["kind"] == E.AUDIO_CAPTURED
    ]
    assert len(events) == 2
    dirs = {json.loads(e["payload_json"])["captures_dir"] for e in events}
    assert len(dirs) == 2


def test_missing_provenance_is_recorded_as_null_not_dropped(tmp_path):
    """`db_seq` is absent when the server couldn't read it; the event should
    still land (the capture DID happen) carrying an explicit null rather than
    silently omitting the key."""
    conn = init_db(tmp_path / "t.db")
    song_id = _song(conn)

    M.record_audio_capture(
        conn, song_id=song_id,
        captures_dir="/songs/take-song/captures/20260811-120000",
    )

    events = [
        e for e in Q.get_events_for_song(conn, song_id)
        if e["kind"] == E.AUDIO_CAPTURED
    ]
    payload = json.loads(events[0]["payload_json"])
    assert payload["manifest_seq"] is None
    assert payload["track_count"] is None
