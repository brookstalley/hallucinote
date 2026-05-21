"""Tests for the Wave-3 pull planner: plan_pull_mix + apply_pull_results."""
from __future__ import annotations

import json
import subprocess
import sys

import pytest
from hypothesis import given, settings, strategies as st

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
        conn, song_id=song, name="Reverb", position=1, volume=0.85, pan=0.0
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
        conn, song_id=song, name="Reverb", position=1, volume=0.85, pan=0.0
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
        conn, song_id=song, name="Reverb", position=1, volume=0.85, pan=0.0
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
        conn, song_id=song, name="Reverb", position=1,
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
        conn, song_id=song, name="Reverb", position=1,
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


def test_apply_return_info_strips_prefix_no_mutation_on_round_trip(
    conn, song, session,
):
    """W4-C: when the DB stores the SUFFIX-only return name and Ableton
    reports the PREFIXED form, the planner should diff them as equal
    (after stripping) — no name mutation fires for a clean round-trip."""
    rid = M.create_return(
        conn, song_id=song, name="Reverb", position=1,
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
            },
        }],
        song_id=song, session_id=session,
    )
    # Strip + diff matches DB; no changes, so no_ops == 1.
    assert out.mutations == 0
    assert out.no_ops == 1
    row = Q.get_return(conn, rid)
    assert row["name"] == "Reverb"  # still suffix-only


def test_apply_return_info_writes_stripped_name_when_changed(
    conn, song, session,
):
    """W4-C: if Ableton reports a return name that differs from the DB
    (after stripping the prefix), the strip-then-diff path writes the
    stripped form, not the raw Live-prefixed form."""
    rid = M.create_return(
        conn, song_id=song, name="Reverb", position=1,
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
                "return_index": 1, "name": "A-Sidechain", "color": None,
                "volume": 0.85, "panning": 0.0,
            },
        }],
        song_id=song, session_id=session,
    )
    assert out.mutations == 1
    row = Q.get_return(conn, rid)
    assert row["name"] == "Sidechain"  # NOT "A-Sidechain"


def test_apply_return_info_ingests_mixer_state(conn, song, session):
    """Wave M-2: the per-return info probe carries the mixer state that
    used to live in the returns_list payload. Diffed and applied via
    update_return."""
    rid = M.create_return(
        conn, song_id=song, name="Reverb", position=1, volume=0.85, pan=0.0
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
        conn, song_id=song, name="Reverb", position=1
    )
    _link_return(conn, session=session, db_id=rid, ableton_index=1)
    M.set_send_level(conn, from_track_id=tid, to_return_id=rid, level=0.0)
    results = [_result(f"track_sends:{tid}", {"A-Reverb": 0.4})]
    out = pull.apply_pull_results(
        conn, results, song_id=song, session_id=session
    )
    assert out.mutations == 1
    sends = Q.get_sends_for_track(conn, tid)
    # W4-C: DB stores SUFFIX-only return names; the send row joins back the
    # DB-side name "Reverb" even though Ableton's send map was keyed by
    # "A-Reverb".
    assert any(s["return_name"] == "Reverb" and abs(s["level"] - 0.4) < 1e-6
               for s in sends)


def test_apply_track_sends_added_in_ableton(conn, song, session):
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    _link_track(conn, session=session, db_id=tid, ableton_index=5)
    rid = M.create_return(conn, song_id=song, name="Reverb", position=1)
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
    rid = M.create_return(conn, song_id=song, name="Reverb", position=1)
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
    rid = M.create_return(conn, song_id=song, name="Reverb", position=1)
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
    rid = M.create_return(conn, song_id=song, name="Reverb", position=1)
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
    r1 = M.create_return(conn, song_id=song, name="Reverb", position=1)
    _link_return(conn, session=session, db_id=r1, ableton_index=1)
    r2 = M.create_return(conn, song_id=song, name="Delay", position=2)
    _link_return(conn, session=session, db_id=r2, ableton_index=2)
    # 1.5 is out of range (set_send_level rejects > 1.0); 0.3 is valid.
    results = [_result(f"track_sends:{tid}",
                       {"A-Reverb": 1.5, "B-Delay": 0.3})]
    out = pull.apply_pull_results(
        conn, results, song_id=song, session_id=session
    )
    # The valid send went through; the out-of-range one is a warning.
    # W4-C: warning identifies the return by its DB (stripped) form.
    assert out.mutations == 1
    assert any("rejected" in w and "Reverb" in w for w in out.warnings)
    sends = Q.get_sends_for_track(conn, tid)
    # Only Delay should be present.
    assert len(sends) == 1
    assert sends[0]["return_name"] == "Delay"


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


def test_apply_cue_points_legacy_bar_zero_warns_and_skips(conn, song, session):
    """Regression gate: the legacy `{bar, beat}` branch (dormant since the
    legacy fork was retired) used to call `_join_bar_beat(0, ...)` -> 0.0
    and crash on the `cue_points.position_bar >= 1.0` CHECK added in J-6.
    Now: warn + skip. Mirrors the broader engineering-rigor preference for
    structural degradation rather than crash on bad upstream data."""
    M.add_time_signature_point(conn, song_id=song, start_bar=1.0,
                               numerator=4, denominator=4)
    out = pull.apply_pull_results(
        conn,
        [_result("cue_points_list", [
            {"bar": 0, "beat": 0.0, "name": "ShouldNotLand"},
        ])],
        song_id=song, session_id=session,
    )
    assert out.mutations == 0
    assert any("legacy bar=0" in w for w in out.warnings)
    assert Q.get_cue_points(conn, song) == []


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


def _devices_payload(*entries, parent_kind="track", parent_index=2) -> dict:
    """Build an `ableton_device(action='list')` payload from
    ``(device_index, class_name, name)`` or
    ``(device_index, class_name, name, class_display_name)`` tuples.

    Mirrors the post-D4 ``list_handler`` shape: ``class_display_name``
    is the browser display name (drives ``devices.kind`` in pull).

    When the 4th tuple element is omitted, defaults to ``class_name``
    — most of these tests describe devices where class_name and
    display name are interchangeable for the assertion (Operator,
    Limiter, Saturator, etc.) or where the test is about chain
    operations (delete, swap, extend) rather than the name-translation
    semantics. Tests that need the realistic Compressor2→"Compressor"
    or DrumGroupDevice→"Drum Rack" divergence pass explicit
    class_display_name as the 4th element.
    """
    addr = {f"{parent_kind}_index": parent_index}
    devices: list[dict] = []
    for entry in entries:
        if len(entry) == 4:
            i, k, n, cdn = entry
        else:
            i, k, n = entry
            cdn = k  # default: class_display_name == class_name (test-fixture
                     # convenience; real Live would diverge for renamed classes)
        devices.append({
            "device_index": i, "name": n, "class_name": k,
            "class_display_name": cdn,
            "is_active": True,
        })
    return {
        "parent_kind": parent_kind,
        **addr,
        "devices": devices,
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
    rid = M.create_return(conn, song_id=song, name="Reverb", position=1)
    _link_return(conn, session=session, db_id=rid, ableton_index=1)
    plan = pull.plan_pull_devices(conn, song_id=song, session_id=session)
    assert len(plan.calls) == 1
    c = plan.calls[0]
    assert c.tool == "ableton_device"
    assert c.args == {"action": "list", "return_index": 1}
    assert c.key == f"return_devices:{rid}"


def test_plan_pull_devices_skips_unlinked_with_warning(conn, song, session):
    M.create_track(conn, song_id=song, track_index=1, name="Drums")
    M.create_return(conn, song_id=song, name="Reverb", position=1)
    plan = pull.plan_pull_devices(conn, song_id=song, session_id=session)
    assert plan.calls == []
    assert any("not linked" in n.lower() for n in plan.notes)


def test_plan_pull_devices_skips_master_kind(
    conn, song, session, master
):
    """Master track rows are not pulled via the per-track `ableton_device`
    probe; master has its own (future) probe path. Real returns are
    iterated separately in plan_pull_devices via the `returns` table."""
    _link_track(conn, session=session, db_id=master, ableton_index=0)
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
    rid = M.create_return(conn, song_id=song, name="Reverb", position=1)
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
                    kind="Compressor2", display_name="Glue",
                    class_name="Compressor2")

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
                    kind="Compressor2", display_name="Glue",
                    class_name="Compressor2")
    M.create_device(conn, chain_id=chain_id, position=2,
                    kind="Eq8", display_name="EQ8",
                    class_name="Eq8")
    M.create_device(conn, chain_id=chain_id, position=3,
                    kind="Limiter", display_name="Limiter",
                    class_name="Limiter")

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
                    kind="Compressor2", display_name="Glue",
                    class_name="Compressor2")

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
                    kind="Eq8", display_name="EQ8",
                    class_name="Eq8")
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
    rid = M.create_return(conn, song_id=song, name="Reverb", position=1)
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
# plan_pull_nested_rack_chains + _apply_nested_rack_chains_for_device (W7-B)
# ---------------------------------------------------------------------------


def _nested_chains_payload(
    *entries,
    parent_kind="track", parent_index=2, rack_position=1,
    rack_class="DrumGroupDevice",
) -> dict:
    """Build a `get_device_chains` payload from
    ``(chain_index, chain_name, [(position, class_name, display_name)
    or (position, class_name, display_name, class_display_name), ...])``
    tuples per nested chain. Mirrors the post-D4 `get_device_chains_handler`
    shape — `class_display_name` defaults to `class_name` for test fixtures
    that don't care about display-name divergence (matches `_devices_payload`).
    """
    addr = {f"{parent_kind}_index": parent_index}
    chains_out = []
    for ci, name, devs in entries:
        devices = []
        for entry in devs:
            if len(entry) == 4:
                p, k, n, cdn = entry
            else:
                p, k, n = entry
                cdn = k
            devices.append({
                "position": p, "name": n, "class_name": k,
                "class_display_name": cdn,
                "parameter_count": 0, "is_active": True,
            })
        chains_out.append({
            "chain_index": ci,
            "name": name,
            "device_count": len(devs),
            "devices": devices,
            "is_muted": False,
            "is_soloed": False,
        })
    return {
        "device_index": rack_position,
        "class_name": rack_class,
        "chain_count": len(chains_out),
        "chains": chains_out,
        "parent_kind": parent_kind,
        **addr,
    }


def _build_track_with_rack(conn, song, session, *, ableton_index=5):
    """Set up a linked track with a rack device on its top-level chain.
    Returns ``(track_id, chain_id, rack_device_id)``.
    """
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    _link_track(conn, session=session, db_id=tid, ableton_index=ableton_index)
    chain_id = M.create_device_chain(conn, parent_track_id=tid, position=0)
    rack_id = M.create_device(
        conn, chain_id=chain_id, position=1,
        kind="DrumGroupDevice", display_name="Drum Rack",
    )
    return tid, chain_id, rack_id


def test_plan_pull_nested_rack_chains_emits_one_probe_per_rack(
    conn, song, session
):
    _, _, rack_id = _build_track_with_rack(conn, song, session)
    plan = pull.plan_pull_nested_rack_chains(
        conn, song_id=song, session_id=session,
    )
    assert len(plan.calls) == 1
    c = plan.calls[0]
    assert c.tool == "ableton_device"
    assert c.args == {
        "action": "get_device_chains",
        "track_index": 5,
        "device_index": 1,
    }
    assert c.key == f"nested_rack_chains:{rack_id}"


def test_plan_pull_nested_rack_chains_skips_non_racks(conn, song, session):
    """Top-level devices that aren't racks don't get a probe — and don't
    warn either (a valid song shape, not an error)."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Bass")
    _link_track(conn, session=session, db_id=tid, ableton_index=5)
    chain_id = M.create_device_chain(conn, parent_track_id=tid, position=0)
    M.create_device(conn, chain_id=chain_id, position=1,
                    kind="Compressor2", display_name="Glue",
                    class_name="Compressor2")
    plan = pull.plan_pull_nested_rack_chains(
        conn, song_id=song, session_id=session,
    )
    assert plan.calls == []
    # Top-level devices exist; no warning fired.
    assert not any("no top-level devices" in n for n in plan.notes)


def test_plan_pull_nested_rack_chains_warns_when_no_top_level_devices(
    conn, song, session
):
    """No devices at all -> the user almost certainly forgot to run
    `plan_pull_devices` first. Warn so the skill surfaces it."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    _link_track(conn, session=session, db_id=tid, ableton_index=5)
    plan = pull.plan_pull_nested_rack_chains(
        conn, song_id=song, session_id=session,
    )
    assert plan.calls == []
    assert any("no top-level devices" in n for n in plan.notes)


def test_plan_pull_nested_rack_chains_skips_unlinked_track(
    conn, song, session
):
    """Unlinked track -> no probe (silent skip, mirrors
    `plan_pull_device_parameters`'s shape)."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    chain_id = M.create_device_chain(conn, parent_track_id=tid, position=0)
    M.create_device(conn, chain_id=chain_id, position=1,
                    kind="DrumGroupDevice", display_name="Drum Rack")
    # NOT linked.
    plan = pull.plan_pull_nested_rack_chains(
        conn, song_id=song, session_id=session,
    )
    # No calls and no top-level-device warning (the unlinked track filters
    # out before the device walk).
    assert plan.calls == []


def test_plan_pull_nested_rack_chains_emits_for_return_rack(
    conn, song, session
):
    """Racks on a return track get the same treatment — addressing via
    `return_index` instead of `track_index`."""
    rid = M.create_return(conn, song_id=song, name="Send-Bus", position=1)
    _link_return(conn, session=session, db_id=rid, ableton_index=1)
    chain_id = M.create_device_chain(conn, parent_return_id=rid, position=0)
    rack_id = M.create_device(conn, chain_id=chain_id, position=2,
                              kind="AudioEffectGroupDevice", display_name="FX")
    plan = pull.plan_pull_nested_rack_chains(
        conn, song_id=song, session_id=session,
    )
    assert len(plan.calls) == 1
    c = plan.calls[0]
    assert c.args == {
        "action": "get_device_chains",
        "return_index": 1,
        "device_index": 2,
    }
    assert c.key == f"nested_rack_chains:{rack_id}"


def test_plan_pull_nested_rack_chains_args_match_mcp_schema(
    conn, song, session
):
    """Structural contract: every arg the planner emits must be a known
    param on `ableton_device(action='get_device_chains')`."""
    from hallucinote_mcp.actions import device as _device_actions  # noqa: F401
    from hallucinote_mcp.schema import all_actions

    gc_action = next(
        a for a in all_actions()
        if a.tool == "ableton_device" and a.name == "get_device_chains"
    )
    schema_param_names = {p.name for p in gc_action.params}

    _build_track_with_rack(conn, song, session)
    plan = pull.plan_pull_nested_rack_chains(
        conn, song_id=song, session_id=session,
    )
    for call in plan.calls:
        emitted = set(call.args.keys()) - {"action"}
        unknown = emitted - schema_param_names
        assert not unknown, (
            f"planner emitted args not on get_device_chains schema: "
            f"{sorted(unknown)} (full call: {call!r})"
        )


def test_apply_nested_rack_chains_creates_chain_and_devices_when_db_empty(
    conn, song, session
):
    _, _, rack_id = _build_track_with_rack(conn, song, session)
    out = pull.apply_pull_results(
        conn,
        [_result(
            f"nested_rack_chains:{rack_id}",
            _nested_chains_payload(
                (1, "Kick", [(1, "Operator", "Operator")]),
            ),
        )],
        song_id=song, session_id=session,
    )
    # 1 chain create + 1 device create
    assert out.mutations == 2
    chains = Q.get_device_chains_for_rack_device(conn, rack_id)
    assert len(chains) == 1 and chains[0]["position"] == 1
    devs = Q.get_devices_for_chain(conn, chains[0]["id"])
    assert [(d["position"], d["kind"], d["display_name"]) for d in devs] == [
        (1, "Operator", "Operator"),
    ]


def test_apply_nested_rack_chains_no_op_when_identical(conn, song, session):
    _, _, rack_id = _build_track_with_rack(conn, song, session)
    nested_chain = M.create_device_chain(
        conn, parent_rack_device_id=rack_id, position=1,
    )
    M.create_device(conn, chain_id=nested_chain, position=1,
                    kind="Operator", display_name="Operator",
                    class_name="Operator")
    out = pull.apply_pull_results(
        conn,
        [_result(
            f"nested_rack_chains:{rack_id}",
            _nested_chains_payload(
                (1, "Kick", [(1, "Operator", "Operator")]),
            ),
        )],
        song_id=song, session_id=session,
    )
    assert out.mutations == 0
    assert out.no_ops == 1


def test_apply_nested_rack_chains_replaces_nested_device_when_kind_changes(
    conn, song, session
):
    _, _, rack_id = _build_track_with_rack(conn, song, session)
    nested_chain = M.create_device_chain(
        conn, parent_rack_device_id=rack_id, position=1,
    )
    M.create_device(conn, chain_id=nested_chain, position=1,
                    kind="Operator", display_name="Operator",
                    class_name="Operator")
    out = pull.apply_pull_results(
        conn,
        [_result(
            f"nested_rack_chains:{rack_id}",
            _nested_chains_payload(
                (1, "Kick", [(1, "Compressor2", "Glue")]),
            ),
        )],
        song_id=song, session_id=session,
    )
    assert out.mutations == 1
    devs = Q.get_devices_for_chain(conn, nested_chain)
    assert [(d["kind"], d["display_name"]) for d in devs] == [
        ("Compressor2", "Glue"),
    ]


def test_apply_nested_rack_chains_deletes_chain_when_ableton_omits_it(
    conn, song, session
):
    """A nested chain Ableton no longer reports gets removed; cascade clears
    the chain's nested devices + their parameters."""
    _, _, rack_id = _build_track_with_rack(conn, song, session)
    # Two chains in DB; Ableton reports only chain 1.
    M.create_device_chain(conn, parent_rack_device_id=rack_id, position=1)
    chain2 = M.create_device_chain(
        conn, parent_rack_device_id=rack_id, position=2,
    )
    M.create_device(conn, chain_id=chain2, position=1,
                    kind="Sampler", display_name="Sampler")
    out = pull.apply_pull_results(
        conn,
        [_result(
            f"nested_rack_chains:{rack_id}",
            _nested_chains_payload((1, "Kick", [])),
        )],
        song_id=song, session_id=session,
    )
    # Chain 2 deletion mutates; the empty chain 1 is a no-op shape-wise.
    assert out.mutations >= 1
    chains = Q.get_device_chains_for_rack_device(conn, rack_id)
    assert [c["position"] for c in chains] == [1]


def test_apply_nested_rack_chains_warns_when_rack_device_missing(
    conn, song, session
):
    """If the rack row vanished between planner and apply (DB-side drift),
    apply warns and skips rather than crashing."""
    out = pull.apply_pull_results(
        conn,
        [_result(
            "nested_rack_chains:does-not-exist",
            _nested_chains_payload((1, "Kick", [])),
        )],
        song_id=song, session_id=session,
    )
    assert out.mutations == 0
    assert any(
        "rack device row not found" in w
        for w in out.warnings
    )


def test_apply_nested_rack_chains_skips_when_parent_unlinked(
    conn, song, session
):
    """Defense-in-depth link check: a hand-crafted results.json that
    references a rack whose parent track isn't linked in this session
    should be skipped, mirroring `_apply_devices_for_parent`."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    # NOT linked.
    chain_id = M.create_device_chain(conn, parent_track_id=tid, position=0)
    rack_id = M.create_device(conn, chain_id=chain_id, position=1,
                              kind="DrumGroupDevice", display_name="Drum Rack")
    out = pull.apply_pull_results(
        conn,
        [_result(
            f"nested_rack_chains:{rack_id}",
            _nested_chains_payload((1, "Kick", [])),
        )],
        song_id=song, session_id=session,
    )
    assert out.skipped_unlinked == 1
    assert out.mutations == 0
    assert any("not linked in session" in w for w in out.warnings)


def test_apply_nested_rack_chains_warns_when_kind_is_not_rack(
    conn, song, session
):
    """Defense: if the DB device pointed at is not a rack class, the
    handler refuses to spawn nested chains under it. (Should be
    unreachable via the planner, but apply is the source of truth.)"""
    tid = M.create_track(conn, song_id=song, track_index=1, name="x")
    _link_track(conn, session=session, db_id=tid, ableton_index=5)
    chain_id = M.create_device_chain(conn, parent_track_id=tid, position=0)
    not_a_rack = M.create_device(
        conn, chain_id=chain_id, position=1,
        kind="Compressor2", display_name="Glue",
    )
    out = pull.apply_pull_results(
        conn,
        [_result(
            f"nested_rack_chains:{not_a_rack}",
            _nested_chains_payload((1, "Kick", [])),
        )],
        song_id=song, session_id=session,
    )
    assert out.mutations == 0
    assert any("not a rack class" in w for w in out.warnings)


def test_apply_nested_rack_chains_round_trip_simulated_no_op(
    conn, song, session
):
    """End-to-end round-trip: capture rack with two chains into DB; the
    `get_device_chains` probe should return the same shape; apply
    produces zero mutations. This is the convergence invariant."""
    from hallucinote.capture import replay_capture
    snap = {
        "song": {}, "returns": [],
        "tracks": [{
            "index": 1, "name": "Drums", "type": "midi",
            "devices": [{
                "index": 1, "name": "Drum Rack", "class": "DrumGroupDevice",
                "class_name": "DrumGroupDevice",
                "chains": [
                    {"chain_index": 1, "name": "Kick", "devices": [
                        {"index": 1, "name": "Operator", "class": "Operator",
                         "class_name": "Operator"},
                    ]},
                    {"chain_index": 2, "name": "Snare", "devices": [
                        {"index": 1, "name": "Drum Synth", "class": "DrumSynths",
                         "class_name": "DrumSynths"},
                        {"index": 2, "name": "EQ", "class": "Eq8",
                         "class_name": "Eq8"},
                    ]},
                ],
            }],
        }],
    }
    new_song = replay_capture(conn, snap, song_name="rt")
    new_session = M.create_ableton_session(conn, song_id=new_song, name="rt-sess")
    track = next(
        t for t in Q.get_tracks_for_song(conn, new_song) if t["name"] == "Drums"
    )
    _link_track(conn, session=new_session, db_id=track["id"], ableton_index=5)
    rack = Q.get_devices_for_track(conn, track["id"])[0]

    out = pull.apply_pull_results(
        conn,
        [_result(
            f"nested_rack_chains:{rack['id']}",
            _nested_chains_payload(
                (1, "Kick", [(1, "Operator", "Operator")]),
                (2, "Snare", [
                    (1, "DrumSynths", "Drum Synth"),
                    (2, "Eq8", "EQ"),
                ]),
                rack_position=1,
            ),
        )],
        song_id=new_song, session_id=new_session,
    )
    assert out.mutations == 0
    # Two chains in DB, one for each in the payload.
    assert out.no_ops >= 1


# ---------------------------------------------------------------------------
# plan_pull_device_parameters + _apply_device_parameters_for_device (W5-D)
# ---------------------------------------------------------------------------


def _params_payload(
    *entries: tuple[str, float, str, float, float, bool],
    track_index: int = 5,
    device_index: int = 1,
) -> dict:
    """Build an `ableton_device(action='get_parameters', detail='full')`
    payload from ``(name, value, value_display, min, max, is_enum)``
    tuples. Mirrors the real ``get_parameters_handler`` shape with
    ``detail='full'`` so apply tests exercise the wire form W5-D
    actually sees.
    """
    return {
        "device_index": device_index,
        "parent_kind": "track",
        "track_index": track_index,
        "parameters": [
            {
                "name": name,
                "value": float(value),
                "value_display": display,
                "min": float(min_v),
                "max": float(max_v),
                "is_enum": bool(is_enum),
            }
            for (name, value, display, min_v, max_v, is_enum) in entries
        ],
    }


def test_plan_pull_device_parameters_emits_per_linked_track_device(
    conn, song, session,
):
    tid = M.create_track(conn, song_id=song, track_index=1, name="Lead")
    _link_track(conn, session=session, db_id=tid, ableton_index=5)
    chain_id = M.create_device_chain(conn, parent_track_id=tid, position=0)
    did = M.create_device(
        conn, chain_id=chain_id, position=1, kind="Operator", display_name="Init",
    )

    plan = pull.plan_pull_device_parameters(
        conn, song_id=song, session_id=session,
    )
    assert len(plan.calls) == 1
    call = plan.calls[0]
    assert call.tool == "ableton_device"
    assert call.args == {
        "action": "get_parameters", "track_index": 5,
        "device_index": 1, "detail": "full",
    }
    assert call.key == f"device_parameters:{did}"


def test_plan_pull_device_parameters_emits_per_linked_return_device(
    conn, song, session,
):
    rid = M.create_return(conn, song_id=song, name="Reverb", position=1)
    _link_return(conn, session=session, db_id=rid, ableton_index=1)
    chain_id = M.create_device_chain(conn, parent_return_id=rid, position=0)
    did = M.create_device(
        conn, chain_id=chain_id, position=1, kind="Reverb", display_name="Reverb",
    )

    plan = pull.plan_pull_device_parameters(
        conn, song_id=song, session_id=session,
    )
    assert len(plan.calls) == 1
    call = plan.calls[0]
    assert call.args == {
        "action": "get_parameters", "return_index": 1,
        "device_index": 1, "detail": "full",
    }
    assert call.key == f"device_parameters:{did}"


def test_plan_pull_device_parameters_skips_unlinked_track_with_warn(
    conn, song, session,
):
    tid = M.create_track(conn, song_id=song, track_index=1, name="Lead")
    chain_id = M.create_device_chain(conn, parent_track_id=tid, position=0)
    M.create_device(
        conn, chain_id=chain_id, position=1, kind="Operator", display_name="Init",
    )

    plan = pull.plan_pull_device_parameters(
        conn, song_id=song, session_id=session,
    )
    assert plan.calls == []
    assert any("not linked" in n.lower() for n in plan.notes)


def test_plan_pull_device_parameters_warns_when_no_devices(
    conn, song, session,
):
    tid = M.create_track(conn, song_id=song, track_index=1, name="Lead")
    _link_track(conn, session=session, db_id=tid, ableton_index=5)

    plan = pull.plan_pull_device_parameters(
        conn, song_id=song, session_id=session,
    )
    assert plan.calls == []
    assert any("no devices" in n.lower() for n in plan.notes)


def test_plan_pull_device_parameters_args_match_mcp_get_parameters_schema(
    conn, song, session,
):
    """Structural canary — every emitted arg must be a known param on
    ``ableton_device(action='get_parameters')``. Catches drift if the
    MCP surface renames params or moves the action."""
    from hallucinote_mcp.actions import device as _device_actions  # noqa: F401
    from hallucinote_mcp.schema import all_actions

    get_params = next(
        a for a in all_actions()
        if a.tool == "ableton_device" and a.name == "get_parameters"
    )
    schema_param_names = {p.name for p in get_params.params}

    tid = M.create_track(conn, song_id=song, track_index=1, name="Lead")
    _link_track(conn, session=session, db_id=tid, ableton_index=5)
    chain_id = M.create_device_chain(conn, parent_track_id=tid, position=0)
    M.create_device(
        conn, chain_id=chain_id, position=1, kind="Operator", display_name="Init",
    )

    plan = pull.plan_pull_device_parameters(
        conn, song_id=song, session_id=session,
    )
    for call in plan.calls:
        emitted = set(call.args.keys()) - {"action"}
        unknown = emitted - schema_param_names
        assert not unknown, (
            f"planner emitted args not on get_parameters schema: "
            f"{sorted(unknown)} (full call: {call!r})"
        )


def test_apply_device_parameters_creates_when_db_empty(conn, song, session):
    """Diff state: in Live only -> create."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Lead")
    _link_track(conn, session=session, db_id=tid, ableton_index=5)
    chain_id = M.create_device_chain(conn, parent_track_id=tid, position=0)
    did = M.create_device(
        conn, chain_id=chain_id, position=1, kind="Operator", display_name="Init",
    )

    out = pull.apply_pull_results(
        conn,
        [_result(
            f"device_parameters:{did}",
            _params_payload(
                ("Volume", 0.5, "0.50", 0.0, 1.0, False),
                ("Filter Type", 1.0, "Lowpass", 0.0, 3.0, True),
            ),
        )],
        song_id=song, session_id=session,
    )
    assert out.mutations == 2
    rows = Q.get_device_parameters(conn, did)
    by_name = {r["name"]: r for r in rows}
    assert by_name["Volume"]["value_display"] == "0.50"
    assert by_name["Volume"]["value_normalized"] == pytest.approx(0.5)
    # Enum param: value_normalized=NULL per schema.
    assert by_name["Filter Type"]["value_display"] == "Lowpass"
    assert by_name["Filter Type"]["value_normalized"] is None


def test_apply_device_parameters_no_op_when_identical(conn, song, session):
    """Diff state: in both, identical -> no-op."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Lead")
    _link_track(conn, session=session, db_id=tid, ableton_index=5)
    chain_id = M.create_device_chain(conn, parent_track_id=tid, position=0)
    did = M.create_device(
        conn, chain_id=chain_id, position=1, kind="Operator", display_name="Init",
    )
    M.set_device_parameter(
        conn, device_id=did, name="Volume",
        value_display="0.50", value_normalized=0.5,
    )

    out = pull.apply_pull_results(
        conn,
        [_result(
            f"device_parameters:{did}",
            _params_payload(("Volume", 0.5, "0.50", 0.0, 1.0, False)),
        )],
        song_id=song, session_id=session,
    )
    assert out.mutations == 0
    assert out.no_ops == 1


def test_apply_device_parameters_no_op_within_float_epsilon(conn, song, session):
    """Float jitter within `_FLOAT_EPS` is not a diff. Live's value
    readback can wiggle in the last decimal place; that's not a
    real change."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Lead")
    _link_track(conn, session=session, db_id=tid, ableton_index=5)
    chain_id = M.create_device_chain(conn, parent_track_id=tid, position=0)
    did = M.create_device(
        conn, chain_id=chain_id, position=1, kind="Operator", display_name="Init",
    )
    M.set_device_parameter(
        conn, device_id=did, name="Volume",
        value_display="0.85", value_normalized=0.85,
    )

    out = pull.apply_pull_results(
        conn,
        [_result(
            f"device_parameters:{did}",
            _params_payload(("Volume", 0.8501, "0.85", 0.0, 1.0, False)),
        )],
        song_id=song, session_id=session,
    )
    assert out.mutations == 0
    assert out.no_ops == 1


def test_apply_device_parameters_updates_when_value_differs(conn, song, session):
    """Diff state: in both, value differs -> upsert (update)."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Lead")
    _link_track(conn, session=session, db_id=tid, ableton_index=5)
    chain_id = M.create_device_chain(conn, parent_track_id=tid, position=0)
    did = M.create_device(
        conn, chain_id=chain_id, position=1, kind="Operator", display_name="Init",
    )
    M.set_device_parameter(
        conn, device_id=did, name="Volume",
        value_display="0.50", value_normalized=0.5,
    )

    out = pull.apply_pull_results(
        conn,
        [_result(
            f"device_parameters:{did}",
            _params_payload(("Volume", 0.75, "0.75", 0.0, 1.0, False)),
        )],
        song_id=song, session_id=session,
    )
    assert out.mutations == 1
    row = Q.get_device_parameters(conn, did)[0]
    assert row["value_display"] == "0.75"
    assert row["value_normalized"] == pytest.approx(0.75)


def test_apply_device_parameters_removes_db_params_absent_from_live(
    conn, song, session,
):
    """Diff state: in DB only -> remove."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Lead")
    _link_track(conn, session=session, db_id=tid, ableton_index=5)
    chain_id = M.create_device_chain(conn, parent_track_id=tid, position=0)
    did = M.create_device(
        conn, chain_id=chain_id, position=1, kind="Operator", display_name="Init",
    )
    M.set_device_parameter(
        conn, device_id=did, name="Volume",
        value_display="0.50", value_normalized=0.5,
    )
    M.set_device_parameter(
        conn, device_id=did, name="Stale Param",
        value_display="0.50", value_normalized=0.5,
    )

    out = pull.apply_pull_results(
        conn,
        [_result(
            f"device_parameters:{did}",
            _params_payload(("Volume", 0.5, "0.50", 0.0, 1.0, False)),
        )],
        song_id=song, session_id=session,
    )
    assert out.mutations == 1
    rows = Q.get_device_parameters(conn, did)
    assert {r["name"] for r in rows} == {"Volume"}


def test_apply_device_parameters_handles_mixed_diff(conn, song, session):
    """All four diff states in one apply: in-both-same (no-op),
    in-both-differ (update), Live-only (create), DB-only (remove)."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Lead")
    _link_track(conn, session=session, db_id=tid, ableton_index=5)
    chain_id = M.create_device_chain(conn, parent_track_id=tid, position=0)
    did = M.create_device(
        conn, chain_id=chain_id, position=1, kind="Operator", display_name="Init",
    )
    M.set_device_parameter(  # will stay identical
        conn, device_id=did, name="Volume",
        value_display="0.50", value_normalized=0.5,
    )
    M.set_device_parameter(  # will change
        conn, device_id=did, name="Attack",
        value_display="0.10", value_normalized=0.1,
    )
    M.set_device_parameter(  # will be removed (Live no longer has it)
        conn, device_id=did, name="Stale",
        value_display="0.00", value_normalized=0.0,
    )

    out = pull.apply_pull_results(
        conn,
        [_result(
            f"device_parameters:{did}",
            _params_payload(
                ("Volume", 0.5, "0.50", 0.0, 1.0, False),    # no-op
                ("Attack", 0.5, "0.50", 0.0, 1.0, False),    # update
                ("Release", 0.3, "0.30", 0.0, 1.0, False),   # create
            ),
        )],
        song_id=song, session_id=session,
    )
    # 1 update + 1 create + 1 remove = 3 mutations; 1 no-op.
    assert out.mutations == 3
    assert out.no_ops == 1
    by_name = {r["name"]: r for r in Q.get_device_parameters(conn, did)}
    assert set(by_name) == {"Volume", "Attack", "Release"}
    assert by_name["Attack"]["value_display"] == "0.50"
    assert by_name["Release"]["value_display"] == "0.30"


def test_apply_device_parameters_normalizes_against_min_max(conn, song, session):
    """value_normalized = (value - min) / (max - min). The raw 'value'
    from Live is in [min, max]; the DB stores the [0, 1] form. With
    a -60..0 range, value=-12 normalizes to 0.8."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Lead")
    _link_track(conn, session=session, db_id=tid, ableton_index=5)
    chain_id = M.create_device_chain(conn, parent_track_id=tid, position=0)
    did = M.create_device(
        conn, chain_id=chain_id, position=1, kind="Compressor2", display_name="Glue",
    )

    out = pull.apply_pull_results(
        conn,
        [_result(
            f"device_parameters:{did}",
            _params_payload(
                ("Threshold", -12.0, "-12.0 dB", -60.0, 0.0, False),
            ),
        )],
        song_id=song, session_id=session,
    )
    assert out.mutations == 1
    row = Q.get_device_parameters(conn, did)[0]
    assert row["value_display"] == "-12.0 dB"
    assert row["value_normalized"] == pytest.approx(0.8)


def test_apply_device_parameters_constant_range_stores_null_normalized(
    conn, song, session,
):
    """min == max -> normalized is undefined; store NULL.

    Schema CHECK allows NULL when ``value_normalized IS NULL``."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Lead")
    _link_track(conn, session=session, db_id=tid, ableton_index=5)
    chain_id = M.create_device_chain(conn, parent_track_id=tid, position=0)
    did = M.create_device(
        conn, chain_id=chain_id, position=1, kind="Operator", display_name="Init",
    )

    out = pull.apply_pull_results(
        conn,
        [_result(
            f"device_parameters:{did}",
            _params_payload(
                ("Algorithm", 1.0, "Algorithm 1", 1.0, 1.0, False),
            ),
        )],
        song_id=song, session_id=session,
    )
    assert out.mutations == 1
    row = Q.get_device_parameters(conn, did)[0]
    assert row["value_normalized"] is None


def test_apply_device_parameters_clamps_normalized_to_valid_range(
    conn, song, session,
):
    """Live can report ``value`` marginally outside [min, max] due to
    float; the schema CHECK is strict on [0, 1] so the apply layer
    clamps at the boundary instead of letting the mutator raise."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Lead")
    _link_track(conn, session=session, db_id=tid, ableton_index=5)
    chain_id = M.create_device_chain(conn, parent_track_id=tid, position=0)
    did = M.create_device(
        conn, chain_id=chain_id, position=1, kind="Operator", display_name="Init",
    )

    # value just barely past max — would normalize to ~1.0001
    out = pull.apply_pull_results(
        conn,
        [_result(
            f"device_parameters:{did}",
            _params_payload(
                ("Volume", 1.0001, "1.00", 0.0, 1.0, False),
            ),
        )],
        song_id=song, session_id=session,
    )
    assert out.mutations == 1
    row = Q.get_device_parameters(conn, did)[0]
    assert row["value_normalized"] == pytest.approx(1.0)


def test_apply_device_parameters_missing_device_row_warns(conn, song, session):
    """If the device_id in the key doesn't resolve to a DB row, surface
    a warning (the planner shouldn't have emitted, but apply is the
    defensive layer)."""
    out = pull.apply_pull_results(
        conn,
        [_result(
            "device_parameters:nonexistent-uuid",
            _params_payload(("Volume", 0.5, "0.50", 0.0, 1.0, False)),
        )],
        song_id=song, session_id=session,
    )
    assert out.mutations == 0
    assert any("device row not found" in w.lower() for w in out.warnings)


def test_apply_device_parameters_missing_parameters_field_warns(
    conn, song, session,
):
    tid = M.create_track(conn, song_id=song, track_index=1, name="Lead")
    _link_track(conn, session=session, db_id=tid, ableton_index=5)
    chain_id = M.create_device_chain(conn, parent_track_id=tid, position=0)
    did = M.create_device(
        conn, chain_id=chain_id, position=1, kind="Operator", display_name="Init",
    )

    out = pull.apply_pull_results(
        conn,
        [_result(f"device_parameters:{did}", {"device_index": 1})],
        song_id=song, session_id=session,
    )
    assert out.mutations == 0
    assert any("'parameters' field" in w for w in out.warnings)


# Hypothesis property: round-trip apply preserves the synthesized
# parameter set in the DB. Random {name, value, min, max, is_enum}
# tuples → apply → DB rows that match the synthesis (value_display
# verbatim; value_normalized within `_FLOAT_EPS` of the computed
# normalization; NULL for enum / constant-range).
_param_name_strat = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N"), whitelist_characters="_-"
    ),
    min_size=1, max_size=20,
).filter(lambda s: bool(s.strip()))


@st.composite
def _param_tuple(draw):
    name = draw(_param_name_strat)
    is_enum = draw(st.booleans())
    if is_enum:
        # Enum params have value_normalized=NULL; min/max still pass through
        # but aren't used for normalization.
        return (name, 1.0, "EnumLabel", 0.0, 1.0, True)
    min_v = draw(st.floats(min_value=-1000.0, max_value=1000.0,
                            allow_nan=False, allow_infinity=False))
    max_v = draw(st.floats(min_value=min_v, max_value=min_v + 1000.0,
                            allow_nan=False, allow_infinity=False))
    value = draw(st.floats(min_value=min_v, max_value=max_v,
                            allow_nan=False, allow_infinity=False))
    return (name, value, f"{value:.4f}", min_v, max_v, False)


# Deadline disabled: SQLite + tempfile create/destroy per example is
# steady ~50ms but spikes past Hypothesis's default 200ms deadline under
# parallel xdist contention with the rest of the sync suite. The test
# checks correctness, not timing; the round-trip discipline is the
# value, and `max_examples=20` (dev profile) already bounds wall-clock
# cost. Without this, the test surfaces as FlakyFailure on busy machines.
@settings(deadline=None)
@given(
    entries=st.lists(_param_tuple(), min_size=1, max_size=8, unique_by=lambda e: e[0]),
)
def test_apply_device_parameters_property_round_trip(entries):
    """Property: synthesized Live-side params → apply → DB rows that
    match. Pins the (normalize + diff) pipeline against random input.

    Tolerances:
    - ``value_display`` is verbatim verbatim from the wire
    - ``value_normalized`` is within ``_FLOAT_EPS`` (or NULL when the
      synthesized param is enum / constant-range)
    """
    from hallucinote.db import init_db
    import tempfile, os
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        conn = init_db(path)
        song_id = M.create_song(conn, name="prop", key="C")
        tid = M.create_track(
            conn, song_id=song_id, track_index=1, name="Lead", kind="midi",
        )
        session_id = M.create_ableton_session(
            conn, song_id=song_id, name="draft",
        )
        M.link_db_to_ableton(
            conn, session_id=session_id, db_kind="track",
            db_id=tid, ableton_index=5,
        )
        chain_id = M.create_device_chain(conn, parent_track_id=tid, position=0)
        did = M.create_device(
            conn, chain_id=chain_id, position=1,
            kind="Operator", display_name="Init",
        )

        out = pull.apply_pull_results(
            conn,
            [_result(
                f"device_parameters:{did}",
                _params_payload(*entries),
            )],
            song_id=song_id, session_id=session_id,
        )
        assert out.mutations == len(entries), (
            f"expected {len(entries)} mutations, got {out.mutations}"
        )

        rows = {r["name"]: r for r in Q.get_device_parameters(conn, did)}
        for name, value, display, min_v, max_v, is_enum in entries:
            assert name in rows, f"missing param {name!r}"
            row = rows[name]
            assert row["value_display"] == display
            rng = max_v - min_v
            if is_enum or abs(rng) < 1e-9:
                assert row["value_normalized"] is None
            else:
                expected = max(0.0, min(1.0, (value - min_v) / rng))
                assert row["value_normalized"] == pytest.approx(
                    expected, abs=1e-9
                )
        conn.close()
    finally:
        os.unlink(path)


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


def test_plan_pull_arrangement_clips_skips_master_kind(
    conn, song, session, master
):
    """Master track rows are not pulled for arrangement clips — master
    has no arrangement of its own. Real returns live in the `returns`
    table and don't appear in the `tracks` iteration the arrangement-
    clip planner walks."""
    _link_track(conn, session=session, db_id=master, ableton_index=0)
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
# plan_pull_session_clips + _apply_session_clips_for_track (V1 close-out C)
# ---------------------------------------------------------------------------


def _session_payload(*entries, track_index: int = 5) -> dict:
    """Build an `ableton_clip(action='list', location='session')` payload.

    Each entry is either ``("empty", slot)`` for an empty slot or
    ``("populated", slot, name, length)`` for a populated one. Mirrors
    the `list_handler` session branch shape so apply tests exercise the
    real wire shape.
    """
    clips: list[dict] = []
    for e in entries:
        if e[0] == "empty":
            clips.append({"clip_index": e[1], "empty": True})
        elif e[0] == "populated":
            _, slot, name, length = e
            clips.append({
                "clip_index": slot, "empty": False,
                "name": name, "length": float(length),
            })
        else:
            raise ValueError(f"unknown session entry kind: {e[0]!r}")
    return {
        "track_index": track_index,
        "location": "session",
        "clips": clips,
    }


def test_plan_pull_session_clips_emits_per_linked_track(conn, song, session):
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    _link_track(conn, session=session, db_id=tid, ableton_index=5)
    plan = pull.plan_pull_session_clips(
        conn, song_id=song, session_id=session
    )
    assert len(plan.calls) == 1
    c = plan.calls[0]
    assert c.tool == "ableton_clip"
    assert c.args == {
        "action": "list", "location": "session", "track_index": 5,
    }
    assert c.key == f"track_session_clips:{tid}"


def test_plan_pull_session_clips_skips_unlinked_with_warning(
    conn, song, session
):
    M.create_track(conn, song_id=song, track_index=1, name="Drums")
    plan = pull.plan_pull_session_clips(
        conn, song_id=song, session_id=session
    )
    assert plan.calls == []
    assert any("not linked" in n.lower() for n in plan.notes)


def test_plan_pull_session_clips_skips_master_kind(conn, song, session, master):
    """Master tracks have no session-view clip grid in Live."""
    _link_track(conn, session=session, db_id=master, ableton_index=0)
    plan = pull.plan_pull_session_clips(
        conn, song_id=song, session_id=session
    )
    assert plan.calls == []


def test_plan_pull_session_clips_args_match_mcp_list_action_schema(
    conn, song, session
):
    """Structural contract: every arg the planner emits must be a known
    param on `ableton_clip(action='list')`. Mirrors the M+1-1 contract
    test pattern; catches drift if the MCP surface renames the param."""
    from hallucinote_mcp.actions import clip as _clip_actions  # noqa: F401
    from hallucinote_mcp.schema import all_actions

    list_action = next(
        a for a in all_actions()
        if a.tool == "ableton_clip" and a.name == "list"
    )
    schema_param_names = {p.name for p in list_action.params}

    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    _link_track(conn, session=session, db_id=tid, ableton_index=5)
    plan = pull.plan_pull_session_clips(
        conn, song_id=song, session_id=session
    )
    emitted = set(plan.calls[0].args) - {"action"}
    unknown = emitted - schema_param_names
    assert not unknown, (
        f"planner emits args not in ableton_clip(list) schema: {unknown}; "
        f"schema params: {schema_param_names}"
    )


def test_apply_session_clips_no_op_when_matched(conn, song, session):
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    _link_track(conn, session=session, db_id=tid, ableton_index=5)
    M.create_clip(conn, track_id=tid, slot=1, length_beats=16.0, name="A")
    M.create_clip(conn, track_id=tid, slot=3, length_beats=8.0, name="B")

    out = pull.apply_pull_results(
        conn,
        [_result(
            f"track_session_clips:{tid}",
            _session_payload(
                ("populated", 1, "A", 16.0),
                ("empty", 2),
                ("populated", 3, "B", 8.0),
            ),
        )],
        song_id=song, session_id=session,
    )
    assert out.mutations == 0
    # 2 populated matches + 1 empty matches DB-empty -> 3 no-ops.
    assert out.no_ops == 3


def test_apply_session_clips_deletes_db_clip_when_ableton_slot_empty(
    conn, song, session
):
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    _link_track(conn, session=session, db_id=tid, ableton_index=5)
    cid = M.create_clip(conn, track_id=tid, slot=2, length_beats=8.0, name="DropMe")

    out = pull.apply_pull_results(
        conn,
        [_result(
            f"track_session_clips:{tid}",
            _session_payload(("empty", 2)),
        )],
        song_id=song, session_id=session,
    )
    assert out.mutations == 1
    assert Q.get_clip(conn, cid) is None
    assert any("cleared in Ableton" in d for d in out.details)


def test_apply_session_clips_updates_name_when_drifted(conn, song, session):
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    _link_track(conn, session=session, db_id=tid, ableton_index=5)
    cid = M.create_clip(conn, track_id=tid, slot=1, length_beats=16.0, name="OldName")

    out = pull.apply_pull_results(
        conn,
        [_result(
            f"track_session_clips:{tid}",
            _session_payload(("populated", 1, "NewName", 16.0)),
        )],
        song_id=song, session_id=session,
    )
    assert out.mutations == 1
    assert Q.get_clip(conn, cid)["name"] == "NewName"


def test_apply_session_clips_updates_length_when_drifted(conn, song, session):
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    _link_track(conn, session=session, db_id=tid, ableton_index=5)
    cid = M.create_clip(conn, track_id=tid, slot=1, length_beats=16.0, name="A")

    out = pull.apply_pull_results(
        conn,
        [_result(
            f"track_session_clips:{tid}",
            _session_payload(("populated", 1, "A", 8.0)),
        )],
        song_id=song, session_id=session,
    )
    assert out.mutations == 1
    assert Q.get_clip(conn, cid)["length_beats"] == pytest.approx(8.0)


def test_apply_session_clips_length_drift_below_epsilon_is_no_op(
    conn, song, session
):
    """Float jitter parity with mix-state: a tiny length delta should
    no-op rather than churn an event."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    _link_track(conn, session=session, db_id=tid, ableton_index=5)
    M.create_clip(conn, track_id=tid, slot=1, length_beats=16.0, name="A")

    out = pull.apply_pull_results(
        conn,
        [_result(
            f"track_session_clips:{tid}",
            _session_payload(("populated", 1, "A", 16.0 + 1e-5)),
        )],
        song_id=song, session_id=session,
    )
    assert out.mutations == 0
    assert out.no_ops == 1


def test_apply_session_clips_warns_on_ableton_only_slot(conn, song, session):
    """Same V1 limit as arrangement-clip: Ableton-only populated slot
    warns + skips because the wire shape carries no note content for
    auto-create and we can't infer moves."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    _link_track(conn, session=session, db_id=tid, ableton_index=5)

    out = pull.apply_pull_results(
        conn,
        [_result(
            f"track_session_clips:{tid}",
            _session_payload(("populated", 4, "MysteryClip", 12.0)),
        )],
        song_id=song, session_id=session,
    )
    assert out.mutations == 0
    assert any("no matching DB clip" in w and "MysteryClip" in w
               for w in out.warnings)


def test_apply_session_clips_deletes_db_clip_beyond_ableton_range(
    conn, song, session
):
    """DB has a clip at slot 5 but Ableton's dense list only reports
    slots 1..3 (track shortened in Live). The slot-5 DB row is
    treated as out-of-range and deleted."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    _link_track(conn, session=session, db_id=tid, ableton_index=5)
    cid = M.create_clip(conn, track_id=tid, slot=5, length_beats=8.0, name="Stray")

    out = pull.apply_pull_results(
        conn,
        [_result(
            f"track_session_clips:{tid}",
            _session_payload(
                ("empty", 1), ("empty", 2), ("empty", 3),
            ),
        )],
        song_id=song, session_id=session,
    )
    assert out.mutations == 1
    assert Q.get_clip(conn, cid) is None
    assert any("out of Ableton range" in d for d in out.details)


def test_apply_session_clips_emits_clip_updated_event(conn, song, session):
    """Mutator discipline: name+length drift goes through `update_clip`
    and emits a `clip_updated` event with actor=sync."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    _link_track(conn, session=session, db_id=tid, ableton_index=5)
    M.create_clip(conn, track_id=tid, slot=1, length_beats=16.0, name="A")

    pull.apply_pull_results(
        conn,
        [_result(
            f"track_session_clips:{tid}",
            _session_payload(("populated", 1, "A2", 8.0)),
        )],
        song_id=song, session_id=session, reason="test",
    )
    events = Q.get_events_for_song(conn, song)
    updated = [e for e in events if e["kind"] == "clip_updated"]
    assert updated, (
        f"expected a clip_updated event; got {[e['kind'] for e in events]}"
    )
    assert updated[0]["actor"] == "sync"
    assert updated[0]["reason"] == "test"


def test_apply_session_clips_skips_when_track_unlinked(conn, song, session):
    """Defense-in-depth link check parallels arrangement-clip apply."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    out = pull.apply_pull_results(
        conn,
        [_result(
            f"track_session_clips:{tid}",
            _session_payload(("empty", 1)),
        )],
        song_id=song, session_id=session,
    )
    assert out.mutations == 0
    assert out.skipped_unlinked == 1
    assert any("not linked" in w for w in out.warnings)


def test_apply_session_clips_warns_on_missing_clips_field(conn, song, session):
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    _link_track(conn, session=session, db_id=tid, ableton_index=5)
    out = pull.apply_pull_results(
        conn,
        [_result(
            f"track_session_clips:{tid}",
            {"track_index": 5, "location": "session"},  # no 'clips'
        )],
        song_id=song, session_id=session,
    )
    assert out.mutations == 0
    assert any("missing 'clips'" in w for w in out.warnings)


def test_pull_cli_session_clips_domain_emits_plan(tmp_path):
    """Smoke test: `session-clips` domain reaches the new planner via the
    CLI dispatch and emits a plan (empty here — no linked tracks)."""
    db_path = tmp_path / "session_clips_cli.db"
    conn = init_db(db_path)
    song_id = M.create_song(conn, name="cli_sess", key="Dm")
    session_id = M.create_ableton_session(
        conn, song_id=song_id, name="draft",
    )
    conn.close()

    p = subprocess.run(
        [sys.executable, "-m", "hallucinote.sync.pull_cli",
         "plan", "session-clips", session_id, "--db", str(db_path)],
        capture_output=True, text=True, check=True,
    )
    plan_dict = json.loads(p.stdout)
    assert plan_dict["domain"] == "session-clips"
    assert plan_dict["session_id"] == session_id
    assert plan_dict["calls"] == []
    assert plan_dict["notes"]


# ---------------------------------------------------------------------------
# plan_pull_notes_for_clips + _apply_notes_for_clip (V1 close-out D — gap #4)
# ---------------------------------------------------------------------------


def _notes_payload(*notes, track_index=5, clip_index=1):
    """Build an `ableton_note(action='list')` payload from
    ``(note_id, pitch, start_time, duration, velocity, mute)`` tuples.

    Mirrors the real `list_handler` shape (V1 close-out D)."""
    return {
        "track_index": track_index,
        "location": "session",
        "clip_index": clip_index,
        "notes": [
            {
                "note_id": nid, "pitch": p, "start_time": st,
                "duration": dur, "velocity": vel, "mute": bool(mute),
            }
            for (nid, p, st, dur, vel, mute) in notes
        ],
    }


def _link_clip(conn, *, session, db_id, ableton_index):
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="clip",
        db_id=db_id, ableton_index=ableton_index,
    )


def test_plan_pull_notes_emits_per_linked_clip(conn, song, session):
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    cid = M.create_clip(conn, track_id=tid, slot=2, length_beats=8.0, name="A")
    _link_track(conn, session=session, db_id=tid, ableton_index=5)
    _link_clip(conn, session=session, db_id=cid, ableton_index=2)

    plan = pull.plan_pull_notes_for_clips(
        conn, song_id=song, session_id=session,
    )
    assert len(plan.calls) == 1
    c = plan.calls[0]
    assert c.tool == "ableton_note"
    assert c.args == {
        "action": "list", "track_index": 5,
        "location": "session", "clip_index": 2,
    }
    assert c.key == f"clip_notes:{cid}"


def test_plan_pull_notes_skips_unlinked_track_with_warning(
    conn, song, session
):
    """Clip is linked but its track isn't — skip + warn."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    cid = M.create_clip(conn, track_id=tid, slot=1, length_beats=8.0)
    _link_clip(conn, session=session, db_id=cid, ableton_index=1)

    plan = pull.plan_pull_notes_for_clips(
        conn, song_id=song, session_id=session,
    )
    assert plan.calls == []
    assert any("track" in n.lower() and "not" in n.lower() for n in plan.notes)


def test_plan_pull_notes_warns_when_no_clips_linked(conn, song, session):
    plan = pull.plan_pull_notes_for_clips(
        conn, song_id=song, session_id=session,
    )
    assert plan.calls == []
    assert any("no clips linked" in n.lower() for n in plan.notes)


def test_plan_pull_notes_args_match_mcp_list_action_schema(
    conn, song, session
):
    """Structural contract: every arg the planner emits must be a known
    param on `ableton_note(action='list')`. Mirrors the M+1-1 pattern."""
    from hallucinote_mcp.actions import note as _note_actions  # noqa: F401
    from hallucinote_mcp.schema import all_actions

    list_action = next(
        a for a in all_actions()
        if a.tool == "ableton_note" and a.name == "list"
    )
    schema_param_names = {p.name for p in list_action.params}

    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    cid = M.create_clip(conn, track_id=tid, slot=1, length_beats=8.0)
    _link_track(conn, session=session, db_id=tid, ableton_index=5)
    _link_clip(conn, session=session, db_id=cid, ableton_index=1)
    plan = pull.plan_pull_notes_for_clips(
        conn, song_id=song, session_id=session,
    )
    emitted = set(plan.calls[0].args) - {"action"}
    unknown = emitted - schema_param_names
    assert not unknown, (
        f"planner emits args not in ableton_note(list) schema: {unknown}; "
        f"schema params: {schema_param_names}"
    )


def test_apply_notes_no_op_when_matched(conn, song, session):
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    cid = M.create_clip(conn, track_id=tid, slot=1, length_beats=8.0)
    _link_track(conn, session=session, db_id=tid, ableton_index=5)
    _link_clip(conn, session=session, db_id=cid, ableton_index=1)
    M.insert_notes(conn, clip_id=cid, notes=[
        {"pitch": 60, "start_beats": 0.0, "duration_beats": 1.0, "velocity": 100, "mute": 0},
        {"pitch": 64, "start_beats": 1.0, "duration_beats": 0.5, "velocity": 80, "mute": 0},
    ])

    out = pull.apply_pull_results(
        conn,
        [_result(
            f"clip_notes:{cid}",
            _notes_payload(
                (101, 60, 0.0, 1.0, 100, False),
                (102, 64, 1.0, 0.5, 80, False),
            ),
        )],
        song_id=song, session_id=session,
    )
    assert out.mutations == 0
    assert out.no_ops == 2


def test_apply_notes_updates_velocity_and_preserves_uuid(
    conn, song, session
):
    """Common compose-time edit: same notes, different velocities. The
    DB-side note UUID is preserved because match is content-based on
    (pitch, start, duration) — velocity changes don't affect the key."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    cid = M.create_clip(conn, track_id=tid, slot=1, length_beats=8.0)
    _link_track(conn, session=session, db_id=tid, ableton_index=5)
    _link_clip(conn, session=session, db_id=cid, ableton_index=1)
    [nid] = M.insert_notes(conn, clip_id=cid, notes=[
        {"pitch": 60, "start_beats": 0.0, "duration_beats": 1.0, "velocity": 100, "mute": 0},
    ])

    out = pull.apply_pull_results(
        conn,
        [_result(
            f"clip_notes:{cid}",
            _notes_payload((101, 60, 0.0, 1.0, 75, False)),
        )],
        song_id=song, session_id=session,
    )
    assert out.mutations == 1
    notes = Q.get_notes_for_clip(conn, cid)
    assert len(notes) == 1
    # UUID preserved.
    assert notes[0]["id"] == nid
    assert notes[0]["velocity"] == 75


def test_apply_notes_updates_mute_when_drifted(conn, song, session):
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    cid = M.create_clip(conn, track_id=tid, slot=1, length_beats=8.0)
    _link_track(conn, session=session, db_id=tid, ableton_index=5)
    _link_clip(conn, session=session, db_id=cid, ableton_index=1)
    [nid] = M.insert_notes(conn, clip_id=cid, notes=[
        {"pitch": 60, "start_beats": 0.0, "duration_beats": 1.0, "velocity": 100, "mute": 0},
    ])

    out = pull.apply_pull_results(
        conn,
        [_result(
            f"clip_notes:{cid}",
            _notes_payload((101, 60, 0.0, 1.0, 100, True)),
        )],
        song_id=song, session_id=session,
    )
    assert out.mutations == 1
    notes = Q.get_notes_for_clip(conn, cid)
    assert notes[0]["id"] == nid
    assert notes[0]["mute"] == 1


def test_apply_notes_inserts_ableton_only_notes(conn, song, session):
    """Ableton has a note the DB doesn't — insert (UUID assigned)."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    cid = M.create_clip(conn, track_id=tid, slot=1, length_beats=8.0)
    _link_track(conn, session=session, db_id=tid, ableton_index=5)
    _link_clip(conn, session=session, db_id=cid, ableton_index=1)

    out = pull.apply_pull_results(
        conn,
        [_result(
            f"clip_notes:{cid}",
            _notes_payload(
                (101, 60, 0.0, 1.0, 100, False),
                (102, 62, 0.5, 1.0, 90, False),
            ),
        )],
        song_id=song, session_id=session,
    )
    # One mutation = the batched insert; out.no_ops is 0 because neither
    # note had a DB match to no-op against.
    assert out.mutations == 1
    notes = Q.get_notes_for_clip(conn, cid)
    assert len(notes) == 2
    pitches = sorted(n["pitch"] for n in notes)
    assert pitches == [60, 62]


def test_apply_notes_deletes_db_notes_absent_from_ableton(
    conn, song, session
):
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    cid = M.create_clip(conn, track_id=tid, slot=1, length_beats=8.0)
    _link_track(conn, session=session, db_id=tid, ableton_index=5)
    _link_clip(conn, session=session, db_id=cid, ableton_index=1)
    M.insert_notes(conn, clip_id=cid, notes=[
        {"pitch": 60, "start_beats": 0.0, "duration_beats": 1.0, "velocity": 100, "mute": 0},
        {"pitch": 62, "start_beats": 0.5, "duration_beats": 1.0, "velocity": 90, "mute": 0},
    ])

    out = pull.apply_pull_results(
        conn,
        [_result(
            f"clip_notes:{cid}",
            _notes_payload((101, 60, 0.0, 1.0, 100, False)),
        )],
        song_id=song, session_id=session,
    )
    # One mutation = the batched delete of the bp 62 note.
    assert out.mutations == 1
    notes = Q.get_notes_for_clip(conn, cid)
    assert len(notes) == 1
    assert notes[0]["pitch"] == 60


def test_apply_notes_handles_mixed_diff(conn, song, session):
    """One match, one velocity update, one insert, one delete in a
    single call — covers all four diff classes against the same clip."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    cid = M.create_clip(conn, track_id=tid, slot=1, length_beats=8.0)
    _link_track(conn, session=session, db_id=tid, ableton_index=5)
    _link_clip(conn, session=session, db_id=cid, ableton_index=1)
    M.insert_notes(conn, clip_id=cid, notes=[
        {"pitch": 60, "start_beats": 0.0, "duration_beats": 1.0, "velocity": 100, "mute": 0},  # match
        {"pitch": 62, "start_beats": 1.0, "duration_beats": 1.0, "velocity": 90, "mute": 0},   # update vel
        {"pitch": 64, "start_beats": 2.0, "duration_beats": 1.0, "velocity": 80, "mute": 0},   # delete
    ])

    out = pull.apply_pull_results(
        conn,
        [_result(
            f"clip_notes:{cid}",
            _notes_payload(
                (101, 60, 0.0, 1.0, 100, False),  # match
                (102, 62, 1.0, 1.0, 75, False),   # velocity drift
                (103, 67, 3.0, 1.0, 100, False),  # insert
            ),
        )],
        song_id=song, session_id=session,
    )
    # mutations: 1 update + 1 insert (batched) + 1 delete (batched) = 3.
    assert out.mutations == 3
    assert out.no_ops == 1
    notes = sorted(Q.get_notes_for_clip(conn, cid), key=lambda n: n["pitch"])
    pitches = [n["pitch"] for n in notes]
    assert pitches == [60, 62, 67]


def test_apply_notes_warns_on_likely_uuid_rotation(conn, song, session):
    """A note moved in time (same pitch + velocity + mute, different
    start/duration) surfaces as delete + insert because the content
    key includes start + duration. The UUID rotates, which is a
    documented V1 limitation — warn so the user knows to edit DB-side
    by UUID if note identity matters to them. (W10-C)"""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    cid = M.create_clip(conn, track_id=tid, slot=1, length_beats=8.0)
    _link_track(conn, session=session, db_id=tid, ableton_index=5)
    _link_clip(conn, session=session, db_id=cid, ableton_index=1)
    M.insert_notes(conn, clip_id=cid, notes=[
        {"pitch": 60, "start_beats": 0.0, "duration_beats": 1.0,
         "velocity": 100, "mute": 0},
        {"pitch": 62, "start_beats": 2.0, "duration_beats": 1.0,
         "velocity": 80, "mute": 0},
    ])

    out = pull.apply_pull_results(
        conn,
        [_result(
            f"clip_notes:{cid}",
            _notes_payload(
                (101, 60, 0.5, 1.0, 100, False),  # moved +0.5 beats
                (102, 62, 2.0, 1.0, 80, False),   # unchanged - no-op
            ),
        )],
        song_id=song, session_id=session,
    )
    assert any(
        "look moved" in w and "UUID rotates" in w
        for w in out.warnings
    ), out.warnings
    # Warning names the moved note(s) so the user can act on it.
    assert any(
        "pitch 60 0->0.5" in w and "note_id" in w for w in out.warnings
    ), out.warnings
    # The diff still applies as delete + insert; warning is informational.
    pitches = sorted(
        n["pitch"] for n in Q.get_notes_for_clip(conn, cid)
    )
    assert pitches == [60, 62]


def test_apply_notes_no_uuid_warning_when_pitch_differs(
    conn, song, session,
):
    """Independent delete + insert (different pitches) — not a moved
    note, no warning."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    cid = M.create_clip(conn, track_id=tid, slot=1, length_beats=8.0)
    _link_track(conn, session=session, db_id=tid, ableton_index=5)
    _link_clip(conn, session=session, db_id=cid, ableton_index=1)
    M.insert_notes(conn, clip_id=cid, notes=[
        {"pitch": 60, "start_beats": 0.0, "duration_beats": 1.0,
         "velocity": 100, "mute": 0},
    ])

    out = pull.apply_pull_results(
        conn,
        [_result(
            f"clip_notes:{cid}",
            _notes_payload((101, 67, 0.0, 1.0, 100, False)),
        )],
        song_id=song, session_id=session,
    )
    assert not any("look moved" in w for w in out.warnings), out.warnings


def test_apply_notes_no_uuid_warning_when_velocity_differs(
    conn, song, session,
):
    """Same pitch but different velocity is ambiguous (could be a
    new note at the same pitch). Stay quiet rather than crying wolf."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    cid = M.create_clip(conn, track_id=tid, slot=1, length_beats=8.0)
    _link_track(conn, session=session, db_id=tid, ableton_index=5)
    _link_clip(conn, session=session, db_id=cid, ableton_index=1)
    M.insert_notes(conn, clip_id=cid, notes=[
        {"pitch": 60, "start_beats": 0.0, "duration_beats": 1.0,
         "velocity": 100, "mute": 0},
    ])

    out = pull.apply_pull_results(
        conn,
        [_result(
            f"clip_notes:{cid}",
            _notes_payload((101, 60, 2.0, 1.0, 80, False)),
        )],
        song_id=song, session_id=session,
    )
    assert not any("look moved" in w for w in out.warnings), out.warnings


def test_apply_notes_warns_on_duplicate_ableton_key(conn, song, session):
    """Two Ableton notes at identical (pitch, start, duration) — first
    entry wins for the diff; subsequent entry surfaces a warning so the
    user can differentiate the upstream duplication."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    cid = M.create_clip(conn, track_id=tid, slot=1, length_beats=8.0)
    _link_track(conn, session=session, db_id=tid, ableton_index=5)
    _link_clip(conn, session=session, db_id=cid, ableton_index=1)
    M.insert_notes(conn, clip_id=cid, notes=[
        {"pitch": 60, "start_beats": 0.0, "duration_beats": 1.0, "velocity": 100, "mute": 0},
    ])

    out = pull.apply_pull_results(
        conn,
        [_result(
            f"clip_notes:{cid}",
            _notes_payload(
                (101, 60, 0.0, 1.0, 100, False),  # matches DB - no-op
                (102, 60, 0.0, 1.0, 80, False),   # duplicate Ableton entry
            ),
        )],
        song_id=song, session_id=session,
    )
    assert any("duplicate Ableton notes" in w for w in out.warnings)
    # No insert / update / delete — the duplicate is ignored and the
    # first entry's match already no-opped.
    assert out.mutations == 0
    assert out.no_ops == 1


def test_apply_notes_warns_on_duplicate_db_key(conn, song, session):
    """Two DB notes at identical (pitch, start, duration) — warn +
    first-wins, mirroring the arrangement-clip collision handling."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    cid = M.create_clip(conn, track_id=tid, slot=1, length_beats=8.0)
    _link_track(conn, session=session, db_id=tid, ableton_index=5)
    _link_clip(conn, session=session, db_id=cid, ableton_index=1)
    M.insert_notes(conn, clip_id=cid, notes=[
        {"pitch": 60, "start_beats": 0.0, "duration_beats": 1.0, "velocity": 100, "mute": 0},
        {"pitch": 60, "start_beats": 0.0, "duration_beats": 1.0, "velocity": 80, "mute": 0},
    ])

    out = pull.apply_pull_results(
        conn,
        [_result(
            f"clip_notes:{cid}",
            _notes_payload((101, 60, 0.0, 1.0, 100, False)),
        )],
        song_id=song, session_id=session,
    )
    # Ableton confirms one note at that position; first-wins no-ops. The
    # second DB row falls out of the diff (not seen by Ableton) — but it's
    # never added to `db_by_key`, so it's not classed as "to delete"
    # either. It just sits there, surfaced via the collision warning.
    assert out.mutations == 0
    assert any("duplicate notes" in w for w in out.warnings)


def test_apply_notes_skips_when_clip_unlinked(conn, song, session):
    """Defense-in-depth link check parallels arrangement-clip apply."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    cid = M.create_clip(conn, track_id=tid, slot=1, length_beats=8.0)
    out = pull.apply_pull_results(
        conn,
        [_result(f"clip_notes:{cid}", _notes_payload())],
        song_id=song, session_id=session,
    )
    assert out.mutations == 0
    assert out.skipped_unlinked == 1
    assert any("not linked" in w for w in out.warnings)


def test_apply_notes_warns_on_missing_notes_field(conn, song, session):
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    cid = M.create_clip(conn, track_id=tid, slot=1, length_beats=8.0)
    _link_track(conn, session=session, db_id=tid, ableton_index=5)
    _link_clip(conn, session=session, db_id=cid, ableton_index=1)
    out = pull.apply_pull_results(
        conn,
        [_result(
            f"clip_notes:{cid}",
            {"track_index": 5, "location": "session", "clip_index": 1},
        )],
        song_id=song, session_id=session,
    )
    assert out.mutations == 0
    assert any("missing 'notes'" in w for w in out.warnings)


def test_apply_notes_emits_note_updated_event(conn, song, session):
    """Mutator discipline: velocity drift goes through `update_note` and
    emits a `note_updated` event with actor=sync.

    Queries the events table by `clip_id` rather than `get_events_for_song`
    because note mutators (insert_notes / update_note / delete_notes)
    don't set the song_id column on their emitted events — they're
    scoped via clip_id. Filing the omission for a future structural fix
    is one option, but the events ARE emitted and ARE attributable.
    """
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    cid = M.create_clip(conn, track_id=tid, slot=1, length_beats=8.0)
    _link_track(conn, session=session, db_id=tid, ableton_index=5)
    _link_clip(conn, session=session, db_id=cid, ableton_index=1)
    M.insert_notes(conn, clip_id=cid, notes=[
        {"pitch": 60, "start_beats": 0.0, "duration_beats": 1.0, "velocity": 100, "mute": 0},
    ])

    pull.apply_pull_results(
        conn,
        [_result(
            f"clip_notes:{cid}",
            _notes_payload((101, 60, 0.0, 1.0, 75, False)),
        )],
        song_id=song, session_id=session, reason="test",
    )
    rows = conn.execute(
        "SELECT kind, actor, reason FROM events WHERE clip_id = ? AND kind = 'note_updated' ORDER BY seq",
        (cid,),
    ).fetchall()
    assert rows, "expected a note_updated event scoped to the clip"
    assert rows[0]["actor"] == "sync"
    assert rows[0]["reason"] == "test"


def test_pull_cli_clip_notes_domain_emits_plan(tmp_path):
    """Smoke test: `clip-notes` domain reaches the planner via the CLI
    dispatch and emits a plan (empty here — no linked clips)."""
    db_path = tmp_path / "clip_notes_cli.db"
    conn = init_db(db_path)
    song_id = M.create_song(conn, name="cli_notes", key="Dm")
    session_id = M.create_ableton_session(
        conn, song_id=song_id, name="draft",
    )
    conn.close()

    p = subprocess.run(
        [sys.executable, "-m", "hallucinote.sync.pull_cli",
         "plan", "clip-notes", session_id, "--db", str(db_path)],
        capture_output=True, text=True, check=True,
    )
    plan_dict = json.loads(p.stdout)
    assert plan_dict["domain"] == "clip-notes"
    assert plan_dict["session_id"] == session_id
    assert plan_dict["calls"] == []
    assert plan_dict["notes"]


# ---------------------------------------------------------------------------
# Round-trip: push -> mutate Ableton-side dict -> pull -> DB matches
# ---------------------------------------------------------------------------


def test_clip_notes_end_to_end_round_trip(conn, song, session):
    """W7-C: end-to-end note round-trip pin — push DB state into a
    simulated Ableton payload, pull it back, confirm convergence.

    Individual diff classes (no-op / update / delete / insert) are
    covered by sibling tests; this is the end-to-end contract pin.
    """
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    cid = M.create_clip(conn, track_id=tid, slot=1, length_beats=8.0, name="A")
    _link_track(conn, session=session, db_id=tid, ableton_index=5)
    _link_clip(conn, session=session, db_id=cid, ableton_index=1)
    M.insert_notes(
        conn, clip_id=cid,
        notes=[
            {"pitch": 60, "start_beats": 0.0, "duration_beats": 0.5,
             "velocity": 100, "mute": 0},
            {"pitch": 62, "start_beats": 1.0, "duration_beats": 0.5,
             "velocity": 100, "mute": 0},
            {"pitch": 64, "start_beats": 2.0, "duration_beats": 0.5,
             "velocity": 100, "mute": 0},
        ],
    )
    db_notes_before = Q.get_notes_for_clip(conn, cid)
    db_note_ids_by_key = {
        (n["pitch"], n["start_beats"], n["duration_beats"]): n["id"]
        for n in db_notes_before
    }

    # Round-trip 1: Ableton state mirrors DB — convergent, zero
    # mutations. The simulated note_id values are arbitrary (Live
    # regenerates them on every write; apply doesn't persist them).
    same_state = [
        _result(f"clip_notes:{cid}", _notes_payload(
            (10, 60, 0.0, 0.5, 100, False),
            (11, 62, 1.0, 0.5, 100, False),
            (12, 64, 2.0, 0.5, 100, False),
        )),
    ]
    out1 = pull.apply_pull_results(
        conn, same_state, song_id=song, session_id=session,
    )
    assert out1.mutations == 0
    assert out1.no_ops == 3
    # UUIDs preserved across the no-op pull.
    db_notes_after_noop = Q.get_notes_for_clip(conn, cid)
    after_ids_by_key = {
        (n["pitch"], n["start_beats"], n["duration_beats"]): n["id"]
        for n in db_notes_after_noop
    }
    assert after_ids_by_key == db_note_ids_by_key

    # Round-trip 2: user dragged a velocity, removed one note, added one.
    # Pitch 62's velocity 100 -> 80 (UPDATE — same key, vel drift).
    # Pitch 64 disappears (DELETE).
    # New pitch 67 at start 3.0 (INSERT).
    drifted_state = [
        _result(f"clip_notes:{cid}", _notes_payload(
            (20, 60, 0.0, 0.5, 100, False),
            (21, 62, 1.0, 0.5,  80, False),
            (22, 67, 3.0, 0.5, 100, False),
        )),
    ]
    out2 = pull.apply_pull_results(
        conn, drifted_state, song_id=song, session_id=session,
    )
    assert out2.mutations >= 3, (out2.mutations, out2.details)
    db_notes_after = Q.get_notes_for_clip(conn, cid)
    by_pitch_start = {(n["pitch"], n["start_beats"]): n for n in db_notes_after}
    assert (60, 0.0) in by_pitch_start
    assert by_pitch_start[(62, 1.0)]["velocity"] == 80
    assert (64, 2.0) not in by_pitch_start
    assert (67, 3.0) in by_pitch_start
    # Pitch-60 + pitch-62 UUIDs preserved (velocity update is in-place).
    assert by_pitch_start[(60, 0.0)]["id"] == db_note_ids_by_key[(60, 0.0, 0.5)]
    assert by_pitch_start[(62, 1.0)]["id"] == db_note_ids_by_key[(62, 1.0, 0.5)]

    # Round-trip 3: re-applying drifted_state is now a full no-op.
    out3 = pull.apply_pull_results(
        conn, drifted_state, song_id=song, session_id=session,
    )
    assert out3.mutations == 0


def test_round_trip_push_then_pull(conn, song, session, master):
    """Set DB state, simulate Ableton drift, pull, confirm DB caught up."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    M.set_track_mixer(conn, track_id=tid, volume=0.6, pan=0.0)
    _link_track(conn, session=session, db_id=tid, ableton_index=5)
    rid = M.create_return(conn, song_id=song, name="Reverb",
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
    rid = M.create_return(conn, song_id=song, name="Reverb", position=1)
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


def test_pull_cli_device_parameters_domain_emits_plan(tmp_path):
    """Smoke test: the `device-parameters` domain reaches the new W5-D
    planner through the CLI dispatch and emits a plan (empty here — no
    linked tracks)."""
    db_path = tmp_path / "device_params_cli.db"
    conn = init_db(db_path)
    song_id = M.create_song(conn, name="cli_dp", key="Dm")
    session_id = M.create_ableton_session(
        conn, song_id=song_id, name="draft",
    )
    conn.close()

    p = subprocess.run(
        [sys.executable, "-m", "hallucinote.sync.pull_cli",
         "plan", "device-parameters", session_id, "--db", str(db_path)],
        capture_output=True, text=True, check=True,
    )
    plan_dict = json.loads(p.stdout)
    assert plan_dict["domain"] == "device-parameters"
    assert plan_dict["session_id"] == session_id
    assert plan_dict["calls"] == []
    assert plan_dict["notes"]


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


# ---------------------------------------------------------------------------
# Arc 3 / C3 — pull_cli execute (in-process probe + apply)
# ---------------------------------------------------------------------------


def _fake_pull_send_factory(routes):
    """Build a fake MCP send_fn keyed by
    ``(tool, action, track_index, return_index, device_index)``.

    Use ``None`` for any of the three index slots when the call doesn't
    carry that param. ``routes`` values are either a dict (used as
    ``result``) or a string (treated as ok=False error). Unrouted calls
    raise AssertionError so tests fail loud on misses.
    """
    from hallucinote_mcp.wire import Response

    def _send(req):
        params = req.params or {}
        key = (
            req.tool, req.action,
            params.get("track_index"),
            params.get("return_index"),
            params.get("device_index"),
        )
        if key not in routes:
            raise AssertionError(
                f"_fake_pull_send_factory: unrouted ({req.tool}, "
                f"{req.action}, params={params!r}); routes={list(routes)!r}"
            )
        v = routes[key]
        if isinstance(v, str):
            return Response(ok=False, error=v)
        return Response(ok=True, result=v)

    return _send


def test_execute_plan_via_mcp_splits_action_and_params(conn, song, session):
    """The pull wire shape is ``Request(tool, action, params)``; PullCall
    bundles action into args. Verify the splitter does the right thing
    on a simple two-call plan."""
    from hallucinote.sync import pull_cli

    plan = pull.PullPlan()
    plan.add(pull.PullCall(
        tool="ableton_track", args={"action": "info", "track_index": 2},
        key="track_info:abc",
    ))
    plan.add(pull.PullCall(
        tool="ableton_return", args={"action": "list"},
        key="returns_list",
    ))

    seen = []

    def _send(req):
        seen.append((req.tool, req.action, dict(req.params)))
        from hallucinote_mcp.wire import Response
        return Response(ok=True, result={"echo": req.action})

    results = pull_cli._execute_plan_via_mcp(plan, send_fn=_send)

    assert seen == [
        ("ableton_track", "info", {"track_index": 2}),
        ("ableton_return", "list", {}),
    ]
    assert results == [
        {"key": "track_info:abc", "ok": True, "tool": "ableton_track",
         "result": {"echo": "info"}},
        {"key": "returns_list", "ok": True, "tool": "ableton_return",
         "result": {"echo": "list"}},
    ]


def test_execute_plan_via_mcp_propagates_tool_errors_as_warnings(conn, song, session):
    """Tool-side ok=False responses pass through as result records with
    error fields — never raise. apply_pull_results downstream surfaces
    them as warnings; the agent layer is the source of truth."""
    from hallucinote.sync import pull_cli

    plan = pull.PullPlan()
    plan.add(pull.PullCall(
        tool="ableton_track", args={"action": "info", "track_index": 1},
        key="track_info:abc",
    ))

    def _send(req):
        from hallucinote_mcp.wire import Response
        return Response(ok=False, error="track 1 doesn't exist")

    results = pull_cli._execute_plan_via_mcp(plan, send_fn=_send)
    assert len(results) == 1
    assert results[0]["ok"] is False
    assert results[0]["error"] == "track 1 doesn't exist"
    assert results[0]["result"] is None


def test_pull_cli_execute_bakes_device_parameter_change(tmp_path, monkeypatch):
    """End-to-end the C3 use case: a device has a stale DB parameter
    row; Live now reports a different value; `pull_cli execute
    device-parameters ...` probes Live, applies the diff, surfaces
    `mutations >= 1`."""
    from hallucinote.sync import pull_cli

    db_path = tmp_path / "c3.db"
    conn = init_db(db_path)
    song_id = M.create_song(conn, name="c3", title="C3", key="Dm")
    track_id = M.create_track(conn, song_id=song_id, track_index=1,
                              name="Drums")
    M.link_db_to_ableton(
        conn, session_id=(session_id := M.create_ableton_session(
            conn, song_id=song_id, name="draft")),
        db_kind="track", db_id=track_id, ableton_index=1,
    )
    chain_id = M.create_device_chain(conn, parent_track_id=track_id)
    device_id = M.create_device(
        conn, chain_id=chain_id, position=1,
        kind="Compressor2", display_name="Compressor",
    )
    M.set_device_parameter(
        conn, device_id=device_id, name="Threshold",
        value_display="-12.0 dB", value_normalized=0.30,
    )
    conn.commit()
    conn.close()

    # Live now reports Threshold at -6.0 dB (a different value).
    fake_send = _fake_pull_send_factory({
        ("ableton_device", "get_parameters", 1, None, 1): {
            "parameters": [
                {"name": "Threshold", "value_display": "-6.0 dB",
                 "value": 0.55, "min": 0.0, "max": 1.0, "is_enum": False},
            ],
        },
    })
    monkeypatch.setattr(pull_cli, "_resolve_send_fn", lambda: fake_send)

    rc = pull_cli.main([
        "execute", "device-parameters", session_id,
        "--db", str(db_path),
    ])
    assert rc == 0

    # Confirm the DB row actually changed — bare rc==0 would pass even
    # if the apply layer silently no-op'd. The C3 contract is that
    # mid-session tweaks survive the next push, which requires the new
    # value to be persisted.
    conn = init_db(db_path)
    row = conn.execute(
        "SELECT value_display, value_normalized FROM device_parameters "
        "WHERE device_id = ? AND name = ?",
        (str(device_id), "Threshold"),
    ).fetchone()
    conn.close()
    assert row is not None
    assert row["value_display"] == "-6.0 dB"
    assert row["value_normalized"] == pytest.approx(0.55)


def test_pull_cli_execute_works_for_mix_state_domain(tmp_path, monkeypatch, capsys):
    """Generality: execute works for non-device-parameters domains too
    (the C3 motivating use case is device-parameters but the surface
    is domain-agnostic by design)."""
    from hallucinote.sync import pull_cli

    db_path = tmp_path / "mix.db"
    conn = init_db(db_path)
    song_id = M.create_song(conn, name="mx", key="Dm")
    mid = M.create_track(conn, song_id=song_id, track_index=0,
                         name="Master", kind="master")
    M.set_track_mixer(conn, track_id=mid, volume=0.85, pan=0.0)
    session_id = M.create_ableton_session(conn, song_id=song_id, name="draft")
    conn.commit()
    conn.close()

    fake_send = _fake_pull_send_factory({
        ("ableton_session", "info", None, None, None): {
            "master": {"volume": 0.70, "panning": 0.0},
        },
        ("ableton_return", "list", None, None, None): [],
    })
    monkeypatch.setattr(pull_cli, "_resolve_send_fn", lambda: fake_send)

    rc = pull_cli.main([
        "execute", "mix-state", session_id, "--db", str(db_path),
    ])
    assert rc == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["domain"] == "mix-state"
    assert summary["applied"]["mutations"] >= 1


def test_pull_cli_execute_records_pull_request(tmp_path, monkeypatch):
    """Provenance: every `execute` run opens a `kind='pull'` request and
    closes it on success — same envelope `pull_cli apply` uses, so
    Arc 2 B4's driver wiring still captures the audit trail when the
    in-process path is taken."""
    from hallucinote.sync import pull_cli

    db_path = tmp_path / "prov.db"
    conn = init_db(db_path)
    song_id = M.create_song(conn, name="pv", key="Dm")
    session_id = M.create_ableton_session(conn, song_id=song_id, name="draft")
    conn.commit()
    conn.close()

    # mix-state on an empty song emits two calls (session info +
    # returns list); we just need a domain that doesn't error.
    fake_send = _fake_pull_send_factory({
        ("ableton_session", "info", None, None, None): {
            "master": {"volume": 0.85, "panning": 0.0},
        },
        ("ableton_return", "list", None, None, None): [],
    })
    monkeypatch.setattr(pull_cli, "_resolve_send_fn", lambda: fake_send)

    rc = pull_cli.main([
        "execute", "mix-state", session_id, "--db", str(db_path),
        "--reason", "test bake-tweaks",
    ])
    assert rc == 0

    # Reopen and inspect requests.
    conn = init_db(db_path)
    rows = conn.execute(
        "SELECT kind, outcome, intent FROM requests WHERE actor = 'sync'"
    ).fetchall()
    conn.close()
    assert len(rows) == 1
    assert rows[0]["kind"] == "pull"
    assert rows[0]["outcome"] == "ok"
    assert "pull_cli execute domain=mix-state" in rows[0]["intent"]


def test_pull_cli_execute_unknown_domain_errors(tmp_path, monkeypatch):
    """Unknown domain names the valid set so the user sees what's
    available without a docs lookup."""
    from hallucinote.sync import pull_cli

    db_path = tmp_path / "x.db"
    conn = init_db(db_path)
    song_id = M.create_song(conn, name="x", key="Dm")
    session_id = M.create_ableton_session(conn, song_id=song_id, name="draft")
    conn.commit()
    conn.close()

    with pytest.raises(SystemExit, match="unknown domain.*bogus"):
        pull_cli.main([
            "execute", "bogus", session_id, "--db", str(db_path),
        ])
