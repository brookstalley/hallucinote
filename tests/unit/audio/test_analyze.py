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
import pytest
import soundfile as sf

from hallucinote.audio import (
    DeclaredEnvelope,
    DeclaredReverbSend,
    SectionEnergy,
    SectionWindow,
    TempoSegment,
    analyze_mix,
)
from hallucinote.audio.report import SCHEMA_VERSION
from hallucinote.audio.reverb import REVERB_TOLERANCE_S

from .fixtures import (
    SAMPLE_RATE,
    calibrated_pink_noise,
    concat,
    convolve,
    onsets_at_beats,
    pink_noise,
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
    ring_out_beats: float = 0.0,
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
        "ring_out_beats": ring_out_beats,
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
    """A declared send + a captured ring-out → one per-RETURN
    ReverbVerification, RT60 measured from the return's own decay tail. The
    capture spans song [0, stop] + ring-out [stop, stop+ring_out]; the return
    decays into silence over the ring-out region."""
    rt60 = 0.8
    total_s, input_s = 5.0, 2.0
    ir = synthetic_ir(rt60, duration_s=total_s)
    tot_n, in_n = int(total_s * SAMPLE_RATE), int(input_s * SAMPLE_RATE)
    dry = np.zeros((tot_n, 2), dtype=np.float32)
    dry[:in_n] = sine(220.0, input_s)   # dry input plays, then stops
    wet = convolve(dry, ir)             # return rings out after input stops
    master = (dry + wet * 0.4).astype(np.float32)

    captures_dir = _write_synthetic_capture(
        tmp_path,
        stems=[("track:1", "01 Snare", dry)],
        returns=[("return:1", "A-Plate", wet)],
        master_audio=master,
        # beat split mirrors the time split: 20/(20+30) = 0.4 = input_s/total_s,
        # so beat_to_sample(stop_at_beat) lands at the input-stop sample.
        stop_at_beat=20.0,
        ring_out_beats=30.0,
    )

    sends = [DeclaredReverbSend(
        dry_track_id="track:1",
        wet_return_track_id="return:1",
        declared_rt60_s=rt60,
    )]
    report = analyze_mix(captures_dir, declared_reverb_sends=sends)
    assert len(report.reverb_verifications) == 1
    v = report.reverb_verifications[0]
    assert v.return_track_id == "return:1"
    assert v.declared_rt60_s == rt60
    assert v.contributing_track_ids == ("track:1",)
    assert v.conflicting_declarations == ()
    assert v.sufficient_tail is True
    assert abs(v.measured_rt60_s - rt60) <= REVERB_TOLERANCE_S
    assert v.within_tolerance is True
    # No skipped reverb entry when a send was actually declared.
    assert not any(s.get("kind") == "reverb_verification"
                   for s in report.skipped_analyses)


def test_analyze_mix_groups_sends_into_one_per_return(tmp_path: Path):
    """Two sends into the SAME return (the real multi-send case) collapse to ONE
    per-return verification, recording both contributing dry sources."""
    rt60 = 1.0
    total_s, input_s = 5.0, 2.0
    ir = synthetic_ir(rt60, duration_s=total_s)
    tot_n, in_n = int(total_s * SAMPLE_RATE), int(input_s * SAMPLE_RATE)
    dry_a = np.zeros((tot_n, 2), dtype=np.float32)
    dry_b = np.zeros((tot_n, 2), dtype=np.float32)
    dry_a[:in_n] = sine(220.0, input_s)
    dry_b[:in_n] = sine(330.0, input_s)
    wet = convolve((dry_a + dry_b).astype(np.float32), ir)
    master = ((dry_a + dry_b) + wet * 0.4).astype(np.float32)

    captures_dir = _write_synthetic_capture(
        tmp_path,
        stems=[("track:1", "01 Gtr", dry_a), ("track:2", "02 Keys", dry_b)],
        returns=[("return:1", "A-Plate", wet)],
        master_audio=master,
        stop_at_beat=20.0,
        ring_out_beats=30.0,
    )
    sends = [
        DeclaredReverbSend(dry_track_id="track:1",
                           wet_return_track_id="return:1", declared_rt60_s=rt60),
        DeclaredReverbSend(dry_track_id="track:2",
                           wet_return_track_id="return:1", declared_rt60_s=rt60),
    ]
    report = analyze_mix(captures_dir, declared_reverb_sends=sends)
    assert len(report.reverb_verifications) == 1  # one PER RETURN, not per send
    v = report.reverb_verifications[0]
    assert v.return_track_id == "return:1"
    assert set(v.contributing_track_ids) == {"track:1", "track:2"}
    assert v.sufficient_tail is True
    assert abs(v.measured_rt60_s - rt60) <= REVERB_TOLERANCE_S


def test_analyze_mix_surfaces_conflicting_rt60_declarations(tmp_path: Path):
    """Sends into the SAME return declaring DIFFERENT RT60s is a contradiction
    (one device, one decay time) — surfaced via conflicting_declarations + a
    reverb_conflicting_declaration finding, measured against the modal value.
    (The conflict is at the declaration level, independent of the audio.)"""
    dry = sine(220.0, 3.0, amplitude=0.4)
    wet = pink_noise(3.0, amplitude=0.3)
    master = (dry + wet * 0.4).astype(np.float32)
    captures_dir = _write_synthetic_capture(
        tmp_path,
        stems=[("track:1", "01", dry)],
        returns=[("return:1", "A-Plate", wet)],
        master_audio=master,
        stop_at_beat=16.0,
        ring_out_beats=0.0,
    )
    # 2 sends declare 3.0, 1 declares 0.8 → modal is 3.0; contributing dry IDs
    # are recorded as provenance (they need not all be captured surfaces).
    sends = [
        DeclaredReverbSend(dry_track_id="track:1",
                           wet_return_track_id="return:1", declared_rt60_s=3.0),
        DeclaredReverbSend(dry_track_id="track:2",
                           wet_return_track_id="return:1", declared_rt60_s=3.0),
        DeclaredReverbSend(dry_track_id="track:3",
                           wet_return_track_id="return:1", declared_rt60_s=0.8),
    ]
    report = analyze_mix(captures_dir, declared_reverb_sends=sends)
    assert len(report.reverb_verifications) == 1  # still one per return
    v = report.reverb_verifications[0]
    assert v.conflicting_declarations == (0.8, 3.0)   # sorted distinct
    assert v.declared_rt60_s == 3.0                    # modal (2 of 3 votes)
    assert set(v.contributing_track_ids) == {"track:1", "track:2", "track:3"}
    assert any(f.kind == "reverb_conflicting_declaration" for f in report.findings)


def test_analyze_mix_no_ringout_emits_honest_insufficient_tail(tmp_path: Path):
    """The real-capture case: no ring-out (ring_out_beats=0, content to the end)
    → an honest insufficient-tail verdict + finding, NOT a fabricated RT60."""
    duration_s = 3.0
    # Continuous content to the last sample — no decay region.
    dry = sine(220.0, duration_s)
    wet = pink_noise(duration_s, amplitude=0.4)
    master = (dry + wet * 0.4).astype(np.float32)
    captures_dir = _write_synthetic_capture(
        tmp_path,
        stems=[("track:1", "01 Snare", dry)],
        returns=[("return:1", "A-Plate", wet)],
        master_audio=master,
        stop_at_beat=16.0,
        ring_out_beats=0.0,  # no ring-out captured
    )
    sends = [DeclaredReverbSend(dry_track_id="track:1",
                                wet_return_track_id="return:1", declared_rt60_s=2.0)]
    report = analyze_mix(captures_dir, declared_reverb_sends=sends)
    assert len(report.reverb_verifications) == 1
    v = report.reverb_verifications[0]
    assert v.sufficient_tail is False
    assert np.isnan(v.measured_rt60_s)
    assert v.within_tolerance is False
    # Surfaced as a finding pointing at the remedy (re-render with ring_out).
    assert any(f.kind == "reverb_insufficient_tail" for f in report.findings)


def test_derive_findings_insufficient_tail_remedy_is_mode_aware():
    """The insufficient-tail remedy must match the failure mode. A genuinely
    absent tail (span ~0) → re-render with more ring_out_beats. A captured-but-
    too-shallow tail (the return's wet path is too quiet) must NOT tell the user
    to add ring_out_beats — that adds time, not level, and won't help."""
    from hallucinote.audio.analyze import _derive_findings
    from hallucinote.audio.report import (
        LoudnessMetrics,
        ReverbVerification,
        StemMetrics,
    )

    master = StemMetrics(
        track_id="master",
        surface_kind="master",
        surface_name="Main",
        loudness=LoudnessMetrics(-12.0, -14.0, -8.0, -1.0),
    )
    no_tail = ReverbVerification(
        return_track_id="return:1", declared_rt60_s=2.0,
        measured_rt60_s=float("nan"), within_tolerance=False,
        tolerance_s=0.15, tail_span_db=0.0, sufficient_tail=False,
    )
    shallow_tail = ReverbVerification(
        return_track_id="return:2", declared_rt60_s=0.8,
        measured_rt60_s=float("nan"), within_tolerance=False,
        tolerance_s=0.15, tail_span_db=13.5, sufficient_tail=False,
    )
    findings = _derive_findings(
        master=master, stems=[], overshoots=[],
        reverbs=[no_tail, shallow_tail],
    )
    by_subject = {
        f.subject: f for f in findings
        if f.kind == "reverb_insufficient_tail"
    }
    assert set(by_subject) == {"return:1", "return:2"}
    # No tail at all → remedy IS more ring-out.
    assert "ring_out_beats" in by_subject["return:1"].db_reference
    # Shallow tail → remedy is NOT more ring-out; it points at the wet level.
    shallow_msg = by_subject["return:2"].db_reference
    assert "13.5" in shallow_msg
    assert "won't help" in shallow_msg
    assert "isolation" in shallow_msg or "send level" in shallow_msg


def test_analyze_mix_records_skip_when_declared_return_not_in_capture(tmp_path: Path):
    """A send to a return that wasn't captured → record the skip with a
    teaching reason rather than crashing."""
    duration_s = 2.0
    captures_dir = _write_synthetic_capture(
        tmp_path,
        stems=[("track:1", "01 Snare", silence(duration_s))],
        master_audio=silence(duration_s),
    )
    sends = [DeclaredReverbSend(
        dry_track_id="track:1",
        wet_return_track_id="return:99",  # doesn't exist
        declared_rt60_s=1.0,
    )]
    report = analyze_mix(captures_dir, declared_reverb_sends=sends)
    assert report.reverb_verifications == []
    assert any(
        "return:99" in s.get("reason", "")
        for s in report.skipped_analyses
    )


# ---------- automation verification (AUD-8H2M) ----------


def test_analyze_mix_verifies_declared_device_parameter_flip(tmp_path: Path):
    """A declared Amp-Type flip with a real dark→bright timbre step at the
    breakpoint reads as a realized automation change through analyze_mix."""
    half = 2.0  # seconds; 16-beat span splits at beat 8 = the audio midpoint
    stem = concat(sine(300.0, half, amplitude=0.5),
                  sine(3500.0, half, amplitude=0.5))
    captures_dir = _write_synthetic_capture(
        tmp_path,
        stems=[("track:3", "03 Rhythm Gtr", stem)],
        master_audio=stem.copy(),
        stop_at_beat=16.0,
    )
    envs = [DeclaredEnvelope(
        target_surface_id="track:3",
        target_kind="device_parameter",
        parameter_path="Amp Type",
        breakpoints=((0.0, 0.0), (8.0, 1.0)),
    )]
    report = analyze_mix(captures_dir, declared_envelopes=envs)
    assert len(report.automation_verifications) == 1
    v = report.automation_verifications[0]
    assert v.target_surface_id == "track:3"
    assert v.realized is True and v.measurable is True
    assert not any(s.get("kind") == "automation_verification"
                   for s in report.skipped_analyses)


def test_analyze_mix_flags_unrealized_automation(tmp_path: Path):
    """A flat stem at a declared flip → automation_not_realized finding."""
    flat = sine(440.0, 4.0, amplitude=0.5)
    captures_dir = _write_synthetic_capture(
        tmp_path,
        stems=[("track:3", "03 Rhythm Gtr", flat)],
        master_audio=flat.copy(),
        stop_at_beat=16.0,
    )
    envs = [DeclaredEnvelope(
        target_surface_id="track:3",
        target_kind="device_parameter",
        parameter_path="Amp Type",
        breakpoints=((0.0, 0.0), (8.0, 1.0)),
    )]
    report = analyze_mix(captures_dir, declared_envelopes=envs)
    assert report.automation_verifications[0].realized is False
    assert any(f.kind == "automation_not_realized" for f in report.findings)


def test_analyze_mix_verifies_declared_mixer_volume_on_master(tmp_path: Path):
    """AUD-3F8M end-to-end: a declared mixer_volume swell whose level step is
    in the master reports measurable=True + realized=True through analyze_mix
    (the master plumb-through, not just the unit-level verifier)."""
    from hallucinote.audio.levels import live_fader_gain

    stem_half = sine(220.0, 2.0, amplitude=0.4)
    rest_half = sine(660.0, 2.0, amplitude=0.3)
    stem = concat(stem_half, stem_half)
    v1, v2 = 0.5, 0.85
    master = concat(rest_half + stem_half * live_fader_gain(v1),
                    rest_half + stem_half * live_fader_gain(v2))
    captures_dir = _write_synthetic_capture(
        tmp_path,
        stems=[("track:1", "01 Bass", stem)],
        master_audio=master,
        stop_at_beat=16.0,
    )
    envs = [DeclaredEnvelope(
        target_surface_id="track:1",
        target_kind="mixer_volume",
        parameter_path=None,
        breakpoints=((0.0, v1), (8.0, v2)),
    )]
    report = analyze_mix(captures_dir, declared_envelopes=envs)
    assert len(report.automation_verifications) == 1
    v = report.automation_verifications[0]
    assert v.metric == "master_rms_db"
    assert v.measurable is True and v.realized is True


def test_analyze_mix_skips_when_no_automation_declared(tmp_path: Path):
    """No declared envelopes → a teaching skip, symmetric with reverb/section."""
    flat = sine(440.0, 2.0, amplitude=0.5)
    captures_dir = _write_synthetic_capture(
        tmp_path, stems=[("track:1", "01", flat)], master_audio=flat.copy(),
    )
    report = analyze_mix(captures_dir)
    assert report.automation_verifications == []
    assert any(s.get("kind") == "automation_verification"
               for s in report.skipped_analyses)


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


def test_analyze_mix_populates_energy_realization(tmp_path: Path):
    """With declared_energy, analyze_mix populates MixReport.energy_realization:
    a quiet-verse / loud-chorus render with declared verse<chorus energy reads a
    monotonic loudness ρ (the arc tracked intent) — joined by start_beat."""
    duration_s = 4.0
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
    declared_energy = [
        SectionEnergy(start_beat=0.0, name="verse", energy=0.4),
        SectionEnergy(start_beat=8.0, name="chorus", energy=0.9),
    ]
    report = analyze_mix(
        captures_dir, sections=sections, declared_energy=declared_energy,
    )

    er = report.energy_realization
    assert er is not None
    # Declared verse<chorus, measured verse quieter than chorus → ρ == 1.0
    # (monotonic, within float tolerance — Spearman over n=2 lands at
    # 0.9999999999999999) and zero loudness inversions; joined by start_beat.
    assert er.correlate_rho["loudness"] == pytest.approx(1.0)
    assert [i for i in er.inversions if i.correlate == "loudness"] == []
    assert {s.start_beat for s in er.sections_ranked} == {0.0, 8.0}
    # Serializes under the strict-JSON backstop (None-or-finite, never nan).
    json.dumps(report.to_json_dict(), allow_nan=False)


def test_analyze_mix_skips_energy_realization_when_none_declared(tmp_path: Path):
    """No declared_energy → energy_realization is None + a structured
    skipped_analyses entry (never a fabricated ρ)."""
    duration_s = 2.0
    stem = calibrated_pink_noise(-20.0, duration_s)
    captures_dir = _write_synthetic_capture(
        tmp_path, stems=[("track:1", "01 Synth", stem)], master_audio=stem,
        start_at_beat=0.0, stop_at_beat=8.0,
    )
    sections = [SectionWindow(name="verse", start_beat=0.0, end_beat=8.0)]
    report = analyze_mix(captures_dir, sections=sections)
    assert report.energy_realization is None
    assert any(
        s.get("kind") == "energy_realization" for s in report.skipped_analyses
    )


def test_analyze_mix_populates_per_section_attribution(tmp_path: Path):
    """Each covered section carries per-band stem-dominance: a low-frequency
    stem owns the low band, a high-frequency stem owns the air band — the
    'kick + bass dominate the chorus low end' question, answerable per-section.
    """
    dur = 4.0
    kick = sine(100.0, dur, amplitude=0.5)   # low_60_200
    hat = sine(9000.0, dur, amplitude=0.5)   # air_6k_plus
    master = kick + hat
    captures_dir = _write_synthetic_capture(
        tmp_path,
        stems=[("track:1", "Kick", kick), ("track:2", "Hat", hat)],
        master_audio=master,
        start_at_beat=0.0,
        stop_at_beat=16.0,
    )
    sections = [SectionWindow(name="verse", start_beat=0.0, end_beat=16.0)]
    report = analyze_mix(captures_dir, sections=sections)

    sec = report.per_section[0]
    by_band = {b.band: b for b in sec.attribution}
    assert by_band["low_60_200"].contributors[0][0] == "track:1"
    assert by_band["air_6k_plus"].contributors[0][0] == "track:2"

    # Serialization carries it, in BANDS order, contributors as [tid, frac].
    sec_json = report.to_json_dict()["per_section"][0]
    assert sec_json["attribution"][0]["band"] == "sub_20_60"
    low = next(b for b in sec_json["attribution"] if b["band"] == "low_60_200")
    assert low["contributors"][0][0] == "track:1"
    assert isinstance(low["contributors"][0][1], float)


def test_analyze_mix_populates_section_masking_when_enabled(tmp_path: Path):
    """With ``analyze_masking=True``, a covered section carries inter-stem
    masking evidence: a loud stem co-timed with a quiet one in the same band
    reads as masking it, and it serializes under ``per_section[].masking``.
    """
    dur = 4.0
    loud = sine(2000.0, dur, amplitude=0.8)
    quiet = sine(2100.0, dur, amplitude=0.01)
    master = loud + quiet
    captures_dir = _write_synthetic_capture(
        tmp_path,
        stems=[("track:1", "Loud", loud), ("track:2", "Quiet", quiet)],
        master_audio=master,
        start_at_beat=0.0,
        stop_at_beat=16.0,
    )
    sections = [SectionWindow(name="verse", start_beat=0.0, end_beat=16.0)]

    # Off by default — no masking computed.
    off = analyze_mix(captures_dir, sections=sections)
    assert off.per_section[0].masking == []

    on = analyze_mix(captures_dir, sections=sections, analyze_masking=True)
    sec = on.per_section[0]
    assert sec.masking, "expected at least one masking pair"
    top = sec.masking[0]
    assert top.masker_track_id == "track:1"
    assert top.maskee_track_id == "track:2"
    assert top.masked_fraction > 0.5

    sec_json = on.to_json_dict()["per_section"][0]
    assert sec_json["masking"][0]["masker_track_id"] == "track:1"
    assert isinstance(sec_json["masking"][0]["masked_fraction"], float)
    assert "bed_masking" in sec_json


def test_analyze_mix_populates_section_timing_when_enabled(tmp_path: Path):
    """With ``analyze_timing=True``, a covered section carries per-part
    onset-vs-grid feel: a tight on-grid stem reads tight + on-grid, a swung
    stem reads a swing ratio, and it serializes under ``per_section[].timing``.

    The capture is 16 beats over 8 s → effective 120 bpm, which the analyzer
    derives from the shared BeatSampleMap (no tempo passed in)."""
    bpm = 120.0
    tight = onsets_at_beats(list(range(16)), bpm=bpm, total_beats=16.0)
    swung = onsets_at_beats(
        [v for b in range(16) for v in (b, b + 0.6667)], bpm=bpm, total_beats=16.0,
    )
    master = tight + swung
    captures_dir = _write_synthetic_capture(
        tmp_path,
        stems=[("track:1", "Tight", tight), ("track:2", "Swung", swung)],
        master_audio=master,
        start_at_beat=0.0,
        stop_at_beat=16.0,
    )
    sections = [SectionWindow(name="verse", start_beat=0.0, end_beat=16.0)]

    # Off by default — no timing computed; onset density rides the same grid
    # geometry, so it's None when neither timing nor cross-rhythm is enabled.
    off = analyze_mix(captures_dir, sections=sections)
    assert off.per_section[0].timing == []
    assert off.per_section[0].onset_density is None

    on = analyze_mix(captures_dir, sections=sections, analyze_timing=True)
    sec = on.per_section[0]
    by_id = {t.track_id: t for t in sec.timing}
    assert "track:1" in by_id and "track:2" in by_id

    # ARR-7M3D: density populated (onsets summed across the 2 stems / beats);
    # the tight+swung 16-beat section is busy, so density is well above zero.
    assert sec.onset_density is not None and sec.onset_density > 1.0
    assert on.to_json_dict()["per_section"][0]["onset_density"] == sec.onset_density

    assert abs(by_id["track:1"].mean_drift_beats) < 0.03   # tight, on grid
    assert by_id["track:1"].drift_stdev_beats < 0.02
    assert by_id["track:2"].swing_ratio is not None
    assert by_id["track:2"].swing_ratio > 1.7              # triplet swing

    sec_json = on.to_json_dict()["per_section"][0]
    assert "timing" in sec_json
    j = {t["track_id"]: t for t in sec_json["timing"]}
    assert isinstance(j["track:1"]["mean_drift_beats"], float)
    assert isinstance(j["track:1"]["onset_count"], int)
    # swing_ratio is JSON null when unmeasurable, a float otherwise.
    assert j["track:2"]["swing_ratio"] is None or isinstance(
        j["track:2"]["swing_ratio"], float
    )


def test_analyze_mix_populates_section_cross_rhythm_when_enabled(tmp_path: Path):
    """With ``analyze_cross_rhythm=True``, a covered section names each part's
    base pulse: a straight-16ths stem reads an on-grid subdivision, a hemiola
    stem reads 3:2 against the meter, and it serializes under
    ``per_section[].cross_rhythm``.

    The capture is 16 beats over 8 s → effective 120 bpm, derived from the
    shared BeatSampleMap (no tempo passed in)."""
    bpm = 120.0
    straight = onsets_at_beats(
        [i * 0.25 for i in range(64)], bpm=bpm, total_beats=16.0,
    )
    hemiola = onsets_at_beats(
        [i * (2.0 / 3.0) for i in range(24)], bpm=bpm, total_beats=16.0,
    )
    master = straight + hemiola
    captures_dir = _write_synthetic_capture(
        tmp_path,
        stems=[("track:1", "Straight", straight), ("track:2", "Hemiola", hemiola)],
        master_audio=master,
        start_at_beat=0.0,
        stop_at_beat=16.0,
    )
    sections = [SectionWindow(name="verse", start_beat=0.0, end_beat=16.0)]

    # Off by default — no cross-rhythm computed.
    off = analyze_mix(captures_dir, sections=sections)
    assert off.per_section[0].cross_rhythm == []

    on = analyze_mix(captures_dir, sections=sections, analyze_cross_rhythm=True)
    sec = on.per_section[0]
    by_id = {c.track_id: c for c in sec.cross_rhythm}
    assert "track:1" in by_id and "track:2" in by_id

    assert by_id["track:1"].pulse_ratio == "4/beat"
    assert by_id["track:1"].verdict == "subdivision"
    assert not by_id["track:1"].against_meter

    assert by_id["track:2"].pulse_ratio == "3:2"
    assert by_id["track:2"].verdict == "cross-rhythm"
    assert by_id["track:2"].against_meter

    sec_json = on.to_json_dict()["per_section"][0]
    assert "cross_rhythm" in sec_json
    j = {c["track_id"]: c for c in sec_json["cross_rhythm"]}
    assert j["track:2"]["pulse_ratio"] == "3:2"
    assert isinstance(j["track:2"]["base_period_beats"], float)
    assert isinstance(j["track:2"]["occupancy"], float)
    assert isinstance(j["track:2"]["against_meter"], bool)


def test_analyze_mix_populates_section_phasing_when_enabled(tmp_path: Path):
    """With ``analyze_cross_rhythm=True``, a section with two parts drifting at
    fractionally different tempi reads a phasing relationship under
    ``per_section[].phasing``; two locked parts read none.

    The capture is 16 beats over 8 s → effective 120 bpm."""
    bpm = 120.0

    def pulse(period):
        beats = [i * period for i in range(64)]
        return onsets_at_beats(
            [b for b in beats if b < 16.0], bpm=bpm, total_beats=16.0,
        )

    drifting = pulse(1.0 / 1.03)   # 3% faster → phases against the locked pulse
    locked = pulse(1.0)
    master = drifting + locked
    captures_dir = _write_synthetic_capture(
        tmp_path,
        stems=[("track:1", "Locked", locked), ("track:2", "Drifting", drifting)],
        master_audio=master,
        start_at_beat=0.0,
        stop_at_beat=16.0,
    )
    sections = [SectionWindow(name="phase", start_beat=0.0, end_beat=16.0)]

    # Off by default.
    off = analyze_mix(captures_dir, sections=sections)
    assert off.per_section[0].phasing == []

    on = analyze_mix(captures_dir, sections=sections, analyze_cross_rhythm=True)
    sec = on.per_section[0]
    assert len(sec.phasing) == 1
    ph = sec.phasing[0]
    assert {ph.track_a, ph.track_b} == {"track:1", "track:2"}
    assert abs(ph.drift_beats_per_cycle) > 0.05
    assert ph.confidence > 0.9

    sec_json = on.to_json_dict()["per_section"][0]
    assert "phasing" in sec_json
    assert isinstance(sec_json["phasing"][0]["drift_beats_per_cycle"], float)

    # Two locked parts → no phasing surfaced.
    locked2 = pulse(1.0)
    master2 = locked + locked2
    captures2 = _write_synthetic_capture(
        tmp_path / "locked",
        stems=[("track:1", "A", locked), ("track:2", "B", locked2)],
        master_audio=master2,
        start_at_beat=0.0,
        stop_at_beat=16.0,
    )
    locked_on = analyze_mix(captures2, sections=sections, analyze_cross_rhythm=True)
    assert locked_on.per_section[0].phasing == []


def test_analyze_mix_populates_section_polymeter_when_enabled(tmp_path: Path):
    """With ``analyze_cross_rhythm=True``, two accented steady streams looping
    different cell lengths (4-beat vs 3-beat) read a polymeter relationship under
    ``per_section[].polymeter`` with the lcm realign; off by default.

    The capture is 24 beats over 12 s → effective 120 bpm."""
    bpm = 120.0

    def accented(cell_beats):
        n = 48  # steady 8ths over 24 beats
        beats = [i * 0.5 for i in range(n)]
        amps = [2.0 if (b % cell_beats) < 1e-6 else 1.0 for b in beats]
        return onsets_at_beats(beats, bpm=bpm, total_beats=24.0, amplitudes=amps)

    cell4 = accented(4.0)
    cell3 = accented(3.0)
    master = cell4 + cell3
    captures_dir = _write_synthetic_capture(
        tmp_path,
        stems=[("track:1", "Cell4", cell4), ("track:2", "Cell3", cell3)],
        master_audio=master,
        start_at_beat=0.0,
        stop_at_beat=24.0,
    )
    sections = [SectionWindow(name="poly", start_beat=0.0, end_beat=24.0)]

    # Off by default.
    off = analyze_mix(captures_dir, sections=sections)
    assert off.per_section[0].polymeter == []

    on = analyze_mix(captures_dir, sections=sections, analyze_cross_rhythm=True)
    sec = on.per_section[0]
    assert len(sec.polymeter) == 1
    pm = sec.polymeter[0]
    assert {pm.track_a, pm.track_b} == {"track:1", "track:2"}
    cells = sorted([pm.cycle_a_beats, pm.cycle_b_beats])
    assert abs(cells[0] - 3.0) < 0.1 and abs(cells[1] - 4.0) < 0.1
    assert abs(pm.realign_beats - 12.0) < 0.1

    sec_json = on.to_json_dict()["per_section"][0]
    assert "polymeter" in sec_json
    assert isinstance(sec_json["polymeter"][0]["realign_beats"], float)


def test_analyze_mix_tempo_map_moves_section_boundary(tmp_path: Path):
    """With a variable tempo, the beat→sample boundary shifts, so a section
    measures different audio than the constant-tempo linear map would.

    Audio: loud first 2/3 (4s) + quiet last 1/3 (2s). Tempo: beats 0..4 @ 60
    bpm, 4..8 @ 120 bpm → beat 4 lands at 2/3 of the samples. So section
    'second' (beats 4..8) with the tempo map measures ONLY the quiet tail;
    without it (linear, beat 4 = halfway) it also catches part of the loud
    region and reads louder.
    """
    loud = calibrated_pink_noise(-14.0, 4.0)
    quiet = calibrated_pink_noise(-30.0, 2.0)
    audio = np.concatenate([loud, quiet], axis=0)
    captures_dir = _write_synthetic_capture(
        tmp_path,
        stems=[("track:1", "Synth", audio)],
        master_audio=audio,
        start_at_beat=0.0,
        stop_at_beat=8.0,
    )
    sections = [SectionWindow(name="second", start_beat=4.0, end_beat=8.0)]
    tempo = [TempoSegment(start_beat=0.0, bpm=60.0),
             TempoSegment(start_beat=4.0, bpm=120.0)]

    with_tempo = analyze_mix(captures_dir, sections=sections, tempo_map=tempo)
    without = analyze_mix(captures_dir, sections=sections)

    lufs_with = with_tempo.per_section[0].master.loudness.lufs_i
    lufs_without = without.per_section[0].master.loudness.lufs_i
    # Tempo-aware sees only the quiet tail → measurably quieter than the
    # linear interpretation that catches part of the loud region.
    assert lufs_with < lufs_without - 3.0


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


def test_analyze_mix_skips_section_with_tiny_overlap(tmp_path: Path):
    """A section overlapping the capture by less than the 400 ms BS.1770
    block minimum is recorded as a skip — measuring it would raise and
    discard the whole report."""
    duration_s = 2.0
    captures_dir = _write_synthetic_capture(
        tmp_path,
        stems=[("track:1", "01 Drums", calibrated_pink_noise(-26.0, duration_s))],
        master_audio=calibrated_pink_noise(-20.0, duration_s),
        start_at_beat=0.0,
        stop_at_beat=8.0,
    )
    # 8 beats over 2 s → 4 beats/s. A 0.1-beat window ≈ 25 ms, well under
    # the 400 ms floor, but it does overlap the capture (covered=True).
    sections = [
        SectionWindow(name="full", start_beat=0.0, end_beat=8.0),
        SectionWindow(name="sliver", start_beat=4.0, end_beat=4.1),
    ]
    report = analyze_mix(captures_dir, sections=sections)
    assert [s.section_name for s in report.per_section] == ["full"]
    assert any(
        s.get("kind") == "section_windowed"
        and "sliver" in s.get("reason", "")
        and "ms" in s.get("reason", "")
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
