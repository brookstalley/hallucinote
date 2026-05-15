"""Tests for the DB->Ableton planner and result application."""
from __future__ import annotations

import pytest

from songwright.db import init_db, mutations as M, queries as Q
from songwright.sync import push


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "p.db")
    yield c
    c.close()


@pytest.fixture
def song(conn):
    return M.create_song(conn, name="t", key="Dm")


@pytest.fixture
def session(conn, song):
    return M.create_ableton_session(conn, song_id=song, name="draft")


@pytest.fixture
def track(conn, song):
    return M.create_track(
        conn, song_id=song, track_index=1, name="Drums", instrument_uri="query:Drums#Kit_X"
    )


@pytest.fixture
def clip(conn, track):
    cid = M.create_clip(
        conn, track_id=track, slot=1, length_beats=16.0, name="verse_drums",
        section_role="verse",
    )
    M.insert_notes(
        conn,
        clip_id=cid,
        notes=[
            {"pitch": 36, "start_beats": 0.0, "duration_beats": 0.25, "velocity": 110,
             "tags": ["kick", "downbeat"]},
            {"pitch": 38, "start_beats": 1.04, "duration_beats": 0.25, "velocity": 100,
             "tags": ["snare", "backbeat"]},
        ],
    )
    return cid


# --- planning ---


def test_plan_push_clip_creates_track_when_unlinked(conn, session, track, clip):
    plan = push.plan_push_clip(conn, clip_id=clip, session_id=session)
    assert len(plan.calls) == 1
    call = plan.calls[0]
    assert call.tool == "create_midi_track_with"
    assert call.args["name"] == "Drums"
    assert call.args["instrument_uri"] == "query:Drums#Kit_X"
    assert call.key == f"track:{track}"
    # Should warn that we need to re-plan after track is linked
    assert any("track" in n for n in plan.notes)


def test_plan_push_clip_uses_replace_when_track_linked_clip_unlinked(
    conn, session, track, clip
):
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=track, ableton_index=2
    )
    plan = push.plan_push_clip(conn, clip_id=clip, session_id=session)
    assert len(plan.calls) == 1
    call = plan.calls[0]
    assert call.tool == "replace_session_clip"
    assert call.args["track_index"] == 2
    assert call.args["clip_index"] == 1
    assert call.args["length"] == 16.0
    assert len(call.args["notes"]) == 2
    # Notes are converted to MCP shape (start_time / duration, no tags)
    n0 = call.args["notes"][0]
    assert "start_time" in n0 and "duration" in n0
    assert "tags" not in n0


def test_plan_push_clip_uses_set_clip_notes_when_already_linked(
    conn, session, track, clip
):
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=track, ableton_index=2
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="clip", db_id=clip, ableton_index=1
    )
    plan = push.plan_push_clip(conn, clip_id=clip, session_id=session)
    assert plan.calls[0].tool == "set_clip_notes"
    assert "length" not in plan.calls[0].args


def test_plan_push_clip_isolates_by_session(conn, song, track, clip):
    """Linking in session A doesn't affect planning under session B."""
    a = M.create_ableton_session(conn, song_id=song, name="a")
    b = M.create_ableton_session(conn, song_id=song, name="b")
    M.link_db_to_ableton(
        conn, session_id=a, db_kind="track", db_id=track, ableton_index=4
    )
    plan_b = push.plan_push_clip(conn, clip_id=clip, session_id=b)
    # Under session b, the track is still unlinked -> create call
    assert plan_b.calls[0].tool == "create_midi_track_with"


# --- arrangement ---


def test_plan_push_arrangement_skips_unlinked_and_warns(
    conn, song, session, track, clip
):
    M.add_arrangement(
        conn, song_id=song, track_id=track, clip_id=clip, start_bar=1, end_bar=16
    )
    plan = push.plan_push_arrangement(conn, song_id=song, session_id=session)
    # Track unlinked -> no batch op emitted, only warnings
    assert plan.calls == []
    assert any("track" in n.lower() for n in plan.notes)


def test_plan_push_arrangement_emits_batch_when_linked(
    conn, song, session, track, clip
):
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=track, ableton_index=2
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="clip", db_id=clip, ableton_index=1
    )
    aid = M.add_arrangement(
        conn, song_id=song, track_id=track, clip_id=clip, start_bar=1.0, end_bar=16.0
    )
    plan = push.plan_push_arrangement(conn, song_id=song, session_id=session)
    assert len(plan.calls) == 1
    call = plan.calls[0]
    assert call.tool == "batch_arrangement_layout"
    ops = call.args["operations"]
    assert len(ops) == 1
    assert ops[0]["op"] == "duplicate"
    assert ops[0]["track_index"] == 2
    assert ops[0]["clip_index"] == 1
    assert ops[0]["destination_bar"] == 1.0
    assert ops[0]["key"] == f"arrangement:{aid}"


# --- apply_push_results ---


def test_apply_results_links_track_and_clip(conn, session, track, clip):
    push.apply_push_results(
        conn,
        [
            {"key": f"track:{track}", "ok": True, "tool": "create_midi_track_with",
             "result": {"track_index": 5}},
            {"key": f"clip:{clip}", "ok": True, "tool": "replace_session_clip",
             "result": {"clip_index": 3}},
        ],
        session_id=session,
    )
    assert Q.get_ableton_link(conn, session_id=session, db_kind="track", db_id=track) == 5
    assert Q.get_ableton_link(conn, session_id=session, db_kind="clip", db_id=clip) == 3


def test_apply_results_skips_failed_calls(conn, session, track):
    push.apply_push_results(
        conn,
        [
            {"key": f"track:{track}", "ok": False, "tool": "create_midi_track_with",
             "error": "boom"},
        ],
        session_id=session,
    )
    assert Q.get_ableton_link(conn, session_id=session, db_kind="track", db_id=track) is None


def test_apply_results_links_arrangement(conn, song, session, track, clip):
    aid = M.add_arrangement(conn, song_id=song, track_id=track, clip_id=clip,
                            start_bar=1.0, end_bar=16.0)
    push.apply_push_results(
        conn,
        [
            {"key": f"arrangement:{aid}", "ok": True, "tool": "batch_arrangement_layout",
             "result": {"arrangement_clip_index": 0}},
        ],
        session_id=session,
    )
    assert (
        Q.get_ableton_link(conn, session_id=session, db_kind="arrangement", db_id=aid)
        == 0
    )


def test_apply_results_records_actor_sync_by_default(conn, session, track):
    push.apply_push_results(
        conn,
        [
            {"key": f"track:{track}", "ok": True, "tool": "create_midi_track_with",
             "result": {"track_index": 5}},
        ],
        session_id=session,
    )
    rows = conn.execute(
        "SELECT actor FROM events WHERE kind='ableton_link_set' ORDER BY seq"
    ).fetchall()
    assert [r["actor"] for r in rows] == ["sync"]
