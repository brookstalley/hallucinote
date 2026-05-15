"""Tests for capture.replay_capture and compile_snapshot."""
from __future__ import annotations

import pytest

from songwright.capture import capture_plan, compile_snapshot, replay_capture
from songwright.db import init_db, mutations as M, queries as Q


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


# ---------- capture_plan / compile_snapshot ----------


def test_capture_plan_lists_expected_probes():
    plan = capture_plan()
    tools = {p["tool"] for p in plan}
    assert tools == {
        "get_session_info",
        "list_return_tracks",
        "get_track_info",
        "get_track_sends",
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
