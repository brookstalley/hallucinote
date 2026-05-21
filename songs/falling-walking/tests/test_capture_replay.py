"""Falling-walking-specific snapshot replay test.

Asserts the captured Ableton snapshot (`captured_session.json`) replays into
the DB with the expected shape: 13 tracks (12 captured + master), 2 returns,
16 sends, 10 device chains, 25 devices, plus spot-checks on `01 Drums` and
`02 Sub Bass` device parameters.

If the snapshot file changes (e.g., re-captured from Live), the assertions
here need to be updated alongside it.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from hallucinote.capture import replay_capture
from hallucinote.db import init_db, queries as Q

SONG_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = SONG_ROOT / "captured_session.json"


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "cap.db")
    yield c
    c.close()


def test_replay_falling_walking_snapshot(conn):
    snap = json.loads(SNAPSHOT.read_text())
    sid = replay_capture(conn, snap, song_name="fw", song_key="Dm")

    # 12 captured tracks + 1 master row.
    tracks = Q.get_tracks_for_song(conn, sid)
    assert len(tracks) == 13
    # Master volume from the snapshot.
    master = next(t for t in tracks if t["kind"] == "master")
    assert master["volume"] == pytest.approx(0.85)
    # 2 returns. W4-C: Live's `<letter>-` slot prefix is stripped on
    # capture so the DB stores SUFFIX-only names (the snapshot still
    # carries Live's prefixed shape).
    returns = Q.get_returns_for_song(conn, sid)
    assert {r["name"] for r in returns} == {"Reverb", "Delay"}
    # 8 audible tracks × 2 returns = 16 send rows.
    sends = Q.get_sends_for_song(conn, sid)
    assert len(sends) == 16

    # Chunk 4a: device chains + devices + dialed params replayed.
    # The 4 placeholder tracks ("1-MIDI", "2-MIDI", "3-Audio", "4-Audio") have
    # no `devices` array; the 8 instrumented tracks each get one top-level
    # chain. Returns Reverb and Delay also each get one chain. Total:
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

    # `01 Drums` carries 4 devices: Late Nite Kit (Drum Rack), EQ Eight,
    # Drum Buss, Precise (Compressor). Post-D4: `kind` is the browser
    # display name.
    drums = next(t for t in tracks if t["name"] == "01 Drums")
    drum_devices = Q.get_devices_for_track(conn, drums["id"])
    assert [d["display_name"] for d in drum_devices] == [
        "Late Nite Kit", "EQ Eight", "Drum Buss", "Precise",
    ]
    assert [d["kind"] for d in drum_devices] == [
        "Drum Rack", "EQ Eight", "Drum Buss", "Compressor",
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
