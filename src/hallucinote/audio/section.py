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

Beat↔sample mapping goes through :class:`BeatSampleMap`. When the caller
supplies a beat-domain tempo map it is variable-tempo accurate (each
constant-tempo segment maps beats→samples at its own rate); with a single
tempo or none it degenerates EXACTLY to the constant-tempo linear map. The
bar→beat conversion via the meter map stays exact upstream (the handler's
job); this module only turns beats into sample bounds.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

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


@dataclass(frozen=True)
class TempoSegment:
    """A constant-tempo span starting at song-absolute beat ``start_beat``.

    ``bpm`` holds from ``start_beat`` until the next segment's start (or the
    end of the capture). Beat-domain, like :class:`SectionWindow` — the MCP
    handler builds these from the DB ``tempo_map`` (each row's ``start_bar``
    converted to a beat via the meter map). Constructing them by hand is fine
    for fixtures.
    """
    start_beat: float
    bpm: float


class BeatSampleMap:
    """Monotonic piecewise-linear beat↔sample map over a captured window.

    Maps the captured span ``[capture_start_beat, capture_stop_beat]`` onto
    ``[0, n_samples]``. Variable-tempo accurate: it integrates seconds-per-beat
    across the supplied ``tempo_segments`` to get the relative SHAPE of the
    beat→time curve, then RESCALES the whole curve so the span still covers the
    real audio length. Rescaling means a global tempo offset between the DB
    ``tempo_map`` and what the render actually played can't shift boundaries —
    only *relative* tempo changes move them. With a single segment (or none)
    the per-segment rate cancels in the rescale, so this degenerates to the
    exact constant-tempo linear map (``frac * n_samples``).

    Works directly in samples (no sample-rate needed): sample breakpoints are
    ``raw_cumulative_seconds / raw_total_seconds * n_samples``.

    Two modelling assumptions:

    * **The render honored the supplied tempo.** The map shifts boundaries by
      the tempo *it is given*; if a song declares variable tempo but was
      rendered at a single tempo (e.g. the push layer only materializes the
      bar-1 tempo — see ``.prawduct/backlog.md`` non-bar-1-tempo gap), the
      declared changes never appear in the audio and the map can be *less*
      accurate than the constant-tempo linear fallback. The rescale cancels a
      global tempo offset but not this declared-vs-rendered divergence. Pass an
      empty ``tempo_segments`` (the default) when in doubt.
    * **Each segment is constant tempo (step).** A DB ``tempo_map`` row's
      ``ramp='linear'`` (tempo glides to the next point) is approximated as a
      step at the segment's own bpm; only ``ramp='hold'`` is modelled exactly.
    """

    def __init__(
        self,
        capture_start_beat: float,
        capture_stop_beat: float,
        n_samples: int,
        tempo_segments: "Sequence[TempoSegment]" = (),
    ) -> None:
        self.start_beat = capture_start_beat
        self.stop_beat = capture_stop_beat
        self.n_samples = n_samples
        span = capture_stop_beat - capture_start_beat
        self.degenerate = span <= 0 or n_samples <= 0
        if self.degenerate:
            self._beats = self._samples = None
            return

        segs = sorted(
            ((float(s.start_beat), float(s.bpm)) for s in tempo_segments if s.bpm > 0),
            key=lambda p: p[0],
        )
        # Breakpoints: window endpoints plus any tempo change strictly inside.
        interior = sorted({
            sb for sb, _ in segs if capture_start_beat < sb < capture_stop_beat
        })
        beats = [capture_start_beat, *interior, capture_stop_beat]

        def _bpm_at(beat: float) -> float:
            active = 120.0  # any positive default — cancels in the rescale
            for sb, bpm in segs:
                if sb <= beat:
                    active = bpm
                else:
                    break
            return active

        raw = [0.0]
        for i in range(1, len(beats)):
            b0, b1 = beats[i - 1], beats[i]
            # Breakpoints sit on segment boundaries, so bpm is constant across
            # [b0, b1] and equals the segment active at b0.
            raw.append(raw[-1] + (b1 - b0) * 60.0 / _bpm_at(b0))
        raw_total = raw[-1]
        if raw_total <= 0:
            self.degenerate = True
            self._beats = self._samples = None
            return
        self._beats = np.asarray(beats, dtype=np.float64)
        self._samples = np.asarray(
            [r / raw_total * n_samples for r in raw], dtype=np.float64
        )

    def beat_to_sample(self, beat: float) -> int:
        """Song-absolute beat → clamped sample index in the capture audio."""
        if self.degenerate:
            return 0
        s = float(np.interp(beat, self._beats, self._samples))
        return int(round(min(max(s, 0.0), float(self.n_samples))))

    def sample_to_beat(self, sample: float) -> float:
        """Sample index in the capture audio → song-absolute beat."""
        if self.degenerate:
            return self.start_beat
        return float(np.interp(sample, self._samples, self._beats))


def intersect_window(
    window: SectionWindow,
    *,
    n_samples: int,
    capture_start_beat: float,
    capture_stop_beat: float,
    beat_map: "BeatSampleMap | None" = None,
) -> WindowSlice:
    """Map a beat-domain section window onto sample bounds in the capture.

    The captured span ``[capture_start_beat, capture_stop_beat)`` maps onto
    ``[0, n_samples)``; the section window is clamped to that span. If there is
    no overlap (the section is entirely before the capture starts or after it
    stops), ``covered`` is False.

    ``beat_map`` (a :class:`BeatSampleMap`) makes the beat→sample step
    variable-tempo accurate; when omitted, the mapping is the constant-tempo
    linear proportion — which is exactly what a single-tempo ``BeatSampleMap``
    would produce, so the two paths agree for constant tempo.

    A degenerate capture span (``capture_stop_beat <= capture_start_beat``)
    or empty audio yields ``covered=False`` rather than dividing by zero —
    the caller surfaces this as a skip.
    """
    span_beats = capture_stop_beat - capture_start_beat
    if span_beats <= 0 or n_samples <= 0:
        return WindowSlice(0, 0, covered=False)

    if beat_map is not None and not beat_map.degenerate:
        _beat_to_sample = beat_map.beat_to_sample
    else:
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
    "TempoSegment",
    "BeatSampleMap",
    "intersect_window",
    "slice_audio",
]
