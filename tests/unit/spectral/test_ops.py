"""Carve and vocode on arrays: one field, one mask, a polarity.

Fields are built by hand — unit magnitude at chosen bins on an STFT grid — so
every assertion is about the operation, not about how a field is measured.
Attenuation is read off the whole-signal spectrum in a band around each tone.
"""
from __future__ import annotations

import librosa
import numpy as np
import pytest

from hallucinote.audio.bark import bark_band_map
from hallucinote.spectral.ops import Mask, apply, build_mask
from hallucinote.spectral.types import MaskParams, ResolutionReport, SpectralField
from tests.unit.audio.fixtures import SAMPLE_RATE, sine

SR = SAMPLE_RATE
N_FFT = 2048
HOP = 512
BARK = bark_band_map(SR, N_FFT)
BASE = ResolutionReport(n_fft=N_FFT, hop=HOP, sample_rate=SR)


def _mono(*tones: float, duration_s: float = 2.0) -> np.ndarray:
    mix = sum(sine(f, duration_s, amplitude=0.3, sr=SR) for f in tones)
    return np.asarray(mix)[:, 0].astype(np.float32)


def _stft_grid(n_samples: int, n_fft: int = N_FFT, hop: int = HOP) -> tuple[np.ndarray, np.ndarray]:
    freqs = librosa.fft_frequencies(sr=SR, n_fft=n_fft)
    times = librosa.frames_to_time(np.arange(1 + n_samples // hop), sr=SR, hop_length=hop)
    return freqs, times


def _field_with(
    n_samples: int,
    *tones_hz: float,
    n_fft: int = N_FFT,
    resolution: ResolutionReport = BASE,
    frames: slice | None = None,
) -> SpectralField:
    """Unit magnitude at the bin nearest each tone, over all frames or a slice of them."""
    freqs, times = _stft_grid(n_samples, n_fft=n_fft)
    magnitude = np.zeros((freqs.shape[0], times.shape[0]))
    for hz in tones_hz:
        magnitude[int(np.argmin(np.abs(freqs - hz))), frames or slice(None)] = 1.0
    return SpectralField(
        freqs_hz=freqs, times_s=times, magnitude=magnitude, origin="symbolic",
        resolution=resolution, fingerprint="fp-test",
    )


def _band_db(mono: np.ndarray, center_hz: float, half_width_hz: float = 30.0) -> float:
    """Power in a band of the whole-signal spectrum, in dB."""
    x = np.asarray(mono, dtype=np.float64)
    spec = np.abs(np.fft.rfft(x * np.hanning(x.shape[0]))) ** 2
    freqs = np.fft.rfftfreq(x.shape[0], d=1.0 / SR)
    band = (freqs >= center_hz - half_width_hz) & (freqs <= center_hz + half_width_hz)
    return 10.0 * np.log10(spec[band].sum() + 1e-30)


def _attenuation_db(before: np.ndarray, after: np.ndarray, hz: float) -> float:
    return _band_db(before, hz) - _band_db(after, hz)


def _params(polarity: str = "carve", **over) -> MaskParams:
    base = dict(polarity=polarity, harmonic_depth=1, notch_width_cents=200.0, depth_db=12.0)
    base.update(over)
    return MaskParams(**base)


def test_carve_attenuates_the_referenced_tone_and_leaves_the_other():
    target = _mono(440.0, 2000.0)
    field = _field_with(target.shape[0], 440.0)
    mask = build_mask(field, _params("carve"), bark=BARK)
    out = apply(target, SR, mask, n_fft=N_FFT, hop=HOP)

    assert out.shape == target.shape and out.dtype == np.float32
    assert _attenuation_db(target, out, 440.0) == pytest.approx(12.0, abs=1.0)
    assert abs(_attenuation_db(target, out, 2000.0)) < 0.5
    assert mask.polarity == "carve"
    assert mask.fingerprint == "fp-test"


def test_vocode_is_the_complement_of_carve():
    target = _mono(440.0, 2000.0)
    field = _field_with(target.shape[0], 440.0)
    mask = build_mask(field, _params("vocode"), bark=BARK)
    out = apply(target, SR, mask, n_fft=N_FFT, hop=HOP)

    assert abs(_attenuation_db(target, out, 440.0)) < 0.5
    assert _attenuation_db(target, out, 2000.0) == pytest.approx(12.0, abs=1.0)


def test_depth_is_capped_by_the_type():
    with pytest.raises(ValueError, match="depth_db"):
        _params(depth_db=60.0)


def test_per_frame_depth_automates_the_carve_over_time():
    target = _mono(440.0, duration_s=2.0)
    field = _field_with(target.shape[0], 440.0)
    n_t = field.times_s.shape[0]
    depth = np.where(field.times_s < 1.0, 12.0, 3.0)
    mask = build_mask(field, _params(depth_db=depth), bark=BARK)
    out = apply(target, SR, mask, n_fft=N_FFT, hop=HOP)

    first = slice(int(0.1 * SR), int(0.8 * SR))
    last = slice(int(1.2 * SR), int(1.9 * SR))
    assert _attenuation_db(target[first], out[first], 440.0) == pytest.approx(12.0, abs=1.5)
    assert _attenuation_db(target[last], out[last], 440.0) == pytest.approx(3.0, abs=1.5)
    assert depth.shape == (n_t,)


def test_an_automated_parameter_must_align_to_the_field_frames():
    field = _field_with(SR, 440.0)
    with pytest.raises(ValueError, match="aligned to the field's time axis"):
        build_mask(field, _params(depth_db=np.array([12.0, 6.0])), bark=BARK)


def test_smoothing_fades_a_notch_in_and_out():
    n = 2 * SR
    freqs, times = _stft_grid(n)
    inside = (times >= 0.8) & (times <= 1.2)
    magnitude = np.zeros((freqs.shape[0], times.shape[0]))
    ref_bin = int(np.argmin(np.abs(freqs - 440.0)))
    magnitude[ref_bin, inside] = 1.0
    field = SpectralField(freqs, times, magnitude, "symbolic", BASE, "fp")

    hard = build_mask(field, _params(), bark=BARK)
    soft = build_mask(field, _params(smoothing_s=0.2), bark=BARK)
    at = lambda m, t: float(m.gain[ref_bin, int(np.argmin(np.abs(times - t)))])  # noqa: E731

    full = 10.0 ** (-12.0 / 20.0)
    assert at(hard, 0.5) == pytest.approx(1.0)
    assert at(hard, 1.0) == pytest.approx(full)
    assert at(hard, 0.79) == pytest.approx(1.0)
    assert at(soft, 0.5) == pytest.approx(1.0)
    assert at(soft, 1.0) == pytest.approx(full, abs=1e-3)
    assert full < at(soft, 0.79) < 1.0


def test_the_bark_band_shapes_the_notch_edges_not_its_width():
    """The plateau is pure cents; the skirt is a fraction of the critical band."""
    n_fft = 16384
    res = ResolutionReport(N_FFT, HOP, SR, low_knee_hz=200.0, low_n_fft=n_fft)
    field = _field_with(2 * SR, 55.0, 5000.0, n_fft=n_fft, resolution=res)
    mask = build_mask(field, _params(notch_width_cents=100.0), bark=BARK, resolution=res)
    gain = mask.gain[:, 0]
    freqs = mask.freqs_hz

    def extent(center_hz: float, level: float) -> float:
        i = int(np.argmin(np.abs(freqs - center_hz)))
        touched = np.flatnonzero(gain[:] <= level)
        near = touched[np.abs(touched - i) < 400]
        return float(freqs[near.max()] - freqs[i])

    full = 10.0 ** (-12.0 / 20.0) + 1e-6
    bass_plateau, bass_footprint = extent(55.0, full), extent(55.0, 1.0 - 1e-6)
    high_plateau, high_footprint = extent(5000.0, full), extent(5000.0, 1.0 - 1e-6)
    # 100 cents at 55 Hz is ~3.3 Hz wide; at 5 kHz ~300 Hz — the pitch axis rules the plateau.
    assert bass_plateau < 6.0
    assert 120.0 < high_plateau < 180.0
    # The skirt follows the Bark band: 5 Hz in the 0-100 band, ~45 Hz in the 4400-5300 band.
    assert bass_footprint - bass_plateau < 12.0
    assert 30.0 < high_footprint - high_plateau < 60.0


def test_apply_refuses_a_field_that_does_not_cover_the_target():
    target = _mono(440.0, duration_s=2.0)
    field = _field_with(SR, 440.0)  # one second of field, two of target
    mask = build_mask(field, _params(), bark=BARK)
    with pytest.raises(ValueError, match="does not cover the target"):
        apply(target, SR, mask, n_fft=N_FFT, hop=HOP)


def test_apply_refuses_a_window_that_is_not_the_masks():
    target = _mono(440.0)
    mask = build_mask(_field_with(target.shape[0], 440.0), _params(), bark=BARK)
    with pytest.raises(ValueError, match="precision claim holds only for its own windows"):
        apply(target, SR, mask, n_fft=4096, hop=HOP)
    with pytest.raises(ValueError, match="precision claim"):
        apply(target, 44100, mask, n_fft=N_FFT, hop=HOP)


def test_apply_refuses_a_target_shorter_than_the_window():
    mask = build_mask(_field_with(SR, 440.0), _params(), bark=BARK)
    with pytest.raises(ValueError, match="shorter than the 2048-point window"):
        apply(np.zeros(1000, dtype=np.float32), SR, mask, n_fft=N_FFT, hop=HOP)


def test_a_single_frame_field_is_a_static_mask():
    target = _mono(440.0, 2000.0)
    freqs = librosa.fft_frequencies(sr=SR, n_fft=N_FFT)
    magnitude = np.zeros((freqs.shape[0], 1))
    magnitude[int(np.argmin(np.abs(freqs - 440.0))), 0] = 1.0
    field = SpectralField(freqs, np.array([0.0]), magnitude, "symbolic", BASE, "fp")
    out = apply(target, SR, build_mask(field, _params(), bark=BARK), n_fft=N_FFT, hop=HOP)
    assert _attenuation_db(target, out, 440.0) == pytest.approx(12.0, abs=1.0)
    assert abs(_attenuation_db(target, out, 2000.0)) < 0.5


def test_an_empty_field_carves_nothing_and_vocodes_everything_down():
    target = _mono(440.0, 2000.0)
    field = _field_with(target.shape[0])
    carve = build_mask(field, _params("carve"), bark=BARK)
    vocode = build_mask(field, _params("vocode"), bark=BARK)
    assert carve.precision is None and vocode.precision is None

    same = apply(target, SR, carve, n_fft=N_FFT, hop=HOP)
    assert np.allclose(same, target, atol=1e-5)
    down = apply(target, SR, vocode, n_fft=N_FFT, hop=HOP)
    for hz in (440.0, 2000.0):
        assert _attenuation_db(target, down, hz) == pytest.approx(12.0, abs=0.5)


def test_stereo_targets_keep_their_shape_and_a_dead_channel_stays_dead():
    left = _mono(440.0)
    target = np.stack([left, np.zeros_like(left)], axis=1)
    mask = build_mask(_field_with(left.shape[0], 440.0), _params(), bark=BARK)
    out = apply(target, SR, mask, n_fft=N_FFT, hop=HOP)
    assert out.shape == target.shape and out.dtype == np.float32
    assert _attenuation_db(target[:, 0], out[:, 0], 440.0) == pytest.approx(12.0, abs=1.0)
    assert np.abs(out[:, 1]).max() == 0.0


def test_the_energy_floor_decides_what_counts_as_reference():
    freqs, times = _stft_grid(SR)
    magnitude = np.zeros((freqs.shape[0], times.shape[0]))
    loud, quiet = (int(np.argmin(np.abs(freqs - f))) for f in (440.0, 2000.0))
    magnitude[loud] = 1.0
    magnitude[quiet] = 10.0 ** (-50.0 / 20.0)
    field = SpectralField(freqs, times, magnitude, "measured", BASE, "fp")

    default = build_mask(field, _params(), bark=BARK)
    assert default.gain[quiet].min() == pytest.approx(1.0)
    generous = build_mask(field, _params(), bark=BARK, energy_floor_db=60.0)
    assert generous.gain[quiet].min() < 0.3


def test_mask_refuses_a_gain_that_boosts():
    with pytest.raises(ValueError, match="never boosts"):
        Mask(
            freqs_hz=np.array([100.0]), times_s=np.array([0.0]), gain=np.array([[1.5]]),
            rest_gain=np.array([1.0]), polarity="carve", resolution=BASE, precision=None,
            fingerprint="fp",
        )
