"""Tests for the chunk-4a push planner: plan_push_devices + device-link apply."""
from __future__ import annotations

import pytest

from songwright.db import init_db, mutations as M, queries as Q
from songwright.sync import push


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "pdev.db")
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
        conn, session_id=session, db_kind="track", db_id=track, ableton_index=5
    )
    return track


@pytest.fixture
def ret(conn, song):
    return M.create_return(conn, song_id=song, name="A-Reverb", position=1)


def _calls_by_tool(plan) -> dict[str, list]:
    out: dict[str, list] = {}
    for c in plan.calls:
        out.setdefault(c.tool, []).append(c)
    return out


# ---------- empty / unlinked cases ----------


def test_plan_push_devices_empty_song_warns(conn, song, session):
    plan = push.plan_push_devices(conn, song_id=song, session_id=session)
    assert plan.calls == []
    assert any("no devices" in n for n in plan.notes)


def test_plan_push_devices_skips_unlinked_track_with_warn(conn, song, session, track):
    cid = M.create_device_chain(conn, parent_track_id=track)
    M.create_device(conn, chain_id=cid, position=1, kind="Eq8", display_name="EQ")
    plan = push.plan_push_devices(conn, song_id=song, session_id=session)
    assert plan.calls == []
    assert any("not linked" in n for n in plan.notes)


def test_plan_push_devices_silent_for_track_without_chain(conn, song, session, linked_track):
    """A linked track with no devices doesn't warn — it's just nothing to push."""
    plan = push.plan_push_devices(conn, song_id=song, session_id=session)
    assert plan.calls == []
    assert plan.notes == []


# ---------- load_device emission for unlinked devices ----------


def test_plan_push_devices_emits_load_for_unlinked_device(
    conn, song, session, linked_track,
):
    cid = M.create_device_chain(conn, parent_track_id=linked_track)
    did = M.create_device(
        conn, chain_id=cid, position=1, kind="DrumGroupDevice",
        display_name="Late Nite Kit", preset_uri="query:Drums#FileId_5418",
    )
    plan = push.plan_push_devices(conn, song_id=song, session_id=session)
    by_tool = _calls_by_tool(plan)
    assert "load_device" in by_tool
    load = by_tool["load_device"][0]
    assert load.args == {
        "track_index": 5,
        "position": 1,
        "kind": "DrumGroupDevice",
        "preset_uri": "query:Drums#FileId_5418",
    }
    assert load.key == f"device:{did}"
    assert any("not linked" in n for n in plan.notes)


def test_plan_push_devices_skips_params_when_device_unlinked(
    conn, song, session, linked_track,
):
    cid = M.create_device_chain(conn, parent_track_id=linked_track)
    did = M.create_device(conn, chain_id=cid, position=1, kind="Eq8", display_name="EQ")
    M.set_device_parameter(
        conn, device_id=did, name="Freq",
        value_display="1.17 kHz", value_normalized=0.59,
    )
    plan = push.plan_push_devices(conn, song_id=song, session_id=session)
    by_tool = _calls_by_tool(plan)
    # Load emitted, but no set_device_parameter — device_index is unknown until apply.
    assert "load_device" in by_tool
    assert "set_device_parameter" not in by_tool


# ---------- set_device_parameter for linked devices ----------


def test_plan_push_devices_emits_params_for_linked_device(
    conn, song, session, linked_track,
):
    cid = M.create_device_chain(conn, parent_track_id=linked_track)
    did = M.create_device(conn, chain_id=cid, position=1, kind="Eq8", display_name="EQ")
    M.set_device_parameter(
        conn, device_id=did, name="Freq",
        value_display="1.17 kHz", value_normalized=0.59,
    )
    M.set_device_parameter(
        conn, device_id=did, name="Q",
        value_display="46.1", value_normalized=0.46,
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="device", db_id=did, ableton_index=2,
    )

    plan = push.plan_push_devices(conn, song_id=song, session_id=session)
    by_tool = _calls_by_tool(plan)
    assert "load_device" not in by_tool  # already linked
    calls = by_tool["set_device_parameter"]
    assert len(calls) == 2
    by_param = {c.args["parameter_name"]: c for c in calls}
    assert by_param["Freq"].args == {
        "track_index": 5, "device_index": 2,
        "parameter_name": "Freq", "value": pytest.approx(0.59),
    }
    assert by_param["Freq"].key == f"device_parameter:{did}:Freq"


def test_plan_push_devices_warns_for_enum_only_params(
    conn, song, session, linked_track,
):
    cid = M.create_device_chain(conn, parent_track_id=linked_track)
    did = M.create_device(conn, chain_id=cid, position=1, kind="Operator", display_name="Op")
    M.set_device_parameter(conn, device_id=did, name="Filter Type",
                           value_display="Lowpass")  # no normalized
    M.set_device_parameter(conn, device_id=did, name="Filter Freq",
                           value_display="12.0 kHz", value_normalized=0.93)
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="device", db_id=did, ableton_index=1,
    )

    plan = push.plan_push_devices(conn, song_id=song, session_id=session)
    by_tool = _calls_by_tool(plan)
    # Only the continuous param emits a call.
    assert len(by_tool["set_device_parameter"]) == 1
    assert by_tool["set_device_parameter"][0].args["parameter_name"] == "Filter Freq"
    # And the enum gets surfaced as a warn.
    assert any("enum-only" in n and "Filter Type" in n for n in plan.notes)


# ---------- returns ----------


def test_plan_push_devices_emits_return_specific_tools(
    conn, song, session, ret,
):
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="return", db_id=ret, ableton_index=1,
    )
    cid = M.create_device_chain(conn, parent_return_id=ret)
    did = M.create_device(conn, chain_id=cid, position=1, kind="Reverb", display_name="Reverb")
    # Unlinked device -> emits load_device_on_return.
    plan = push.plan_push_devices(conn, song_id=song, session_id=session)
    by_tool = _calls_by_tool(plan)
    assert "load_device_on_return" in by_tool
    load = by_tool["load_device_on_return"][0]
    assert load.args == {
        "return_index": 1, "position": 1, "kind": "Reverb", "preset_uri": None,
    }

    # Once linked, params use return_index, not track_index.
    M.set_device_parameter(conn, device_id=did, name="Decay",
                           value_display="2.5 s", value_normalized=0.6)
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="device", db_id=did, ableton_index=2,
    )
    plan = push.plan_push_devices(conn, song_id=song, session_id=session)
    by_tool = _calls_by_tool(plan)
    assert "set_return_device_parameter" in by_tool
    param_call = by_tool["set_return_device_parameter"][0]
    assert param_call.args == {
        "return_index": 1, "device_index": 2,
        "parameter_name": "Decay", "value": pytest.approx(0.6),
    }


# ---------- apply_push_results integration ----------


def test_apply_push_results_links_devices(conn, song, session, linked_track):
    cid = M.create_device_chain(conn, parent_track_id=linked_track)
    did = M.create_device(conn, chain_id=cid, position=1, kind="Eq8", display_name="EQ")

    push.apply_push_results(
        conn,
        [
            {"key": f"device:{did}", "ok": True, "tool": "load_device",
             "result": {"device_index": 3}},
        ],
        session_id=session,
    )
    assert Q.get_ableton_link(
        conn, session_id=session, db_kind="device", db_id=did
    ) == 3


def test_apply_push_results_accepts_device_parameter_as_ack(
    conn, song, session, linked_track,
):
    cid = M.create_device_chain(conn, parent_track_id=linked_track)
    did = M.create_device(conn, chain_id=cid, position=1, kind="Eq8", display_name="EQ")
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="device", db_id=did, ableton_index=2,
    )
    # No raise. No new link materialized — device_parameter is ack-only.
    push.apply_push_results(
        conn,
        [
            {"key": f"device_parameter:{did}:Freq", "ok": True,
             "tool": "set_device_parameter", "result": {}},
        ],
        session_id=session,
    )
    # Existing device + track links survive; nothing else added.
    links = Q.get_ableton_links_for_session(conn, session)
    kinds = sorted(l["db_kind"] for l in links)
    assert kinds == ["device", "track"]


# ---------- end-to-end: falling-walking-shaped fixture ----------


def test_plan_push_devices_handles_mixed_linked_unlinked(
    conn, song, session, linked_track, ret,
):
    """Snapshot-realistic mix: linked track with one linked device + one
    unlinked device, plus linked return with one unlinked device."""
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="return", db_id=ret, ableton_index=1,
    )
    cid = M.create_device_chain(conn, parent_track_id=linked_track)
    eq = M.create_device(conn, chain_id=cid, position=1, kind="Eq8", display_name="EQ")
    comp = M.create_device(conn, chain_id=cid, position=2, kind="Compressor2", display_name="Comp")
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="device", db_id=eq, ableton_index=1,
    )
    M.set_device_parameter(conn, device_id=eq, name="Freq",
                           value_display="1 kHz", value_normalized=0.5)

    rcid = M.create_device_chain(conn, parent_return_id=ret)
    M.create_device(conn, chain_id=rcid, position=1, kind="Reverb", display_name="Rev")

    plan = push.plan_push_devices(conn, song_id=song, session_id=session)
    by_tool = _calls_by_tool(plan)
    # EQ linked -> 1 set_device_parameter, no load. Comp unlinked -> 1 load_device.
    # Return reverb unlinked -> 1 load_device_on_return.
    assert len(by_tool.get("set_device_parameter", [])) == 1
    assert len(by_tool.get("load_device", [])) == 1
    assert by_tool["load_device"][0].args["kind"] == "Compressor2"
    assert len(by_tool.get("load_device_on_return", [])) == 1
