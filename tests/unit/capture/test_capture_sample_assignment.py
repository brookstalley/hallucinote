"""Capture records which sample a sampler plays, portably.

``ableton_device(action='list')`` reports ``sample_file_path`` — an absolute
path, because that is what Live holds. The snapshot must not: a machine-absolute
path in `captured_session.json` stops the song travelling between machines. So a
sample living under the song directory is written song-relative (the same
``assets/...`` form ``clips.audio_file`` carries) and only a sample from
somewhere else keeps its absolute path.

The round trip is the point: what capture writes, replay reads back into
``devices.audio_file``, and the push planner resolves against the song directory
to the file capture saw.

Synthetic fixtures only (project convention for tests/unit/capture/): the fake
`probe` stands in for a running Live + bridge.
"""
from __future__ import annotations

import pytest

from hallucinote.capture import assemble_snapshot_via_probes, replay_capture
from hallucinote.db import init_db, mutations as M, queries as Q
from hallucinote.sync import push


@pytest.fixture
def song_dir(tmp_path):
    d = tmp_path / "songs" / "smp"
    (d / "assets").mkdir(parents=True)
    return d


@pytest.fixture
def conn(song_dir):
    c = init_db(song_dir / "smp.db")
    yield c
    c.close()


@pytest.fixture
def sample(song_dir):
    path = song_dir / "assets" / "vox.wav"
    path.write_bytes(b"RIFF....WAVE")
    return path


def _probe_for(devices):
    """A one-track live set whose single track carries ``devices``."""

    def probe(tool, action, **params):
        if (tool, action) == ("ableton_session", "info"):
            return {
                "tempo": 120.0,
                "signature": {"numerator": 4, "denominator": 4},
                "master": None, "track_count": 1, "return_count": 0,
            }
        if (tool, action) == ("ableton_return", "list"):
            return {"returns": []}
        if (tool, action) == ("ableton_track", "info"):
            return {"track_index": 1, "name": "Vox", "kind": "midi",
                    "volume": 0.7, "panning": 0.0}
        if (tool, action) == ("ableton_track", "get_sends"):
            return {"sends": []}
        if (tool, action) == ("ableton_device", "list"):
            return {"devices": devices}
        if (tool, action) == ("ableton_device", "get_parameters"):
            return {"parameters": []}
        if (tool, action) == ("ableton_device", "get_input_routing"):
            return {"has_input_routing": False}
        raise AssertionError(f"unrouted {tool}.{action}")

    return probe


def _simpler(sample_file_path):
    return {
        "device_index": 1, "name": "Simpler", "class_name": "OriginalSimpler",
        "class_display_name": "Simpler", "sample_file_path": sample_file_path,
    }


def _captured_device(snapshot):
    return snapshot["tracks"][0]["devices"][0]


# ---------- what capture writes ----------


def test_sample_under_the_song_dir_is_stored_song_relative(song_dir, sample):
    snap = assemble_snapshot_via_probes(
        _probe_for([_simpler(str(sample))]), song_dir=song_dir,
    )

    assert _captured_device(snap)["audio_file"] == "assets/vox.wav"


def test_sample_from_elsewhere_keeps_its_absolute_path(song_dir, tmp_path):
    outside = tmp_path / "library" / "kick.wav"
    outside.parent.mkdir()
    outside.write_bytes(b"RIFF....WAVE")

    snap = assemble_snapshot_via_probes(
        _probe_for([_simpler(str(outside))]), song_dir=song_dir,
    )

    assert _captured_device(snap)["audio_file"] == str(outside)


def test_an_empty_sampler_records_no_sample(song_dir):
    """A Simpler with nothing loaded answers the question with None — there is
    no reference to write, and the entry stays a Simpler with no sample."""
    snap = assemble_snapshot_via_probes(
        _probe_for([_simpler(None)]), song_dir=song_dir,
    )

    device = _captured_device(snap)
    assert device["class"] == "Simpler"
    assert "audio_file" not in device


def test_a_device_with_no_sample_slot_records_nothing(song_dir):
    snap = assemble_snapshot_via_probes(
        _probe_for([{
            "device_index": 1, "name": "Comp", "class_name": "Compressor2",
            "class_display_name": "Compressor",
        }]),
        song_dir=song_dir,
    )

    assert "audio_file" not in _captured_device(snap)


def test_without_a_song_dir_the_path_stays_absolute(sample):
    """No anchor is no reason to invent one — the reference is still resolvable
    on this machine, just not portable."""
    snap = assemble_snapshot_via_probes(_probe_for([_simpler(str(sample))]))

    assert _captured_device(snap)["audio_file"] == str(sample)


# ---------- and what it round-trips to ----------


def test_captured_sample_replays_into_the_device_row(conn, song_dir, sample):
    snap = assemble_snapshot_via_probes(
        _probe_for([_simpler(str(sample))]), song_dir=song_dir,
    )
    song = replay_capture(conn, snapshot=snap, song_name="smp", song_key="Dm")

    track = Q.get_tracks_for_song(conn, song)[0]
    chain = Q.get_device_chains_for_track(conn, track["id"])[0]
    device = Q.get_devices_for_chain(conn, chain["id"])[0]
    assert device["audio_file"] == "assets/vox.wav"


def test_the_round_trip_plans_back_the_file_capture_saw(conn, song_dir, sample):
    snap = assemble_snapshot_via_probes(
        _probe_for([_simpler(str(sample))]), song_dir=song_dir,
    )
    song = replay_capture(conn, snapshot=snap, song_name="smp", song_key="Dm")
    session = M.create_ableton_session(conn, song_id=song, name="draft")
    track = Q.get_tracks_for_song(conn, song)[0]
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=track["id"],
        ableton_index=1,
    )
    chain = Q.get_device_chains_for_track(conn, track["id"])[0]
    device = Q.get_devices_for_chain(conn, chain["id"])[0]
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="device", db_id=device["id"],
        ableton_index=1,
    )

    plan = push.plan_push_devices(conn, song_id=song, session_id=session)

    (call,) = [c for c in plan.calls if c.args.get("action") == "assign_sample"]
    assert call.args["sample_path"] == str(sample)
