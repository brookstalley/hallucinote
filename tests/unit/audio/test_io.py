"""``load_capture`` reads a captures dir + manifest into in-memory
arrays. Tests use synthetic stems written to a temp dir per project
convention "Platform tests use synthetic fixtures, NOT song data."
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from hallucinote.audio.io import CaptureSet, load_capture

from .fixtures import SAMPLE_RATE, kick_onset, pink_noise, sine


def _write_manifest(
    tmp_path: Path,
    *,
    tracks: list[dict] | None = None,
    returns: list[dict] | None = None,
    master: dict | None = None,
    schema_version: str = "1",
) -> Path:
    manifest = {
        "schema_version": schema_version,
        "captured_at": "20260528T120000Z",
        "song_slug": "test-song",
        "start_at_beat": 0,
        "stop_at_beat": 16,
        "post_roll_beats": 4.0,
        "status": "ok",
        "frames_received": 100,
        "analyzer_signature": "hallucinote-analyzer-v1",
        "tracks": tracks or [],
        "returns": returns or [],
        "master": master,
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return path


def _write_stem(
    captures_dir: Path,
    *,
    filename: str,
    audio: np.ndarray,
    sr: int = SAMPLE_RATE,
) -> Path:
    """Write a float32 stereo WAV via soundfile (the canonical writer)."""
    out = captures_dir / filename
    sf.write(str(out), audio, sr, subtype="FLOAT")
    return out


def _surface_entry(track_id: str, filename: str, captures_dir: Path) -> dict:
    return {
        "track_id": track_id,
        "surface_name": track_id.replace(":", "_"),
        "surface_index": int(track_id.split(":")[-1]) if ":" in track_id else 0,
        "device_index": 1,
        "osc_port": 11020,
        "filename": filename,
        "absolute_path": str(captures_dir / filename),
    }


def test_load_capture_returns_structured_capture_set(tmp_path: Path):
    captures_dir = tmp_path
    _write_stem(captures_dir, filename="track-01.wav", audio=kick_onset())
    _write_stem(captures_dir, filename="track-02.wav", audio=sine(440, 0.25))
    _write_stem(captures_dir, filename="master.wav", audio=pink_noise(0.5))

    manifest_path = _write_manifest(
        captures_dir,
        tracks=[
            _surface_entry("track:1", "track-01.wav", captures_dir),
            _surface_entry("track:2", "track-02.wav", captures_dir),
        ],
        master=_surface_entry("master", "master.wav", captures_dir),
    )

    capture = load_capture(manifest_path)

    assert isinstance(capture, CaptureSet)
    assert capture.sample_rate == SAMPLE_RATE
    assert capture.song_slug == "test-song"
    assert capture.analyzer_signature == "hallucinote-analyzer-v1"
    assert len(capture.stems) == 2
    assert capture.master is not None
    assert capture.master.track_id == "master"
    assert capture.master.audio.dtype == np.float32
    assert capture.master.audio.shape[1] == 2
    assert capture.stems[0].track_id == "track:1"


def test_load_capture_includes_returns(tmp_path: Path):
    captures_dir = tmp_path
    _write_stem(captures_dir, filename="track-01.wav", audio=kick_onset())
    _write_stem(captures_dir, filename="return-01.wav", audio=pink_noise(0.25))
    _write_stem(captures_dir, filename="master.wav", audio=pink_noise(0.25))

    manifest_path = _write_manifest(
        captures_dir,
        tracks=[_surface_entry("track:1", "track-01.wav", captures_dir)],
        returns=[_surface_entry("return:1", "return-01.wav", captures_dir)],
        master=_surface_entry("master", "master.wav", captures_dir),
    )

    capture = load_capture(manifest_path)
    assert len(capture.returns) == 1
    assert capture.returns[0].track_id == "return:1"
    assert capture.returns[0].surface_kind == "return"


def test_load_capture_rejects_non_float32_wav(tmp_path: Path):
    captures_dir = tmp_path
    bad_audio = np.zeros((4800, 2), dtype=np.int16)
    sf.write(str(captures_dir / "track-01.wav"), bad_audio, SAMPLE_RATE,
             subtype="PCM_16")
    _write_stem(captures_dir, filename="master.wav", audio=pink_noise(0.25))
    manifest_path = _write_manifest(
        captures_dir,
        tracks=[_surface_entry("track:1", "track-01.wav", captures_dir)],
        master=_surface_entry("master", "master.wav", captures_dir),
    )

    with pytest.raises(ValueError, match="float32"):
        load_capture(manifest_path)


def test_load_capture_rejects_mono_wav(tmp_path: Path):
    captures_dir = tmp_path
    mono = np.zeros(4800, dtype=np.float32)
    sf.write(str(captures_dir / "track-01.wav"), mono, SAMPLE_RATE,
             subtype="FLOAT")
    _write_stem(captures_dir, filename="master.wav", audio=pink_noise(0.25))
    manifest_path = _write_manifest(
        captures_dir,
        tracks=[_surface_entry("track:1", "track-01.wav", captures_dir)],
        master=_surface_entry("master", "master.wav", captures_dir),
    )

    with pytest.raises(ValueError, match="stereo"):
        load_capture(manifest_path)


def test_load_capture_teaches_when_wav_missing(tmp_path: Path):
    captures_dir = tmp_path
    _write_stem(captures_dir, filename="master.wav", audio=pink_noise(0.25))
    manifest_path = _write_manifest(
        captures_dir,
        tracks=[_surface_entry("track:1", "no-such-track.wav", captures_dir)],
        master=_surface_entry("master", "master.wav", captures_dir),
    )

    with pytest.raises(FileNotFoundError, match="track:1"):
        load_capture(manifest_path)


def test_load_capture_teaches_on_schema_version_mismatch(tmp_path: Path):
    captures_dir = tmp_path
    _write_stem(captures_dir, filename="master.wav", audio=pink_noise(0.25))
    manifest_path = _write_manifest(
        captures_dir,
        master=_surface_entry("master", "master.wav", captures_dir),
        schema_version="99",
    )

    with pytest.raises(ValueError, match="schema_version"):
        load_capture(manifest_path)


def test_load_capture_requires_master(tmp_path: Path):
    """A capture without a master.wav is structurally broken — the
    master is the ground truth for attribution. Refuse with teaching."""
    captures_dir = tmp_path
    _write_stem(captures_dir, filename="track-01.wav", audio=kick_onset())
    manifest_path = _write_manifest(
        captures_dir,
        tracks=[_surface_entry("track:1", "track-01.wav", captures_dir)],
        master=None,
    )
    with pytest.raises(ValueError, match="master"):
        load_capture(manifest_path)
