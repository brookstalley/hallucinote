"""SMP-6V2K — a ``reverse=1`` clip row materializes through the derived cache (#237).

Neither a Live Clip nor Simpler carries a reverse the wire could set, so the
flag is materialized one step earlier: the sample is run through the
``reverse`` transform, filed in the song's content-addressed derived cache,
and the clip is created from THAT file. The property that makes this safe is
the address — it hashes the source's checksum together with the chain, so the
flag and the file the clip plays cannot disagree. Flip the flag and the path
changes; push then re-points the clip through the same delete → create →
conform → re-emit-envelopes route a re-pointed ``audio_file`` takes, and a
song nobody changed still plans nothing.

Sources here are synthesized: a ramp, because reversing one is visible in the
samples rather than only in a hash.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from hallucinote.assets import derived as derived_cache
from hallucinote.assets.manifest import Manifest, ManifestEntry
from hallucinote.assets import store, transforms
from hallucinote.db import init_db, mutations as M
from hallucinote.sync import push


SAMPLE_RATE = 8000
RAMP_FRAMES = 400
FAKE_CHECKSUM = "0" * 64


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def song_dir(tmp_path):
    """The DB lives IN the song dir — that is what an ``audio_file`` reference
    and the derived cache both resolve against."""
    (tmp_path / "assets" / "sources").mkdir(parents=True)
    return tmp_path


@pytest.fixture
def conn(song_dir):
    c = init_db(song_dir / "rev.db")
    yield c
    c.close()


@pytest.fixture
def song(conn):
    return M.create_song(conn, name="dialogue", key="Dm")


@pytest.fixture
def session(conn, song):
    return M.create_ableton_session(conn, song_id=song, name="draft")


@pytest.fixture
def audio_track(conn, song, session):
    tid = M.create_track(
        conn, song_id=song, track_index=1, name="Dialogue", kind="audio",
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=tid, ableton_index=4,
    )
    return tid


def _ramp(frames: int = RAMP_FRAMES) -> np.ndarray:
    """A mono ramp as (n, 1) float32 — its reverse is the descending ramp, so a
    test can assert the AUDIO turned around and not merely that a name did."""
    return np.linspace(-0.9, 0.9, frames, dtype=np.float32).reshape(-1, 1)


def _write_source(song_dir: Path, name: str = "line") -> str:
    """Write a synthesized source WAV and return its song-relative reference."""
    path = store.source_path(song_dir, name)
    sf.write(str(path), _ramp(), SAMPLE_RATE, subtype="FLOAT", format="WAV")
    return store.source_ref(name)


def _record_in_manifest(song_dir: Path, name: str = "line", *, checksum: str | None = None) -> None:
    """Give the song a manifest entry for ``name``, so the store hands the
    planner a recorded source rather than an unmanifested one."""
    path = store.source_path(song_dir, name)
    store.write_manifest(song_dir, Manifest(entries=(ManifestEntry(
        name=name,
        path=store.source_ref(name),
        checksum=checksum if checksum is not None else store.file_checksum(path),
        sample_rate=SAMPLE_RATE,
        channels=1,
        duration_s=RAMP_FRAMES / SAMPLE_RATE,
        note="a spoken line",
        origin="synthesized for a test",
        original_filename="line.wav",
        original_format="WAV",
        original_lossy=False,
        ingested_at="2026-09-09T00:00:00+00:00",
    ),)))


def _live_slot(clip_index: int, file_path: str) -> dict:
    """One populated entry as ``ableton_clip(action='list', location='session')``
    reports it for an audio clip."""
    return {
        "clip_index": clip_index,
        "empty": False,
        "name": "line",
        "length": 8.0,
        "is_audio": True,
        "file_path": file_path,
    }


def _create_call(plan):
    return next(c for c in plan.calls if c.args.get("action") == "create")


def _reversed_path(song_dir: Path, name: str = "line") -> str:
    """Where the reversed file for a manifest source lands, derived here so a
    test that never plans an unlinked create still knows the address."""
    # A frozen transform's read-only `kind` does not satisfy the protocol's
    # settable one; the structural check `derive` makes at runtime does pass.
    return str(derived_cache.derive(
        store.source(song_dir, name),
        (transforms.reverse(),),
        song_dir=song_dir,
    ).path)


# ---------------------------------------------------------------------------
# The flag materializes as a file
# ---------------------------------------------------------------------------


def test_a_reversed_row_creates_from_the_derived_file(
    conn, session, audio_track, song_dir,
):
    """The headline: the create carries a path in the derived cache, not the
    source — and the record beside it says the recipe was ``reverse``."""
    ref = _write_source(song_dir)
    _record_in_manifest(song_dir)
    cid = M.create_audio_clip(
        conn, track_id=audio_track, slot=2, length_beats=8.0,
        audio_file=ref, name="line", reverse=1,
    )

    plan = push.plan_push_clip(conn, clip_id=cid, session_id=session)

    assert plan.blocked_reasons == []
    audio_path = Path(_create_call(plan).args["audio_path"])
    assert audio_path.is_absolute()
    assert audio_path.parent == derived_cache.derived_dir(song_dir)
    assert audio_path.is_file()

    address = derived_cache.address_of_filename(audio_path.name)
    record = json.loads(
        (derived_cache.derived_dir(song_dir) / f"{address}.json").read_text()
    )
    assert [step["kind"] for step in record["chain"]] == ["reverse"]
    assert record["source"]["name"] == "line"


def test_the_derived_file_is_the_source_played_backwards(
    conn, session, audio_track, song_dir,
):
    """What ships is audio, not a name: the file the clip is pointed at holds
    the source's samples in the opposite order."""
    ref = _write_source(song_dir)
    _record_in_manifest(song_dir)
    cid = M.create_audio_clip(
        conn, track_id=audio_track, slot=1, length_beats=8.0,
        audio_file=ref, name="line", reverse=1,
    )

    plan = push.plan_push_clip(conn, clip_id=cid, session_id=session)

    played, sample_rate = sf.read(
        _create_call(plan).args["audio_path"], dtype="float32", always_2d=True,
    )
    assert sample_rate == SAMPLE_RATE
    np.testing.assert_allclose(played, _ramp()[::-1], atol=1e-6)


def test_a_sample_the_manifest_does_not_record_still_derives(
    conn, session, audio_track, song_dir,
):
    """A file referenced straight out of ``assets/`` — never ingested, so no
    manifest entry — is wrapped as an unmanifested source and addressed the
    same way, because the address is built from the bytes either way."""
    (song_dir / "assets" / "loose.wav").write_bytes(b"")
    sf.write(
        str(song_dir / "assets" / "loose.wav"), _ramp(), SAMPLE_RATE,
        subtype="FLOAT", format="WAV",
    )
    cid = M.create_audio_clip(
        conn, track_id=audio_track, slot=1, length_beats=8.0,
        audio_file="assets/loose.wav", name="loose", reverse=1,
    )

    plan = push.plan_push_clip(conn, clip_id=cid, session_id=session)

    assert plan.blocked_reasons == []
    audio_path = Path(_create_call(plan).args["audio_path"])
    assert audio_path.parent == derived_cache.derived_dir(song_dir)
    address = derived_cache.address_of_filename(audio_path.name)
    record = json.loads(
        (derived_cache.derived_dir(song_dir) / f"{address}.json").read_text()
    )
    assert record["source"]["checksum"] == store.file_checksum(
        song_dir / "assets" / "loose.wav"
    )


def test_a_forward_row_is_still_created_from_the_source(
    conn, session, audio_track, song_dir,
):
    """Nothing is derived for a row that did not ask for it: reverse NULL or 0
    plans the create against the file the row names."""
    ref = _write_source(song_dir)
    _record_in_manifest(song_dir)
    forward = M.create_audio_clip(
        conn, track_id=audio_track, slot=3, length_beats=8.0,
        audio_file=ref, name="line", reverse=0,
    )
    unset = M.create_audio_clip(
        conn, track_id=audio_track, slot=4, length_beats=8.0,
        audio_file=ref, name="line",
    )

    for cid in (forward, unset):
        plan = push.plan_push_clip(conn, clip_id=cid, session_id=session)
        assert _create_call(plan).args["audio_path"] == str(
            store.source_path(song_dir, "line")
        )
    assert not derived_cache.derived_dir(song_dir).exists()


# ---------------------------------------------------------------------------
# Flipping the flag flips the address
# ---------------------------------------------------------------------------


def test_flipping_the_flag_on_repoints_a_linked_clip(
    conn, session, audio_track, song_dir,
):
    """R5: Live plays the forward source, the row now says reversed, and the
    address the row resolves to is a different file — so this is the ordinary
    re-pointed-``audio_file`` reconcile: delete, then create from the derived
    file."""
    ref = _write_source(song_dir)
    _record_in_manifest(song_dir)
    cid = M.create_audio_clip(
        conn, track_id=audio_track, slot=1, length_beats=8.0,
        audio_file=ref, name="line", reverse=1,
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="clip", db_id=cid, ableton_index=1,
    )
    live = {4: [_live_slot(1, str(store.source_path(song_dir, "line")))]}

    plan = push.plan_push_clip(
        conn, clip_id=cid, session_id=session,
        live_session_clips_by_track=live,
    )

    assert [c.args["action"] for c in plan.calls][:2] == ["delete", "create"]
    assert Path(_create_call(plan).args["audio_path"]).parent == (
        derived_cache.derived_dir(song_dir)
    )


def test_flipping_the_flag_off_repoints_the_clip_back_to_the_source(
    conn, session, audio_track, song_dir,
):
    """The reverse direction of the same rule: Live plays the derived file, the
    row no longer asks for it, and the clip is rebuilt from the source."""
    ref = _write_source(song_dir)
    _record_in_manifest(song_dir)
    cid = M.create_audio_clip(
        conn, track_id=audio_track, slot=1, length_beats=8.0,
        audio_file=ref, name="line", reverse=1,
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="clip", db_id=cid, ableton_index=1,
    )
    reversed_path = _reversed_path(song_dir)

    M.update_clip(conn, clip_id=cid, reverse=0)
    plan = push.plan_push_clip(
        conn, clip_id=cid, session_id=session,
        live_session_clips_by_track={4: [_live_slot(1, reversed_path)]},
    )

    assert [c.args["action"] for c in plan.calls][:2] == ["delete", "create"]
    assert _create_call(plan).args["audio_path"] == str(
        store.source_path(song_dir, "line")
    )


def test_a_second_push_of_an_unchanged_reversed_clip_plans_nothing(
    conn, session, audio_track, song_dir,
):
    """The cache is content-addressed, so re-planning re-derives the SAME
    address and the probe reports Live already playing it: idempotent, which is
    what makes the derived route safe to run on every push."""
    ref = _write_source(song_dir)
    _record_in_manifest(song_dir)
    cid = M.create_audio_clip(
        conn, track_id=audio_track, slot=1, length_beats=8.0,
        audio_file=ref, name="line", reverse=1,
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="clip", db_id=cid, ableton_index=1,
    )
    derived_path = _reversed_path(song_dir)

    second = push.plan_push_clip(
        conn, clip_id=cid, session_id=session,
        live_session_clips_by_track={4: [_live_slot(1, derived_path)]},
    )

    assert second.calls == []
    assert second.blocked_reasons == []


# ---------------------------------------------------------------------------
# What it refuses rather than guessing
# ---------------------------------------------------------------------------


def test_a_missing_source_still_fails_loudly(
    conn, session, audio_track, song_dir,
):
    """The existence check runs before anything is derived: a row pointing at
    a file that is not there is blocked with no create, exactly as a forward
    row is."""
    cid = M.create_audio_clip(
        conn, track_id=audio_track, slot=1, length_beats=8.0,
        audio_file="assets/sources/gone.wav", name="gone", reverse=1,
    )

    plan = push.plan_push_clip(conn, clip_id=cid, session_id=session)

    assert plan.calls == []
    assert any("not on disk" in reason for reason in plan.blocked_reasons)


def test_a_source_that_no_longer_matches_its_checksum_is_refused(
    conn, session, audio_track, song_dir,
):
    """A source edited in place would be filed under an address that lies, so
    the derive refuses — and the row is blocked rather than placed FORWARD,
    which would report OK over audio the author did not write."""
    ref = _write_source(song_dir)
    _record_in_manifest(song_dir, checksum=FAKE_CHECKSUM)
    cid = M.create_audio_clip(
        conn, track_id=audio_track, slot=1, length_beats=8.0,
        audio_file=ref, name="line", reverse=1,
    )

    plan = push.plan_push_clip(conn, clip_id=cid, session_id=session)

    assert plan.calls == []
    assert any(
        "reverse=1" in reason and "has changed" in reason
        for reason in plan.blocked_reasons
    )


def test_an_undecodable_sample_is_refused_rather_than_crashing_the_plan(
    conn, session, audio_track, song_dir,
):
    """A push plans a whole song; one file libsndfile cannot open blocks its
    own row and leaves the rest of the plan to be made."""
    broken = song_dir / "assets" / "sources" / "broken.wav"
    broken.write_bytes(b"RIFF....WAVEfmt ")
    cid = M.create_audio_clip(
        conn, track_id=audio_track, slot=1, length_beats=8.0,
        audio_file="assets/sources/broken.wav", name="broken", reverse=1,
    )

    plan = push.plan_push_clip(conn, clip_id=cid, session_id=session)

    assert plan.calls == []
    assert any(
        "could not be derived" in reason for reason in plan.blocked_reasons
    )


# ---------------------------------------------------------------------------
# The unlinked-occupied-slot alert
# ---------------------------------------------------------------------------


def test_the_occupied_slot_alert_names_what_it_can_now_mean(
    conn, session, audio_track, song_dir,
):
    """Pull writes the link for every clip it ingests, so an unlinked row over
    an occupied slot is a hand-placed clip or a stale link — the alert says
    that, and no longer defers the question to an open issue."""
    ref = _write_source(song_dir)
    cid = M.create_audio_clip(
        conn, track_id=audio_track, slot=1, length_beats=8.0,
        audio_file=ref, name="line",
    )
    live = {4: [_live_slot(1, "/elsewhere/other.wav")]}

    plan = push.plan_push_clip(
        conn, clip_id=cid, session_id=session,
        live_session_clips_by_track=live,
    )

    alert = next(a for a in plan.alerts if "already" in a)
    assert "#507" not in alert
    assert "placed by hand" in alert
    assert "pull links what it ingests" in alert
