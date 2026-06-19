"""replace_device_param_overrides — nested-param overrides on a preset device (SNP-2H9F).

The DB-storage half of "load instrument X from its portable preset_query, then
override nested param P": a replace-style, idempotent, content-change-detecting
mutator that rides DEVICE_PARAM_OVERRIDES_REPLACED (one coarse event per device,
mirroring drum_pad_mappings). Keyed by (device_id, descent path, name) because a
preset device has only its top-level row in the DB — no nested device row to key on.
"""
from __future__ import annotations

import json

import pytest

from hallucinote.db import init_db, mutations as M, queries as Q
from hallucinote.db import events as E


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "test.db")
    yield c
    c.close()


@pytest.fixture
def song(conn):
    return M.create_song(conn, name="t", key="Dm")


@pytest.fixture
def preset_device(conn, song):
    """A top-level instrument loaded via preset_query (its nested tree is NOT in
    the DB — the preset instantiates it at push time)."""
    track = M.create_track(conn, song_id=song, track_index=1, name="Lead")
    top_chain = M.create_device_chain(conn, parent_track_id=track, position=0)
    return M.create_device(
        conn, chain_id=top_chain, position=1,
        kind="Instrument Rack", display_name="Synth Vox Ai",
        preset_query={"root": "instruments", "pattern": "Synth Vox Ai"},
    )


# The swell witness: an LFO two levels deep, dialed Free->Tempo + rate 1/8->1/2.
DEEP = [{"chain_index": 1, "device_position": 1},
        {"chain_index": 1, "device_position": 1}]
OVERRIDES = [
    {"path": DEEP, "name": "LFO 1 Sync", "value_display": "Tempo",
     "value_items": ["Free", "Tempo"]},
    {"path": DEEP, "name": "LFO 1 S. Rate", "value_display": "1/2",
     "value_normalized": 0.38095238},
]


def _override_events(conn):
    return conn.execute(
        "SELECT payload_json, actor FROM events WHERE kind = ? ORDER BY seq",
        (E.DEVICE_PARAM_OVERRIDES_REPLACED,),
    ).fetchall()


def test_replace_inserts_rows_and_emits_one_event(conn, preset_device):
    ids = M.replace_device_param_overrides(
        conn, device_id=preset_device, overrides=OVERRIDES, actor="sync",
    )
    assert len(ids) == 2
    rows = Q.get_device_param_overrides(conn, preset_device)
    assert len(rows) == 2
    by_name = {r["name"]: r for r in rows}
    assert by_name["LFO 1 Sync"]["value_display"] == "Tempo"
    assert json.loads(by_name["LFO 1 Sync"]["value_items_json"]) == ["Free", "Tempo"]
    assert by_name["LFO 1 Sync"]["value_normalized"] is None
    assert json.loads(by_name["LFO 1 Sync"]["path_json"]) == DEEP
    assert by_name["LFO 1 S. Rate"]["value_display"] == "1/2"
    assert by_name["LFO 1 S. Rate"]["value_normalized"] == pytest.approx(0.38095238)
    assert by_name["LFO 1 S. Rate"]["value_items_json"] is None
    events = _override_events(conn)
    assert len(events) == 1
    payload = json.loads(events[0]["payload_json"])
    assert payload["device_id"] == preset_device
    assert payload["prev_count"] == 0 and payload["new_count"] == 2
    assert events[0]["actor"] == "sync"


def test_query_orders_by_path_then_name(conn, preset_device):
    shallow = [{"chain_index": 1, "device_position": 1}]
    M.replace_device_param_overrides(conn, device_id=preset_device, overrides=[
        {"path": DEEP, "name": "B", "value_display": "1"},
        {"path": shallow, "name": "Z", "value_display": "1"},
        {"path": shallow, "name": "A", "value_display": "1"},
    ])
    rows = Q.get_device_param_overrides(conn, preset_device)
    # path_json sorts the shallow ("[{...}]") before the deep ("[{...},{...}]")
    # only by string order — assert (path, name) tuples come back sorted.
    got = [(r["path_json"], r["name"]) for r in rows]
    assert got == sorted(got)


def test_idempotent_replace_no_new_event(conn, preset_device):
    ids1 = M.replace_device_param_overrides(
        conn, device_id=preset_device, overrides=OVERRIDES)
    ids2 = M.replace_device_param_overrides(
        conn, device_id=preset_device, overrides=OVERRIDES)
    assert ids1 == ids2  # same rows preserved, not re-inserted
    assert len(_override_events(conn)) == 1


def test_replace_clears_vanished_overrides(conn, preset_device):
    M.replace_device_param_overrides(
        conn, device_id=preset_device, overrides=OVERRIDES)
    # Re-replace with only the first — the second is dropped.
    M.replace_device_param_overrides(
        conn, device_id=preset_device, overrides=[OVERRIDES[0]])
    rows = Q.get_device_param_overrides(conn, preset_device)
    assert [r["name"] for r in rows] == ["LFO 1 Sync"]
    assert len(_override_events(conn)) == 2


def test_replace_empty_clears_all_and_emits(conn, preset_device):
    M.replace_device_param_overrides(
        conn, device_id=preset_device, overrides=OVERRIDES)
    M.replace_device_param_overrides(
        conn, device_id=preset_device, overrides=[])
    assert Q.get_device_param_overrides(conn, preset_device) == []
    events = _override_events(conn)
    assert len(events) == 2
    assert json.loads(events[1]["payload_json"]) == {
        "device_id": preset_device, "prev_count": 2, "new_count": 0,
        "override_ids": [],
    }


def test_value_change_re_emits(conn, preset_device):
    M.replace_device_param_overrides(
        conn, device_id=preset_device, overrides=OVERRIDES)
    changed = [OVERRIDES[0], {**OVERRIDES[1], "value_display": "1/4"}]
    M.replace_device_param_overrides(
        conn, device_id=preset_device, overrides=changed)
    rows = {r["name"]: r for r in Q.get_device_param_overrides(conn, preset_device)}
    assert rows["LFO 1 S. Rate"]["value_display"] == "1/4"
    assert len(_override_events(conn)) == 2


def test_empty_path_rejected(conn, preset_device):
    with pytest.raises(ValueError, match="non-empty"):
        M.replace_device_param_overrides(conn, device_id=preset_device, overrides=[
            {"path": [], "name": "X", "value_display": "1"}])


@pytest.mark.parametrize("bad_step", [
    {"device_position": 1},                       # missing chain_index
    {"chain_index": 1},                           # missing device_position
    {"chain_index": 0, "device_position": 1},     # chain_index < 1
    {"chain_index": 1, "device_position": 0},     # device_position < 1
    {"chain_index": True, "device_position": 1},  # bool is not a valid int
])
def test_bad_path_step_rejected(conn, preset_device, bad_step):
    with pytest.raises(ValueError):
        M.replace_device_param_overrides(conn, device_id=preset_device, overrides=[
            {"path": [bad_step], "name": "X", "value_display": "1"}])


def test_value_normalized_out_of_range_rejected(conn, preset_device):
    with pytest.raises(ValueError, match="out of range"):
        M.replace_device_param_overrides(conn, device_id=preset_device, overrides=[
            {"path": DEEP, "name": "X", "value_display": "1", "value_normalized": 1.5}])


def test_empty_value_items_rejected(conn, preset_device):
    with pytest.raises(ValueError, match="ambiguous"):
        M.replace_device_param_overrides(conn, device_id=preset_device, overrides=[
            {"path": DEEP, "name": "X", "value_display": "1", "value_items": []}])


# --- DEV-4P7R: the raw channel for a nested override ---

def test_value_raw_override_stored_unclamped(conn, preset_device):
    """The witness LFO S. Rate (raw 8.0, range [0,21]) stores on the raw channel
    — value_raw UNCLAMPED, value_normalized NULL, display kept as a hint."""
    M.replace_device_param_overrides(conn, device_id=preset_device, overrides=[
        {"path": DEEP, "name": "LFO 1 S. Rate", "value_display": "1/2",
         "value_raw": 8.0}])
    row = Q.get_device_param_overrides(conn, preset_device)[0]
    assert row["value_raw"] == pytest.approx(8.0)
    assert row["value_normalized"] is None
    assert row["value_display"] == "1/2"


def test_value_raw_override_idempotent_no_new_event(conn, preset_device):
    """The dedup signature includes value_raw, so re-replacing an identical raw
    override is a no-op (no second event)."""
    ov = [{"path": DEEP, "name": "LFO 1 S. Rate", "value_display": "1/2",
           "value_raw": 8.0}]
    M.replace_device_param_overrides(conn, device_id=preset_device, overrides=ov)
    M.replace_device_param_overrides(conn, device_id=preset_device, overrides=ov)
    assert len(_override_events(conn)) == 1


def test_value_raw_change_re_emits(conn, preset_device):
    """A value_raw change (display unchanged) is a content change → new event."""
    M.replace_device_param_overrides(conn, device_id=preset_device, overrides=[
        {"path": DEEP, "name": "LFO 1 S. Rate", "value_display": "1/2",
         "value_raw": 8.0}])
    M.replace_device_param_overrides(conn, device_id=preset_device, overrides=[
        {"path": DEEP, "name": "LFO 1 S. Rate", "value_display": "1/2",
         "value_raw": 4.0}])
    assert len(_override_events(conn)) == 2


def test_value_raw_override_rejects_normalized_pair(conn, preset_device):
    with pytest.raises(ValueError, match="mutually exclusive"):
        M.replace_device_param_overrides(conn, device_id=preset_device, overrides=[
            {"path": DEEP, "name": "X", "value_display": "1",
             "value_raw": 8.0, "value_normalized": 0.38}])


def test_value_raw_override_rejects_enum_pair(conn, preset_device):
    with pytest.raises(ValueError, match="continuous"):
        M.replace_device_param_overrides(conn, device_id=preset_device, overrides=[
            {"path": DEEP, "name": "X", "value_display": "Tempo",
             "value_raw": 1.0, "value_items": ["Free", "Tempo"]}])


def test_duplicate_path_name_rejected(conn, preset_device):
    with pytest.raises(ValueError, match="duplicate"):
        M.replace_device_param_overrides(conn, device_id=preset_device, overrides=[
            {"path": DEEP, "name": "X", "value_display": "1"},
            {"path": DEEP, "name": "X", "value_display": "2"}])


def test_path_canonicalized_extra_keys_dropped(conn, preset_device):
    M.replace_device_param_overrides(conn, device_id=preset_device, overrides=[
        {"path": [{"chain_index": 1, "device_position": 1, "name": "noise"}],
         "name": "X", "value_display": "1"}])
    row = Q.get_device_param_overrides(conn, preset_device)[0]
    assert json.loads(row["path_json"]) == [{"chain_index": 1, "device_position": 1}]


def test_cascade_delete_with_device(conn, preset_device):
    M.replace_device_param_overrides(
        conn, device_id=preset_device, overrides=OVERRIDES)
    M.delete_device(conn, device_id=preset_device)
    assert Q.get_device_param_overrides(conn, preset_device) == []


def test_sync_override_protects_preset_device_from_tombstone(conn):
    """SNP-2H9F (mirrors RTE-1K9T): a build-owned preset device that later receives
    a pulled nested-param override (actor='sync') must NOT be tombstoned when a
    later build drops it — `device_param_overrides_replaced` registers as a
    non-build touch on the device. Without it the device + the user's by-ear
    override would be silently CASCADE-deleted."""
    with M.build_session(conn, song_name="s"):
        sid = M.create_song(conn, name="s")
        tid = M.create_track(conn, song_id=sid, track_index=1, name="Lead")
        ch = M.create_device_chain(conn, parent_track_id=tid, position=0)
        did = M.create_device(
            conn, chain_id=ch, position=1, kind="Instrument Rack",
            display_name="Synth Vox Ai",
            preset_query={"root": "instruments", "pattern": "Synth Vox Ai"})
    # A pull lands a nested override on the preset device (actor='sync').
    M.replace_device_param_overrides(
        conn, device_id=did, actor="sync",
        overrides=[{"path": [{"chain_index": 1, "device_position": 1}],
                    "name": "LFO 1 Sync", "value_display": "Tempo"}])

    # Re-build keeps the track + its chain but drops the device.
    with M.build_session(conn, song_name="s"):
        M.create_song(conn, name="s")
        tid2 = M.create_track(conn, song_id=sid, track_index=1, name="Lead")
        M.create_device_chain(conn, parent_track_id=tid2, position=0)

    devices = Q.get_devices_for_track(conn, tid)
    survivors = [d for d in devices if d["display_name"] == "Synth Vox Ai"]
    assert survivors, "sync param override must protect the device from tombstoning"
    assert Q.get_device_param_overrides(conn, survivors[0]["id"]), \
        "the protected device keeps its pulled override"
