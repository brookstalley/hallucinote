"""Section-windowed analysis — slice captured audio into named section
windows so the same loudness metrics can be scoped to verse / chorus /
bridge instead of only the full-song aggregate.

``analyze_mix`` stays DB-agnostic, exactly like ``DeclaredReverbSend``:
the MCP handler reads the song's ``sections`` table (named half-open
``[start_bar, end_bar)`` spans), converts each bound to song-absolute
beats via the time-signature map, and passes a list of beat-domain
``SectionWindow`` records here. This module never touches the DB — it
slices audio by beat window and measures it, so synthetic-fixture tests
can drive it without a song DB.

Beat→sample mapping reuses the capture's **constant-tempo linear** map —
the same assumption ``analyze._rebeat_overshoot`` already documents for
overshoot beat positions. Under variable tempo the sample boundaries are
approximate (the bar→beat conversion via the meter map stays exact; only
the beat→sample step is linear). Variable-tempo-accurate windowing is a
follow-on (see ``.prawduct/backlog.md``).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class SectionWindow:
    """One named section as a half-open beat-domain window.

    ``start_beat`` / ``end_beat`` are song-absolute beats (bar 1's
    downbeat == beat 0.0) — the same domain as the capture's
    ``start_at_beat`` / ``stop_at_beat`` and ``MasterOvershoot.start_beat``.
    Half-open ``[start_beat, end_beat)`` mirrors the schema's section span
    convention.

    The MCP handler builds these from ``sections`` rows; callers invoking
    ``analyze_mix`` directly can construct them by hand for fixtures.
    """
    name: str
    start_beat: float
    end_beat: float


@dataclass(frozen=True)
class WindowSlice:
    """Result of intersecting a ``SectionWindow`` with a capture's audio.

    ``start_sample`` / ``end_sample`` are the clamped sample bounds of the
    overlap between the section window and the captured transport span.
    ``covered`` is False when the section falls entirely outside the
    captured window (no overlap) — the caller records a skip rather than
    measuring an empty slice.
    """
    start_sample: int
    end_sample: int
    covered: bool


def intersect_window(
    window: SectionWindow,
    *,
    n_samples: int,
    capture_start_beat: float,
    capture_stop_beat: float,
) -> WindowSlice:
    """Map a beat-domain section window onto sample bounds in the capture.

    Linear beat→sample under the constant-tempo assumption: the captured
    span ``[capture_start_beat, capture_stop_beat)`` maps onto
    ``[0, n_samples)`` proportionally. The section window is clamped to that
    span; if there is no overlap (the section is entirely before the
    capture starts or after it stops), ``covered`` is False.

    A degenerate capture span (``capture_stop_beat <= capture_start_beat``)
    or empty audio yields ``covered=False`` rather than dividing by zero —
    the caller surfaces this as a skip.
    """
    span_beats = capture_stop_beat - capture_start_beat
    if span_beats <= 0 or n_samples <= 0:
        return WindowSlice(0, 0, covered=False)

    def _beat_to_sample(beat: float) -> int:
        frac = (beat - capture_start_beat) / span_beats
        return int(round(frac * n_samples))

    start_sample = _beat_to_sample(window.start_beat)
    end_sample = _beat_to_sample(window.end_beat)
    # Clamp to the captured extent.
    start_sample = max(0, min(start_sample, n_samples))
    end_sample = max(0, min(end_sample, n_samples))
    if end_sample <= start_sample:
        return WindowSlice(start_sample, end_sample, covered=False)
    return WindowSlice(start_sample, end_sample, covered=True)


def slice_audio(audio: np.ndarray, window_slice: WindowSlice) -> np.ndarray:
    """Return the ``[start_sample:end_sample)`` slice of a (n, 2) buffer.

    Assumes ``window_slice.covered`` — callers check that first. Returns a
    view (no copy); loudness math reads it without mutation.
    """
    return audio[window_slice.start_sample:window_slice.end_sample]


__all__ = [
    "SectionWindow",
    "WindowSlice",
    "intersect_window",
    "slice_audio",
]
