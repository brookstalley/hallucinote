"""PSH-3K9D: tests for the devices-phase diff-reconcile (skip-unchanged).

Three layers:
  * ``param_matches_live`` — the value comparison per wire form + every trap +
    the keep-on-doubt fallbacks (the safety law).
  * ``partition_unchanged_device_params`` — grouping, per-device single read,
    passthrough of non-param calls, keep-on-read-failure.
  * ``execute_push`` end-to-end — the devices phase dispatches 0 set_parameter
    when Live already matches, 1 when one param differs.
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from hallucinote.db import init_db, mutations as M
from hallucinote.sync import push, push_execute
from hallucinote.sync.push._core import build_node_addr
from hallucinote.sync.push.device_param_diff import (
    param_matches_live,
    partition_unchanged_device_params,
)


# ---------------------------------------------------------------------------
# param_matches_live — value comparison per wire form
# ---------------------------------------------------------------------------


def _row(*, value_display=None, value_items_json=None, value_raw=None,
         value_normalized=None):
    """A dict standing in for a device_parameters sqlite3.Row (same subscript
    access for the four columns param_matches_live reads)."""
    return {
        "value_display": value_display,
        "value_items_json": value_items_json,
        "value_raw": value_raw,
        "value_normalized": value_normalized,
    }


def test_enum_matches_on_equal_display():
    row = _row(value_items_json='["Lowpass","Highpass"]', value_display="Highpass")
    assert param_matches_live(row, {"value_display": "Highpass"}) is True


def test_enum_differs_on_other_display():
    row = _row(value_items_json='["Lowpass","Highpass"]', value_display="Highpass")
    assert param_matches_live(row, {"value_display": "Lowpass"}) is False


def test_enum_keeps_when_live_display_empty():
    row = _row(value_items_json='["A","B"]', value_display="B")
    # No usable live display -> can't prove equality -> keep.
    assert param_matches_live(row, {"value_display": ""}) is False


def test_value_raw_matches_within_tolerance():
    row = _row(value_raw=8.0, value_display="8.00 Hz")
    assert param_matches_live(row, {"value": 8.0}) is True
    assert param_matches_live(row, {"value": 8.0 + 1e-7}) is True  # float noise


def test_value_raw_differs_beyond_tolerance():
    row = _row(value_raw=8.0, value_display="8.00 Hz")
    assert param_matches_live(row, {"value": 9.0}) is False


def test_value_raw_takes_precedence_over_display():
    # value_raw is checked before display; a stale/garbage live display must not
    # rescue a mismatched raw.
    row = _row(value_raw=8.0, value_display="8.00 Hz")
    assert param_matches_live(row, {"value": 9.0, "value_display": "8.00 Hz"}) is False


def test_display_string_matches_exactly():
    row = _row(value_display="1.17 kHz", value_normalized=0.59)
    assert param_matches_live(row, {"value_display": "1.17 kHz"}) is True


def test_display_string_differs():
    row = _row(value_display="1.17 kHz", value_normalized=0.59)
    assert param_matches_live(row, {"value_display": "1.20 kHz"}) is False


def test_normalized_only_converts_via_min_max():
    row = _row(value_normalized=0.5)  # no display, no raw, no items
    live = {"value": 5.0, "min": 0.0, "max": 10.0}  # 0 + 0.5*(10-0) = 5.0
    assert param_matches_live(row, live) is True


def test_normalized_only_differs():
    row = _row(value_normalized=0.5)
    assert param_matches_live(row, {"value": 7.0, "min": 0.0, "max": 10.0}) is False


def test_normalized_keeps_when_min_max_missing():
    row = _row(value_normalized=0.5)
    # Can't compute a comparable raw without the range -> keep.
    assert param_matches_live(row, {"value": 5.0}) is False


def test_keeps_when_live_is_none():
    assert param_matches_live(_row(value_display="x"), None) is False


def test_keeps_when_no_writable_form():
    assert param_matches_live(_row(), {"value": 1.0, "value_display": "1"}) is False


# ---------------------------------------------------------------------------
# partition_unchanged_device_params — grouping, single read, passthrough
# ---------------------------------------------------------------------------


@dataclass
class _Call:
    tool: str
    args: dict
    key: str


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "diff.db")
    yield c
    c.close()


@pytest.fixture
def linked_device(conn):
    song = M.create_song(conn, name="t", key="Dm")
    session = M.create_ableton_session(conn, song_id=song, name="draft")
    track = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=track, ableton_index=5,
    )
    cid = M.create_device_chain(conn, parent_track_id=track)
    did = M.create_device(conn, chain_id=cid, position=1, kind="EQ Eight",
                          display_name="EQ")
    M.set_device_parameter(conn, device_id=did, name="Freq",
                           value_display="1.17 kHz", value_normalized=0.59)
    M.set_device_parameter(conn, device_id=did, name="Q",
                           value_display="46.1", value_normalized=0.46)
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="device", db_id=did, ableton_index=2,
    )
    return {"song": song, "session": session, "device_id": did}


def _param_calls(conn, song, session):
    plan = push.plan_push_devices(conn, song_id=song, session_id=session)
    return [c for c in plan.calls if c.args.get("action") == "set_parameter"]


def test_partition_skips_all_when_every_param_matches(conn, linked_device):
    calls = _param_calls(conn, linked_device["song"], linked_device["session"])
    assert len(calls) == 2
    reads: list = []

    def read_fn(node):
        reads.append(node)
        return {"parameters": [
            {"name": "Freq", "value_display": "1.17 kHz"},
            {"name": "Q", "value_display": "46.1"},
        ]}

    to_send, skipped = partition_unchanged_device_params(
        calls, conn=conn, read_fn=read_fn,
    )
    assert to_send == []
    assert {s["parameter_name"] for s in skipped} == {"Freq", "Q"}
    assert len(reads) == 1  # one batched read for the device, not one per param


def test_partition_keeps_only_the_changed_param(conn, linked_device):
    calls = _param_calls(conn, linked_device["song"], linked_device["session"])

    def read_fn(node):
        return {"parameters": [
            {"name": "Freq", "value_display": "2.00 kHz"},  # changed in Live
            {"name": "Q", "value_display": "46.1"},          # unchanged
        ]}

    to_send, skipped = partition_unchanged_device_params(
        calls, conn=conn, read_fn=read_fn,
    )
    assert [c.args["parameter_name"] for c in to_send] == ["Freq"]
    assert [s["parameter_name"] for s in skipped] == ["Q"]


def test_partition_keeps_all_when_read_fails(conn, linked_device):
    calls = _param_calls(conn, linked_device["song"], linked_device["session"])

    def read_fn(node):
        return None  # read failure -> keep everything (safety law)

    to_send, skipped = partition_unchanged_device_params(
        calls, conn=conn, read_fn=read_fn,
    )
    assert len(to_send) == 2
    assert skipped == []


def test_partition_keeps_param_absent_from_read(conn, linked_device):
    calls = _param_calls(conn, linked_device["song"], linked_device["session"])

    def read_fn(node):
        return {"parameters": [{"name": "Freq", "value_display": "1.17 kHz"}]}  # Q missing

    to_send, skipped = partition_unchanged_device_params(
        calls, conn=conn, read_fn=read_fn,
    )
    assert [c.args["parameter_name"] for c in to_send] == ["Q"]
    assert [s["parameter_name"] for s in skipped] == ["Freq"]


def test_partition_skips_nested_rack_param_by_its_own_device_id(conn):
    """A param on a device nested inside a rack is keyed by the NESTED device's
    id and addressed by a device_path node — the partition must group + read +
    compare it correctly (the repro's Instrument Rack is exactly this shape)."""
    song = M.create_song(conn, name="t", key="Dm")
    session = M.create_ableton_session(conn, song_id=song, name="draft")
    track = M.create_track(conn, song_id=song, track_index=1, name="Pad")
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=track, ableton_index=5,
    )
    top_chain = M.create_device_chain(conn, parent_track_id=track)
    rack = M.create_device(conn, chain_id=top_chain, position=1,
                           kind="Instrument Rack", display_name="Outer Rack")
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="device", db_id=rack, ableton_index=2,
    )
    nested_chain = M.create_device_chain(conn, parent_rack_device_id=rack, position=1)
    nested = M.create_device(conn, chain_id=nested_chain, position=1,
                             kind="Operator", display_name="Lead")
    M.set_device_parameter(conn, device_id=nested, name="Volume",
                           value_display="-6 dB", value_normalized=0.5)

    calls = _param_calls(conn, song, session)
    assert len(calls) == 1
    assert calls[0].key == f"device_parameter:{nested}:Volume"

    seen_nodes: list = []

    def read_fn(node):
        seen_nodes.append(node)
        return {"parameters": [{"name": "Volume", "value_display": "-6 dB"}]}

    to_send, skipped = partition_unchanged_device_params(
        calls, conn=conn, read_fn=read_fn,
    )
    assert to_send == []
    assert [s["parameter_name"] for s in skipped] == ["Volume"]
    # The read was issued against the nested device's path-bearing node.
    assert seen_nodes[0].get("path")


def test_partition_value_raw_path_compares_against_live_raw(conn):
    """A value_raw param (Wavetable LFO S. Rate shape) compares against Live's
    raw `value`, not a display string."""
    song = M.create_song(conn, name="t", key="Dm")
    session = M.create_ableton_session(conn, song_id=song, name="draft")
    track = M.create_track(conn, song_id=song, track_index=1, name="Synth")
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=track, ableton_index=5,
    )
    cid = M.create_device_chain(conn, parent_track_id=track)
    did = M.create_device(conn, chain_id=cid, position=1, kind="Wavetable",
                          display_name="WT")
    M.set_device_parameter(conn, device_id=did, name="LFO 1 S. Rate",
                           value_display="8.00", value_raw=8.0)
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="device", db_id=did, ableton_index=1,
    )
    calls = _param_calls(conn, song, session)
    assert len(calls) == 1

    # Live at the same raw -> skip; Live at a different raw -> keep.
    to_send, skipped = partition_unchanged_device_params(
        calls, conn=conn,
        read_fn=lambda node: {"parameters": [
            {"name": "LFO 1 S. Rate", "value": 8.0, "value_display": "8.00"},
        ]},
    )
    assert to_send == [] and len(skipped) == 1

    to_send, skipped = partition_unchanged_device_params(
        calls, conn=conn,
        read_fn=lambda node: {"parameters": [
            {"name": "LFO 1 S. Rate", "value": 4.0, "value_display": "4.00"},
        ]},
    )
    assert len(to_send) == 1 and skipped == []


def test_partition_passes_through_non_param_calls(conn, linked_device):
    load = _Call(tool="ableton_device",
                 args={"action": "load", "node": {}}, key="device:abc")
    chain = _Call(tool="ableton_device",
                  args={"action": "set_chain_property", "node": {}},
                  key="device_chain_props:xyz")

    def read_fn(node):
        raise AssertionError("read_fn must not be called for non-param calls")

    to_send, skipped = partition_unchanged_device_params(
        [load, chain], conn=conn, read_fn=read_fn,
    )
    assert to_send == [load, chain]
    assert skipped == []


# ---------------------------------------------------------------------------
# execute_push end-to-end — the wiring (read closure + filter + warning)
# ---------------------------------------------------------------------------


@dataclass
class _Resp:
    ok: bool
    result: dict | None = None
    error: str | None = None
    hint: str | None = None


def _devices_send_fn(live_params):
    """Fake send_fn: answers get_parameters with ``live_params`` (the modeled
    current Live values), acks everything else. Records call_log."""
    call_log: list = []

    def send(req, *, read_timeout=None):
        call_log.append({"tool": req.tool, "action": req.action,
                         "params": dict(req.params)})
        if req.tool == "ableton_device" and req.action == "get_parameters":
            return _Resp(ok=True, result={"parameters": live_params})
        return _Resp(ok=True, result={})

    send.call_log = call_log
    return send


@pytest.fixture
def state_dir(tmp_path):
    d = tmp_path / "state"
    d.mkdir()
    return d


def test_execute_devices_skips_all_when_live_matches(conn, linked_device, state_dir):
    send = _devices_send_fn([
        {"name": "Freq", "value_display": "1.17 kHz"},
        {"name": "Q", "value_display": "46.1"},
    ])
    result = push_execute.execute_push(
        conn=conn, song_id=linked_device["song"],
        session_id=linked_device["session"], state_dir=state_dir,
        send_fn=send, only="devices",
    )
    assert result.outcome == "ok"
    set_param_calls = [c for c in send.call_log if c["action"] == "set_parameter"]
    assert set_param_calls == []  # everything already current -> nothing written
    get_param_calls = [c for c in send.call_log if c["action"] == "get_parameters"]
    assert len(get_param_calls) == 1  # one batched read for the device
    assert any("already current" in w for w in result.warnings)


def test_execute_devices_writes_only_changed_param(conn, linked_device, state_dir):
    send = _devices_send_fn([
        {"name": "Freq", "value_display": "2.00 kHz"},  # differs from DB
        {"name": "Q", "value_display": "46.1"},          # matches DB
    ])
    result = push_execute.execute_push(
        conn=conn, song_id=linked_device["song"],
        session_id=linked_device["session"], state_dir=state_dir,
        send_fn=send, only="devices",
    )
    assert result.outcome == "ok"
    set_param_calls = [c for c in send.call_log if c["action"] == "set_parameter"]
    assert len(set_param_calls) == 1
    assert set_param_calls[0]["params"]["parameter_name"] == "Freq"
