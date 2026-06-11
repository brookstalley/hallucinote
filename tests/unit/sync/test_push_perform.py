"""Performed-automation push phase (ENV-7G4K chunk 03).

The phase emits one ``ableton_automation(action='perform')`` call per
perform-routed envelope whose fingerprint changed since the last
successful perform; unchanged arcs are skipped AND reported; every call
names its wall-clock estimate (Visible Costs); the apply layer records
performed-state only on a verified write (``automation_state == 1``).
"""
from __future__ import annotations

import pytest

from hallucinote.db import init_db, mutations as M, queries as Q
from hallucinote.db import events as E
from hallucinote.sync import push


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "perform.db")
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
    return M.create_track(conn, song_id=song, track_index=0, name="Master",
                          kind="master")


@pytest.fixture
def linked_group(conn, song, session):
    gid = M.create_track(conn, song_id=song, track_index=2, name="Bus",
                         kind="group")
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=gid, ableton_index=3,
    )
    return gid


@pytest.fixture
def linked_return(conn, song, session):
    rid = M.create_return(conn, song_id=song, name="A-Reverb", position=1)
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="return", db_id=rid, ableton_index=1,
    )
    return rid


@pytest.fixture
def master_arc(conn, song, master):
    """A master mixer_volume envelope with a 16-beat two-point ramp."""
    eid = M.create_envelope(
        conn, song_id=song, target_kind="mixer_volume",
        target_track_id=master,
    )
    M.replace_breakpoints(
        conn, envelope_id=eid,
        breakpoints=[
            {"time_beats": 0.0, "value": 0.85},
            {"time_beats": 16.0, "value": 0.4, "curve_kind": "slow"},
        ],
    )
    return eid


def _plan(conn, song, session):
    return push.plan_push_performed_automation(
        conn, song_id=song, session_id=session,
    )


def _ok_result(eid, automation_state=1):
    return {
        "key": f"perform:{eid}",
        "ok": True,
        "tool": "ableton_automation",
        "result": {"automation_state": automation_state},
    }


# ---------------------------------------------------------------------------
# Phase emission + fingerprint gate
# ---------------------------------------------------------------------------


def test_phase_emits_perform_call_for_master_arc(conn, song, session, master_arc):
    plan = _plan(conn, song, session)
    assert len(plan.calls) == 1
    call = plan.calls[0]
    assert call.tool == "ableton_automation"
    assert call.args["action"] == "perform"
    assert call.args["target_kind"] == "mixer_volume"
    assert call.args["master"] is True
    assert call.key == f"perform:{master_arc}"
    # Wire breakpoints carry the curve rename (curve_kind -> curve).
    assert call.args["breakpoints"][1]["curve"] == "slow"


def test_phase_skips_and_reports_unchanged_arc(conn, song, session, master_arc):
    """Second push after a successful perform: the arc is skipped AND
    named in the notes — never a silent skip (Visible Costs)."""
    push.apply_push_results(
        conn, [_ok_result(master_arc)], session_id=session,
    )
    plan = _plan(conn, song, session)
    assert plan.calls == []
    assert any("skipped (unchanged)" in n for n in plan.notes), plan.notes


def test_phase_reperforms_when_breakpoints_change(conn, song, session, master_arc):
    push.apply_push_results(
        conn, [_ok_result(master_arc)], session_id=session,
    )
    M.replace_breakpoints(
        conn, envelope_id=master_arc,
        breakpoints=[
            {"time_beats": 0.0, "value": 0.85},
            {"time_beats": 16.0, "value": 0.2},  # deeper duck
        ],
    )
    plan = _plan(conn, song, session)
    assert len(plan.calls) == 1
    assert plan.calls[0].key == f"perform:{master_arc}"


def test_phase_routes_group_and_return_arcs(
    conn, song, session, linked_group, linked_return,
):
    g_eid = M.create_envelope(
        conn, song_id=song, target_kind="mixer_volume",
        target_track_id=linked_group,
    )
    r_eid = M.create_envelope(
        conn, song_id=song, target_kind="return_mixer_pan",
        target_send_return_id=linked_return,
    )
    for eid in (g_eid, r_eid):
        M.replace_breakpoints(
            conn, envelope_id=eid,
            breakpoints=[
                {"time_beats": 0.0, "value": 0.5},
                {"time_beats": 8.0, "value": 0.8},
            ],
        )
    plan = _plan(conn, song, session)
    by_key = {c.key: c for c in plan.calls}
    assert by_key[f"perform:{g_eid}"].args["track_index"] == 3
    ret_call = by_key[f"perform:{r_eid}"]
    # return_mixer_pan maps to the wire vocabulary: mixer_pan + return_index.
    assert ret_call.args["target_kind"] == "mixer_pan"
    assert ret_call.args["return_index"] == 1


def test_phase_ignores_session_clip_and_audio_envelopes(
    conn, song, session, master_arc,
):
    """Only perform-routed envelopes reach this phase — midi-host arcs
    belong to the envelopes phase and don't double-emit here."""
    midi = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    eid = M.create_envelope(
        conn, song_id=song, target_kind="mixer_volume", target_track_id=midi,
    )
    M.replace_breakpoints(
        conn, envelope_id=eid,
        breakpoints=[{"time_beats": 0.0, "value": 0.1},
                     {"time_beats": 4.0, "value": 0.9}],
    )
    plan = _plan(conn, song, session)
    assert [c.key for c in plan.calls] == [f"perform:{master_arc}"]


def test_phase_warns_pending_when_group_unlinked(conn, song, session):
    gid = M.create_track(conn, song_id=song, track_index=2, name="Bus",
                         kind="group")
    eid = M.create_envelope(
        conn, song_id=song, target_kind="mixer_volume", target_track_id=gid,
    )
    M.replace_breakpoints(
        conn, envelope_id=eid,
        breakpoints=[{"time_beats": 0.0, "value": 0.5},
                     {"time_beats": 8.0, "value": 0.8}],
    )
    plan = _plan(conn, song, session)
    assert plan.calls == []
    assert any("not linked" in n and "pending" in n for n in plan.notes), \
        plan.notes


def test_phase_skips_empty_span_with_teaching(conn, song, session, master):
    eid = M.create_envelope(
        conn, song_id=song, target_kind="mixer_volume", target_track_id=master,
    )
    M.replace_breakpoints(
        conn, envelope_id=eid,
        breakpoints=[{"time_beats": 4.0, "value": 0.5}],
    )
    plan = _plan(conn, song, session)
    assert plan.calls == []
    assert any("static value" in n for n in plan.notes), plan.notes


def _two_point_ramp(conn, eid, end_beats=8.0):
    M.replace_breakpoints(
        conn, envelope_id=eid,
        breakpoints=[{"time_beats": 0.0, "value": 0.5},
                     {"time_beats": end_beats, "value": 0.8}],
    )


def test_phase_addresses_master_chain_device_sweep(
    conn, song, session, master,
):
    """The canonical perform use (design.md decision 3): a device on the
    master's chain → master=True + device_index + parameter_name."""
    chain = M.create_device_chain(conn, parent_track_id=master, position=0)
    device = M.create_device(
        conn, chain_id=chain, position=1, kind="AutoFilter",
        display_name="Auto Filter",
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="device", db_id=device,
        ableton_index=2,
    )
    eid = M.create_envelope(
        conn, song_id=song, target_kind="device_parameter",
        target_device_id=device, parameter_path="Frequency",
    )
    _two_point_ramp(conn, eid)
    plan = _plan(conn, song, session)
    assert len(plan.calls) == 1
    args = plan.calls[0].args
    assert args["target_kind"] == "device_parameter"
    assert args["master"] is True
    assert "track_index" not in args and "return_index" not in args
    assert args["device_index"] == 2
    assert args["parameter_name"] == "Frequency"


def test_phase_addresses_return_device_sweep(
    conn, song, session, linked_return,
):
    chain = M.create_device_chain(conn, parent_return_id=linked_return)
    device = M.create_device(
        conn, chain_id=chain, position=1, kind="Reverb", display_name="Reverb",
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="device", db_id=device,
        ableton_index=1,
    )
    eid = M.create_envelope(
        conn, song_id=song, target_kind="device_parameter",
        target_device_id=device, parameter_path="Decay Time",
    )
    _two_point_ramp(conn, eid)
    plan = _plan(conn, song, session)
    assert len(plan.calls) == 1
    args = plan.calls[0].args
    assert args["return_index"] == 1
    assert args["device_index"] == 1
    assert args["parameter_name"] == "Decay Time"
    assert "master" not in args and "track_index" not in args


def test_phase_addresses_group_send_ride(
    conn, song, session, linked_group, linked_return,
):
    eid = M.create_envelope(
        conn, song_id=song, target_kind="send_level",
        target_track_id=linked_group, target_send_return_id=linked_return,
    )
    _two_point_ramp(conn, eid)
    plan = _plan(conn, song, session)
    assert len(plan.calls) == 1
    args = plan.calls[0].args
    assert args["target_kind"] == "send_level"
    assert args["track_index"] == 3
    assert args["return_index"] == 1


def test_phase_warns_pending_when_master_device_unlinked(
    conn, song, session, master,
):
    """Master-chain devices are placed manually (DEV-2M9K) — an unlinked
    one defers the arc with the probe-and-link teaching, never silently."""
    chain = M.create_device_chain(conn, parent_track_id=master, position=0)
    device = M.create_device(
        conn, chain_id=chain, position=1, kind="AutoFilter",
        display_name="Auto Filter",
    )
    eid = M.create_envelope(
        conn, song_id=song, target_kind="device_parameter",
        target_device_id=device, parameter_path="Frequency",
    )
    _two_point_ramp(conn, eid)
    plan = _plan(conn, song, session)
    assert plan.calls == []
    assert any("not linked" in n and "probe-and-link" in n
               for n in plan.notes), plan.notes


def test_phase_warns_pending_when_send_return_unlinked(
    conn, song, session, linked_group,
):
    rid = M.create_return(conn, song_id=song, name="B-Delay", position=2)
    eid = M.create_envelope(
        conn, song_id=song, target_kind="send_level",
        target_track_id=linked_group, target_send_return_id=rid,
    )
    _two_point_ramp(conn, eid)
    plan = _plan(conn, song, session)
    assert plan.calls == []
    assert any("return" in n and "not linked" in n for n in plan.notes), \
        plan.notes


# ---------------------------------------------------------------------------
# Visible Costs: wall-clock estimate
# ---------------------------------------------------------------------------


def test_wall_clock_estimate_in_purpose_and_summary(
    conn, song, session, master_arc,
):
    """16 beats at the default 120 BPM = 8.0s; the call's purpose and the
    plan summary both name the cost and that the transport plays."""
    plan = _plan(conn, song, session)
    assert "~8.0s" in plan.calls[0].purpose
    summary = [n for n in plan.notes if "WILL PLAY" in n]
    assert summary and "~8.0s" in summary[0]


def test_wall_clock_estimate_honors_tempo_map(conn, song, session, master_arc):
    """Tempo map: 60 BPM from bar 1, 120 BPM from bar 3 (= beat 8 in 4/4).
    The 16-beat arc costs 8 beats @60 (8s) + 8 beats @120 (4s) = 12s."""
    M.add_tempo_point(conn, song_id=song, start_bar=1.0, tempo_bpm=60.0)
    M.add_tempo_point(conn, song_id=song, start_bar=3.0, tempo_bpm=120.0)
    plan = _plan(conn, song, session)
    assert "~12.0s" in plan.calls[0].purpose


# ---------------------------------------------------------------------------
# Apply layer: performed-state recording
# ---------------------------------------------------------------------------


def test_apply_records_state_and_event_on_verified_write(
    conn, song, session, master_arc,
):
    push.apply_push_results(
        conn, [_ok_result(master_arc)], session_id=session,
    )
    row = Q.get_performed_automation(conn, master_arc)
    assert row is not None
    assert row["fingerprint"]
    events = conn.execute(
        "SELECT kind FROM events WHERE kind = ?", (E.AUTOMATION_PERFORMED,),
    ).fetchall()
    assert len(events) == 1


@pytest.mark.parametrize("automation_state", [0, 2, None])
def test_apply_leaves_fingerprint_unwritten_on_unverified_write(
    conn, song, session, master_arc, automation_state,
):
    """automation_state != 1 (none recorded / overridden / missing) →
    no performed-state row, so the next plan retries the arc."""
    result = _ok_result(master_arc, automation_state=automation_state)
    if automation_state is None:
        del result["result"]["automation_state"]
    push.apply_push_results(conn, [result], session_id=session)
    assert Q.get_performed_automation(conn, master_arc) is None
    plan = _plan(conn, song, session)
    assert [c.key for c in plan.calls] == [f"perform:{master_arc}"]


def test_apply_skips_failed_result(conn, song, session, master_arc):
    push.apply_push_results(
        conn,
        [{"key": f"perform:{master_arc}", "ok": False,
          "tool": "ableton_automation", "error": "boom"}],
        session_id=session,
    )
    assert Q.get_performed_automation(conn, master_arc) is None


def test_full_cycle_perform_then_skip_then_change_then_perform(
    conn, song, session, master_arc,
):
    """Multi-hop: perform → no-op push → edit → re-perform → no-op again.
    Exercises the fingerprint gate across consecutive push cycles, not
    just the immediate post-state."""
    plan1 = _plan(conn, song, session)
    assert len(plan1.calls) == 1
    push.apply_push_results(conn, [_ok_result(master_arc)], session_id=session)

    assert _plan(conn, song, session).calls == []

    M.replace_breakpoints(
        conn, envelope_id=master_arc,
        breakpoints=[{"time_beats": 0.0, "value": 0.9},
                     {"time_beats": 16.0, "value": 0.3}],
    )
    plan3 = _plan(conn, song, session)
    assert len(plan3.calls) == 1
    push.apply_push_results(conn, [_ok_result(master_arc)], session_id=session)

    assert _plan(conn, song, session).calls == []
    # Two distinct performs recorded, state updated in place.
    events = conn.execute(
        "SELECT kind FROM events WHERE kind = ?", (E.AUTOMATION_PERFORMED,),
    ).fetchall()
    assert len(events) == 2
