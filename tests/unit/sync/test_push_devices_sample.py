"""The devices phase hands a sampler its sample.

A ``devices.audio_file`` row says which file the sampler plays. Push resolves it
the way the clips phase resolves a clip's audio — song-relative against the
song directory, absolute passed through — and emits
``ableton_device(action='assign_sample')`` only where Live is not already
playing that file.

Two refusals are covered here as first-class behaviour rather than error
plumbing, because both of them are ways a push could otherwise report OK on a
track that will be silent: a sample that is not on disk, and a sample assigned
to a device with no sample slot.
"""
from __future__ import annotations

import pytest

from hallucinote.db import init_db, mutations as M
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
def song(conn):
    return M.create_song(conn, name="smp", key="Dm")


@pytest.fixture
def session(conn, song):
    return M.create_ableton_session(conn, song_id=song, name="draft")


@pytest.fixture
def sample(song_dir):
    """A real file under the song's assets/ — the reference authors write."""
    path = song_dir / "assets" / "vox.wav"
    path.write_bytes(b"RIFF....WAVE")
    return path


def _linked_track(conn, song, session, *, live_index=5):
    track = M.create_track(conn, song_id=song, track_index=1, name="Vox")
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=track,
        ableton_index=live_index,
    )
    return track


def _linked_device(conn, session, chain_id, *, kind="Simpler", audio_file=None,
                   position=1, live_index=1, display_name="Simpler"):
    device = M.create_device(
        conn, chain_id=chain_id, position=position, kind=kind,
        display_name=display_name, audio_file=audio_file,
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="device", db_id=device,
        ableton_index=live_index,
    )
    return device


def _sampler_song(conn, song, session, *, audio_file, kind="Simpler"):
    track = _linked_track(conn, song, session)
    chain = M.create_device_chain(conn, parent_track_id=track)
    device = _linked_device(conn, session, chain, kind=kind, audio_file=audio_file)
    return device


def _assign_calls(plan):
    return [c for c in plan.calls if c.args.get("action") == "assign_sample"]


def _actions(plan):
    return [c.args.get("action") for c in plan.calls]


def _probe(devices):
    """A ``live_devices_by_parent`` map for the one track these tests link."""
    return {("track", 5): devices}


# ---------- emitted when the DB names a sample ----------


def test_assign_sample_emitted_for_a_sampler_row(conn, song, session, sample):
    _sampler_song(conn, song, session, audio_file="assets/vox.wav")

    plan = push.plan_push_devices(conn, song_id=song, session_id=session)

    (call,) = _assign_calls(plan)
    assert call.args["track_index"] == 5
    assert call.args["device_index"] == 1
    assert call.args["sample_path"] == str(sample)
    assert "device_path" not in call.args
    assert plan.blocked_reasons == []


def test_assign_sample_precedes_the_parameter_writes(conn, song, session, sample):
    device = _sampler_song(conn, song, session, audio_file="assets/vox.wav")
    M.set_device_parameter(
        conn, device_id=device, name="S Start", value_display="25 %",
        value_normalized=0.25,
    )

    plan = push.plan_push_devices(conn, song_id=song, session_id=session)

    actions = _actions(plan)
    assert actions.index("assign_sample") < actions.index("set_parameter")


def test_no_assign_sample_for_a_device_without_one(conn, song, session):
    track = _linked_track(conn, song, session)
    chain = M.create_device_chain(conn, parent_track_id=track)
    _linked_device(conn, session, chain, kind="EQ Eight", display_name="EQ")

    plan = push.plan_push_devices(conn, song_id=song, session_id=session)

    assert _assign_calls(plan) == []


def test_absolute_audio_file_passes_through(conn, song, session, tmp_path):
    outside = tmp_path / "library" / "kick.wav"
    outside.parent.mkdir()
    outside.write_bytes(b"RIFF....WAVE")
    _sampler_song(conn, song, session, audio_file=str(outside))

    plan = push.plan_push_devices(conn, song_id=song, session_id=session)

    (call,) = _assign_calls(plan)
    assert call.args["sample_path"] == str(outside)


# ---------- diffed against what Live already plays ----------


def test_not_emitted_when_live_already_plays_that_file(
    conn, song, session, sample,
):
    _sampler_song(conn, song, session, audio_file="assets/vox.wav")

    plan = push.plan_push_devices(
        conn, song_id=song, session_id=session,
        live_devices_by_parent=_probe([{
            "device_index": 1,
            "class_display_name": "Simpler",
            "sample_file_path": str(sample),
        }]),
    )

    assert _assign_calls(plan) == []
    assert plan.blocked_reasons == []


def test_emitted_when_live_plays_a_different_file(
    conn, song, session, sample, song_dir,
):
    stale = song_dir / "assets" / "old.wav"
    stale.write_bytes(b"RIFF....WAVE")
    _sampler_song(conn, song, session, audio_file="assets/vox.wav")

    plan = push.plan_push_devices(
        conn, song_id=song, session_id=session,
        live_devices_by_parent=_probe([{
            "device_index": 1,
            "class_display_name": "Simpler",
            "sample_file_path": str(stale),
        }]),
    )

    (call,) = _assign_calls(plan)
    assert call.args["sample_path"] == str(sample)


def test_emitted_when_the_live_sampler_is_empty(conn, song, session, sample):
    """``sample_file_path: None`` is a sampler with nothing loaded — a slot to
    fill, not a device to refuse."""
    _sampler_song(conn, song, session, audio_file="assets/vox.wav")

    plan = push.plan_push_devices(
        conn, song_id=song, session_id=session,
        live_devices_by_parent=_probe([{
            "device_index": 1,
            "class_display_name": "Simpler",
            "sample_file_path": None,
        }]),
    )

    assert len(_assign_calls(plan)) == 1
    assert plan.blocked_reasons == []


def test_emitted_when_the_probe_says_nothing_about_this_parent(
    conn, song, session, sample,
):
    """No probe data is not evidence the sample is already there. Re-assigning
    costs a call; skipping leaves the track silent."""
    _sampler_song(conn, song, session, audio_file="assets/vox.wav")

    plan = push.plan_push_devices(
        conn, song_id=song, session_id=session,
        live_devices_by_parent={("track", 99): []},
    )

    assert len(_assign_calls(plan)) == 1


# ---------- refusals ----------


def test_missing_file_blocks_that_device(conn, song, session):
    device = _sampler_song(conn, song, session, audio_file="assets/gone.wav")
    M.set_device_parameter(
        conn, device_id=device, name="S Start", value_display="25 %",
        value_normalized=0.25,
    )

    plan = push.plan_push_devices(conn, song_id=song, session_id=session)

    assert _assign_calls(plan) == []
    assert plan.calls == []
    (reason,) = plan.blocked_reasons
    assert "assets/gone.wav" in reason
    assert "not on disk" in reason


def test_missing_file_leaves_other_devices_pushable(conn, song, session, sample):
    track = _linked_track(conn, song, session)
    chain = M.create_device_chain(conn, parent_track_id=track)
    _linked_device(
        conn, session, chain, audio_file="assets/gone.wav",
        position=1, live_index=1,
    )
    _linked_device(
        conn, session, chain, audio_file="assets/vox.wav",
        position=2, live_index=2, display_name="Simpler 2",
    )

    plan = push.plan_push_devices(conn, song_id=song, session_id=session)

    assert len(_assign_calls(plan)) == 1
    assert len(plan.blocked_reasons) == 1


def test_sample_on_a_device_with_no_slot_blocks_naming_simpler(
    conn, song, session, sample,
):
    _sampler_song(conn, song, session, audio_file="assets/vox.wav", kind="Compressor")

    plan = push.plan_push_devices(
        conn, song_id=song, session_id=session,
        live_devices_by_parent=_probe([{
            "device_index": 1,
            "class_display_name": "Compressor",
        }]),
    )

    assert _assign_calls(plan) == []
    (reason,) = plan.blocked_reasons
    assert "Compressor" in reason
    assert "Simpler" in reason
    assert "no sample slot" in reason


def test_capability_refusal_needs_probe_evidence(conn, song, session, sample):
    """With no probe there is nothing that says this device lacks a slot, so
    the assignment is planned rather than refused on a class-name guess."""
    _sampler_song(conn, song, session, audio_file="assets/vox.wav", kind="Compressor")

    plan = push.plan_push_devices(conn, song_id=song, session_id=session)

    assert len(_assign_calls(plan)) == 1
    assert plan.blocked_reasons == []


# ---------- nested ----------


def test_nested_sampler_is_addressed_by_device_path(conn, song, session, sample):
    track = _linked_track(conn, song, session)
    chain = M.create_device_chain(conn, parent_track_id=track)
    rack = _linked_device(
        conn, session, chain, kind="Instrument Rack", display_name="Rack",
    )
    inner = M.create_device_chain(conn, parent_rack_device_id=rack, position=1)
    M.create_device(
        conn, chain_id=inner, position=1, kind="EQ Eight", display_name="EQ",
    )
    M.create_device(
        conn, chain_id=inner, position=2, kind="Simpler",
        display_name="Inner Simpler", audio_file="assets/vox.wav",
    )

    plan = push.plan_push_devices(conn, song_id=song, session_id=session)

    (call,) = _assign_calls(plan)
    assert call.args["track_index"] == 5
    assert call.args["device_index"] == 1
    assert call.args["device_path"] == [{"chain_index": 1, "device_position": 2}]
    assert call.args["sample_path"] == str(sample)
