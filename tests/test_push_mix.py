"""Tests for the chunk-3 push planner: plan_push_mix and return-link apply."""
from __future__ import annotations

import pytest

from songwright.db import init_db, mutations as M
from songwright.sync import push


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "pmix.db")
    yield c
    c.close()


@pytest.fixture
def song(conn):
    return M.create_song(conn, name="t", key="Dm")


@pytest.fixture
def session(conn, song):
    return M.create_ableton_session(conn, song_id=song, name="draft")


def _calls_by_tool(plan) -> dict[str, list]:
    out: dict[str, list] = {}
    for c in plan.calls:
        out.setdefault(c.tool, []).append(c)
    return out


def test_plan_push_mix_skips_unlinked_tracks(conn, song, session):
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    M.set_track_mixer(conn, track_id=tid, volume=0.6, pan=-0.25)
    plan = push.plan_push_mix(conn, song_id=song, session_id=session)
    assert _calls_by_tool(plan) == {}
    assert any("not linked" in n for n in plan.notes)


def test_plan_push_mix_emits_volume_and_pan_for_linked_tracks(conn, song, session):
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    M.set_track_mixer(conn, track_id=tid, volume=0.6, pan=-0.25)
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=tid, ableton_index=5
    )
    plan = push.plan_push_mix(conn, song_id=song, session_id=session)
    by_tool = _calls_by_tool(plan)
    assert "set_track_volume" in by_tool
    assert "set_track_panning" in by_tool
    vol_call = by_tool["set_track_volume"][0]
    assert vol_call.args == {"track_index": 5, "volume": 0.6}
    pan_call = by_tool["set_track_panning"][0]
    assert pan_call.args == {"track_index": 5, "panning": -0.25}


def test_plan_push_mix_skips_volume_when_none(conn, song, session):
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    M.set_track_mixer(conn, track_id=tid, pan=0.0)  # volume left null
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=tid, ableton_index=5
    )
    plan = push.plan_push_mix(conn, song_id=song, session_id=session)
    by_tool = _calls_by_tool(plan)
    assert "set_track_volume" not in by_tool
    assert "set_track_panning" in by_tool


def test_plan_push_mix_emits_gap_flagged_mute_solo_arm_color(conn, song, session):
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    M.set_track_mixer(conn, track_id=tid, mute=1, solo=0, arm=1, color=0xFF00FF)
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=tid, ableton_index=5
    )
    plan = push.plan_push_mix(conn, song_id=song, session_id=session)
    by_tool = _calls_by_tool(plan)
    assert "set_track_mute" in by_tool
    assert "set_track_solo" in by_tool
    assert "set_track_arm" in by_tool
    assert "set_track_color" in by_tool


def test_plan_push_mix_master_uses_master_strip_tools(conn, song, session):
    mid = M.create_track(
        conn, song_id=song, track_index=0, name="Master", kind="master"
    )
    M.set_track_mixer(conn, track_id=mid, volume=0.85, pan=0.0)
    plan = push.plan_push_mix(conn, song_id=song, session_id=session)
    by_tool = _calls_by_tool(plan)
    # Master is reached via the master strip — no track_index.
    assert "set_master_volume" in by_tool
    assert "set_master_panning" in by_tool
    master_vol = by_tool["set_master_volume"][0]
    assert master_vol.args == {"value": 0.85}
    assert "track_index" not in master_vol.args


def test_plan_push_mix_emits_create_return_track_when_unlinked(conn, song, session):
    M.create_return(conn, song_id=song, name="A-Reverb", position=1)
    plan = push.plan_push_mix(conn, song_id=song, session_id=session)
    by_tool = _calls_by_tool(plan)
    assert "create_return_track" in by_tool
    assert by_tool["create_return_track"][0].args == {"name": "A-Reverb"}


def test_plan_push_mix_sends_require_both_links(conn, song, session):
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    rid = M.create_return(conn, song_id=song, name="A-Reverb", position=1)
    M.set_send_level(conn, from_track_id=tid, to_return_id=rid, level=0.4)

    # Neither linked — skipped with warning.
    plan = push.plan_push_mix(conn, song_id=song, session_id=session)
    assert "set_track_send" not in _calls_by_tool(plan)
    assert any("missing link" in n for n in plan.notes)

    # Link both — call emitted.
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=tid, ableton_index=5
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="return", db_id=rid, ableton_index=1
    )
    plan = push.plan_push_mix(conn, song_id=song, session_id=session)
    by_tool = _calls_by_tool(plan)
    assert "set_track_send" in by_tool
    send_call = by_tool["set_track_send"][0]
    assert send_call.args == {"track_index": 5, "return_index": 1, "value": 0.4}


def test_apply_push_results_links_returns(conn, song, session):
    rid = M.create_return(conn, song_id=song, name="A-Reverb", position=1)
    push.apply_push_results(
        conn,
        [
            {"key": f"return:{rid}", "ok": True, "tool": "create_return_track",
             "result": {"return_index": 1}},
        ],
        session_id=session,
    )
    from songwright.db import queries as Q
    linked = Q.get_ableton_link(
        conn, session_id=session, db_kind="return", db_id=rid
    )
    assert linked == 1


def test_apply_push_results_silently_drops_unknown_chunk3_keys(conn, song, session):
    """Documents the current silent-no-op behavior for chunk-3 result keys.

    `plan_push_mix` emits keys like `track_volume:`, `track_pan:`, `send:`,
    `master_volume:` — none of which have an apply_push_results branch yet.
    Today they're silent no-ops; backlog item: switch to a raise-on-unknown
    dispatch table so silent drops can't mask real failures.
    """
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    M.set_track_mixer(conn, track_id=tid, volume=0.5)
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=tid, ableton_index=5
    )
    # Feed a result for a key kind that apply_push_results doesn't recognize.
    # Should not raise; should not link anything new beyond what we just set.
    push.apply_push_results(
        conn,
        [
            {"key": f"track_volume:{tid}", "ok": True, "tool": "set_track_volume",
             "result": {}},
            {"key": f"send:{tid}:fake_return_uuid_for_test", "ok": True,
             "tool": "set_track_send", "result": {}},
            {"key": f"master_volume:{tid}", "ok": True, "tool": "set_master_volume",
             "result": {}},
        ],
        session_id=session,
    )
    # No new links materialized.
    from songwright.db import queries as Q
    links = Q.get_ableton_links_for_session(conn, session)
    # Only the original track link should exist.
    assert len(links) == 1
    assert links[0]["db_kind"] == "track"


def test_plan_push_mix_empty_song_warns(conn, song, session):
    plan = push.plan_push_mix(conn, song_id=song, session_id=session)
    assert plan.calls == []
    assert any("no mix state" in n for n in plan.notes)


def test_plan_push_mix_handles_falling_walking_snapshot(conn, session, tmp_path):
    """End-to-end: replay falling-walking snapshot, link everything, plan push.

    Verifies the planner shape doesn't blow up on the real song. With 12 tracks
    (some empty) + 2 returns + 16 sends + 1 master, the linked plan should emit
    plausible numbers of set_track_volume / set_track_send calls.
    """
    import json
    from pathlib import Path

    from songwright.capture import replay_capture

    repo_root = Path(__file__).resolve().parents[1]
    snap = json.loads(
        (repo_root / "songs" / "falling-walking" / "captured_session.json").read_text()
    )
    # New song in this conn — use the existing session fixture's song.
    new_sid = replay_capture(conn, snap, song_name="fw", song_key="Dm")
    new_session = M.create_ableton_session(conn, song_id=new_sid, name="draft")

    # Link all tracks (by track_index) and returns (by position) so the planner
    # has full coverage.
    from songwright.db import queries as Q
    for t in Q.get_tracks_for_song(conn, new_sid):
        if t["kind"] != "master":
            M.link_db_to_ableton(
                conn, session_id=new_session, db_kind="track",
                db_id=t["id"], ableton_index=t["track_index"],
            )
    for r in Q.get_returns_for_song(conn, new_sid):
        M.link_db_to_ableton(
            conn, session_id=new_session, db_kind="return",
            db_id=r["id"], ableton_index=r["position"],
        )

    plan = push.plan_push_mix(conn, song_id=new_sid, session_id=new_session)
    by_tool = _calls_by_tool(plan)
    # 8 audible + 4 empty tracks all have volume set -> 12 set_track_volume calls
    assert len(by_tool.get("set_track_volume", [])) >= 8
    # 16 sends from 8 audible tracks × 2 returns
    assert len(by_tool.get("set_track_send", [])) == 16
    # Master uses master-strip tool
    assert "set_master_volume" in by_tool
