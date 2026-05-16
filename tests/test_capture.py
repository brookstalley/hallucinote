"""Tests for capture.replay_capture and compile_snapshot."""
from __future__ import annotations

import pytest

from hallucinote.capture import capture_plan, compile_snapshot, replay_capture
from hallucinote.db import init_db, mutations as M, queries as Q


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "cap.db")
    yield c
    c.close()


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
    assert [r["name"] for r in returns] == ["A-Reverb", "B-Delay"]
    assert returns[0]["position"] == 1

    sends = Q.get_sends_for_song(conn, sid)
    # Drums sends to A and B; Pluck sends to A and B → 4 send rows
    assert len(sends) == 4
    drums_to_delay = next(
        s for s in sends if s["from_track_name"] == "01 Drums"
        and s["return_name"] == "B-Delay"
    )
    assert drums_to_delay["level"] == pytest.approx(0.1)


def test_replay_rejects_duplicate_song(conn):
    snap = _sample_snapshot()
    replay_capture(conn, snap, song_name="t")
    with pytest.raises(ValueError, match="already exists"):
        replay_capture(conn, snap, song_name="t")


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


def test_replay_falling_walking_snapshot(conn):
    """Smoke test against the real falling-walking snapshot."""
    import json
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[1]
    snap_path = repo_root / "songs" / "falling-walking" / "captured_session.json"
    snap = json.loads(snap_path.read_text())
    sid = replay_capture(conn, snap, song_name="fw", song_key="Dm")

    # 12 captured tracks + 1 master row.
    tracks = Q.get_tracks_for_song(conn, sid)
    assert len(tracks) == 13
    # Master volume from the snapshot.
    master = next(t for t in tracks if t["kind"] == "master")
    assert master["volume"] == pytest.approx(0.85)
    # 2 returns.
    returns = Q.get_returns_for_song(conn, sid)
    assert {r["name"] for r in returns} == {"A-Reverb", "B-Delay"}
    # 8 audible tracks × 2 returns = 16 send rows.
    sends = Q.get_sends_for_song(conn, sid)
    assert len(sends) == 16

    # Chunk 4a: device chains + devices + dialed params replayed.
    # The 4 placeholder tracks ("1-MIDI", "2-MIDI", "3-Audio", "4-Audio") have
    # no `devices` array; the 8 instrumented tracks each get one top-level
    # chain. Returns A-Reverb and B-Delay also each get one chain. Total:
    # 8 + 2 = 10 chains.
    chains = conn.execute(
        "SELECT COUNT(*) FROM device_chains"
    ).fetchone()[0]
    assert chains == 10

    # Each instrumented track has 2-4 devices; returns have 1 device each.
    # The falling-walking snapshot totals 25 device rows (verified by counting
    # the snapshot file's `devices: [...]` array entries across all tracks +
    # returns at capture time). If this number changes, the snapshot file
    # changed too — update both.
    devices = conn.execute("SELECT COUNT(*) FROM devices").fetchone()[0]
    assert devices == 25

    # `01 Drums` carries 4 devices: Late Nite Kit (DrumGroupDevice), EQ Eight,
    # Drum Buss, Precise (Compressor2).
    drums = next(t for t in tracks if t["name"] == "01 Drums")
    drum_devices = Q.get_devices_for_track(conn, drums["id"])
    assert [d["display_name"] for d in drum_devices] == [
        "Late Nite Kit", "EQ Eight", "Drum Buss", "Precise",
    ]
    assert [d["kind"] for d in drum_devices] == [
        "DrumGroupDevice", "Eq8", "DrumBuss", "Compressor2",
    ]

    # `01 Drums` Late Nite Kit has 4 dialed parameters.
    late_nite = drum_devices[0]
    params = Q.get_device_parameters(conn, late_nite["id"])
    assert {p["name"] for p in params} == {"Filter", "Delay", "Low Freq", "Hi Freq"}
    low_freq = next(p for p in params if p["name"] == "Low Freq")
    assert low_freq["value_display"] == "2.51 dB"
    assert low_freq["value_normalized"] == pytest.approx(0.71)

    # Discrete-enum params (Filter Type) have NULL value_normalized.
    sub = next(t for t in tracks if t["name"] == "02 Sub Bass")
    operator = Q.get_devices_for_track(conn, sub["id"])[0]
    op_params = {p["name"]: p for p in Q.get_device_parameters(conn, operator["id"])}
    assert op_params["Filter Type"]["value_display"] == "Lowpass"
    assert op_params["Filter Type"]["value_normalized"] is None
    # Continuous params still carry the normalized value.
    assert op_params["Filter Freq"]["value_normalized"] == pytest.approx(0.93)


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


# ---------- capture_plan / compile_snapshot ----------


def test_capture_plan_lists_expected_probes():
    plan = capture_plan()
    tools = {p["tool"] for p in plan}
    assert tools == {
        "get_session_info",
        "list_return_tracks",
        "get_track_info",
        "get_track_sends",
        # Chunk 4a additions:
        "get_device_parameters",  # MCP gap #17b; included for protocol completeness
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
