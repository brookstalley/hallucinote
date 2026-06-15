"""Performed-automation push phase (ENV-7G4K; ENV-9P4T single-pass batch).

The phase emits ONE ``ableton_automation(action='perform_batch')`` call
carrying every perform-routed arc whose fingerprint changed since the last
successful perform (one transport pass, per-parameter windowing); unchanged
arcs are fingerprint-gated out AND reported; the call's purpose names the
UNION-span wall-clock (one pass, not the per-arc sum); a loud ``alert()``
enumerates every span the pass will overwrite (Visible Costs); the apply
layer records each arc's performed-state INDEPENDENTLY, only on a verified
write (``automation_state == 1``).
"""
from __future__ import annotations

import pytest

from hallucinote.db import init_db, mutations as M, queries as Q
from hallucinote.db import events as E
from hallucinote.sync import push
from hallucinote.sync.push._core import build_node_addr


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


def _batch_arcs(plan):
    """The single batched call's `arcs` list (raises if not exactly one)."""
    assert len(plan.calls) == 1, [c.key for c in plan.calls]
    call = plan.calls[0]
    assert call.tool == "ableton_automation"
    assert call.args["action"] == "perform_batch"
    return call, call.args["arcs"]


def _arc_result(eid, automation_state=1):
    arc = {"arc_id": eid}
    if automation_state is not _OMIT:
        arc["automation_state"] = automation_state
    return arc


_OMIT = object()


def _batch_result(*eids_or_arcs, automation_state=1, song="x"):
    """A batched perform result keyed `perform_batch:<song>` whose
    `result.arcs` carries one entry per arc. Pass envelope ids (default
    state 1) or pre-built arc dicts."""
    arcs = [
        a if isinstance(a, dict) else _arc_result(a, automation_state)
        for a in eids_or_arcs
    ]
    return {
        "key": f"perform_batch:{song}",
        "ok": True,
        "tool": "ableton_automation",
        "result": {"arcs": arcs},
    }


# ---------------------------------------------------------------------------
# Phase emission + fingerprint gate
# ---------------------------------------------------------------------------


def test_phase_emits_batched_call_for_master_arc(conn, song, session, master_arc):
    plan = _plan(conn, song, session)
    call, arcs = _batch_arcs(plan)
    assert call.key == f"perform_batch:{song}"
    assert len(arcs) == 1
    arc = arcs[0]
    assert arc["arc_id"] == master_arc
    assert arc["target_kind"] == "mixer_volume"
    assert arc["master"] is True
    # Wire breakpoints carry the curve rename (curve_kind -> curve).
    assert arc["breakpoints"][1]["curve"] == "slow"


def test_phase_skips_and_reports_unchanged_arc(conn, song, session, master_arc):
    """Second push after a successful perform: the arc is skipped AND
    named in the notes — never a silent skip (Visible Costs)."""
    push.apply_push_results(
        conn, [_batch_result(master_arc)], session_id=session,
    )
    plan = _plan(conn, song, session)
    assert plan.calls == []
    assert any("skipped (unchanged)" in n for n in plan.notes), plan.notes


def test_phase_reperforms_when_breakpoints_change(conn, song, session, master_arc):
    push.apply_push_results(
        conn, [_batch_result(master_arc)], session_id=session,
    )
    M.replace_breakpoints(
        conn, envelope_id=master_arc,
        breakpoints=[
            {"time_beats": 0.0, "value": 0.85},
            {"time_beats": 16.0, "value": 0.2},  # deeper duck
        ],
    )
    _, arcs = _batch_arcs(_plan(conn, song, session))
    assert [a["arc_id"] for a in arcs] == [master_arc]


def test_phase_routes_group_and_return_arcs_into_one_batch(
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
    _, arcs = _batch_arcs(_plan(conn, song, session))
    by_arc = {a["arc_id"]: a for a in arcs}
    assert by_arc[g_eid]["track_index"] == 3
    ret = by_arc[r_eid]
    # return_mixer_pan maps to the wire vocabulary: mixer_pan + return_index.
    assert ret["target_kind"] == "mixer_pan"
    assert ret["return_index"] == 1


def test_phase_ignores_session_clip_routed_envelope(
    conn, song, session, master_arc,
):
    """Only perform-routed arcs reach this phase. A midi mixer envelope
    COVERED by a session clip routes 'session_clip' (ENV-9P4T
    infer-from-span) and belongs to the envelopes phase — it does NOT
    double-emit here. The midi track is LINKED and has a covering placement,
    so the exclusion is genuine routing, not an unlinked-arc drop. (An
    UNCOVERED plain-track envelope DOES perform — see
    test_phase_performs_uncovered_plain_track_arc.)"""
    midi = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=midi, ableton_index=5,
    )
    clip = M.create_clip(conn, track_id=midi, slot=1, length_beats=8.0,
                         name="loop")
    M.add_arrangement_clip(
        conn, song_id=song, track_id=midi, clip_id=clip,
        start_bar=1.0, end_bar=3.0,  # covers beats [0, 8]
    )
    eid = M.create_envelope(
        conn, song_id=song, target_kind="mixer_volume", target_track_id=midi,
    )
    M.replace_breakpoints(
        conn, envelope_id=eid,
        breakpoints=[{"time_beats": 0.0, "value": 0.1},
                     {"time_beats": 4.0, "value": 0.9}],  # within [0, 8]
    )
    _, arcs = _batch_arcs(_plan(conn, song, session))
    assert [a["arc_id"] for a in arcs] == [master_arc]


def test_phase_performs_uncovered_plain_track_arc(
    conn, song, session, master_arc,
):
    """ENV-9P4T: a plain LINKED midi track whose mixer envelope no session
    clip covers is a continuous ride — it joins the batched perform pass
    alongside the master arc, addressed by its own track_index."""
    midi = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=midi, ableton_index=5,
    )
    eid = M.create_envelope(
        conn, song_id=song, target_kind="mixer_volume", target_track_id=midi,
    )
    M.replace_breakpoints(
        conn, envelope_id=eid,
        breakpoints=[{"time_beats": 0.0, "value": 0.1},
                     {"time_beats": 4.0, "value": 0.9}],
    )
    _, arcs = _batch_arcs(_plan(conn, song, session))
    by_id = {a["arc_id"]: a for a in arcs}
    assert set(by_id) == {master_arc, eid}
    assert by_id[eid]["track_index"] == 5
    assert by_id[eid]["target_kind"] == "mixer_volume"
    assert "master" not in by_id[eid]


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
    _, arcs = _batch_arcs(_plan(conn, song, session))
    arc = arcs[0]
    assert arc["target_kind"] == "device_parameter"
    assert arc["node"] == build_node_addr({"master": True}, device_index=2)
    assert "track_index" not in arc and "return_index" not in arc
    assert arc["parameter_name"] == "Frequency"


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
    _, arcs = _batch_arcs(_plan(conn, song, session))
    arc = arcs[0]
    assert arc["node"] == build_node_addr({"return_index": 1}, device_index=1)
    assert arc["parameter_name"] == "Decay Time"
    assert "master" not in arc and "track_index" not in arc


def test_phase_addresses_nested_device_via_device_path(conn, song, session):
    """DEEP-RACK-ADDR: a device_parameter envelope on a device NESTED inside a
    rack routes to perform and addresses by the TOP-LEVEL rack's link +
    device_path. The nested device is never linked itself — push reads its
    positional path from the DB."""
    track = M.create_track(conn, song_id=song, track_index=1, name="Gtr")
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=track, ableton_index=4,
    )
    top_chain = M.create_device_chain(conn, parent_track_id=track)
    rack = M.create_device(
        conn, chain_id=top_chain, position=1, kind="Instrument Rack",
        display_name="Outer Rack",
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="device", db_id=rack, ableton_index=2,
    )
    nested_chain = M.create_device_chain(
        conn, parent_rack_device_id=rack, position=1,
    )
    nested = M.create_device(
        conn, chain_id=nested_chain, position=1, kind="Operator",
        display_name="Deep Synth",
    )
    eid = M.create_envelope(
        conn, song_id=song, target_kind="device_parameter",
        target_device_id=nested, parameter_path="Volume",
    )
    _two_point_ramp(conn, eid)
    _, arcs = _batch_arcs(_plan(conn, song, session))
    arc = arcs[0]
    assert arc["target_kind"] == "device_parameter"
    # The TOP-LEVEL rack's Live index (track 4 / device 2), not the (unlinked)
    # nested device — addressed via the node's path.
    assert arc["node"] == build_node_addr(
        {"track_index": 4}, device_index=2,
        device_path=[{"chain_index": 1, "device_position": 1}],
    )
    assert arc["parameter_name"] == "Volume"


def test_phase_addresses_group_send_ride(
    conn, song, session, linked_group, linked_return,
):
    eid = M.create_envelope(
        conn, song_id=song, target_kind="send_level",
        target_track_id=linked_group, target_send_return_id=linked_return,
    )
    _two_point_ramp(conn, eid)
    _, arcs = _batch_arcs(_plan(conn, song, session))
    arc = arcs[0]
    assert arc["target_kind"] == "send_level"
    assert arc["track_index"] == 3
    assert arc["return_index"] == 1


def test_phase_warns_pending_when_master_device_unlinked(
    conn, song, session, master,
):
    """The perform (automation) phase writes only to LINKED devices — an
    unlinked master device defers the arc with the probe-and-link teaching,
    never silently. (DEV-6M2K loads master devices in the earlier devices
    phase, so this is now a transient pre-link state, not the old
    placed-by-hand contract — the deferral behavior is unchanged.)"""
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
# Visible Costs: union-span wall-clock + overwrite alert
# ---------------------------------------------------------------------------


def test_wall_clock_estimate_in_purpose_and_overwrite_alert(
    conn, song, session, master_arc,
):
    """16 beats at the default 120 BPM = 8.0s; the call's purpose names the
    union-span cost and the operator-facing alert names it too."""
    plan = _plan(conn, song, session)
    assert "~8.0s" in plan.calls[0].purpose
    alerts = [a for a in plan.alerts if "WILL RECORD/OVERWRITE" in a]
    assert alerts and "~8.0s" in alerts[0], plan.alerts


def test_overwrite_alert_enumerates_every_span(
    conn, song, session, linked_group, linked_return,
):
    """The Visible-Cost overwrite warning names each arc's span, so the
    operator sees exactly what the single pass will record/overwrite."""
    g_eid = M.create_envelope(
        conn, song_id=song, target_kind="mixer_volume",
        target_track_id=linked_group,
    )
    M.replace_breakpoints(
        conn, envelope_id=g_eid,
        breakpoints=[{"time_beats": 0.0, "value": 0.5},
                     {"time_beats": 12.0, "value": 0.8}],
    )
    r_eid = M.create_envelope(
        conn, song_id=song, target_kind="return_mixer_volume",
        target_send_return_id=linked_return,
    )
    M.replace_breakpoints(
        conn, envelope_id=r_eid,
        breakpoints=[{"time_beats": 4.0, "value": 0.2},
                     {"time_beats": 20.0, "value": 0.9}],
    )
    plan = _plan(conn, song, session)
    alert = next(a for a in plan.alerts if "WILL RECORD/OVERWRITE" in a)
    assert "[0-12]" in alert
    assert "[4-20]" in alert
    assert "2 arc(s)" in alert


def test_union_span_cost_is_not_the_per_arc_sum(
    conn, song, session, linked_group, linked_return,
):
    """Two overlapping arcs — A beats [0,16], B beats [8,24] — record in ONE
    pass over the UNION [0,24] = 12.0s, NOT the per-arc sum (8+8=16s)."""
    a_eid = M.create_envelope(
        conn, song_id=song, target_kind="mixer_volume",
        target_track_id=linked_group,
    )
    M.replace_breakpoints(
        conn, envelope_id=a_eid,
        breakpoints=[{"time_beats": 0.0, "value": 0.5},
                     {"time_beats": 16.0, "value": 0.8}],
    )
    b_eid = M.create_envelope(
        conn, song_id=song, target_kind="return_mixer_volume",
        target_send_return_id=linked_return,
    )
    M.replace_breakpoints(
        conn, envelope_id=b_eid,
        breakpoints=[{"time_beats": 8.0, "value": 0.2},
                     {"time_beats": 24.0, "value": 0.9}],
    )
    plan = _plan(conn, song, session)
    assert "~12.0s" in plan.calls[0].purpose
    assert "~16.0s" not in plan.calls[0].purpose


def test_wall_clock_estimate_honors_tempo_map(conn, song, session, master_arc):
    """Tempo map: 60 BPM from bar 1, 120 BPM from bar 3 (= beat 8 in 4/4).
    The 16-beat union span costs 8 beats @60 (8s) + 8 beats @120 (4s) = 12s."""
    M.add_tempo_point(conn, song_id=song, start_bar=1.0, tempo_bpm=60.0)
    M.add_tempo_point(conn, song_id=song, start_bar=3.0, tempo_bpm=120.0)
    plan = _plan(conn, song, session)
    assert "~12.0s" in plan.calls[0].purpose


def test_unchanged_arc_excluded_from_batch_gating_composes(
    conn, song, session, master, linked_group,
):
    """Fingerprint-gating composes with batching: after A is performed,
    editing B leaves ONLY B in the next batch — A (unchanged) is not
    re-recorded, so a hand edit to A's lane survives."""
    a_eid = M.create_envelope(
        conn, song_id=song, target_kind="mixer_volume", target_track_id=master,
    )
    _two_point_ramp(conn, a_eid)
    b_eid = M.create_envelope(
        conn, song_id=song, target_kind="mixer_volume",
        target_track_id=linked_group,
    )
    _two_point_ramp(conn, b_eid)
    # First pass records both.
    _, arcs0 = _batch_arcs(_plan(conn, song, session))
    assert {a["arc_id"] for a in arcs0} == {a_eid, b_eid}
    push.apply_push_results(
        conn, [_batch_result(a_eid, b_eid)], session_id=session,
    )
    assert _plan(conn, song, session).calls == []  # both unchanged
    # Edit only B.
    M.replace_breakpoints(
        conn, envelope_id=b_eid,
        breakpoints=[{"time_beats": 0.0, "value": 0.5},
                     {"time_beats": 8.0, "value": 0.3}],
    )
    _, arcs1 = _batch_arcs(_plan(conn, song, session))
    assert [a["arc_id"] for a in arcs1] == [b_eid]


# ---------------------------------------------------------------------------
# Apply layer: per-arc performed-state recording
# ---------------------------------------------------------------------------


def test_apply_records_state_and_event_on_verified_write(
    conn, song, session, master_arc,
):
    warnings = push.apply_push_results(
        conn, [_batch_result(master_arc)], session_id=session,
    )
    assert warnings == []
    row = Q.get_performed_automation(conn, master_arc, session)
    assert row is not None
    assert row["fingerprint"]
    events = conn.execute(
        "SELECT kind FROM events WHERE kind = ?", (E.AUTOMATION_PERFORMED,),
    ).fetchall()
    assert len(events) == 1


@pytest.mark.parametrize("automation_state", [0, 2, _OMIT])
def test_apply_leaves_fingerprint_unwritten_on_unverified_write(
    conn, song, session, master_arc, automation_state,
):
    """automation_state != 1 (none recorded / overridden / missing) →
    no performed-state row, so the next plan retries the arc — and the
    apply layer RETURNS a warning naming the arc (never a silent skip)."""
    result = _batch_result(master_arc, automation_state=automation_state)
    warnings = push.apply_push_results(conn, [result], session_id=session)
    assert len(warnings) == 1
    assert master_arc in warnings[0]
    assert "automation_state" in warnings[0]
    assert Q.get_performed_automation(conn, master_arc, session) is None
    _, arcs = _batch_arcs(_plan(conn, song, session))
    assert [a["arc_id"] for a in arcs] == [master_arc]


def test_apply_gates_each_arc_in_a_batch_independently(
    conn, song, session, master, linked_group,
):
    """One pass, two arcs: A verifies (state 1), B does not (state 2). A's
    fingerprint is recorded (next push skips it); B's is not (next push
    retries ONLY B). One unverified arc never blocks the verified one."""
    a_eid = M.create_envelope(
        conn, song_id=song, target_kind="mixer_volume", target_track_id=master,
    )
    _two_point_ramp(conn, a_eid)
    b_eid = M.create_envelope(
        conn, song_id=song, target_kind="mixer_volume",
        target_track_id=linked_group,
    )
    _two_point_ramp(conn, b_eid)
    warnings = push.apply_push_results(
        conn,
        [_batch_result(_arc_result(a_eid, 1), _arc_result(b_eid, 2))],
        session_id=session,
    )
    assert len(warnings) == 1 and b_eid in warnings[0]
    assert Q.get_performed_automation(conn, a_eid, session) is not None
    assert Q.get_performed_automation(conn, b_eid, session) is None
    _, arcs = _batch_arcs(_plan(conn, song, session))
    assert [a["arc_id"] for a in arcs] == [b_eid]


def test_apply_skips_failed_result(conn, song, session, master_arc):
    warnings = push.apply_push_results(
        conn,
        [{"key": f"perform_batch:{song}", "ok": False,
          "tool": "ableton_automation", "error": "boom"}],
        session_id=session,
    )
    assert warnings == []  # ok=False is the agent layer's to report
    assert Q.get_performed_automation(conn, master_arc, session) is None


def test_fingerprint_gate_is_session_scoped(conn, song, session, master_arc):
    """A second Live set must NOT inherit set A's performed state: after a
    verified perform into session A, planning against a fresh session B
    re-emits the arc instead of false-skipping it as unchanged."""
    push.apply_push_results(
        conn, [_batch_result(master_arc)], session_id=session,
    )
    assert not _plan(conn, song, session).calls  # set A: skip-unchanged
    session_b = M.create_ableton_session(conn, song_id=song, name="set-b")
    _, arcs_b = _batch_arcs(_plan(conn, song, session_b))
    assert [a["arc_id"] for a in arcs_b] == [master_arc]


def test_full_cycle_perform_then_skip_then_change_then_perform(
    conn, song, session, master_arc,
):
    """Multi-hop: perform → no-op push → edit → re-perform → no-op again.
    Exercises the fingerprint gate across consecutive push cycles, not
    just the immediate post-state."""
    _, arcs1 = _batch_arcs(_plan(conn, song, session))
    assert [a["arc_id"] for a in arcs1] == [master_arc]
    push.apply_push_results(
        conn, [_batch_result(master_arc)], session_id=session,
    )

    assert _plan(conn, song, session).calls == []

    M.replace_breakpoints(
        conn, envelope_id=master_arc,
        breakpoints=[{"time_beats": 0.0, "value": 0.9},
                     {"time_beats": 16.0, "value": 0.3}],
    )
    _, arcs3 = _batch_arcs(_plan(conn, song, session))
    assert [a["arc_id"] for a in arcs3] == [master_arc]
    push.apply_push_results(
        conn, [_batch_result(master_arc)], session_id=session,
    )

    assert _plan(conn, song, session).calls == []
    # Two distinct performs recorded, state updated in place.
    events = conn.execute(
        "SELECT kind FROM events WHERE kind = ?", (E.AUTOMATION_PERFORMED,),
    ).fetchall()
    assert len(events) == 2


def test_apply_perform_batch_missing_arc_id_raises(conn, song, session):
    """A batched result arc with no arc_id can't be correlated to a DB
    envelope — apply raises rather than silently dropping the record."""
    bad = {
        "key": f"perform_batch:{song}", "ok": True,
        "tool": "ableton_automation",
        "result": {"arcs": [{"automation_state": 1}]},  # no arc_id
    }
    with pytest.raises(ValueError, match="arc_id"):
        push.apply_push_results(conn, [bad], session_id=session)


def test_apply_perform_batch_empty_arcs_is_noop(conn, song, session, master_arc):
    """A batched result with an empty arcs list records nothing and warns
    nothing — a benign no-op (no arc to gate)."""
    warnings = push.apply_push_results(
        conn,
        [{"key": f"perform_batch:{song}", "ok": True,
          "tool": "ableton_automation", "result": {"arcs": []}}],
        session_id=session,
    )
    assert warnings == []
    assert Q.get_performed_automation(conn, master_arc, session) is None


def test_apply_zero_write_arc_leaves_fingerprint_unwritten(
    conn, song, session, master_arc,
):
    """automation_state==1 but updates_written==0 means the playhead crossed
    the arc's span between ticks — the '1' reflects a stale lane, not this
    arc. The fingerprint must stay unwritten so the next push re-performs."""
    arc = {"arc_id": master_arc, "automation_state": 1, "updates_written": 0}
    warnings = push.apply_push_results(
        conn,
        [{"key": f"perform_batch:{song}", "ok": True,
          "tool": "ableton_automation", "result": {"arcs": [arc]}}],
        session_id=session,
    )
    assert len(warnings) == 1
    assert master_arc in warnings[0]
    assert "updates_written=0" in warnings[0]
    assert Q.get_performed_automation(conn, master_arc, session) is None
    # And it re-emits on the next plan.
    _, arcs = _batch_arcs(_plan(conn, song, session))
    assert [a["arc_id"] for a in arcs] == [master_arc]


def test_apply_surfaces_restore_failures(conn, song, session, master_arc):
    """A restore failure (set possibly left armed) must reach the operator
    as a warning, not vanish — even when the arc itself verified."""
    result = {
        "arcs": [{"arc_id": master_arc, "automation_state": 1,
                  "updates_written": 5}],
        "restore_failures": ["record_mode: Live unreachable"],
    }
    warnings = push.apply_push_results(
        conn,
        [{"key": f"perform_batch:{song}", "ok": True,
          "tool": "ableton_automation", "result": result}],
        session_id=session,
    )
    assert any("restore step FAILED" in w and "record_mode" in w
               for w in warnings), warnings
    # The arc still recorded (the failure is a separate, additive warning).
    assert Q.get_performed_automation(conn, master_arc, session) is not None


def test_phase_degenerate_arc_does_not_poison_batch(
    conn, song, session, master, linked_group,
):
    """A degenerate (single-point) arc is filtered by the planner and never
    reaches the handler — so it can't make the whole batch span-empty-fatal.
    Valid arcs alongside it still record."""
    valid = M.create_envelope(
        conn, song_id=song, target_kind="mixer_volume",
        target_track_id=linked_group,
    )
    _two_point_ramp(conn, valid)
    degenerate = M.create_envelope(
        conn, song_id=song, target_kind="mixer_volume", target_track_id=master,
    )
    M.replace_breakpoints(
        conn, envelope_id=degenerate,
        breakpoints=[{"time_beats": 4.0, "value": 0.5}],  # single point
    )
    _, arcs = _batch_arcs(_plan(conn, song, session))
    assert [a["arc_id"] for a in arcs] == [valid]
    assert any("static value" in n for n in _plan(conn, song, session).notes)


def test_phase_defers_duplicate_target_with_alert(conn, song, session):
    """Two DISTINCT envelopes whose WIRE addressing coincides (here: two group
    tracks linked to the same Ableton index — link drift create_envelope can't
    prevent, since it dedups on DB target, not wire target) can't both ride one
    transport pass. The planner queues the first and loudly defers the rest, so
    the handler never sees a whole-batch collision."""
    g1 = M.create_track(conn, song_id=song, track_index=2, name="Bus1",
                        kind="group")
    g2 = M.create_track(conn, song_id=song, track_index=3, name="Bus2",
                        kind="group")
    # Both linked to Ableton index 3 (the collision).
    M.link_db_to_ableton(conn, session_id=session, db_kind="track", db_id=g1,
                         ableton_index=3)
    M.link_db_to_ableton(conn, session_id=session, db_kind="track", db_id=g2,
                         ableton_index=3)
    e1 = M.create_envelope(conn, song_id=song, target_kind="mixer_volume",
                          target_track_id=g1)
    _two_point_ramp(conn, e1)
    e2 = M.create_envelope(conn, song_id=song, target_kind="mixer_volume",
                          target_track_id=g2)
    _two_point_ramp(conn, e2)
    assert e1 != e2  # distinct envelopes, same wire address
    plan = _plan(conn, song, session)
    _, arcs = _batch_arcs(plan)
    assert len(arcs) == 1  # only the first-queued arc rides the pass
    assert any("same parameter" in al for al in plan.alerts), plan.alerts


def test_phase_alerts_when_changed_arc_collides_with_skipped_lane(
    conn, song, session,
):
    """ENV-8K2R #3: a CHANGED arc colliding on one wire target with an already
    recorded (skipped-unchanged) arc must be SURFACED — not silently recorded
    over the skipped arc's lane, which corrupted its stored fingerprint with no
    warning. The skipped arc now seeds the duplicate-target preflight too, so the
    collision alerts regardless of which arc the planner visits first."""
    g1 = M.create_track(conn, song_id=song, track_index=2, name="Bus1",
                        kind="group")
    g2 = M.create_track(conn, song_id=song, track_index=3, name="Bus2",
                        kind="group")
    # Link drift: both group tracks point at one Ableton index → one wire param.
    M.link_db_to_ableton(conn, session_id=session, db_kind="track", db_id=g1,
                         ableton_index=3)
    M.link_db_to_ableton(conn, session_id=session, db_kind="track", db_id=g2,
                         ableton_index=3)
    e1 = M.create_envelope(conn, song_id=song, target_kind="mixer_volume",
                          target_track_id=g1)
    _two_point_ramp(conn, e1)
    # Perform e1 → its fingerprint is recorded → next plan it is skipped-unchanged.
    push.apply_push_results(
        conn, [_batch_result(e1, song=song)], session_id=session,
    )
    # e2 on the SAME wire target, changed (never performed).
    e2 = M.create_envelope(conn, song_id=song, target_kind="mixer_volume",
                          target_track_id=g2)
    _two_point_ramp(conn, e2)

    plan = _plan(conn, song, session)
    # The collision is surfaced. Before the fix this was SILENT: the skipped e1
    # never claimed the target, so e2 queued + recorded over e1's lane.
    assert any("same parameter" in al for al in plan.alerts), plan.alerts


def test_phase_keeps_skipped_lane_when_changed_arc_visited_first(
    conn, song, session,
):
    """ENV-8K2R #3 (visit-order independence): even when the CHANGED arc is
    EARLIER in the envelope order, the already-recorded (skipped-unchanged) lane
    is kept and the changed arc is the one deferred. The two-pass claims recorded
    lanes before queuing any changed arc, so a correct lane is never clobbered —
    the gap the single-pass version had (the changed arc could win on order)."""
    g1 = M.create_track(conn, song_id=song, track_index=2, name="Bus1",
                        kind="group")
    g2 = M.create_track(conn, song_id=song, track_index=3, name="Bus2",
                        kind="group")
    M.link_db_to_ableton(conn, session_id=session, db_kind="track", db_id=g1,
                         ableton_index=3)
    M.link_db_to_ableton(conn, session_id=session, db_kind="track", db_id=g2,
                         ableton_index=3)
    # e_changed created FIRST (earlier in envelope order).
    e_changed = M.create_envelope(conn, song_id=song, target_kind="mixer_volume",
                                  target_track_id=g1)
    _two_point_ramp(conn, e_changed)
    # e_kept created second, then PERFORMED so it reads skipped-unchanged.
    e_kept = M.create_envelope(conn, song_id=song, target_kind="mixer_volume",
                               target_track_id=g2)
    _two_point_ramp(conn, e_kept)
    push.apply_push_results(
        conn, [_batch_result(e_kept, song=song)], session_id=session,
    )

    plan = _plan(conn, song, session)
    queued_ids = [
        a["arc_id"] for c in plan.calls for a in c.args.get("arcs", [])
    ]
    assert e_changed not in queued_ids, queued_ids  # deferred, lane preserved
    assert any("same parameter" in al for al in plan.alerts), plan.alerts


def test_apply_warns_on_arc_count_mismatch(conn, song, session, master_arc):
    """ENV-8K2R #4: the apply layer cross-checks the handler's reported
    arc_count against the per-arc entries actually returned. A truncated/empty
    arcs list would record nothing and re-perform forever — it must surface."""
    result = {
        "key": f"perform_batch:{song}",
        "ok": True,
        "tool": "ableton_automation",
        "result": {
            # Handler claims 2 prepared but only 1 came back (truncated payload).
            "arcs": [{"arc_id": master_arc, "automation_state": 1}],
            "arc_count": 2,
        },
    }
    warnings = push.apply_push_results(conn, [result], session_id=session)
    assert any(
        "arc_count=2" in w and "carried 1" in w for w in warnings
    ), warnings


def test_apply_no_count_warning_when_arc_counts_agree(
    conn, song, session, master_arc,
):
    """The cross-check is silent on the happy path (returned == reported)."""
    result = {
        "key": f"perform_batch:{song}",
        "ok": True,
        "tool": "ableton_automation",
        "result": {
            "arcs": [{"arc_id": master_arc, "automation_state": 1}],
            "arc_count": 1,
        },
    }
    warnings = push.apply_push_results(conn, [result], session_id=session)
    assert not any("counts disagree" in w for w in warnings), warnings


def test_perform_batch_call_carries_finite_read_ceiling(
    conn, song, session, master_arc,
):
    """ENV-8K2R #5: the planner caps the otherwise-unbounded perform_batch read
    at a union-span-derived ceiling, so a worker that dies mid-pass can't block
    push_cli forever. The ceiling must clear the realtime playback estimate (so a
    legitimate pass is never falsely timed out) yet stay finite."""
    from hallucinote.sync.push.perform import (
        _PERFORM_READ_CEILING_BUFFER_S,
        _PERFORM_READ_CEILING_FACTOR,
    )

    call, _ = _batch_arcs(_plan(conn, song, session))
    assert call.read_timeout is not None  # finite — bounds a dead worker
    # 16-beat span @120 BPM = 8s realtime; ceiling = 8*factor + buffer.
    expected = 8.0 * _PERFORM_READ_CEILING_FACTOR + _PERFORM_READ_CEILING_BUFFER_S
    assert call.read_timeout == pytest.approx(expected, abs=0.5)
    assert call.read_timeout > 8.0  # comfortably above realtime playback


def test_perform_slowdown_scales_cost_and_forwards_factor(
    conn, song, session, master_arc,
):
    """ENV-2T9K: a >1 slowdown is forwarded to the handler AND scales the
    operator cost estimates (purpose, alert, #5 read ceiling) — the pass plays
    factor× slower, so Visible Costs must reflect it."""
    from hallucinote.sync.push.perform import (
        _PERFORM_READ_CEILING_BUFFER_S,
        _PERFORM_READ_CEILING_FACTOR,
    )

    plan = push.plan_push_performed_automation(
        conn, song_id=song, session_id=session, slowdown_factor=4.0,
    )
    call, _ = _batch_arcs(plan)
    assert call.args["slowdown_factor"] == 4.0
    # 16-beat span @120 BPM = 8s realtime → 32s at 4× slowdown.
    assert "~32.0s" in call.purpose
    assert any(
        "~32.0s" in a and "slowdown for fidelity" in a for a in plan.alerts
    ), plan.alerts
    # The #5 read ceiling scales with the slowed wall-clock, not the realtime one.
    assert call.read_timeout == pytest.approx(
        32.0 * _PERFORM_READ_CEILING_FACTOR + _PERFORM_READ_CEILING_BUFFER_S,
        abs=0.5,
    )


def test_perform_default_factor_omits_slowdown_from_wire_args(
    conn, song, session, master_arc,
):
    """Default (off) keeps the wire args clean — no slowdown_factor=1.0."""
    call, _ = _batch_arcs(_plan(conn, song, session))
    assert "slowdown_factor" not in call.args


def test_plan_perform_rejects_slowdown_below_one(conn, song, session, master_arc):
    with pytest.raises(ValueError, match="slowdown_factor"):
        push.plan_push_performed_automation(
            conn, song_id=song, session_id=session, slowdown_factor=0.5,
        )


def test_collision_key_parity_planner_vs_handler():
    """The planner's duplicate-target key and the handler's collision-guard key
    must be field-for-field identical across the package boundary — if they
    drift, the planner silently stops deduping and one collision halts the whole
    phase. Pin both (this fails if either tuple's fields/order/normalization
    changes)."""
    from hallucinote.sync.push.perform import perform_target_key
    from hallucinote_mcp.handlers.automation import _PreparedArc

    def _handler_key(**addr):
        return _PreparedArc(
            arc_id="x", cleaned=[], span_start=0.0, span_end=1.0,
            target_kind=addr.get("target_kind"),
            master=bool(addr.get("master", False)),
            track_index=addr.get("track_index"),
            return_index=addr.get("return_index"),
            device_index=addr.get("device_index"),
            parameter_name=addr.get("parameter_name"),
            device_path=addr.get("device_path"),
        ).addressing_key()

    # Master device-parameter arc.
    a1 = {"target_kind": "device_parameter", "master": True,
          "device_index": 2, "parameter_name": "Frequency"}
    assert perform_target_key(a1) == _handler_key(**a1)
    # Non-master track arc — `master` absent on the planner side must normalize
    # to the handler's explicit False (the bug the bool() normalization fixed).
    a2 = {"target_kind": "mixer_volume", "track_index": 3}
    assert perform_target_key(a2) == _handler_key(**a2)
    # Send arc (track + return).
    a3 = {"target_kind": "send_level", "track_index": 3, "return_index": 1}
    assert perform_target_key(a3) == _handler_key(**a3)
    # DEEP-RACK-ADDR: a NESTED device-parameter arc — device_path is part of the
    # identity on both sides, in the same hashable normalization.
    a4 = {"target_kind": "device_parameter", "track_index": 3,
          "device_index": 2, "parameter_name": "Volume",
          "device_path": [{"chain_index": 1, "device_position": 2}]}
    assert perform_target_key(a4) == _handler_key(**a4)
    # Two arcs sharing device_index but differing by device_path must NOT
    # collide (the whole point of putting device_path in the key).
    a5 = {**a4, "device_path": [{"chain_index": 2, "device_position": 1}]}
    assert perform_target_key(a4) != perform_target_key(a5)
