"""Formants: a synthesized two-formant vowel gives back both resonances."""
from __future__ import annotations

import numpy as np
import pytest
from scipy.signal import lfilter

from hallucinote.features.formants import formant_tracks
from tests.unit.audio.fixtures import SAMPLE_RATE, concat, silence

SR = SAMPLE_RATE


def _resonator(freq_hz: float, bandwidth_hz: float, sr: int) -> tuple[np.ndarray, np.ndarray]:
    r = np.exp(-np.pi * bandwidth_hz / sr)
    theta = 2.0 * np.pi * freq_hz / sr
    return np.asarray([1.0 - r]), np.asarray([1.0, -2.0 * r * np.cos(theta), r * r])


def _vowel(f1: float, f2: float, *, duration_s: float = 1.0, pitch_hz: float = 120.0) -> np.ndarray:
    n = int(round(duration_s * SR))
    pulses = np.zeros(n)
    pulses[:: int(round(SR / pitch_hz))] = 1.0
    b1, a1 = _resonator(f1, 80.0, SR)
    b2, a2 = _resonator(f2, 100.0, SR)
    v = lfilter(b1, a1, lfilter(b2, a2, pulses))
    v = (0.5 * v / np.max(np.abs(v))).astype(np.float32)
    return np.stack([v, v], axis=1)


def test_two_formant_vowel_recovers_both_within_ten_percent():
    tracks = formant_tracks(_vowel(500.0, 1500.0), SR, n_formants=2)

    assert [t.name for t in tracks] == ["F1", "F2"]
    assert all(t.units == "Hz" for t in tracks)
    assert np.nanmedian(tracks[0].values) == pytest.approx(500.0, rel=0.10)
    assert np.nanmedian(tracks[1].values) == pytest.approx(1500.0, rel=0.10)
    assert np.isnan(tracks[0].values).mean() < 0.1
    for t in tracks:
        assert t.confidence is not None
        assert np.all((t.confidence >= 0.0) & (t.confidence <= 1.0))


def test_a_different_vowel_moves_the_tracks():
    open_vowel = formant_tracks(_vowel(700.0, 1200.0), SR, n_formants=2)
    close_vowel = formant_tracks(_vowel(300.0, 2300.0), SR, n_formants=2)
    assert np.nanmedian(open_vowel[0].values) > np.nanmedian(close_vowel[0].values)
    assert np.nanmedian(open_vowel[1].values) < np.nanmedian(close_vowel[1].values)


def test_silent_frames_carry_nan_on_every_track():
    audio = concat(silence(0.5), _vowel(500.0, 1500.0, duration_s=0.5))
    tracks = formant_tracks(audio, SR, n_formants=3)
    for t in tracks:
        head = t.values[t.times_s < 0.4]
        assert head.size > 0 and np.all(np.isnan(head))
        assert t.confidence is not None
        assert np.all(t.confidence[t.times_s < 0.4] == 0.0)
    assert not np.all(np.isnan(tracks[0].values[tracks[0].times_s > 0.6]))


def test_frames_sit_on_the_requested_hop():
    tracks = formant_tracks(_vowel(500.0, 1500.0, duration_s=0.3), SR, hop_s=0.010)
    assert len(tracks) == 3
    assert np.allclose(np.diff(tracks[0].times_s), 0.010, atol=1e-6)
    assert tracks[0].times_s[0] == 0.0


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"n_formants": 0}, "n_formants must be >= 1"),
        ({"window_s": 0.0}, "must be positive seconds"),
        ({"max_bandwidth_hz": -1.0}, "max_bandwidth_hz must be > 0"),
        ({"lpc_order": 1}, "lpc_order must be >= 2"),
    ],
)
def test_parameters_are_validated(kwargs, match):
    with pytest.raises(ValueError, match=match):
        formant_tracks(_vowel(500.0, 1500.0, duration_s=0.2), SR, **kwargs)


def test_empty_audio_is_refused():
    with pytest.raises(ValueError, match="no samples"):
        formant_tracks(np.zeros((0, 2), dtype=np.float32), SR)
