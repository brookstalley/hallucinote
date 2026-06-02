"""Capture trim-to-common-length alignment (AUD-1C7K).

The capture pipeline's per-surface sfrecord~ instances finalize at staggered
times, so the raw WAVs differ in length — but their content starts are
sample-aligned (a known-offset calibration capture recovered a 2-beat impulse
spacing to the exact sample). So the fix is to trim every surface to the common
(shortest) length; these pin that contract, including the capstone that the
reverb deconvolution — which hard-fails on mismatched lengths — succeeds once
the surfaces are trimmed.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from hallucinote.audio.alignment import trim_to_common_length
from hallucinote.audio.io import CaptureSet, Surface
from hallucinote.audio.reverb import (
    REVERB_TOLERANCE_S,
    deconvolve_ir,
    verify_reverb_send,
)
from tests.unit.audio import fixtures

SR = fixtures.SAMPLE_RATE


def _surface(track_id: str, kind: str, audio: np.ndarray) -> Surface:
    return Surface(
        track_id=track_id,
        surface_kind=kind,  # type: ignore[arg-type]
        surface_name=track_id,
        audio=audio,
        sample_rate=SR,
    )


def _capture(master: Surface, stems=(), returns=()) -> CaptureSet:
    return CaptureSet(
        song_slug="trim-test",
        captured_at="20260602T000000Z",
        analyzer_signature="hallucinote-analyzer-v1",
        captures_dir=Path("/tmp/x"),
        manifest_path=Path("/tmp/x/manifest.json"),
        sample_rate=SR,
        start_at_beat=0.0,
        stop_at_beat=64.0,
        master=master,
        stems=list(stems),
        returns=list(returns),
    )


def test_trim_equalizes_lengths_and_preserves_heads():
    """Surfaces of different lengths are all trimmed to the shortest; the
    retained head of each is byte-identical to the original (only tails drop)."""
    base = fixtures.pink_noise(1.0)  # 48000 samples
    master = base[:47000]            # the shortest → defines the common length
    s1 = base[:48000]
    r1 = base[:47500]
    capture = _capture(
        master=_surface("master", "master", master),
        stems=[_surface("track:1", "track", s1)],
        returns=[_surface("return:1", "return", r1)],
    )

    aligned, report = trim_to_common_length(capture)

    lengths = {
        aligned.master.audio.shape[0],
        *(s.audio.shape[0] for s in aligned.stems),
        *(r.audio.shape[0] for r in aligned.returns),
    }
    assert lengths == {47000}
    assert report.common_length == 47000
    assert report.max_drift_samples == 1000  # 48000 - 47000
    # Heads preserved exactly (trim drops only the tail).
    np.testing.assert_array_equal(aligned.stems[0].audio, s1[:47000])
    np.testing.assert_array_equal(aligned.returns[0].audio, r1[:47000])
    # Report accounts every surface with its drop.
    by_id = {s.track_id: s for s in report.surfaces}
    assert by_id["track:1"].trimmed_samples == 1000
    assert by_id["return:1"].trimmed_samples == 500
    assert by_id["master"].trimmed_samples == 0


def test_trim_is_noop_when_already_equal_length():
    """Equal-length surfaces (synthetic fixtures) pass through untouched —
    drift 0, same arrays, so existing analysis tests aren't perturbed."""
    s1 = fixtures.pink_noise(0.5)
    s2 = fixtures.sine(220.0, 0.5)
    master = (s1 + s2).astype(np.float32)
    capture = _capture(
        master=_surface("master", "master", master),
        stems=[_surface("track:1", "track", s1), _surface("track:2", "track", s2)],
    )

    aligned, report = trim_to_common_length(capture)

    assert report.max_drift_samples == 0
    assert "already equal length" in report.human_summary
    np.testing.assert_array_equal(aligned.stems[0].audio, s1)
    np.testing.assert_array_equal(aligned.stems[1].audio, s2)


def test_human_summary_reports_drift_for_unequal_capture():
    capture = _capture(
        master=_surface("master", "master", fixtures.silence(1.0)),
        stems=[_surface("track:1", "track", fixtures.silence(1.1))],  # 100 ms longer
    )
    _, report = trim_to_common_length(capture)
    assert report.max_drift_samples == int(round(0.1 * SR))
    assert "100 ms" in report.human_summary


def test_reverb_verification_survives_capture_length_drift():
    """The AUD-1C7K capstone. Per-surface stop drift gives the dry stem and its
    wet return DIFFERENT lengths, so deconvolve_ir hard-fails. Because the
    starts are sample-aligned (only the tails differ), trimming to the common
    length restores the equal-length, phase-aligned pair and the RT60 comes
    back within tolerance."""
    ir = fixtures.synthetic_ir(0.6, duration_s=1.0)
    # Unit-impulse dry so wet is the full IR (no truncated reverb tail) — the
    # clean dry/wet pair the deconvolution math assumes; the variable under test
    # is the LENGTH drift, not the deconvolution's tolerance to truncated input.
    dry = fixtures.silence(2.0)
    dry[0, 0] = 1.0
    dry[0, 1] = 1.0
    wet_full = fixtures.convolve(dry, ir)  # = the IR, with its 1.0 s tail intact

    # Stop drift: the wet return's sfrecord~ finalized later → its WAV is longer
    # by the per-surface stop offset, but it STARTS at the same sample as the
    # dry (heads aligned). Model that with extra trailing silence on the wet.
    wet = np.concatenate([wet_full, fixtures.silence(0.05)], axis=0)  # 50 ms longer tail
    assert dry.shape[0] != wet.shape[0]

    # Raw, the deconvolution refuses the mismatched lengths — the AUD-1C7K bug.
    with pytest.raises(ValueError, match="same length"):
        deconvolve_ir(dry, wet, sr=SR)

    capture = _capture(
        master=_surface("master", "master", dry),  # any equal-or-shorter ref
        stems=[_surface("track:1", "track", dry)],
        returns=[_surface("return:1", "return", wet)],
    )
    aligned, _ = trim_to_common_length(capture)
    dry_a = aligned.stems[0].audio
    wet_a = aligned.returns[0].audio
    assert dry_a.shape == wet_a.shape

    result = verify_reverb_send(
        dry_a, wet_a,
        sample_rate=SR, declared_rt60_s=0.6,
        dry_track_id="track:1", wet_return_track_id="return:1",
    )
    assert np.isfinite(result.measured_rt60_s)
    assert abs(result.measured_rt60_s - 0.6) <= REVERB_TOLERANCE_S
    assert result.within_tolerance
