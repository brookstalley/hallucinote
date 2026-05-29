"""Beat-domain → sample-domain windowing for section-scoped analysis.

These tests pin the pure geometry (``intersect_window`` / ``slice_audio``)
independently of the loudness math: given a capture's transport span and a
section's beat window, which samples are inside, and what happens at the
edges (clamping, no-overlap, degenerate spans).
"""
from __future__ import annotations

import numpy as np
import pytest

from hallucinote.audio.section import (
    BeatSampleMap,
    SectionWindow,
    TempoSegment,
    intersect_window,
    slice_audio,
)


def _window(name: str, start: float, end: float) -> SectionWindow:
    return SectionWindow(name=name, start_beat=start, end_beat=end)


def test_intersect_window_maps_full_span_to_full_audio():
    """A window covering the whole capture maps to [0, n_samples)."""
    sl = intersect_window(
        _window("all", 0.0, 16.0),
        n_samples=48_000,
        capture_start_beat=0.0,
        capture_stop_beat=16.0,
    )
    assert sl.covered is True
    assert sl.start_sample == 0
    assert sl.end_sample == 48_000


def test_intersect_window_maps_middle_window_proportionally():
    """Beats 4..8 of a 0..16 / 48000-sample capture → samples 12000..24000."""
    sl = intersect_window(
        _window("verse", 4.0, 8.0),
        n_samples=48_000,
        capture_start_beat=0.0,
        capture_stop_beat=16.0,
    )
    assert sl.covered is True
    assert sl.start_sample == 12_000
    assert sl.end_sample == 24_000


def test_intersect_window_respects_nonzero_capture_start():
    """When the capture starts at beat 8, a beat-12..16 window maps onto the
    back half of the audio (the capture origin is subtracted first)."""
    sl = intersect_window(
        _window("chorus", 12.0, 16.0),
        n_samples=8_000,
        capture_start_beat=8.0,
        capture_stop_beat=16.0,
    )
    assert sl.covered is True
    assert sl.start_sample == 4_000
    assert sl.end_sample == 8_000


def test_intersect_window_clamps_window_overhanging_capture_end():
    """A section running past the capture end is clamped to n_samples,
    still covered (the overlapping front portion is analyzable)."""
    sl = intersect_window(
        _window("outro", 12.0, 99.0),
        n_samples=16_000,
        capture_start_beat=0.0,
        capture_stop_beat=16.0,
    )
    assert sl.covered is True
    assert sl.start_sample == 12_000
    assert sl.end_sample == 16_000


def test_intersect_window_not_covered_when_entirely_after_capture():
    """A section that starts after the capture stops has no overlap."""
    sl = intersect_window(
        _window("never-rendered", 20.0, 24.0),
        n_samples=16_000,
        capture_start_beat=0.0,
        capture_stop_beat=16.0,
    )
    assert sl.covered is False


def test_intersect_window_not_covered_when_entirely_before_capture():
    """A section ending before the capture starts has no overlap."""
    sl = intersect_window(
        _window("pre-roll", 0.0, 4.0),
        n_samples=16_000,
        capture_start_beat=8.0,
        capture_stop_beat=24.0,
    )
    assert sl.covered is False


def test_intersect_window_degenerate_capture_span_is_not_covered():
    """stop<=start (degenerate capture) → not covered, no divide-by-zero."""
    sl = intersect_window(
        _window("x", 0.0, 4.0),
        n_samples=16_000,
        capture_start_beat=8.0,
        capture_stop_beat=8.0,
    )
    assert sl.covered is False


def test_intersect_window_empty_audio_is_not_covered():
    sl = intersect_window(
        _window("x", 0.0, 4.0),
        n_samples=0,
        capture_start_beat=0.0,
        capture_stop_beat=16.0,
    )
    assert sl.covered is False


def test_slice_audio_returns_the_clamped_sample_range():
    audio = np.arange(20, dtype=np.float32).reshape(10, 2)
    sl = intersect_window(
        _window("mid", 4.0, 8.0),
        n_samples=10,
        capture_start_beat=0.0,
        capture_stop_beat=16.0,
    )
    sliced = slice_audio(audio, sl)
    # beats 4..8 of 0..16 over 10 samples → samples 2.5..5 → round → 2..5
    assert sliced.shape == (3, 2)
    assert sliced[0, 0] == audio[2, 0]


# ---------- BeatSampleMap (variable-tempo beat<->sample) ----------


def test_beat_sample_map_constant_tempo_is_linear():
    """No tempo segments → exact constant-tempo linear map: the midpoint beat
    lands at the midpoint sample, matching the old frac*n_samples formula."""
    m = BeatSampleMap(0.0, 16.0, 48_000)
    assert m.beat_to_sample(0.0) == 0
    assert m.beat_to_sample(16.0) == 48_000
    assert m.beat_to_sample(8.0) == 24_000  # midpoint
    assert m.sample_to_beat(24_000) == pytest.approx(8.0)


def test_beat_sample_map_single_segment_equals_no_segments():
    """A single tempo segment cancels in the rescale — identical to no map."""
    m_none = BeatSampleMap(0.0, 16.0, 48_000)
    m_one = BeatSampleMap(0.0, 16.0, 48_000, [TempoSegment(0.0, 120.0)])
    for beat in (0.0, 4.0, 8.0, 12.0, 16.0):
        assert m_one.beat_to_sample(beat) == m_none.beat_to_sample(beat)


def test_beat_sample_map_variable_tempo_shifts_boundary():
    """First half at 60 bpm, second half at 120 bpm over an 8-beat span.

    At 60 bpm a beat takes twice as long as at 120 bpm, so beats 0..4 occupy
    2/3 of the wall-clock (4*1.0s) and beats 4..8 occupy 1/3 (4*0.5s). The
    beat-4 boundary should therefore land at ~2/3 of the samples, NOT the
    halfway point a constant-tempo map would give.
    """
    n = 60_000
    segs = [TempoSegment(0.0, 60.0), TempoSegment(4.0, 120.0)]
    m = BeatSampleMap(0.0, 8.0, n, segs)
    # raw: [0..4]@60bpm = 4.0s, [4..8]@120bpm = 2.0s, total 6.0s → beat 4 at 4/6.
    assert m.beat_to_sample(4.0) == pytest.approx(n * (4.0 / 6.0), abs=2)
    # A constant-tempo map would have put beat 4 at the halfway sample.
    linear = BeatSampleMap(0.0, 8.0, n)
    assert m.beat_to_sample(4.0) > linear.beat_to_sample(4.0)


def test_beat_sample_map_round_trips():
    segs = [TempoSegment(0.0, 90.0), TempoSegment(6.0, 140.0)]
    m = BeatSampleMap(0.0, 12.0, 50_000, segs)
    for beat in (0.0, 3.0, 6.0, 9.0, 12.0):
        s = m.beat_to_sample(beat)
        assert m.sample_to_beat(s) == pytest.approx(beat, abs=1e-3)


def test_beat_sample_map_explicit_hold_matches_default():
    """An explicit ramp='hold' is identical to the default — both are steps."""
    default = BeatSampleMap(0.0, 8.0, 60_000, [
        TempoSegment(0.0, 60.0), TempoSegment(4.0, 120.0)])
    explicit = BeatSampleMap(0.0, 8.0, 60_000, [
        TempoSegment(0.0, 60.0, "hold"), TempoSegment(4.0, 120.0, "hold")])
    for beat in (0.0, 2.0, 4.0, 6.0, 8.0):
        assert explicit.beat_to_sample(beat) == default.beat_to_sample(beat)


def test_beat_sample_map_linear_ramp_integrates_the_glide():
    """A 60→120 bpm linear ramp over beats [0, 8] is the log integral, not a
    step. Early beats run slow (≈60 bpm) and so eat MORE wall-clock, pushing
    beat 4 PAST the halfway sample a step model would give.

    raw(β) = (60/slope)·ln(bpm(β)/bpm0) with slope = (120-60)/8 = 7.5, so the
    beat-4 fraction is ln(90/60)/ln(120/60) = ln(1.5)/ln(2).
    """
    import math
    n = 100_000
    segs = [TempoSegment(0.0, 60.0, "linear"), TempoSegment(8.0, 120.0)]
    m = BeatSampleMap(0.0, 8.0, n, segs)
    expected = n * math.log(1.5) / math.log(2.0)
    assert m.beat_to_sample(4.0) == pytest.approx(expected, abs=2)
    # A step model (hold) would put beat 4 at the halfway sample — the ramp
    # lands strictly later.
    step = BeatSampleMap(0.0, 8.0, n, [
        TempoSegment(0.0, 60.0), TempoSegment(8.0, 120.0)])
    assert m.beat_to_sample(4.0) > step.beat_to_sample(4.0)
    assert step.beat_to_sample(4.0) == pytest.approx(n / 2, abs=2)


def test_beat_sample_map_linear_ramp_round_trips():
    """beat → sample → beat survives the closed-form inverse across a ramp."""
    segs = [TempoSegment(0.0, 80.0, "linear"), TempoSegment(12.0, 160.0)]
    m = BeatSampleMap(0.0, 12.0, 50_000, segs)
    for beat in (0.0, 2.5, 6.0, 9.5, 12.0):
        assert m.sample_to_beat(m.beat_to_sample(beat)) == pytest.approx(beat, abs=1e-3)


def test_beat_sample_map_linear_ramp_is_monotonic():
    """Sample breakpoints strictly increase across a ramp — the map stays
    invertible (positive bpm → strictly increasing cumulative seconds)."""
    segs = [TempoSegment(0.0, 60.0, "linear"), TempoSegment(16.0, 140.0)]
    m = BeatSampleMap(0.0, 16.0, 64_000, segs)
    samples = [m.beat_to_sample(b) for b in range(0, 17)]
    assert samples == sorted(samples)
    assert all(b < a for b, a in zip(samples, samples[1:]))


def test_beat_sample_map_linear_ramp_boundary_inside_window():
    """A linear ramp whose target point falls strictly inside the captured
    window splits into two intervals — the constant tail after the ramp's end
    is still a step, and the ramp portion is integrated."""
    # Ramp 90→90? No — ramp to the bar-8 point at 100 bpm, then hold to 16.
    segs = [
        TempoSegment(0.0, 90.0, "linear"),
        TempoSegment(8.0, 100.0, "hold"),
    ]
    m = BeatSampleMap(0.0, 16.0, 80_000, segs)
    # Interior breakpoint at beat 8 exists; both halves map monotonically and
    # the whole window covers [0, n].
    assert m.beat_to_sample(0.0) == 0
    assert m.beat_to_sample(16.0) == 80_000
    assert 0 < m.beat_to_sample(8.0) < 80_000
    assert m.sample_to_beat(m.beat_to_sample(8.0)) == pytest.approx(8.0, abs=1e-3)


def test_beat_sample_map_degenerate_span():
    m = BeatSampleMap(8.0, 8.0, 48_000)  # zero-length span
    assert m.degenerate
    assert m.beat_to_sample(8.0) == 0
    assert m.sample_to_beat(0) == 8.0


def test_beat_sample_map_degenerate_empty_audio():
    m = BeatSampleMap(0.0, 16.0, 0)
    assert m.degenerate


def test_intersect_window_uses_beat_map_when_supplied():
    """A variable-tempo map moves the section boundary vs the linear path."""
    n = 60_000
    segs = [TempoSegment(0.0, 60.0), TempoSegment(4.0, 120.0)]
    m = BeatSampleMap(0.0, 8.0, n, segs)
    w = _window("chorus", 4.0, 8.0)
    sl_map = intersect_window(
        w, n_samples=n, capture_start_beat=0.0, capture_stop_beat=8.0, beat_map=m
    )
    sl_linear = intersect_window(
        w, n_samples=n, capture_start_beat=0.0, capture_stop_beat=8.0
    )
    assert sl_map.covered and sl_linear.covered
    # The 120-bpm second half is compressed into fewer samples than linear.
    assert sl_map.start_sample > sl_linear.start_sample
