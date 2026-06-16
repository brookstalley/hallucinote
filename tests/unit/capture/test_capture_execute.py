"""Tests for the deterministic in-code capture (NODE-ADDR Chunk B):
`capture.assemble_snapshot_via_probes` + the OQ5 default-value filter
(`_snapshot_param_entry`).

These exercise the READ-SIDE acquisition the params-durability gap was missing:
a dialed parameter at ANY nesting depth is probed via a NodeAddr `path` and
lands in the snapshot, so it survives a `/song-snapshot` + rebuild. The headline
test is the *acquisition* round-trip — fake-Live probe -> capture -> snapshot ->
DB -> push re-emit — which is the loop the prior replay-only test never closed
(it started from a hand-built snapshot, never from the capture walk).

Synthetic fixtures only (project convention for tests/unit/capture/): the fake
`probe` stands in for a running Live + bridge.
"""
from __future__ import annotations

import pytest

from hallucinote.capture import (
    assemble_snapshot_via_probes,
    replay_capture,
    _params_dialed_via_probe,
    _snapshot_param_entry,
)
from hallucinote.db import init_db, mutations as M, queries as Q
from hallucinote.sync import push
from hallucinote.sync.push._core import build_node_addr


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "cap.db")
    yield c
    c.close()


# --------------------------------------------------------------------------
# _snapshot_param_entry — the OQ5 default-value filter + probe->params_dialed
# --------------------------------------------------------------------------


def test_param_entry_continuous_non_default_keeps_value_and_normalized():
    entry = _snapshot_param_entry({
        "name": "Freq", "value": 0.75, "value_display": "1 kHz",
        "default_value": 0.0, "min": 0.0, "max": 1.0, "is_enum": False,
    })
    assert entry == {"value": "1 kHz", "normalized": 0.75}


def test_param_entry_at_default_is_filtered_out():
    """A param sitting at its intrinsic default is not *dialed* — dropped."""
    assert _snapshot_param_entry({
        "name": "Vol", "value": 0.5, "value_display": "0 dB",
        "default_value": 0.5, "min": 0.0, "max": 1.0, "is_enum": False,
    }) is None


def test_param_entry_near_default_within_epsilon_is_filtered():
    assert _snapshot_param_entry({
        "name": "Vol", "value": 0.5004, "value_display": "0 dB",
        "default_value": 0.5, "min": 0.0, "max": 1.0, "is_enum": False,
    }) is None


def test_param_entry_default_omitted_is_always_captured():
    """The raises-fallback (design §1b): Live raises on some quantized params'
    `default_value`, so the handler OMITS it. Capture can't prove the param is
    at default -> ALWAYS keep it (the always-capture minority)."""
    entry = _snapshot_param_entry({
        "name": "Snap", "value": 1.0, "value_display": "On",
        "min": 0.0, "max": 1.0, "is_enum": True, "value_items": ["Off", "On"],
    })
    assert entry == {"value": "On", "value_items": ["Off", "On"]}


def test_param_entry_enum_has_no_normalized():
    entry = _snapshot_param_entry({
        "name": "Wave", "value": 2.0, "value_display": "Saw",
        "default_value": 0.0, "min": 0.0, "max": 3.0, "is_enum": True,
        "value_items": ["Sine", "Tri", "Saw", "Square"],
    })
    assert "normalized" not in entry
    assert entry["value"] == "Saw"
    assert entry["value_items"] == ["Sine", "Tri", "Saw", "Square"]


def test_param_entry_non_numeric_value_is_skipped():
    assert _snapshot_param_entry({"name": "X", "value": None}) is None
    assert _snapshot_param_entry({"name": "B", "value": True}) is None


def test_macro_value_rides_device_parameters_keyed_by_name():
    """NODE-ADDR Chunk D: a macro IS a DeviceParameter, so its value is captured
    by the standard params_dialed path, keyed by the macro's (custom) name —
    which is why `macro_values` is SUPPORTED with NO separate handler. The NAME
    itself is a LOM wall (see the `macro_names` matrix cell); capture keys by
    name, so a by-ear macro rename can decouple a stored value from its knob."""
    def probe(tool, action, **params):
        assert (tool, action) == ("ableton_device", "get_parameters")
        return {"parameters": [
            # The rack's Device On macro slot, sitting at its default -> dropped.
            {"name": "Device On", "value": 1.0, "default_value": 1.0,
             "value_display": "On", "min": 0.0, "max": 1.0, "is_enum": True,
             "value_items": ["Off", "On"]},
            # A renamed macro (name != original_name) dialed off its default.
            {"name": "Filter Cutoff", "original_name": "Macro 1",
             "value": 0.62, "default_value": 0.0, "value_display": "79.0",
             "min": 0.0, "max": 1.0, "is_enum": False},
        ]}
    out = _params_dialed_via_probe(
        probe,
        node={"parent": {"kind": "track", "index": 1},
              "terminal": "device", "device_index": 1},
    )
    assert out == {"Filter Cutoff": {"value": "79.0", "normalized": 0.62}}


def test_param_entry_empty_display_stays_empty_not_raw():
    """Probe with no display string -> store EMPTY value (push then uses the
    normalized value), never str(raw): a bare number pushed as a *display* value
    mis-dials a continuous param. Matches the pull apply path's behavior."""
    entry = _snapshot_param_entry({
        "name": "P", "value": 0.6, "value_display": None,
        "default_value": 0.0, "min": 0.0, "max": 1.0, "is_enum": False,
    })
    assert entry == {"value": "", "normalized": 0.6}


def test_param_entry_constant_range_stores_display_only():
    """min == max -> no continuous form -> normalized omitted, value is the
    display string (replay stores value_normalized NULL)."""
    entry = _snapshot_param_entry({
        "name": "Const", "value": 1.0, "value_display": "fixed",
        "default_value": 0.0, "min": 1.0, "max": 1.0, "is_enum": False,
    })
    assert entry == {"value": "fixed"}


# --------------------------------------------------------------------------
# A fake `probe` that models a small live set with a depth-2 nested dialed param
# --------------------------------------------------------------------------


class _FakeProbe:
    """Records every (tool, action, params) call so tests can assert the walk
    (the symmetry contract) and routes get_parameters by NodeAddr path depth."""

    def __init__(self, *, nested_params):
        self.calls: list[tuple[str, str, dict]] = []
        self._nested_params = nested_params

    def __call__(self, tool, action, **params):
        self.calls.append((tool, action, dict(params)))
        if (tool, action) == ("ableton_session", "info"):
            return {
                "tempo": 120.0,
                "signature": {"numerator": 7, "denominator": 8},
                "master": {"volume": 0.85, "panning": 0.0},
                "track_count": 1, "return_count": 0,
            }
        if (tool, action) == ("ableton_return", "list"):
            return {"returns": []}
        if (tool, action) == ("ableton_track", "info"):
            return {
                "track_index": params["track_index"], "name": "Guitar",
                "kind": "midi", "volume": 0.7, "panning": 0.0,
                "mute": False, "solo": False, "arm": False,
            }
        if (tool, action) == ("ableton_track", "get_sends"):
            return {"sends": []}
        if (tool, action) == ("ableton_device", "list"):
            if params.get("master"):
                return {"devices": []}
            return {"devices": [{
                "device_index": 1, "name": "Guitar-Dual Amped Heavy",
                "class_name": "InstrumentGroupDevice",
                "class_display_name": "Instrument Rack", "is_active": True,
            }]}
        if (tool, action) == ("ableton_device", "get_device_chains"):
            # depth-2 recursive tree: top rack -> rack -> Operator.
            return {"chains": [{"chain_index": 1, "name": "Guitar", "devices": [{
                "position": 1, "name": "Guitar Dead Notes",
                "class_name": "InstrumentGroupDevice",
                "class_display_name": "Instrument Rack", "is_rack": True,
                "device_path": [{"chain_index": 1, "device_position": 1}],
                "chains": [{"chain_index": 1, "name": "", "devices": [{
                    "position": 1, "name": "Deep Synth",
                    "class_name": "Operator", "class_display_name": "Operator",
                    "is_rack": False,
                    "device_path": [
                        {"chain_index": 1, "device_position": 1},
                        {"chain_index": 1, "device_position": 1},
                    ],
                }]}],
            }]}]}
        if (tool, action) == ("ableton_device", "get_parameters"):
            node = params["node"]
            depth = len(node.get("path") or [])
            return {"parameters": self._nested_params.get(depth, [])}
        raise AssertionError(f"unrouted probe {tool}.{action} {params}")


def _operator_params():
    """Operator (depth-2): one dialed Volume + one param sitting at default."""
    return {
        2: [
            {"name": "Volume", "value": 0.6, "value_display": "-4 dB",
             "default_value": 0.0, "min": 0.0, "max": 1.0, "is_enum": False},
            {"name": "Tone", "value": 0.5, "value_display": "0",
             "default_value": 0.5, "min": 0.0, "max": 1.0, "is_enum": False},
        ],
    }


def test_assemble_captures_depth2_param_into_snapshot():
    probe = _FakeProbe(nested_params=_operator_params())
    snap = assemble_snapshot_via_probes(probe)

    assert snap["song"]["signature"] == "7/8"
    op = (
        snap["tracks"][0]["devices"][0]   # top rack
        ["chains"][0]["devices"][0]       # nested rack
        ["chains"][0]["devices"][0]       # Operator
    )
    assert op["name"] == "Deep Synth"
    # The dialed Volume is captured; the at-default Tone is filtered out.
    assert op["params_dialed"] == {"Volume": {"value": "-4 dB", "normalized": 0.6}}


def test_symmetry_nested_device_is_probed_like_top_level():
    """Symmetry contract: capture probes get_parameters for EVERY device at
    EVERY depth (top rack, nested rack, deep Operator) — not just top-level."""
    probe = _FakeProbe(nested_params=_operator_params())
    assemble_snapshot_via_probes(probe)
    param_probes = [
        c for c in probe.calls
        if c[0] == "ableton_device" and c[1] == "get_parameters"
    ]
    depths = sorted(len(c[2]["node"].get("path") or []) for c in param_probes)
    assert depths == [0, 1, 2]  # top-level, depth-1 rack, depth-2 Operator


def test_acquisition_roundtrip_depth2_nested_param(conn):
    """The durability gap closed end-to-end via the ACQUISITION (not a
    hand-built snapshot): fake-Live probe -> assemble_snapshot_via_probes ->
    replay into DB -> push re-emits the depth-2 dialed param as set_parameter
    with the correct 2-step device_path. A deep by-ear fix survives a rebuild."""
    probe = _FakeProbe(nested_params=_operator_params())
    snapshot = assemble_snapshot_via_probes(probe)

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
    assert len(sets) == 1  # only the deep Operator's Volume (Tone was at default)
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


def test_assemble_captures_master_and_returns():
    """Returns get a per-return `info` probe for mixer state; the master block
    carries its chain (the session `info` master mixer + a device list)."""
    calls: list[tuple[str, str, dict]] = []

    def probe(tool, action, **params):
        calls.append((tool, action, dict(params)))
        if (tool, action) == ("ableton_session", "info"):
            return {"tempo": 128.0, "signature": {"numerator": 4, "denominator": 4},
                    "master": {"volume": 0.9, "panning": 0.0},
                    "track_count": 0, "return_count": 1}
        if (tool, action) == ("ableton_return", "list"):
            return {"returns": [{"return_index": 1, "name": "A-Reverb", "color": 5}]}
        if (tool, action) == ("ableton_return", "info"):
            return {"return_index": 1, "name": "A-Reverb", "volume": 0.8,
                    "panning": -0.2, "color": 5}
        if (tool, action) == ("ableton_device", "list"):
            if params.get("master"):
                return {"devices": [{
                    "device_index": 1, "name": "Limiter",
                    "class_name": "Limiter", "class_display_name": "Limiter",
                }]}
            return {"devices": []}  # the return has no devices
        if (tool, action) == ("ableton_device", "get_parameters"):
            return {"parameters": [
                {"name": "Ceiling", "value": 0.95, "value_display": "-0.3 dB",
                 "default_value": 1.0, "min": 0.0, "max": 1.0, "is_enum": False},
            ]}
        raise AssertionError(f"unrouted {tool}.{action}")

    snap = assemble_snapshot_via_probes(probe)
    assert snap["song"]["master"]["volume"] == 0.9
    assert snap["song"]["master"]["devices"][0]["class"] == "Limiter"
    assert snap["song"]["master"]["devices"][0]["params_dialed"]["Ceiling"] == {
        "value": "-0.3 dB", "normalized": 0.95,
    }
    ret = snap["returns"][0]
    assert ret["name"] == "A-Reverb"
    assert ret["volume"] == 0.8
    assert ret["panning"] == -0.2
    # A per-return `info` probe was issued for the mixer state the list omits.
    assert ("ableton_return", "info", {"return_index": 1}) in calls


def test_assemble_skips_analyzer_without_probing_it():
    """The HallucinoteAnalyzer is measurement infra — never enters the snapshot
    AND is never probed (no wasted get_parameters / get_device_chains on it)."""
    calls: list[tuple[str, str, dict]] = []

    def probe(tool, action, **params):
        calls.append((tool, action, dict(params)))
        if (tool, action) == ("ableton_session", "info"):
            return {"tempo": 120.0, "signature": {"numerator": 4, "denominator": 4},
                    "master": None, "track_count": 1, "return_count": 0}
        if (tool, action) == ("ableton_return", "list"):
            return {"returns": []}
        if (tool, action) == ("ableton_track", "info"):
            return {"track_index": 1, "name": "T", "kind": "audio",
                    "volume": 0.7, "panning": 0.0}
        if (tool, action) == ("ableton_track", "get_sends"):
            return {"sends": []}
        if (tool, action) == ("ableton_device", "list"):
            return {"devices": [{
                "device_index": 1, "name": "HallucinoteAnalyzer",
                "class_name": "Max Audio Effect",
                "class_display_name": "Max Audio Effect",
            }]}
        if (tool, action) == ("ableton_device", "get_parameters"):
            raise AssertionError("analyzer must NOT be probed for parameters")
        raise AssertionError(f"unrouted {tool}.{action}")

    snap = assemble_snapshot_via_probes(probe)
    assert snap["tracks"][0].get("devices") in (None, [])
    assert not any(c[1] == "get_parameters" for c in calls)
