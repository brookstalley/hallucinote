"""NODE-ADDR Chunk C — per-DrumChain capture: the non-default filter
(`chain_authored_props`), the snapshot-assemble attaching it, and the
capture->replay round-trip landing choke_group / out_note in the DB.

The filter mirrors the Chunk B param default-filter: a DrumChain stores only
non-default per-drum props (choke != 0, out_note != in_note); a plain
instrument-rack chain (no such attrs) stores nothing.
"""
from __future__ import annotations

import pytest

from hallucinote.capture import (
    assemble_snapshot_via_probes,
    chain_authored_props,
    replay_capture,
    _capture_nested_chains,
)
from hallucinote.db import init_db, mutations as M, queries as Q


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "test.db")
    yield c
    c.close()


# --------------------------------------------------------------------------
# chain_authored_props — the single non-default filter
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "entry,expected",
    [
        # plain instrument-rack chain — no drum attrs at all.
        ({"name": "808"}, {"choke_group": None, "out_note": None}),
        # choke 0 is Live's "no choke group" default -> dropped.
        ({"choke_group": 0, "out_note": 36, "in_note": 36},
         {"choke_group": None, "out_note": None}),
        # a real choke group is kept.
        ({"choke_group": 3, "out_note": 36, "in_note": 36},
         {"choke_group": 3, "out_note": None}),
        # out_note == in_note is the no-transpose identity -> dropped.
        ({"choke_group": 0, "out_note": 60, "in_note": 60},
         {"choke_group": None, "out_note": None}),
        # a real transpose is kept.
        ({"choke_group": 0, "out_note": 60, "in_note": 36},
         {"choke_group": None, "out_note": 60}),
        # both meaningful.
        ({"choke_group": 2, "out_note": 48, "in_note": 36},
         {"choke_group": 2, "out_note": 48}),
    ],
)
def test_chain_authored_props_filter(entry, expected):
    assert chain_authored_props(entry) == expected


def test_chain_authored_props_ignores_bools():
    # A stray bool must never be read as a 0/1 int prop.
    assert chain_authored_props({"choke_group": True, "out_note": False}) == {
        "choke_group": None, "out_note": None,
    }


def test_capture_nested_chains_attaches_only_nondefault_props():
    chains_tree = [
        {"chain_index": 1, "name": "Kick", "devices": [],
         "choke_group": 2, "out_note": 36, "in_note": 36},   # choke kept, out dropped
        {"chain_index": 2, "name": "OH", "devices": [],
         "choke_group": 1, "out_note": 60, "in_note": 36},   # both kept
        {"chain_index": 3, "name": "Clap", "devices": [],
         "choke_group": 0, "out_note": 40, "in_note": 40},   # both default -> none
    ]
    out = _capture_nested_chains(
        probe=lambda *a, **k: {"parameters": []},
        parent_kind="track", parent_index=2,
        top_device_index=1, chains_tree=chains_tree,
    )
    assert out[0].get("choke_group") == 2 and "out_note" not in out[0]
    assert out[1]["choke_group"] == 1 and out[1]["out_note"] == 60
    assert "choke_group" not in out[2] and "out_note" not in out[2]


# --------------------------------------------------------------------------
# capture -> replay round-trip (the props land in the DB)
# --------------------------------------------------------------------------

def _drum_rack_chains(conn, song_id):
    """The {position: chain_row} of the Drums track's drum-rack nested chains
    (skips the auto-created master track)."""
    track = next(
        t for t in Q.get_tracks_for_song(conn, song_id) if t["name"] == "Drums"
    )
    top = Q.get_device_chains_for_track(conn, track["id"])[0]
    rack = Q.get_devices_for_chain(conn, top["id"])[0]
    return {
        c["position"]: c
        for c in Q.get_device_chains_for_rack_device(conn, rack["id"])
    }


def _drum_probe(chains):
    """A fake-Live probe exposing one track with one Drum Rack whose chains are
    `chains` (each a get_device_chains entry dict). Empty device lists keep the
    walk to the chain level — Chunk C is about the chain, not its devices."""
    def probe(tool, action, **params):
        if (tool, action) == ("ableton_session", "info"):
            return {"tempo": 120.0,
                    "signature": {"numerator": 4, "denominator": 4},
                    "master": {"volume": 0.85, "panning": 0.0},
                    "track_count": 1, "return_count": 0}
        if (tool, action) == ("ableton_return", "list"):
            return {"returns": []}
        if (tool, action) == ("ableton_track", "info"):
            return {"track_index": params["track_index"], "name": "Drums",
                    "kind": "midi", "volume": 0.7, "panning": 0.0,
                    "mute": False, "solo": False, "arm": False}
        if (tool, action) == ("ableton_track", "get_sends"):
            return {"sends": []}
        if (tool, action) == ("ableton_device", "list"):
            if params.get("master"):
                return {"devices": []}
            return {"devices": [{
                "device_index": 1, "name": "Kit", "class_name": "DrumGroupDevice",
                "class_display_name": "Drum Rack", "is_active": True,
            }]}
        if (tool, action) == ("ableton_device", "get_device_chains"):
            return {"chains": chains}
        if (tool, action) == ("ableton_device", "pad_info"):
            return {"pads": []}  # Chunk C is about chains, not pad mappings
        if (tool, action) == ("ableton_device", "get_parameters"):
            return {"parameters": []}
        raise AssertionError(f"unrouted probe {tool}.{action} {params}")
    return probe


def test_capture_replay_lands_choke_and_out_note(conn):
    chains = [
        {"chain_index": 1, "name": "Kick", "device_count": 0, "devices": [],
         "is_muted": False, "is_soloed": False,
         "choke_group": 0, "out_note": 36, "in_note": 36},   # default -> NULL
        {"chain_index": 2, "name": "OH", "device_count": 0, "devices": [],
         "is_muted": False, "is_soloed": False,
         "choke_group": 1, "out_note": 36, "in_note": 36},   # choke 1
        {"chain_index": 3, "name": "Tom", "device_count": 0, "devices": [],
         "is_muted": False, "is_soloed": False,
         "choke_group": 0, "out_note": 67, "in_note": 45},   # transpose 67
    ]
    snap = assemble_snapshot_via_probes(_drum_probe(chains))
    # The snapshot carries the filtered props at the chain level.
    snap_chains = snap["tracks"][0]["devices"][0]["chains"]
    assert "choke_group" not in snap_chains[0] and "out_note" not in snap_chains[0]
    assert snap_chains[1]["choke_group"] == 1
    assert snap_chains[2]["out_note"] == 67

    song_id = replay_capture(conn, snap, song_name="dc")
    db_chains = _drum_rack_chains(conn, song_id)
    assert db_chains[1]["choke_group"] is None and db_chains[1]["out_note"] is None
    assert db_chains[2]["choke_group"] == 1
    assert db_chains[3]["out_note"] == 67


def test_re_replay_clears_a_dropped_prop(conn):
    """Re-replaying a snapshot that DROPPED a prop (now at the Live default)
    clears the stale DB value — replay is idempotent, the snapshot is truth."""
    with_choke = [{"chain_index": 1, "name": "OH", "device_count": 0,
                   "devices": [], "is_muted": False, "is_soloed": False,
                   "choke_group": 1, "out_note": 36, "in_note": 36}]
    snap1 = assemble_snapshot_via_probes(_drum_probe(with_choke))
    song_id = replay_capture(conn, snap1, song_name="dc")

    # The pad's choke was cleared in Live -> snapshot no longer carries it.
    no_choke = [{"chain_index": 1, "name": "OH", "device_count": 0,
                 "devices": [], "is_muted": False, "is_soloed": False,
                 "choke_group": 0, "out_note": 36, "in_note": 36}]
    snap2 = assemble_snapshot_via_probes(_drum_probe(no_choke))
    replay_capture(conn, snap2, song_name="dc")

    assert _drum_rack_chains(conn, song_id)[1]["choke_group"] is None
