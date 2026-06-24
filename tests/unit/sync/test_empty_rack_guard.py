"""SYN-9F4K: tests for the empty-rack guard (fail-loud on a rack that loaded
with 0 chains in the push devices phase).

Two layers:
  * ``_dependent_address`` — which calls descend into a chain (so are doomed when
    the rack is empty) vs the rack's own params (survive an empty load).
  * ``partition_doomed_nested_writes`` — derive candidate racks from the calls,
    suppress-when-empty, keep-when-populated, keep-on-probe-failure,
    no-probe-when-nothing-pending, parent disambiguation, one-probe-per-rack,
    name vs address fallback, order preservation.

The executor wiring (probe closure + both dispatch sites + halt) is exercised
end-to-end in ``test_push_execute.py``.
"""
from __future__ import annotations

from dataclasses import dataclass

from hallucinote.sync.push._core import build_node_addr
from hallucinote.sync.push.empty_rack_guard import (
    _dependent_address,
    _parent_key,
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


_TRACK_KV = {"track_index": 5}
_PATH = [{"chain_index": 1, "device_position": 1}]


# ---------------------------------------------------------------------------
# _dependent_address — dependency classification
# ---------------------------------------------------------------------------


def test_nested_path_write_is_dependent():
    node = build_node_addr(_TRACK_KV, device_index=1, device_path=_PATH)
    assert _dependent_address(node) == ({"kind": "track", "index": 5}, 1)


def test_chain_terminal_write_is_dependent():
    node = build_node_addr(_TRACK_KV, device_index=2, terminal="chain", chain_index=1)
    assert _dependent_address(node) == ({"kind": "track", "index": 5}, 2)


def test_top_level_param_write_is_not_dependent():
    # Device terminal, no path -> addresses the rack itself, survives empty load.
    node = build_node_addr(_TRACK_KV, device_index=1)
    assert _dependent_address(node) is None


def test_node_without_device_index_is_not_dependent():
    # A track-terminal (a load) has no device_index — never a dependent write.
    node = build_node_addr(_TRACK_KV, terminal="track")
    assert _dependent_address(node) is None


def test_non_dict_node_is_not_dependent():
    assert _dependent_address(None) is None


def test_parent_key_master_has_no_index():
    assert _parent_key({"kind": "master"}) == ("master", None)
    assert _parent_key({"kind": "track", "index": 5}) == ("track", 5)


# ---------------------------------------------------------------------------
# partition_doomed_nested_writes — the guard
# ---------------------------------------------------------------------------


def test_suppresses_all_dependent_writes_when_rack_empty():
    calls = [
        _nested_param_call(_TRACK_KV, device_index=1, device_path=_PATH, key="a"),
        _chain_property_call(_TRACK_KV, device_index=1, chain_index=1, key="b"),
    ]
    survivors, failures = partition_doomed_nested_writes(calls, probe_fn=lambda r: 0)
    assert survivors == []
    assert len(failures) == 1
    f = failures[0]
    assert f["device_index"] == 1
    assert f["suppressed_count"] == 2
    assert "preset content did not load" in f["message"]
    # No name_fn -> address fallback in the message.
    assert "track index 5" in f["message"]
    assert "device index 1" in f["message"]
    assert f["hint"]


def test_keeps_dependent_writes_when_rack_populated():
    calls = [_nested_param_call(_TRACK_KV, device_index=1, device_path=_PATH)]
    survivors, failures = partition_doomed_nested_writes(calls, probe_fn=lambda r: 16)
    assert survivors == calls
    assert failures == []


def test_keeps_dependent_writes_when_probe_fails():
    # probe returns None (read failed) -> keep-on-doubt, no suppression, no halt.
    calls = [_nested_param_call(_TRACK_KV, device_index=1, device_path=_PATH)]
    survivors, failures = partition_doomed_nested_writes(calls, probe_fn=lambda r: None)
    assert survivors == calls
    assert failures == []


def test_rack_own_params_survive_an_empty_load():
    # The rack's own macro param is NOT chain-dependent, so even an empty rack
    # keeps it; only the nested write is suppressed.
    own = _top_level_param_call(_TRACK_KV, device_index=1, key="own")
    nested = _nested_param_call(_TRACK_KV, device_index=1, device_path=_PATH, key="nest")
    survivors, failures = partition_doomed_nested_writes(
        [own, nested], probe_fn=lambda r: 0,
    )
    assert survivors == [own]
    assert failures[0]["suppressed_count"] == 1


def test_no_probe_and_no_failure_when_no_dependent_writes():
    # Only top-level params -> no candidate rack -> probe never called.
    own = _top_level_param_call(_TRACK_KV, device_index=1, key="own")

    def probe_fn(rack):
        raise AssertionError("must not probe when there are no dependent writes")

    survivors, failures = partition_doomed_nested_writes([own], probe_fn=probe_fn)
    assert survivors == [own]
    assert failures == []


def test_probe_receives_parent_and_live_index():
    seen = []
    calls = [_nested_param_call(_TRACK_KV, device_index=3, device_path=_PATH)]

    def probe_fn(rack):
        seen.append(rack)
        return 0

    partition_doomed_nested_writes(calls, probe_fn=probe_fn)
    assert seen == [{"parent": {"kind": "track", "index": 5}, "live_index": 3}]


def test_one_probe_per_rack_for_many_writes():
    calls = [
        _nested_param_call(_TRACK_KV, device_index=1, device_path=_PATH, key=f"n{i}")
        for i in range(5)
    ]
    probes = []
    partition_doomed_nested_writes(calls, probe_fn=lambda r: probes.append(r) or 16)
    assert len(probes) == 1  # five writes, one rack, one probe


def test_parent_disambiguates_two_racks_at_same_index():
    # Track 5's rack (index 1) loaded empty; track 9's rack (index 1) is fine.
    empty = _nested_param_call({"track_index": 5}, device_index=1, device_path=_PATH, key="empty")
    good = _nested_param_call({"track_index": 9}, device_index=1, device_path=_PATH, key="good")

    def probe_fn(rack):
        return 0 if rack["parent"]["index"] == 5 else 16

    survivors, failures = partition_doomed_nested_writes([empty, good], probe_fn=probe_fn)
    assert survivors == [good]
    assert [f["parent"]["index"] for f in failures] == [5]


def test_name_fn_supplies_display_name_in_message():
    calls = [_nested_param_call(_TRACK_KV, device_index=1, device_path=_PATH)]
    _, failures = partition_doomed_nested_writes(
        calls, probe_fn=lambda r: 0,
        name_fn=lambda parent, di: "AG Techno Kit",
    )
    assert failures[0]["display_name"] == "AG Techno Kit"
    assert "'AG Techno Kit'" in failures[0]["message"]


def test_master_rack_address_fallback_message():
    calls = [_nested_param_call({"master": True}, device_index=1, device_path=_PATH)]
    _, failures = partition_doomed_nested_writes(calls, probe_fn=lambda r: 0)
    assert "the master track" in failures[0]["message"]


def test_preserves_survivor_order():
    a = _top_level_param_call(_TRACK_KV, device_index=1, key="a")
    doomed = _nested_param_call(_TRACK_KV, device_index=1, device_path=_PATH, key="doomed")
    b = _top_level_param_call(_TRACK_KV, device_index=1, key="b")
    survivors, _ = partition_doomed_nested_writes([a, doomed, b], probe_fn=lambda r: 0)
    assert [c.key for c in survivors] == ["a", "b"]


def test_empty_call_list_is_a_noop():
    survivors, failures = partition_doomed_nested_writes([], probe_fn=lambda r: 0)
    assert survivors == []
    assert failures == []
