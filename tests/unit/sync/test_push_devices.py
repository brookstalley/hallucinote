"""Tests for the chunk-4a push planner: plan_push_devices + device-link apply."""
from __future__ import annotations

import pytest

from hallucinote.db import init_db, mutations as M, queries as Q
from hallucinote.sync import push


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
    """Group calls by tool name. Pre-Wave-M-4 this was the only key; with
    the unified tool collapse, callers usually want by (tool, action) —
    use _calls_by_action.
    """
    out: dict[str, list] = {}
    for c in plan.calls:
        out.setdefault(c.tool, []).append(c)
    return out


def _calls_by_action(plan) -> dict[str, list]:
    """Group calls by their 'action' arg for the unified-tool surface.
    Calls without an action key (legacy) end up under their tool name.
    """
    out: dict[str, list] = {}
    for c in plan.calls:
        key = c.args.get("action", c.tool)
        out.setdefault(key, []).append(c)
    return out


# ---------- empty / unlinked cases ----------


def test_plan_push_devices_empty_song_warns(conn, song, session):
    plan = push.plan_push_devices(conn, song_id=song, session_id=session)
    assert plan.calls == []
    assert any("no devices" in n for n in plan.notes)


def test_plan_push_devices_skips_unlinked_track_with_warn(conn, song, session, track):
    cid = M.create_device_chain(conn, parent_track_id=track)
    M.create_device(conn, chain_id=cid, position=1, kind="EQ Eight", display_name="EQ")
    plan = push.plan_push_devices(conn, song_id=song, session_id=session)
    assert plan.calls == []
    assert any("not linked" in n for n in plan.notes)


def test_plan_push_devices_silent_for_track_without_chain(conn, song, session, linked_track):
    """A linked track with no devices doesn't warn — it's just nothing to push."""
    plan = push.plan_push_devices(conn, song_id=song, session_id=session)
    assert plan.calls == []
    assert plan.notes == []


# ---------- placeholder devices (W13-B v0.9.0) ----------


def test_plan_push_devices_skips_placeholder_with_warn(
    conn, song, session, linked_track,
):
    """Placeholder devices represent author-intentional empty slots.
    Push leaves the chain position empty + warns so the agent surfaces
    the gap without trying (and failing) to load anything.
    """
    cid = M.create_device_chain(conn, parent_track_id=linked_track)
    M.create_device(
        conn, chain_id=cid, position=1, kind="placeholder",
        display_name="future warm pad",
    )
    plan = push.plan_push_devices(conn, song_id=song, session_id=session)
    assert plan.calls == []  # no load, no set_parameter
    assert any(
        "placeholder" in n and "future warm pad" in n for n in plan.notes
    )


# ---------- load_device emission for unlinked devices ----------


def test_plan_push_devices_emits_load_for_unlinked_device(
    conn, song, session, linked_track,
):
    cid = M.create_device_chain(conn, parent_track_id=linked_track)
    did = M.create_device(
        conn, chain_id=cid, position=1, kind="Drum Rack",
        display_name="Late Nite Kit", preset_uri="query:Drums#FileId_5418",
    )
    plan = push.plan_push_devices(conn, song_id=song, session_id=session)
    by_action = _calls_by_action(plan)
    # Wave M-4: unified ableton_device(action='load') replaces load_device.
    assert "load" in by_action
    load = by_action["load"][0]
    assert load.tool == "ableton_device"
    assert load.args["track_index"] == 5
    # Live 12.4 has no public reorder API — planner does NOT emit position.
    assert "position" not in load.args
    assert load.args["kind"] == "Drum Rack"
    assert load.args["preset_uri"] == "query:Drums#FileId_5418"
    assert load.key == f"device:{did}"
    assert any("not linked" in n for n in plan.notes)


def test_plan_push_devices_threads_browser_path_alongside_preset_uri(
    conn, song, session, linked_track,
):
    """E3 (W13-A v1.0): when a device has both preset_uri and
    browser_path captured, the planner emits both — preset_uri is the
    fast path, browser_path is the fallback identity for cross-machine
    FileId mismatches."""
    cid = M.create_device_chain(conn, parent_track_id=linked_track)
    M.create_device(
        conn, chain_id=cid, position=1, kind="Massive X",
        display_name="FatBass",
        preset_uri="query:Plugin#FileId_AUTHOR_MACHINE",
        browser_path=["plug-ins", "Native Instruments", "Massive X", "FatBass"],
    )
    plan = push.plan_push_devices(conn, song_id=song, session_id=session)
    load = next(
        c for c in plan.calls
        if c.tool == "ableton_device" and c.args.get("action") == "load"
    )
    assert load.args["preset_uri"] == "query:Plugin#FileId_AUTHOR_MACHINE"
    assert load.args["browser_path"] == [
        "plug-ins", "Native Instruments", "Massive X", "FatBass",
    ]


def test_plan_push_devices_browser_path_omitted_when_using_preset_query(
    conn, song, session, linked_track,
):
    """When the snapshot prefers preset_query (portable form), the
    planner does not also emit browser_path — preset_query is itself
    the path-scoped selector, so layering both would be redundant."""
    cid = M.create_device_chain(conn, parent_track_id=linked_track)
    M.create_device(
        conn, chain_id=cid, position=1, kind="Drum Rack",
        display_name="Kit",
        preset_query={"root": "drums", "pattern": "909"},
    )
    plan = push.plan_push_devices(conn, song_id=song, session_id=session)
    load = next(
        c for c in plan.calls
        if c.tool == "ableton_device" and c.args.get("action") == "load"
    )
    assert "preset_query" in load.args
    assert "browser_path" not in load.args


def test_plan_push_devices_preset_uri_only_no_browser_path(
    conn, song, session, linked_track,
):
    """Pre-E3 snapshots have preset_uri but no browser_path — the
    planner emits just preset_uri, no fallback identity surface. Loaders
    on a different machine where the FileId doesn't resolve will fail
    loudly rather than silently picking a same-display-name plugin from
    a different vendor."""
    cid = M.create_device_chain(conn, parent_track_id=linked_track)
    M.create_device(
        conn, chain_id=cid, position=1, kind="Drum Rack",
        display_name="Late Nite", preset_uri="query:Drums#FileId_X",
    )
    plan = push.plan_push_devices(conn, song_id=song, session_id=session)
    load = next(
        c for c in plan.calls
        if c.tool == "ableton_device" and c.args.get("action") == "load"
    )
    assert load.args["preset_uri"] == "query:Drums#FileId_X"
    assert "browser_path" not in load.args


def test_plan_push_devices_threads_preset_query_to_load(
    conn, song, session, linked_track,
):
    """Sweep B: stored preset_query (JSON) is parsed back into a dict and
    threaded to ableton_device(action='load', preset_query={...}). The MCP
    handler resolves on the consumer's machine."""
    cid = M.create_device_chain(conn, parent_track_id=linked_track)
    did = M.create_device(
        conn, chain_id=cid, position=1, kind="Drum Rack",
        display_name="Some 909 Kit",
        preset_query={"root": "drums", "pattern": "909", "mode": "substring"},
    )
    plan = push.plan_push_devices(conn, song_id=song, session_id=session)
    load = next(
        c for c in plan.calls
        if c.tool == "ableton_device" and c.args.get("action") == "load"
        and c.key == f"device:{did}"
    )
    assert "preset_uri" not in load.args
    assert load.args["preset_query"] == {
        "root": "drums", "pattern": "909", "mode": "substring",
    }


def test_plan_push_devices_preset_query_precedence_when_only_query_set(
    conn, song, session, linked_track,
):
    """When only preset_query is set (preset_uri is None), threading is
    straightforward — preset_query lands in load_args."""
    cid = M.create_device_chain(conn, parent_track_id=linked_track)
    M.create_device(
        conn, chain_id=cid, position=1, kind="Drum Rack",
        display_name="Kit", preset_query={"root": "drums", "pattern": "x"},
    )
    plan = push.plan_push_devices(conn, song_id=song, session_id=session)
    load = next(
        c for c in plan.calls
        if c.tool == "ableton_device" and c.args.get("action") == "load"
    )
    assert load.args.get("preset_query") == {"root": "drums", "pattern": "x"}
    assert "preset_uri" not in load.args


def test_plan_push_devices_malformed_preset_query_fallback_threads_browser_path(
    conn, song, session, linked_track,
):
    """E3 follow-up: when preset_query is malformed JSON, the planner
    falls back to preset_uri. browser_path must thread on that branch too
    (was asymmetric pre-fix — only the preset_uri-primary branch threaded
    it). Otherwise the cross-machine FileId fallback identity is silently
    dropped whenever preset_query happens to be unparseable.
    """
    cid = M.create_device_chain(conn, parent_track_id=linked_track)
    did = M.create_device(
        conn, chain_id=cid, position=1, kind="Massive X",
        display_name="FatBass",
        preset_uri="query:Plugin#FileId_AUTHOR",
        browser_path=["plug-ins", "Native Instruments", "Massive X", "FatBass"],
    )
    # The mutator always writes well-formed JSON. Inject malformed JSON
    # directly to exercise the fallback branch — the planner has to be
    # resilient to a corrupted preset_query column regardless of how it
    # got there.
    conn.execute(
        "UPDATE devices SET preset_query = ? WHERE id = ?",
        ("{not valid json", did),
    )
    plan = push.plan_push_devices(conn, song_id=song, session_id=session)
    load = next(
        c for c in plan.calls
        if c.tool == "ableton_device" and c.args.get("action") == "load"
    )
    assert load.args["preset_uri"] == "query:Plugin#FileId_AUTHOR"
    assert load.args["browser_path"] == [
        "plug-ins", "Native Instruments", "Massive X", "FatBass",
    ]
    assert any(
        "preset_query is not valid JSON" in n for n in plan.notes
    )


def test_plan_push_devices_skips_params_when_device_unlinked(
    conn, song, session, linked_track,
):
    cid = M.create_device_chain(conn, parent_track_id=linked_track)
    did = M.create_device(conn, chain_id=cid, position=1, kind="EQ Eight", display_name="EQ")
    M.set_device_parameter(
        conn, device_id=did, name="Freq",
        value_display="1.17 kHz", value_normalized=0.59,
    )
    plan = push.plan_push_devices(conn, song_id=song, session_id=session)
    by_action = _calls_by_action(plan)
    # Load emitted, but no set_parameter — device_index is unknown until apply.
    assert "load" in by_action
    assert "set_parameter" not in by_action


# ---------- set_parameter for linked devices ----------


def test_plan_push_devices_emits_params_for_linked_device(
    conn, song, session, linked_track,
):
    cid = M.create_device_chain(conn, parent_track_id=linked_track)
    did = M.create_device(conn, chain_id=cid, position=1, kind="EQ Eight", display_name="EQ")
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
    by_action = _calls_by_action(plan)
    assert "load" not in by_action  # already linked
    calls = by_action["set_parameter"]
    assert len(calls) == 2
    by_param = {c.args["parameter_name"]: c for c in calls}
    freq = by_param["Freq"]
    assert freq.tool == "ableton_device"
    assert freq.args["track_index"] == 5
    assert freq.args["device_index"] == 2
    assert freq.args["parameter_name"] == "Freq"
    # value is stringified on the wire (schema uniformity continuous + enum)
    assert float(freq.args["value"]) == pytest.approx(0.59)
    assert freq.args["value_type"] == "continuous"
    assert freq.key == f"device_parameter:{did}:Freq"


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
    by_action = _calls_by_action(plan)
    # Only the continuous param emits a call.
    assert len(by_action["set_parameter"]) == 1
    assert by_action["set_parameter"][0].args["parameter_name"] == "Filter Freq"
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
    # Unlinked device -> emits ableton_device(action='load', return_index=...).
    plan = push.plan_push_devices(conn, song_id=song, session_id=session)
    by_action = _calls_by_action(plan)
    assert "load" in by_action
    load = by_action["load"][0]
    assert load.tool == "ableton_device"
    assert load.args["return_index"] == 1
    # No position emission — Live 12.4 cannot reorder, planner relies on
    # chain-order push to match DB position.
    assert "position" not in load.args
    assert load.args["kind"] == "Reverb"
    # preset_uri is omitted when None — keeps the wire shape minimal.
    assert "preset_uri" not in load.args

    # Once linked, params use return_index, not track_index.
    M.set_device_parameter(conn, device_id=did, name="Decay",
                           value_display="2.5 s", value_normalized=0.6)
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="device", db_id=did, ableton_index=2,
    )
    plan = push.plan_push_devices(conn, song_id=song, session_id=session)
    by_action = _calls_by_action(plan)
    assert "set_parameter" in by_action
    param_call = by_action["set_parameter"][0]
    assert param_call.tool == "ableton_device"
    assert param_call.args["return_index"] == 1
    assert param_call.args["device_index"] == 2
    assert param_call.args["parameter_name"] == "Decay"
    assert float(param_call.args["value"]) == pytest.approx(0.6)


# ---------- apply_push_results integration ----------


def test_apply_push_results_links_devices(conn, song, session, linked_track):
    cid = M.create_device_chain(conn, parent_track_id=linked_track)
    did = M.create_device(conn, chain_id=cid, position=1, kind="EQ Eight", display_name="EQ")

    push.apply_push_results(
        conn,
        [
            {"key": f"device:{did}", "ok": True, "tool": "ableton_device",
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
    did = M.create_device(conn, chain_id=cid, position=1, kind="EQ Eight", display_name="EQ")
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="device", db_id=did, ableton_index=2,
    )
    # No raise. No new link materialized — device_parameter is ack-only.
    push.apply_push_results(
        conn,
        [
            {"key": f"device_parameter:{did}:Freq", "ok": True,
             "tool": "ableton_device", "result": {}},
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
    eq = M.create_device(conn, chain_id=cid, position=1, kind="EQ Eight", display_name="EQ")
    comp = M.create_device(conn, chain_id=cid, position=2, kind="Compressor", display_name="Comp")
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="device", db_id=eq, ableton_index=1,
    )
    M.set_device_parameter(conn, device_id=eq, name="Freq",
                           value_display="1 kHz", value_normalized=0.5)

    rcid = M.create_device_chain(conn, parent_return_id=ret)
    M.create_device(conn, chain_id=rcid, position=1, kind="Reverb", display_name="Rev")

    plan = push.plan_push_devices(conn, song_id=song, session_id=session)
    by_action = _calls_by_action(plan)
    # EQ linked -> 1 set_parameter call; Comp unlinked -> 1 load (track-side);
    # Return reverb unlinked -> 1 load (return-side). All three under the
    # unified ableton_device tool.
    assert len(by_action.get("set_parameter", [])) == 1
    loads = by_action.get("load", [])
    assert len(loads) == 2  # one for track-side Comp, one for return-side Reverb
    by_target = {
        ("track" if "track_index" in c.args else "return"): c for c in loads
    }
    assert by_target["track"].args["kind"] == "Compressor"
    assert by_target["return"].args["kind"] == "Reverb"
