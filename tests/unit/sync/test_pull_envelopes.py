"""Tests for the W7-A pull planner: plan_pull_envelopes + _apply_envelope.

Pull-side mirror of `test_push_envelopes.py`. Same fixture shape (covering
arrangement_clip placement on a linked track + clip) so the planner finds a
route; same target_kind coverage; same skip-with-warn semantics.

Two halves:

  - **Planner tests** assert that the right read_envelope ToolCall args go
    out for each target_kind, that gap-blocked kinds skip with the right
    warn, and that the planner is skip-symmetric with push (no Live-side
    state? don't ask Live for it).

  - **Apply tests** assert curve preservation (DB-side `linear`/`fast`/
    `slow` survive when Live returns the same (time, value) as `hold`),
    `exists=False` → cascade-delete, offset translation (clip-local Live
    times → arrangement-time DB times for mixer/send/device_parameter),
    and the V1 Ableton-authoritative diff rules end-to-end.
"""
from __future__ import annotations

import pytest

from hallucinote.db import init_db, mutations as M, queries as Q
from hallucinote.sync import pull


# ---------------------------------------------------------------------------
# Fixtures — same shape as test_push_envelopes.py so planner symmetry is
# trivially checkable side-by-side.
# ---------------------------------------------------------------------------


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "puenv.db")
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
    return M.create_track(conn, song_id=song, track_index=1, name="Drums")


@pytest.fixture
def linked_track(conn, session, track):
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=track, ableton_index=5,
    )
    return track


@pytest.fixture
def clip(conn, track):
    return M.create_clip(conn, track_id=track, slot=1, length_beats=8.0, name="loop")


@pytest.fixture
def arr_clip(conn, song, track, clip):
    """Arrangement placement at bar 1 (beat 0) covering the 8-beat clip."""
    return M.add_arrangement_clip(
        conn, song_id=song, track_id=track, clip_id=clip,
        start_bar=1.0, end_bar=3.0,
    )


@pytest.fixture
def linked_clip(conn, session, clip):
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="clip", db_id=clip, ableton_index=1,
    )
    return clip


@pytest.fixture
def note(conn, clip):
    return M.insert_notes(
        conn, clip_id=clip,
        notes=[{"pitch": 60, "start_beats": 1.5, "duration_beats": 1.0, "velocity": 100}],
    )[0]


@pytest.fixture
def ret(conn, song):
    return M.create_return(conn, song_id=song, name="A-Reverb", position=1)


@pytest.fixture
def linked_return(conn, session, ret):
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="return", db_id=ret, ableton_index=1,
    )
    return ret


@pytest.fixture
def device(conn, track):
    cid = M.create_device_chain(conn, parent_track_id=track)
    return M.create_device(
        conn, chain_id=cid, position=1, kind="Compressor", display_name="Comp",
    )


@pytest.fixture
def linked_device(conn, session, device):
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="device", db_id=device, ableton_index=2,
    )
    return device


@pytest.fixture
def return_device(conn, ret):
    cid = M.create_device_chain(conn, parent_return_id=ret)
    return M.create_device(
        conn, chain_id=cid, position=1, kind="Reverb", display_name="Reverb",
    )


def _add_two_breakpoints(conn, envelope_id, *, curve_kind="linear"):
    """Adds two breakpoints in clip-local beats for clip-scoped envelopes,
    or in arrangement-time for mixer/send/device_parameter (the planner
    range checker uses the absolute beats either way)."""
    M.replace_breakpoints(
        conn, envelope_id=envelope_id, breakpoints=[
            {"time_beats": 0.0, "value": 0.5, "curve_kind": curve_kind},
            {"time_beats": 1.0, "value": 0.0, "curve_kind": curve_kind},
        ],
    )


def _result(key, payload, *, ok=True, tool="ableton_automation"):
    return {"key": key, "ok": ok, "tool": tool, "result": payload}


def _live_envelope_reply(
    breakpoints,
    *,
    exists=True,
    resolution=1.0 / 96.0,
    target_kind="mixer_volume",
    clip_length=8.0,
):
    """Build a read_envelope-shaped response. Breakpoints come back with
    `curve='hold'` because Live 12.4 only supports stepped envelopes."""
    return {
        "target_kind": target_kind,
        "exists": exists,
        "time_range_beats": [0.0, clip_length],
        "resolution_beats": resolution,
        "breakpoints": [
            {"time_beats": float(t), "value": float(v), "curve": "hold"}
            for (t, v) in breakpoints
        ],
    }


# ---------------------------------------------------------------------------
# Planner — empty / gap-blocked / unlinked
# ---------------------------------------------------------------------------


def test_empty_song_warns(conn, song, session):
    plan = pull.plan_pull_envelopes(conn, song_id=song, session_id=session)
    assert plan.calls == []
    assert any("no envelopes" in n for n in plan.notes)


def test_clip_cc_skipped_with_lom_gap_warn(
    conn, song, session, linked_track, linked_clip,
):
    """Symmetric with push: Live 12.4 LOM doesn't expose envelope read for
    MIDI CC targets; pull warn-skips like push does."""
    eid = M.create_envelope(
        conn, song_id=song, target_kind="clip_cc",
        target_clip_id=linked_clip, parameter_path="64",
    )
    _add_two_breakpoints(conn, eid)
    plan = pull.plan_pull_envelopes(conn, song_id=song, session_id=session)
    assert plan.calls == []
    assert any("clip_cc" in n for n in plan.notes), plan.notes


def test_clip_pitch_bend_skipped_with_lom_gap_warn(
    conn, song, session, linked_track, linked_clip,
):
    eid = M.create_envelope(
        conn, song_id=song, target_kind="clip_pitch_bend",
        target_clip_id=linked_clip,
    )
    _add_two_breakpoints(conn, eid)
    plan = pull.plan_pull_envelopes(conn, song_id=song, session_id=session)
    assert plan.calls == []
    assert any("clip_pitch_bend" in n for n in plan.notes), plan.notes


# ---------------------------------------------------------------------------
# Planner — note_expression
# ---------------------------------------------------------------------------


def test_note_expression_is_refused_at_plan_time(
    conn, song, session, linked_track, linked_clip, note,
):
    """There is nothing in Live to read back, so no read is planned.

    This test used to assert the addressing of a `read_envelope` call that
    mirrored push's write. Both rode `Clip.envelope_for_note`, a method Live
    has never shipped, and the LOM exposes no per-note expression surface
    under any name — so no envelope of this kind can exist in Live at all.
    """
    eid = M.create_envelope(
        conn, song_id=song, target_kind="note_expression",
        target_note_id=note, parameter_path="pitch",
    )
    _add_two_breakpoints(conn, eid)
    plan = pull.plan_pull_envelopes(conn, song_id=song, session_id=session)
    assert plan.calls == []
    assert any("no per-note expression surface" in n for n in plan.notes), plan.notes


def test_note_expression_is_refused_even_when_nothing_is_linked(
    conn, song, session, linked_track, clip, note,
):
    """The refusal does not depend on link state — it is about the API.

    Worth pinning separately: the old skip here was 'clip not linked', which
    is a fixable condition. This one never becomes fixable, and telling a user
    to link a clip would send them to work that changes nothing.
    """
    eid = M.create_envelope(
        conn, song_id=song, target_kind="note_expression",
        target_note_id=note, parameter_path="pitch",
    )
    _add_two_breakpoints(conn, eid)
    plan = pull.plan_pull_envelopes(conn, song_id=song, session_id=session)
    assert plan.calls == []
    assert any("no per-note expression surface" in n for n in plan.notes), plan.notes
    assert not any("not linked" in n for n in plan.notes)


# ---------------------------------------------------------------------------
# Planner — mixer / send / device_parameter (session-clip routed)
# ---------------------------------------------------------------------------


def test_mixer_volume_emits_session_clip_addressing(
    conn, song, session, linked_track, linked_clip, arr_clip,
):
    eid = M.create_envelope(
        conn, song_id=song, target_kind="mixer_volume", target_track_id=linked_track,
    )
    _add_two_breakpoints(conn, eid)
    plan = pull.plan_pull_envelopes(conn, song_id=song, session_id=session)
    assert len(plan.calls) == 1, plan.notes
    call = plan.calls[0]
    assert call.args["target_kind"] == "mixer_volume"
    assert call.args["track_index"] == 5
    assert call.args["clip_index"] == 1
    assert call.args["location"] == "session"
    # mixer envelopes don't take note_pitch / device_index args.
    assert "device_index" not in call.args
    assert "parameter_name" not in call.args


def test_mixer_pan_emits_correctly(
    conn, song, session, linked_track, linked_clip, arr_clip,
):
    eid = M.create_envelope(
        conn, song_id=song, target_kind="mixer_pan", target_track_id=linked_track,
    )
    _add_two_breakpoints(conn, eid)
    plan = pull.plan_pull_envelopes(conn, song_id=song, session_id=session)
    assert len(plan.calls) == 1
    assert plan.calls[0].args["target_kind"] == "mixer_pan"


def test_send_level_emits_return_index(
    conn, song, session, linked_track, linked_clip, arr_clip,
    linked_return,
):
    eid = M.create_envelope(
        conn, song_id=song, target_kind="send_level",
        target_track_id=linked_track,
        target_send_return_id=linked_return,
    )
    _add_two_breakpoints(conn, eid)
    plan = pull.plan_pull_envelopes(conn, song_id=song, session_id=session)
    assert len(plan.calls) == 1
    call = plan.calls[0]
    assert call.args["target_kind"] == "send_level"
    assert call.args["return_index"] == 1
    assert call.args["track_index"] == 5
    assert call.args["clip_index"] == 1


def test_device_parameter_emits_with_device_index_and_param_name(
    conn, song, session, linked_track, linked_clip, arr_clip, linked_device,
):
    eid = M.create_envelope(
        conn, song_id=song, target_kind="device_parameter",
        target_device_id=linked_device, parameter_path="Threshold",
    )
    _add_two_breakpoints(conn, eid)
    plan = pull.plan_pull_envelopes(conn, song_id=song, session_id=session)
    assert len(plan.calls) == 1, plan.notes
    call = plan.calls[0]
    assert call.args["target_kind"] == "device_parameter"
    assert call.args["device_index"] == 2
    assert call.args["parameter_name"] == "Threshold"
    assert call.args["clip_index"] == 1


def test_mixer_volume_no_covering_placement_skips_symmetric_with_push(
    conn, song, session, linked_track, linked_clip,
):
    """W7-A skip-symmetry: when no arrangement_clip covers the envelope's
    beat range, push warn-skips. Pull must do the same — otherwise a pull
    on a never-pushed envelope would return exists=False and the apply
    layer would delete the DB row that represents the user's intent.
    """
    eid = M.create_envelope(
        conn, song_id=song, target_kind="mixer_volume", target_track_id=linked_track,
    )
    # No arr_clip fixture used → no covering placement.
    _add_two_breakpoints(conn, eid)
    plan = pull.plan_pull_envelopes(conn, song_id=song, session_id=session)
    assert plan.calls == []
    assert any(
        "covers beat range" in n or "no arrangement" in n for n in plan.notes
    ), plan.notes


def test_device_parameter_return_side_skipped_with_warn(
    conn, song, session, linked_track, linked_clip, arr_clip, linked_return,
    return_device,
):
    """Symmetric with push: return-side device_parameter envelopes are
    blocked (no return-clip schema model)."""
    eid = M.create_envelope(
        conn, song_id=song, target_kind="device_parameter",
        target_device_id=return_device, parameter_path="Decay",
    )
    _add_two_breakpoints(conn, eid)
    plan = pull.plan_pull_envelopes(conn, song_id=song, session_id=session)
    assert plan.calls == []
    assert any("return-side" in n for n in plan.notes), plan.notes


def test_device_parameter_nested_rack_skipped_with_warn(
    conn, song, session, linked_track, linked_clip, arr_clip,
):
    """Symmetric with push: device_parameter envelopes on devices inside
    rack chains (parent_rack_device_id IS NOT NULL) are skipped. W6-I/J
    shipped the MCP-side probe but pull routing is still flat — closing
    that gap is W7-B."""
    # Build a rack device on the track, then a nested chain on the rack,
    # then a device inside that nested chain.
    rack_chain = M.create_device_chain(conn, parent_track_id=linked_track)
    rack_device = M.create_device(
        conn, chain_id=rack_chain, position=1,
        kind="Instrument Rack", display_name="Rack",
    )
    nested_chain = M.create_device_chain(
        conn, parent_rack_device_id=rack_device, position=0,
    )
    nested_device = M.create_device(
        conn, chain_id=nested_chain, position=1,
        kind="Operator", display_name="Synth",
    )
    eid = M.create_envelope(
        conn, song_id=song, target_kind="device_parameter",
        target_device_id=nested_device, parameter_path="Cutoff",
    )
    _add_two_breakpoints(conn, eid)
    plan = pull.plan_pull_envelopes(conn, song_id=song, session_id=session)
    assert plan.calls == []
    assert any("nested-rack" in n for n in plan.notes), plan.notes


def test_unlinked_track_skipped_with_warn(
    conn, song, session, track, clip,
):
    """No links → no addressing path → skip-with-warn."""
    eid = M.create_envelope(
        conn, song_id=song, target_kind="mixer_volume", target_track_id=track,
    )
    _add_two_breakpoints(conn, eid)
    plan = pull.plan_pull_envelopes(conn, song_id=song, session_id=session)
    assert plan.calls == []
    assert any("not linked" in n for n in plan.notes), plan.notes


# ---------------------------------------------------------------------------
# Apply — exists=False handling
# ---------------------------------------------------------------------------


def test_apply_exists_false_deletes_envelope_with_breakpoints(
    conn, song, session, linked_track, linked_clip, arr_clip,
):
    """Live reports no envelope at this address; DB has authored
    breakpoints → user removed it in Live → cascade-delete."""
    eid = M.create_envelope(
        conn, song_id=song, target_kind="mixer_volume", target_track_id=linked_track,
    )
    _add_two_breakpoints(conn, eid)
    payload = _live_envelope_reply([], exists=False)
    result = pull.apply_pull_results(
        conn, [_result(f"envelope:{eid}", payload)],
        song_id=song, session_id=session,
    )
    assert result.mutations == 1
    assert Q.get_envelope(conn, eid) is None, "envelope should be deleted"
    assert any("removed" in d for d in result.details), result.details


def test_apply_exists_false_no_db_breakpoints_is_noop(
    conn, song, session, linked_track,
):
    """DB row exists but already empty; Live agrees. No mutation."""
    eid = M.create_envelope(
        conn, song_id=song, target_kind="mixer_volume", target_track_id=linked_track,
    )
    payload = _live_envelope_reply([], exists=False)
    result = pull.apply_pull_results(
        conn, [_result(f"envelope:{eid}", payload)],
        song_id=song, session_id=session,
    )
    assert result.mutations == 0
    assert result.no_ops == 1
    assert Q.get_envelope(conn, eid) is not None


def test_apply_single_constant_value_envelope_survives_round_trip(
    conn, song, session, linked_track, linked_clip, arr_clip,
):
    """W7-0 cumulative-Critic regression: a single-breakpoint envelope
    held at a constant value across the clip MUST NOT be cascade-deleted
    on round-trip. The handler's `exists` field uses a `len > 1` heuristic
    that conflates "no envelope" with "one-breakpoint constant envelope"
    — apply must gate the delete decision on `len(live_bps) == 0`, not
    on the heuristic. Without this fix, a real-Live read of a constant-
    value envelope returns 1 breakpoint with exists=False and the DB row
    gets deleted (silent round-trip data loss)."""
    eid = M.create_envelope(
        conn, song_id=song, target_kind="mixer_volume", target_track_id=linked_track,
    )
    # DB has the same single constant breakpoint as Live.
    M.replace_breakpoints(
        conn, envelope_id=eid, breakpoints=[
            {"time_beats": 0.0, "value": 0.7, "curve_kind": "hold"},
        ],
    )
    # Live read returns exists=False (heuristic: len(bps) > 1 = False),
    # but breakpoints contains the one constant value. This is the case
    # the apply layer must NOT treat as "envelope absent."
    payload = _live_envelope_reply([(0.0, 0.7)], exists=False)
    result = pull.apply_pull_results(
        conn, [_result(f"envelope:{eid}", payload)],
        song_id=song, session_id=session,
    )
    assert Q.get_envelope(conn, eid) is not None, (
        "single-constant-value envelope must survive — apply trusted "
        "the heuristic and cascade-deleted it"
    )
    # The DB breakpoint is identical to Live's, so no mutation needed.
    assert result.mutations == 0
    assert result.no_ops == 1


# ---------------------------------------------------------------------------
# Apply — curve preservation
# ---------------------------------------------------------------------------


def test_apply_identical_breakpoints_preserves_curve_kind(
    conn, song, session, linked_track, linked_clip, arr_clip,
):
    """The round-trip case: push wrote a `linear` envelope, Live discarded
    the curve hint (W5-E warn), reads back with `curve='hold'`. Apply must
    no-op so the DB's authored `linear` curve survives."""
    eid = M.create_envelope(
        conn, song_id=song, target_kind="mixer_volume", target_track_id=linked_track,
    )
    _add_two_breakpoints(conn, eid, curve_kind="linear")
    # Same (time, value) — Live returns curve='hold'.
    payload = _live_envelope_reply([(0.0, 0.5), (1.0, 0.0)])
    result = pull.apply_pull_results(
        conn, [_result(f"envelope:{eid}", payload)],
        song_id=song, session_id=session,
    )
    assert result.mutations == 0
    assert result.no_ops == 1
    bps = Q.get_breakpoints(conn, eid)
    assert [b["curve_kind"] for b in bps] == ["linear", "linear"], (
        "DB curve hint must survive a round-trip"
    )


def test_apply_value_change_overwrites_with_hold_curve(
    conn, song, session, linked_track, linked_clip, arr_clip,
):
    """Same time, different value — Live overwrote. New value lands with
    curve='hold' (Live can't tell us what the original curve intent was)."""
    eid = M.create_envelope(
        conn, song_id=song, target_kind="mixer_volume", target_track_id=linked_track,
    )
    _add_two_breakpoints(conn, eid, curve_kind="linear")
    # Same times, different values.
    payload = _live_envelope_reply([(0.0, 0.9), (1.0, 0.1)])
    result = pull.apply_pull_results(
        conn, [_result(f"envelope:{eid}", payload)],
        song_id=song, session_id=session,
    )
    assert result.mutations == 1
    bps = Q.get_breakpoints(conn, eid)
    assert [b["value"] for b in bps] == pytest.approx([0.9, 0.1])
    assert [b["curve_kind"] for b in bps] == ["hold", "hold"]


def test_apply_new_breakpoint_in_live_lands_with_hold_curve(
    conn, song, session, linked_track, linked_clip, arr_clip,
):
    """Live has a breakpoint the DB doesn't — user added it. Curve='hold'."""
    eid = M.create_envelope(
        conn, song_id=song, target_kind="mixer_volume", target_track_id=linked_track,
    )
    _add_two_breakpoints(conn, eid, curve_kind="fast")
    # Original two + a new mid-range breakpoint.
    payload = _live_envelope_reply([(0.0, 0.5), (0.5, 0.25), (1.0, 0.0)])
    result = pull.apply_pull_results(
        conn, [_result(f"envelope:{eid}", payload)],
        song_id=song, session_id=session,
    )
    assert result.mutations == 1
    bps = Q.get_breakpoints(conn, eid)
    assert len(bps) == 3
    # Original two preserved their curves; the new mid-range one is hold.
    by_time = {b["time_beats"]: b for b in bps}
    assert by_time[0.0]["curve_kind"] == "fast"
    assert by_time[1.0]["curve_kind"] == "fast"
    assert by_time[0.5]["curve_kind"] == "hold"


def test_apply_missing_breakpoint_in_live_is_dropped(
    conn, song, session, linked_track, linked_clip, arr_clip,
):
    """DB had a breakpoint Live doesn't report → user removed it."""
    eid = M.create_envelope(
        conn, song_id=song, target_kind="mixer_volume", target_track_id=linked_track,
    )
    M.replace_breakpoints(
        conn, envelope_id=eid, breakpoints=[
            {"time_beats": 0.0, "value": 0.5, "curve_kind": "linear"},
            {"time_beats": 0.5, "value": 0.25, "curve_kind": "linear"},
            {"time_beats": 1.0, "value": 0.0, "curve_kind": "linear"},
        ],
    )
    payload = _live_envelope_reply([(0.0, 0.5), (1.0, 0.0)])
    result = pull.apply_pull_results(
        conn, [_result(f"envelope:{eid}", payload)],
        song_id=song, session_id=session,
    )
    assert result.mutations == 1
    bps = Q.get_breakpoints(conn, eid)
    assert len(bps) == 2


# ---------------------------------------------------------------------------
# Apply — offset translation
# ---------------------------------------------------------------------------


def test_apply_mixer_offset_translation_clip_local_to_arrangement(
    conn, song, session, linked_track, linked_clip,
):
    """When the covering session-clip placement is at beat 4.0 (bar 2),
    Live's clip-local times must be translated back to arrangement-time
    (i.e. +4.0) before diffing against the DB."""
    # Place arrangement clip at bar 2 = beat 4.
    M.add_arrangement_clip(
        conn, song_id=song, track_id=linked_track, clip_id=linked_clip,
        start_bar=2.0, end_bar=4.0,
    )
    eid = M.create_envelope(
        conn, song_id=song, target_kind="mixer_volume", target_track_id=linked_track,
    )
    # DB stores arrangement-time: 4.0 and 5.0 (one beat into the placement).
    M.replace_breakpoints(
        conn, envelope_id=eid, breakpoints=[
            {"time_beats": 4.0, "value": 0.5, "curve_kind": "linear"},
            {"time_beats": 5.0, "value": 0.0, "curve_kind": "linear"},
        ],
    )
    # Live returns clip-local times: 0.0 and 1.0.
    payload = _live_envelope_reply([(0.0, 0.5), (1.0, 0.0)])
    result = pull.apply_pull_results(
        conn, [_result(f"envelope:{eid}", payload)],
        song_id=song, session_id=session,
    )
    # Translation correct → identical breakpoints (post-translation) → no-op.
    assert result.mutations == 0, result.details
    assert result.no_ops == 1


def test_apply_note_expression_no_offset_translation(
    conn, song, session, linked_track, linked_clip, note,
):
    """note_expression breakpoints are clip-local on both sides."""
    eid = M.create_envelope(
        conn, song_id=song, target_kind="note_expression",
        target_note_id=note, parameter_path="pitch",
    )
    M.replace_breakpoints(
        conn, envelope_id=eid, breakpoints=[
            {"time_beats": 0.0, "value": 0.0, "curve_kind": "linear"},
            {"time_beats": 0.5, "value": 0.5, "curve_kind": "linear"},
        ],
    )
    payload = _live_envelope_reply(
        [(0.0, 0.0), (0.5, 0.5)], target_kind="note_expression",
    )
    result = pull.apply_pull_results(
        conn, [_result(f"envelope:{eid}", payload)],
        song_id=song, session_id=session,
    )
    assert result.mutations == 0
    assert result.no_ops == 1


# ---------------------------------------------------------------------------
# Round-trip property: DB -> push-like read -> apply converges to no-op
# ---------------------------------------------------------------------------


def test_apply_time_jitter_within_sampling_resolution_is_noop(
    conn, song, session, linked_track, linked_clip, arr_clip,
):
    """Regression for the Critic-caught epsilon mismatch (W7-A round 1):
    Live's sampling-based read can localize a step transition anywhere
    within `resolution_beats` of its true position, so time deltas up to
    `resolution_beats + _ENVELOPE_TIME_EPS_SLACK` (~0.0114 at default
    1/96 beat) MUST be tolerated. Comparing time deltas against
    `value_eps` (1e-3, an order of magnitude tighter) would flag every
    pull as a change even when no real edit happened, producing
    spurious mutations on every round-trip.
    """
    eid = M.create_envelope(
        conn, song_id=song, target_kind="mixer_volume", target_track_id=linked_track,
    )
    _add_two_breakpoints(conn, eid, curve_kind="linear")
    # Times jittered by ~0.005 (5x value_eps but ~half of time_eps at
    # default sampling resolution). Same values.
    payload = _live_envelope_reply([(0.005, 0.5), (1.005, 0.0)])
    result = pull.apply_pull_results(
        conn, [_result(f"envelope:{eid}", payload)],
        song_id=song, session_id=session,
    )
    assert result.mutations == 0, (
        f"Live's sampling jitter must not churn DB breakpoints: {result.details}"
    )
    assert result.no_ops == 1
    # And curves survive.
    bps = Q.get_breakpoints(conn, eid)
    assert [b["curve_kind"] for b in bps] == ["linear", "linear"]


def test_round_trip_simulated_read_is_no_op(
    conn, song, session, linked_track, linked_clip, arr_clip,
):
    """Property: a successful push followed by a simulated Live read of the
    same shape converges to a no-op apply. This is the round-trip invariant
    Wave 7 closes.

    The 'simulated Live read' here returns the same (time, value) pairs as
    DB breakpoints but with curve='hold' (Live's quantum). Apply must
    preserve DB curves and no-op."""
    eid = M.create_envelope(
        conn, song_id=song, target_kind="mixer_volume", target_track_id=linked_track,
    )
    # Stress-test: many breakpoints, multiple curve_kinds.
    bps_in = [
        (0.0, 0.50, "linear"),
        (0.25, 0.75, "fast"),
        (0.50, 0.50, "slow"),
        (1.0, 0.25, "hold"),
        (2.0, 0.10, "linear"),
    ]
    M.replace_breakpoints(
        conn, envelope_id=eid, breakpoints=[
            {"time_beats": t, "value": v, "curve_kind": c}
            for (t, v, c) in bps_in
        ],
    )
    # Simulate Live's read: same (time, value), curve='hold' everywhere.
    payload = _live_envelope_reply([(t, v) for (t, v, _c) in bps_in])
    result = pull.apply_pull_results(
        conn, [_result(f"envelope:{eid}", payload)],
        song_id=song, session_id=session,
    )
    assert result.mutations == 0, result.details
    assert result.no_ops == 1
    # And the DB curves survived intact.
    bps_after = Q.get_breakpoints(conn, eid)
    by_time = {round(b["time_beats"], 6): b["curve_kind"] for b in bps_after}
    for (t, _v, c) in bps_in:
        assert by_time[round(t, 6)] == c, (
            f"curve_kind for breakpoint at {t} should still be {c}"
        )


# ---------------------------------------------------------------------------
# Edge: stale routing between plan and apply
# ---------------------------------------------------------------------------


def test_apply_missing_placement_warns_and_skips(
    conn, song, session, linked_track, linked_clip, arr_clip,
):
    """If the covering placement was removed between plan and apply (rare —
    requires a concurrent edit), the apply layer should warn rather than
    silently mis-translate offsets."""
    eid = M.create_envelope(
        conn, song_id=song, target_kind="mixer_volume", target_track_id=linked_track,
    )
    _add_two_breakpoints(conn, eid)
    # Remove the arrangement clip after the (notional) plan stage.
    conn.execute("DELETE FROM arrangement_clips WHERE id = ?", (arr_clip,))
    conn.commit()
    payload = _live_envelope_reply([(0.0, 0.5), (1.0, 0.0)])
    result = pull.apply_pull_results(
        conn, [_result(f"envelope:{eid}", payload)],
        song_id=song, session_id=session,
    )
    assert result.mutations == 0
    assert any("no longer resolves" in w for w in result.warnings), result.warnings
