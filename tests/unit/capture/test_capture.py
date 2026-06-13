"""Tests for capture.replay_capture and compile_snapshot."""
from __future__ import annotations

import json

import pytest

from hallucinote.capture import (
    capture_plan, compile_snapshot, inject_browser_paths,
    preserve_browser_paths, replay_capture, strip_return_slot_prefix,
)
from hallucinote.db import init_db, mutations as M, queries as Q

# Several fixtures in this module deliberately use Live's `<letter>-` prefixed
# return names (e.g. `"A-Reverb"`) — they simulate captured Live state, where
# the prefix is part of Live's wire shape. `replay_capture` strips on the way
# in (W4-C convention) and emits a UserWarning. The dedicated warn test
# (`test_replay_warns_when_stripping_slot_prefix`) uses `pytest.warns(...)`
# which overrides this filter for its scope; everywhere else the warn is
# strip-path-working-correctly noise, not a fixture defect.
pytestmark = pytest.mark.filterwarnings(
    r"ignore:.*stripped Live's <letter>- slot prefix.*:UserWarning"
)


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
                        "class": "Drum Rack",
                        "guess_uri": "query:Drums#FileId_5418",
                        "params_dialed": {
                            "Filter": {"value": "1", "normalized": 0.01},
                            "Filter Type": {"value": "Lowpass"},
                        },
                    },
                    {"index": 2, "name": "EQ Eight", "class": "EQ Eight"},
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
    assert [d["kind"] for d in devices] == ["Drum Rack", "EQ Eight"]
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


def test_replay_reads_preset_query_from_snapshot(conn):
    """Sweep B: a snapshot device with `preset_query` should land in the DB
    with the query JSON-serialized into the devices.preset_query column. The
    push planner reads it back to thread into ableton_device(load,
    preset_query=...) on the consumer's machine."""
    snap = {
        "song": {}, "returns": [],
        "tracks": [{
            "index": 1, "name": "Drums", "type": "midi",
            "devices": [{
                "index": 1, "name": "Some 909 Kit", "class": "Drum Rack",
                "preset_query": {
                    "root": "drums",
                    "pattern": "909",
                    "mode": "substring",
                },
            }],
        }],
    }
    sid = replay_capture(conn, snap, song_name="t")
    track = next(t for t in Q.get_tracks_for_song(conn, sid) if t["name"] == "Drums")
    devices = Q.get_devices_for_track(conn, track["id"])
    assert devices[0]["preset_uri"] is None
    stored = devices[0]["preset_query"]
    assert stored is not None
    parsed = json.loads(stored)
    assert parsed == {"root": "drums", "pattern": "909", "mode": "substring"}


def test_replay_reads_audio_file_from_snapshot(conn):
    """SMP-7K2D: a snapshot device with `audio_file` (a sample-instrument)
    lands in `devices.audio_file`, so a sampler's assigned sample round-trips
    as song source-of-truth. Non-sampler devices omit the key → NULL column."""
    snap = {
        "song": {}, "returns": [],
        "tracks": [{
            "index": 1, "name": "Buried We", "type": "midi",
            "devices": [
                {
                    "index": 1, "name": "we-all", "class": "Simpler",
                    "audio_file": "assets/we-all.wav",
                },
                {"index": 2, "name": "EQ Eight", "class": "EQ Eight"},
            ],
        }],
    }
    sid = replay_capture(conn, snap, song_name="t")
    track = next(
        t for t in Q.get_tracks_for_song(conn, sid) if t["name"] == "Buried We"
    )
    devices = Q.get_devices_for_track(conn, track["id"])
    assert devices[0]["audio_file"] == "assets/we-all.wav"
    # Non-sampler device omits the key → column stays NULL.
    assert devices[1]["audio_file"] is None


def test_replay_reads_browser_path_from_snapshot(conn):
    """E3 (W13-A v1.0): a snapshot device with `browser_path` lands in
    `devices.browser_path_json` so the push planner can thread it back
    into `ableton_device(action='load', browser_path=[...])` as the
    fallback identity for cross-machine FileId mismatches. Pre-E3
    snapshots without the key still load — column stays NULL."""
    snap = {
        "song": {}, "returns": [],
        "tracks": [{
            "index": 1, "name": "Bass", "type": "midi",
            "devices": [{
                "index": 1, "name": "FatBass", "class": "Massive X",
                "guess_uri": "query:Plugin#FileId_AUTHOR",
                "browser_path": [
                    "plug-ins", "Native Instruments", "Massive X", "FatBass",
                ],
            }],
        }],
    }
    sid = replay_capture(conn, snap, song_name="t")
    track = next(t for t in Q.get_tracks_for_song(conn, sid) if t["name"] == "Bass")
    devices = Q.get_devices_for_track(conn, track["id"])
    assert devices[0]["preset_uri"] == "query:Plugin#FileId_AUTHOR"
    stored = devices[0]["browser_path_json"]
    assert stored is not None
    assert json.loads(stored) == [
        "plug-ins", "Native Instruments", "Massive X", "FatBass",
    ]


def test_replay_omits_browser_path_when_snapshot_lacks_key(conn):
    """Pre-E3 snapshots load cleanly with browser_path_json NULL — the
    column is opt-in and absence is the dominant case until snapshots
    recapture against the post-E3 load handler."""
    snap = {
        "song": {}, "returns": [],
        "tracks": [{
            "index": 1, "name": "Synth", "type": "midi",
            "devices": [{"index": 1, "name": "Op", "class": "Operator"}],
        }],
    }
    sid = replay_capture(conn, snap, song_name="t")
    track = next(t for t in Q.get_tracks_for_song(conn, sid) if t["name"] == "Synth")
    devices = Q.get_devices_for_track(conn, track["id"])
    assert devices[0]["browser_path_json"] is None


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
                "index": 1, "name": "X", "class": "EQ Eight",
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
                "class": "Drum Rack",
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
            {"index": 2, "name": "Compressor", "class": "Compressor"},
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
        (1, "DrumSynths"), (2, "Compressor"),
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
            "index": 1, "name": "Inner Rack", "class": "Instrument Rack",
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
                "index": 1, "name": "Comp", "class": "Compressor",
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
            "devices": [{"index": 1, "name": "R", "class": "Drum Rack"}],
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
        "ableton_track(action='info')",
        "ableton_track(action='get_sends')",
        "ableton_device(action='get_parameters')",
        # W7-B: nested rack chain probe (one level only)
        "ableton_device(action='get_device_chains')",
        # M1-C: per-Drum-Rack pad layout probe
        "ableton_device(action='pad_info')",
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


def test_compile_snapshot_preserves_nested_rack_chains():
    """W19-B: the agent assembles each rack device's nested chains via
    `ableton_device(action='get_device_chains')` and attaches them as the
    device's `chains` field. compile_snapshot is pass-through for those —
    lock the round-trip shape here so a future refactor that "normalises"
    nested chains away surfaces as a test failure, not as silent drop on
    push."""
    nested_chains = [
        {
            "chain_index": 1,
            "name": "Kick",
            "devices": [{"position": 1, "class": "Simpler", "name": "Kick.als"}],
        },
        {
            "chain_index": 2,
            "name": "Snare",
            "devices": [{"position": 1, "class": "Simpler", "name": "Snare.als"}],
        },
    ]
    track = {
        "index": 1, "name": "Drums", "type": "midi",
        "volume": 0.7, "panning": 0.0,
        "devices": [{
            "position": 1, "class": "Drum Rack", "name": "Drum Kit",
            "chains": nested_chains,
        }],
    }
    snap = compile_snapshot(
        session_info={"tempo": 120.0, "signature": "4/4",
                      "master": {"volume": 0.85, "panning": 0.0}},
        returns=[],
        tracks=[track],
    )
    assert snap["tracks"][0]["devices"][0]["chains"] == nested_chains


# ---------- M1-C: Drum Rack pad mapping replay ----------


def _snapshot_with_drum_rack(*, drum_pads: list[dict] | None) -> dict:
    """Build a single-track snapshot with one Drum Rack carrying drum_pads."""
    device = {
        "index": 1, "name": "Late Nite Kit",
        "class": "Drum Rack",
    }
    if drum_pads is not None:
        device["drum_pads"] = drum_pads
    return {
        "song": {},
        "returns": [],
        "tracks": [{
            "index": 1, "name": "Drums", "type": "midi",
            "devices": [device],
        }],
    }


def test_replay_persists_drum_pads_into_drum_pad_mappings(conn):
    snap = _snapshot_with_drum_rack(drum_pads=[
        {"chain_name": "Kick Drum", "midi_note": 36},
        {"chain_name": "Snare Top", "midi_note": 38},
        {"chain_name": "Closed Hat", "midi_note": 42},
    ])
    sid = replay_capture(conn, snap, song_name="t")
    track = next(t for t in Q.get_tracks_for_song(conn, sid) if t["name"] == "Drums")
    rack = Q.get_devices_for_track(conn, track["id"])[0]
    rows = Q.get_drum_pad_mappings(conn, rack["id"])
    assert [(r["chain_name"], r["midi_note"]) for r in rows] == [
        ("Kick Drum", 36), ("Snare Top", 38), ("Closed Hat", 42),
    ]


def test_replay_accepts_note_alias_for_midi_note(conn):
    """The MCP pad_info handler returns ``{note: int, name: str, chain_name:
    str}`` per pad — the snapshot may carry either ``midi_note`` (canonical
    snapshot field) or ``note`` (raw passthrough from the MCP probe). Both
    are accepted so the agent can wire either shape."""
    snap = _snapshot_with_drum_rack(drum_pads=[
        {"chain_name": "Kick", "note": 36},
        {"chain_name": "Snare", "note": 38},
    ])
    sid = replay_capture(conn, snap, song_name="t")
    track = next(t for t in Q.get_tracks_for_song(conn, sid) if t["name"] == "Drums")
    rack = Q.get_devices_for_track(conn, track["id"])[0]
    rows = Q.get_drum_pad_mappings(conn, rack["id"])
    assert [r["midi_note"] for r in rows] == [36, 38]


def test_replay_rejects_drum_pads_on_non_drum_rack(conn):
    """`drum_pads` only makes sense on DrumGroupDevice."""
    snap = {
        "song": {}, "returns": [],
        "tracks": [{
            "index": 1, "name": "Synth", "type": "midi",
            "devices": [{
                "index": 1, "name": "Wavetable", "class": "Wavetable",
                "drum_pads": [{"chain_name": "Pad", "midi_note": 36}],
            }],
        }],
    }
    with pytest.raises(ValueError, match="not 'Drum Rack'"):
        replay_capture(conn, snap, song_name="t")


def test_replay_drum_rack_without_drum_pads_field_still_works(conn):
    """Drum Racks captured by a pre-M1-C agent (no pad_info probe) replay
    cleanly without drum_pads — no error, just no pad mappings persisted."""
    snap = _snapshot_with_drum_rack(drum_pads=None)
    sid = replay_capture(conn, snap, song_name="t")
    track = next(t for t in Q.get_tracks_for_song(conn, sid) if t["name"] == "Drums")
    rack = Q.get_devices_for_track(conn, track["id"])[0]
    assert Q.get_drum_pad_mappings(conn, rack["id"]) == []


# ---------- E3: inject_browser_paths / preserve_browser_paths ----------
# Arc 7-tail / E3, snapshot-write side of W13-A v1.0. The READ side
# (`replay_capture` consumes `browser_path`, push planner threads it back)
# shipped in E3; these helpers cover the producer side so the cross-machine
# fallback identity round-trips through capture.


def _snapshot_with_one_track_one_device(class_name: str = "Operator") -> dict:
    """Minimal fixture: one track, one device, no browser_path yet."""
    return {
        "song": {"tempo": 120.0, "signature": "4/4"},
        "returns": [],
        "tracks": [{
            "index": 1, "name": "T1", "type": "midi",
            "devices": [{
                "index": 1, "name": class_name, "class": class_name,
            }],
        }],
    }


def _snapshot_with_one_return_one_device(class_name: str = "Reverb") -> dict:
    return {
        "song": {}, "returns": [{
            "index": 1, "name": "Reverb",
            "devices": [{
                "index": 1, "name": class_name, "class": class_name,
            }],
        }],
        "tracks": [],
    }


def test_inject_browser_paths_attaches_to_track_device():
    """The agent collects `resolved_path` per load, then passes it here so
    the snapshot captures cross-machine fallback identity."""
    snap = _snapshot_with_one_track_one_device()
    inject_browser_paths(snap, [
        {"track_index": 1, "device_index": 1,
         "browser_path": ["instruments", "Operator"]},
    ])
    assert snap["tracks"][0]["devices"][0]["browser_path"] == [
        "instruments", "Operator",
    ]


def test_inject_browser_paths_attaches_to_return_device():
    snap = _snapshot_with_one_return_one_device()
    inject_browser_paths(snap, [
        {"return_index": 1, "device_index": 1,
         "browser_path": ["audio-effects", "Reverb"]},
    ])
    assert snap["returns"][0]["devices"][0]["browser_path"] == [
        "audio-effects", "Reverb",
    ]


def test_inject_browser_paths_empty_loads_is_noop():
    snap = _snapshot_with_one_track_one_device()
    before = json.dumps(snap, sort_keys=True)
    inject_browser_paths(snap, [])
    assert json.dumps(snap, sort_keys=True) == before


def test_inject_browser_paths_multiple_records():
    """One snapshot, two loads on different tracks — both land."""
    snap = {
        "song": {}, "returns": [],
        "tracks": [
            {"index": 1, "name": "T1", "type": "midi",
             "devices": [{"index": 1, "name": "Operator", "class": "Operator"}]},
            {"index": 2, "name": "T2", "type": "midi",
             "devices": [{"index": 1, "name": "Wavetable", "class": "Wavetable"}]},
        ],
    }
    inject_browser_paths(snap, [
        {"track_index": 1, "device_index": 1,
         "browser_path": ["instruments", "Operator"]},
        {"track_index": 2, "device_index": 1,
         "browser_path": ["instruments", "Wavetable"]},
    ])
    assert snap["tracks"][0]["devices"][0]["browser_path"] == [
        "instruments", "Operator",
    ]
    assert snap["tracks"][1]["devices"][0]["browser_path"] == [
        "instruments", "Wavetable",
    ]


def test_inject_browser_paths_overwrites_existing():
    """A second injection of the same slot replaces (most-recent-load wins)."""
    snap = _snapshot_with_one_track_one_device()
    inject_browser_paths(snap, [
        {"track_index": 1, "device_index": 1,
         "browser_path": ["instruments", "Old"]},
    ])
    inject_browser_paths(snap, [
        {"track_index": 1, "device_index": 1,
         "browser_path": ["instruments", "New"]},
    ])
    assert snap["tracks"][0]["devices"][0]["browser_path"] == [
        "instruments", "New",
    ]


@pytest.mark.parametrize("record,match", [
    # missing browser_path
    ({"track_index": 1, "device_index": 1}, "non-empty browser_path"),
    # empty browser_path
    ({"track_index": 1, "device_index": 1, "browser_path": []},
     "non-empty browser_path"),
    # non-string element in browser_path
    ({"track_index": 1, "device_index": 1, "browser_path": ["a", 5]},
     "non-empty browser_path"),
    # missing device_index
    ({"track_index": 1, "browser_path": ["a", "b"]}, "device_index"),
    # device_index < 1
    ({"track_index": 1, "device_index": 0, "browser_path": ["a"]},
     "device_index must be >= 1"),
    # neither track_index nor return_index
    ({"device_index": 1, "browser_path": ["a"]}, "track_index or return_index"),
    # both track_index and return_index
    ({"track_index": 1, "return_index": 1, "device_index": 1,
      "browser_path": ["a"]}, "track_index or return_index"),
])
def test_inject_browser_paths_rejects_malformed_records(record, match):
    snap = _snapshot_with_one_track_one_device()
    with pytest.raises(ValueError, match=match):
        inject_browser_paths(snap, [record])


def test_inject_browser_paths_raises_on_missing_track():
    """Stale agent state: load record points at a track that's not in the
    snapshot. Better to fail loud than silently drop the path."""
    snap = _snapshot_with_one_track_one_device()
    with pytest.raises(ValueError, match="no track with index=99"):
        inject_browser_paths(snap, [
            {"track_index": 99, "device_index": 1,
             "browser_path": ["instruments", "Operator"]},
        ])


def test_inject_browser_paths_raises_on_missing_return():
    snap = _snapshot_with_one_return_one_device()
    with pytest.raises(ValueError, match="no return with index=99"):
        inject_browser_paths(snap, [
            {"return_index": 99, "device_index": 1,
             "browser_path": ["audio-effects", "Reverb"]},
        ])


def test_inject_browser_paths_raises_on_missing_device():
    snap = _snapshot_with_one_track_one_device()
    with pytest.raises(ValueError, match="no device at index=5"):
        inject_browser_paths(snap, [
            {"track_index": 1, "device_index": 5,
             "browser_path": ["instruments", "Operator"]},
        ])


def test_compile_snapshot_accepts_browser_paths():
    """The composed entry point: agent passes loads alongside the probed
    state so the snapshot leaves compile_snapshot already enriched."""
    snap = compile_snapshot(
        session_info={"tempo": 120.0, "signature": "4/4"},
        returns=[],
        tracks=[{
            "index": 1, "name": "T1", "type": "midi",
            "devices": [{"index": 1, "name": "Operator", "class": "Operator"}],
        }],
        browser_paths=[{
            "track_index": 1, "device_index": 1,
            "browser_path": ["instruments", "Operator"],
        }],
    )
    assert snap["tracks"][0]["devices"][0]["browser_path"] == [
        "instruments", "Operator",
    ]


def test_compile_snapshot_browser_paths_none_is_noop():
    snap = compile_snapshot(
        session_info={"tempo": 120.0, "signature": "4/4"},
        returns=[],
        tracks=[{
            "index": 1, "name": "T1", "type": "midi",
            "devices": [{"index": 1, "name": "Operator", "class": "Operator"}],
        }],
        browser_paths=None,
    )
    assert "browser_path" not in snap["tracks"][0]["devices"][0]


def test_inject_then_replay_round_trips(conn):
    """End-to-end: inject browser_path on a snapshot device, replay into
    DB, confirm `devices.browser_path_json` is populated. Closes the
    snapshot-write-to-DB-read loop."""
    snap = _snapshot_with_one_track_one_device(class_name="Operator")
    inject_browser_paths(snap, [
        {"track_index": 1, "device_index": 1,
         "browser_path": ["instruments", "Operator"]},
    ])
    sid = replay_capture(conn, snap, song_name="t")
    track = next(t for t in Q.get_tracks_for_song(conn, sid) if t["name"] == "T1")
    device = Q.get_devices_for_track(conn, track["id"])[0]
    assert device["browser_path_json"] == json.dumps(
        ["instruments", "Operator"]
    )


def test_preserve_browser_paths_copies_matching_track_device():
    old = _snapshot_with_one_track_one_device()
    old["tracks"][0]["devices"][0]["browser_path"] = ["instruments", "Operator"]
    new = _snapshot_with_one_track_one_device()
    preserve_browser_paths(old, new)
    assert new["tracks"][0]["devices"][0]["browser_path"] == [
        "instruments", "Operator",
    ]


def test_preserve_browser_paths_copies_matching_return_device():
    old = _snapshot_with_one_return_one_device()
    old["returns"][0]["devices"][0]["browser_path"] = ["audio-effects", "Reverb"]
    new = _snapshot_with_one_return_one_device()
    preserve_browser_paths(old, new)
    assert new["returns"][0]["devices"][0]["browser_path"] == [
        "audio-effects", "Reverb",
    ]


def test_preserve_browser_paths_does_not_overwrite_new_value():
    """If `new` already has a browser_path (e.g. just-loaded), the fresh
    value wins over the old one."""
    old = _snapshot_with_one_track_one_device()
    old["tracks"][0]["devices"][0]["browser_path"] = ["instruments", "Old"]
    new = _snapshot_with_one_track_one_device()
    new["tracks"][0]["devices"][0]["browser_path"] = ["instruments", "New"]
    preserve_browser_paths(old, new)
    assert new["tracks"][0]["devices"][0]["browser_path"] == [
        "instruments", "New",
    ]


def test_preserve_browser_paths_drops_on_class_mismatch():
    """If the device at the same position has a different class, the user
    swapped instruments — the old browser_path is stale and shouldn't
    carry forward."""
    old = _snapshot_with_one_track_one_device(class_name="Operator")
    old["tracks"][0]["devices"][0]["browser_path"] = ["instruments", "Operator"]
    new = _snapshot_with_one_track_one_device(class_name="Wavetable")
    preserve_browser_paths(old, new)
    assert "browser_path" not in new["tracks"][0]["devices"][0]


def test_preserve_browser_paths_drops_on_position_change():
    """Device at index 1 in old, now at index 2 in new — old path is stale."""
    old = _snapshot_with_one_track_one_device(class_name="Operator")
    old["tracks"][0]["devices"][0]["browser_path"] = ["instruments", "Operator"]
    new = {
        "song": {}, "returns": [],
        "tracks": [{
            "index": 1, "name": "T1", "type": "midi",
            "devices": [
                {"index": 1, "name": "EQ Eight", "class": "EQ Eight"},
                {"index": 2, "name": "Operator", "class": "Operator"},
            ],
        }],
    }
    preserve_browser_paths(old, new)
    # The EQ Eight at new position 1 has a different class — no carry forward.
    assert "browser_path" not in new["tracks"][0]["devices"][0]
    # The Operator at new position 2 was at position 1 in old, position
    # identity doesn't match, so no carry forward either. Stale-position
    # paths are dropped intentionally.
    assert "browser_path" not in new["tracks"][0]["devices"][1]


def test_preserve_browser_paths_handles_missing_old_entry():
    """New device at a slot that didn't exist in old — no error, no path."""
    old = {"song": {}, "returns": [], "tracks": []}
    new = _snapshot_with_one_track_one_device()
    preserve_browser_paths(old, new)
    assert "browser_path" not in new["tracks"][0]["devices"][0]


def test_preserve_browser_paths_empty_old_is_noop():
    new = _snapshot_with_one_track_one_device()
    new["tracks"][0]["devices"][0]["browser_path"] = ["instruments", "Operator"]
    before = json.dumps(new, sort_keys=True)
    preserve_browser_paths({"song": {}, "returns": [], "tracks": []}, new)
    assert json.dumps(new, sort_keys=True) == before
