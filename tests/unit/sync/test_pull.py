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
    """Wave M-2: every domain probe routes through the unified surface."""
    plan = pull.plan_pull_mix(conn, song_id=song, session_id=session)
    session_info_calls = [
        c for c in plan.calls
        if c.tool == "ableton_session" and c.args.get("action") == "info"
    ]
    assert len(session_info_calls) == 1
    return_list_calls = [
        c for c in plan.calls
        if c.tool == "ableton_return" and c.args.get("action") == "list"
    ]
    assert len(return_list_calls) == 1


def test_plan_pull_mix_emits_per_linked_track_probes(conn, song, session):
    """Per-track probes route through ableton_track(action='info'/'get_sends')."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    _link_track(conn, session=session, db_id=tid, ableton_index=5)
    plan = pull.plan_pull_mix(conn, song_id=song, session_id=session)
    keys = {c.key for c in plan.calls}
    assert f"track_info:{tid}" in keys
    assert f"track_sends:{tid}" in keys
    info_call = next(c for c in plan.calls if c.key == f"track_info:{tid}")
    assert info_call.tool == "ableton_track"
    assert info_call.args == {"action": "info", "track_index": 5}
    sends_call = next(c for c in plan.calls if c.key == f"track_sends:{tid}")
    assert sends_call.tool == "ableton_track"
    assert sends_call.args == {"action": "get_sends", "track_index": 5}


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


def test_apply_returns_list_accepts_wrapped_shape_from_unified_surface(conn, song, session):
    """Wave M-2: ableton_return(action='list') returns {"returns": [...]} with
    only identity fields. The apply layer accepts the wrapper natively (no
    skill-side normalization needed)."""
    rid = M.create_return(
        conn, song_id=song, name="A-Reverb", position=1, volume=0.85, pan=0.0
    )
    _link_return(conn, session=session, db_id=rid, ableton_index=1)
    # New shape: wrapped dict + return_index instead of index. Mixer state
    # NOT included — comes via per-return ableton_return(action='info').
    results = [_result("returns_list", {
        "returns": [
            {"return_index": 1, "name": "A-Reverb", "color": None},
        ],
    })]
    out = pull.apply_pull_results(
        conn, results, song_id=song, session_id=session
    )
    # No volume/panning in the list payload → no diff → no mutations.
    assert out.mutations == 0


def test_apply_return_info_skips_unlinked_return(conn, song, session):
    """Defense-in-depth: if a hand-rolled results.json routes a return_info
    payload to a return that isn't linked in this session, the apply layer
    reports it as ``skipped_unlinked`` rather than writing.
    """
    rid = M.create_return(
        conn, song_id=song, name="A-Reverb", position=1, volume=0.85, pan=0.0
    )
    # Deliberately NOT linked.
    results = [{
        "key": f"return_info:{rid}",
        "ok": True,
        "tool": "ableton_return",
        "result": {"return_index": 1, "name": "A-Reverb", "volume": 0.6},
    }]
    out = pull.apply_pull_results(
        conn, results, song_id=song, session_id=session
    )
    assert out.mutations == 0
    assert out.skipped_unlinked == 1
    row = Q.get_return(conn, rid)
    assert row["volume"] == pytest.approx(0.85)  # unchanged


def test_apply_return_info_ingests_mute_and_solo(conn, song, session):
    """M+1-4: return-track mute/solo now round-trip. Asymmetric-None
    handling: DB-side NULL + Ableton-side True/False both count as a
    real change (matches `tracks.mute`/`solo`/`arm` semantics)."""
    rid = M.create_return(
        conn, song_id=song, name="A-Reverb", position=1,
        volume=0.85, pan=0.0,
    )
    _link_return(conn, session=session, db_id=rid, ableton_index=1)
    out = pull.apply_pull_results(
        conn,
        [{
            "key": f"return_info:{rid}",
            "ok": True,
            "tool": "ableton_return",
            "result": {
                "return_index": 1, "name": "A-Reverb", "color": None,
                "volume": 0.85, "panning": 0.0,
                "mute": True, "solo": False,
            },
        }],
        song_id=song, session_id=session,
    )
    assert out.mutations == 1
    row = Q.get_return(conn, rid)
    assert row["mute"] == 1
    assert row["solo"] == 0


def test_apply_return_info_mute_solo_no_op_when_unchanged(conn, song, session):
    """Once DB-side mute/solo match the Ableton state, re-applying the
    same probe is a no-op."""
    rid = M.create_return(
        conn, song_id=song, name="A-Reverb", position=1,
        volume=0.85, pan=0.0,
    )
    M.update_return(conn, return_id=rid, mute=1, solo=0)
    _link_return(conn, session=session, db_id=rid, ableton_index=1)
    out = pull.apply_pull_results(
        conn,
        [{
            "key": f"return_info:{rid}",
            "ok": True,
            "tool": "ableton_return",
            "result": {
                "return_index": 1, "name": "A-Reverb", "color": None,
                "volume": 0.85, "panning": 0.0,
                "mute": True, "solo": False,
            },
        }],
        song_id=song, session_id=session,
    )
    assert out.mutations == 0
    assert out.no_ops == 1


def test_apply_return_info_ingests_mixer_state(conn, song, session):
    """Wave M-2: the per-return info probe carries the mixer state that
    used to live in the returns_list payload. Diffed and applied via
    update_return."""
    rid = M.create_return(
        conn, song_id=song, name="A-Reverb", position=1, volume=0.85, pan=0.0
    )
    _link_return(conn, session=session, db_id=rid, ableton_index=1)
    results = [
        # Note the key kind 'return_info' — the planner emits return_info:<db_id>.
        {
            "key": f"return_info:{rid}",
            "ok": True,
            "tool": "ableton_return",
            "result": {
                "return_index": 1,
                "name": "A-Reverb",
                "color": None,
                "volume": 0.6,
                "panning": -0.1,
                "mute": False,
                "solo": False,
            },
        }
    ]
    out = pull.apply_pull_results(
        conn, results, song_id=song, session_id=session
    )
    assert out.mutations == 1
    row = Q.get_return(conn, rid)
    assert row["volume"] == pytest.approx(0.6)
    assert row["pan"] == pytest.approx(-0.1)


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
    """Wave M-5: retargeted to ableton_arrangement(action='cue_list')."""
    plan = pull.plan_pull_cue_points(conn, song_id=song, session_id=session)
    assert len(plan.calls) == 1
    call = plan.calls[0]
    assert call.tool == "ableton_arrangement"
    assert call.args == {"action": "cue_list"}
    assert call.key == "cue_points_list"


def test_apply_cue_points_accepts_position_beats(conn, song, session):
    """Wave M-5: cue_list returns position_beats. Apply must convert via
    the song's time-signature map to position_bar for DB storage.
    """
    M.add_time_signature_point(conn, song_id=song, start_bar=1.0,
                               numerator=4, denominator=4)
    # 4/4: bar 5 = beats 16; bar 5 + 2 beats = beats 18 → position_bar 5.5
    results = [_result("cue_points_list", [
        {"position_beats": 16.0, "name": "Verse"},
        {"position_beats": 18.0, "name": "Pickup"},
    ])]
    pull.apply_pull_results(conn, results, song_id=song, session_id=session)
    cues = sorted(Q.get_cue_points(conn, song), key=lambda c: c["position_bar"])
    assert len(cues) == 2
    assert cues[0]["position_bar"] == pytest.approx(5.0)
    assert cues[1]["position_bar"] == pytest.approx(5.5)
    # Names round-trip in Wave M-5+.
    assert cues[0]["name"] == "Verse"


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
# plan_pull_devices + _apply_devices_for_parent (W3-3)
# ---------------------------------------------------------------------------


def _devices_payload(*entries: tuple[int, str, str], parent_kind="track",
                     parent_index=2) -> dict:
    """Build an `ableton_device(action='list')` payload from
    ``(device_index, class_name, name)`` tuples. Mirrors the
    `list_handler` shape so the apply tests exercise the real wire shape.
    """
    addr = {f"{parent_kind}_index": parent_index}
    return {
        "parent_kind": parent_kind,
        **addr,
        "devices": [
            {
                "device_index": i, "name": n, "class_name": k,
                "is_active": True,
            }
            for i, k, n in entries
        ],
    }


def test_plan_pull_devices_emits_list_per_linked_track(conn, song, session):
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    _link_track(conn, session=session, db_id=tid, ableton_index=5)
    plan = pull.plan_pull_devices(conn, song_id=song, session_id=session)
    assert len(plan.calls) == 1
    c = plan.calls[0]
    assert c.tool == "ableton_device"
    assert c.args == {"action": "list", "track_index": 5}
    assert c.key == f"track_devices:{tid}"


def test_plan_pull_devices_emits_list_per_linked_return(conn, song, session):
    rid = M.create_return(conn, song_id=song, name="A-Reverb", position=1)
    _link_return(conn, session=session, db_id=rid, ableton_index=1)
    plan = pull.plan_pull_devices(conn, song_id=song, session_id=session)
    assert len(plan.calls) == 1
    c = plan.calls[0]
    assert c.tool == "ableton_device"
    assert c.args == {"action": "list", "return_index": 1}
    assert c.key == f"return_devices:{rid}"


def test_plan_pull_devices_skips_unlinked_with_warning(conn, song, session):
    M.create_track(conn, song_id=song, track_index=1, name="Drums")
    M.create_return(conn, song_id=song, name="A-Reverb", position=1)
    plan = pull.plan_pull_devices(conn, song_id=song, session_id=session)
    assert plan.calls == []
    assert any("not linked" in n.lower() for n in plan.notes)


def test_plan_pull_devices_skips_master_and_return_kinds(
    conn, song, session, master
):
    """Master and the reserved `kind='return'` track rows are not pulled
    via `ableton_track` probes; master has its own future planner, and
    return rows go through the dedicated `returns` table path."""
    rt = M.create_track(
        conn, song_id=song, track_index=99, name="ReservedReturn",
        kind="return",
    )
    _link_track(conn, session=session, db_id=master, ableton_index=0)
    _link_track(conn, session=session, db_id=rt, ableton_index=98)
    plan = pull.plan_pull_devices(conn, song_id=song, session_id=session)
    assert plan.calls == []


def test_plan_pull_devices_args_match_mcp_list_action_schema(
    conn, song, session
):
    """Structural contract: every arg the planner emits for the list probe
    must be a known param on `ableton_device(action='list')`. Mirrors the
    M+1-1 contract test pattern; catches drift if the MCP surface ever
    renames the param or moves the action."""
    from hallucinote_mcp.actions import device as _device_actions  # noqa: F401
    from hallucinote_mcp.schema import all_actions

    list_action = next(
        a for a in all_actions()
        if a.tool == "ableton_device" and a.name == "list"
    )
    schema_param_names = {p.name for p in list_action.params}

    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    _link_track(conn, session=session, db_id=tid, ableton_index=5)
    rid = M.create_return(conn, song_id=song, name="A-Reverb", position=1)
    _link_return(conn, session=session, db_id=rid, ableton_index=1)

    plan = pull.plan_pull_devices(conn, song_id=song, session_id=session)
    for call in plan.calls:
        emitted = set(call.args.keys()) - {"action"}
        unknown = emitted - schema_param_names
        assert not unknown, (
            f"planner emitted args not on ableton_device(list) schema: "
            f"{sorted(unknown)} (full call: {call!r})"
        )


def test_apply_track_devices_creates_chain_and_devices_when_db_empty(
    conn, song, session
):
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    _link_track(conn, session=session, db_id=tid, ableton_index=5)

    out = pull.apply_pull_results(
        conn,
        [_result(
            f"track_devices:{tid}",
            _devices_payload(
                (1, "DrumGroupDevice", "808 Kit"),
                (2, "Compressor2", "Glue"),
            ),
        )],
        song_id=song, session_id=session,
    )
    assert out.mutations == 2
    chains = Q.get_device_chains_for_track(conn, tid)
    assert len(chains) == 1 and chains[0]["position"] == 0
    devs = Q.get_devices_for_chain(conn, chains[0]["id"])
    assert [(d["position"], d["kind"], d["display_name"]) for d in devs] == [
        (1, "DrumGroupDevice", "808 Kit"),
        (2, "Compressor2", "Glue"),
    ]


def test_apply_track_devices_no_op_when_identical(conn, song, session):
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    _link_track(conn, session=session, db_id=tid, ableton_index=5)
    chain_id = M.create_device_chain(conn, parent_track_id=tid, position=0)
    M.create_device(conn, chain_id=chain_id, position=1,
                    kind="Compressor2", display_name="Glue")

    out = pull.apply_pull_results(
        conn,
        [_result(f"track_devices:{tid}",
                 _devices_payload((1, "Compressor2", "Glue")))],
        song_id=song, session_id=session,
    )
    assert out.mutations == 0
    assert out.no_ops == 1


def test_apply_track_devices_replaces_at_position_when_kind_changes(
    conn, song, session
):
    """Different kind at same position -> delete + create at same slot.
    Replacement is structurally a new device since per-device parameters
    cascade off the old id; a hypothetical update_device wouldn't make
    sense across kinds."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    _link_track(conn, session=session, db_id=tid, ableton_index=5)
    chain_id = M.create_device_chain(conn, parent_track_id=tid, position=0)
    old = M.create_device(conn, chain_id=chain_id, position=1,
                          kind="Compressor2", display_name="Glue")

    out = pull.apply_pull_results(
        conn,
        [_result(f"track_devices:{tid}",
                 _devices_payload((1, "Eq8", "EQ8")))],
        song_id=song, session_id=session,
    )
    assert out.mutations == 1
    devs = Q.get_devices_for_chain(conn, chain_id)
    assert len(devs) == 1
    assert devs[0]["kind"] == "Eq8"
    assert devs[0]["display_name"] == "EQ8"
    assert devs[0]["id"] != old  # new device, not in-place update


def test_apply_track_devices_replaces_at_position_when_display_name_changes(
    conn, song, session
):
    """Same kind, different display_name (user renamed a preset) — still
    replace at the slot. Cheaper than a separate rename mutator and
    correct given Live exposes no stable per-device identity."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    _link_track(conn, session=session, db_id=tid, ableton_index=5)
    chain_id = M.create_device_chain(conn, parent_track_id=tid, position=0)
    M.create_device(conn, chain_id=chain_id, position=1,
                    kind="Operator", display_name="Init")

    out = pull.apply_pull_results(
        conn,
        [_result(f"track_devices:{tid}",
                 _devices_payload((1, "Operator", "Soft Bell")))],
        song_id=song, session_id=session,
    )
    assert out.mutations == 1
    devs = Q.get_devices_for_chain(conn, chain_id)
    assert devs[0]["display_name"] == "Soft Bell"


def test_apply_track_devices_deletes_db_devices_absent_from_ableton(
    conn, song, session
):
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    _link_track(conn, session=session, db_id=tid, ableton_index=5)
    chain_id = M.create_device_chain(conn, parent_track_id=tid, position=0)
    M.create_device(conn, chain_id=chain_id, position=1,
                    kind="Compressor2", display_name="Glue")
    M.create_device(conn, chain_id=chain_id, position=2,
                    kind="Eq8", display_name="EQ8")
    M.create_device(conn, chain_id=chain_id, position=3,
                    kind="Limiter", display_name="Limiter")

    out = pull.apply_pull_results(
        conn,
        [_result(f"track_devices:{tid}",
                 _devices_payload((1, "Compressor2", "Glue")))],
        song_id=song, session_id=session,
    )
    # 2 deletes (positions 2 and 3), 1 no-op (position 1)
    assert out.mutations == 2
    devs = Q.get_devices_for_chain(conn, chain_id)
    assert [d["position"] for d in devs] == [1]


def test_apply_track_devices_extends_chain_when_ableton_has_more(
    conn, song, session
):
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    _link_track(conn, session=session, db_id=tid, ableton_index=5)
    chain_id = M.create_device_chain(conn, parent_track_id=tid, position=0)
    M.create_device(conn, chain_id=chain_id, position=1,
                    kind="Compressor2", display_name="Glue")

    out = pull.apply_pull_results(
        conn,
        [_result(f"track_devices:{tid}", _devices_payload(
            (1, "Compressor2", "Glue"),
            (2, "Eq8", "EQ8"),
            (3, "Limiter", "Master Limiter"),
        ))],
        song_id=song, session_id=session,
    )
    # 1 no-op (pos 1), 2 inserts (pos 2 and 3)
    assert out.mutations == 2
    assert out.no_ops == 1
    devs = Q.get_devices_for_chain(conn, chain_id)
    assert [(d["position"], d["kind"]) for d in devs] == [
        (1, "Compressor2"), (2, "Eq8"), (3, "Limiter"),
    ]


def test_apply_track_devices_empty_ableton_empty_db_is_noop(
    conn, song, session
):
    """No DB chain, no Ableton devices — don't create a stub chain row."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    _link_track(conn, session=session, db_id=tid, ableton_index=5)

    out = pull.apply_pull_results(
        conn,
        [_result(f"track_devices:{tid}", _devices_payload())],
        song_id=song, session_id=session,
    )
    assert out.mutations == 0
    assert out.no_ops == 1
    assert Q.get_device_chains_for_track(conn, tid) == []


def test_apply_track_devices_swap_within_chain(conn, song, session):
    """Reorder = positional replacement, because Live's API exposes no
    stable per-device identity. Verifies the delete-before-create order
    doesn't trip the UNIQUE(chain_id, position) constraint, even when
    every slot's kind changes."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    _link_track(conn, session=session, db_id=tid, ableton_index=5)
    chain_id = M.create_device_chain(conn, parent_track_id=tid, position=0)
    M.create_device(conn, chain_id=chain_id, position=1,
                    kind="Eq8", display_name="EQ8")
    M.create_device(conn, chain_id=chain_id, position=2,
                    kind="Compressor2", display_name="Glue")

    out = pull.apply_pull_results(
        conn,
        [_result(f"track_devices:{tid}", _devices_payload(
            (1, "Compressor2", "Glue"),
            (2, "Eq8", "EQ8"),
        ))],
        song_id=song, session_id=session,
    )
    assert out.mutations == 2  # two slot replacements
    devs = Q.get_devices_for_chain(conn, chain_id)
    assert [(d["position"], d["kind"]) for d in devs] == [
        (1, "Compressor2"), (2, "Eq8"),
    ]


def test_apply_return_devices_uses_return_chain(conn, song, session):
    """Smoke test for the return path through the shared helper."""
    rid = M.create_return(conn, song_id=song, name="A-Reverb", position=1)
    _link_return(conn, session=session, db_id=rid, ableton_index=1)

    out = pull.apply_pull_results(
        conn,
        [_result(f"return_devices:{rid}", _devices_payload(
            (1, "Reverb", "Hall"),
            parent_kind="return", parent_index=1,
        ))],
        song_id=song, session_id=session,
    )
    assert out.mutations == 1
    chains = Q.get_device_chains_for_return(conn, rid)
    assert len(chains) == 1
    devs = Q.get_devices_for_chain(conn, chains[0]["id"])
    assert devs[0]["kind"] == "Reverb"


def test_apply_track_devices_skips_unlinked_track(conn, song, session):
    """Hand-rolled results.json shouldn't route around the planner's
    linkage guard. Parity with `_apply_track_info`/`_apply_return_info`."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    # NOT linked.
    out = pull.apply_pull_results(
        conn,
        [_result(f"track_devices:{tid}", _devices_payload(
            (1, "Compressor2", "Glue"),
        ))],
        song_id=song, session_id=session,
    )
    assert out.skipped_unlinked == 1
    assert out.mutations == 0


def test_apply_track_devices_missing_class_name_warns(conn, song, session):
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    _link_track(conn, session=session, db_id=tid, ableton_index=5)

    payload = {
        "parent_kind": "track", "track_index": 5,
        "devices": [{"device_index": 1, "name": "?", "class_name": ""}],
    }
    out = pull.apply_pull_results(
        conn, [_result(f"track_devices:{tid}", payload)],
        song_id=song, session_id=session,
    )
    assert out.mutations == 0
    assert any("class_name" in w for w in out.warnings)


# ---------------------------------------------------------------------------
# plan_pull_arrangement_clips + _apply_arrangement_clips_for_track (W3-4 / M+1-3b)
# ---------------------------------------------------------------------------


def _arr_payload(*entries: tuple[float, float, str], track_index: int = 5) -> dict:
    """Build an `ableton_clip(action='list', location='arrangement')` payload
    from ``(start_beats, length, name)`` tuples. Mirrors the
    `list_handler` arrangement branch shape so apply tests exercise the
    real wire shape (including the `length` field — NOT `end_beats`).
    """
    return {
        "track_index": track_index,
        "location": "arrangement",
        "clips": [
            {
                "arrangement_clip_index": i,
                "name": name,
                "start_beats": sb,
                "length": ln,
            }
            for i, (sb, ln, name) in enumerate(entries, start=1)
        ],
    }


def _seed_arrangement_row(conn, *, song_id, track_id, slot, start_bar, end_bar,
                          length_beats=None, clip_name=None):
    """Create a clips row + arrangement_clips row in one shot. Returns the
    arrangement_clip_id so a test can assert on its presence/absence."""
    if length_beats is None:
        # Default to 4 beats per bar of span. The exact value doesn't matter
        # for the diff tests — the clips row needs *some* length_beats.
        length_beats = (end_bar - start_bar) * 4.0
    clip_id = M.create_clip(
        conn, track_id=track_id, slot=slot,
        length_beats=length_beats, name=clip_name,
    )
    return M.add_arrangement_clip(
        conn, song_id=song_id, track_id=track_id, clip_id=clip_id,
        start_bar=start_bar, end_bar=end_bar,
    )


def test_plan_pull_arrangement_clips_emits_per_linked_track(conn, song, session):
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    _link_track(conn, session=session, db_id=tid, ableton_index=5)
    plan = pull.plan_pull_arrangement_clips(
        conn, song_id=song, session_id=session
    )
    assert len(plan.calls) == 1
    c = plan.calls[0]
    assert c.tool == "ableton_clip"
    assert c.args == {
        "action": "list", "location": "arrangement", "track_index": 5,
    }
    assert c.key == f"track_arrangement_clips:{tid}"


def test_plan_pull_arrangement_clips_skips_unlinked_with_warning(
    conn, song, session
):
    M.create_track(conn, song_id=song, track_index=1, name="Drums")
    plan = pull.plan_pull_arrangement_clips(
        conn, song_id=song, session_id=session
    )
    assert plan.calls == []
    assert any("not linked" in n.lower() for n in plan.notes)


def test_plan_pull_arrangement_clips_skips_master_and_return_kinds(
    conn, song, session, master
):
    """Master and the reserved `kind='return'` track rows are not pulled
    for arrangement clips — master has no arrangement of its own, and
    return rows have no arrangement timeline in Live."""
    rt = M.create_track(
        conn, song_id=song, track_index=99, name="ReservedReturn",
        kind="return",
    )
    _link_track(conn, session=session, db_id=master, ableton_index=0)
    _link_track(conn, session=session, db_id=rt, ableton_index=98)
    plan = pull.plan_pull_arrangement_clips(
        conn, song_id=song, session_id=session
    )
    assert plan.calls == []


def test_plan_pull_arrangement_clips_args_match_mcp_list_action_schema(
    conn, song, session
):
    """Structural contract: every arg the planner emits for the
    arrangement-clip list probe must be a known param on
    `ableton_clip(action='list')`. Same pattern as the M+1-2 device
    contract test."""
    from hallucinote_mcp.actions import clip as _clip_actions  # noqa: F401
    from hallucinote_mcp.schema import all_actions

    list_action = next(
        a for a in all_actions()
        if a.tool == "ableton_clip" and a.name == "list"
    )
    schema_param_names = {p.name for p in list_action.params}

    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    _link_track(conn, session=session, db_id=tid, ableton_index=5)

    plan = pull.plan_pull_arrangement_clips(
        conn, song_id=song, session_id=session
    )
    for call in plan.calls:
        emitted = set(call.args.keys()) - {"action"}
        unknown = emitted - schema_param_names
        assert not unknown, (
            f"planner emitted args not on ableton_clip(list) schema: "
            f"{sorted(unknown)} (full call: {call!r})"
        )


def test_apply_arrangement_clips_no_op_when_identical(conn, song, session):
    """Same (start_bar, end_bar) on both sides -> no-op. Default song
    has no time-signature map, so 4/4 fallback applies: start_beats=0
    is bar 1.0; start_beats + length=8 is bar 3.0 (2 bars of 4 beats).
    """
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    _link_track(conn, session=session, db_id=tid, ableton_index=5)
    _seed_arrangement_row(
        conn, song_id=song, track_id=tid, slot=1,
        start_bar=1.0, end_bar=3.0,
    )

    out = pull.apply_pull_results(
        conn,
        [_result(
            f"track_arrangement_clips:{tid}",
            _arr_payload((0.0, 8.0, "Verse")),
        )],
        song_id=song, session_id=session,
    )
    assert out.mutations == 0
    assert out.no_ops == 1


def test_apply_arrangement_clips_removes_db_placement_absent_in_ableton(
    conn, song, session
):
    """DB has a placement Ableton doesn't -> remove_arrangement_clip +
    mutation count + detail line."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    _link_track(conn, session=session, db_id=tid, ableton_index=5)
    arr_id = _seed_arrangement_row(
        conn, song_id=song, track_id=tid, slot=1,
        start_bar=1.0, end_bar=3.0, clip_name="Verse",
    )

    out = pull.apply_pull_results(
        conn,
        [_result(
            f"track_arrangement_clips:{tid}",
            _arr_payload(),  # empty
        )],
        song_id=song, session_id=session,
    )
    assert out.mutations == 1
    # Confirm the row is gone.
    rows = [
        r for r in Q.get_arrangement_for_song(conn, song)
        if r["id"] == arr_id
    ]
    assert rows == []
    assert any("removed" in d for d in out.details)


def test_apply_arrangement_clips_warns_for_ableton_only_placement(
    conn, song, session
):
    """Ableton has a placement DB doesn't -> warn + skip (V1 cannot
    auto-create a clips row). The DB stays untouched."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    _link_track(conn, session=session, db_id=tid, ableton_index=5)

    out = pull.apply_pull_results(
        conn,
        [_result(
            f"track_arrangement_clips:{tid}",
            _arr_payload((0.0, 8.0, "Mystery")),
        )],
        song_id=song, session_id=session,
    )
    assert out.mutations == 0
    assert any("no matching DB placement" in w for w in out.warnings)
    # No DB rows for this track.
    assert [
        r for r in Q.get_arrangement_for_song(conn, song)
        if r["track_id"] == tid
    ] == []


def test_apply_arrangement_clips_move_is_remove_plus_warn(conn, song, session):
    """A "move" (DB has placement at bars 1..3; Ableton has it at 5..7)
    is structurally `remove_at_old + warn_at_new` since positional
    matching can't distinguish a move from an unrelated delete+add. This
    documents the V1 limitation honestly — the user can recreate the DB
    placement at the new position. Parity with the device-chain
    delete+create pattern for "no stable identity" cases."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    _link_track(conn, session=session, db_id=tid, ableton_index=5)
    _seed_arrangement_row(
        conn, song_id=song, track_id=tid, slot=1,
        start_bar=1.0, end_bar=3.0, clip_name="Verse",
    )

    out = pull.apply_pull_results(
        conn,
        [_result(
            f"track_arrangement_clips:{tid}",
            _arr_payload((16.0, 8.0, "Verse")),  # moved 4 bars later
        )],
        song_id=song, session_id=session,
    )
    assert out.mutations == 1  # the remove
    assert any("no matching DB placement" in w for w in out.warnings)
    # Old row is gone.
    rows_for_track = [
        r for r in Q.get_arrangement_for_song(conn, song)
        if r["track_id"] == tid
    ]
    assert rows_for_track == []


def test_apply_arrangement_clips_float_jitter_within_tolerance_is_no_op(
    conn, song, session
):
    """1e-6 wobble in start_beats must NOT register as a change. The
    apply matches at 1/1000 of a bar precision."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    _link_track(conn, session=session, db_id=tid, ableton_index=5)
    _seed_arrangement_row(
        conn, song_id=song, track_id=tid, slot=1,
        start_bar=1.0, end_bar=3.0,
    )

    out = pull.apply_pull_results(
        conn,
        [_result(
            f"track_arrangement_clips:{tid}",
            # start_beats=1e-7 -> bar 1.000000025; end_beats ≈ 8.0000001 -> bar ≈ 3.0
            _arr_payload((1e-7, 8.0 - 1e-7, "Verse")),
        )],
        song_id=song, session_id=session,
    )
    assert out.mutations == 0
    assert out.no_ops == 1


def test_apply_arrangement_clips_unlinked_track_skips_with_warning(
    conn, song, session
):
    """Defense in depth: a hand-rolled results.json for an unlinked
    track must skip with a warning, not mutate. Parity with
    `_apply_devices_for_parent`."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    # NOT linked.
    _seed_arrangement_row(
        conn, song_id=song, track_id=tid, slot=1,
        start_bar=1.0, end_bar=3.0,
    )

    out = pull.apply_pull_results(
        conn,
        [_result(
            f"track_arrangement_clips:{tid}",
            _arr_payload(),  # would remove the row if it ran
        )],
        song_id=song, session_id=session,
    )
    assert out.skipped_unlinked == 1
    assert out.mutations == 0
    # Row still there.
    assert len([
        r for r in Q.get_arrangement_for_song(conn, song)
        if r["track_id"] == tid
    ]) == 1


def test_apply_arrangement_clips_entry_missing_start_or_length_warns(
    conn, song, session
):
    """Malformed entry with no start_beats / length must warn + skip,
    not crash. Defensive against MCP wire-shape drift."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    _link_track(conn, session=session, db_id=tid, ableton_index=5)

    payload = {
        "track_index": 5,
        "location": "arrangement",
        "clips": [
            {"arrangement_clip_index": 1, "name": "Broken"},  # no fields
        ],
    }
    out = pull.apply_pull_results(
        conn,
        [_result(f"track_arrangement_clips:{tid}", payload)],
        song_id=song, session_id=session,
    )
    assert out.mutations == 0
    assert any("missing start_beats or length" in w for w in out.warnings)


def test_apply_arrangement_clips_missing_clips_field_warns(conn, song, session):
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    _link_track(conn, session=session, db_id=tid, ableton_index=5)

    out = pull.apply_pull_results(
        conn,
        [_result(
            f"track_arrangement_clips:{tid}",
            {"track_index": 5, "location": "arrangement"},  # no 'clips'
        )],
        song_id=song, session_id=session,
    )
    assert out.mutations == 0
    assert any("missing 'clips'" in w for w in out.warnings)


def test_apply_arrangement_clips_emits_arrangement_clip_removed_event(
    conn, song, session
):
    """Mutator discipline: each remove goes through `remove_arrangement_clip`
    and emits an `arrangement_clip_removed` event with actor=sync."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    _link_track(conn, session=session, db_id=tid, ableton_index=5)
    _seed_arrangement_row(
        conn, song_id=song, track_id=tid, slot=1,
        start_bar=1.0, end_bar=3.0,
    )

    pull.apply_pull_results(
        conn,
        [_result(f"track_arrangement_clips:{tid}", _arr_payload())],
        song_id=song, session_id=session, reason="test",
    )
    events = Q.get_events_for_song(conn, song)
    removed = [e for e in events if e["kind"] == "arrangement_clip_removed"]
    assert removed, (
        f"expected an arrangement_clip_removed event; "
        f"got {[e['kind'] for e in events]}"
    )
    assert removed[0]["actor"] == "sync"
    assert removed[0]["reason"] == "test"


def test_apply_arrangement_clips_mixed_diff_states(conn, song, session):
    """One DB row that matches, one DB row that's gone in Ableton, and
    one Ableton row with no DB equivalent — exercises all three diff
    classes in a single call."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    _link_track(conn, session=session, db_id=tid, ableton_index=5)
    keep_id = _seed_arrangement_row(
        conn, song_id=song, track_id=tid, slot=1,
        start_bar=1.0, end_bar=3.0, clip_name="A",
    )
    _seed_arrangement_row(
        conn, song_id=song, track_id=tid, slot=2,
        start_bar=5.0, end_bar=7.0, clip_name="B",
    )

    out = pull.apply_pull_results(
        conn,
        [_result(
            f"track_arrangement_clips:{tid}",
            _arr_payload(
                (0.0, 8.0, "A"),     # matches bars 1..3 -> no-op
                (32.0, 8.0, "C"),    # bars 9..11 in 4/4 -> Ableton-only -> warn
            ),
        )],
        song_id=song, session_id=session,
    )
    assert out.no_ops == 1
    assert out.mutations == 1  # the bars 5..7 remove
    assert any("no matching DB placement" in w for w in out.warnings)
    # The bars 1..3 placement survived.
    surviving = [
        r for r in Q.get_arrangement_for_song(conn, song)
        if r["track_id"] == tid
    ]
    assert len(surviving) == 1
    assert surviving[0]["id"] == keep_id


def test_apply_arrangement_clips_warns_on_duplicate_db_position(
    conn, song, session
):
    """Two DB placements at identical (start_bar, end_bar) on the same
    track surface as a warning (first-row-wins for the diff). The diff
    still proceeds: the kept row no-ops against the matching Ableton
    placement and the colliding row's `clip_name` appears in the warning
    so the user can find it."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    _link_track(conn, session=session, db_id=tid, ableton_index=5)
    # Two placements at identical bars 1..3 — exact-coincidence is the
    # collision case the dict-build would otherwise silently collapse.
    _seed_arrangement_row(
        conn, song_id=song, track_id=tid, slot=1,
        start_bar=1.0, end_bar=3.0, clip_name="First",
    )
    _seed_arrangement_row(
        conn, song_id=song, track_id=tid, slot=2,
        start_bar=1.0, end_bar=3.0, clip_name="Second",
    )

    out = pull.apply_pull_results(
        conn,
        [_result(
            f"track_arrangement_clips:{tid}",
            _arr_payload((0.0, 8.0, "Whatever")),  # matches bars 1..3
        )],
        song_id=song, session_id=session,
    )
    # Apply did NOT remove either row (Ableton confirms one placement at
    # those bars; first-row-wins means it's a no-op for the kept row).
    assert out.mutations == 0
    assert out.no_ops == 1
    # Warning surfaces the collision so the user can act. Both clip
    # names appear in the message — the test doesn't pin which one wins
    # (the query's `(start_bar, id)` ordering makes the choice stable
    # per-DB but the choice is arbitrary from a user POV; either way
    # the collision must be fixed manually).
    collisions = [w for w in out.warnings if "duplicate arrangement-clip" in w]
    assert len(collisions) == 1
    assert "'First'" in collisions[0]
    assert "'Second'" in collisions[0]


def test_apply_arrangement_clips_remove_detail_includes_clip_breadcrumb(
    conn, song, session
):
    """Remove `details` line carries clip_id prefix + clip_name so a user
    chasing a *moved* placement (which surfaces as remove + Ableton-only
    warning) can correlate the two halves by clip name."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    _link_track(conn, session=session, db_id=tid, ableton_index=5)
    arr_id = _seed_arrangement_row(
        conn, song_id=song, track_id=tid, slot=1,
        start_bar=1.0, end_bar=3.0, clip_name="Verse Hook",
    )

    out = pull.apply_pull_results(
        conn,
        [_result(
            f"track_arrangement_clips:{tid}",
            _arr_payload(),  # empty -> the DB row is removed
        )],
        song_id=song, session_id=session,
    )
    assert out.mutations == 1
    detail = out.details[0]
    assert f"arrangement_clip_id={arr_id[:8]}" in detail
    assert "'Verse Hook'" in detail


def test_pull_cli_arrangement_clips_domain_emits_plan(tmp_path):
    """Smoke test: the `arrangement-clips` domain reaches the new
    planner through the CLI dispatch and emits a plan (empty here —
    no linked tracks)."""
    db_path = tmp_path / "arrangement_clips_cli.db"
    conn = init_db(db_path)
    song_id = M.create_song(conn, name="cli_arr", key="Dm")
    session_id = M.create_ableton_session(
        conn, song_id=song_id, name="draft",
    )
    conn.close()

    p = subprocess.run(
        [sys.executable, "-m", "hallucinote.sync.pull_cli",
         "plan", "arrangement-clips", session_id, "--db", str(db_path)],
        capture_output=True, text=True, check=True,
    )
    plan_dict = json.loads(p.stdout)
    assert plan_dict["domain"] == "arrangement-clips"
    assert plan_dict["session_id"] == session_id
    assert plan_dict["calls"] == []
    assert plan_dict["notes"]


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


def test_skill_allowed_tools_cover_every_planner_emitted_tool(
    conn, song, session
):
    """Structural guard: every MCP tool a `_DOMAINS` planner can emit
    must be listed in `.claude/skills/ableton-pull/SKILL.md`'s
    `allowed-tools` frontmatter. Without that, the harness blocks the
    probe even though the SKILL prose advertises the domain — same
    class of bug Critic round 1 + round 2 each caught one layer deeper
    on this chunk (planner unwired from `_DOMAINS`; then `_DOMAINS`
    wired but tool not in allowed-tools).

    Uses a minimal seeded DB (one linked track, one linked return) so
    every planner emits its full set of probes.
    """
    from pathlib import Path
    from hallucinote.sync import pull, pull_cli

    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    _link_track(conn, session=session, db_id=tid, ableton_index=2)
    rid = M.create_return(conn, song_id=song, name="A-Reverb", position=1)
    _link_return(conn, session=session, db_id=rid, ableton_index=1)

    emitted_tools: set[str] = set()
    for planner in pull_cli._DOMAINS.values():
        plan = planner(conn, song_id=song, session_id=session)
        emitted_tools.update(c.tool for c in plan.calls)

    skill_path = Path(__file__).resolve().parents[3] / ".claude" / "skills" \
        / "ableton-pull" / "SKILL.md"
    frontmatter_end = skill_path.read_text().find("\n---\n", 4)
    assert frontmatter_end > 0, "SKILL.md missing closing frontmatter delimiter"
    frontmatter = skill_path.read_text()[:frontmatter_end]
    allowed_line = next(
        ln for ln in frontmatter.splitlines() if ln.startswith("allowed-tools:")
    )

    missing = [
        t for t in sorted(emitted_tools)
        if f"mcp__hallucinote-mcp__{t}" not in allowed_line
    ]
    assert not missing, (
        "SKILL.md `allowed-tools` is missing entries for tools the "
        f"pull planners emit: {missing}. Add "
        f"{', '.join('mcp__hallucinote-mcp__' + t for t in missing)} "
        "to the allowed-tools frontmatter line."
    )


def test_pull_cli_domains_cover_every_public_planner():
    """Structural guard: every `plan_pull_*` function on `pull` must be
    reachable from the CLI's `_DOMAINS` table. The Critic caught the
    M+1-2 miss where `plan_pull_devices` shipped without a CLI entry,
    making the planner unreachable from the `/ableton-pull` skill;
    this test prevents that class of bug going forward."""
    from hallucinote.sync import pull, pull_cli

    public_planners = {
        getattr(pull, name) for name in dir(pull)
        if name.startswith("plan_pull_") and callable(getattr(pull, name))
    }
    cli_planners = set(pull_cli._DOMAINS.values())
    missing = public_planners - cli_planners
    assert not missing, (
        "plan_pull_* functions not reachable via pull_cli._DOMAINS: "
        f"{sorted(p.__name__ for p in missing)}. Register them in "
        "pull_cli._DOMAINS and update .claude/skills/ableton-pull/SKILL.md."
    )


def test_pull_cli_devices_domain_emits_plan(tmp_path):
    """Smoke test: the `devices` domain reaches the new planner through
    the CLI dispatch and emits a plan (empty here — no linked tracks)."""
    db_path = tmp_path / "devices_cli.db"
    conn = init_db(db_path)
    song_id = M.create_song(conn, name="cli_devices", key="Dm")
    session_id = M.create_ableton_session(
        conn, song_id=song_id, name="draft",
    )
    conn.close()

    p = subprocess.run(
        [sys.executable, "-m", "hallucinote.sync.pull_cli",
         "plan", "devices", session_id, "--db", str(db_path)],
        capture_output=True, text=True, check=True,
    )
    plan_dict = json.loads(p.stdout)
    assert plan_dict["domain"] == "devices"
    assert plan_dict["session_id"] == session_id
    # No linked tracks/returns → empty calls + a non-empty notes warning.
    assert plan_dict["calls"] == []
    assert plan_dict["notes"]


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
