"""PDC alignment regression — synthetic-stems version of Chunk 1's load-bearing check.

Why this test exists
====================

The audio-analysis MVP depends on each track's `sfrecord~`-captured WAV being
sample-aligned with the master bus's `sfrecord~`-captured WAV. Plugin Delay
Compensation in Live is supposed to guarantee that: the master sees every
track's audio delayed by exactly the right amount to land in phase. If PDC
fails to align dry+wet pairs the reverb-verification deconvolution (Chunk 3)
collapses to noise.

We cannot run `sfrecord~` from CI — that needs Live + the `.amxd`. What we
*can* do is fix the verification routine in code: the math the in-Live test
will run on captured WAVs. If this synthetic round-trip passes, the failure
mode for the in-Live test reduces to "PDC didn't align," not "our alignment
metric was wrong."

The contract this test pins
===========================

``cross_correlation_peak_lag(stem, master)`` returns the sample lag at which
``master`` best matches ``stem``. The in-Live verification (build-plan.md
Chunk 1, "Done when") requires that lag to be within ± 64 samples of zero at
48 kHz — i.e. ~1.3 ms — *after* the stem has been zero-padded to compensate
for Live's reported PDC value. This file:

1. Defines the alignment function (lives here for now; promotes to
   ``src/hallucinote/audio/alignment.py`` in Chunk 3 when the analysis
   package lands).
2. Proves it returns exactly the lag we injected on synthetic stems.
3. Documents the tolerance the in-Live test will assert against.
"""
from __future__ import annotations

import numpy as np
import pytest
from scipy.signal import correlate, correlation_lags

from tests.unit.audio import fixtures

# In-Live tolerance, in samples at 48 kHz. The build plan's Chunk 1 success
# criterion: peak at zero lag ± 64 samples. About 1.3 ms — within one audio
# buffer at typical session sizes (Live defaults to 128 / 256 / 512 buffers).
PDC_TOLERANCE_SAMPLES = 64


def cross_correlation_peak_lag(stem: np.ndarray, master: np.ndarray) -> int:
    """Sample lag at which ``master`` is best explained by ``stem``.

    Positive lag = master arrives later than stem (the expected PDC case).
    Operates on the mono sum so stereo phase tricks don't bias the peak.
    Both inputs must be stereo float arrays of equal length.
    """
    if stem.shape != master.shape:
        raise ValueError(
            f"stem {stem.shape} and master {master.shape} must match"
        )
    stem_mono = stem.mean(axis=1)
    master_mono = master.mean(axis=1)
    # SciPy's FFT-based correlate. mode='full' returns 2N-1 lags; we read
    # the peak and convert its index to a signed lag in samples.
    xcorr = correlate(master_mono, stem_mono, mode="full", method="fft")
    lags = correlation_lags(master_mono.size, stem_mono.size, mode="full")
    return int(lags[int(np.argmax(np.abs(xcorr)))])


def test_zero_delay_returns_zero_lag():
    """No PDC at all → lag is exactly zero. Pins the trivial case."""
    kick = fixtures.kick_onset()
    # Embed in a longer buffer so xcorr has room to find the peak unambiguously.
    pad = fixtures.silence(0.5)
    stem = np.concatenate([pad, kick, pad], axis=0)
    lag = cross_correlation_peak_lag(stem, stem)
    assert lag == 0


def test_known_delay_recovered_exactly():
    """Inject a 37-sample delay; xcorr recovers exactly 37."""
    kick = fixtures.kick_onset()
    pad = fixtures.silence(0.5)
    stem = np.concatenate([pad, kick, pad], axis=0)
    master = fixtures.delayed_copy(stem, delay_samples=37)
    assert cross_correlation_peak_lag(stem, master) == 37


def test_negative_delay_recovered_exactly():
    """If master leads stem (shouldn't happen with real PDC, but the math
    must still be unambiguous), lag is negative.
    """
    kick = fixtures.kick_onset()
    pad = fixtures.silence(0.5)
    stem = np.concatenate([pad, kick, pad], axis=0)
    master = fixtures.delayed_copy(stem, delay_samples=-23)
    assert cross_correlation_peak_lag(stem, master) == -23


def test_pdc_compensated_signal_within_tolerance():
    """The shape the in-Live test will assert.

    Scenario: master is delayed N samples behind the stem (PDC), the
    capture pipeline pre-shifts the stem by Live's reported PDC value,
    and the residual lag must fall within ± 64 samples (1.3 ms at 48 k).
    Here we model that with a small residual jitter (≤ 16 samples) on
    top of perfect compensation, since real PDC can be sample-accurate
    but buffer-granular under some conditions.
    """
    rng = np.random.default_rng(seed=20260523)
    kick = fixtures.kick_onset()
    pad = fixtures.silence(0.5)
    stem = np.concatenate([pad, kick, pad], axis=0)
    for _ in range(8):
        live_pdc = int(rng.integers(0, 2048))  # arbitrary PDC value
        residual = int(rng.integers(-16, 17))  # buffer-granular residual
        master = fixtures.delayed_copy(stem, delay_samples=live_pdc + residual)
        # Pretend the pipeline pre-shifts the stem by Live's reported PDC.
        compensated = fixtures.delayed_copy(stem, delay_samples=live_pdc)
        lag = cross_correlation_peak_lag(compensated, master)
        assert abs(lag) <= PDC_TOLERANCE_SAMPLES, (
            f"residual lag {lag} exceeds PDC_TOLERANCE_SAMPLES "
            f"({PDC_TOLERANCE_SAMPLES}); injected residual was {residual}"
        )


def test_pink_noise_alignment_is_robust():
    """Cross-correlation should not need a transient to align — pure noise
    works too, since the peak comes from the noise's own structure.
    """
    noise = fixtures.pink_noise(2.0)
    master = fixtures.delayed_copy(noise, delay_samples=512)
    assert cross_correlation_peak_lag(noise, master) == 512


def test_unequal_lengths_rejected():
    """The contract requires equal-length buffers; mismatched inputs are
    a caller bug, not a silent edge case. ``pytest.raises`` pins the exact
    exception type — a broader except would silently accept any subclass.
    """
    short = fixtures.sine(440.0, 0.1)
    long_ = fixtures.sine(440.0, 0.2)
    with pytest.raises(ValueError):
        cross_correlation_peak_lag(short, long_)
