"""Tests for the Wave-3 pull planner: plan_pull_mix + apply_pull_results."""
from __future__ import annotations

import json
import subprocess
import sys

import pytest

from hallucinote.db import init_db, mutations as M, queries as Q
from hallucinote.sync import pull


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "pull.db")
    yield c
    c.close()


@pytest.fixture
def song(conn):
    return M.create_song(conn, name="t", key="Dm")


@pytest.fixture
def session(conn, song):
    return M.create_ableton_session(conn, song_id=song, name="draft")


@pytest.fixture
def master(conn, song):
    mid = M.create_track(
        conn, song_id=song, track_index=0, name="Master", kind="master"
    )
    M.set_track_mixer(conn, track_id=mid, volume=0.85, pan=0.0)
    return mid


def _link_track(conn, *, session, db_id, ableton_index):
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=db_id,
        ableton_index=ableton_index,
    )


def _link_return(conn, *, session, db_id, ableton_index):
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="return", db_id=db_id,
        ableton_index=ableton_index,
    )


def _result(key, payload, *, ok=True, tool="probe"):
    return {"key": key, "ok": ok, "tool": tool, "result": payload}


# ---------------------------------------------------------------------------
# Reverse-link query
# ---------------------------------------------------------------------------


def test_reverse_link_lookup(conn, song, session):
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    _link_track(conn, session=session, db_id=tid, ableton_index=5)
    got = Q.get_db_id_by_ableton_index(
        conn, session_id=session, db_kind="track", ableton_index=5
    )
    assert got == tid


def test_reverse_link_missing_returns_none(conn, session):
    got = Q.get_db_id_by_ableton_index(
        conn, session_id=session, db_kind="track", ableton_index=99
    )
    assert got is None


# ---------------------------------------------------------------------------
# plan_pull_mix
# ---------------------------------------------------------------------------


def test_plan_pull_mix_emits_global_probes(conn, song, session):
    plan = pull.plan_pull_mix(conn, song_id=song, session_id=session)
    # Under Wave M-1, session-info is probed via the unified ableton_session
    # tool. list_return_tracks retargets in M-2.
    session_info_calls = [
        c for c in plan.calls
        if c.tool == "ableton_session" and c.args.get("action") == "info"
    ]
    assert len(session_info_calls) == 1
    tools = [c.tool for c in plan.calls]
    assert "list_return_tracks" in tools


def test_plan_pull_mix_emits_per_linked_track_probes(conn, song, session):
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    _link_track(conn, session=session, db_id=tid, ableton_index=5)
    plan = pull.plan_pull_mix(conn, song_id=song, session_id=session)
    keys = {c.key for c in plan.calls}
    assert f"track_info:{tid}" in keys
    assert f"track_sends:{tid}" in keys
    info_call = next(c for c in plan.calls if c.key == f"track_info:{tid}")
    assert info_call.args == {"track_index": 5}


def test_plan_pull_mix_warns_for_unlinked_tracks(conn, song, session):
    M.create_track(conn, song_id=song, track_index=1, name="Drums")
    plan = pull.plan_pull_mix(conn, song_id=song, session_id=session)
    assert any("not linked" in n for n in plan.notes)
    # No track-scoped probes emitted.
    assert not any(c.key.startswith("track_info:") for c in plan.calls)


def test_plan_pull_mix_skips_master_and_return_kinds(conn, song, session, master):
    plan = pull.plan_pull_mix(conn, song_id=song, session_id=session)
    # The master row is not probed via track_info — master comes from session_info.
    assert not any(c.key.startswith("track_info:") for c in plan.calls)


# ---------------------------------------------------------------------------
# apply_pull_results — session_info / master
# ---------------------------------------------------------------------------


def test_apply_session_info_updates_master_volume(conn, song, session, master):
    results = [_result("session_info", {"master": {"volume": 0.7, "panning": 0.0}})]
    out = pull.apply_pull_results(
        conn, results, song_id=song, session_id=session
    )
    assert out.mutations == 1
    row = Q.get_track(conn, master)
    assert row["volume"] == pytest.approx(0.7)


def test_apply_session_info_idempotent_within_tolerance(conn, song, session, master):
    # 0.85 in DB; Ableton reports 0.8504 (within _FLOAT_EPS).
    results = [_result("session_info", {"master": {"volume": 0.8504, "panning": 0.0}})]
    out = pull.apply_pull_results(
        conn, results, song_id=song, session_id=session
    )
    assert out.mutations == 0
    assert out.no_ops == 1


def test_apply_session_info_no_master_row_warns(conn, song, session):
    results = [_result("session_info", {"master": {"volume": 0.7}})]
    out = pull.apply_pull_results(
        conn, results, song_id=song, session_id=session
    )
    assert out.mutations == 0
    assert any("no master row" in w for w in out.warnings)


# ---------------------------------------------------------------------------
# apply_pull_results — returns_list
# ---------------------------------------------------------------------------


def test_apply_returns_list_updates_linked_return(conn, song, session):
    rid = M.create_return(
        conn, song_id=song, name="A-Reverb", position=1, volume=0.85, pan=0.0
    )
    _link_return(conn, session=session, db_id=rid, ableton_index=1)
    results = [_result("returns_list", [
        {"index": 1, "name": "A-Reverb", "volume": 0.6, "panning": -0.1},
    ])]
    out = pull.apply_pull_results(
        conn, results, song_id=song, session_id=session
    )
    assert out.mutations == 1
    row = Q.get_return(conn, rid)
    assert row["volume"] == pytest.approx(0.6)
    assert row["pan"] == pytest.approx(-0.1)


def test_apply_returns_list_skips_unlinked_returns(conn, song, session):
    results = [_result("returns_list", [
        {"index": 1, "name": "Unknown-Return", "volume": 0.5, "panning": 0.0},
    ])]
    out = pull.apply_pull_results(
        conn, results, song_id=song, session_id=session
    )
    assert out.mutations == 0
    assert out.skipped_unlinked == 1


# ---------------------------------------------------------------------------
# apply_pull_results — track_info
# ---------------------------------------------------------------------------


def test_apply_track_info_volume_pan(conn, song, session):
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    M.set_track_mixer(conn, track_id=tid, volume=0.5, pan=0.0)
    _link_track(conn, session=session, db_id=tid, ableton_index=5)
    results = [_result(f"track_info:{tid}",
                       {"name": "Drums", "type": "midi",
                        "volume": 0.62, "panning": -0.25})]
    out = pull.apply_pull_results(
        conn, results, song_id=song, session_id=session
    )
    assert out.mutations == 1
    row = Q.get_track(conn, tid)
    assert row["volume"] == pytest.approx(0.62)
    assert row["pan"] == pytest.approx(-0.25)


def test_apply_track_info_mute_solo_arm_color(conn, song, session):
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    M.set_track_mixer(conn, track_id=tid, mute=0, solo=0, arm=0)
    _link_track(conn, session=session, db_id=tid, ableton_index=5)
    results = [_result(f"track_info:{tid}",
                       {"mute": True, "solo": False, "arm": True, "color": 0x00FF00})]
    out = pull.apply_pull_results(
        conn, results, song_id=song, session_id=session
    )
    assert out.mutations == 1
    row = Q.get_track(conn, tid)
    assert row["mute"] == 1
    assert row["arm"] == 1
    assert row["color"] == 0x00FF00


def test_apply_track_info_no_change_is_no_op(conn, song, session):
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    M.set_track_mixer(conn, track_id=tid, volume=0.62, pan=0.0)
    _link_track(conn, session=session, db_id=tid, ableton_index=5)
    results = [_result(f"track_info:{tid}",
                       {"volume": 0.6201, "panning": 0.0})]
    out = pull.apply_pull_results(
        conn, results, song_id=song, session_id=session
    )
    assert out.mutations == 0
    assert out.no_ops == 1


def test_apply_track_info_missing_optional_fields_does_not_clobber(conn, song, session):
    """Probe doesn't include `mute` — apply must leave DB mute alone, not None it out."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    M.set_track_mixer(conn, track_id=tid, volume=0.62, pan=0.0, mute=1)
    _link_track(conn, session=session, db_id=tid, ableton_index=5)
    results = [_result(f"track_info:{tid}", {"volume": 0.62, "panning": 0.0})]
    out = pull.apply_pull_results(
        conn, results, song_id=song, session_id=session
    )
    row = Q.get_track(conn, tid)
    assert row["mute"] == 1
    assert out.mutations == 0


# ---------------------------------------------------------------------------
# apply_pull_results — track_sends
# ---------------------------------------------------------------------------


def test_apply_track_sends_level_change(conn, song, session):
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    _link_track(conn, session=session, db_id=tid, ableton_index=5)
    rid = M.create_return(
        conn, song_id=song, name="A-Reverb", position=1
    )
    _link_return(conn, session=session, db_id=rid, ableton_index=1)
    M.set_send_level(conn, from_track_id=tid, to_return_id=rid, level=0.0)
    results = [_result(f"track_sends:{tid}", {"A-Reverb": 0.4})]
    out = pull.apply_pull_results(
        conn, results, song_id=song, session_id=session
    )
    assert out.mutations == 1
    sends = Q.get_sends_for_track(conn, tid)
    assert any(s["return_name"] == "A-Reverb" and abs(s["level"] - 0.4) < 1e-6
               for s in sends)


def test_apply_track_sends_added_in_ableton(conn, song, session):
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    _link_track(conn, session=session, db_id=tid, ableton_index=5)
    rid = M.create_return(conn, song_id=song, name="A-Reverb", position=1)
    _link_return(conn, session=session, db_id=rid, ableton_index=1)
    # No existing send row in DB; Ableton has one.
    results = [_result(f"track_sends:{tid}", {"A-Reverb": 0.3})]
    out = pull.apply_pull_results(
        conn, results, song_id=song, session_id=session
    )
    assert out.mutations == 1
    sends = Q.get_sends_for_track(conn, tid)
    assert len(sends) == 1


def test_apply_track_sends_removed_in_ableton(conn, song, session):
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    _link_track(conn, session=session, db_id=tid, ableton_index=5)
    rid = M.create_return(conn, song_id=song, name="A-Reverb", position=1)
    _link_return(conn, session=session, db_id=rid, ableton_index=1)
    M.set_send_level(conn, from_track_id=tid, to_return_id=rid, level=0.4)
    # Ableton no longer reports A-Reverb on this track.
    results = [_result(f"track_sends:{tid}", {})]
    out = pull.apply_pull_results(
        conn, results, song_id=song, session_id=session
    )
    assert out.mutations == 1
    sends = Q.get_sends_for_track(conn, tid)
    assert sends == []


def test_apply_track_sends_no_op_within_tolerance(conn, song, session):
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    _link_track(conn, session=session, db_id=tid, ableton_index=5)
    rid = M.create_return(conn, song_id=song, name="A-Reverb", position=1)
    _link_return(conn, session=session, db_id=rid, ableton_index=1)
    M.set_send_level(conn, from_track_id=tid, to_return_id=rid, level=0.4)
    results = [_result(f"track_sends:{tid}", {"A-Reverb": 0.4001})]
    out = pull.apply_pull_results(
        conn, results, song_id=song, session_id=session
    )
    assert out.mutations == 0
    assert out.no_ops == 1


def test_apply_track_sends_unknown_return_warns(conn, song, session):
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    _link_track(conn, session=session, db_id=tid, ableton_index=5)
    results = [_result(f"track_sends:{tid}", {"Ghost-Return": 0.5})]
    out = pull.apply_pull_results(
        conn, results, song_id=song, session_id=session
    )
    assert out.mutations == 0
    assert any("no matching return" in w for w in out.warnings)


# ---------------------------------------------------------------------------
# apply_pull_results — events emitted
# ---------------------------------------------------------------------------


def test_apply_emits_events_via_mutators(conn, song, session, master):
    pre = len(Q.get_events_for_song(conn, song))
    results = [_result("session_info", {"master": {"volume": 0.7, "panning": 0.0}})]
    pull.apply_pull_results(conn, results, song_id=song, session_id=session)
    post = len(Q.get_events_for_song(conn, song))
    assert post == pre + 1


def test_apply_actor_sync_with_reason_in_events(conn, song, session, master):
    """Pull mutations use actor='sync' (matching push); pull-vs-push
    provenance lives in `reason`. Keeps the actors enum stable."""
    results = [_result("session_info", {"master": {"volume": 0.7, "panning": 0.0}})]
    pull.apply_pull_results(
        conn, results, song_id=song, session_id=session, reason="pull-test"
    )
    # get_events_for_song orders seq DESC, so the newest event is events[0].
    events = Q.get_events_for_song(conn, song)
    latest = events[0]
    assert latest["actor"] == "sync"
    assert latest["reason"] == "pull-test"


# ---------------------------------------------------------------------------
# apply_pull_results — dispatch hardness
# ---------------------------------------------------------------------------


def test_apply_unknown_kind_raises(conn, song, session):
    results = [_result("nope:abc", {})]
    with pytest.raises(ValueError, match="unknown pull result key kind"):
        pull.apply_pull_results(conn, results, song_id=song, session_id=session)


def test_apply_failed_result_is_warning_not_error(conn, song, session):
    results = [
        {"key": "session_info", "ok": False, "tool": "ableton_session",
         "error": "MCP timeout"},
    ]
    out = pull.apply_pull_results(conn, results, song_id=song, session_id=session)
    assert out.mutations == 0
    assert any("MCP timeout" in w for w in out.warnings)


def test_apply_track_info_missing_db_id_raises(conn, song, session):
    results = [_result("track_info:", {"volume": 0.5})]
    with pytest.raises(ValueError, match="missing db_id"):
        pull.apply_pull_results(conn, results, song_id=song, session_id=session)


def test_apply_track_info_unlinked_track_skips_with_warning(conn, song, session):
    """Defense in depth: even if a hand-rolled results.json carries a
    track_info for an unlinked track, apply must refuse to mutate it."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    M.set_track_mixer(conn, track_id=tid, volume=0.5, pan=0.0)
    # Note: NO link created for this track in this session.
    results = [_result(f"track_info:{tid}", {"volume": 0.9, "panning": 0.0})]
    out = pull.apply_pull_results(
        conn, results, song_id=song, session_id=session
    )
    assert out.mutations == 0
    assert out.skipped_unlinked == 1
    assert any("not linked" in w for w in out.warnings)
    # DB untouched.
    assert Q.get_track(conn, tid)["volume"] == pytest.approx(0.5)


def test_apply_track_sends_unlinked_track_skips_with_warning(conn, song, session):
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    rid = M.create_return(conn, song_id=song, name="A-Reverb", position=1)
    _link_return(conn, session=session, db_id=rid, ableton_index=1)
    # track NOT linked
    results = [_result(f"track_sends:{tid}", {"A-Reverb": 0.4})]
    out = pull.apply_pull_results(
        conn, results, song_id=song, session_id=session
    )
    assert out.mutations == 0
    assert out.skipped_unlinked == 1


def test_apply_track_sends_out_of_range_warns_continues_batch(conn, song, session):
    """One bad send level must not abort the whole batch. The mutator's
    ValueError is caught per-send and reported as a warning."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    _link_track(conn, session=session, db_id=tid, ableton_index=5)
    r1 = M.create_return(conn, song_id=song, name="A-Reverb", position=1)
    _link_return(conn, session=session, db_id=r1, ableton_index=1)
    r2 = M.create_return(conn, song_id=song, name="B-Delay", position=2)
    _link_return(conn, session=session, db_id=r2, ableton_index=2)
    # 1.5 is out of range (set_send_level rejects > 1.0); 0.3 is valid.
    results = [_result(f"track_sends:{tid}",
                       {"A-Reverb": 1.5, "B-Delay": 0.3})]
    out = pull.apply_pull_results(
        conn, results, song_id=song, session_id=session
    )
    # The valid send went through; the out-of-range one is a warning.
    assert out.mutations == 1
    assert any("rejected" in w and "A-Reverb" in w for w in out.warnings)
    sends = Q.get_sends_for_track(conn, tid)
    # Only B-Delay should be present.
    assert len(sends) == 1
    assert sends[0]["return_name"] == "B-Delay"


# ---------------------------------------------------------------------------
# apply_pull_results — session_info / tempo (W3-2)
# ---------------------------------------------------------------------------


def test_apply_session_tempo_adds_bar1_row_when_missing(conn, song, session):
    results = [_result("session_info", {"tempo": 132.0})]
    out = pull.apply_pull_results(
        conn, results, song_id=song, session_id=session
    )
    assert out.mutations == 1
    rows = Q.get_tempo_map(conn, song)
    assert len(rows) == 1
    assert rows[0]["start_bar"] == 1.0
    assert rows[0]["tempo_bpm"] == pytest.approx(132.0)


def test_apply_session_tempo_updates_existing_bar1_row(conn, song, session):
    M.add_tempo_point(conn, song_id=song, start_bar=1.0, tempo_bpm=132.0)
    results = [_result("session_info", {"tempo": 130.0})]
    out = pull.apply_pull_results(
        conn, results, song_id=song, session_id=session
    )
    assert out.mutations == 1
    rows = Q.get_tempo_map(conn, song)
    assert len(rows) == 1  # still one row — updated in place, not add+remove
    assert rows[0]["tempo_bpm"] == pytest.approx(130.0)


def test_apply_session_tempo_idempotent_within_tolerance(conn, song, session):
    M.add_tempo_point(conn, song_id=song, start_bar=1.0, tempo_bpm=132.0)
    results = [_result("session_info", {"tempo": 132.0005})]
    out = pull.apply_pull_results(
        conn, results, song_id=song, session_id=session
    )
    assert out.mutations == 0
    assert out.no_ops == 1


def test_apply_session_tempo_leaves_other_points_untouched(conn, song, session):
    """Multi-point tempo maps are MCP-gapped; pull must touch only bar-1."""
    M.add_tempo_point(conn, song_id=song, start_bar=1.0, tempo_bpm=132.0)
    other_id = M.add_tempo_point(conn, song_id=song, start_bar=32.0,
                                  tempo_bpm=140.0)
    results = [_result("session_info", {"tempo": 130.0})]
    pull.apply_pull_results(conn, results, song_id=song, session_id=session)
    rows = Q.get_tempo_map(conn, song)
    assert len(rows) == 2
    other = next(r for r in rows if r["id"] == other_id)
    assert other["tempo_bpm"] == pytest.approx(140.0)


def test_apply_session_tempo_rejects_non_positive(conn, song, session):
    results = [_result("session_info", {"tempo": -1})]
    out = pull.apply_pull_results(
        conn, results, song_id=song, session_id=session
    )
    assert out.mutations == 0
    assert any("non-positive" in w for w in out.warnings)


# ---------------------------------------------------------------------------
# apply_pull_results — session_info / signature (W3-2)
# ---------------------------------------------------------------------------


def test_apply_session_signature_adds_bar1_row_when_missing(conn, song, session):
    results = [_result("session_info", {"signature": "4/4"})]
    out = pull.apply_pull_results(
        conn, results, song_id=song, session_id=session
    )
    assert out.mutations == 1
    rows = Q.get_time_signature_map(conn, song)
    assert len(rows) == 1
    assert rows[0]["numerator"] == 4
    assert rows[0]["denominator"] == 4


def test_apply_session_signature_updates_existing(conn, song, session):
    M.add_time_signature_point(conn, song_id=song, start_bar=1.0,
                               numerator=4, denominator=4)
    results = [_result("session_info", {"signature": "6/8"})]
    out = pull.apply_pull_results(
        conn, results, song_id=song, session_id=session
    )
    assert out.mutations == 1
    rows = Q.get_time_signature_map(conn, song)
    assert len(rows) == 1
    assert rows[0]["numerator"] == 6
    assert rows[0]["denominator"] == 8


def test_apply_session_signature_idempotent(conn, song, session):
    M.add_time_signature_point(conn, song_id=song, start_bar=1.0,
                               numerator=4, denominator=4)
    results = [_result("session_info", {"signature": "4/4"})]
    out = pull.apply_pull_results(
        conn, results, song_id=song, session_id=session
    )
    assert out.mutations == 0
    assert out.no_ops == 1


def test_apply_session_signature_parse_error_warns(conn, song, session):
    results = [_result("session_info", {"signature": "garbage"})]
    out = pull.apply_pull_results(
        conn, results, song_id=song, session_id=session
    )
    assert out.mutations == 0
    assert any("parse error" in w for w in out.warnings)


# ---------------------------------------------------------------------------
# apply_pull_results — cue_points_list (W3-2)
# ---------------------------------------------------------------------------


def test_plan_pull_cue_points_emits_single_probe(conn, song, session):
    plan = pull.plan_pull_cue_points(conn, song_id=song, session_id=session)
    assert [c.tool for c in plan.calls] == ["get_cue_points"]
    assert plan.calls[0].key == "cue_points_list"


def test_plan_pull_score_globals_emits_single_session_info_probe(conn, song, session):
    """score-globals is the cheap subset of mix-state — one ableton_session probe."""
    plan = pull.plan_pull_score_globals(conn, song_id=song, session_id=session)
    assert len(plan.calls) == 1
    call = plan.calls[0]
    assert call.tool == "ableton_session"
    assert call.args == {"action": "info"}
    assert call.key == "session_info"


def test_apply_cue_points_adds_new(conn, song, session):
    results = [_result("cue_points_list", [
        {"position_bar": 5.0, "name": "Verse"},
        {"position_bar": 13.0, "name": "Chorus"},
    ])]
    out = pull.apply_pull_results(
        conn, results, song_id=song, session_id=session
    )
    assert out.mutations == 2
    cues = Q.get_cue_points(conn, song)
    assert len(cues) == 2
    positions = sorted(c["position_bar"] for c in cues)
    assert positions == [5.0, 13.0]


def test_apply_cue_points_accepts_bar_beat_form(conn, song, session):
    """Skill may pass either {position_bar} or {bar, beat}; apply joins (bar,
    beat) -> position_bar via the song's time signature."""
    M.add_time_signature_point(conn, song_id=song, start_bar=1.0,
                               numerator=4, denominator=4)
    results = [_result("cue_points_list", [
        {"bar": 5, "beat": 2.0, "name": "Pickup"},
    ])]
    pull.apply_pull_results(conn, results, song_id=song, session_id=session)
    cues = Q.get_cue_points(conn, song)
    assert len(cues) == 1
    # 4/4 -> beats_per_bar=4 -> position = 5 + 2/4 = 5.5
    assert cues[0]["position_bar"] == pytest.approx(5.5)


def test_apply_cue_points_drops_numeric_id_names(conn, song, session):
    """MCP gap #13: names come back as numeric strings. Apply must NOT store
    these — they'd clobber real names on later round-trips."""
    results = [_result("cue_points_list", [
        {"position_bar": 5.0, "name": "1"},
        {"position_bar": 13.0, "name": "2"},
    ])]
    pull.apply_pull_results(conn, results, song_id=song, session_id=session)
    cues = Q.get_cue_points(conn, song)
    assert all(c["name"] is None for c in cues)


def test_apply_cue_points_removes_db_cues_absent_from_ableton(conn, song, session):
    M.add_cue_point(conn, song_id=song, position_bar=5.0, name="Verse")
    M.add_cue_point(conn, song_id=song, position_bar=13.0, name="Chorus")
    # Ableton reports only one cue.
    results = [_result("cue_points_list", [{"position_bar": 5.0}])]
    out = pull.apply_pull_results(
        conn, results, song_id=song, session_id=session
    )
    # 1 mutation: removed Chorus.
    assert out.mutations == 1
    cues = Q.get_cue_points(conn, song)
    assert len(cues) == 1
    assert cues[0]["position_bar"] == 5.0


def test_apply_cue_points_position_match_is_no_op(conn, song, session):
    M.add_cue_point(conn, song_id=song, position_bar=5.0, name="Verse")
    results = [_result("cue_points_list", [{"position_bar": 5.0, "name": "1"}])]
    out = pull.apply_pull_results(
        conn, results, song_id=song, session_id=session
    )
    assert out.mutations == 0
    assert out.no_ops == 1
    # Name preserved.
    assert Q.get_cue_points(conn, song)[0]["name"] == "Verse"


def test_apply_cue_points_name_diff_warns_no_mutate(conn, song, session):
    """If MCP gap #13 ever lifts and returns real names, a mismatch should be
    surfaced as a warning — but apply still does NOT mutate the DB name from
    pull data (writes go through the DB-authoritative path)."""
    M.add_cue_point(conn, song_id=song, position_bar=5.0, name="Verse")
    results = [_result("cue_points_list",
                       [{"position_bar": 5.0, "name": "VerseTakeTwo"}])]
    out = pull.apply_pull_results(
        conn, results, song_id=song, session_id=session
    )
    assert out.mutations == 0
    assert any("name mismatch" in w for w in out.warnings)
    assert Q.get_cue_points(conn, song)[0]["name"] == "Verse"


# ---------------------------------------------------------------------------
# Round-trip: push -> mutate Ableton-side dict -> pull -> DB matches
# ---------------------------------------------------------------------------


def test_round_trip_push_then_pull(conn, song, session, master):
    """Set DB state, simulate Ableton drift, pull, confirm DB caught up."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    M.set_track_mixer(conn, track_id=tid, volume=0.6, pan=0.0)
    _link_track(conn, session=session, db_id=tid, ableton_index=5)
    rid = M.create_return(conn, song_id=song, name="A-Reverb",
                          position=1, volume=0.85, pan=0.0)
    _link_return(conn, session=session, db_id=rid, ableton_index=1)
    M.set_send_level(conn, from_track_id=tid, to_return_id=rid, level=0.0)

    # User drags faders in Ableton: master 0.85 -> 0.7; track vol 0.6 -> 0.75;
    # send 0.0 -> 0.35.
    ableton_state = [
        _result("session_info", {"master": {"volume": 0.7, "panning": 0.0}}),
        _result("returns_list", [
            {"index": 1, "name": "A-Reverb", "volume": 0.85, "panning": 0.0},
        ]),
        _result(f"track_info:{tid}",
                {"name": "Drums", "volume": 0.75, "panning": 0.0}),
        _result(f"track_sends:{tid}", {"A-Reverb": 0.35}),
    ]
    out = pull.apply_pull_results(
        conn, ableton_state, song_id=song, session_id=session
    )
    assert out.mutations == 3  # master vol, track vol, send level
    assert Q.get_track(conn, master)["volume"] == pytest.approx(0.7)
    assert Q.get_track(conn, tid)["volume"] == pytest.approx(0.75)
    sends = Q.get_sends_for_track(conn, tid)
    assert sends[0]["level"] == pytest.approx(0.35)

    # Idempotency: re-applying the same probe is a no-op.
    out2 = pull.apply_pull_results(
        conn, ableton_state, song_id=song, session_id=session
    )
    assert out2.mutations == 0


# ---------------------------------------------------------------------------
# CLI smoke
# ---------------------------------------------------------------------------


def test_pull_cli_plan_and_apply_roundtrip(tmp_path):
    db_path = tmp_path / "cli.db"
    conn = init_db(db_path)
    song_id = M.create_song(conn, name="cli", key="Dm")
    mid = M.create_track(conn, song_id=song_id, track_index=0, name="Master",
                         kind="master")
    M.set_track_mixer(conn, track_id=mid, volume=0.85, pan=0.0)
    session_id = M.create_ableton_session(conn, song_id=song_id, name="draft")
    conn.close()

    plan_path = tmp_path / "plan.json"
    results_path = tmp_path / "results.json"

    # Run `plan` with the --db escape hatch (test layout isn't songs/<slug>/...).
    p = subprocess.run(
        [sys.executable, "-m", "hallucinote.sync.pull_cli",
         "plan", "mix-state", session_id, "--db", str(db_path)],
        capture_output=True, text=True, check=True,
    )
    plan_dict = json.loads(p.stdout)
    plan_path.write_text(p.stdout)
    assert plan_dict["song_id"] == song_id
    assert plan_dict["session_id"] == session_id
    assert plan_dict["domain"] == "mix-state"
    assert any(
        c["tool"] == "ableton_session" and c["args"].get("action") == "info"
        for c in plan_dict["calls"]
    )

    # Hand-roll a results file with a master volume change.
    results_path.write_text(json.dumps([
        {"key": "session_info", "ok": True, "tool": "ableton_session",
         "result": {"master": {"volume": 0.7, "panning": 0.0}}},
        {"key": "returns_list", "ok": True, "tool": "list_return_tracks",
         "result": []},
    ]))

    p2 = subprocess.run(
        [sys.executable, "-m", "hallucinote.sync.pull_cli",
         "apply", session_id, "--db", str(db_path),
         "--plan", str(plan_path), "--results", str(results_path)],
        capture_output=True, text=True, check=True,
    )
    summary = json.loads(p2.stdout)
    assert summary["mutations"] == 1


def test_pull_cli_song_flag_resolves_canonical_path(tmp_path, monkeypatch):
    """`--song <slug>` resolves to `songs/<slug>/<slug>.db` from CWD."""
    slug = "myslug"
    song_dir = tmp_path / "songs" / slug
    song_dir.mkdir(parents=True)
    db_path = song_dir / f"{slug}.db"
    conn = init_db(db_path)
    M.create_song(conn, name=slug, title="My Slug Song", key="Dm")
    sid = M.create_ableton_session(conn, song_id=Q.get_song_by_name(
        conn, slug)["id"], name="draft")
    conn.close()

    monkeypatch.chdir(tmp_path)
    p = subprocess.run(
        [sys.executable, "-m", "hallucinote.sync.pull_cli",
         "plan", "mix-state", sid, "--song", slug],
        capture_output=True, text=True, check=True,
    )
    plan_dict = json.loads(p.stdout)
    assert plan_dict["domain"] == "mix-state"


def test_pull_cli_song_flag_missing_db_errors_clearly(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    p = subprocess.run(
        [sys.executable, "-m", "hallucinote.sync.pull_cli",
         "plan", "mix-state", "fake-session", "--song", "nope"],
        capture_output=True, text=True,
    )
    assert p.returncode != 0
    assert "DB not found" in p.stderr or "DB not found" in p.stdout


def test_pull_cli_requires_song_or_db(tmp_path):
    p = subprocess.run(
        [sys.executable, "-m", "hallucinote.sync.pull_cli",
         "plan", "mix-state", "fake-session"],
        capture_output=True, text=True,
    )
    assert p.returncode != 0
    # argparse mutually-exclusive-required failure goes to stderr.
    assert "--song" in p.stderr or "--db" in p.stderr
