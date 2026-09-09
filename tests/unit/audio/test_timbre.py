"""Standing timbre descriptors (AUD-8T3K) — the corpus IS the spec.

There is no labelled timbre ground truth, so correctness is defined by
constructed fixtures: a pure tone reads maximally tonal (flatness ~0); white
noise reads noisy (flatness high); a brighter signal has a higher centroid and
rolloff; silence / too-short returns the honest NaN sentinel; and the
silence-gated median reflects timbre *while sounding*, not diluted by silence.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from hallucinote.audio.timbre import measure_timbre, spectral_centroid_hz
from tests.unit.audio.fixtures import SAMPLE_RATE, concat, silence, sine

SR = SAMPLE_RATE
DUR = 1.0  # seconds — plenty of STFT frames at 2048/512


def _white(duration_s: float, *, amplitude: float = 0.2, seed: int = 0) -> np.ndarray:
    """Stereo white noise — flat per Hz, the noisiness ceiling fixture."""
    n = int(round(duration_s * SR))
    rng = np.random.default_rng(seed)
    mono = (amplitude * rng.standard_normal(n)).astype(np.float32)
    return np.stack([mono, mono], axis=1)


def test_pure_tone_reads_tonal():
    m = measure_timbre(sine(1000.0, DUR), SR)
    assert m.spectral_centroid_hz == pytest.approx(1000.0, abs=50.0)
    assert m.spectral_flatness < 0.05          # concentrated energy → tonal
    assert m.spectral_rolloff_hz == pytest.approx(1000.0, abs=100.0)


def test_white_noise_reads_noisy():
    tone = measure_timbre(sine(1000.0, DUR), SR)
    noise = measure_timbre(_white(DUR), SR)
    assert noise.spectral_flatness > 0.2       # broadband → noisy
    assert noise.spectral_flatness > tone.spectral_flatness * 5


def test_brighter_signal_has_higher_centroid_and_rolloff():
    dark = measure_timbre(sine(200.0, DUR), SR)
    bright = measure_timbre(sine(5000.0, DUR), SR)
    assert bright.spectral_centroid_hz > dark.spectral_centroid_hz
    assert bright.spectral_rolloff_hz > dark.spectral_rolloff_hz


def test_silence_returns_nan_sentinel():
    m = measure_timbre(silence(DUR), SR)
    assert math.isnan(m.spectral_centroid_hz)
    assert math.isnan(m.spectral_flatness)
    assert math.isnan(m.spectral_rolloff_hz)


def test_too_short_to_stft_returns_nan_sentinel():
    # Fewer samples than one n_fft window → no measurable frame.
    m = measure_timbre(sine(1000.0, 0.01), SR)  # ~480 samples < 2048
    assert math.isnan(m.spectral_centroid_hz)


def test_stereo_matches_mono_sum():
    mono = sine(1000.0, DUR)[:, 0]              # one channel as a 1-D buffer
    stereo = sine(1000.0, DUR)
    a = measure_timbre(mono, SR)
    b = measure_timbre(stereo, SR)
    assert a.spectral_centroid_hz == pytest.approx(b.spectral_centroid_hz, abs=1.0)
    assert a.spectral_flatness == pytest.approx(b.spectral_flatness, abs=1e-6)


def test_scale_invariant():
    sig = _white(DUR)
    quiet = measure_timbre(sig, SR)
    loud = measure_timbre(sig * 10.0, SR)
    assert loud.spectral_centroid_hz == pytest.approx(quiet.spectral_centroid_hz, rel=1e-6)
    assert loud.spectral_flatness == pytest.approx(quiet.spectral_flatness, rel=1e-6)
    assert loud.spectral_rolloff_hz == pytest.approx(quiet.spectral_rolloff_hz, rel=1e-6)


def test_silence_gate_excludes_quiet_frames_from_median():
    # Decision #2: the median is taken over silence-gated frames, so a stem that
    # is silent half the time still reports the timbre of the half that sounds —
    # the silence does not drag the centroid toward 0 nor NaN the result.
    tone = sine(1000.0, 0.5)
    half_silent = concat(tone, silence(0.5), tone)
    m = measure_timbre(half_silent, SR)
    assert m.spectral_centroid_hz == pytest.approx(1000.0, abs=50.0)
    assert not math.isnan(m.spectral_flatness)


def test_whole_window_spectral_centroid_hz():
    # The lifted automation-side helper (whole-window, single FFT).
    n = SR
    t = np.arange(n) / SR
    assert spectral_centroid_hz(np.sin(2 * np.pi * 1000.0 * t), SR) == pytest.approx(
        1000.0, abs=30.0
    )
    assert spectral_centroid_hz(np.zeros(n), SR) == 0.0      # silent → 0
    assert spectral_centroid_hz(np.array([]), SR) == 0.0     # empty → 0


# --------------------------------------------------------------------------- #
# Sharpness — the shrillness axis
# --------------------------------------------------------------------------- #

def test_sharpness_orders_dark_to_piercing():
    dark = measure_timbre(sine(200.0, DUR), SR)
    mid = measure_timbre(sine(1000.0, DUR), SR)
    piercing = measure_timbre(sine(5000.0, DUR), SR)
    assert dark.sharpness_acum < mid.sharpness_acum < piercing.sharpness_acum
    # The weighting above 14 Bark is what separates "bright" from "shrill":
    # 1 kHz -> 5 kHz must move sharpness by more than 200 Hz -> 1 kHz did.
    assert (piercing.sharpness_acum - mid.sharpness_acum) > (
        mid.sharpness_acum - dark.sharpness_acum)


def test_sharpness_reads_a_high_boost_as_shriller_at_equal_centroid_family():
    # A 3 kHz + 6 kHz pair vs a 300 Hz + 6 kHz pair: the second has MORE
    # of its loudness in the low bands, so it reads less sharp even though
    # both carry the same top partial.
    a = measure_timbre(sine(3000.0, DUR) + sine(6000.0, DUR), SR)
    b = measure_timbre(sine(300.0, DUR) + sine(6000.0, DUR), SR)
    assert a.sharpness_acum > b.sharpness_acum


def test_sharpness_is_scale_invariant_and_nan_on_silence():
    sig = _white(DUR)
    assert measure_timbre(sig * 8.0, SR).sharpness_acum == pytest.approx(
        measure_timbre(sig, SR).sharpness_acum, rel=1e-6)
    assert math.isnan(measure_timbre(silence(DUR), SR).sharpness_acum)


def test_white_noise_is_sharper_than_a_low_tone():
    assert measure_timbre(_white(DUR), SR).sharpness_acum > \
        measure_timbre(sine(200.0, DUR), SR).sharpness_acum
