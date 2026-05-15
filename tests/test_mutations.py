"""Mutator + event-emission round-trip tests."""
from __future__ import annotations

import json

import pytest

from songwright.db import init_db, mutations as M, queries as Q
from songwright.db import events as E


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "test.db")
    yield c
    c.close()


@pytest.fixture
def song(conn):
    return M.create_song(conn, name="t", key="Dm")


@pytest.fixture
def track(conn, song):
    return M.create_track(conn, song_id=song, track_index=1, name="Drums", instrument_uri="x")


@pytest.fixture
def clip(conn, track):
    return M.create_clip(conn, track_id=track, slot=1, length_beats=16.0, name="verse_drums")


def _events(conn):
    return conn.execute(
        "SELECT kind, payload_json, actor, reason, request_id FROM events ORDER BY seq"
    ).fetchall()


# ---------- creation chain ----------


def test_create_song_emits_event(conn):
    sid = M.create_song(conn, name="x", key="Dm")
    rows = _events(conn)
    assert len(rows) == 1
    assert rows[0]["kind"] == E.SONG_CREATED
    payload = json.loads(rows[0]["payload_json"])
    assert payload == {"name": "x", "key": "Dm", "timing_mode": "native"}
    # song id is a 32-char UUID hex
    assert isinstance(sid, str) and len(sid) == 32 and all(c in "0123456789abcdef" for c in sid)


def test_create_track_emits_event_and_links_to_song(conn, song):
    tid = M.create_track(conn, song_id=song, track_index=2, name="Bass")
    ev = _events(conn)[-1]
    assert ev["kind"] == E.TRACK_CREATED
    payload = json.loads(ev["payload_json"])
    assert payload["track_id"] == tid
    assert payload["track_index"] == 2


def test_create_clip_with_generator_call(conn, track):
    cid = M.create_clip(
        conn,
        track_id=track,
        slot=1,
        length_beats=16.0,
        name="verse_drums",
        section_role="verse",
        generator_call={"fn": "trip_hop_drums", "kwargs": {"bars": 4}},
    )
    row = Q.get_clip(conn, cid)
    assert row["section_role"] == "verse"
    assert json.loads(row["generator_call_json"])["fn"] == "trip_hop_drums"
    ev = _events(conn)[-1]
    assert ev["kind"] == E.CLIP_CREATED


# ---------- notes ----------


def _make_note(pitch=36, start=0.0, dur=0.25, vel=100, tags=None):
    n = {"pitch": pitch, "start_beats": start, "duration_beats": dur, "velocity": vel}
    if tags:
        n["tags"] = tags
    return n


def test_insert_notes_returns_ids_and_emits_event(conn, clip):
    notes = [_make_note(start=0.0), _make_note(start=1.0, tags=["ghost"])]
    ids = M.insert_notes(conn, clip_id=clip, notes=notes)
    assert len(ids) == 2 and all(isinstance(i, str) and len(i) == 32 for i in ids)
    out = Q.get_notes_for_clip(conn, clip)
    assert len(out) == 2
    assert out[1]["tags"] == ["ghost"]
    ev = _events(conn)[-1]
    assert ev["kind"] == E.NOTES_INSERTED
    assert json.loads(ev["payload_json"])["count"] == 2


def test_replace_clip_notes_is_atomic(conn, clip):
    M.insert_notes(conn, clip_id=clip, notes=[_make_note() for _ in range(5)])
    new_ids = M.replace_clip_notes(
        conn, clip_id=clip, notes=[_make_note(pitch=38), _make_note(pitch=42)]
    )
    out = Q.get_notes_for_clip(conn, clip)
    assert len(out) == 2
    assert {n["pitch"] for n in out} == {38, 42}
    # Old ids gone
    assert all(n["id"] in new_ids for n in out)
    # Event records prev_count and new_count
    last = _events(conn)[-1]
    assert last["kind"] == E.CLIP_NOTES_REPLACED
    p = json.loads(last["payload_json"])
    assert p["prev_count"] == 5 and p["new_count"] == 2


def test_update_note_partial(conn, clip):
    [nid] = M.insert_notes(conn, clip_id=clip, notes=[_make_note(vel=50)])
    M.update_note(conn, note_id=nid, velocity=110)
    [out] = Q.get_notes_for_clip(conn, clip)
    assert out["velocity"] == 110
    assert out["pitch"] == 36  # unchanged
    ev = _events(conn)[-1]
    assert ev["kind"] == E.NOTE_UPDATED
    assert json.loads(ev["payload_json"])["changes"] == {"velocity": 110}


def test_update_note_rejects_unknown_fields(conn, clip):
    [nid] = M.insert_notes(conn, clip_id=clip, notes=[_make_note()])
    with pytest.raises(ValueError, match="unsupported"):
        M.update_note(conn, note_id=nid, foo="bar")


def test_update_note_tags_serialization(conn, clip):
    [nid] = M.insert_notes(conn, clip_id=clip, notes=[_make_note(tags=["old"])])
    M.update_note(conn, note_id=nid, tags=["new", "ghost"])
    [out] = Q.get_notes_for_clip(conn, clip)
    assert out["tags"] == ["new", "ghost"]


def test_delete_notes(conn, clip):
    ids = M.insert_notes(conn, clip_id=clip, notes=[_make_note(start=i) for i in range(3)])
    M.delete_notes(conn, note_ids=ids[:2])
    out = Q.get_notes_for_clip(conn, clip)
    assert len(out) == 1 and out[0]["id"] == ids[2]
    ev = _events(conn)[-1]
    assert ev["kind"] == E.NOTES_DELETED


def test_update_notes_by_tag_velocity_delta(conn, clip):
    M.insert_notes(
        conn,
        clip_id=clip,
        notes=[
            _make_note(start=0.0, vel=40, tags=["ghost"]),
            _make_note(start=1.0, vel=100),  # no tag
            _make_note(start=2.0, vel=50, tags=["ghost"]),
        ],
    )
    n = M.update_notes_by_tag(conn, clip_id=clip, tag="ghost", velocity_delta=5)
    assert n == 2
    notes = Q.get_notes_for_clip(conn, clip)
    by_start = {round(x["start_beats"], 2): x for x in notes}
    assert by_start[0.0]["velocity"] == 45
    assert by_start[1.0]["velocity"] == 100  # unchanged
    assert by_start[2.0]["velocity"] == 55
    ev = _events(conn)[-1]
    assert ev["kind"] == E.NOTES_BULK_UPDATED


def test_update_notes_by_tag_clamps_velocity(conn, clip):
    M.insert_notes(conn, clip_id=clip, notes=[_make_note(vel=125, tags=["loud"])])
    M.update_notes_by_tag(conn, clip_id=clip, tag="loud", velocity_delta=20)
    [out] = Q.get_notes_for_clip(conn, clip)
    assert out["velocity"] == 127


def test_update_notes_by_tag_requires_one_arg(conn, clip):
    with pytest.raises(ValueError):
        M.update_notes_by_tag(conn, clip_id=clip, tag="x")
    with pytest.raises(ValueError):
        M.update_notes_by_tag(conn, clip_id=clip, tag="x", velocity_delta=1, velocity_set=2)


# ---------- arrangement ----------


def test_arrangement_lifecycle(conn, song, track, clip):
    aid = M.add_arrangement(
        conn, song_id=song, track_id=track, clip_id=clip, start_bar=1, end_bar=16
    )
    rows = Q.get_arrangement_for_song(conn, song)
    assert len(rows) == 1 and rows[0]["id"] == aid

    M.remove_arrangement(conn, arrangement_id=aid)
    assert Q.get_arrangement_for_song(conn, song) == []
    kinds = [r["kind"] for r in _events(conn)]
    assert kinds[-2:] == [E.ARRANGEMENT_ADDED, E.ARRANGEMENT_REMOVED]


# ---------- foreign keys / cascades ----------


def test_clip_delete_cascades_to_notes(conn, track):
    cid = M.create_clip(conn, track_id=track, slot=1, length_beats=4.0)
    M.insert_notes(conn, clip_id=cid, notes=[_make_note() for _ in range(3)])
    assert len(Q.get_notes_for_clip(conn, cid)) == 3
    M.delete_clip(conn, clip_id=cid)
    assert Q.get_notes_for_clip(conn, cid) == []


# ---------- ableton sync wiring (sessions + links projection) ----------


def test_link_db_to_ableton_records_in_session(conn, song, track, clip):
    sess = M.create_ableton_session(conn, song_id=song, name="draft")
    M.link_db_to_ableton(
        conn, session_id=sess, db_kind="track", db_id=track, ableton_index=3
    )
    M.link_db_to_ableton(
        conn, session_id=sess, db_kind="clip", db_id=clip, ableton_index=2
    )

    assert Q.get_ableton_link(conn, session_id=sess, db_kind="track", db_id=track) == 3
    assert Q.get_ableton_link(conn, session_id=sess, db_kind="clip", db_id=clip) == 2

    # Core rows are untouched — projection separation
    track_cols = [r[1] for r in conn.execute("PRAGMA table_info(tracks)").fetchall()]
    clip_cols = [r[1] for r in conn.execute("PRAGMA table_info(clips)").fetchall()]
    assert "ableton_track_index" not in track_cols
    assert "ableton_clip_index" not in clip_cols

    kinds = [r["kind"] for r in _events(conn)]
    assert kinds.count(E.ABLETON_LINK_SET) == 2
    assert E.ABLETON_SESSION_CREATED in kinds


def test_link_db_to_ableton_upserts_existing(conn, song, track):
    sess = M.create_ableton_session(conn, song_id=song)
    M.link_db_to_ableton(conn, session_id=sess, db_kind="track", db_id=track, ableton_index=1)
    M.link_db_to_ableton(conn, session_id=sess, db_kind="track", db_id=track, ableton_index=7)
    # Single row, updated value
    rows = conn.execute(
        "SELECT ableton_index FROM ableton_links WHERE session_id=? AND db_kind='track' AND db_id=?",
        (sess, track),
    ).fetchall()
    assert [r["ableton_index"] for r in rows] == [7]


def test_link_db_to_ableton_rejects_unknown_kind(conn, song, track):
    sess = M.create_ableton_session(conn, song_id=song)
    with pytest.raises(ValueError, match="db_kind"):
        M.link_db_to_ableton(
            conn, session_id=sess, db_kind="bogus", db_id=track, ableton_index=0
        )


def test_two_sessions_isolate_bindings(conn, song, track):
    """Same db row, two sessions, two independent ableton indices."""
    s1 = M.create_ableton_session(conn, song_id=song, name="draft")
    s2 = M.create_ableton_session(conn, song_id=song, name="render")
    M.link_db_to_ableton(conn, session_id=s1, db_kind="track", db_id=track, ableton_index=2)
    M.link_db_to_ableton(conn, session_id=s2, db_kind="track", db_id=track, ableton_index=9)
    assert Q.get_ableton_link(conn, session_id=s1, db_kind="track", db_id=track) == 2
    assert Q.get_ableton_link(conn, session_id=s2, db_kind="track", db_id=track) == 9


# ---------- requests + provenance ----------


def test_create_request_returns_uuid_and_emits_event(conn, song):
    rid = M.create_request(
        conn,
        actor="llm",
        intent="add a chorus",
        payload={"section": "chorus"},
        song_id=song,
    )
    assert isinstance(rid, str) and len(rid) == 32
    row = conn.execute("SELECT * FROM requests WHERE id=?", (rid,)).fetchone()
    assert row["actor"] == "llm" and row["intent"] == "add a chorus"
    ev = _events(conn)[-1]
    assert ev["kind"] == E.REQUEST_CREATED
    assert ev["actor"] == "llm"
    assert ev["request_id"] == rid


def test_create_request_rejects_invalid_actor(conn):
    with pytest.raises(ValueError, match="invalid actor"):
        M.create_request(conn, actor="alien", intent="x")


def test_mutator_kwarg_defaults_actor_system_no_request(conn, song):
    """Mutators without explicit metadata default to actor='system' / no request."""
    M.create_track(conn, song_id=song, track_index=2, name="Bass")
    last = _events(conn)[-1]
    assert last["actor"] == "system"
    assert last["request_id"] is None
    assert last["reason"] is None


def test_mutator_metadata_kwargs_propagate_to_event(conn, song):
    rid = M.create_request(conn, actor="user", intent="add bass track", song_id=song)
    M.create_track(
        conn,
        song_id=song,
        track_index=2,
        name="Bass",
        actor="user",
        request_id=rid,
        reason="user asked for a bassline",
    )
    last = _events(conn)[-1]
    assert last["kind"] == E.TRACK_CREATED
    assert last["actor"] == "user"
    assert last["request_id"] == rid
    assert last["reason"] == "user asked for a bassline"


def test_emit_rejects_invalid_actor(conn, song):
    with pytest.raises(ValueError, match="invalid actor"):
        M.create_track(conn, song_id=song, track_index=2, name="x", actor="bogus")


# ---------- events.seq ordering ----------


def test_events_seq_is_monotonic(conn, song, track):
    M.create_clip(conn, track_id=track, slot=1, length_beats=4.0)
    M.create_clip(conn, track_id=track, slot=2, length_beats=4.0)
    seqs = [r["seq"] for r in conn.execute("SELECT seq FROM events ORDER BY seq").fetchall()]
    assert seqs == sorted(seqs)
    assert seqs == list(range(1, len(seqs) + 1))


def test_event_id_is_uuid_hex(conn):
    M.create_song(conn, name="x")
    eid = conn.execute("SELECT id FROM events").fetchone()["id"]
    assert isinstance(eid, str) and len(eid) == 32
