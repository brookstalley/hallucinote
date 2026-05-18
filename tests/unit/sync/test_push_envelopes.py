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
        conn, chain_id=cid, position=1, kind="Compressor2", display_name="Comp",
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
        "track_index": 5,
        "location": "session",
        "clip_index": 1,
        "device_index": 2,
        "parameter_name": "Threshold",
        "breakpoints": [
            {"time_beats": 0.0, "value": 0.5, "curve": "linear"},
            {"time_beats": 1.0, "value": 0.0, "curve": "linear"},
        ],
    }


def test_device_parameter_return_skipped_lacking_session_clip_model(
    conn, song, session, linked_return, return_device,
):
    """W4-B: return-side device_parameter envelopes require session-clip
    routing per Live 12.4, but the DB has no return-side session-clip
    model. Planner warns + skips (filed as backlog: return-track clip
    domain)."""
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
    assert any("return-side" in n and "session-clip" in n for n in plan.notes)


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


def test_device_parameter_skipped_for_nested_rack(
    conn, song, session, linked_track,
):
    """Nested-rack device envelopes are a gap; planner warns instead of emitting."""
    top_chain = M.create_device_chain(conn, parent_track_id=linked_track)
    rack = M.create_device(conn, chain_id=top_chain, position=1,
                           kind="DrumGroupDevice", display_name="Kit")
    inner_chain = M.create_device_chain(conn, parent_rack_device_id=rack, position=1)
    inner = M.create_device(conn, chain_id=inner_chain, position=1,
                            kind="Simpler", display_name="Kick")
    eid = M.create_envelope(
        conn, song_id=song, target_kind="device_parameter",
        target_device_id=inner, parameter_path="Volume",
    )
    _add_one_breakpoint(conn, eid)
    plan = push.plan_push_envelopes(conn, song_id=song, session_id=session)
    assert plan.calls == []
    assert any("nested-rack" in n for n in plan.notes)


def test_device_parameter_skipped_when_no_arrangement_clip_covers(
    conn, song, session, linked_track, linked_clip, linked_device,
):
    """W4-B: with no arrangement_clip placement on the parent track, the
    envelope has no session-clip to route through."""
    eid = M.create_envelope(
        conn, song_id=song, target_kind="device_parameter",
        target_device_id=linked_device, parameter_path="Threshold",
    )
    _add_one_breakpoint(conn, eid)
    plan = push.plan_push_envelopes(conn, song_id=song, session_id=session)
    assert plan.calls == []
    assert any(
        "device_parameter" in n and "no arrangement clip" in n
        for n in plan.notes
    ), plan.notes


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


def test_mixer_volume_skipped_when_no_arrangement_clip(
    conn, song, session, linked_track,
):
    """W4-B: without an arrangement_clip placement on the target track,
    no session clip is available to host the envelope. Planner warns +
    skips, pointing at the route-or-trim options."""
    eid = M.create_envelope(
        conn, song_id=song, target_kind="mixer_volume",
        target_track_id=linked_track,
    )
    _add_one_breakpoint(conn, eid)
    plan = push.plan_push_envelopes(conn, song_id=song, session_id=session)
    assert plan.calls == []
    assert any(
        "mixer_volume" in n and "no arrangement clip" in n
        for n in plan.notes
    ), plan.notes


def test_mixer_volume_skipped_when_envelope_exceeds_placement(
    conn, song, session, linked_track, linked_clip, arr_clip,
):
    """W4-B: the envelope's max time_beats exceeds the placement's
    end_beats (arr_clip is 8 beats at offset 0; envelope goes to 16).
    No covering placement → skip."""
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
    assert any("no arrangement clip" in n for n in plan.notes), plan.notes


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


def test_send_level_skipped_when_no_arrangement_clip_covers(
    conn, song, session, linked_track, linked_return,
):
    eid = M.create_envelope(
        conn, song_id=song, target_kind="send_level",
        target_track_id=linked_track, target_send_return_id=linked_return,
    )
    _add_one_breakpoint(conn, eid)
    plan = push.plan_push_envelopes(conn, song_id=song, session_id=session)
    assert plan.calls == []
    assert any(
        "send_level" in n and "no arrangement clip" in n
        for n in plan.notes
    ), plan.notes


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
