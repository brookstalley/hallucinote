"""F0 contour: tracks a vibrato's centre, marks silence as ``nan`` not 0."""
from __future__ import annotations

import numpy as np
import pytest

from hallucinote.audio.section import TempoSegment
from hallucinote.features.beatmap import beat_map_for_placement
from hallucinote.features.f0 import default_frame_length, f0_contour
from hallucinote.features.types import BeatStream, FeatureStream
from tests.unit.audio.fixtures import SAMPLE_RATE, concat, silence

SR = SAMPLE_RATE


def _vibrato_sine(center_hz: float, duration_s: float, *, depth: float = 0.03, rate_hz: float = 5.0) -> np.ndarray:
    t = np.arange(int(round(duration_s * SR)), dtype=np.float64) / SR
    inst = center_hz * (1.0 + depth * np.sin(2.0 * np.pi * rate_hz * t))
    phase = 2.0 * np.pi * np.cumsum(inst) / SR
    mono = (0.5 * np.sin(phase)).astype(np.float32)
    return np.stack([mono, mono], axis=1)


def test_vibrato_sine_f0_tracks_its_centre_within_one_percent():
    stream = f0_contour(_vibrato_sine(220.0, 2.0), SR, fmin=60.0, fmax=800.0)

    assert isinstance(stream, FeatureStream)
    assert stream.name == "f0" and stream.units == "Hz"
    assert np.nanmean(stream.values) == pytest.approx(220.0, rel=0.01)
    assert np.nanmax(stream.values) > 220.0 * 1.02  # the vibrato is visible
    assert np.nanmin(stream.values) < 220.0 * 0.98
    assert stream.confidence is not None
    assert np.mean(stream.confidence) > 0.9


def test_unvoiced_frames_carry_nan_never_zero():
    audio = concat(silence(0.5), _vibrato_sine(220.0, 1.0), silence(0.5))
    stream = f0_contour(audio, SR, fmin=60.0, fmax=800.0)

    head = stream.values[stream.times_s < 0.4]
    assert head.size > 0 and np.all(np.isnan(head))
    assert not np.any(stream.values == 0.0)
    assert stream.confidence is not None
    assert np.all(stream.confidence[stream.times_s < 0.4] < 0.5)
    assert np.all((stream.confidence >= 0.0) & (stream.confidence <= 1.0))


def test_frame_grid_follows_hop_and_frame_defaults_scale_with_fmin():
    stream = f0_contour(_vibrato_sine(220.0, 1.0), SR, fmin=60.0, fmax=800.0, hop_length=480)
    assert np.allclose(np.diff(stream.times_s), 480 / SR)
    assert default_frame_length(SR, 60.0) == 4096
    assert default_frame_length(SR, 300.0) == 2048


def test_contour_maps_to_beats_through_a_placement():
    stream = f0_contour(_vibrato_sine(220.0, 1.0), SR, fmin=60.0, fmax=800.0)
    bmap = beat_map_for_placement(
        [TempoSegment(0.0, 120.0)], start_beat=8.0, n_samples=SR, sample_rate=SR,
    )
    beats = stream.to_beats(bmap)
    assert isinstance(beats, BeatStream)
    assert beats.beats[0] == pytest.approx(8.0)
    assert beats.beats[-1] == pytest.approx(8.0 + 2.0 * stream.times_s[-1])


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"fmin": 0.0, "fmax": 500.0}, "fmin must be > 0"),
        ({"fmin": 500.0, "fmax": 100.0}, "fmax .* must exceed fmin"),
        ({"fmin": 60.0, "fmax": SR}, "below Nyquist"),
    ],
)
def test_pitch_range_is_validated(kwargs, match):
    with pytest.raises(ValueError, match=match):
        f0_contour(_vibrato_sine(220.0, 0.2), SR, **kwargs)


def test_empty_audio_is_refused():
    with pytest.raises(ValueError, match="no samples"):
        f0_contour(np.zeros((0, 2), dtype=np.float32), SR, fmin=60.0, fmax=800.0)
