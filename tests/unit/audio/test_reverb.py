"""Reverb send verification tests.

Pins success criterion #5 from the audio-analysis MVP build plan:
on a synthetic dry impulse + known-RT60 IR, the Wiener-deconvolved IR
measures RT60 within ±0.15 s of the declared value.

The MVP path is the *clean* one — the analyzer's wet capture lives at
the return-track instance, not blended back into the master, so the
dry/wet pair deconvolves to a clean IR. Per spike §3.
"""
from __future__ import annotations

import numpy as np
import pytest

from hallucinote.audio.reverb import (
    REVERB_TOLERANCE_S,
    deconvolve_ir,
    verify_reverb_send,
)

from .fixtures import (
    SAMPLE_RATE,
    convolve,
    pink_noise,
    silence,
    synthetic_ir,
)


def _impulse(duration_s: float = 2.0) -> np.ndarray:
    """A clean stereo impulse — single sample at t=0, zeros elsewhere."""
    audio = silence(duration_s)
    audio[0, 0] = 1.0
    audio[0, 1] = 1.0
    return audio


def test_deconvolve_recovers_known_ir_from_impulse_dry():
    """When dry is a delta, wet IS the IR — deconvolution should
    recover the IR with very small error."""
    declared = 0.8
    ir = synthetic_ir(declared, duration_s=2.0)
    dry = _impulse(duration_s=2.0)
    wet = convolve(dry, ir)

    recovered = deconvolve_ir(dry, wet, sr=SAMPLE_RATE)
    # The deconvolution introduces some numerical noise; allow generous
    # tolerance on per-sample IR shape but check the energy decay is right.
    ir_mono = 0.5 * (ir[:, 0] + ir[:, 1])
    rec_mono = 0.5 * (recovered[:, 0] + recovered[:, 1])
    # Both should have energy front-loaded; check cumulative energy crosses
    # 90% at roughly the same point.
    def _e90(x):
        cumul = np.cumsum(x**2)
        return int(np.searchsorted(cumul, 0.9 * cumul[-1]))
    assert abs(_e90(rec_mono) - _e90(ir_mono)) < int(0.05 * SAMPLE_RATE)


def test_verify_reverb_send_measures_known_rt60_within_tolerance():
    """Success criterion #5 (build plan Chunk 3-B)."""
    declared = 1.2
    ir = synthetic_ir(declared, duration_s=3.0)
    dry = _impulse(duration_s=3.0)
    wet = convolve(dry, ir)

    result = verify_reverb_send(dry, wet, sample_rate=SAMPLE_RATE,
                                declared_rt60_s=declared,
                                dry_track_id="track:snare",
                                wet_return_track_id="return:1")
    assert abs(result.measured_rt60_s - declared) <= REVERB_TOLERANCE_S, (
        f"RT60 drift: declared={declared}, measured={result.measured_rt60_s}, "
        f"tolerance={REVERB_TOLERANCE_S}"
    )
    assert result.within_tolerance is True
    assert result.dry_track_id == "track:snare"
    assert result.wet_return_track_id == "return:1"


def test_verify_reverb_send_flags_out_of_tolerance():
    """Send a wet signal made with a 2.0 s IR but declare it was 0.5 s —
    measured value should fall outside tolerance and within_tolerance
    should be False."""
    actual = 2.0
    declared = 0.5
    ir = synthetic_ir(actual, duration_s=4.0)
    dry = _impulse(duration_s=4.0)
    wet = convolve(dry, ir)

    result = verify_reverb_send(dry, wet, sample_rate=SAMPLE_RATE,
                                declared_rt60_s=declared,
                                dry_track_id="track:snare",
                                wet_return_track_id="return:1")
    assert result.within_tolerance is False
    assert result.measured_rt60_s > declared + REVERB_TOLERANCE_S


def test_wiener_regularization_keeps_deconvolution_stable_on_noisy_dry():
    """A noisy dry signal (pink noise) has near-zero spectral bins; the
    Wiener regularization epsilon prevents the deconvolution from blowing
    up. We assert STABILITY (finite output, no NaN/Inf) — not RT60
    accuracy, which is the documented honest gap per spike §7. Noisy /
    dense source material is the post-MVP P2 backlog territory for
    section-scoped masking + improved deconvolution."""
    declared = 1.0
    ir = synthetic_ir(declared, duration_s=3.0)
    dry = pink_noise(3.0, amplitude=0.5)
    wet = convolve(dry, ir)

    result = verify_reverb_send(dry, wet, sample_rate=SAMPLE_RATE,
                                declared_rt60_s=declared,
                                dry_track_id="track:vox",
                                wet_return_track_id="return:1")
    # Stability checks only — measured RT60 may be wildly off but it must
    # be a finite real number, not a deconvolution explosion.
    assert np.isfinite(result.measured_rt60_s)
    assert result.measured_rt60_s >= 0.0
