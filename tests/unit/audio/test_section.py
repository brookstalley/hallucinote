"""Beat-domain → sample-domain windowing for section-scoped analysis.

These tests pin the pure geometry (``intersect_window`` / ``slice_audio``)
independently of the loudness math: given a capture's transport span and a
section's beat window, which samples are inside, and what happens at the
edges (clamping, no-overlap, degenerate spans).
"""
from __future__ import annotations

import numpy as np

from hallucinote.audio.section import (
    SectionWindow,
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
