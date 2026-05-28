"""Loudness measurement tests.

Pins success criterion #3 from the audio-analysis MVP build plan:
per-stem LUFS-I matches a calibrated reference within ±0.2 LU.

Also covers true-peak detection on a known inter-sample peak fixture,
LUFS-S median, LUFS-M peak, and the short-clip teaching-error guard.
"""
from __future__ import annotations

import numpy as np
import pytest

from hallucinote.audio.loudness import (
    LOUDNESS_TOLERANCE_LU,
    measure_loudness,
)

from .fixtures import (
    SAMPLE_RATE,
    calibrated_pink_noise,
    sine,
    silence,
)


def test_lufs_i_within_tolerance_on_calibrated_pink_noise():
    """Success criterion #3 (build plan Chunk 3-A)."""
    target = -23.0
    audio = calibrated_pink_noise(target, duration_s=4.0)
    metrics = measure_loudness(audio, sr=SAMPLE_RATE)
    assert abs(metrics.lufs_i - target) <= LOUDNESS_TOLERANCE_LU, (
        f"LUFS-I drifted: target={target}, measured={metrics.lufs_i}, "
        f"tolerance={LOUDNESS_TOLERANCE_LU}"
    )


def test_lufs_s_median_is_close_to_lufs_i_on_stationary_signal():
    """Pink noise is stationary — short-term median should agree with
    integrated within roughly a LU."""
    audio = calibrated_pink_noise(-20.0, duration_s=8.0)
    metrics = measure_loudness(audio, sr=SAMPLE_RATE)
    assert abs(metrics.lufs_s_median - metrics.lufs_i) < 1.0


def test_lufs_m_peak_at_or_above_lufs_i():
    """Momentary (400ms) blocks include peaks that the gated integrated
    measurement smooths over — peak should never be lower than integrated."""
    audio = calibrated_pink_noise(-23.0, duration_s=4.0)
    metrics = measure_loudness(audio, sr=SAMPLE_RATE)
    assert metrics.lufs_m_peak >= metrics.lufs_i - 0.5


def test_true_peak_detects_full_scale_sine():
    """A pure 1 kHz sine at amplitude 1.0 should hit 0 dBTP (or just over).
    Asserts the true-peak measurement is on the right scale and direction."""
    audio = sine(1000.0, duration_s=1.0, amplitude=1.0)
    metrics = measure_loudness(audio, sr=SAMPLE_RATE)
    # 0 dBTP ± half a dB is plenty of tolerance for 4× oversample on
    # a 1 kHz sine that lands well within nyquist headroom.
    assert -0.5 < metrics.true_peak_dbtp <= 1.0


def test_true_peak_negative_on_quiet_signal():
    """-23 LUFS pink noise has well below 0 dBTP sample-peak; true-peak
    should reflect that with a comfortably negative dBTP."""
    audio = calibrated_pink_noise(-23.0, duration_s=4.0)
    metrics = measure_loudness(audio, sr=SAMPLE_RATE)
    assert metrics.true_peak_dbtp < -3.0


def test_short_clip_raises_teaching_error():
    """``pyloudnorm`` requires ≥0.4s of audio for default block size;
    shorter clips silently return NaN. We pre-check and raise a teaching
    error so the analysis pipeline doesn't emit a NaN-filled MixReport."""
    audio = sine(440.0, duration_s=0.1)  # 100 ms — below 400 ms block
    with pytest.raises(ValueError, match="too short for LUFS"):
        measure_loudness(audio, sr=SAMPLE_RATE)


def test_lufs_s_median_falls_back_to_momentary_on_sub_three_second_clip():
    """Clips between 0.4 s and 3 s can't fill a 3 s short-term block.
    Rather than NaN, the wrapper falls back to 400 ms momentary blocks
    so the MixReport carries a finite degraded value (relevant for
    section-windowed analysis, P1 backlog)."""
    audio = calibrated_pink_noise(-23.0, duration_s=1.5)
    metrics = measure_loudness(audio, sr=SAMPLE_RATE)
    assert np.isfinite(metrics.lufs_s_median), (
        f"fallback path returned non-finite value {metrics.lufs_s_median}"
    )
    # Stationary signal: momentary-block median should agree with
    # integrated within a couple LU (looser than the 8 s case above
    # because there are fewer momentary blocks to median over).
    assert abs(metrics.lufs_s_median - metrics.lufs_i) < 2.0


def test_silent_clip_lufs_i_is_finite_or_explicitly_minus_infinity():
    """BS.1770's gating returns -inf on pure silence (all blocks below
    -70 LUFS gate). Our wrapper should surface that as the canonical
    'silent' marker rather than NaN, so downstream code can branch on it."""
    audio = silence(2.0)
    metrics = measure_loudness(audio, sr=SAMPLE_RATE)
    # We accept -inf as the silence indicator. Anything else (NaN, 0)
    # would be a bug in the wrapper.
    assert metrics.lufs_i == float("-inf") or metrics.lufs_i < -120.0
