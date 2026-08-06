"""Tests for the chunk-4a push planner: plan_push_devices + device-link apply."""
from __future__ import annotations

import pytest

from hallucinote.capture import SNAPSHOT_SCHEMA_VERSION, replay_capture
from hallucinote.db import init_db, mutations as M, queries as Q
from hallucinote.sync import push
from hallucinote.sync.push._core import build_node_addr


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
    assert load.args["node"] == build_node_addr({"track_index": 5}, terminal="track")
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


def test_plan_push_devices_emits_standalone_browser_path_for_preset_file(
    conn, song, session, linked_track,
):
    """SYN-RACK-PRESET-RELINK: a rack-preset device captured with browser_path
    ONLY (no preset_uri/preset_query — the common /song-snapshot case, since
    capture can't probe preset_uri) must emit browser_path as a STANDALONE load
    selector when its leaf is a preset file (.adg/.adv). Before this the planner
    emitted kind only, so the rack loaded empty (0 chains) and every nested
    param write failed."""
    cid = M.create_device_chain(conn, parent_track_id=linked_track)
    M.create_device(
        conn, chain_id=cid, position=1, kind="Drum Rack",
        display_name="AG Techno Kit",
        browser_path=["drums", "AG Techno Kit.adg"],
    )
    plan = push.plan_push_devices(conn, song_id=song, session_id=session)
    load = next(
        c for c in plan.calls
        if c.tool == "ableton_device" and c.args.get("action") == "load"
    )
    assert "preset_uri" not in load.args
    assert "preset_query" not in load.args
    assert load.args["browser_path"] == ["drums", "AG Techno Kit.adg"]


def test_plan_push_devices_standalone_browser_path_survives_corrupt_preset_query(
    conn, song, session, linked_track,
):
    """Resilience: if a device's stored preset_query is corrupt JSON (can only
    happen via DB corruption — the mutator normalizes) and there's no
    preset_uri, the planner must still fall back to a standalone preset-file
    browser_path rather than loading an empty rack. Closes the elif-chain gap
    the Critic flagged."""
    cid = M.create_device_chain(conn, parent_track_id=linked_track)
    did = M.create_device(
        conn, chain_id=cid, position=1, kind="Drum Rack",
        display_name="AG Techno Kit",
        browser_path=["drums", "AG Techno Kit.adg"],
    )
    # Corrupt the preset_query column directly (the mutator would reject this).
    conn.execute(
        "UPDATE devices SET preset_query = ? WHERE id = ?", ("{not json", did),
    )
    plan = push.plan_push_devices(conn, song_id=song, session_id=session)
    load = next(
        c for c in plan.calls
        if c.tool == "ableton_device" and c.args.get("action") == "load"
    )
    assert "preset_query" not in load.args
    assert "preset_uri" not in load.args
    assert load.args["browser_path"] == ["drums", "AG Techno Kit.adg"]
    assert any("not valid JSON" in n for n in plan.notes)


def test_plan_push_devices_no_standalone_browser_path_for_builtin_device(
    conn, song, session, linked_track,
):
    """The standalone emission is preset-FILE-only. A built-in device captured
    with a non-preset browser_path (leaf is a class node, no .adg/.adv) and no
    preset_uri stays kind-only — emitting browser_path standalone would make the
    load handler refuse it (it's not a standalone selector for built-ins)."""
    cid = M.create_device_chain(conn, parent_track_id=linked_track)
    M.create_device(
        conn, chain_id=cid, position=1, kind="Operator",
        display_name="Operator",
        browser_path=["instruments", "Operator"],
    )
    plan = push.plan_push_devices(conn, song_id=song, session_id=session)
    load = next(
        c for c in plan.calls
        if c.tool == "ableton_device" and c.args.get("action") == "load"
    )
    assert load.args["kind"] == "Operator"
    assert "browser_path" not in load.args
    assert "preset_uri" not in load.args


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
    assert freq.args["node"] == build_node_addr(
        {"track_index": 5}, device_index=2,
    )
    assert freq.args["parameter_name"] == "Freq"
    # SYN-9F2L: the display value is the preferred wire form — the handler
    # inverts the param's own display curve, which is exact for center-zero
    # params where a naive normalized fraction dials the wrong direction.
    assert freq.args["value_display"] == "1.17 kHz"
    assert "value" not in freq.args
    assert freq.args["value_type"] == "continuous"
    assert freq.key == f"device_parameter:{did}:Freq"


# ---------- DEEP-RACK-ADDR: nested-device param durability ----------


def test_plan_push_devices_emits_nested_params_with_device_path(
    conn, song, session, linked_track,
):
    """A dialed param on a device nested ONE level inside a linked rack is
    re-emitted on push as set_parameter + device_path (relative to the rack's
    linked Live index). The nested device is NOT loaded — it arrives with the
    rack preset — so no load call is emitted for it."""
    top_chain = M.create_device_chain(conn, parent_track_id=linked_track)
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
        display_name="Guitar Dead Notes",
    )
    M.set_device_parameter(
        conn, device_id=nested, name="Volume",
        value_display="-6 dB", value_normalized=0.5,
    )

    plan = push.plan_push_devices(conn, song_id=song, session_id=session)
    by_action = _calls_by_action(plan)
    # Nested device is never loaded — it comes with the rack preset.
    assert "load" not in by_action
    calls = by_action["set_parameter"]
    assert len(calls) == 1  # only the nested Volume (the rack itself has no params)
    c = calls[0]
    # the TOP-LEVEL rack's Live index (5/2) + the nested device's path.
    assert c.args["node"] == build_node_addr(
        {"track_index": 5}, device_index=2,
        device_path=[{"chain_index": 1, "device_position": 1}],
    )
    assert c.args["parameter_name"] == "Volume"
    assert c.args["value_display"] == "-6 dB"
    assert c.key == f"device_parameter:{nested}:Volume"


def test_plan_push_devices_top_level_param_has_no_device_path(
    conn, song, session, linked_track,
):
    """Lock-test: a top-level device's set_parameter carries NO device_path key
    (the wire shape is unchanged from before nesting) — only nested params get
    one."""
    cid = M.create_device_chain(conn, parent_track_id=linked_track)
    did = M.create_device(
        conn, chain_id=cid, position=1, kind="EQ Eight", display_name="EQ",
    )
    M.set_device_parameter(
        conn, device_id=did, name="Freq",
        value_display="1 kHz", value_normalized=0.5,
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="device", db_id=did, ableton_index=2,
    )
    plan = push.plan_push_devices(conn, song_id=song, session_id=session)
    call = _calls_by_action(plan)["set_parameter"][0]
    assert "device_path" not in call.args


def test_capture_replay_push_roundtrip_depth2_nested_param(conn):
    """The durability regression, end to end (the swell guitar case): a depth-2
    nested dialed param captured into a snapshot replays into the DB and is
    re-emitted on push as set_parameter + a depth-2 device_path — so a deep
    by-ear fix survives a build.py rebuild instead of being silently dropped."""
    snapshot = {
        "snapshot_version": SNAPSHOT_SCHEMA_VERSION,
        "song": {}, "returns": [],
        "tracks": [{
            "index": 1, "name": "Guitar", "type": "midi",
            "devices": [{
                "index": 1, "name": "Guitar-Dual Amped Heavy",
                "class": "Instrument Rack",
                "chains": [{"chain_index": 1, "name": "Guitar", "devices": [{
                    "index": 1, "name": "Guitar Dead Notes",
                    "class": "Instrument Rack",
                    "chains": [{"chain_index": 1, "devices": [{
                        "index": 1, "name": "Deep Synth", "class": "Operator",
                        "params_dialed": {
                            "Volume": {"value": "-4 dB", "normalized": 0.6},
                        },
                    }]}],
                }]}],
            }],
        }],
    }
    song_id = replay_capture(conn, snapshot, song_name="rt")
    session = M.create_ableton_session(conn, song_id=song_id, name="draft")
    track = next(
        t for t in Q.get_tracks_for_song(conn, song_id) if t["name"] == "Guitar"
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=track["id"],
        ableton_index=3,
    )
    top_rack = Q.get_devices_for_track(conn, track["id"])[0]
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="device", db_id=top_rack["id"],
        ableton_index=1,
    )
    plan = push.plan_push_devices(conn, song_id=song_id, session_id=session)
    sets = [c for c in plan.calls if c.args.get("action") == "set_parameter"]
    assert len(sets) == 1  # only the deep Operator's Volume
    c = sets[0]
    assert c.args["node"] == build_node_addr(
        {"track_index": 3}, device_index=1,
        device_path=[
            {"chain_index": 1, "device_position": 1},
            {"chain_index": 1, "device_position": 1},
        ],
    )
    assert c.args["parameter_name"] == "Volume"
    assert c.args["value_display"] == "-4 dB"


def test_plan_push_devices_falls_back_to_normalized_without_display(
    conn, song, session, linked_track,
):
    """A param with no display string still writes via its normalized value."""
    cid = M.create_device_chain(conn, parent_track_id=linked_track)
    did = M.create_device(conn, chain_id=cid, position=1, kind="EQ Eight", display_name="EQ")
    M.set_device_parameter(
        conn, device_id=did, name="Gain",
        value_display="", value_normalized=0.42,
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="device", db_id=did, ableton_index=2,
    )
    plan = push.plan_push_devices(conn, song_id=song, session_id=session)
    by_action = _calls_by_action(plan)
    call = by_action["set_parameter"][0]
    assert float(call.args["value"]) == pytest.approx(0.42)
    assert "value_display" not in call.args
    assert call.args["value_type"] == "continuous"


def test_plan_push_devices_writes_value_raw_as_raw_continuous(
    conn, song, session, linked_track,
):
    """DEV-4P7R: a param stored on the raw channel emits its UNCLAMPED raw value
    on the wire as a continuous `value` (the witness LFO S. Rate: raw 8.0 in
    [0,21]) — never value_display (which the live setter refuses) nor the
    normalized-as-raw form (which mis-dials a non-[0,1] param)."""
    cid = M.create_device_chain(conn, parent_track_id=linked_track)
    did = M.create_device(conn, chain_id=cid, position=1, kind="Wavetable",
                          display_name="WT")
    M.set_device_parameter(conn, device_id=did, name="LFO 1 S. Rate",
                           value_display="1/2", value_raw=8.0)
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="device", db_id=did, ableton_index=1,
    )
    plan = push.plan_push_devices(conn, song_id=song, session_id=session)
    call = _calls_by_action(plan)["set_parameter"][0]
    assert float(call.args["value"]) == pytest.approx(8.0)
    assert call.args["value_type"] == "continuous"
    assert "value_display" not in call.args


def test_plan_push_devices_value_raw_beats_display_hint(
    conn, song, session, linked_track,
):
    """Channel precedence: an explicit value_raw wins over a stored display
    string, so a readable hint can ride alongside the authoritative raw."""
    cid = M.create_device_chain(conn, parent_track_id=linked_track)
    did = M.create_device(conn, chain_id=cid, position=1, kind="Wavetable",
                          display_name="WT")
    # Both stored: display is a hint; raw is authoritative.
    M.set_device_parameter(conn, device_id=did, name="LFO 1 S. Rate",
                           value_display="1/2", value_raw=8.0)
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="device", db_id=did, ableton_index=1,
    )
    plan = push.plan_push_devices(conn, song_id=song, session_id=session)
    call = _calls_by_action(plan)["set_parameter"][0]
    assert float(call.args["value"]) == pytest.approx(8.0)
    assert "value_display" not in call.args


def test_plan_push_devices_writes_known_enums_as_enum(
    conn, song, session, linked_track,
):
    """SYN-9F2L sweep: a param with captured value_items is a known enum —
    the planner emits a value_type='enum' write (the handler validates
    membership), closing the old silently-skipped-enum gap."""
    cid = M.create_device_chain(conn, parent_track_id=linked_track)
    did = M.create_device(conn, chain_id=cid, position=1, kind="Operator", display_name="Op")
    M.set_device_parameter(conn, device_id=did, name="Filter Type",
                           value_display="Lowpass",
                           value_items=["Lowpass", "Highpass", "Bandpass"])
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="device", db_id=did, ableton_index=1,
    )
    plan = push.plan_push_devices(conn, song_id=song, session_id=session)
    by_action = _calls_by_action(plan)
    call = by_action["set_parameter"][0]
    assert call.args["value_type"] == "enum"
    assert call.args["value"] == "Lowpass"
    assert "value_display" not in call.args


def test_plan_push_devices_ambiguous_param_writes_display(
    conn, song, session, linked_track,
):
    """A display-only param with no captured value_items and no normalized
    (hand-authored snapshot enum, or a continuous param authored by display
    alone) emits a continuous display write — the executor's set_parameter
    fallback retries it as an enum if the handler refuses."""
    cid = M.create_device_chain(conn, parent_track_id=linked_track)
    did = M.create_device(conn, chain_id=cid, position=1, kind="Operator", display_name="Op")
    M.set_device_parameter(conn, device_id=did, name="Filter Type",
                           value_display="Lowpass")  # no normalized, no items
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="device", db_id=did, ableton_index=1,
    )
    plan = push.plan_push_devices(conn, song_id=song, session_id=session)
    by_action = _calls_by_action(plan)
    call = by_action["set_parameter"][0]
    assert call.args["value_display"] == "Lowpass"
    assert call.args["value_type"] == "continuous"


def test_plan_push_devices_warns_for_unwritable_params(
    conn, song, session, linked_track,
):
    """SYN-9F2L: a params_dialed write that cannot be planned in ANY form must
    surface as an operator-actionable ALERT (drained into the push report's
    warnings), never drop silently and never get buried in the diagnostic
    `notes` channel that the executor discards."""
    cid = M.create_device_chain(conn, parent_track_id=linked_track)
    did = M.create_device(conn, chain_id=cid, position=1, kind="Operator", display_name="Op")
    M.set_device_parameter(conn, device_id=did, name="Mystery",
                           value_display="")  # no display, no normalized
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="device", db_id=did, ableton_index=1,
    )
    plan = push.plan_push_devices(conn, song_id=song, session_id=session)
    by_action = _calls_by_action(plan)
    assert "set_parameter" not in by_action
    assert any("Mystery" in a and "no writable form" in a for a in plan.alerts)
    # Must NOT also land in the diagnostic notes channel (which execute drops).
    assert not any("no writable form" in n for n in plan.notes)


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
    assert load.args["node"] == build_node_addr(
        {"return_index": 1}, terminal="return",
    )
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
    assert param_call.args["node"] == build_node_addr(
        {"return_index": 1}, device_index=2,
    )
    assert param_call.args["parameter_name"] == "Decay"
    # SYN-9F2L: display form preferred on the wire.
    assert param_call.args["value_display"] == "2.5 s"


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
    kinds = sorted(link["db_kind"] for link in links)
    assert kinds == ["device", "track"]


def test_apply_push_results_accepts_device_param_override_as_ack(
    conn, song, session, linked_track,
):
    """A nested preset param override (DEV-4P7R `param_overrides`, e.g. a
    `value_raw` on a rack's nested Wavetable LFO) is emitted by the planner as a
    `device_param_override:` result key whose tail carries the NodeAddr path +
    param name. apply_push_results must ACK it (no DB write, no raise): its value
    ORIGINATES in the snapshot/DB, exactly like `device_parameter`.

    Regression: the kind had no case, so apply_push_results raised
    `ValueError: unknown push result key kind 'device_param_override'`, which
    HALTED the devices phase mid-run — a full from-scratch push of any song with
    such an override never finished (no routing/envelopes/automation/arrangement).
    See incoming-bugs/archives/2026-06-18-push-apply-unknown-device_param_override-result-kind-halts-devices-phase.md
    """
    cid = M.create_device_chain(conn, parent_track_id=linked_track)
    did = M.create_device(
        conn, chain_id=cid, position=1, kind="Instrument Rack",
        display_name="Synth Vox Ai",
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="device", db_id=did, ableton_index=2,
    )
    key = (
        f'device_param_override:{did}:'
        '[{"chain_index": 1, "device_position": 1}]:LFO 1 S. Rate'
    )
    warnings = push.apply_push_results(
        conn,
        [
            {"key": key, "ok": True, "tool": "ableton_device", "result": {}},
        ],
        session_id=session,
    )
    assert warnings == []
    # Existing device + track links survive; nothing else added (ack-only).
    links = Q.get_ableton_links_for_session(conn, session)
    kinds = sorted(link["db_kind"] for link in links)
    assert kinds == ["device", "track"]


def test_apply_push_results_accepts_device_chain_props_as_ack(
    conn, song, session, linked_track,
):
    """Per-chain mixer/choke state (NODE-ADDR Chunk C/F: mute/solo/volume/pan +
    choke_group/out_note) is emitted by the planner as a
    `device_chain_props:{chain_id}` result key via
    ableton_device(set_chain_property). apply_push_results must ACK it (no DB
    write, no raise): the chain state ORIGINATES in the snapshot/DB and a chain
    has no Live-side index to record back (addressed by chain_index), exactly
    like `device_param_override`.

    Regression (DIRECT TWIN of the 2026-06-18 device_param_override bug, one key
    kind over): the kind had no case, so apply_push_results raised
    `ValueError: unknown push result key kind 'device_chain_props'`, which
    CRASHED the devices-phase apply — a full from-scratch push of any rack-preset
    song carrying non-default per-chain volume/mute/choke never finished (no
    routing/envelopes/automation/arrangement/cues). Stayed latent until the
    rack-preset load fix made the rack load populated, so the set_chain_property
    calls finally SUCCEEDED and their results reached this apply step.
    See incoming-bugs/archives/2026-06-20-push-apply-unknown-device_chain_props-result-kind-crashes-devices-phase.md
    """
    cid = M.create_device_chain(conn, parent_track_id=linked_track)
    did = M.create_device(
        conn, chain_id=cid, position=1, kind="Drum Rack",
        display_name="AG Techno Kit",
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="device", db_id=did, ableton_index=2,
    )
    # The planner keys this by the chain id; the result carries the applied
    # chain state (content irrelevant to apply — it's ack-only).
    warnings = push.apply_push_results(
        conn,
        [
            {"key": f"device_chain_props:{cid}", "ok": True,
             "tool": "ableton_device",
             "result": {"volume": 0.72, "mute": False}},
        ],
        session_id=session,
    )
    assert warnings == []
    # Existing device + track links survive; nothing else added (ack-only).
    links = Q.get_ableton_links_for_session(conn, session)
    kinds = sorted(link["db_kind"] for link in links)
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
    M.create_device(conn, chain_id=cid, position=2, kind="Compressor", display_name="Comp")
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
        c.args["node"]["parent"]["kind"]: c for c in loads
    }
    assert by_target["track"].args["kind"] == "Compressor"
    assert by_target["return"].args["kind"] == "Reverb"


# ---------- master-strip device chains (Chunk 2 — closes P0 backlog) -------


@pytest.fixture
def master_track(conn, song):
    """A master-strip track in the DB. Bootstrapped by hand here because
    the song fixture above doesn't create one — master strips are not
    required for the bulk of the planner tests, so this is opt-in."""
    return M.create_track(
        conn, song_id=song, track_index=0, name="Master", kind="master",
    )


def test_plan_push_devices_walks_master_chain(
    conn, song, session, master_track,
):
    """DEV-6M2K: plan_push_devices walks kind='master' tracks and emits a
    ``device.load(master=True)`` for an UNLINKED master device, exactly like a
    track/return device. The earlier SYN-2M9P/DEV-2M9K skip (zero loads +
    place-by-hand note) rested on a premise refuted on Live 12.4.2 — master
    device load works, so the load executes and links via the same
    ``device:<id>`` key path; no PARTIAL-by-master halt. (Fuller plan +
    execute-path coverage lives in test_dev_6m2k_master_load.py.)"""
    cid = M.create_device_chain(conn, parent_track_id=master_track)
    M.create_device(
        conn, chain_id=cid, position=1,
        kind="Limiter", display_name="Master Limiter",
    )

    plan = push.plan_push_devices(conn, song_id=song, session_id=session)
    loads = [c for c in plan.calls if c.args.get("action") == "load"]
    assert len(loads) == 1, f"unlinked master device must emit one load, got {loads}"
    args = loads[0].args
    assert args["node"] == build_node_addr({"master": True}, terminal="master")
    assert "track_index" not in args and "return_index" not in args
    assert args["kind"] == "Limiter"
    # Standard device-level "not linked yet" note (the generic path), NOT the
    # retired "place by hand" note.
    assert any("Master Limiter" in n and "not linked yet" in n for n in plan.notes), \
        plan.notes
    assert not any("by hand" in n or "not loadable via LOM" in n for n in plan.notes)


def test_plan_push_devices_master_chain_no_unlinked_track_warn(
    conn, song, session, master_track,
):
    """Master strip has no ableton_link row (no track_index addressing).
    The planner must NOT emit the TRACK-LEVEL "track ... not linked" warning
    for the master — it's a singleton, not a missing track. (Device-level
    "device ... not linked yet" warnings still apply per-device until
    apply_push_results lands the device_index.)"""
    cid = M.create_device_chain(conn, parent_track_id=master_track)
    M.create_device(
        conn, chain_id=cid, position=1,
        kind="Limiter", display_name="Master Limiter",
    )

    plan = push.plan_push_devices(conn, song_id=song, session_id=session)
    assert not any(
        n.startswith("track 'Master'") and "not linked" in n
        for n in plan.notes
    ), plan.notes


def test_plan_push_devices_master_set_parameter_uses_master_kv(
    conn, song, session, master_track,
):
    """When the master device is linked, parameter writes must use
    master=True addressing too (not track_index)."""
    cid = M.create_device_chain(conn, parent_track_id=master_track)
    dev = M.create_device(
        conn, chain_id=cid, position=1,
        kind="Limiter", display_name="Master Limiter",
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="device", db_id=dev, ableton_index=1,
    )
    M.set_device_parameter(
        conn, device_id=dev, name="Ceiling",
        value_display="-0.3 dB", value_normalized=0.9,
    )

    plan = push.plan_push_devices(conn, song_id=song, session_id=session)
    set_calls = [c for c in plan.calls if c.args.get("action") == "set_parameter"]
    assert len(set_calls) == 1
    args = set_calls[0].args
    assert args["node"] == build_node_addr({"master": True}, device_index=1)
    assert "track_index" not in args
    assert "return_index" not in args
    assert args["parameter_name"] == "Ceiling"


# ---------- SDC-7K3M: device sidechain SOURCE routing ----------


def test_plan_push_device_sidechain_emits_set_input_routing(
    conn, song, session, linked_track,
):
    """A device carrying a sidechain source FK emits set_input_routing,
    resolving the FK to the source track's Live display_name (symmetric with
    track routing). Ack-only, keyed device_sidechain:<id>."""
    cid = M.create_device_chain(conn, parent_track_id=linked_track)
    did = M.create_device(
        conn, chain_id=cid, position=1, kind="Compressor", display_name="Bass Punk"
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="device", db_id=did, ableton_index=2,
    )
    kick = M.create_track(conn, song_id=song, track_index=9, name="Kick", kind="midi")
    M.set_device_sidechain(
        conn, device_id=did, source_track_id=kick, channel="Post FX",
    )

    plan = push.plan_push_device_sidechain(conn, song_id=song, session_id=session)
    assert len(plan.calls) == 1
    call = plan.calls[0]
    assert call.tool == "ableton_device"
    assert call.args["action"] == "set_input_routing"
    assert call.args["track_index"] == 5       # the device's parent track
    assert call.args["device_index"] == 2
    assert call.args["type_display_name"] == "Kick"   # source FK → display_name
    assert call.args["channel_display_name"] == "Post FX"
    assert call.key == f"device_sidechain:{did}"


def test_plan_push_device_sidechain_skips_devices_without_source(
    conn, song, session, linked_track,
):
    """A device with no sidechain source (NULL FK) emits nothing."""
    cid = M.create_device_chain(conn, parent_track_id=linked_track)
    did = M.create_device(
        conn, chain_id=cid, position=1, kind="Compressor", display_name="C"
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="device", db_id=did, ableton_index=2,
    )
    plan = push.plan_push_device_sidechain(conn, song_id=song, session_id=session)
    assert plan.calls == []


def test_plan_push_device_sidechain_defers_unlinked_device(
    conn, song, session, linked_track,
):
    """An unlinked device (the devices phase hasn't landed its link yet) is
    deferred with a warn, not emitted — the devices-convergence re-plan picks
    it up once the device_index exists."""
    cid = M.create_device_chain(conn, parent_track_id=linked_track)
    did = M.create_device(
        conn, chain_id=cid, position=1, kind="Compressor", display_name="C"
    )
    kick = M.create_track(conn, song_id=song, track_index=9, name="Kick", kind="midi")
    M.set_device_sidechain(conn, device_id=did, source_track_id=kick)
    # Device intentionally NOT linked.
    plan = push.plan_push_device_sidechain(conn, song_id=song, session_id=session)
    assert plan.calls == []


# ---------- analyzer rows (SNP-8R4K chunk 1) ----------


def test_plan_push_devices_skips_analyzer_row_with_warn(
    conn, song, session, linked_track,
):
    """SNP-8R4K: a legacy-polluted DB carrying a HallucinoteAnalyzer row must
    NOT emit a load (it's measurement infrastructure, not a loadable browser
    node — emitting one would fail/halt the push). Skip cleanly with a warn,
    placed alongside the placeholder skip.
    """
    cid = M.create_device_chain(conn, parent_track_id=linked_track)
    M.create_device(
        conn, chain_id=cid, position=1, kind="Max Audio Effect",
        display_name="HallucinoteAnalyzer", class_name="MxDeviceAudioEffect",
    )
    plan = push.plan_push_devices(conn, song_id=song, session_id=session)
    assert plan.calls == []  # no load, no set_parameter
    assert any(
        "HallucinoteAnalyzer" in n and "skipping" in n for n in plan.notes
    )


def test_plan_push_devices_analyzer_skip_does_not_block_authored_devices(
    conn, song, session, linked_track,
):
    """An analyzer row interleaved with authored devices in a polluted DB:
    the analyzer is skipped (warned) but the authored devices still push."""
    cid = M.create_device_chain(conn, parent_track_id=linked_track)
    M.create_device(conn, chain_id=cid, position=1, kind="Operator",
                    display_name="Operator")
    M.create_device(
        conn, chain_id=cid, position=2, kind="Max Audio Effect",
        display_name="HallucinoteAnalyzer", class_name="MxDeviceAudioEffect",
    )
    M.create_device(conn, chain_id=cid, position=3, kind="EQ Eight",
                    display_name="EQ Eight")
    plan = push.plan_push_devices(conn, song_id=song, session_id=session)
    loads = [
        c for c in plan.calls
        if c.tool == "ableton_device" and c.args.get("action") == "load"
    ]
    loaded_kinds = [c.args["kind"] for c in loads]
    assert loaded_kinds == ["Operator", "EQ Eight"]
    assert all(k != "Max Audio Effect" for k in loaded_kinds)
    assert any("HallucinoteAnalyzer" in n for n in plan.notes)


# ---------------------------------------------------------------------------
# NODE-ADDR Chunk C — per-DrumChain choke_group / out_note push
# ---------------------------------------------------------------------------


def _linked_drum_rack(conn, session, track, *, track_at=5, rack_at=1):
    """A linked track with a linked Drum Rack on its top-level chain. Returns
    the rack's DB id so the test can hang nested (drum) chains off it."""
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=track,
        ableton_index=track_at,
    )
    top_chain = M.create_device_chain(conn, parent_track_id=track, position=0)
    rack = M.create_device(
        conn, chain_id=top_chain, position=1,
        kind="Drum Rack", display_name="Drum Rack",
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="device", db_id=rack,
        ableton_index=rack_at,
    )
    return rack


def test_push_emits_set_chain_property_for_authored_drum_chain(
    conn, song, session, track
):
    rack = _linked_drum_rack(conn, session, track)
    nested = M.create_device_chain(conn, parent_rack_device_id=rack, position=1)
    M.set_chain_properties(conn, chain_id=nested, choke_group=1, out_note=60)

    plan = push.plan_push_devices(conn, song_id=song, session_id=session)
    calls = _calls_by_action(plan)["set_chain_property"]
    assert len(calls) == 1
    c = calls[0]
    assert c.args["choke_group"] == 1 and c.args["out_note"] == 60
    assert c.args["node"] == build_node_addr(
        {"track_index": 5}, device_index=1, terminal="chain", chain_index=1,
    )
    assert c.key == f"device_chain_props:{nested}"


def test_push_emits_only_the_authored_field(conn, song, session, track):
    rack = _linked_drum_rack(conn, session, track)
    nested = M.create_device_chain(conn, parent_rack_device_id=rack, position=2)
    M.set_chain_properties(conn, chain_id=nested, choke_group=3)  # out_note default

    calls = _calls_by_action(
        push.plan_push_devices(conn, song_id=song, session_id=session)
    )["set_chain_property"]
    assert len(calls) == 1
    assert calls[0].args["choke_group"] == 3
    assert "out_note" not in calls[0].args
    assert calls[0].args["node"]["chain_index"] == 2


def test_push_skips_default_only_drum_chain(conn, song, session, track):
    rack = _linked_drum_rack(conn, session, track)
    # A chain row with no authored props (the common case — most pads).
    M.create_device_chain(conn, parent_rack_device_id=rack, position=1)
    plan = push.plan_push_devices(conn, song_id=song, session_id=session)
    assert "set_chain_property" not in _calls_by_action(plan)


# NODE-ADDR Chunk F — per-chain mixer state (mute/solo/volume/pan) push.

def test_push_emits_mixer_state_for_authored_chain(conn, song, session, track):
    rack = _linked_drum_rack(conn, session, track)
    nested = M.create_device_chain(conn, parent_rack_device_id=rack, position=1)
    M.set_chain_properties(
        conn, chain_id=nested, mute=True, volume=0.5, pan=-0.25,
    )
    calls = _calls_by_action(
        push.plan_push_devices(conn, song_id=song, session_id=session)
    )["set_chain_property"]
    assert len(calls) == 1
    c = calls[0]
    # mute stored 0/1 -> re-emitted as the handler's bool wire type.
    assert c.args["mute"] is True
    assert c.args["volume"] == 0.5 and c.args["pan"] == -0.25
    assert "solo" not in c.args  # solo at default -> not emitted
    assert c.args["node"]["terminal"] == "chain"
    assert c.args["node"]["chain_index"] == 1


def test_push_combines_choke_and_mixer_on_one_chain(conn, song, session, track):
    rack = _linked_drum_rack(conn, session, track)
    nested = M.create_device_chain(conn, parent_rack_device_id=rack, position=1)
    M.set_chain_properties(conn, chain_id=nested, choke_group=2, solo=True)
    calls = _calls_by_action(
        push.plan_push_devices(conn, song_id=song, session_id=session)
    )["set_chain_property"]
    assert len(calls) == 1
    assert calls[0].args["choke_group"] == 2 and calls[0].args["solo"] is True


def test_push_addresses_a_nested_rack_chain_with_a_path(
    conn, song, session, track
):
    """A drum rack nested INSIDE another rack: the chain-terminal node carries
    the path to the inner rack, device_index stays the top-level rack."""
    rack = _linked_drum_rack(conn, session, track)
    inner_chain = M.create_device_chain(conn, parent_rack_device_id=rack, position=1)
    inner_rack = M.create_device(
        conn, chain_id=inner_chain, position=1,
        kind="Drum Rack", display_name="Inner Kit",
    )
    drum_chain = M.create_device_chain(
        conn, parent_rack_device_id=inner_rack, position=2,
    )
    M.set_chain_properties(conn, chain_id=drum_chain, choke_group=4)

    calls = _calls_by_action(
        push.plan_push_devices(conn, song_id=song, session_id=session)
    )["set_chain_property"]
    assert len(calls) == 1
    assert calls[0].args["node"] == build_node_addr(
        {"track_index": 5},
        device_index=1,
        device_path=[{"chain_index": 1, "device_position": 1}],
        terminal="chain",
        chain_index=2,
    )
