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
# chain_authored_props — the single non-default filter (Chunk C + F)
# --------------------------------------------------------------------------

def _props(choke_group=None, out_note=None, mute=None, solo=None,
           volume=None, pan=None):
    """The full 6-key authored-props dict (all keys always present so a pull
    diff can clear any one back to its default)."""
    return {"choke_group": choke_group, "out_note": out_note,
            "mute": mute, "solo": solo, "volume": volume, "pan": pan}


@pytest.mark.parametrize(
    "entry,expected",
    [
        # plain instrument-rack chain — no drum attrs at all.
        ({"name": "808"}, _props()),
        # choke 0 is Live's "no choke group" default -> dropped.
        ({"choke_group": 0, "out_note": 36, "in_note": 36}, _props()),
        # a real choke group is kept.
        ({"choke_group": 3, "out_note": 36, "in_note": 36},
         _props(choke_group=3)),
        # out_note == in_note is the no-transpose identity -> dropped.
        ({"choke_group": 0, "out_note": 60, "in_note": 60}, _props()),
        # a real transpose is kept.
        ({"choke_group": 0, "out_note": 60, "in_note": 36},
         _props(out_note=60)),
        # both meaningful.
        ({"choke_group": 2, "out_note": 48, "in_note": 36},
         _props(choke_group=2, out_note=48)),
    ],
)
def test_chain_authored_props_filter(entry, expected):
    assert chain_authored_props(entry) == expected


def test_chain_authored_props_ignores_bools():
    # A stray bool must never be read as a 0/1 int prop.
    assert chain_authored_props(
        {"choke_group": True, "out_note": False}
    ) == _props()


@pytest.mark.parametrize(
    "entry,expected",
    [
        # NODE-ADDR Chunk F mixer state. mute/solo default off -> dropped.
        ({"is_muted": False, "is_soloed": False}, _props()),
        # a set mute/solo is stored as 1.
        ({"is_muted": True, "is_soloed": False}, _props(mute=1)),
        ({"is_muted": False, "is_soloed": True}, _props(solo=1)),
        # volume at its intrinsic default (within eps) -> dropped.
        ({"volume": 0.85, "volume_default": 0.85}, _props()),
        # volume off default -> kept.
        ({"volume": 0.5, "volume_default": 0.85}, _props(volume=0.5)),
        # pan centred at its default -> dropped; off-centre -> kept.
        ({"pan": 0.0, "pan_default": 0.0}, _props()),
        ({"pan": -0.5, "pan_default": 0.0}, _props(pan=-0.5)),
        # value present but NO default (param raised on default_value) ->
        # treated as default, NOT captured (mixer state must not over-capture).
        ({"volume": 0.5}, _props()),
        ({"pan": -0.5}, _props()),
        # a stray bool is never read as a mixer float.
        ({"volume": True, "pan": False}, _props()),
    ],
)
def test_chain_authored_props_mixer_filter(entry, expected):
    assert chain_authored_props(entry) == expected


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
        if (tool, action) == ("ableton_device", "get_input_routing"):
            return {"has_input_routing": False}
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


# --------------------------------------------------------------------------
# NODE-ADDR Chunk F — per-chain mixer state through the capture->replay path
# --------------------------------------------------------------------------

def test_capture_replay_lands_mixer_state(conn):
    chains = [
        # chain 1: muted + volume off default; pan centred (default).
        {"chain_index": 1, "name": "A", "device_count": 0, "devices": [],
         "is_muted": True, "is_soloed": False,
         "volume": 0.5, "volume_default": 0.85, "pan": 0.0, "pan_default": 0.0},
        # chain 2: soloed + pan off centre; volume at default.
        {"chain_index": 2, "name": "B", "device_count": 0, "devices": [],
         "is_muted": False, "is_soloed": True,
         "volume": 0.85, "volume_default": 0.85, "pan": -0.4, "pan_default": 0.0},
        # chain 3: everything at the default -> nothing stored.
        {"chain_index": 3, "name": "C", "device_count": 0, "devices": [],
         "is_muted": False, "is_soloed": False,
         "volume": 0.85, "volume_default": 0.85, "pan": 0.0, "pan_default": 0.0},
    ]
    snap = assemble_snapshot_via_probes(_drum_probe(chains))
    snap_chains = snap["tracks"][0]["devices"][0]["chains"]
    # chain 1: mute + volume kept; pan/solo at default -> absent.
    assert snap_chains[0]["mute"] == 1 and snap_chains[0]["volume"] == 0.5
    assert "pan" not in snap_chains[0] and "solo" not in snap_chains[0]
    # chain 2: solo + pan kept; volume/mute at default -> absent.
    assert snap_chains[1]["solo"] == 1 and snap_chains[1]["pan"] == -0.4
    assert "volume" not in snap_chains[1] and "mute" not in snap_chains[1]
    # chain 3: all default -> nothing.
    for k in ("mute", "solo", "volume", "pan"):
        assert k not in snap_chains[2]

    song_id = replay_capture(conn, snap, song_name="mx")
    db = _drum_rack_chains(conn, song_id)
    assert db[1]["mute"] == 1 and db[1]["volume"] == 0.5 and db[1]["pan"] is None
    assert db[2]["solo"] == 1 and db[2]["pan"] == -0.4 and db[2]["volume"] is None
    assert all(db[3][k] is None for k in ("mute", "solo", "volume", "pan"))


def test_re_replay_clears_dropped_mixer_state(conn):
    """A chain unmuted / returned to unity in Live drops the prop from the
    snapshot; re-replay clears the stale DB value (shared clear-on-None path)."""
    on = [{"chain_index": 1, "name": "A", "device_count": 0, "devices": [],
           "is_muted": True, "is_soloed": False,
           "volume": 0.4, "volume_default": 0.85, "pan": 0.0, "pan_default": 0.0}]
    song_id = replay_capture(conn, assemble_snapshot_via_probes(_drum_probe(on)),
                             song_name="mx")
    assert _drum_rack_chains(conn, song_id)[1]["mute"] == 1

    off = [{"chain_index": 1, "name": "A", "device_count": 0, "devices": [],
            "is_muted": False, "is_soloed": False,
            "volume": 0.85, "volume_default": 0.85, "pan": 0.0, "pan_default": 0.0}]
    replay_capture(conn, assemble_snapshot_via_probes(_drum_probe(off)),
                   song_name="mx")
    row = _drum_rack_chains(conn, song_id)[1]
    assert row["mute"] is None and row["volume"] is None
