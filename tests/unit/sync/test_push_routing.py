"""Tests for the RTE-1K9T routing push planner — ``plan_push_routing``.

Covers the plan level (which ``ableton_track`` calls get emitted for each
routing kind, channel pass-through, the PRE-MAIN submaster scenario, the
unlinked-track skip, and the dangling-target alert), the apply path (the three
routing ack keys round-trip through ``apply_push_results`` without raising or
writing a link), and the orchestration wiring (the ``routing`` phase in
``plan_push_song`` actually invokes this planner).

Platform-level planner tests use synthetic fixtures (no song data) per the
test-levels contract in ``.prawduct/artifacts/boundary-patterns.md``.
"""
from __future__ import annotations

import pytest

from hallucinote.db import init_db, mutations as M, queries as Q
from hallucinote.sync import push


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "prouting.db")
    yield c
    c.close()


@pytest.fixture
def song(conn):
    return M.create_song(conn, name="t", key="Dm")


@pytest.fixture
def session(conn, song):
    return M.create_ableton_session(conn, song_id=song, name="draft")


def _routing_calls(plan, action):
    """Return the ``ableton_track`` calls in ``plan`` matching a routing action."""
    return [
        c for c in plan.calls
        if c.tool == "ableton_track" and c.args.get("action") == action
    ]


def _link(conn, session, track_id, index):
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=track_id,
        ableton_index=index,
    )


# ---------------------------------------------------------------------------
# Empty / no-routing cases
# ---------------------------------------------------------------------------


def test_plan_push_routing_no_tracks_warns(conn, song, session):
    plan = push.plan_push_routing(conn, song_id=song, session_id=session)
    assert plan.calls == []
    assert any("no tracks to route" in n for n in plan.notes)


def test_plan_push_routing_track_without_routing_emits_nothing(conn, song, session):
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    _link(conn, session, tid, 5)
    plan = push.plan_push_routing(conn, song_id=song, session_id=session)
    assert plan.calls == []


def test_plan_push_routing_skips_unlinked_track(conn, song, session):
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    M.set_track_routing(conn, track_id=tid, output_routing_kind="master")
    plan = push.plan_push_routing(conn, song_id=song, session_id=session)
    assert plan.calls == []
    assert any("not linked" in n for n in plan.notes)


def test_plan_push_routing_skips_master_track(conn, song, session):
    """The master strip has no Live-side routing surface and no track_index —
    even if a master row somehow carried routing columns, the planner skips it."""
    M.create_track(conn, song_id=song, track_index=0, name="Master", kind="master")
    plan = push.plan_push_routing(conn, song_id=song, session_id=session)
    assert plan.calls == []


# ---------------------------------------------------------------------------
# Output routing — every kind resolves to the right display_name
# ---------------------------------------------------------------------------


def test_plan_push_routing_output_to_master(conn, song, session):
    tid = M.create_track(conn, song_id=song, track_index=1, name="Bus", kind="audio")
    M.set_track_routing(conn, track_id=tid, output_routing_kind="master")
    _link(conn, session, tid, 5)
    plan = push.plan_push_routing(conn, song_id=song, session_id=session)
    calls = _routing_calls(plan, "set_output_routing")
    assert len(calls) == 1
    assert calls[0].args == {
        "action": "set_output_routing",
        "track_index": 5,
        "type_display_name": "Main",
    }
    assert calls[0].key == f"track_output_routing:{tid}"


def test_plan_push_routing_output_sends_only(conn, song, session):
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    M.set_track_routing(conn, track_id=tid, output_routing_kind="sends_only")
    _link(conn, session, tid, 5)
    plan = push.plan_push_routing(conn, song_id=song, session_id=session)
    calls = _routing_calls(plan, "set_output_routing")
    assert len(calls) == 1
    assert calls[0].args["type_display_name"] == "Sends Only"


def test_plan_push_routing_output_ext_out_with_channel(conn, song, session):
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums", kind="audio")
    M.set_track_routing(
        conn, track_id=tid,
        output_routing_kind="ext_out", output_routing_channel="3/4",
    )
    _link(conn, session, tid, 5)
    plan = push.plan_push_routing(conn, song_id=song, session_id=session)
    calls = _routing_calls(plan, "set_output_routing")
    assert len(calls) == 1
    assert calls[0].args == {
        "action": "set_output_routing",
        "track_index": 5,
        "type_display_name": "Ext. Out",
        "channel_display_name": "3/4",
    }


def test_plan_push_routing_output_to_track_resolves_target_name(conn, song, session):
    """kind='track' resolves the FK to the target track's own name — the
    reference survives renames; push materializes it to the display_name."""
    bus = M.create_track(conn, song_id=song, track_index=2, name="PRE-MAIN", kind="audio")
    src = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    M.set_track_routing(
        conn, track_id=src,
        output_routing_kind="track", output_routing_target_id=bus,
    )
    _link(conn, session, src, 5)
    _link(conn, session, bus, 6)
    plan = push.plan_push_routing(conn, song_id=song, session_id=session)
    src_calls = [
        c for c in _routing_calls(plan, "set_output_routing")
        if c.args["track_index"] == 5
    ]
    assert len(src_calls) == 1
    assert src_calls[0].args["type_display_name"] == "PRE-MAIN"


# ---------------------------------------------------------------------------
# Input routing + monitor
# ---------------------------------------------------------------------------


def test_plan_push_routing_input_kinds(conn, song, session):
    for idx, (kind, expected) in enumerate(
        (("ext_in", "Ext. In"), ("no_input", "No Input"), ("resampling", "Resampling")),
        start=1,
    ):
        tid = M.create_track(conn, song_id=song, track_index=idx, name=f"T{idx}", kind="audio")
        M.set_track_routing(conn, track_id=tid, input_routing_kind=kind)
        _link(conn, session, tid, idx)
        plan = push.plan_push_routing(conn, song_id=song, session_id=session)
        calls = [
            c for c in _routing_calls(plan, "set_input_routing")
            if c.args["track_index"] == idx
        ]
        assert len(calls) == 1, f"input kind {kind!r}"
        assert calls[0].args["type_display_name"] == expected
        assert calls[0].key == f"track_input_routing:{tid}"


def test_plan_push_routing_input_to_track(conn, song, session):
    src = M.create_track(conn, song_id=song, track_index=1, name="Source", kind="audio")
    sink = M.create_track(conn, song_id=song, track_index=2, name="Sink", kind="audio")
    M.set_track_routing(
        conn, track_id=sink,
        input_routing_kind="track", input_routing_target_id=src,
    )
    _link(conn, session, src, 5)
    _link(conn, session, sink, 6)
    plan = push.plan_push_routing(conn, song_id=song, session_id=session)
    calls = [
        c for c in _routing_calls(plan, "set_input_routing")
        if c.args["track_index"] == 6
    ]
    assert len(calls) == 1
    assert calls[0].args["type_display_name"] == "Source"


def test_plan_push_routing_monitor_state(conn, song, session):
    tid = M.create_track(conn, song_id=song, track_index=1, name="Bus", kind="audio")
    M.set_track_routing(conn, track_id=tid, monitoring_state="In")
    _link(conn, session, tid, 5)
    plan = push.plan_push_routing(conn, song_id=song, session_id=session)
    calls = _routing_calls(plan, "set_monitoring_state")
    assert len(calls) == 1
    assert calls[0].args == {
        "action": "set_monitoring_state",
        "track_index": 5,
        "state": "In",
    }
    assert calls[0].key == f"track_monitor:{tid}"


# ---------------------------------------------------------------------------
# Dangling target (D6): kind='track', target_id=NULL after the target's deletion
# ---------------------------------------------------------------------------


def test_plan_push_routing_dangling_target_alerts_and_skips_direction(
    conn, song, session
):
    """ON DELETE SET NULL leaves (kind='track', target_id=NULL) when a route
    target is deleted. Push treats it as 'target gone': alert + skip that
    direction. An unrelated monitor on the same track still pushes."""
    bus = M.create_track(conn, song_id=song, track_index=2, name="PRE-MAIN", kind="audio")
    src = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    M.set_track_routing(
        conn, track_id=src,
        output_routing_kind="track", output_routing_target_id=bus,
    )
    M.set_track_routing(conn, track_id=src, monitoring_state="In")
    _link(conn, session, src, 5)
    # Delete the target bus → FK cascades target_id to NULL (kind stays 'track').
    M._delete_track(conn, track_id=bus)
    assert Q.get_track(conn, src)["output_routing_target_id"] is None

    plan = push.plan_push_routing(conn, song_id=song, session_id=session)
    # The dangling output direction is NOT pushed...
    assert _routing_calls(plan, "set_output_routing") == []
    assert any("no longer exists" in a for a in plan.alerts)
    # ...but the unrelated monitor state still emits (per-direction skip).
    assert len(_routing_calls(plan, "set_monitoring_state")) == 1


# ---------------------------------------------------------------------------
# The PRE-MAIN submaster scenario (acceptance criterion) + idempotency
# ---------------------------------------------------------------------------


def _author_pre_main(conn, song, session):
    """Author + link the canonical PRE-MAIN layout: Drums → bus, bus → master,
    bus Monitor='In'. Returns (drums_id, bus_id)."""
    bus = M.create_track(conn, song_id=song, track_index=2, name="PRE-MAIN", kind="audio")
    drums = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    M.set_track_routing(
        conn, track_id=drums,
        output_routing_kind="track", output_routing_target_id=bus,
    )
    M.set_track_routing(conn, track_id=bus, output_routing_kind="master")
    M.set_track_routing(conn, track_id=bus, monitoring_state="In")
    _link(conn, session, drums, 5)
    _link(conn, session, bus, 6)
    return drums, bus


def test_plan_push_routing_pre_main_submaster(conn, song, session):
    """Acceptance criterion: a DB-authored PRE-MAIN layout materializes as the
    three routing writes (Drums output → 'PRE-MAIN', bus output → 'Main', bus
    Monitor → 'In')."""
    _author_pre_main(conn, song, session)
    plan = push.plan_push_routing(conn, song_id=song, session_id=session)

    out_calls = {c.args["track_index"]: c for c in _routing_calls(plan, "set_output_routing")}
    assert out_calls[5].args["type_display_name"] == "PRE-MAIN"   # Drums → bus
    assert out_calls[6].args["type_display_name"] == "Main"       # bus → master

    mon_calls = _routing_calls(plan, "set_monitoring_state")
    assert len(mon_calls) == 1
    assert mon_calls[0].args == {
        "action": "set_monitoring_state",
        "track_index": 6,
        "state": "In",
    }
    assert plan.alerts == []


def test_plan_push_routing_re_push_re_emits_identical_calls(conn, song, session):
    """'Re-push is a no-op' holds at the EFFECT level (D7): a routing set is an
    idempotent LOM write, like the mix/devices set_property calls — the planner
    re-emits the same calls (it never reads Live state to gate), and re-setting
    the same route changes nothing in Live."""
    _author_pre_main(conn, song, session)
    first = push.plan_push_routing(conn, song_id=song, session_id=session)
    second = push.plan_push_routing(conn, song_id=song, session_id=session)
    assert [(c.tool, c.args, c.key) for c in first.calls] == \
           [(c.tool, c.args, c.key) for c in second.calls]


# ---------------------------------------------------------------------------
# Apply path (execute-side): routing keys are ack-only
# ---------------------------------------------------------------------------


def test_apply_push_results_accepts_routing_acks(conn, song, session):
    """The three routing keys are ack-only — ``apply_push_results`` accepts them
    without raising and writes no ``ableton_links`` binding (the routing state
    already lives in the DB; the push originated from it)."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Bus", kind="audio")
    _link(conn, session, tid, 5)
    push.apply_push_results(
        conn,
        [
            {"key": f"track_output_routing:{tid}", "ok": True,
             "tool": "ableton_track", "result": {}},
            {"key": f"track_input_routing:{tid}", "ok": True,
             "tool": "ableton_track", "result": {}},
            {"key": f"track_monitor:{tid}", "ok": True,
             "tool": "ableton_track", "result": {}},
        ],
        session_id=session,
    )
    # Only the pre-existing track link survives — no routing binding written.
    links = Q.get_ableton_links_for_session(conn, session)
    assert len(links) == 1
    assert links[0]["db_kind"] == "track"


# ---------------------------------------------------------------------------
# Orchestration wiring: the routing phase invokes this planner
# ---------------------------------------------------------------------------


def test_routing_phase_in_plan_push_song_emits_routing_calls(conn, song, session):
    """The ``routing`` phase of the master orchestrator runs ``plan_push_routing``
    against current DB state — wiring it end-to-end through ``plan_push_song``."""
    _author_pre_main(conn, song, session)
    phases = push.plan_push_song(conn, song_id=song, session_id=session)
    routing_phase = next(p for p in phases if p.name == "routing")
    plan = routing_phase.plan_fn()
    assert len(_routing_calls(plan, "set_output_routing")) == 2
    assert len(_routing_calls(plan, "set_monitoring_state")) == 1
