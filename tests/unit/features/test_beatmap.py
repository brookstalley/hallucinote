"""The placed beat map: seconds ↔ beats round-trip across a tempo ramp,
anchored at the clip's placement, and a re-tempo moves the beats without
touching the stream."""
from __future__ import annotations

import numpy as np
import pytest

from hallucinote.audio.section import TempoSegment, declared_span_seconds
from hallucinote.features.beatmap import PlacedBeatMap, beat_map_for_placement
from hallucinote.features.types import BeatMap, FeatureStream

SR = 48_000
RAMP = (TempoSegment(0.0, 120.0, "linear"), TempoSegment(8.0, 90.0, "hold"), TempoSegment(16.0, 140.0, "hold"))


def test_satisfies_the_beat_map_protocol():
    m = beat_map_for_placement([TempoSegment(0.0, 120.0)], start_beat=0.0, n_samples=SR, sample_rate=SR)
    assert isinstance(m, BeatMap)
    assert isinstance(m, PlacedBeatMap)


def test_constant_tempo_is_exact():
    m = beat_map_for_placement([TempoSegment(0.0, 120.0)], start_beat=4.0, n_samples=3 * SR, sample_rate=SR)
    assert m.seconds_to_beats(0.0) == pytest.approx(4.0)
    assert m.seconds_to_beats(1.0) == pytest.approx(6.0)
    assert m.beats_to_seconds(7.0) == pytest.approx(1.5)
    assert m.end_beat == pytest.approx(10.0)
    assert m.duration_s == pytest.approx(3.0)


def test_round_trips_across_a_tempo_ramp():
    m = beat_map_for_placement(RAMP, start_beat=4.0, n_samples=6 * SR, sample_rate=SR)
    for s in np.linspace(0.0, 6.0, 25):
        assert m.beats_to_seconds(m.seconds_to_beats(float(s))) == pytest.approx(s, abs=1e-6)
    for b in np.linspace(4.0, m.end_beat, 25):
        assert m.seconds_to_beats(m.beats_to_seconds(float(b))) == pytest.approx(b, abs=1e-6)


def test_end_beat_is_where_the_tempo_map_puts_the_files_last_sample():
    m = beat_map_for_placement(RAMP, start_beat=4.0, n_samples=6 * SR, sample_rate=SR)
    assert declared_span_seconds(4.0, m.end_beat, RAMP) == pytest.approx(6.0, abs=1e-6)
    # The ramp slows from 120 toward 90 by beat 8, so 6 s covers fewer beats than 120 bpm would.
    assert m.end_beat < 4.0 + 12.0
    assert m.end_beat > 4.0 + 9.0


def test_beats_follow_the_ramp_not_a_straight_line():
    m = beat_map_for_placement(RAMP, start_beat=0.0, n_samples=8 * SR, sample_rate=SR)
    # Half a second at the start is at ~120 bpm; half a second around beat 12 is at 90 bpm.
    early = m.seconds_to_beats(0.5) - m.seconds_to_beats(0.0)
    late_start = m.beats_to_seconds(12.0)
    late = m.seconds_to_beats(late_start + 0.5) - 12.0
    assert early == pytest.approx(1.0, abs=0.05)
    assert late == pytest.approx(0.75, abs=1e-6)


def test_extrapolates_beyond_the_file_in_both_directions():
    m = beat_map_for_placement([TempoSegment(0.0, 120.0)], start_beat=4.0, n_samples=SR, sample_rate=SR)
    assert m.seconds_to_beats(2.5) == pytest.approx(9.0, abs=1e-6)
    assert m.seconds_to_beats(-0.5) == pytest.approx(3.0, abs=1e-6)
    assert m.beats_to_seconds(2.0) == pytest.approx(-1.0)


def test_a_re_tempo_moves_the_beats_and_leaves_the_stream_alone():
    stream = FeatureStream("f0", np.linspace(0.0, 1.0, 11), np.full(11, 220.0), "Hz")
    slow = beat_map_for_placement([TempoSegment(0.0, 60.0)], start_beat=16.0, n_samples=SR, sample_rate=SR)
    fast = beat_map_for_placement([TempoSegment(0.0, 120.0)], start_beat=16.0, n_samples=SR, sample_rate=SR)
    at_slow = stream.to_beats(slow)
    at_fast = stream.to_beats(fast)
    assert at_slow.beats[-1] == pytest.approx(17.0)
    assert at_fast.beats[-1] == pytest.approx(18.0)
    np.testing.assert_array_equal(at_slow.values, at_fast.values)
    np.testing.assert_array_equal(stream.times_s, np.linspace(0.0, 1.0, 11))


def test_placement_before_the_tempo_map_teaches():
    with pytest.raises(ValueError, match="precedes the tempo map's first point"):
        beat_map_for_placement([TempoSegment(8.0, 120.0)], start_beat=4.0, n_samples=SR, sample_rate=SR)


def test_a_beat_before_the_tempo_map_teaches():
    m = beat_map_for_placement([TempoSegment(8.0, 120.0)], start_beat=8.0, n_samples=SR, sample_rate=SR)
    with pytest.raises(ValueError, match="precedes the tempo map's first point"):
        m.beats_to_seconds(2.0)


def test_empty_or_zero_bpm_tempo_map_is_refused():
    with pytest.raises(ValueError, match="at least one TempoSegment"):
        beat_map_for_placement([], start_beat=0.0, n_samples=SR, sample_rate=SR)
    with pytest.raises(ValueError, match="at least one TempoSegment"):
        beat_map_for_placement([TempoSegment(0.0, 0.0)], start_beat=0.0, n_samples=SR, sample_rate=SR)


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"n_samples": 0}, "n_samples must be > 0"),
        ({"sample_rate": 0}, "sample_rate must be > 0"),
    ],
)
def test_size_and_rate_are_validated(kwargs, match):
    args = {"start_beat": 0.0, "n_samples": SR, "sample_rate": SR, **kwargs}
    with pytest.raises(ValueError, match=match):
        beat_map_for_placement([TempoSegment(0.0, 120.0)], **args)
