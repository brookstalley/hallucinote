"""Tests for the chunk-4b push planner: plan_push_envelopes + envelope-link apply.

W4-B reshape: mixer/pan/send/device_parameter envelopes now route through
a SESSION clip on the target track (Live 12.4 LOM only accepts these
targets on session clips per push-findings #11). The planner finds an
arrangement_clip placement on the target track that covers the envelope's
beat range, emits on the source session clip with clip-local breakpoints
(arrangement-time minus placement offset), and ``duplicate_to_arrangement``
later snapshot-copies the envelope to the arrangement (W4-A finding).

Fixtures here build a song-bar timeline so envelope time_beats interpret
naturally (arrangement-relative throughout the test suite). ``arr_clip``
fixture provides a covering arrangement_clip placement.
"""
from __future__ import annotations

import pytest

from hallucinote.db import init_db, mutations as M
from hallucinote.sync import push
from hallucinote.sync.push._core import build_node_addr


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "penv.db")
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
    """An arrangement_clip placement at bar 1 (= beat 0) covering the
    8-beat ``clip``. Beat range [0, 8] covers the [0, 1] breakpoint range
    used by ``_add_one_breakpoint`` so the W4-B session-clip resolver
    finds it.
    """
    return M.add_arrangement_clip(
        conn, song_id=song, track_id=track, clip_id=clip,
        start_bar=1.0, end_bar=3.0,  # 2 bars × 4 beats = 8 beats
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


def _calls_by_tool(plan) -> dict[str, list]:
    out: dict[str, list] = {}
    for c in plan.calls:
        out.setdefault(c.tool, []).append(c)
    return out


def _calls_by_target_kind(plan) -> dict[str, list]:
    """Wave M-4: all envelope writes flow through
    ableton_automation(action='write_envelope', target_kind=...). Group by
    target_kind for shape assertions.
    """
    out: dict[str, list] = {}
    for c in plan.calls:
        kind = c.args.get("target_kind")
        if kind is None:
            continue
        out.setdefault(kind, []).append(c)
    return out


# ---------- empty / no-targets ----------


def test_empty_song_warns(conn, song, session):
    plan = push.plan_push_envelopes(conn, song_id=song, session_id=session)
    assert plan.calls == []
    assert any("no envelopes" in n for n in plan.notes)


def test_envelope_without_breakpoints_skipped_with_warn(
    conn, song, session, linked_track, linked_clip,
):
    M.create_envelope(
        conn, song_id=song, target_kind="clip_cc",
        target_clip_id=linked_clip, parameter_path="64",
    )
    plan = push.plan_push_envelopes(conn, song_id=song, session_id=session)
    assert plan.calls == []
    assert any("no breakpoints" in n for n in plan.notes)


def _add_one_breakpoint(conn, envelope_id):
    M.add_breakpoint(conn, envelope_id=envelope_id, time_beats=0.0, value=0.5)
    M.add_breakpoint(conn, envelope_id=envelope_id, time_beats=1.0, value=0.0)


# ---------- clip_cc + clip_pitch_bend (W4-B: LOM-gap skip) ----------


def test_clip_cc_skipped_with_lom_gap_warn(
    conn, song, session, linked_track, linked_clip,
):
    """W4-B / push-findings #12: Live 12.4's LOM doesn't expose
    ``Clip.create_automation_envelope`` for MIDI CC targets. Planner
    must skip and warn pointing at the encode-as-notes workaround."""
    eid = M.create_envelope(
        conn, song_id=song, target_kind="clip_cc",
        target_clip_id=linked_clip, parameter_path="64",
    )
    _add_one_breakpoint(conn, eid)
    plan = push.plan_push_envelopes(conn, song_id=song, session_id=session)
    assert plan.calls == []
    assert any(
        "clip_cc" in n and "replace_notes" in n
        for n in plan.notes
    ), plan.notes


def test_clip_pitch_bend_skipped_with_lom_gap_warn(
    conn, song, session, linked_track, linked_clip,
):
    """W4-B / push-findings #12: same LOM gap as clip_cc; no encode
    workaround exists for pitch bend, so warn says author manually."""
    eid = M.create_envelope(
        conn, song_id=song, target_kind="clip_pitch_bend",
        target_clip_id=linked_clip,
    )
    _add_one_breakpoint(conn, eid)
    plan = push.plan_push_envelopes(conn, song_id=song, session_id=session)
    assert plan.calls == []
    assert any(
        "clip_pitch_bend" in n and "author manually" in n
        for n in plan.notes
    ), plan.notes


# ---------- note_expression (MPE microtonal) ----------


def test_note_expression_microtonal_pitch_envelope(
    conn, song, session, linked_track, linked_clip, note,
):
    """Synthetic microtonal MPE: a per-note pitch envelope (semitone offsets)."""
    eid = M.create_envelope(
        conn, song_id=song, target_kind="note_expression",
        target_note_id=note, parameter_path="pitch",
    )
    M.replace_breakpoints(
        conn, envelope_id=eid,
        breakpoints=[
            {"time_beats": 0.0, "value": 0.0,  "curve_kind": "linear"},
            {"time_beats": 0.5, "value": 0.25, "curve_kind": "linear"},
            {"time_beats": 1.0, "value": 0.0,  "curve_kind": "linear"},
        ],
    )
    plan = push.plan_push_envelopes(conn, song_id=song, session_id=session)
    calls = _calls_by_target_kind(plan)
    assert list(calls) == ["note_expression"]
    call = calls["note_expression"][0]
    assert call.tool == "ableton_automation"
    assert call.args["track_index"] == 5
    assert call.args["location"] == "session"
    assert call.args["clip_index"] == 1
    assert call.args["note_pitch"] == 60
    assert call.args["note_start_beats"] == 1.5
    # W7-0 anchor (P1): planner threads the note's duration so the MCP
    # handler can extend the last step to note end (note spans 1.5..2.5).
    assert call.args["note_duration"] == 1.0
    assert call.args["axis"] == "pitch"
    assert len(call.args["breakpoints"]) == 3


# ---------- device_parameter (track + return) ----------


def test_device_parameter_track_emits_via_session_clip(
    conn, song, session, linked_track, linked_clip, linked_device, arr_clip,
):
    """W4-B: device_parameter envelopes route through a session clip on
    the parent track. ``arr_clip`` places ``linked_clip`` at bar 1 (beat
    0); the envelope's [0,1] beat range fits within the clip's 8-beat
    span. Breakpoint times stay at [0,1] because the placement starts at
    beat 0 (zero offset)."""
    eid = M.create_envelope(
        conn, song_id=song, target_kind="device_parameter",
        target_device_id=linked_device, parameter_path="Threshold",
    )
    _add_one_breakpoint(conn, eid)
    plan = push.plan_push_envelopes(conn, song_id=song, session_id=session)
    calls = _calls_by_target_kind(plan)
    assert list(calls) == ["device_parameter"]
    call = calls["device_parameter"][0]
    assert call.tool == "ableton_automation"
    assert call.args == {
        "action": "write_envelope",
        "target_kind": "device_parameter",
        "node": build_node_addr({"track_index": 5}, device_index=2),
        "location": "session",
        "clip_index": 1,
        "parameter_name": "Threshold",
        "breakpoints": [
            {"time_beats": 0.0, "value": 0.5, "curve": "linear"},
            {"time_beats": 1.0, "value": 0.0, "curve": "linear"},
        ],
    }


def test_device_parameter_return_routes_to_perform(
    conn, song, session, linked_return, return_device,
):
    """ENV-7G4K: return-side device_parameter envelopes are perform-routed
    (was: W4-B skip-warn for the missing return-side session-clip model —
    the perform mechanism made that model unnecessary)."""
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="device",
        db_id=return_device, ableton_index=3,
    )
    eid = M.create_envelope(
        conn, song_id=song, target_kind="device_parameter",
        target_device_id=return_device, parameter_path="Decay",
    )
    _add_one_breakpoint(conn, eid)
    plan = push.plan_push_envelopes(conn, song_id=song, session_id=session)
    assert plan.calls == []
    assert any("performed-automation" in n for n in plan.notes), plan.notes


def test_device_parameter_skipped_when_device_unlinked(
    conn, song, session, linked_track, device, arr_clip,
):
    eid = M.create_envelope(
        conn, song_id=song, target_kind="device_parameter",
        target_device_id=device, parameter_path="Threshold",
    )
    _add_one_breakpoint(conn, eid)
    plan = push.plan_push_envelopes(conn, song_id=song, session_id=session)
    assert plan.calls == []
    assert any("device not linked" in n for n in plan.notes)


def test_device_parameter_nested_routes_to_perform(
    conn, song, session, linked_track,
):
    """DEEP-RACK-ADDR: a nested-rack device_parameter envelope routes to the
    PERFORM phase (the perform handler rides it via device_path). The
    session-clip envelope phase emits nothing and notes the perform route — no
    longer the old 'nested-rack — push not yet supported (MCP gap)' skip."""
    top_chain = M.create_device_chain(conn, parent_track_id=linked_track)
    rack = M.create_device(conn, chain_id=top_chain, position=1,
                           kind="Drum Rack", display_name="Kit")
    inner_chain = M.create_device_chain(conn, parent_rack_device_id=rack, position=1)
    inner = M.create_device(conn, chain_id=inner_chain, position=1,
                            kind="Simpler", display_name="Kick")
    eid = M.create_envelope(
        conn, song_id=song, target_kind="device_parameter",
        target_device_id=inner, parameter_path="Volume",
    )
    _add_one_breakpoint(conn, eid)
    # classify routes it to perform...
    row = conn.execute(
        "SELECT * FROM envelopes WHERE id = ?", (eid,),
    ).fetchone()
    assert push.classify_envelope_route(conn, row, song_id=song) == "perform"
    # ...so the session-clip phase emits nothing and notes the perform route.
    plan = push.plan_push_envelopes(conn, song_id=song, session_id=session)
    assert plan.calls == []
    assert any("performed-automation" in n for n in plan.notes), plan.notes
    assert not any("not yet supported" in n for n in plan.notes), plan.notes


def test_device_parameter_routes_to_perform_when_no_arrangement_clip_covers(
    conn, song, session, linked_track, linked_clip, linked_device,
):
    """ENV-9P4T (was W4-B skip): with no covering session clip on the parent
    track, a midi-track device-parameter envelope is a continuous ride —
    infer-from-span routes it to perform (uniform with the mixer kinds)."""
    eid = M.create_envelope(
        conn, song_id=song, target_kind="device_parameter",
        target_device_id=linked_device, parameter_path="Threshold",
    )
    _add_one_breakpoint(conn, eid)
    plan = push.plan_push_envelopes(conn, song_id=song, session_id=session)
    assert plan.calls == []
    assert any(
        "device_parameter" in n and "performed-automation" in n
        for n in plan.notes
    ), plan.notes
    assert not any("no arrangement clip" in n for n in plan.notes), plan.notes


# ---------- mixer_volume + mixer_pan (W4-B session-clip routing) ----------


def test_mixer_volume_emits_via_session_clip(
    conn, song, session, linked_track, linked_clip, arr_clip,
):
    """W4-B: mixer_volume routes through a session clip on the target
    track. ``arr_clip`` covers the envelope's [0,1] range at offset 0."""
    eid = M.create_envelope(
        conn, song_id=song, target_kind="mixer_volume",
        target_track_id=linked_track,
    )
    _add_one_breakpoint(conn, eid)
    plan = push.plan_push_envelopes(conn, song_id=song, session_id=session)
    calls = _calls_by_target_kind(plan)
    assert list(calls) == ["mixer_volume"]
    call = calls["mixer_volume"][0]
    assert call.args == {
        "action": "write_envelope",
        "target_kind": "mixer_volume",
        "track_index": 5,
        "location": "session",
        "clip_index": 1,
        "breakpoints": [
            {"time_beats": 0.0, "value": 0.5, "curve": "linear"},
            {"time_beats": 1.0, "value": 0.0, "curve": "linear"},
        ],
    }


# ---------- ARR-PROJ §5/§9: envelope_hosting_clip_ids (duplicate-route detection) ----------


def test_envelope_hosting_clip_ids_includes_session_clip_host(
    conn, song, session, track, clip, arr_clip,
):
    """A clip that HOSTS a session_clip-routed envelope (here a mixer_volume
    covered by ``arr_clip``) is reported as an envelope host, so the arrangement
    planner routes its placement to duplicate (create+fill would drop the
    snapshot-copied clip envelope — §9 risk)."""
    eid = M.create_envelope(
        conn, song_id=song, target_kind="mixer_volume", target_track_id=track,
    )
    _add_one_breakpoint(conn, eid)  # breakpoints in [0,1], covered by arr_clip [0,8]
    assert push.envelope_hosting_clip_ids(conn, song) == {clip}


def test_envelope_hosting_clip_ids_excludes_perform_routed(
    conn, song, session, track, clip,
):
    """An envelope with NO covering session clip routes to perform (a continuous
    arrangement ride), so its track's clips are NOT envelope hosts — create+fill
    is safe for them. (No ``arr_clip`` placement here, so nothing covers it.)"""
    eid = M.create_envelope(
        conn, song_id=song, target_kind="mixer_volume", target_track_id=track,
    )
    _add_one_breakpoint(conn, eid)
    assert push.envelope_hosting_clip_ids(conn, song) == set()


def test_mixer_pan_emits_via_session_clip(
    conn, song, session, linked_track, linked_clip, arr_clip,
):
    eid = M.create_envelope(
        conn, song_id=song, target_kind="mixer_pan",
        target_track_id=linked_track,
    )
    _add_one_breakpoint(conn, eid)
    plan = push.plan_push_envelopes(conn, song_id=song, session_id=session)
    calls = _calls_by_target_kind(plan)
    assert list(calls) == ["mixer_pan"]
    call = calls["mixer_pan"][0]
    assert call.args["location"] == "session"
    assert call.args["clip_index"] == 1


def test_mixer_volume_routes_to_perform_when_no_arrangement_clip(
    conn, song, session, linked_track,
):
    """ENV-9P4T (was W4-B skip): a plain midi track's mixer_volume envelope
    that NO session clip covers is a continuous, clip-independent
    arrangement ride — infer-from-span routes it to the performed-automation
    phase. The session-clip planner emits nothing and names the perform
    route (not the old "no arrangement clip" skip); the perform planner
    carries it as ONE un-segmented arc."""
    eid = M.create_envelope(
        conn, song_id=song, target_kind="mixer_volume",
        target_track_id=linked_track,
    )
    _add_one_breakpoint(conn, eid)
    # Session-clip planner: no session-clip call; route names perform.
    plan = push.plan_push_envelopes(conn, song_id=song, session_id=session)
    assert plan.calls == []
    assert any("performed-automation" in n for n in plan.notes), plan.notes
    assert not any("no arrangement clip" in n for n in plan.notes), plan.notes
    # Perform planner: ONE arc, full span, addressed to the plain track —
    # not segmented at clip boundaries.
    pplan = push.plan_push_performed_automation(
        conn, song_id=song, session_id=session,
    )
    batch = [c for c in pplan.calls if c.args.get("action") == "perform_batch"]
    assert len(batch) == 1
    arcs = batch[0].args["arcs"]
    assert len(arcs) == 1
    assert arcs[0]["arc_id"] == eid
    assert arcs[0]["target_kind"] == "mixer_volume"
    assert arcs[0]["track_index"] == 5  # linked_track's ableton index
    assert "master" not in arcs[0]
    assert [bp["time_beats"] for bp in arcs[0]["breakpoints"]] == [0.0, 1.0]


def test_mixer_volume_routes_to_perform_when_envelope_exceeds_placement(
    conn, song, session, linked_track, linked_clip, arr_clip,
):
    """ENV-9P4T (was W4-B skip): the envelope's span exceeds the covering
    clip's source length (arr_clip is 8 beats at offset 0; envelope goes to
    16), so no single session clip covers it → infer-from-span routes it to
    perform (a continuous ride past the clip seam), not the old skip."""
    eid = M.create_envelope(
        conn, song_id=song, target_kind="mixer_volume",
        target_track_id=linked_track,
    )
    M.replace_breakpoints(
        conn, envelope_id=eid,
        breakpoints=[
            {"time_beats": 0.0,  "value": 0.5, "curve_kind": "linear"},
            {"time_beats": 16.0, "value": 1.0, "curve_kind": "linear"},
        ],
    )
    plan = push.plan_push_envelopes(conn, song_id=song, session_id=session)
    assert plan.calls == []
    assert any("performed-automation" in n for n in plan.notes), plan.notes
    assert not any("no arrangement clip" in n for n in plan.notes), plan.notes


def test_mixer_volume_breakpoints_translated_to_clip_local(
    conn, song, session, linked_track, linked_clip,
):
    """W4-B: when a placement starts mid-song, breakpoint times are
    translated to clip-local by subtracting the placement offset.

    ``linked_clip`` (length=8) is placed at bar 3 = beat 8 (in 4/4). An
    envelope with arrangement-time breakpoints at beats 8 and 14 should
    emit clip-local breakpoints at beats 0 and 6.
    """
    M.add_arrangement_clip(
        conn, song_id=song, track_id=linked_track, clip_id=linked_clip,
        start_bar=3.0, end_bar=5.0,
    )
    eid = M.create_envelope(
        conn, song_id=song, target_kind="mixer_volume",
        target_track_id=linked_track,
    )
    M.replace_breakpoints(
        conn, envelope_id=eid,
        breakpoints=[
            {"time_beats": 8.0,  "value": 0.45, "curve_kind": "linear"},
            {"time_beats": 14.0, "value": 0.85, "curve_kind": "linear"},
        ],
    )
    plan = push.plan_push_envelopes(conn, song_id=song, session_id=session)
    calls = _calls_by_target_kind(plan)
    assert list(calls) == ["mixer_volume"]
    bps = calls["mixer_volume"][0].args["breakpoints"]
    assert bps == [
        {"time_beats": 0.0, "value": 0.45, "curve": "linear"},
        {"time_beats": 6.0, "value": 0.85, "curve": "linear"},
    ]


def test_mixer_volume_warns_when_session_clip_has_multiple_placements(
    conn, song, session, linked_track, linked_clip, arr_clip,
):
    """W4-B / W4-A: when the source session clip is placed multiple
    times in the arrangement, ``duplicate_to_arrangement`` snapshot-
    copies the envelope to every placement. Planner emits + warns so
    the author knows the envelope will also fire at the extras.
    """
    # arr_clip is at bar 1 (beat 0). Add a second placement at bar 9
    # (beat 32) of the same source clip — same source, different
    # arrangement position.
    M.add_arrangement_clip(
        conn, song_id=song, track_id=linked_track, clip_id=linked_clip,
        start_bar=9.0, end_bar=11.0,
    )
    eid = M.create_envelope(
        conn, song_id=song, target_kind="mixer_volume",
        target_track_id=linked_track,
    )
    _add_one_breakpoint(conn, eid)
    plan = push.plan_push_envelopes(conn, song_id=song, session_id=session)
    calls = _calls_by_target_kind(plan)
    assert list(calls) == ["mixer_volume"]
    assert any(
        "multiple arrangement positions" in n and "32" in n
        for n in plan.notes
    ), plan.notes


# ---------- W7-C: W4-B defensive warns ----------


def test_warns_when_multiple_distinct_clips_cover_envelope_range(
    conn, song, session, linked_track, linked_clip, arr_clip,
):
    """W4-B defensive warn: two DISTINCT session clips on the same
    track cover the envelope's beat range. Planner routes through the
    earliest by start_bar but warns so the author can resolve."""
    # Second distinct clip on the same track with overlapping arrangement
    # range. arr_clip covers [0, 8]; this one covers [4, 12].
    other_clip = M.create_clip(
        conn, track_id=linked_track, slot=2, length_beats=8.0, name="other",
    )
    M.add_arrangement_clip(
        conn, song_id=song, track_id=linked_track, clip_id=other_clip,
        start_bar=2.0, end_bar=4.0,  # bar 2 (beat 4) -> bar 4 (beat 12)
    )
    eid = M.create_envelope(
        conn, song_id=song, target_kind="mixer_volume",
        target_track_id=linked_track,
    )
    # Envelope range [4, 6] — covered by BOTH clips.
    M.replace_breakpoints(
        conn, envelope_id=eid,
        breakpoints=[
            {"time_beats": 4.0, "value": 0.5, "curve_kind": "hold"},
            {"time_beats": 6.0, "value": 0.0, "curve_kind": "hold"},
        ],
    )
    plan = push.plan_push_envelopes(conn, song_id=song, session_id=session)
    assert len(plan.calls) == 1, "envelope should still emit on the chosen clip"
    assert any(
        "multiple distinct session clips" in n
        and other_clip in n  # the alternative is named
        for n in plan.notes
    ), plan.notes


def test_no_multiple_covering_warn_when_only_same_clip_duplicated(
    conn, song, session, linked_track, linked_clip, arr_clip,
):
    """The multi-distinct-clip warn must NOT fire when the SAME source
    clip is placed multiple times. That case is handled by the existing
    `_warn_extra_placements` and would be noise here."""
    M.add_arrangement_clip(
        conn, song_id=song, track_id=linked_track, clip_id=linked_clip,
        start_bar=9.0, end_bar=11.0,
    )
    eid = M.create_envelope(
        conn, song_id=song, target_kind="mixer_volume",
        target_track_id=linked_track,
    )
    _add_one_breakpoint(conn, eid)
    plan = push.plan_push_envelopes(conn, song_id=song, session_id=session)
    assert not any(
        "multiple distinct session clips" in n for n in plan.notes
    ), plan.notes


def test_warns_when_placement_trimmed_shorter_than_envelope(
    conn, song, session, linked_track,
):
    """W4-B defensive warn: the matched placement's end_bar trims the
    clip shorter than its source length, AND the envelope's max time
    exceeds the trimmed end. The envelope writes correctly to the
    session clip but won't sound past the trim point in this
    arrangement placement.
    """
    clip = M.create_clip(
        conn, track_id=linked_track, slot=1, length_beats=16.0, name="long",
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="clip", db_id=clip, ableton_index=1,
    )
    # Source is 16 beats; placement trims to 8 beats (bar 1 to bar 3).
    M.add_arrangement_clip(
        conn, song_id=song, track_id=linked_track, clip_id=clip,
        start_bar=1.0, end_bar=3.0,
    )
    eid = M.create_envelope(
        conn, song_id=song, target_kind="mixer_volume",
        target_track_id=linked_track,
    )
    # Envelope goes to beat 12 — past the placement's 8-beat trim.
    # Coverage check uses source length (16), so the placement still
    # matches; the warn flags the trimmed-extent mismatch.
    M.replace_breakpoints(
        conn, envelope_id=eid,
        breakpoints=[
            {"time_beats": 0.0,  "value": 0.5, "curve_kind": "hold"},
            {"time_beats": 12.0, "value": 1.0, "curve_kind": "hold"},
        ],
    )
    plan = push.plan_push_envelopes(conn, song_id=song, session_id=session)
    assert len(plan.calls) == 1
    assert any(
        "trimmed shorter than the source clip" in n
        and "time_beats=12" in n
        for n in plan.notes
    ), plan.notes


def test_no_trimmed_warn_when_envelope_fits_within_trimmed_extent(
    conn, song, session, linked_track,
):
    """Placement is trimmed but the envelope ends inside the trimmed
    extent — playback is unaffected, no warn."""
    clip = M.create_clip(
        conn, track_id=linked_track, slot=1, length_beats=16.0, name="long",
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="clip", db_id=clip, ableton_index=1,
    )
    M.add_arrangement_clip(
        conn, song_id=song, track_id=linked_track, clip_id=clip,
        start_bar=1.0, end_bar=3.0,  # 8 beats
    )
    eid = M.create_envelope(
        conn, song_id=song, target_kind="mixer_volume",
        target_track_id=linked_track,
    )
    # Envelope fits within the trimmed [0, 8] extent.
    M.replace_breakpoints(
        conn, envelope_id=eid,
        breakpoints=[
            {"time_beats": 0.0, "value": 0.5, "curve_kind": "hold"},
            {"time_beats": 4.0, "value": 1.0, "curve_kind": "hold"},
        ],
    )
    plan = push.plan_push_envelopes(conn, song_id=song, session_id=session)
    assert not any(
        "trimmed shorter than the source clip" in n for n in plan.notes
    ), plan.notes


def test_no_trimmed_warn_when_placement_not_trimmed(
    conn, song, session, linked_track, linked_clip, arr_clip,
):
    """The default arr_clip fixture covers exactly source length —
    no trim, so the trimmed-placement warn must not fire."""
    eid = M.create_envelope(
        conn, song_id=song, target_kind="mixer_volume",
        target_track_id=linked_track,
    )
    _add_one_breakpoint(conn, eid)
    plan = push.plan_push_envelopes(conn, song_id=song, session_id=session)
    assert not any(
        "trimmed shorter than the source clip" in n for n in plan.notes
    ), plan.notes


# ---------- send_level (W4-B session-clip routing) ----------


def test_send_level_emits_via_session_clip(
    conn, song, session, linked_track, linked_clip, linked_return, arr_clip,
):
    eid = M.create_envelope(
        conn, song_id=song, target_kind="send_level",
        target_track_id=linked_track, target_send_return_id=linked_return,
    )
    _add_one_breakpoint(conn, eid)
    plan = push.plan_push_envelopes(conn, song_id=song, session_id=session)
    calls = _calls_by_target_kind(plan)
    assert list(calls) == ["send_level"]
    call = calls["send_level"][0]
    assert call.args == {
        "action": "write_envelope",
        "target_kind": "send_level",
        "track_index": 5,
        "location": "session",
        "clip_index": 1,
        "return_index": 1,
        "breakpoints": [
            {"time_beats": 0.0, "value": 0.5, "curve": "linear"},
            {"time_beats": 1.0, "value": 0.0, "curve": "linear"},
        ],
    }


def test_send_level_skipped_when_return_unlinked(
    conn, song, session, linked_track, ret, arr_clip,
):
    eid = M.create_envelope(
        conn, song_id=song, target_kind="send_level",
        target_track_id=linked_track, target_send_return_id=ret,
    )
    _add_one_breakpoint(conn, eid)
    plan = push.plan_push_envelopes(conn, song_id=song, session_id=session)
    assert plan.calls == []
    assert any("send_level" in n and "missing link" in n for n in plan.notes)


def test_send_level_routes_to_perform_when_no_arrangement_clip_covers(
    conn, song, session, linked_track, linked_return,
):
    """ENV-9P4T (was W4-B skip): the song-spanning send across tacet-section
    gaps that MIX-3S7P/ENV-3M7K could not host on a session clip now routes
    to perform — no covering clip → continuous arrangement send ride."""
    eid = M.create_envelope(
        conn, song_id=song, target_kind="send_level",
        target_track_id=linked_track, target_send_return_id=linked_return,
    )
    _add_one_breakpoint(conn, eid)
    plan = push.plan_push_envelopes(conn, song_id=song, session_id=session)
    assert plan.calls == []
    assert any(
        "send_level" in n and "performed-automation" in n
        for n in plan.notes
    ), plan.notes
    assert not any("no arrangement clip" in n for n in plan.notes), plan.notes


# ---------- apply_push_results dispatch ----------


def test_apply_push_results_records_envelope_link(
    conn, song, session, linked_track, linked_clip,
):
    eid = M.create_envelope(
        conn, song_id=song, target_kind="mixer_volume", target_track_id=linked_track,
    )
    push.apply_push_results(
        conn,
        results=[{
            "key": f"envelope:{eid}",
            "ok": True,
            "tool": "ableton_automation",
            "result": {"envelope_index": 7},
        }],
        session_id=session,
    )
    from hallucinote.db import queries as Q
    assert Q.get_ableton_link(
        conn, session_id=session, db_kind="envelope", db_id=eid,
    ) == 7


def test_apply_push_results_envelope_without_index_skips_link(
    conn, song, session, linked_track,
):
    eid = M.create_envelope(
        conn, song_id=song, target_kind="mixer_volume", target_track_id=linked_track,
    )
    # Emulator that no-ops returns ok=True with no envelope_index.
    push.apply_push_results(
        conn,
        results=[{
            "key": f"envelope:{eid}",
            "ok": True,
            "tool": "ableton_automation",
            "result": {},
        }],
        session_id=session,
    )
    from hallucinote.db import queries as Q
    assert Q.get_ableton_link(
        conn, session_id=session, db_kind="envelope", db_id=eid,
    ) is None


# ---------- multi-kind: end-to-end smoke ----------


def test_emittable_target_kinds_in_one_song(
    conn, song, session, linked_track, linked_clip, linked_return,
    linked_device, note, arr_clip,
):
    """W4-B: five target_kinds are emittable today (clip_cc / clip_pitch_bend
    are skip-and-warn per the LOM gap). All emit through one
    ableton_automation tool; each carries the envelope:<id> key.

    ``arr_clip`` provides session-clip routing for the four mix-targeting
    kinds; the note_expression envelope addresses ``linked_clip`` directly
    via target_note_id.
    """
    eids = []
    eids.append(M.create_envelope(
        conn, song_id=song, target_kind="note_expression",
        target_note_id=note, parameter_path="timbre",
    ))
    eids.append(M.create_envelope(
        conn, song_id=song, target_kind="device_parameter",
        target_device_id=linked_device, parameter_path="Threshold",
    ))
    eids.append(M.create_envelope(
        conn, song_id=song, target_kind="mixer_volume",
        target_track_id=linked_track,
    ))
    eids.append(M.create_envelope(
        conn, song_id=song, target_kind="mixer_pan",
        target_track_id=linked_track,
    ))
    eids.append(M.create_envelope(
        conn, song_id=song, target_kind="send_level",
        target_track_id=linked_track, target_send_return_id=linked_return,
    ))
    for eid in eids:
        _add_one_breakpoint(conn, eid)
    plan = push.plan_push_envelopes(conn, song_id=song, session_id=session)
    kinds = sorted(_calls_by_target_kind(plan))
    assert kinds == [
        "device_parameter",
        "mixer_pan",
        "mixer_volume",
        "note_expression",
        "send_level",
    ]
    # Single-tool collapse holds across all emittable target_kinds.
    assert {c.tool for c in plan.calls} == {"ableton_automation"}
    keys = {c.key for c in plan.calls}
    assert keys == {f"envelope:{eid}" for eid in eids}


# ---------- W5-E: curve-hint lossiness warn ----------
#
# Live 12.4 envelopes are step-only (Envelope.insert_step). DB curve_kinds
# 'linear' / 'fast' / 'slow' are recorded faithfully but discarded on push;
# only 'hold' round-trips. The planner emits ONE warn per envelope when any
# breakpoint carries a lossy curve hint, surfacing the round-trip lossiness
# at plan time rather than letting the user discover it from MCP-side
# response notes.


def _lossy_warns(plan) -> list[str]:
    return [n for n in plan.notes if "curve hints are recorded in the DB but lossy" in n]


def test_lossy_curve_hint_warns_once_for_linear_default(
    conn, song, session, linked_track, linked_clip, linked_device, arr_clip,
):
    """Default curve_kind is 'linear'. A typical envelope hits the warn."""
    eid = M.create_envelope(
        conn, song_id=song, target_kind="device_parameter",
        target_device_id=linked_device, parameter_path="Threshold",
    )
    _add_one_breakpoint(conn, eid)  # both breakpoints curve_kind='linear'
    plan = push.plan_push_envelopes(conn, song_id=song, session_id=session)
    warns = _lossy_warns(plan)
    assert len(warns) == 1, plan.notes
    assert eid in warns[0]
    assert "device_parameter" in warns[0]
    assert "Live 12.4" in warns[0]


def test_lossy_curve_hint_dedupes_across_many_breakpoints(
    conn, song, session, linked_track, linked_clip, linked_device, arr_clip,
):
    """Many lossy breakpoints in one envelope → exactly one warn (dedup
    per envelope, not per breakpoint)."""
    eid = M.create_envelope(
        conn, song_id=song, target_kind="device_parameter",
        target_device_id=linked_device, parameter_path="Threshold",
    )
    for t, curve in [
        (0.0, "linear"),
        (0.25, "fast"),
        (0.5, "slow"),
        (0.75, "linear"),
        (1.0, "hold"),
    ]:
        M.add_breakpoint(
            conn, envelope_id=eid, time_beats=t, value=0.5, curve_kind=curve,
        )
    plan = push.plan_push_envelopes(conn, song_id=song, session_id=session)
    assert len(_lossy_warns(plan)) == 1, plan.notes


def test_all_hold_curves_no_lossy_warn(
    conn, song, session, linked_track, linked_clip, linked_device, arr_clip,
):
    """An envelope authored entirely with 'hold' curves round-trips
    losslessly — no warn fires."""
    eid = M.create_envelope(
        conn, song_id=song, target_kind="device_parameter",
        target_device_id=linked_device, parameter_path="Threshold",
    )
    M.add_breakpoint(
        conn, envelope_id=eid, time_beats=0.0, value=0.5, curve_kind="hold",
    )
    M.add_breakpoint(
        conn, envelope_id=eid, time_beats=1.0, value=0.0, curve_kind="hold",
    )
    plan = push.plan_push_envelopes(conn, song_id=song, session_id=session)
    # The envelope still emits a ToolCall (it ships).
    assert _calls_by_target_kind(plan).get("device_parameter")
    # But no lossy-curve warn — 'hold' matches Live's step behavior.
    assert _lossy_warns(plan) == [], plan.notes


def test_lossy_warn_per_envelope_not_pooled(
    conn, song, session, linked_track, linked_clip, linked_device, arr_clip,
):
    """Two envelopes each with lossy curves → two warns (one per envelope).
    Dedup is scoped per-envelope, not global."""
    eid1 = M.create_envelope(
        conn, song_id=song, target_kind="device_parameter",
        target_device_id=linked_device, parameter_path="Threshold",
    )
    eid2 = M.create_envelope(
        conn, song_id=song, target_kind="mixer_volume",
        target_track_id=linked_track,
    )
    for eid in (eid1, eid2):
        _add_one_breakpoint(conn, eid)  # linear defaults
    plan = push.plan_push_envelopes(conn, song_id=song, session_id=session)
    warns = _lossy_warns(plan)
    assert len(warns) == 2, plan.notes
    assert any(eid1 in w for w in warns)
    assert any(eid2 in w for w in warns)


def test_skipped_envelope_does_not_emit_lossy_curve_warn(
    conn, song, session, linked_track, linked_clip,
):
    """clip_cc envelopes are skipped wholesale (LOM gap); the curve hint
    isn't "lossy on push" because nothing gets pushed. The skip-with-warn
    message stands alone — no additional curve-lossiness warn."""
    eid = M.create_envelope(
        conn, song_id=song, target_kind="clip_cc",
        target_clip_id=linked_clip, parameter_path="64",
    )
    _add_one_breakpoint(conn, eid)  # linear curves, but envelope is skipped
    plan = push.plan_push_envelopes(conn, song_id=song, session_id=session)
    assert plan.calls == []
    assert _lossy_warns(plan) == [], plan.notes
    # The LOM-gap skip warn is still present.
    assert any("clip_cc" in n and "Skipping" in n for n in plan.notes)


def test_lossy_warn_fires_on_note_expression_path(
    conn, song, session, linked_track, linked_clip, note,
):
    """The warn helper is wired into all four emit paths. Cross-path
    canary: note_expression envelope with lossy curves → one warn."""
    eid = M.create_envelope(
        conn, song_id=song, target_kind="note_expression",
        target_note_id=note, parameter_path="pitch",
    )
    _add_one_breakpoint(conn, eid)  # linear defaults
    plan = push.plan_push_envelopes(conn, song_id=song, session_id=session)
    warns = _lossy_warns(plan)
    assert len(warns) == 1, plan.notes
    assert "note_expression" in warns[0]


# ---------------------------------------------------------------------------
# ENV-7G4K: route partition (session-clip vs perform vs refused-audio)
# ---------------------------------------------------------------------------


def _force_track_kind(conn, track_id: str, kind: str) -> None:
    """Flip a track's kind AFTER envelope creation. For 'audio' this
    bypasses the mutator refusal to exercise the planner-side safety net
    (legacy rows / pulled state); for master/group it just spares the
    fixtures a second track + link."""
    conn.execute("UPDATE tracks SET kind = ? WHERE id = ?", (kind, track_id))


def test_planner_routes_master_mixer_envelope_to_perform(
    conn, song, session, linked_track, linked_clip, arr_clip,
):
    """ENV-7G4K: a master-host mixer envelope is not emitted by the
    session-clip phase and not refused — the note names the
    performed-automation route (was: sub-bus teaching + skip)."""
    eid = M.create_envelope(
        conn, song_id=song, target_kind="mixer_volume",
        target_track_id=linked_track,
    )
    _add_one_breakpoint(conn, eid)
    _force_track_kind(conn, linked_track, "master")
    plan = push.plan_push_envelopes(conn, song_id=song, session_id=session)
    assert plan.calls == []
    assert any("performed-automation" in n for n in plan.notes), plan.notes
    assert not any("sub-bus" in n for n in plan.notes), plan.notes


def test_planner_routes_group_mixer_envelope_to_perform(
    conn, song, session, linked_track, linked_clip, arr_clip,
):
    eid = M.create_envelope(
        conn, song_id=song, target_kind="mixer_volume",
        target_track_id=linked_track,
    )
    _add_one_breakpoint(conn, eid)
    _force_track_kind(conn, linked_track, "group")
    plan = push.plan_push_envelopes(conn, song_id=song, session_id=session)
    assert plan.calls == []
    assert any("performed-automation" in n for n in plan.notes), plan.notes


def test_audio_mixer_envelope_covered_by_clip_refuses_with_clp_aud2(
    conn, song, session, linked_track, linked_clip, arr_clip,
):
    """ENV-9P4T: an audio-track mixer envelope COVERED by a single (audio)
    session clip is a per-clip ride — refused at push with CLP-AUD2 teaching
    (the session-audio-clip push surface), NOT the obsolete ENV-8H1T blanket
    refusal. arr_clip covers the [0,1] span, so this is the covered case."""
    eid = M.create_envelope(
        conn, song_id=song, target_kind="mixer_pan",
        target_track_id=linked_track,
    )
    _add_one_breakpoint(conn, eid)
    _force_track_kind(conn, linked_track, "audio")
    plan = push.plan_push_envelopes(conn, song_id=song, session_id=session)
    assert plan.calls == []
    assert any("audio" in n and "CLP-AUD2" in n for n in plan.notes), plan.notes
    assert not any("sub-bus" in n for n in plan.notes), plan.notes


def test_audio_mixer_envelope_uncovered_routes_to_perform(
    conn, song, session, linked_track,
):
    """ENV-9P4T: an audio track's mixer envelope that NO session clip covers
    is a continuous arrangement ride — it routes to perform exactly like a
    plain midi track (the audio-track continuous ride this chunk unlocks).
    No arr_clip fixture → uncovered."""
    eid = M.create_envelope(
        conn, song_id=song, target_kind="mixer_volume",
        target_track_id=linked_track,
    )
    _add_one_breakpoint(conn, eid)
    _force_track_kind(conn, linked_track, "audio")
    plan = push.plan_push_envelopes(conn, song_id=song, session_id=session)
    assert plan.calls == []
    assert any("performed-automation" in n for n in plan.notes), plan.notes
    assert not any("CLP-AUD2" in n for n in plan.notes), plan.notes
    # End-to-end: the perform planner carries the audio-track arc.
    pplan = push.plan_push_performed_automation(
        conn, song_id=song, session_id=session,
    )
    batch = [c for c in pplan.calls if c.args.get("action") == "perform_batch"]
    assert len(batch) == 1
    assert batch[0].args["arcs"][0]["arc_id"] == eid
    assert batch[0].args["arcs"][0]["track_index"] == 5


def test_planner_warns_when_send_envelope_targets_audio_track(
    conn, song, session, linked_track, linked_clip, arr_clip,
    linked_return,
):
    eid = M.create_envelope(
        conn, song_id=song, target_kind="send_level",
        target_track_id=linked_track,
        target_send_return_id=linked_return,
    )
    _add_one_breakpoint(conn, eid)
    _force_track_kind(conn, linked_track, "audio")
    plan = push.plan_push_envelopes(conn, song_id=song, session_id=session)
    assert plan.calls == []
    assert any("audio" in n and "send_level" in n for n in plan.notes), plan.notes


def test_planner_warns_send_level_on_master_as_invalid(
    conn, song, session, linked_track, linked_clip, arr_clip,
    linked_return,
):
    """Legacy-row safety net: send_level on the master is unauthorable on
    any route (the master has no sends) — a hard skip-warn, not a
    perform routing note."""
    eid = M.create_envelope(
        conn, song_id=song, target_kind="send_level",
        target_track_id=linked_track,
        target_send_return_id=linked_return,
    )
    _add_one_breakpoint(conn, eid)
    _force_track_kind(conn, linked_track, "master")
    plan = push.plan_push_envelopes(conn, song_id=song, session_id=session)
    assert plan.calls == []
    assert any("no sends" in n for n in plan.notes), plan.notes
    assert not any("performed-automation" in n for n in plan.notes), plan.notes


def test_planner_routes_master_device_parameter_to_perform(
    conn, song, session, linked_track, linked_clip, arr_clip, linked_device,
):
    """Master-chain device sweeps are the canonical perform target
    (design.md decision 3)."""
    eid = M.create_envelope(
        conn, song_id=song, target_kind="device_parameter",
        target_device_id=linked_device, parameter_path="Threshold",
    )
    _add_one_breakpoint(conn, eid)
    _force_track_kind(conn, linked_track, "master")
    plan = push.plan_push_envelopes(conn, song_id=song, session_id=session)
    assert plan.calls == []
    assert any("performed-automation" in n for n in plan.notes), plan.notes


def test_planner_routes_return_mixer_envelope_to_perform(
    conn, song, session, linked_return,
):
    """return_mixer_* kinds are always perform-routed (returns host no
    clips; probe 4b verified the mechanism on returns)."""
    eid = M.create_envelope(
        conn, song_id=song, target_kind="return_mixer_volume",
        target_send_return_id=linked_return,
    )
    _add_one_breakpoint(conn, eid)
    plan = push.plan_push_envelopes(conn, song_id=song, session_id=session)
    assert plan.calls == []
    assert any("performed-automation" in n and "return_mixer_volume" in n
               for n in plan.notes), plan.notes


def test_route_for_host_kind_covers_every_track_kind():
    """Drift-guard (ENV-5R2J): the host-kind→route map must assign a concrete
    route to EVERY canonical track kind, so a new track kind added without a
    push route fails here instead of silently routing to 'unroutable' at push
    time. Pins the planner's route policy to the single host-kind vocabulary
    (db.mutations.TRACK_KINDS) the DB eligibility gate also keys off — the two
    encodings can no longer drift apart unnoticed. Routing and eligibility stay
    separate policies; only the vocabulary is shared.
    """
    from hallucinote.sync.push.envelopes import _route_for_host_kind
    from hallucinote.db.mutations import TRACK_KINDS

    unrouted = {k for k in TRACK_KINDS if _route_for_host_kind(k) == "unroutable"}
    assert not unrouted, (
        f"track kinds with no push route: {sorted(unrouted)} — add a branch in "
        "_route_for_host_kind (ENV-5R2J: single host-kind vocabulary)"
    )
    # A kind OUTSIDE the vocabulary (and None) still falls through to the
    # explicit 'unroutable' belt-and-suspenders.
    assert _route_for_host_kind("synthetic-unknown-kind") == "unroutable"
    assert _route_for_host_kind(None) == "unroutable"


def test_classify_envelope_route_partitions_all_kinds(
    conn, song, session, linked_track, linked_clip, arr_clip,
    linked_return, linked_device,
):
    """The eligibility predicate cleanly partitions session-clip vs
    perform vs refused-audio (chunk 02 acceptance criterion). One song,
    one envelope per route family, asserted directly on the predicate.

    These envelopes carry NO breakpoints, so they exercise the coarse
    host-kind fallback (`_route_track_hosted` returns the
    `_route_for_host_kind` base when span is undefined). The ENV-9P4T
    infer-from-span branch (covered → per-clip, uncovered → perform) has
    dedicated tests above: `test_mixer_volume_routes_to_perform_when_*`,
    `test_audio_mixer_envelope_*`, `test_mixer_volume_emits_via_session_clip`."""
    mixer_midi = M.create_envelope(
        conn, song_id=song, target_kind="mixer_volume",
        target_track_id=linked_track,
    )
    ret_mixer = M.create_envelope(
        conn, song_id=song, target_kind="return_mixer_pan",
        target_send_return_id=linked_return,
    )
    dev_midi = M.create_envelope(
        conn, song_id=song, target_kind="device_parameter",
        target_device_id=linked_device, parameter_path="Threshold",
    )
    cc = M.create_envelope(
        conn, song_id=song, target_kind="clip_cc",
        target_clip_id=linked_clip, parameter_path="64",
    )

    def route_of(env_id):
        row = conn.execute(
            "SELECT * FROM envelopes WHERE id = ?", (env_id,),
        ).fetchone()
        return push.classify_envelope_route(conn, row, song_id=song)

    assert route_of(mixer_midi) == "session_clip"
    assert route_of(ret_mixer) == "perform"
    assert route_of(dev_midi) == "session_clip"
    assert route_of(cc) == "clip_scoped"

    _force_track_kind(conn, linked_track, "master")
    assert route_of(mixer_midi) == "perform"
    assert route_of(dev_midi) == "perform"

    _force_track_kind(conn, linked_track, "audio")
    assert route_of(mixer_midi) == "refused_audio"
    assert route_of(dev_midi) == "refused_audio"


def test_classify_send_level_on_master_is_unroutable(
    conn, song, session, linked_track, linked_return,
):
    """The master strip has no sends — a (mutator-bypassing) master
    send_level row must NOT partition to 'perform', or the performed-
    automation phase would emit a guaranteed-fail wire call. It routes
    nowhere; group hosts stay perform-routed."""
    eid = M.create_envelope(
        conn, song_id=song, target_kind="send_level",
        target_track_id=linked_track,
        target_send_return_id=linked_return,
    )

    def route_of(env_id):
        row = conn.execute(
            "SELECT * FROM envelopes WHERE id = ?", (env_id,),
        ).fetchone()
        return push.classify_envelope_route(conn, row, song_id=song)

    _force_track_kind(conn, linked_track, "master")
    assert route_of(eid) == "unroutable"
    _force_track_kind(conn, linked_track, "group")
    assert route_of(eid) == "perform"


# The former "D1 teaching-message regression" tests (partition-by-hand /
# v1.1 suggestion on a no-covering-clip envelope) were removed in ENV-9P4T
# chunk 02: an uncovered track-hosted envelope now routes to perform
# (continuous ride) instead of being skipped with that stopgap teaching.
# The perform-routing of those same scenarios is asserted by
# `test_mixer_volume_routes_to_perform_when_no_arrangement_clip`,
# `_when_envelope_exceeds_placement`, `test_send_level_routes_to_perform_*`,
# and `test_device_parameter_routes_to_perform_*` above.


# ---------------------------------------------------------------------------
# P1 / N3: shared _resolve_and_translate_to_session_clip helper
# ---------------------------------------------------------------------------


def test_session_clip_routing_helper_returns_full_tuple_on_success(
    conn, song, session, linked_track, linked_clip, arr_clip,
):
    """The shared helper returns (clip_at, local_bps, placement, env_max)
    on success — the four pieces every clip-scoped emitter (mixer / send /
    device_parameter) needs to assemble its ToolCall and fire post-warnings.
    Same call shape regardless of target_kind."""
    eid = M.create_envelope(
        conn, song_id=song, target_kind="mixer_volume",
        target_track_id=linked_track,
    )
    M.replace_breakpoints(
        conn, envelope_id=eid,
        breakpoints=[
            {"time_beats": 1.0, "value": 0.5, "curve_kind": "linear"},
            {"time_beats": 3.0, "value": 0.8, "curve_kind": "linear"},
        ],
    )
    env = next(
        e for e in push.Q.get_envelopes_for_song(conn, song) if e["id"] == eid
    )
    bps_mcp = push._breakpoints_for_mcp(push.Q.get_breakpoints(conn, eid))
    plan = push.PushPlan()
    routing = push._resolve_and_translate_to_session_clip(
        plan, conn, song_id=song, session_id=session,
        envelope=env, breakpoints_mcp=bps_mcp,
        host_track_id=linked_track, host_track_at=5,
    )
    assert routing is not None
    clip_at, local_bps, placement, env_max = routing
    assert clip_at == 1
    # Placement starts at beat 0 (bar 1), so local == arrangement here.
    assert local_bps == bps_mcp
    assert placement.start_beats == 0.0
    assert env_max == 3.0
    assert plan.notes == []  # success path emits no skip warns


def test_session_clip_routing_helper_raises_on_uncovered_invariant_break(
    conn, song, session, linked_track,
):
    """ENV-9P4T: the shared helper is only reached for envelopes that
    classify_envelope_route already routed 'session_clip' (i.e. covered by a
    single session clip). Calling it with NO covering placement is an
    internal contract break between classify and the resolver, so it RAISES
    rather than emitting the former no-arrangement-clip skip-with-warn —
    uncovered envelopes now route to perform before they reach this
    session-clip emitter."""
    eid = M.create_envelope(
        conn, song_id=song, target_kind="send_level",
        target_track_id=linked_track,
        target_send_return_id=M.create_return(
            conn, song_id=song, name="Reverb", position=1,
        ),
    )
    M.replace_breakpoints(
        conn, envelope_id=eid,
        breakpoints=[
            {"time_beats": 0.0, "value": 0.5, "curve_kind": "linear"},
            {"time_beats": 2.0, "value": 0.0, "curve_kind": "linear"},
        ],
    )
    env = next(
        e for e in push.Q.get_envelopes_for_song(conn, song) if e["id"] == eid
    )
    bps_mcp = push._breakpoints_for_mcp(push.Q.get_breakpoints(conn, eid))
    plan = push.PushPlan()
    with pytest.raises(RuntimeError) as excinfo:
        push._resolve_and_translate_to_session_clip(
            plan, conn, song_id=song, session_id=session,
            envelope=env, breakpoints_mcp=bps_mcp,
            host_track_id=linked_track, host_track_at=5,
        )
    assert "classify_envelope_route" in str(excinfo.value)


def test_session_clip_routing_helper_skips_when_clip_unlinked(
    conn, song, session, linked_track, clip, arr_clip,
):
    """When a covering arrangement_clip exists but the underlying session
    clip has no Ableton link, the helper emits the second skip-with-warn
    ("session clip … not linked") and returns None."""
    # arr_clip is created over `clip` (unlinked), so the helper finds a
    # covering placement but Q.get_ableton_link returns None for it.
    eid = M.create_envelope(
        conn, song_id=song, target_kind="mixer_pan",
        target_track_id=linked_track,
    )
    M.replace_breakpoints(
        conn, envelope_id=eid,
        breakpoints=[{"time_beats": 1.0, "value": 0.5, "curve_kind": "linear"}],
    )
    env = next(
        e for e in push.Q.get_envelopes_for_song(conn, song) if e["id"] == eid
    )
    bps_mcp = push._breakpoints_for_mcp(push.Q.get_breakpoints(conn, eid))
    plan = push.PushPlan()
    routing = push._resolve_and_translate_to_session_clip(
        plan, conn, song_id=song, session_id=session,
        envelope=env, breakpoints_mcp=bps_mcp,
        host_track_id=linked_track, host_track_at=5,
    )
    assert routing is None
    msgs = [n for n in plan.notes if "not linked" in n]
    assert msgs
    assert "mixer_pan" in msgs[0]
