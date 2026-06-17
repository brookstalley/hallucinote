"""SNP-2H9F — nested-param overrides on a preset_query device, across the
snapshot->replay->push round-trip.

The durability gap: a by-ear tweak deep inside a rack loaded via `preset_query`
reverted on every from-scratch rebuild because the snapshot had no shape for
"load X from its portable preset, then override nested param P". This exercises
the new `param_overrides` representation: replay lands it in the DB keeping
`preset_query` intact, and push re-asserts each override at its NodeAddr path
after the preset loads (no chain creation -> the preset's timbre survives).
"""
from __future__ import annotations

import json

import pytest

from hallucinote.capture import (
    assemble_snapshot_via_probes,
    compile_snapshot,
    preserve_preset_overrides,
    replay_capture,
    _chains_carry_props,
    _flatten_chains_to_overrides,
)
from hallucinote.db import init_db, mutations as M, queries as Q
from hallucinote.sync import push
from hallucinote.sync.push._core import build_node_addr


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "test.db")
    yield c
    c.close()


# The swell witness: a Wavetable LFO two levels deep inside "Synth Vox Ai".
DEEP = [{"chain_index": 1, "device_position": 1},
        {"chain_index": 1, "device_position": 1}]


def _preset_track(*, param_overrides=None, chains=None, preset_query=True):
    dev = {"index": 1, "class": "Instrument Rack", "name": "Synth Vox Ai"}
    if preset_query:
        dev["preset_query"] = {"root": "instruments", "pattern": "Synth Vox Ai"}
    if param_overrides is not None:
        dev["param_overrides"] = param_overrides
    if chains is not None:
        dev["chains"] = chains
    return {"index": 1, "name": "Lead", "type": "midi", "devices": [dev]}


def _snapshot(track):
    return compile_snapshot(
        session_info={"tempo": 120.0, "signature": "4/4", "master": None},
        returns=[], tracks=[track],
    )


def _preset_device(conn, song_id):
    track = Q.get_tracks_for_song(conn, song_id)[0]
    return Q.get_devices_for_track(conn, track["id"])[0]


def test_replay_lands_param_overrides_keeping_preset_query(conn):
    ovr = [
        {"path": DEEP, "name": "LFO 1 Sync", "value": "Tempo",
         "value_items": ["Free", "Tempo"]},
        {"path": DEEP, "name": "LFO 1 S. Rate", "value": "1/2",
         "normalized": 0.38095238},
    ]
    song_id = replay_capture(
        conn, _snapshot(_preset_track(param_overrides=ovr)), song_name="po")
    dev = _preset_device(conn, song_id)
    # The portable seed survives — replay did NOT drop it for a chains dump.
    assert dev["preset_query"] is not None
    rows = {r["name"]: r for r in Q.get_device_param_overrides(conn, dev["id"])}
    assert json.loads(rows["LFO 1 Sync"]["path_json"]) == DEEP
    assert rows["LFO 1 Sync"]["value_display"] == "Tempo"
    assert json.loads(rows["LFO 1 Sync"]["value_items_json"]) == ["Free", "Tempo"]
    assert rows["LFO 1 S. Rate"]["value_normalized"] == pytest.approx(0.38095238)


def test_replay_chains_and_overrides_conflict_raises(conn):
    snap = _snapshot(_preset_track(
        param_overrides=[{"path": DEEP, "name": "X", "value": "1"}],
        chains=[{"chain_index": 1, "name": "c", "devices": []}],
        preset_query=False,
    ))
    with pytest.raises(ValueError, match="contradictory"):
        replay_capture(conn, snap, song_name="conf")


def test_re_replay_clears_a_dropped_override(conn):
    ovr = [{"path": DEEP, "name": "A", "value": "1"},
           {"path": DEEP, "name": "B", "value": "2"}]
    song_id = replay_capture(
        conn, _snapshot(_preset_track(param_overrides=ovr)), song_name="rr")
    # Re-replay the same song with B dropped (e.g. returned to default).
    replay_capture(
        conn, _snapshot(_preset_track(param_overrides=[ovr[0]])), song_name="rr")
    dev = _preset_device(conn, song_id)
    assert [r["name"] for r in Q.get_device_param_overrides(conn, dev["id"])] == ["A"]


def test_roundtrip_override_pushes_at_nested_path(conn):
    """The durability signal: snapshot(preset_query + param_overrides) -> replay
    -> push re-emits each override as a node-addressed set_parameter at its
    NodeAddr path AND loads the device from preset_query (no chain creation)."""
    ovr = [
        {"path": DEEP, "name": "LFO 1 Sync", "value": "Tempo",
         "value_items": ["Free", "Tempo"]},
        {"path": DEEP, "name": "LFO 1 S. Rate", "value": "1/2",
         "normalized": 0.38095238},
    ]
    song_id = replay_capture(
        conn, _snapshot(_preset_track(param_overrides=ovr)), song_name="rt")
    session = M.create_ableton_session(conn, song_id=song_id, name="draft")
    track = Q.get_tracks_for_song(conn, song_id)[0]
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=track["id"],
        ableton_index=3,
    )
    dev = Q.get_devices_for_track(conn, track["id"])[0]
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="device", db_id=dev["id"],
        ableton_index=1,
    )

    plan = push.plan_push_devices(conn, song_id=song_id, session_id=session)

    # The device is linked, so push re-asserts the overrides (no reload). Crucially
    # NOTHING creates a chain — the override rides set_parameter on the
    # preset-instantiated descendant, so the preset's waveform/samples survive.
    assert not any(c.args.get("action") == "create_device_chain"
                   for c in plan.calls)
    sets = [c for c in plan.calls if c.args.get("action") == "set_parameter"]
    expected_node = build_node_addr({"track_index": 3}, device_index=1,
                                    device_path=DEEP)
    assert {c.args["parameter_name"] for c in sets} == {"LFO 1 Sync", "LFO 1 S. Rate"}
    for c in sets:
        assert c.args["node"] == expected_node
    sync = next(c for c in sets if c.args["parameter_name"] == "LFO 1 Sync")
    assert sync.args["value"] == "Tempo" and sync.args["value_type"] == "enum"


# --------------------------------------------------------------------------
# preserve_preset_overrides / _flatten / _chains_carry_props — the transform
# --------------------------------------------------------------------------

def _new_with_chains(chains, *, cls="Instrument Rack", extra=None):
    """A freshly-captured snapshot (no preset_query yet) — one track, one rack
    device carrying the given `chains` dump."""
    dev = {"index": 1, "class": cls, "name": "Synth Vox Ai", "chains": chains}
    if extra:
        dev.update(extra)
    return {"tracks": [{"index": 1, "name": "Lead", "devices": [dev]}],
            "returns": []}


def _old_with_preset(*, cls="Instrument Rack", pq=None):
    pq = pq or {"root": "instruments", "pattern": "Synth Vox Ai"}
    return {"tracks": [{"index": 1, "name": "Lead", "devices": [
        {"index": 1, "class": cls, "name": "Synth Vox Ai", "preset_query": pq}]}],
        "returns": []}


def test_flatten_chains_to_overrides_depth2_path():
    chains = [{"chain_index": 1, "name": "", "devices": [{
        "index": 1, "class": "Instrument Rack", "name": "inner",
        "chains": [{"chain_index": 1, "name": "", "devices": [{
            "index": 1, "class": "Wavetable", "name": "WT",
            "params_dialed": {"LFO 1 Sync": {"value": "Tempo",
                                             "value_items": ["Free", "Tempo"]}},
        }]}],
    }]}]
    assert _flatten_chains_to_overrides(chains, []) == [
        {"path": [{"chain_index": 1, "device_position": 1},
                  {"chain_index": 1, "device_position": 1}],
         "name": "LFO 1 Sync", "value": "Tempo",
         "value_items": ["Free", "Tempo"]}]


def test_chains_carry_props_detects_nested_choke():
    plain = [{"chain_index": 1, "devices": [
        {"index": 1, "class": "X", "params_dialed": {"a": {"value": "1"}}}]}]
    assert _chains_carry_props(plain) is False
    drum = [{"chain_index": 1, "choke_group": 2, "devices": []}]
    assert _chains_carry_props(drum) is True


def test_preserve_converts_preset_device_chains_to_overrides():
    new = _new_with_chains([{"chain_index": 1, "name": "", "devices": [{
        "index": 1, "class": "Wavetable", "name": "WT",
        "params_dialed": {"Cutoff": {"value": "1 kHz", "normalized": 0.6}}}]}])
    preserve_preset_overrides(_old_with_preset(), new)
    dev = new["tracks"][0]["devices"][0]
    assert "chains" not in dev
    assert dev["preset_query"] == {"root": "instruments", "pattern": "Synth Vox Ai"}
    assert dev["param_overrides"] == [
        {"path": [{"chain_index": 1, "device_position": 1}],
         "name": "Cutoff", "value": "1 kHz", "normalized": 0.6}]


def test_preserve_leaves_non_preset_device_alone():
    new = _new_with_chains([{"chain_index": 1, "devices": [
        {"index": 1, "class": "X", "params_dialed": {"a": {"value": "1"}}}]}])
    # The old snapshot has NO preset_query for this device.
    preserve_preset_overrides({"tracks": [], "returns": []}, new)
    dev = new["tracks"][0]["devices"][0]
    assert "chains" in dev and "param_overrides" not in dev
    assert "preset_query" not in dev


def test_preserve_class_mismatch_does_not_carry():
    """A different device now sits at the slot (class changed) — don't carry the
    stale preset seed or convert."""
    new = _new_with_chains([], cls="Operator")  # was Instrument Rack
    preserve_preset_overrides(_old_with_preset(cls="Instrument Rack"), new)
    dev = new["tracks"][0]["devices"][0]
    assert "preset_query" not in dev


def test_preserve_keeps_chains_and_warns_on_chain_props():
    """A preset device whose dump carries authored per-chain props can't ride
    param_overrides — keep the chains dump, warn, don't carry preset_query."""
    new = _new_with_chains([{"chain_index": 1, "choke_group": 3, "devices": []}])
    with pytest.warns(UserWarning, match="per-chain props"):
        preserve_preset_overrides(_old_with_preset(), new)
    dev = new["tracks"][0]["devices"][0]
    assert "chains" in dev and "param_overrides" not in dev
    assert "preset_query" not in dev


def test_preserve_preset_device_with_no_deltas_just_carries_seed():
    new = _new_with_chains([{"chain_index": 1, "devices": [
        {"index": 1, "class": "Wavetable", "name": "WT"}]}])  # no params_dialed
    preserve_preset_overrides(_old_with_preset(), new)
    dev = new["tracks"][0]["devices"][0]
    assert "chains" not in dev and "param_overrides" not in dev
    assert dev["preset_query"] is not None


# --------------------------------------------------------------------------
# Capture acquisition (full probe walk) + the acquisition->push round-trip
# --------------------------------------------------------------------------

class _PresetProbe:
    """A small live set: track 'Lead' with one Instrument Rack loaded via a
    preset, a nested rack, and a Wavetable two levels down carrying one dialed
    (non-default) LFO param."""

    def __init__(self):
        self.calls = []

    def __call__(self, tool, action, **params):
        self.calls.append((tool, action, dict(params)))
        if (tool, action) == ("ableton_session", "info"):
            return {"tempo": 120.0, "signature": {"numerator": 4, "denominator": 4},
                    "master": {"volume": 0.85, "panning": 0.0},
                    "track_count": 1, "return_count": 0}
        if (tool, action) == ("ableton_return", "list"):
            return {"returns": []}
        if (tool, action) == ("ableton_track", "info"):
            return {"track_index": params["track_index"], "name": "Lead",
                    "kind": "midi", "volume": 0.7, "panning": 0.0,
                    "mute": False, "solo": False, "arm": False}
        if (tool, action) == ("ableton_track", "get_sends"):
            return {"sends": []}
        if (tool, action) == ("ableton_device", "list"):
            if params.get("master"):
                return {"devices": []}
            return {"devices": [{
                "device_index": 1, "name": "Synth Vox Ai",
                "class_name": "InstrumentGroupDevice",
                "class_display_name": "Instrument Rack", "is_active": True}]}
        if (tool, action) == ("ableton_device", "get_device_chains"):
            return {"chains": [{"chain_index": 1, "name": "", "devices": [{
                "position": 1, "name": "inner",
                "class_name": "InstrumentGroupDevice",
                "class_display_name": "Instrument Rack", "is_rack": True,
                "device_path": [{"chain_index": 1, "device_position": 1}],
                "chains": [{"chain_index": 1, "name": "", "devices": [{
                    "position": 1, "name": "WT", "class_name": "Wavetable",
                    "class_display_name": "Wavetable", "is_rack": False,
                    "device_path": [{"chain_index": 1, "device_position": 1},
                                    {"chain_index": 1, "device_position": 1}],
                }]}],
            }]}]}
        if (tool, action) == ("ableton_device", "get_parameters"):
            depth = len(params["node"].get("path") or [])
            if depth == 2:
                return {"parameters": [{
                    "name": "LFO 1 Sync", "value": 1.0, "value_display": "Tempo",
                    "default_value": 0.0, "min": 0.0, "max": 1.0, "is_enum": True,
                    "value_items": ["Free", "Tempo"]}]}
            return {"parameters": []}
        raise AssertionError(f"unrouted probe {tool}.{action} {params}")


_PRESET_PQ = {"root": "instruments", "pattern": "Synth Vox Ai"}
_OLD_SNAP = compile_snapshot(
    session_info={"tempo": 120.0, "signature": "4/4", "master": None},
    returns=[],
    tracks=[{"index": 1, "name": "Lead", "type": "midi", "devices": [
        {"index": 1, "class": "Instrument Rack", "name": "Synth Vox Ai",
         "preset_query": _PRESET_PQ}]}],
)


def test_capture_preset_device_emits_overrides_not_chains():
    new = assemble_snapshot_via_probes(_PresetProbe(), old_snapshot=_OLD_SNAP)
    dev = new["tracks"][0]["devices"][0]
    assert "chains" not in dev
    assert dev["preset_query"] == _PRESET_PQ
    assert dev["param_overrides"] == [
        {"path": [{"chain_index": 1, "device_position": 1},
                  {"chain_index": 1, "device_position": 1}],
         "name": "LFO 1 Sync", "value": "Tempo",
         "value_items": ["Free", "Tempo"]}]


def test_capture_without_old_snapshot_keeps_chains_dump():
    """No old snapshot -> capture can't know the device is preset-seeded, so the
    full chains dump stands (the pre-SNP-2H9F behavior; the seed is restored only
    when a prior snapshot recorded it)."""
    new = assemble_snapshot_via_probes(_PresetProbe())
    dev = new["tracks"][0]["devices"][0]
    assert "chains" in dev and "param_overrides" not in dev


def test_capture_to_push_roundtrip_preset_override(conn):
    """The SNP-2H9F verifiable signal end-to-end at unit level: fake-Live probe
    -> capture (preset device -> preset_query + param_overrides) -> replay -> DB
    -> push re-emits the depth-2 override as a node-addressed set_parameter. The
    deep by-ear tweak survives a from-scratch rebuild without dropping the seed."""
    new = assemble_snapshot_via_probes(_PresetProbe(), old_snapshot=_OLD_SNAP)
    song_id = replay_capture(conn, new, song_name="rt2")
    session = M.create_ableton_session(conn, song_id=song_id, name="draft")
    track = next(t for t in Q.get_tracks_for_song(conn, song_id)
                 if t["name"] == "Lead")
    M.link_db_to_ableton(conn, session_id=session, db_kind="track",
                         db_id=track["id"], ableton_index=3)
    dev = Q.get_devices_for_track(conn, track["id"])[0]
    assert dev["preset_query"] is not None
    M.link_db_to_ableton(conn, session_id=session, db_kind="device",
                         db_id=dev["id"], ableton_index=1)

    plan = push.plan_push_devices(conn, song_id=song_id, session_id=session)
    assert not any(c.args.get("action") == "create_device_chain" for c in plan.calls)
    sets = [c for c in plan.calls if c.args.get("action") == "set_parameter"]
    assert len(sets) == 1
    c = sets[0]
    assert c.args["node"] == build_node_addr(
        {"track_index": 3}, device_index=1,
        device_path=[{"chain_index": 1, "device_position": 1},
                     {"chain_index": 1, "device_position": 1}])
    assert c.args["parameter_name"] == "LFO 1 Sync"
    assert c.args["value"] == "Tempo" and c.args["value_type"] == "enum"


# --------------------------------------------------------------------------
# Push override error paths — never a silent drop (operator ALERT)
# --------------------------------------------------------------------------

def _linked_preset_device(conn):
    """A preset device replayed + linked in a session, ready for push."""
    song_id = replay_capture(conn, _snapshot(_preset_track()), song_name="pe")
    session = M.create_ableton_session(conn, song_id=song_id, name="d")
    track = Q.get_tracks_for_song(conn, song_id)[0]
    M.link_db_to_ableton(conn, session_id=session, db_kind="track",
                         db_id=track["id"], ableton_index=2)
    dev = Q.get_devices_for_track(conn, track["id"])[0]
    M.link_db_to_ableton(conn, session_id=session, db_kind="device",
                         db_id=dev["id"], ableton_index=1)
    return song_id, session, dev


def test_push_override_with_no_writable_form_alerts(conn):
    """An override with no display string and no normalized value can't be pushed
    — surface an operator ALERT, never a silent drop."""
    song_id, session, dev = _linked_preset_device(conn)
    M.replace_device_param_overrides(conn, device_id=dev["id"], overrides=[
        {"path": DEEP, "name": "Ghost", "value_display": ""}])
    plan = push.plan_push_devices(conn, song_id=song_id, session_id=session)
    assert not any(c.args.get("action") == "set_parameter" for c in plan.calls)
    assert any("no writable form" in a for a in plan.alerts)


def test_push_override_with_malformed_path_alerts(conn):
    """Defensive: the mutator never writes invalid path JSON, but a hand-edited /
    migrated row might — push alerts and skips it rather than crashing the plan."""
    song_id, session, dev = _linked_preset_device(conn)
    conn.execute(
        "INSERT INTO device_param_overrides "
        "(id, device_id, path_json, name, value_display) "
        "VALUES ('bad1', ?, '{not json', 'P', 'Tempo')", (dev["id"],))
    plan = push.plan_push_devices(conn, song_id=song_id, session_id=session)
    assert not any(c.args.get("action") == "set_parameter" for c in plan.calls)
    assert any("malformed path" in a for a in plan.alerts)
