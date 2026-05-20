"""Tests for capture.replay_capture and compile_snapshot."""
from __future__ import annotations

import pytest

from hallucinote.capture import (
    capture_plan, compile_snapshot, replay_capture,
    strip_return_slot_prefix,
)
from hallucinote.db import init_db, mutations as M, queries as Q


# ---------- W4-C: strip_return_slot_prefix ----------


@pytest.mark.parametrize("inp,expected", [
    ("A-Reverb", "Reverb"),
    ("B-Delay", "Delay"),
    ("Z-Bus", "Bus"),
    # idempotent: already-stripped name passes through
    ("Reverb", "Reverb"),
    # only strips ONCE: "A-B-Comp" -> "B-Comp", not "Comp"
    ("A-B-Comp", "B-Comp"),
    # multi-letter first segment is NOT a slot prefix; pass through
    ("Bus-A", "Bus-A"),
    ("Ghost-Reverb", "Ghost-Reverb"),
    # lowercase first letter is NOT a slot prefix; pass through
    ("a-mine", "a-mine"),
    # empty / None pass through
    ("", ""),
    (None, None),
])
def test_strip_return_slot_prefix(inp, expected):
    assert strip_return_slot_prefix(inp) == expected


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "cap.db")
    yield c
    c.close()


def test_replay_warns_when_stripping_slot_prefix(conn):
    """Wave 0 paper-cut: silent strips were a hand-authoring trap. Now warns."""
    snapshot = {
        "song": {"master": {"volume": 0.85, "panning": 0.0}},
        "returns": [
            {"index": 1, "name": "A-Reverb", "volume": 0.8, "panning": 0.0},
            {"index": 2, "name": "B-Delay", "volume": 0.7, "panning": 0.0},
        ],
        "tracks": [],
    }
    with pytest.warns(UserWarning, match=r"stripped Live's <letter>- slot prefix"):
        replay_capture(conn, snapshot, song_name="stripwarn")
    # Both originals appear in the message so the author sees what got changed.
    with pytest.warns(UserWarning, match=r"'A-Reverb'.*'Reverb'"):
        replay_capture(conn, snapshot, song_name="stripwarn2")
    with pytest.warns(UserWarning, match=r"'B-Delay'.*'Delay'"):
        replay_capture(conn, snapshot, song_name="stripwarn3")


def test_replay_does_not_warn_when_no_strip_needed(conn, recwarn):
    """No prefixed returns -> no warning."""
    snapshot = {
        "song": {"master": {"volume": 0.85, "panning": 0.0}},
        "returns": [
            {"index": 1, "name": "Reverb", "volume": 0.8, "panning": 0.0},
            {"index": 2, "name": "Bus-A", "volume": 0.7, "panning": 0.0},  # not stripped
        ],
        "tracks": [],
    }
    replay_capture(conn, snapshot, song_name="nostrip")
    strip_warnings = [
        w for w in recwarn.list
        if issubclass(w.category, UserWarning)
        and "slot prefix" in str(w.message)
    ]
    assert strip_warnings == []


def _sample_snapshot() -> dict:
    return {
        "song": {
            "tempo": 132.0,
            "signature": "4/4",
            "master": {"volume": 0.85, "panning": 0.0},
        },
        "returns": [
            {"index": 1, "name": "A-Reverb", "volume": 0.85, "panning": 0.0},
            {"index": 2, "name": "B-Delay", "volume": 0.85, "panning": 0.0},
        ],
        "tracks": [
            {
                "index": 5, "name": "01 Drums", "type": "midi",
                "volume": 0.6249, "panning": 0.0,
                "sends": {"A-Reverb": 0.0, "B-Delay": 0.1},
            },
            {
                "index": 9, "name": "05 Chorus Pluck", "type": "midi",
                "volume": 0.8149, "panning": 0.25,
                "sends": {"A-Reverb": 0.0, "B-Delay": 0.0},
            },
        ],
    }


def test_replay_creates_song_master_returns_tracks_sends(conn):
    sid = replay_capture(conn, _sample_snapshot(), song_name="t", song_key="Dm")
    song = Q.get_song_by_name(conn, "t")
    assert song["id"] == sid
    assert song["key"] == "Dm"

    tracks = Q.get_tracks_for_song(conn, sid)
    # 2 captured tracks + 1 master row
    assert len(tracks) == 3
    by_name = {t["name"]: t for t in tracks}
    assert by_name["Master"]["kind"] == "master"
    assert by_name["Master"]["volume"] == pytest.approx(0.85)
    assert by_name["Master"]["track_index"] == 0
    assert by_name["01 Drums"]["kind"] == "midi"
    assert by_name["01 Drums"]["volume"] == pytest.approx(0.6249)
    assert by_name["05 Chorus Pluck"]["pan"] == pytest.approx(0.25)

    returns = Q.get_returns_for_song(conn, sid)
    # W4-C: Live's `<letter>-` slot prefix is stripped on capture so the DB
    # stores SUFFIX-only return names. Push re-emits the suffix and Live
    # auto-prefixes back. The snapshot still carries Live's prefixed shape.
    assert [r["name"] for r in returns] == ["Reverb", "Delay"]
    assert returns[0]["position"] == 1

    sends = Q.get_sends_for_song(conn, sid)
    # Drums sends to A and B; Pluck sends to A and B → 4 send rows.
    # Send-side lookup also strips the prefix when matching the snapshot's
    # send map (keyed by Live's prefixed names) against return_ids_by_name.
    assert len(sends) == 4
    drums_to_delay = next(
        s for s in sends if s["from_track_name"] == "01 Drums"
        and s["return_name"] == "Delay"
    )
    assert drums_to_delay["level"] == pytest.approx(0.1)


def test_replay_is_idempotent_on_duplicate_song(conn):
    """W12-A: replay_capture is now idempotent — running it twice over the
    same snapshot is a no-op for unchanged state. Prior contract (raise)
    pre-dated mutator idempotency."""
    snap = _sample_snapshot()
    sid1 = replay_capture(conn, snap, song_name="t")
    sid2 = replay_capture(conn, snap, song_name="t")
    assert sid1 == sid2
    # Same name resolves to same song; mutators recognize the existing rows
    # and either no-op or update (depending on whether snapshot content
    # differs from DB).


def test_replay_rejects_unknown_track_type(conn):
    snap = {"song": {}, "returns": [], "tracks": [
        {"index": 1, "name": "x", "type": "phantom"},
    ]}
    with pytest.raises(ValueError, match="not in"):
        replay_capture(conn, snap, song_name="t")


def test_replay_rejects_unknown_return_in_send(conn):
    snap = {
        "song": {}, "returns": [],
        "tracks": [{
            "index": 1, "name": "x", "type": "midi",
            "sends": {"Ghost-Reverb": 0.4},
        }],
    }
    with pytest.raises(ValueError, match="not defined in snapshot"):
        replay_capture(conn, snap, song_name="t")


def test_replay_volume_out_of_range_rejected(conn):
    snap = {"song": {}, "returns": [], "tracks": [
        {"index": 1, "name": "x", "type": "midi", "volume": 1.5},
    ]}
    with pytest.raises(ValueError, match="out of range"):
        replay_capture(conn, snap, song_name="t")


def test_replay_skips_missing_fields_gracefully(conn):
    # Minimal snapshot with no master / no mixer fields — should still succeed.
    snap = {"song": {}, "returns": [], "tracks": [
        {"index": 1, "name": "bare", "type": "midi"},
    ]}
    sid = replay_capture(conn, snap, song_name="t")
    tracks = Q.get_tracks_for_song(conn, sid)
    assert len(tracks) == 1
    assert tracks[0]["volume"] is None
    assert tracks[0]["pan"] is None


def test_replay_actor_is_threaded_through_events(conn):
    sid = replay_capture(
        conn, _sample_snapshot(), song_name="t", actor="sync", reason="capture replay"
    )
    actors = {
        row["actor"]
        for row in conn.execute(
            "SELECT DISTINCT actor FROM events WHERE song_id=?", (sid,)
        ).fetchall()
    }
    # All non-system events from this replay carry actor='sync'
    assert actors == {"sync"}


# Song-specific snapshot tests (falling-walking) live at
# `songs/falling-walking/tests/test_capture_replay.py`. This file holds only
# platform-level replay tests that use synthetic snapshots.


# ---------- chunk 4a: device replay ----------


def _snapshot_with_devices() -> dict:
    return {
        "song": {"master": {"volume": 0.85, "panning": 0.0}},
        "returns": [
            {
                "index": 1, "name": "A-Reverb", "volume": 0.85, "panning": 0.0,
                "devices": [{"index": 1, "name": "Reverb", "class": "Reverb"}],
            },
        ],
        "tracks": [
            {
                "index": 5, "name": "01 Drums", "type": "midi",
                "volume": 0.6, "panning": 0.0,
                "sends": {"A-Reverb": 0.0},
                "devices": [
                    {
                        "index": 1, "name": "Late Nite Kit",
                        "class": "DrumGroupDevice",
                        "guess_uri": "query:Drums#FileId_5418",
                        "params_dialed": {
                            "Filter": {"value": "1", "normalized": 0.01},
                            "Filter Type": {"value": "Lowpass"},
                        },
                    },
                    {"index": 2, "name": "EQ Eight", "class": "Eq8"},
                ],
            },
        ],
    }


def test_replay_creates_top_level_chain_per_parent(conn):
    sid = replay_capture(conn, _snapshot_with_devices(), song_name="t")
    # 1 track chain + 1 return chain = 2 chains.
    chains = conn.execute("SELECT * FROM device_chains").fetchall()
    assert len(chains) == 2
    # All top-level chains are position=0.
    assert {c["position"] for c in chains} == {0}


def test_replay_creates_devices_with_kind_and_display_name(conn):
    sid = replay_capture(conn, _snapshot_with_devices(), song_name="t")
    drums = next(
        t for t in Q.get_tracks_for_song(conn, sid) if t["name"] == "01 Drums"
    )
    devices = Q.get_devices_for_track(conn, drums["id"])
    assert [d["display_name"] for d in devices] == ["Late Nite Kit", "EQ Eight"]
    assert [d["kind"] for d in devices] == ["DrumGroupDevice", "Eq8"]
    assert devices[0]["preset_uri"] == "query:Drums#FileId_5418"
    assert devices[1]["preset_uri"] is None


def test_replay_creates_dialed_params(conn):
    sid = replay_capture(conn, _snapshot_with_devices(), song_name="t")
    drums = next(
        t for t in Q.get_tracks_for_song(conn, sid) if t["name"] == "01 Drums"
    )
    late_nite = Q.get_devices_for_track(conn, drums["id"])[0]
    params = {p["name"]: p for p in Q.get_device_parameters(conn, late_nite["id"])}
    assert params["Filter"]["value_display"] == "1"
    assert params["Filter"]["value_normalized"] == pytest.approx(0.01)
    # Discrete-enum param carries display only.
    assert params["Filter Type"]["value_display"] == "Lowpass"
    assert params["Filter Type"]["value_normalized"] is None


def test_replay_handles_track_with_no_devices(conn):
    """The 4 placeholder tracks in falling-walking carry no `devices` field."""
    snap = {
        "song": {}, "returns": [],
        "tracks": [{"index": 1, "name": "empty", "type": "midi"}],
    }
    sid = replay_capture(conn, snap, song_name="t")
    track = next(t for t in Q.get_tracks_for_song(conn, sid) if t["name"] == "empty")
    assert Q.get_device_chains_for_track(conn, track["id"]) == []


def test_replay_rejects_device_missing_class(conn):
    snap = {
        "song": {}, "returns": [],
        "tracks": [{
            "index": 1, "name": "t", "type": "midi",
            "devices": [{"index": 1, "name": "X"}],  # no class
        }],
    }
    with pytest.raises(ValueError, match="missing required keys"):
        replay_capture(conn, snap, song_name="t")


def test_replay_handles_explicit_null_normalized(conn):
    """A future snapshot could ship `"normalized": null` explicitly (rather
    than omitting the key) — that must still produce a NULL value_normalized
    rather than raising on `float(None)`."""
    snap = {
        "song": {}, "returns": [],
        "tracks": [{
            "index": 1, "name": "t", "type": "midi",
            "devices": [{
                "index": 1, "name": "X", "class": "Operator",
                "params_dialed": {
                    "Filter Type": {"value": "Lowpass", "normalized": None},
                },
            }],
        }],
    }
    sid = replay_capture(conn, snap, song_name="t")
    track = next(t for t in Q.get_tracks_for_song(conn, sid) if t["name"] == "t")
    device = Q.get_devices_for_track(conn, track["id"])[0]
    params = Q.get_device_parameters(conn, device["id"])
    assert params[0]["value_normalized"] is None


def test_replay_rejects_param_bad_shape(conn):
    snap = {
        "song": {}, "returns": [],
        "tracks": [{
            "index": 1, "name": "t", "type": "midi",
            "devices": [{
                "index": 1, "name": "X", "class": "Eq8",
                "params_dialed": {"Freq": "not-a-dict"},  # should be {value, normalized?}
            }],
        }],
    }
    with pytest.raises(ValueError, match="expected dict with 'value' key"):
        replay_capture(conn, snap, song_name="t")


# ---------- W7-B: nested rack chains ----------


def _snapshot_with_nested_rack(*, chains: list[dict]) -> dict:
    """Build a single-track snapshot whose track carries one Drum Rack with
    the given nested chains. Each chain is dict-shaped per W6-I/J.
    """
    return {
        "song": {},
        "returns": [],
        "tracks": [{
            "index": 1, "name": "Drums", "type": "midi",
            "devices": [{
                "index": 1, "name": "Drum Rack",
                "class": "DrumGroupDevice",
                "chains": chains,
            }],
        }],
    }


def test_replay_creates_nested_chain_and_device(conn):
    snap = _snapshot_with_nested_rack(chains=[
        {"chain_index": 1, "name": "Kick", "devices": [
            {"index": 1, "name": "Operator", "class": "Operator"},
        ]},
    ])
    sid = replay_capture(conn, snap, song_name="t")
    track = next(t for t in Q.get_tracks_for_song(conn, sid) if t["name"] == "Drums")
    top_devs = Q.get_devices_for_track(conn, track["id"])
    assert len(top_devs) == 1
    rack = top_devs[0]
    nested_chains = Q.get_device_chains_for_rack_device(conn, rack["id"])
    assert len(nested_chains) == 1
    assert nested_chains[0]["position"] == 1
    nested_devs = Q.get_devices_for_chain(conn, nested_chains[0]["id"])
    assert [(d["position"], d["kind"], d["display_name"]) for d in nested_devs] == [
        (1, "Operator", "Operator"),
    ]


def test_replay_creates_multiple_nested_chains_ordered_by_chain_index(conn):
    snap = _snapshot_with_nested_rack(chains=[
        {"chain_index": 1, "name": "Kick", "devices": [
            {"index": 1, "name": "Operator", "class": "Operator"},
        ]},
        {"chain_index": 2, "name": "Snare", "devices": [
            {"index": 1, "name": "Drum Synth", "class": "DrumSynths"},
            {"index": 2, "name": "Compressor", "class": "Compressor2"},
        ]},
    ])
    sid = replay_capture(conn, snap, song_name="t")
    track = next(t for t in Q.get_tracks_for_song(conn, sid) if t["name"] == "Drums")
    rack = Q.get_devices_for_track(conn, track["id"])[0]
    chains = Q.get_device_chains_for_rack_device(conn, rack["id"])
    assert [c["position"] for c in chains] == [1, 2]
    # Chain 2 holds two devices in 1-based position order.
    chain_2_devs = Q.get_devices_for_chain(conn, chains[1]["id"])
    assert [(d["position"], d["kind"]) for d in chain_2_devs] == [
        (1, "DrumSynths"), (2, "Compressor2"),
    ]


def test_replay_nested_device_with_dialed_params(conn):
    snap = _snapshot_with_nested_rack(chains=[
        {"chain_index": 1, "devices": [{
            "index": 1, "name": "Operator", "class": "Operator",
            "params_dialed": {
                "Volume": {"value": "-6 dB", "normalized": 0.5},
            },
        }]},
    ])
    sid = replay_capture(conn, snap, song_name="t")
    track = next(t for t in Q.get_tracks_for_song(conn, sid) if t["name"] == "Drums")
    rack = Q.get_devices_for_track(conn, track["id"])[0]
    nested_chain = Q.get_device_chains_for_rack_device(conn, rack["id"])[0]
    nested_dev = Q.get_devices_for_chain(conn, nested_chain["id"])[0]
    params = Q.get_device_parameters(conn, nested_dev["id"])
    assert len(params) == 1
    assert params[0]["name"] == "Volume"
    assert params[0]["value_display"] == "-6 dB"
    assert params[0]["value_normalized"] == pytest.approx(0.5)


def test_replay_rejects_nested_nested_rack(conn):
    """One level only: a rack inside a rack chain raises at replay time.
    Recursive support is deferred per the backlog nested-nested item.
    """
    snap = _snapshot_with_nested_rack(chains=[
        {"chain_index": 1, "devices": [{
            "index": 1, "name": "Inner Rack", "class": "InstrumentGroupDevice",
            "chains": [{"chain_index": 1, "devices": []}],
        }]},
    ])
    with pytest.raises(ValueError, match="nested-nested"):
        replay_capture(conn, snap, song_name="t")


def test_replay_rejects_chains_on_non_rack(conn):
    """A `chains` field on a non-rack-classed device is malformed — surface it
    rather than silently fabricating nested rows under a Compressor."""
    snap = {
        "song": {}, "returns": [],
        "tracks": [{
            "index": 1, "name": "x", "type": "midi",
            "devices": [{
                "index": 1, "name": "Comp", "class": "Compressor2",
                "chains": [{"chain_index": 1, "devices": []}],
            }],
        }],
    }
    with pytest.raises(ValueError, match="not a rack"):
        replay_capture(conn, snap, song_name="t")


def test_replay_rejects_missing_chain_index(conn):
    snap = _snapshot_with_nested_rack(chains=[
        {"devices": []},  # no chain_index
    ])
    with pytest.raises(ValueError, match="missing 'chain_index'"):
        replay_capture(conn, snap, song_name="t")


def test_replay_rejects_chain_index_below_one(conn):
    snap = _snapshot_with_nested_rack(chains=[{"chain_index": 0, "devices": []}])
    with pytest.raises(ValueError, match="must be >= 1"):
        replay_capture(conn, snap, song_name="t")


def test_replay_rack_with_no_chains_field_still_works(conn):
    """A `DrumGroupDevice` without a `chains` field on the snapshot is fine —
    it just doesn't get any nested rows. Useful for snapshots from a pre-W7-B
    agent (back-compat) or racks the agent intentionally skipped probing."""
    snap = {
        "song": {}, "returns": [],
        "tracks": [{
            "index": 1, "name": "x", "type": "midi",
            "devices": [{"index": 1, "name": "R", "class": "DrumGroupDevice"}],
        }],
    }
    sid = replay_capture(conn, snap, song_name="t")
    track = next(t for t in Q.get_tracks_for_song(conn, sid) if t["name"] == "x")
    rack = Q.get_devices_for_track(conn, track["id"])[0]
    assert Q.get_device_chains_for_rack_device(conn, rack["id"]) == []


def test_replay_rack_with_empty_chains_array_no_rows(conn):
    snap = _snapshot_with_nested_rack(chains=[])
    sid = replay_capture(conn, snap, song_name="t")
    track = next(t for t in Q.get_tracks_for_song(conn, sid) if t["name"] == "Drums")
    rack = Q.get_devices_for_track(conn, track["id"])[0]
    assert Q.get_device_chains_for_rack_device(conn, rack["id"]) == []


# ---------- capture_plan / compile_snapshot ----------


def test_capture_plan_lists_expected_probes():
    plan = capture_plan()
    tools = {p["tool"] for p in plan}
    assert tools == {
        "ableton_session(action='info')",
        "ableton_return(action='list')",
        "ableton_track(action='get_info')",
        "ableton_track(action='get_sends')",
        "ableton_device(action='get_parameters')",
        # W7-B: nested rack chain probe (one level only)
        "ableton_device(action='get_device_chains')",
    }


def test_compile_snapshot_passes_through_inputs():
    snap = compile_snapshot(
        session_info={
            "tempo": 132.0, "signature": "4/4",
            "master": {"volume": 0.85, "panning": 0.0},
        },
        returns=[{"index": 1, "name": "A", "volume": 0.85}],
        tracks=[{"index": 1, "name": "x", "type": "midi", "volume": 0.5}],
    )
    assert snap["song"]["tempo"] == 132.0
    assert snap["song"]["master"]["volume"] == 0.85
    assert snap["returns"][0]["name"] == "A"
    assert snap["tracks"][0]["name"] == "x"
