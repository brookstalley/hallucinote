"""Tests for the chunk-4b push planner: plan_push_envelopes + envelope-link apply."""
from __future__ import annotations

import pytest

from songwright.db import init_db, mutations as M
from songwright.sync import push


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


# ---------- clip_cc ----------


def test_clip_cc_emits_canonical_call(
    conn, song, session, linked_track, linked_clip,
):
    eid = M.create_envelope(
        conn, song_id=song, target_kind="clip_cc",
        target_clip_id=linked_clip, parameter_path="64",
    )
    _add_one_breakpoint(conn, eid)
    plan = push.plan_push_envelopes(conn, song_id=song, session_id=session)
    calls = _calls_by_tool(plan)
    assert list(calls) == ["write_clip_cc_envelope"]
    call = calls["write_clip_cc_envelope"][0]
    assert call.args == {
        "track_index": 5,
        "clip_index": 1,
        "cc_number": 64,
        "breakpoints": [
            {"time_beats": 0.0, "value": 0.5, "curve_kind": "linear"},
            {"time_beats": 1.0, "value": 0.0, "curve_kind": "linear"},
        ],
    }
    assert call.key == f"envelope:{eid}"


def test_clip_envelope_skipped_when_clip_not_linked(
    conn, song, session, linked_track, clip,
):
    eid = M.create_envelope(
        conn, song_id=song, target_kind="clip_cc",
        target_clip_id=clip, parameter_path="64",
    )
    _add_one_breakpoint(conn, eid)
    plan = push.plan_push_envelopes(conn, song_id=song, session_id=session)
    assert plan.calls == []
    assert any("not linked" in n for n in plan.notes)


# ---------- clip_pitch_bend ----------


def test_clip_pitch_bend_emits_canonical_call(
    conn, song, session, linked_track, linked_clip,
):
    eid = M.create_envelope(
        conn, song_id=song, target_kind="clip_pitch_bend",
        target_clip_id=linked_clip,
    )
    _add_one_breakpoint(conn, eid)
    plan = push.plan_push_envelopes(conn, song_id=song, session_id=session)
    calls = _calls_by_tool(plan)
    assert list(calls) == ["write_clip_pitch_bend_envelope"]
    assert calls["write_clip_pitch_bend_envelope"][0].args["track_index"] == 5


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
    calls = _calls_by_tool(plan)
    assert list(calls) == ["write_note_expression_envelope"]
    call = calls["write_note_expression_envelope"][0]
    assert call.args["track_index"] == 5
    assert call.args["clip_index"] == 1
    assert call.args["note_pitch"] == 60
    assert call.args["note_start_beats"] == 1.5
    assert call.args["axis"] == "pitch"
    assert len(call.args["breakpoints"]) == 3


# ---------- device_parameter (track + return) ----------


def test_device_parameter_track_emits_canonical_call(
    conn, song, session, linked_track, linked_device,
):
    eid = M.create_envelope(
        conn, song_id=song, target_kind="device_parameter",
        target_device_id=linked_device, parameter_path="Threshold",
    )
    _add_one_breakpoint(conn, eid)
    plan = push.plan_push_envelopes(conn, song_id=song, session_id=session)
    calls = _calls_by_tool(plan)
    assert list(calls) == ["write_device_parameter_envelope"]
    call = calls["write_device_parameter_envelope"][0]
    assert call.args == {
        "track_index": 5,
        "device_index": 2,
        "parameter_name": "Threshold",
        "breakpoints": [
            {"time_beats": 0.0, "value": 0.5, "curve_kind": "linear"},
            {"time_beats": 1.0, "value": 0.0, "curve_kind": "linear"},
        ],
    }


def test_device_parameter_return_emits_canonical_call(
    conn, song, session, linked_return, return_device,
):
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
    calls = _calls_by_tool(plan)
    assert list(calls) == ["write_return_device_parameter_envelope"]
    call = calls["write_return_device_parameter_envelope"][0]
    assert call.args["return_index"] == 1
    assert call.args["device_index"] == 3
    assert call.args["parameter_name"] == "Decay"


def test_device_parameter_skipped_when_device_unlinked(
    conn, song, session, linked_track, device,
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


# ---------- mixer_volume + mixer_pan ----------


def test_mixer_volume_emits_canonical_call(conn, song, session, linked_track):
    eid = M.create_envelope(
        conn, song_id=song, target_kind="mixer_volume", target_track_id=linked_track,
    )
    _add_one_breakpoint(conn, eid)
    plan = push.plan_push_envelopes(conn, song_id=song, session_id=session)
    calls = _calls_by_tool(plan)
    assert list(calls) == ["write_mixer_volume_envelope"]
    assert calls["write_mixer_volume_envelope"][0].args["track_index"] == 5


def test_mixer_pan_emits_canonical_call(conn, song, session, linked_track):
    eid = M.create_envelope(
        conn, song_id=song, target_kind="mixer_pan", target_track_id=linked_track,
    )
    _add_one_breakpoint(conn, eid)
    plan = push.plan_push_envelopes(conn, song_id=song, session_id=session)
    calls = _calls_by_tool(plan)
    assert list(calls) == ["write_mixer_pan_envelope"]


# ---------- send_level ----------


def test_send_level_emits_canonical_call(
    conn, song, session, linked_track, linked_return,
):
    eid = M.create_envelope(
        conn, song_id=song, target_kind="send_level",
        target_track_id=linked_track, target_send_return_id=linked_return,
    )
    _add_one_breakpoint(conn, eid)
    plan = push.plan_push_envelopes(conn, song_id=song, session_id=session)
    calls = _calls_by_tool(plan)
    assert list(calls) == ["write_send_envelope"]
    call = calls["write_send_envelope"][0]
    assert call.args["track_index"] == 5
    assert call.args["return_index"] == 1


def test_send_level_skipped_when_return_unlinked(
    conn, song, session, linked_track, ret,
):
    eid = M.create_envelope(
        conn, song_id=song, target_kind="send_level",
        target_track_id=linked_track, target_send_return_id=ret,
    )
    _add_one_breakpoint(conn, eid)
    plan = push.plan_push_envelopes(conn, song_id=song, session_id=session)
    assert plan.calls == []
    assert any("send_level" in n and "missing link" in n for n in plan.notes)


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
            "tool": "write_mixer_volume_envelope",
            "result": {"envelope_index": 7},
        }],
        session_id=session,
    )
    from songwright.db import queries as Q
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
            "tool": "write_mixer_volume_envelope",
            "result": {},
        }],
        session_id=session,
    )
    from songwright.db import queries as Q
    assert Q.get_ableton_link(
        conn, session_id=session, db_kind="envelope", db_id=eid,
    ) is None


# ---------- multi-kind: end-to-end smoke ----------


def test_all_seven_target_kinds_in_one_song(
    conn, song, session, linked_track, linked_clip, linked_return,
    linked_device, note,
):
    """Sanity: one envelope per target_kind, all emit their canonical call."""
    eids = []
    eids.append(M.create_envelope(
        conn, song_id=song, target_kind="clip_cc",
        target_clip_id=linked_clip, parameter_path="1",
    ))
    eids.append(M.create_envelope(
        conn, song_id=song, target_kind="clip_pitch_bend",
        target_clip_id=linked_clip,
    ))
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
    tools = sorted(_calls_by_tool(plan))
    assert tools == [
        "write_clip_cc_envelope",
        "write_clip_pitch_bend_envelope",
        "write_device_parameter_envelope",
        "write_mixer_pan_envelope",
        "write_mixer_volume_envelope",
        "write_note_expression_envelope",
        "write_send_envelope",
    ]
    # Each call carries the envelope:<id> key for dispatch.
    keys = {c.key for c in plan.calls}
    assert keys == {f"envelope:{eid}" for eid in eids}
