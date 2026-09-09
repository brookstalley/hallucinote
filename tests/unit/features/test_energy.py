"""Energy and descriptor streams: dBFS you can check by hand, timbre that
agrees with the timbre lens, one frame grid for all of them."""
from __future__ import annotations

import numpy as np
import pytest

from hallucinote.audio.bark import bark_band_map
from hallucinote.features.energy import (
    N_FFT,
    SILENCE_FLOOR_DBFS,
    bark_band_energies,
    energy_envelope,
    spectral_centroid,
    spectral_descriptors,
    spectral_flatness,
    spectral_rolloff,
)
from tests.unit.audio.fixtures import SAMPLE_RATE, concat, silence, sine

SR = SAMPLE_RATE


def _white(duration_s: float, *, amplitude: float = 0.2, seed: int = 0) -> np.ndarray:
    n = int(round(duration_s * SR))
    mono = (amplitude * np.random.default_rng(seed).standard_normal(n)).astype(np.float32)
    return np.stack([mono, mono], axis=1)


def test_sine_energy_reads_its_rms_in_dbfs():
    stream = energy_envelope(sine(440.0, 1.0, amplitude=0.5), SR)
    assert stream.name == "energy" and stream.units == "dBFS"
    steady = stream.values[(stream.times_s > 0.1) & (stream.times_s < 0.9)]
    assert np.median(steady) == pytest.approx(20.0 * np.log10(0.5 / np.sqrt(2.0)), abs=0.1)


def test_silence_reads_the_floor_and_stays_finite():
    stream = energy_envelope(silence(0.5), SR)
    assert np.all(np.isfinite(stream.values))
    assert np.all(stream.values == SILENCE_FLOOR_DBFS)


def test_hop_sets_the_frame_grid_for_every_stream():
    audio = sine(1000.0, 0.5)
    env = energy_envelope(audio, SR, hop_s=0.020)
    desc = spectral_descriptors(audio, SR, hop_s=0.020)
    assert np.allclose(np.diff(env.times_s), 960 / SR)
    np.testing.assert_array_equal(env.times_s, desc.centroid.times_s)
    np.testing.assert_array_equal(desc.centroid.times_s, desc.bark_bands.times_s)
    assert env.times_s[0] == 0.0


def test_pure_tone_descriptors_agree_with_the_timbre_lens():
    desc = spectral_descriptors(sine(1000.0, 1.0), SR)
    mid = (desc.centroid.times_s > 0.1) & (desc.centroid.times_s < 0.9)
    assert np.nanmedian(desc.centroid.values[mid]) == pytest.approx(1000.0, abs=50.0)
    assert np.nanmedian(desc.rolloff.values[mid]) == pytest.approx(1000.0, abs=100.0)
    assert np.nanmedian(desc.flatness.values[mid]) < 0.05
    assert desc.centroid.units == "Hz" and desc.flatness.units == "ratio"


def test_noise_is_flatter_than_a_tone():
    tone = spectral_flatness(sine(1000.0, 1.0), SR)
    noise = spectral_flatness(_white(1.0), SR)
    assert np.nanmedian(noise.values) > 0.2
    assert np.nanmedian(noise.values) > 5 * np.nanmedian(tone.values)


def test_brighter_signal_has_higher_centroid_and_rolloff():
    dark_c = spectral_centroid(sine(200.0, 0.5), SR)
    bright_c = spectral_centroid(sine(5000.0, 0.5), SR)
    dark_r = spectral_rolloff(sine(200.0, 0.5), SR)
    bright_r = spectral_rolloff(sine(5000.0, 0.5), SR)
    assert np.nanmedian(bright_c.values) > np.nanmedian(dark_c.values)
    assert np.nanmedian(bright_r.values) > np.nanmedian(dark_r.values)


def test_bark_bands_are_a_vector_stream_peaking_in_the_tones_band():
    stream = bark_band_energies(sine(1000.0, 0.5), SR)
    n_bands = bark_band_map(SR, N_FFT).n_bands
    assert stream.values.shape == (len(stream), n_bands)
    assert stream.units == "dB"
    mid = int(len(stream) // 2)
    edges = bark_band_map(SR, N_FFT).edges_hz
    band_of_1k = int(np.searchsorted(edges, 1000.0, side="right") - 1)
    assert int(np.argmax(stream.values[mid])) == band_of_1k


def test_silent_frames_are_nan_in_descriptors_with_zero_confidence():
    audio = concat(silence(0.5), sine(1000.0, 0.5))
    desc = spectral_descriptors(audio, SR)
    head = desc.centroid.times_s < 0.4
    assert np.all(np.isnan(desc.centroid.values[head]))
    assert np.all(np.isnan(desc.bark_bands.values[head]))
    assert desc.centroid.confidence is not None
    assert np.all(desc.centroid.confidence[head] == 0.0)
    assert np.all(desc.centroid.confidence[desc.centroid.times_s > 0.6] == 1.0)


def test_all_silent_descriptors_are_nan_everywhere():
    desc = spectral_descriptors(silence(0.3), SR)
    assert np.all(np.isnan(desc.centroid.values))
    assert np.all(np.isnan(desc.flatness.values))


@pytest.mark.parametrize("hop_s", [0.0, -0.01])
def test_hop_must_be_positive(hop_s):
    with pytest.raises(ValueError, match="hop_s must be positive"):
        energy_envelope(sine(440.0, 0.1), SR, hop_s=hop_s)


def test_empty_audio_is_refused():
    with pytest.raises(ValueError, match="no samples"):
        spectral_descriptors(np.zeros((0, 2), dtype=np.float32), SR)
