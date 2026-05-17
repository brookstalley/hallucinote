"""Falling-walking-specific push planner shape test.

End-to-end: replay the captured snapshot, link all tracks + returns into a
fresh Ableton session, then plan a push and assert the call counts match
the song's mix shape (12 tracks → ≥8 volume calls, 8 audible × 2 returns
→ 16 send calls, master fader via the unified session tool).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from hallucinote.capture import replay_capture
from hallucinote.db import init_db, mutations as M, queries as Q
from hallucinote.sync import push

SONG_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = SONG_ROOT / "captured_session.json"


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "pmix.db")
    yield c
    c.close()


def test_plan_push_mix_handles_falling_walking_snapshot(conn):
    snap = json.loads(SNAPSHOT.read_text())
    sid = replay_capture(conn, snap, song_name="fw", song_key="Dm")
    session_id = M.create_ableton_session(conn, song_id=sid, name="draft")

    # Link all tracks (by track_index) and returns (by position) so the planner
    # has full coverage.
    for t in Q.get_tracks_for_song(conn, sid):
        if t["kind"] != "master":
            M.link_db_to_ableton(
                conn, session_id=session_id, db_kind="track",
                db_id=t["id"], ableton_index=t["track_index"],
            )
    for r in Q.get_returns_for_song(conn, sid):
        M.link_db_to_ableton(
            conn, session_id=session_id, db_kind="return",
            db_id=r["id"], ableton_index=r["position"],
        )

    plan = push.plan_push_mix(conn, song_id=sid, session_id=session_id)
    track_calls = [c for c in plan.calls if c.tool == "ableton_track"]
    vol_calls = [
        c for c in track_calls
        if c.args.get("action") == "set_property"
        and c.args.get("property") == "volume"
    ]
    send_calls = [c for c in track_calls if c.args.get("action") == "set_send"]
    # 8 audible + 4 empty tracks all have volume set -> ≥8 set_property volume calls.
    assert len(vol_calls) >= 8
    # 16 sends from 8 audible tracks × 2 returns
    assert len(send_calls) == 16
    # Master uses the unified ableton_session tool (M-1 retarget).
    session_calls = [c for c in plan.calls if c.tool == "ableton_session"]
    master_props = [
        c for c in session_calls
        if c.args.get("action") == "set_master_property"
    ]
    assert any(c.args.get("property") == "volume" for c in master_props)
