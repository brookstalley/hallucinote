"""Low-frequency precision is bounded, and the operation says so.

A 55 Hz reference at 2048/512 cannot be carved a semitone wide; the report
says what width the window achieves, and the long-window path narrows it.
"""
from __future__ import annotations

import librosa
import numpy as np
import pytest

from hallucinote.audio.bark import bark_band_map
from hallucinote.spectral.ops import apply, build_mask
from hallucinote.spectral.resolution import (
    MAX_LOW_N_FFT,
    PrecisionClaim,
    bin_hz_over,
    choose_resolution,
    claim_precision,
    split_bands,
)
from hallucinote.spectral.types import MaskParams, ResolutionReport, SpectralField
from tests.unit.audio.fixtures import SAMPLE_RATE, sine

SR = SAMPLE_RATE
BASE = ResolutionReport(n_fft=2048, hop=512, sample_rate=SR)


def test_a_bass_reference_below_the_knee_earns_a_longer_window():
    report = choose_resolution(55.0, 44100)
    assert report.n_fft == 2048 and report.hop == 512
    assert report.low_knee_hz == 200.0
    assert report.low_n_fft == 16384
    assert report.achieved_cents_at_hz(55.0) <= 100.0
    # Above the knee the base window is untouched.
    base_44k = ResolutionReport(n_fft=2048, hop=512, sample_rate=44100)
    assert report.achieved_cents_at_hz(1000.0) == base_44k.achieved_cents_at_hz(1000.0)


def test_a_reference_above_the_knee_keeps_the_base_window():
    report = choose_resolution(440.0, SR)
    assert report.low_n_fft is None and report.low_knee_hz is None


def test_a_request_the_base_window_already_meets_adds_no_window():
    assert choose_resolution(150.0, 44100, target_cents=300.0).low_n_fft is None
    assert choose_resolution(150.0, 44100, target_cents=100.0).low_n_fft is not None


def test_the_long_window_is_capped_and_the_claim_stays_honest():
    report = choose_resolution(20.0, SR, target_cents=10.0)
    assert report.low_n_fft == MAX_LOW_N_FFT
    claim = claim_precision(20.0, 10.0, report)
    assert not claim.met
    assert claim.achieved_cents == pytest.approx(report.achieved_cents_at_hz(20.0))
    assert "20.0 Hz" in claim.describe() and "longer window" in claim.describe()


def test_choose_resolution_refuses_nonsense():
    with pytest.raises(ValueError, match="lowest_hz"):
        choose_resolution(0.0, SR)
    with pytest.raises(ValueError, match="knee_hz"):
        choose_resolution(55.0, SR, knee_hz=-1.0)
    with pytest.raises(ValueError, match="target_cents"):
        choose_resolution(55.0, SR, target_cents=0.0)


def test_a_55_hz_reference_at_2048_reports_its_achieved_width():
    short = claim_precision(55.0, 100.0, BASE)
    assert not short.met
    assert short.achieved_cents > 500.0
    assert "100 cents requested at 55.0 Hz" in short.describe()

    long = claim_precision(55.0, 100.0, choose_resolution(55.0, SR))
    assert long.met
    assert long.achieved_cents == 100.0
    assert "resolved as requested" in long.describe()


def test_the_claim_is_bounded_by_every_window_on_the_path():
    fine = choose_resolution(55.0, SR)
    coarse_field_then_fine_apply = claim_precision(55.0, 100.0, BASE, fine)
    assert not coarse_field_then_fine_apply.met
    assert coarse_field_then_fine_apply.achieved_cents == pytest.approx(BASE.achieved_cents_at_hz(55.0))


def test_a_claim_cannot_be_finer_than_its_request():
    with pytest.raises(ValueError, match="cannot be finer"):
        PrecisionClaim(lowest_hz=55.0, requested_cents=100.0, achieved_cents=50.0)


def test_bin_hz_over_switches_windows_at_the_knee():
    report = ResolutionReport(2048, 512, SR, low_knee_hz=200.0, low_n_fft=16384)
    widths = bin_hz_over(report, np.array([55.0, 199.9, 200.0, 5000.0]))
    assert widths[0] == widths[1] == pytest.approx(SR / 16384)
    assert widths[2] == widths[3] == pytest.approx(SR / 2048)


def test_split_bands_is_an_exact_complement_with_the_bass_in_the_low_band():
    x = (sine(55.0, 1.0, sr=SR) + sine(2000.0, 1.0, sr=SR))[:, 0].astype(np.float64)
    low, high = split_bands(x, SR, 200.0)
    assert np.allclose(low + high, x, atol=1e-9)

    def band_db(y: np.ndarray, hz: float) -> float:
        spec = np.abs(np.fft.rfft(y * np.hanning(y.shape[0]))) ** 2
        f = np.fft.rfftfreq(y.shape[0], 1.0 / SR)
        return 10.0 * np.log10(spec[(f > hz - 20) & (f < hz + 20)].sum() + 1e-30)

    assert band_db(low, 2000.0) < band_db(x, 2000.0) - 40.0
    assert band_db(high, 55.0) < band_db(x, 55.0) - 40.0
    with pytest.raises(ValueError, match="Nyquist"):
        split_bands(x, SR, SR)


def _bass_field(n_samples: int, n_fft: int, resolution: ResolutionReport) -> SpectralField:
    freqs = librosa.fft_frequencies(sr=SR, n_fft=n_fft)
    times = librosa.frames_to_time(np.arange(1 + n_samples // 512), sr=SR, hop_length=512)
    magnitude = np.zeros((freqs.shape[0], times.shape[0]))
    magnitude[int(np.argmin(np.abs(freqs - 55.0)))] = 1.0
    return SpectralField(freqs, times, magnitude, "measured", resolution, "fp")


def _band_db(mono: np.ndarray, hz: float, half: float = 4.0) -> float:
    x = np.asarray(mono, dtype=np.float64)
    spec = np.abs(np.fft.rfft(x * np.hanning(x.shape[0]))) ** 2
    f = np.fft.rfftfreq(x.shape[0], 1.0 / SR)
    return 10.0 * np.log10(spec[(f >= hz - half) & (f <= hz + half)].sum() + 1e-30)


def test_the_long_window_path_narrows_a_bass_carve():
    """55 Hz and the fourth above it at 73.4 Hz are neighbours in a 2048-point bin; a 16384-point one separates them."""
    fine = ResolutionReport(2048, 512, SR, low_knee_hz=200.0, low_n_fft=16384)
    target = (sine(55.0, 4.0, sr=SR) + sine(73.4, 4.0, sr=SR) + sine(2000.0, 4.0, sr=SR))[:, 0]
    target = target.astype(np.float32)
    field = _bass_field(target.shape[0], 16384, fine)
    params = MaskParams(polarity="carve", harmonic_depth=1, notch_width_cents=150.0, depth_db=20.0)
    bark = bark_band_map(SR, 2048)

    short = build_mask(field, params, bark=bark, resolution=BASE)
    assert short.precision is not None and not short.precision.met
    assert short.precision.achieved_cents == pytest.approx(BASE.achieved_cents_at_hz(55.0), abs=15.0)
    out_short = apply(target, SR, short, n_fft=2048, hop=512)
    # The short window's 23 Hz bins cannot keep the fourth out of the notch.
    assert _band_db(target, 73.4) - _band_db(out_short, 73.4) > 3.0

    long = build_mask(field, params, bark=bark)
    assert long.resolution.low_n_fft == 16384
    assert long.precision is not None and long.precision.met
    out_long = apply(target, SR, long, n_fft=2048, hop=512)
    assert _band_db(target, 55.0) - _band_db(out_long, 55.0) == pytest.approx(20.0, abs=1.5)
    assert abs(_band_db(target, 73.4) - _band_db(out_long, 73.4)) < 0.5
    assert abs(_band_db(target, 2000.0) - _band_db(out_long, 2000.0)) < 0.5


def test_the_split_path_reconstructs_an_untouched_target():
    fine = ResolutionReport(2048, 512, SR, low_knee_hz=200.0, low_n_fft=16384)
    target = (sine(55.0, 1.0, sr=SR) + sine(2000.0, 1.0, sr=SR))[:, 0].astype(np.float32)
    freqs = librosa.fft_frequencies(sr=SR, n_fft=2048)
    times = librosa.frames_to_time(np.arange(1 + target.shape[0] // 512), sr=SR, hop_length=512)
    empty = SpectralField(freqs, times, np.zeros((freqs.shape[0], times.shape[0])), "symbolic", fine, "fp")
    params = MaskParams(polarity="carve", harmonic_depth=1, notch_width_cents=100.0, depth_db=12.0)
    out = apply(target, SR, build_mask(empty, params, bark=bark_band_map(SR, 2048)), n_fft=2048, hop=512)
    assert np.allclose(out, target, atol=2e-5)


def test_apply_refuses_a_target_shorter_than_the_long_window():
    fine = ResolutionReport(2048, 512, SR, low_knee_hz=200.0, low_n_fft=16384)
    field = _bass_field(4096, 2048, fine)
    params = MaskParams(polarity="carve", harmonic_depth=1, notch_width_cents=100.0, depth_db=6.0)
    mask = build_mask(field, params, bark=bark_band_map(SR, 2048), resolution=fine)
    with pytest.raises(ValueError, match="shorter than the 16384-point low-band window"):
        apply(np.zeros(4096, dtype=np.float32), SR, mask, n_fft=2048, hop=512)
