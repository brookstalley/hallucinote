"""End-to-end ``analyze_mix`` integration over io + loudness + attribution
+ reverb modules.

These tests assemble synthetic captures on disk and assert the produced
``MixReport`` has the right shape + populated metrics. They're the
closest unit-level analog to the worked-example demo from spike §6 —
without yet running against a real song.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import soundfile as sf

from hallucinote.audio import DeclaredReverbSend, SectionWindow, analyze_mix
from hallucinote.audio.report import SCHEMA_VERSION

from .fixtures import (
    SAMPLE_RATE,
    calibrated_pink_noise,
    convolve,
    silence,
    sine,
    synthetic_ir,
)


def _write_synthetic_capture(
    tmp_path: Path,
    *,
    stems: list[tuple[str, str, np.ndarray]],
    returns: list[tuple[str, str, np.ndarray]] | None = None,
    master_audio: np.ndarray,
    start_at_beat: float = 0.0,
    stop_at_beat: float = 16.0,
) -> Path:
    """Write a captures dir + manifest mirroring what render produces."""
    returns = returns or []
    captures_dir = tmp_path / "captures" / "20260528T130000Z"
    captures_dir.mkdir(parents=True)

    def _entry(track_id: str, surface_name: str, filename: str) -> dict:
        return {
            "track_id": track_id,
            "surface_name": surface_name,
            "surface_index": 0,
            "device_index": 1,
            "osc_port": 11020,
            "filename": filename,
            "absolute_path": str(captures_dir / filename),
        }

    sf.write(str(captures_dir / "master.wav"), master_audio,
             SAMPLE_RATE, subtype="FLOAT")
    track_entries = []
    for track_id, surface_name, audio in stems:
        filename = f"{track_id.replace(':', '-')}.wav"
        sf.write(str(captures_dir / filename), audio, SAMPLE_RATE,
                 subtype="FLOAT")
        track_entries.append(_entry(track_id, surface_name, filename))
    return_entries = []
    for track_id, surface_name, audio in returns:
        filename = f"{track_id.replace(':', '-')}.wav"
        sf.write(str(captures_dir / filename), audio, SAMPLE_RATE,
                 subtype="FLOAT")
        return_entries.append(_entry(track_id, surface_name, filename))

    manifest = {
        "schema_version": "1",
        "captured_at": "20260528T130100Z",
        "song_slug": "test-song",
        "start_at_beat": start_at_beat,
        "stop_at_beat": stop_at_beat,
        "post_roll_beats": 4.0,
        "status": "ok",
        "frames_received": 400,
        "analyzer_signature": "hallucinote-analyzer-v1",
        "tracks": track_entries,
        "returns": return_entries,
        "master": _entry("master", "Main", "master.wav"),
    }
    (captures_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return captures_dir


def test_analyze_mix_produces_populated_mixreport_with_no_overshoots(tmp_path: Path):
    """Calm input → loudness numbers everywhere, zero overshoots, reverb
    section skipped (no declared sends), no findings."""
    duration_s = 4.0
    stems = [
        ("track:1", "01 Drums", calibrated_pink_noise(-26.0, duration_s)),
        ("track:2", "02 Bass", calibrated_pink_noise(-26.0, duration_s)),
    ]
    master = calibrated_pink_noise(-20.0, duration_s)
    captures_dir = _write_synthetic_capture(tmp_path, stems=stems, master_audio=master)

    report = analyze_mix(captures_dir)

    assert report.schema_version == SCHEMA_VERSION
    assert report.song_slug == "test-song"
    assert len(report.stems) == 2
    assert report.master.loudness.lufs_i < 0
    assert report.overshoots == []
    assert report.skipped_analyses[0]["kind"] == "reverb_verification"
    assert report.findings == []


def test_analyze_mix_attributes_overshoot_to_loud_stem(tmp_path: Path):
    """Hot kick + bass in the middle of a 2s capture → master overshoot
    detected, kick + bass dominate attribution in the low_60_200 band."""
    duration_s = 2.0
    silence_audio = silence(duration_s)
    hot_start = int(0.5 * SAMPLE_RATE)
    hot_end = int(1.5 * SAMPLE_RATE)
    hot_win = (hot_end - hot_start) / SAMPLE_RATE

    kick = silence_audio.copy()
    bass = silence_audio.copy()
    rhythm = silence_audio.copy()
    kick[hot_start:hot_end] = sine(60.0, hot_win, amplitude=0.6)
    bass[hot_start:hot_end] = sine(100.0, hot_win, amplitude=0.5)
    rhythm[hot_start:hot_end] = sine(1000.0, hot_win, amplitude=0.3)
    master = (kick + bass + rhythm) * 1.5

    captures_dir = _write_synthetic_capture(
        tmp_path,
        stems=[
            ("track:1", "01 Kick", kick),
            ("track:2", "02 Bass", bass),
            ("track:3", "03 Rhythm", rhythm),
        ],
        master_audio=master,
        start_at_beat=0.0,
        stop_at_beat=8.0,
    )

    report = analyze_mix(captures_dir)
    assert len(report.overshoots) >= 1
    overshoot = report.overshoots[0]
    assert overshoot.dominant_band == "low_60_200"
    # Beat conversion: 8 beats spread over 2 seconds → 4 beats/sec.
    # Hot window 0.5..1.5 s should map to bar ~2.0..6.0 in beat-space.
    assert 1.0 < overshoot.start_beat < 3.0
    assert 5.0 < overshoot.end_beat < 7.0
    by_track = dict(overshoot.attribution)
    assert by_track.get("track:1", 0) + by_track.get("track:2", 0) > 0.6
    # Finding for the overshoot should be present.
    assert any(f.kind == "master_overshoot" for f in report.findings)


def test_analyze_mix_runs_declared_reverb_verification(tmp_path: Path):
    """When the caller declares a dry→wet send with target RT60, the
    pipeline measures it and emits a ReverbVerification record."""
    duration_s = 3.0
    declared = 0.8
    ir = synthetic_ir(declared, duration_s=duration_s)
    # Use a single impulse as the dry; pure-impulse dry deconvolves cleanly.
    dry = silence(duration_s)
    dry[0, 0] = 1.0
    dry[0, 1] = 1.0
    wet = convolve(dry, ir)
    master = (dry + wet * 0.4)  # any signal that has SOME content

    captures_dir = _write_synthetic_capture(
        tmp_path,
        stems=[("track:1", "01 Snare", dry)],
        returns=[("return:1", "A-Plate", wet)],
        master_audio=master,
    )

    sends = [DeclaredReverbSend(
        dry_track_id="track:1",
        wet_return_track_id="return:1",
        declared_rt60_s=declared,
    )]
    report = analyze_mix(captures_dir, declared_reverb_sends=sends)
    assert len(report.reverb_verifications) == 1
    v = report.reverb_verifications[0]
    assert v.declared_rt60_s == declared
    assert v.within_tolerance is True
    # No skipped reverb entry when a send was actually declared.
    assert not any(s.get("kind") == "reverb_verification"
                   for s in report.skipped_analyses)


def test_analyze_mix_records_skip_when_declared_track_not_in_capture(tmp_path: Path):
    """Declared dry/wet pointing at IDs that didn't get captured → record
    the skip with a teaching reason rather than crashing."""
    duration_s = 2.0
    captures_dir = _write_synthetic_capture(
        tmp_path,
        stems=[("track:1", "01 Snare", silence(duration_s))],
        master_audio=silence(duration_s),
    )
    sends = [DeclaredReverbSend(
        dry_track_id="track:99",  # doesn't exist
        wet_return_track_id="return:99",  # doesn't exist
        declared_rt60_s=1.0,
    )]
    report = analyze_mix(captures_dir, declared_reverb_sends=sends)
    assert report.reverb_verifications == []
    assert any(
        "track:99" in s.get("reason", "")
        for s in report.skipped_analyses
    )


# ---------- per-section windowing ----------


def test_analyze_mix_skips_section_pass_when_none_declared(tmp_path: Path):
    """No declared sections → per_section empty + a teaching skip entry,
    symmetric with the reverb-verification skip."""
    duration_s = 2.0
    captures_dir = _write_synthetic_capture(
        tmp_path,
        stems=[("track:1", "01 Drums", calibrated_pink_noise(-26.0, duration_s))],
        master_audio=calibrated_pink_noise(-20.0, duration_s),
    )
    report = analyze_mix(captures_dir)
    assert report.per_section == []
    assert any(s.get("kind") == "section_windowed" for s in report.skipped_analyses)


def test_analyze_mix_populates_per_section_loudness(tmp_path: Path):
    """Two sections spanning the capture → one SectionMetrics each, keyed by
    name, with master + per-stem loudness scoped to the window. The loud
    half should read louder than the quiet half on the master."""
    duration_s = 4.0
    # Quiet first half, hot second half, on both the stem and the master.
    quiet = calibrated_pink_noise(-30.0, duration_s / 2)
    loud = calibrated_pink_noise(-14.0, duration_s / 2)
    stem = np.concatenate([quiet, loud], axis=0)
    master = stem.copy()
    captures_dir = _write_synthetic_capture(
        tmp_path,
        stems=[("track:1", "01 Synth", stem)],
        master_audio=master,
        start_at_beat=0.0,
        stop_at_beat=16.0,
    )
    sections = [
        SectionWindow(name="verse", start_beat=0.0, end_beat=8.0),
        SectionWindow(name="chorus", start_beat=8.0, end_beat=16.0),
    ]
    report = analyze_mix(captures_dir, sections=sections)

    assert [s.section_name for s in report.per_section] == ["verse", "chorus"]
    verse, chorus = report.per_section
    assert verse.master.surface_kind == "master"
    assert len(verse.stems) == 1
    assert verse.stems[0].track_id == "track:1"
    # Chorus (hot second half) is louder than verse (quiet first half).
    assert chorus.master.loudness.lufs_i > verse.master.loudness.lufs_i + 5.0
    # No section skip when sections were actually declared and covered.
    assert not any(
        s.get("kind") == "section_windowed" for s in report.skipped_analyses
    )


def test_analyze_mix_records_skip_for_section_outside_capture(tmp_path: Path):
    """A section beyond the captured transport window → recorded as a skip
    with a teaching reason, not emitted with empty metrics."""
    duration_s = 2.0
    captures_dir = _write_synthetic_capture(
        tmp_path,
        stems=[("track:1", "01 Drums", calibrated_pink_noise(-26.0, duration_s))],
        master_audio=calibrated_pink_noise(-20.0, duration_s),
        start_at_beat=0.0,
        stop_at_beat=8.0,
    )
    sections = [
        SectionWindow(name="intro", start_beat=0.0, end_beat=8.0),
        SectionWindow(name="bridge", start_beat=16.0, end_beat=24.0),  # not captured
    ]
    report = analyze_mix(captures_dir, sections=sections)
    assert [s.section_name for s in report.per_section] == ["intro"]
    assert any(
        s.get("kind") == "section_windowed" and "bridge" in s.get("reason", "")
        for s in report.skipped_analyses
    )


def test_analyze_mix_tags_overshoot_finding_with_section(tmp_path: Path):
    """A master overshoot inside a declared section → the finding's
    db_reference names that section."""
    duration_s = 2.0
    silence_audio = silence(duration_s)
    hot_start = int(0.5 * SAMPLE_RATE)
    hot_end = int(1.5 * SAMPLE_RATE)
    hot_win = (hot_end - hot_start) / SAMPLE_RATE
    kick = silence_audio.copy()
    kick[hot_start:hot_end] = sine(60.0, hot_win, amplitude=0.6)
    master = kick * 1.8

    captures_dir = _write_synthetic_capture(
        tmp_path,
        stems=[("track:1", "01 Kick", kick)],
        master_audio=master,
        start_at_beat=0.0,
        stop_at_beat=8.0,
    )
    # The hot window maps to beats ~2..6; a section covering 0..8 contains it.
    sections = [SectionWindow(name="chorus1", start_beat=0.0, end_beat=8.0)]
    report = analyze_mix(captures_dir, sections=sections)

    overshoot_findings = [f for f in report.findings if f.kind == "master_overshoot"]
    assert overshoot_findings
    assert all("section:chorus1" in f.db_reference for f in overshoot_findings)
