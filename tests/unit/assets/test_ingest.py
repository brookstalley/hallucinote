"""Ingest normalizes what it is given, keeps what it must, and refuses the rest."""
from __future__ import annotations

import os
import stat

import numpy as np
import pytest
import soundfile as sf

from hallucinote.assets import ingest as ingest_mod
from hallucinote.assets import store
from hallucinote.tools import asset_ingest

NOTE = "the pilot's last transmission"
ORIGIN = "Rivers of Sand (1974), reel 3, the radio scene"


def _audio(seconds: float = 0.4, sample_rate: int = 44_100, channels: int = 1):
    t = np.arange(int(seconds * sample_rate), dtype=np.float64) / sample_rate
    mono = 0.3 * np.sin(2.0 * np.pi * 440.0 * t)
    return np.stack([mono] * channels, axis=1).astype(np.float32)


def _write(path, audio, sample_rate: int, **kwargs):
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), audio, sample_rate, **kwargs)
    return path


def _fake_ffmpeg(tmp_path, wav_bytes: bytes, *, exit_code: int = 0) -> str:
    """A shim named ``ffmpeg`` that emits a prepared WAV — never a real decode.

    Returns the directory to prepend to PATH.
    """
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir(exist_ok=True)
    payload = bin_dir / "payload.wav"
    payload.write_bytes(wav_bytes)
    shim = bin_dir / "ffmpeg"
    if exit_code == 0:
        shim.write_text(f'#!/bin/sh\ncat "{payload}"\n', encoding="utf-8")
    else:
        shim.write_text(
            f'#!/bin/sh\necho "fake ffmpeg: refusing" >&2\nexit {exit_code}\n',
            encoding="utf-8",
        )
    shim.chmod(shim.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return str(bin_dir)


def _wav_bytes(tmp_path, audio, sample_rate: int) -> bytes:
    path = _write(tmp_path / "payload-src.wav", audio, sample_rate)
    return path.read_bytes()


def test_a_wav_is_normalized_into_the_store_with_its_rate_and_channels_kept(tmp_path):
    song = tmp_path / "song"
    song.mkdir()
    dropped = _write(tmp_path / "drop" / "line.wav", _audio(channels=2, sample_rate=22_050), 22_050)

    result = ingest_mod.ingest(song, dropped, name="rivers-01", note=NOTE, origin=ORIGIN)

    landed = store.source_path(song, "rivers-01")
    assert landed.is_file()
    info = sf.info(str(landed))
    assert info.samplerate == 22_050
    assert info.channels == 2
    assert info.subtype == "FLOAT"
    assert result.source.sample_rate == 22_050
    assert result.source.channels == 2
    assert result.decoder == "soundfile"
    assert result.replaced is False


def test_a_flac_round_trips_through_soundfile_into_the_canonical_wav(tmp_path):
    song = tmp_path / "song"
    song.mkdir()
    audio = _audio(sample_rate=48_000)
    # FLAC is integer-coded; 24-bit keeps the round trip well inside the
    # tolerance below, so a difference here would be the normalizer's, not the
    # container's.
    dropped = _write(tmp_path / "drop" / "line.flac", audio, 48_000, subtype="PCM_24")

    result = ingest_mod.ingest(song, dropped, name="line", note=NOTE, origin=ORIGIN)

    landed, sample_rate = sf.read(str(store.source_path(song, "line")), dtype="float32",
                                  always_2d=True)
    assert sample_rate == 48_000
    assert landed.shape == audio.shape
    np.testing.assert_allclose(landed, audio, atol=1e-6)
    assert result.entry.original_format == "flac"
    assert result.entry.original_lossy is False


def test_a_container_soundfile_does_not_read_goes_through_ffmpeg(tmp_path, monkeypatch):
    song = tmp_path / "song"
    song.mkdir()
    audio = _audio(sample_rate=44_100)
    monkeypatch.setenv(
        "PATH",
        _fake_ffmpeg(tmp_path, _wav_bytes(tmp_path, audio, 44_100)) + os.pathsep
        + os.environ["PATH"],
    )
    dropped = tmp_path / "drop" / "line.mp3"
    dropped.parent.mkdir(parents=True)
    dropped.write_bytes(b"not really an mp3 - the shim decides what comes back")

    result = ingest_mod.ingest(song, dropped, name="line", note=NOTE, origin=ORIGIN)

    assert result.decoder == "ffmpeg"
    assert result.entry.original_lossy is True
    assert result.entry.original_format == "mp3"
    assert store.source_path(song, "line").is_file()
    assert result.source.duration_s == pytest.approx(0.4, abs=1e-3)


def test_an_ffmpeg_that_refuses_the_file_says_so(tmp_path, monkeypatch):
    song = tmp_path / "song"
    song.mkdir()
    monkeypatch.setenv(
        "PATH",
        _fake_ffmpeg(tmp_path, b"", exit_code=1) + os.pathsep + os.environ["PATH"],
    )
    dropped = tmp_path / "line.mp3"
    dropped.write_bytes(b"garbage")

    with pytest.raises(ValueError) as excinfo:
        ingest_mod.ingest(song, dropped, name="line", note=NOTE, origin=ORIGIN)
    assert "ffmpeg could not decode" in str(excinfo.value)
    assert "refusing" in str(excinfo.value)


def test_a_missing_ffmpeg_teaches_how_to_get_one(tmp_path, monkeypatch):
    song = tmp_path / "song"
    song.mkdir()
    empty = tmp_path / "emptybin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    dropped = tmp_path / "line.mp3"
    dropped.write_bytes(b"garbage")

    with pytest.raises(ValueError) as excinfo:
        ingest_mod.ingest(song, dropped, name="line", note=NOTE, origin=ORIGIN)
    message = str(excinfo.value)
    assert "not on PATH" in message
    assert "brew install ffmpeg" in message


def test_a_name_already_in_the_manifest_is_refused(tmp_path):
    song = tmp_path / "song"
    song.mkdir()
    dropped = _write(tmp_path / "line.wav", _audio(), 44_100)
    ingest_mod.ingest(song, dropped, name="line", note=NOTE, origin=ORIGIN)

    with pytest.raises(ValueError) as excinfo:
        ingest_mod.ingest(song, dropped, name="line", note=NOTE, origin=ORIGIN)
    assert "--replace" in str(excinfo.value)


def test_replace_keeps_the_slot_and_records_the_prior_checksum(tmp_path):
    song = tmp_path / "song"
    song.mkdir()
    first = _write(tmp_path / "first.wav", _audio(seconds=0.4), 44_100)
    second = _write(tmp_path / "second.wav", _audio(seconds=0.8), 44_100)
    original = ingest_mod.ingest(song, first, name="line", note=NOTE, origin=ORIGIN)

    result = ingest_mod.ingest(
        song, second, name="line", note="a longer take", origin=ORIGIN, replace=True
    )

    assert result.replaced is True
    assert result.entry.superseded == (original.entry.checksum,)
    assert result.entry.checksum != original.entry.checksum
    assert len(store.load_manifest(song).entries) == 1
    assert store.verify(song) == []


def test_a_third_ingest_keeps_the_whole_supersession_chain(tmp_path):
    song = tmp_path / "song"
    song.mkdir()
    takes = [
        _write(tmp_path / f"take{i}.wav", _audio(seconds=0.2 + 0.1 * i), 44_100)
        for i in range(3)
    ]
    checksums = []
    for i, take in enumerate(takes):
        result = ingest_mod.ingest(
            song, take, name="line", note=NOTE, origin=ORIGIN, replace=i > 0
        )
        checksums.append(result.entry.checksum)

    assert result.entry.superseded == tuple(checksums[:2])


def test_a_file_above_the_limit_is_refused_without_allow_large(tmp_path, monkeypatch):
    song = tmp_path / "song"
    song.mkdir()
    dropped = _write(tmp_path / "line.wav", _audio(), 44_100)
    monkeypatch.setattr(ingest_mod, "REFUSE_BYTES", 16)
    monkeypatch.setattr(ingest_mod, "WARN_BYTES", 8)

    with pytest.raises(ValueError) as excinfo:
        ingest_mod.ingest(song, dropped, name="line", note=NOTE, origin=ORIGIN)
    assert "--allow-large" in str(excinfo.value)
    assert not store.source_path(song, "line").exists()


def test_allow_large_ingests_it_anyway(tmp_path, monkeypatch):
    song = tmp_path / "song"
    song.mkdir()
    dropped = _write(tmp_path / "line.wav", _audio(), 44_100)
    monkeypatch.setattr(ingest_mod, "REFUSE_BYTES", 16)
    monkeypatch.setattr(ingest_mod, "WARN_BYTES", 8)

    result = ingest_mod.ingest(
        song, dropped, name="line", note=NOTE, origin=ORIGIN, allow_large=True
    )
    assert store.source_path(song, "line").is_file()
    assert result.warnings  # the size is still worth saying out loud


def test_a_middling_file_warns_without_refusing(tmp_path, monkeypatch):
    song = tmp_path / "song"
    song.mkdir()
    dropped = _write(tmp_path / "line.wav", _audio(), 44_100)
    monkeypatch.setattr(ingest_mod, "WARN_BYTES", 8)

    result = ingest_mod.ingest(song, dropped, name="line", note=NOTE, origin=ORIGIN)
    assert len(result.warnings) == 1
    assert "songs repo" in result.warnings[0]


def test_the_guard_thresholds_are_the_ones_the_binary_policy_names():
    assert ingest_mod.WARN_BYTES == 25 * 1024 * 1024
    assert ingest_mod.REFUSE_BYTES == 100 * 1024 * 1024


def test_a_file_that_is_not_there_is_refused(tmp_path):
    song = tmp_path / "song"
    song.mkdir()
    with pytest.raises(ValueError, match="no file at"):
        ingest_mod.ingest(song, tmp_path / "nope.wav", name="line", note=NOTE,
                          origin=ORIGIN)


@pytest.mark.parametrize("field", ["note", "origin"])
def test_provenance_prose_is_required(tmp_path, field):
    song = tmp_path / "song"
    song.mkdir()
    dropped = _write(tmp_path / "line.wav", _audio(), 44_100)
    kwargs = {"note": NOTE, "origin": ORIGIN}
    kwargs[field] = "   "
    with pytest.raises(ValueError, match=f"--{field}"):
        ingest_mod.ingest(song, dropped, name="line", **kwargs)


def test_a_name_that_would_escape_the_store_is_refused(tmp_path):
    song = tmp_path / "song"
    song.mkdir()
    dropped = _write(tmp_path / "line.wav", _audio(), 44_100)
    with pytest.raises(ValueError, match="not usable"):
        ingest_mod.ingest(song, dropped, name="../escape", note=NOTE, origin=ORIGIN)


def test_the_ingested_source_verifies_against_its_manifest_entry(tmp_path):
    song = tmp_path / "song"
    song.mkdir()
    dropped = _write(tmp_path / "line.wav", _audio(), 44_100)
    ingest_mod.ingest(song, dropped, name="line", note=NOTE, origin=ORIGIN)
    assert store.verify(song) == []


# --- the command a user actually runs -----------------------------------------


def test_the_cli_adds_a_source_and_says_what_it_did(tmp_path, capsys):
    song = tmp_path / "song"
    song.mkdir()
    dropped = _write(tmp_path / "line.wav", _audio(), 44_100)

    code = asset_ingest.main(
        ["add", str(dropped), "--name", "rivers-01", "--note", NOTE,
         "--origin", ORIGIN, "--song-dir", str(song)]
    )

    assert code == 0
    out = capsys.readouterr().out
    assert "added rivers-01" in out
    assert "assets/sources/rivers-01.wav" in out
    assert NOTE in out
    assert ORIGIN in out
    assert store.source(song, "rivers-01").path.is_file()


def test_the_cli_refuses_a_duplicate_and_explains(tmp_path, capsys):
    song = tmp_path / "song"
    song.mkdir()
    dropped = _write(tmp_path / "line.wav", _audio(), 44_100)
    args = ["add", str(dropped), "--name", "line", "--note", NOTE,
            "--origin", ORIGIN, "--song-dir", str(song)]
    asset_ingest.main(args)
    capsys.readouterr()

    assert asset_ingest.main(args) == 1
    assert "--replace" in capsys.readouterr().err


def test_the_cli_reports_a_song_directory_that_is_not_there(tmp_path):
    assert asset_ingest.main(
        ["add", str(tmp_path / "x.wav"), "--name", "line", "--note", NOTE,
         "--origin", ORIGIN, "--song-dir", str(tmp_path / "missing")]
    ) == 2


def test_the_cli_lists_what_the_song_holds(tmp_path, capsys):
    song = tmp_path / "song"
    song.mkdir()
    dropped = _write(tmp_path / "line.wav", _audio(), 44_100)
    asset_ingest.main(["add", str(dropped), "--name", "line", "--note", NOTE,
                       "--origin", ORIGIN, "--song-dir", str(song)])
    capsys.readouterr()

    assert asset_ingest.main(["list", "--song-dir", str(song)]) == 0
    out = capsys.readouterr().out
    assert "line:" in out
    assert NOTE in out


def test_the_cli_verify_fails_when_a_source_was_edited(tmp_path, capsys):
    song = tmp_path / "song"
    song.mkdir()
    dropped = _write(tmp_path / "line.wav", _audio(), 44_100)
    asset_ingest.main(["add", str(dropped), "--name", "line", "--note", NOTE,
                       "--origin", ORIGIN, "--song-dir", str(song)])
    assert asset_ingest.main(["verify", "--song-dir", str(song)]) == 0

    _write(store.source_path(song, "line"), _audio(seconds=0.9), 44_100)
    capsys.readouterr()
    assert asset_ingest.main(["verify", "--song-dir", str(song)]) == 3
    assert "changed since it was ingested" in capsys.readouterr().err


def test_the_copyright_note_is_where_a_user_meets_the_tool():
    assert "copyright" in asset_ingest.__doc__
    help_text = asset_ingest.build_parser().format_help()
    assert "copyright" in help_text
    assert "clearance is your call" in help_text
