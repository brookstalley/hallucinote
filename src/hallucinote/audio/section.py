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

import math
from dataclasses import dataclass
from typing import Sequence

import numpy as np

# Below this per-beat bpm slope the segment is treated as constant tempo: the
# closed-form log integral degenerates to the linear (seconds = beats·60/bpm)
# form as the slope → 0, so we switch before the log/division loses precision.
_EPS_BPM_SLOPE = 1e-9


def _partial_seconds(bpm0: float, slope: float, beats: float) -> float:
    """Wall-clock seconds to advance ``beats`` from a point where the tempo is
    ``bpm0`` and changes by ``slope`` bpm per beat.

    For a linear ramp ``∫ 60/(bpm0 + slope·x) dx`` over ``[0, beats]`` is the
    log term ``(60/slope)·ln(bpm_end/bpm0)``; as ``slope → 0`` this limits to
    the constant-tempo ``60·beats/bpm0``. Only ``ramp='hold'`` (slope 0) and a
    true linear glide are representable, which is exactly the DB's ramp vocab.
    """
    if abs(slope) < _EPS_BPM_SLOPE:
        return 60.0 * beats / bpm0
    return (60.0 / slope) * math.log((bpm0 + slope * beats) / bpm0)


def _partial_beats(bpm0: float, slope: float, seconds: float) -> float:
    """Inverse of :func:`_partial_seconds`: beats advanced in ``seconds`` from a
    point where the tempo is ``bpm0`` and changes by ``slope`` bpm per beat."""
    if abs(slope) < _EPS_BPM_SLOPE:
        return bpm0 * seconds / 60.0
    return (bpm0 / slope) * (math.exp(slope * seconds / 60.0) - 1.0)


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

    ``section_id`` carries the DB ``sections`` row id when the handler built
    the window, so the resulting ``SectionMetrics`` can correlate back to its
    row (AUD-2N6K); it is ``None`` for hand-built fixture windows that have no
    DB identity.
    """
    name: str
    start_beat: float
    end_beat: float
    section_id: str | None = None


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
    """A tempo point at song-absolute beat ``start_beat``, mirroring one DB
    ``tempo_map`` row.

    ``bpm`` is the tempo *at* ``start_beat``. ``ramp`` describes how it reaches
    the next segment's bpm:

    * ``'hold'`` (default) — tempo stays at ``bpm`` until the next segment's
      start (a step). The only exact model before linear-ramp support landed.
    * ``'linear'`` — tempo glides linearly from this ``bpm`` to the next
      segment's ``bpm`` across ``[start_beat, next.start_beat)``. The last
      segment has no successor, so its ``ramp`` is moot (constant to the end of
      the capture).

    Beat-domain, like :class:`SectionWindow` — the MCP handler builds these
    from the DB ``tempo_map`` (each row's ``start_bar`` converted to a beat via
    the meter map, carrying the row's ``ramp``). Constructing them by hand is
    fine for fixtures.
    """
    start_beat: float
    bpm: float
    ramp: str = "hold"


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

    Both ``ramp`` kinds are modelled exactly: a ``'hold'`` segment is a constant
    step, and a ``'linear'`` segment integrates the log-shaped beat→seconds
    curve of a linearly-varying bpm (``∫ 60/bpm(beat) dβ``), so a section
    boundary landing mid-ramp maps to the right sample instead of drifting off a
    step approximation.

    One modelling assumption remains:

    * **The render honored the supplied tempo.** The map shifts boundaries by
      the tempo *it is given*; if a song declares variable tempo but was
      rendered at a single tempo (e.g. the push layer only materializes the
      bar-1 tempo — see ``.prawduct/backlog.md`` non-bar-1-tempo gap), the
      declared changes never appear in the audio and the map can be *less*
      accurate than the constant-tempo linear fallback. The rescale cancels a
      global tempo offset but not this declared-vs-rendered divergence. Pass an
      empty ``tempo_segments`` (the default) when in doubt.
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
            self._mark_degenerate()
            return

        segs = sorted(
            ((float(s.start_beat), float(s.bpm), str(s.ramp)) for s in tempo_segments
             if s.bpm > 0),
            key=lambda p: p[0],
        )
        # Breakpoints: window endpoints plus any tempo change strictly inside.
        # Each resulting interval lies within a single segment, so tempo varies
        # at most linearly across it — exactly what the closed form integrates.
        interior = sorted({
            sb for sb, _, _ in segs if capture_start_beat < sb < capture_stop_beat
        })
        beats = [capture_start_beat, *interior, capture_stop_beat]

        def _seg_index_at(beat: float) -> int:
            """Index of the segment active at ``beat`` (last start ≤ beat), or
            -1 when ``beat`` precedes every segment."""
            idx = -1
            for i, (sb, _, _) in enumerate(segs):
                if sb <= beat:
                    idx = i
                else:
                    break
            return idx

        def _bpm_endpoints(b0: float, b1: float) -> tuple[float, float]:
            """bpm at the two ends of interval ``[b0, b1]`` along the underlying
            segment's tempo line (constant for a hold/last segment, interpolated
            for a linear ramp)."""
            idx = _seg_index_at(0.5 * (b0 + b1))
            if idx < 0:
                return 120.0, 120.0  # before any segment; cancels in the rescale
            sb, bpm, ramp = segs[idx]
            if ramp == "linear" and idx + 1 < len(segs):
                nsb, nbpm, _ = segs[idx + 1]
                if nsb > sb:
                    glide = (nbpm - bpm) / (nsb - sb)
                    return bpm + glide * (b0 - sb), bpm + glide * (b1 - sb)
            return bpm, bpm

        raw = [0.0]
        bpm0s: list[float] = []
        slopes: list[float] = []
        for i in range(1, len(beats)):
            b0, b1 = beats[i - 1], beats[i]
            length = b1 - b0
            bpm0, bpm1 = _bpm_endpoints(b0, b1)
            slope = 0.0 if length <= 0 else (bpm1 - bpm0) / length
            bpm0s.append(bpm0)
            slopes.append(slope)
            raw.append(raw[-1] + _partial_seconds(bpm0, slope, length))
        raw_total = raw[-1]
        if raw_total <= 0:
            self.degenerate = True
            self._mark_degenerate()
            return
        self._beats = np.asarray(beats, dtype=np.float64)
        self._raw = np.asarray(raw, dtype=np.float64)
        self._bpm0s = bpm0s
        self._slopes = slopes
        self._raw_total = raw_total

    def _mark_degenerate(self) -> None:
        """Null out the interpolation state for a degenerate map. The accessors
        all short-circuit on ``self.degenerate`` before touching these, so they
        only need to exist, but resetting them in one place keeps both
        degenerate branches in ``__init__`` consistent."""
        self._beats = self._raw = None
        self._bpm0s = self._slopes = None
        self._raw_total = 0.0

    def beat_to_sample(self, beat: float) -> int:
        """Song-absolute beat → clamped sample index in the capture audio."""
        if self.degenerate:
            return 0
        beat = min(max(beat, self.start_beat), self.stop_beat)
        i = self._interval_for(self._beats, beat)
        raw = self._raw[i] + _partial_seconds(
            self._bpm0s[i], self._slopes[i], beat - self._beats[i],
        )
        s = raw / self._raw_total * self.n_samples
        return int(round(min(max(s, 0.0), float(self.n_samples))))

    def sample_to_beat(self, sample: float) -> float:
        """Sample index in the capture audio → song-absolute beat."""
        if self.degenerate:
            return self.start_beat
        raw = min(max(sample, 0.0), float(self.n_samples)) / self.n_samples * self._raw_total
        i = self._interval_for(self._raw, raw)
        return float(self._beats[i] + _partial_beats(
            self._bpm0s[i], self._slopes[i], raw - self._raw[i],
        ))

    @staticmethod
    def _interval_for(breakpoints: np.ndarray, value: float) -> int:
        """Index of the interval ``[breakpoints[i], breakpoints[i+1]]`` that
        contains ``value`` (clamped to the last interval at the upper edge)."""
        i = int(np.searchsorted(breakpoints, value, side="right")) - 1
        return min(max(i, 0), len(breakpoints) - 2)


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
