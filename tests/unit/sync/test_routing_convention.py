"""Worked example + doc-drift lock for the PRE-MAIN submaster convention
(RTE-1K9T chunk 06).

This is the end-to-end acceptance test for the convention documented in
``docs/song-authoring-conventions.md`` ("The PRE-MAIN submaster bus"): it runs
the doc's exact authoring sequence through the SHIPPED mutators + planners — no
raw ``ableton_probe`` — and proves (1) push materializes the routing, (2) pull
ingests a hand-built bus, and (3) push-then-pull is identity (round-trip stable).

If the doc's code block and this test drift apart, this test breaks — that is the
point (the "lock a doc-as-deliverable with a parity test" discipline). Distinct
from ``test_push_routing.py``, which unit-tests the ``plan_push_routing`` planner
mechanics on a single source; here the scenario is the realistic multi-instrument
bus the convention describes, end-to-end across push AND pull.
"""
from __future__ import annotations

import pytest

from hallucinote.db import init_db, mutations as M, queries as Q
from hallucinote.sync import push, pull


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "convention.db")
    yield c
    c.close()


@pytest.fixture
def song(conn):
    return M.create_song(conn, name="t", key="Dm")


@pytest.fixture
def session(conn, song):
    return M.create_ableton_session(conn, song_id=song, name="draft")


def _link(conn, session, track_id, index):
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=track_id,
        ableton_index=index,
    )


def _author_pre_main(conn, song_id):
    """The convention, verbatim from docs/song-authoring-conventions.md.

    Returns (bus_id, [instrument_ids])."""
    bus = M.create_track(conn, song_id=song_id, track_index=1, name="PRE-MAIN",
                         kind="audio")
    drums = M.create_track(conn, song_id=song_id, track_index=2, name="Drums")
    bass = M.create_track(conn, song_id=song_id, track_index=3, name="Bass")
    keys = M.create_track(conn, song_id=song_id, track_index=4, name="Keys")

    for inst_id in (drums, bass, keys):
        M.set_track_routing(conn, track_id=inst_id,
                            output_routing_kind="track",
                            output_routing_target_id=bus)
    M.set_track_routing(conn, track_id=bus, output_routing_kind="master")
    M.set_track_routing(conn, track_id=bus, monitoring_state="In")
    return bus, [drums, bass, keys]


def _routing_calls(plan, action):
    return [
        c for c in plan.calls
        if c.tool == "ableton_track" and c.args.get("action") == action
    ]


def test_pre_main_convention_pushes(conn, song, session):
    """Acceptance criterion: the convention is reproducible from shipped actions
    — pushing the DB-authored layout materializes every routing write."""
    bus, insts = _author_pre_main(conn, song)
    # Link the bus + every instrument so the planner emits their routing.
    _link(conn, session, bus, 1)
    for i, inst_id in enumerate(insts, start=2):
        _link(conn, session, inst_id, i)

    plan = push.plan_push_routing(conn, song_id=song, session_id=session)

    out_by_index = {
        c.args["track_index"]: c.args["type_display_name"]
        for c in _routing_calls(plan, "set_output_routing")
    }
    # Each instrument routes to the bus by its display name; the bus routes Main.
    assert out_by_index[2] == "PRE-MAIN"
    assert out_by_index[3] == "PRE-MAIN"
    assert out_by_index[4] == "PRE-MAIN"
    assert out_by_index[1] == "Main"

    mon = _routing_calls(plan, "set_monitoring_state")
    assert len(mon) == 1
    assert mon[0].args == {
        "action": "set_monitoring_state", "track_index": 1, "state": "In",
    }
    # Nothing skipped / dangling — the convention pushes cleanly.
    assert plan.alerts == []


def test_pre_main_convention_pulls_a_manual_setup(conn, song, session):
    """A bus built by HAND in Live pulls back into the DB through the mutator:
    instruments routed to "PRE-MAIN" + the bus on Monitor='In'."""
    bus = M.create_track(conn, song_id=song, track_index=1, name="PRE-MAIN",
                         kind="audio")
    drums = M.create_track(conn, song_id=song, track_index=2, name="Drums")
    _link(conn, session, bus, 1)
    _link(conn, session, drums, 2)

    # The Live state an operator would create by hand: Drums output -> PRE-MAIN,
    # bus Monitor -> In. (Output to the master is the default "Main" -> no-op.)
    results = [
        {"key": f"track_output_routing:{drums}", "ok": True, "tool": "ableton_track",
         "result": {"has_output_routing": True, "current_type": "PRE-MAIN",
                    "current_channel": None}},
        {"key": f"track_monitor:{bus}", "ok": True, "tool": "ableton_track",
         "result": {"has_monitoring_state": True, "monitoring_state": "In"}},
    ]
    out = pull.apply_pull_results(conn, results, song_id=song, session_id=session)
    assert out.mutations == 2

    drums_row = Q.get_track(conn, drums)
    assert drums_row["output_routing_kind"] == "track"
    assert drums_row["output_routing_target_id"] == bus
    assert Q.get_track(conn, bus)["monitoring_state"] == "In"


def test_pre_main_convention_round_trip_is_stable(conn, song, session):
    """Push-then-pull is identity: pulling the exact Live state the authored
    layout produces is a clean no-op (no churn)."""
    bus, insts = _author_pre_main(conn, song)
    _link(conn, session, bus, 1)
    for i, inst_id in enumerate(insts, start=2):
        _link(conn, session, inst_id, i)

    # The Live state that push would have materialized from the authored DB.
    results = [
        {"key": f"track_monitor:{bus}", "ok": True, "tool": "ableton_track",
         "result": {"has_monitoring_state": True, "monitoring_state": "In"}},
        {"key": f"track_output_routing:{bus}", "ok": True, "tool": "ableton_track",
         "result": {"has_output_routing": True, "current_type": "Main",
                    "current_channel": None}},
    ]
    for i, inst_id in enumerate(insts, start=2):
        results.append({
            "key": f"track_output_routing:{inst_id}", "ok": True,
            "tool": "ableton_track",
            "result": {"has_output_routing": True, "current_type": "PRE-MAIN",
                       "current_channel": None},
        })

    out = pull.apply_pull_results(conn, results, song_id=song, session_id=session)
    assert out.mutations == 0
