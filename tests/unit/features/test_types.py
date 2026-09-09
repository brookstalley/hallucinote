"""Feature streams validate their shapes and map seconds to beats through a BeatMap."""
from __future__ import annotations

import numpy as np
import pytest

from hallucinote.features.types import BeatStream, FeatureEvent, FeatureStream, Segment


class _ConstantTempo:
    """120 bpm, clip placed at beat 8: a BeatMap with nothing tempo-aware in it."""

    def seconds_to_beats(self, seconds: float) -> float:
        return 8.0 + seconds * 2.0

    def beats_to_seconds(self, beats: float) -> float:
        return (beats - 8.0) / 2.0


def test_stream_maps_to_beats_through_the_placement_and_keeps_values():
    s = FeatureStream("f0", times_s=[0.0, 0.5, 1.0], values=[220.0, np.nan, 440.0],
                      units="hz", confidence=[0.9, 0.0, 0.8])
    b = s.to_beats(_ConstantTempo())
    assert isinstance(b, BeatStream)
    assert b.beats.tolist() == [8.0, 9.0, 10.0]
    assert np.isnan(b.values[1]) and b.values[2] == 440.0
    assert b.confidence is not None and b.confidence[0] == 0.9
    assert len(b) == 3


def test_vector_valued_stream_keeps_its_second_axis():
    s = FeatureStream("bark", times_s=[0.0, 0.1], values=np.zeros((2, 24)), units="db")
    assert s.values.shape == (2, 24)


@pytest.mark.parametrize("kwargs,msg", [
    (dict(times_s=[0.0, 1.0], values=[1.0]), "first axis"),
    (dict(times_s=[1.0, 0.0], values=[1.0, 2.0]), "non-decreasing"),
    (dict(times_s=[0.0, 1.0], values=[1.0, 2.0], confidence=[0.5]), "confidence"),
    (dict(times_s=[0.0, 1.0], values=[1.0, 2.0], confidence=[0.5, 1.5]), r"\[0, 1\]"),
])
def test_stream_refuses_mismatched_series(kwargs, msg):
    with pytest.raises(ValueError, match=msg):
        FeatureStream("x", units="u", **kwargs)


def test_segment_and_event_validate():
    seg = Segment(0.2, 0.9, "phrase")
    assert seg.duration_s == pytest.approx(0.7)
    with pytest.raises(ValueError, match="precedes"):
        Segment(1.0, 0.5, "phrase")
    ev = FeatureEvent(0.25, "scale_tone", {"pitch_class": 2})
    assert ev.beat is None and ev.payload["pitch_class"] == 2
    with pytest.raises(ValueError, match="kind"):
        FeatureEvent(0.0, "")
