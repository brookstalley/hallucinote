"""SYN-9F4K: tests for the empty-rack guard (fail-loud on a rack that loaded
with 0 chains in the push devices phase).

Two layers:
  * ``_addresses_into_rack`` — which calls count as "dependent" (descend into a
    chain) vs the rack's own params (survive an empty load).
  * ``partition_doomed_nested_writes`` — suppress-when-empty, keep-when-populated,
    keep-on-probe-failure, no-probe-when-nothing-pending, parent+index
    disambiguation, order preservation, failure-record shape.

The executor wiring (probe closure + halt) is exercised end-to-end in
``test_push_execute.py``.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from hallucinote.sync.push._core import build_node_addr
from hallucinote.sync.push.empty_rack_guard import (
    _addresses_into_rack,
    partition_doomed_nested_writes,
)


@dataclass
class _Call:
    """Stand-in for a push ToolCall — the guard only reads ``args['node']``."""
    args: dict
    key: str = ""
    tool: str = "ableton_device"


def _nested_param_call(parent_kv, *, device_index, device_path, key="np"):
    """A nested-device set_parameter (descends into a chain via ``path``)."""
    return _Call(
        args={
            "action": "set_parameter",
            "node": build_node_addr(
                parent_kv, device_index=device_index, device_path=device_path,
            ),
            "parameter_name": "Volume",
        },
        key=key,
    )


def _chain_property_call(parent_kv, *, device_index, chain_index, key="cp"):
    """A set_chain_property (chain-terminal — also chain-dependent)."""
    return _Call(
        args={
            "action": "set_chain_property",
            "node": build_node_addr(
                parent_kv, device_index=device_index,
                terminal="chain", chain_index=chain_index,
            ),
            "mute": True,
        },
        key=key,
    )


def _top_level_param_call(parent_kv, *, device_index, key="tp"):
    """A write to the RACK's OWN params (device terminal, no path) — exists even
    on an empty rack, so it must NOT be suppressed."""
    return _Call(
        args={
            "action": "set_parameter",
            "node": build_node_addr(parent_kv, device_index=device_index),
            "parameter_name": "Macro 1",
        },
        key=key,
    )


def _rack(*, device_id="dev1", live_index=1, parent=None, display_name="AG Kit"):
    if parent is None:
        parent = {"kind": "track", "index": 5}
    return {
        "device_id": device_id, "live_index": live_index,
        "parent": parent, "display_name": display_name,
    }


_TRACK_KV = {"track_index": 5}
_PATH = [{"chain_index": 1, "device_position": 1}]


# ---------------------------------------------------------------------------
# _addresses_into_rack — dependency classification
# ---------------------------------------------------------------------------


def test_nested_path_write_is_dependent():
    node = build_node_addr(_TRACK_KV, device_index=1, device_path=_PATH)
    assert _addresses_into_rack(node, parent={"kind": "track", "index": 5}, device_index=1)


def test_chain_terminal_write_is_dependent():
    node = build_node_addr(_TRACK_KV, device_index=1, terminal="chain", chain_index=1)
    assert _addresses_into_rack(node, parent={"kind": "track", "index": 5}, device_index=1)


def test_top_level_param_write_is_not_dependent():
    # Device terminal, no path -> addresses the rack itself, survives empty load.
    node = build_node_addr(_TRACK_KV, device_index=1)
    assert not _addresses_into_rack(node, parent={"kind": "track", "index": 5}, device_index=1)


def test_different_device_index_is_not_dependent():
    node = build_node_addr(_TRACK_KV, device_index=2, device_path=_PATH)
    assert not _addresses_into_rack(node, parent={"kind": "track", "index": 5}, device_index=1)


def test_different_parent_is_not_dependent():
    node = build_node_addr({"track_index": 9}, device_index=1, device_path=_PATH)
    assert not _addresses_into_rack(node, parent={"kind": "track", "index": 5}, device_index=1)


def test_non_dict_node_is_not_dependent():
    assert not _addresses_into_rack(None, parent={"kind": "track", "index": 5}, device_index=1)


# ---------------------------------------------------------------------------
# partition_doomed_nested_writes — the guard
# ---------------------------------------------------------------------------


def test_suppresses_all_dependent_writes_when_rack_empty():
    calls = [
        _nested_param_call(_TRACK_KV, device_index=1, device_path=_PATH, key="a"),
        _chain_property_call(_TRACK_KV, device_index=1, chain_index=1, key="b"),
    ]
    survivors, failures = partition_doomed_nested_writes(
        calls, loaded_racks=[_rack(live_index=1)], probe_fn=lambda r: 0,
    )
    assert survivors == []
    assert len(failures) == 1
    f = failures[0]
    assert f["device_id"] == "dev1"
    assert f["suppressed_count"] == 2
    assert "preset content did not load" in f["message"]
    assert "AG Kit" in f["message"]
    assert "track index 5" in f["message"]
    assert f["hint"]


def test_keeps_dependent_writes_when_rack_populated():
    calls = [_nested_param_call(_TRACK_KV, device_index=1, device_path=_PATH)]
    survivors, failures = partition_doomed_nested_writes(
        calls, loaded_racks=[_rack(live_index=1)], probe_fn=lambda r: 16,
    )
    assert survivors == calls
    assert failures == []


def test_keeps_dependent_writes_when_probe_fails():
    # probe returns None (read failed) -> keep-on-doubt, no suppression, no halt.
    calls = [_nested_param_call(_TRACK_KV, device_index=1, device_path=_PATH)]
    survivors, failures = partition_doomed_nested_writes(
        calls, loaded_racks=[_rack(live_index=1)], probe_fn=lambda r: None,
    )
    assert survivors == calls
    assert failures == []


def test_rack_own_params_survive_an_empty_load():
    # The rack's own macro param is NOT chain-dependent, so even an empty rack
    # keeps it; only the nested write is suppressed.
    own = _top_level_param_call(_TRACK_KV, device_index=1, key="own")
    nested = _nested_param_call(_TRACK_KV, device_index=1, device_path=_PATH, key="nest")
    survivors, failures = partition_doomed_nested_writes(
        [own, nested], loaded_racks=[_rack(live_index=1)], probe_fn=lambda r: 0,
    )
    assert survivors == [own]
    assert failures[0]["suppressed_count"] == 1


def test_no_probe_and_no_failure_when_rack_has_no_dependent_writes():
    # A loaded rack with no pending nested writes (legitimately-empty preset) is
    # never probed and never flagged.
    own = _top_level_param_call(_TRACK_KV, device_index=1, key="own")

    def probe_fn(rack):
        raise AssertionError("must not probe a rack with no dependent writes")

    survivors, failures = partition_doomed_nested_writes(
        [own], loaded_racks=[_rack(live_index=1)], probe_fn=probe_fn,
    )
    assert survivors == [own]
    assert failures == []


def test_parent_disambiguates_two_racks_at_same_index():
    # Track 5's rack (index 1) loaded empty; track 9's rack (index 1) is fine.
    # Only track 5's nested write is suppressed.
    empty = _nested_param_call({"track_index": 5}, device_index=1, device_path=_PATH, key="empty")
    good = _nested_param_call({"track_index": 9}, device_index=1, device_path=_PATH, key="good")

    def probe_fn(rack):
        return 0 if rack["parent"]["index"] == 5 else 16

    survivors, failures = partition_doomed_nested_writes(
        [empty, good],
        loaded_racks=[
            _rack(device_id="t5", live_index=1, parent={"kind": "track", "index": 5}),
            _rack(device_id="t9", live_index=1, parent={"kind": "track", "index": 9}),
        ],
        probe_fn=probe_fn,
    )
    assert survivors == [good]
    assert [f["device_id"] for f in failures] == ["t5"]


def test_preserves_survivor_order():
    a = _top_level_param_call(_TRACK_KV, device_index=1, key="a")
    doomed = _nested_param_call(_TRACK_KV, device_index=1, device_path=_PATH, key="doomed")
    b = _top_level_param_call(_TRACK_KV, device_index=1, key="b")
    survivors, _ = partition_doomed_nested_writes(
        [a, doomed, b], loaded_racks=[_rack(live_index=1)], probe_fn=lambda r: 0,
    )
    assert [c.key for c in survivors] == ["a", "b"]


def test_master_rack_failure_message():
    parent = {"kind": "master"}
    calls = [_nested_param_call({"master": True}, device_index=1, device_path=_PATH)]
    _, failures = partition_doomed_nested_writes(
        calls, loaded_racks=[_rack(parent=parent, display_name="Bus Rack")],
        probe_fn=lambda r: 0,
    )
    assert "the master track" in failures[0]["message"]


def test_no_loaded_racks_is_a_noop():
    calls = [_nested_param_call(_TRACK_KV, device_index=1, device_path=_PATH)]
    survivors, failures = partition_doomed_nested_writes(
        calls, loaded_racks=[], probe_fn=lambda r: 0,
    )
    assert survivors == calls
    assert failures == []
