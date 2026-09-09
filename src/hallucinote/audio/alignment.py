"""Trim captured surfaces to a common length (AUD-1C7K).

Why this exists
===============

Each surface's ``HallucinoteAnalyzer`` runs its own ``sfrecord~``, and the
recordings *stop* at staggered times — a ~20 ms/surface wall-clock ramp tied to
the render's sequential per-surface disarm (measured directly; it does NOT scale
with the audio buffer size, so it isn't buffer-cycle jitter). So the per-surface
WAVs come out at different **lengths**.

Crucially, their content **starts are sample-aligned**. A known-offset
calibration capture settled this empirically: two identical impulses authored
exactly 2 beats apart were recovered from two separate tracks' captures at
*exactly* 48000 samples apart (0 sample deviation, by both onset detection and
cross-correlation). So the surfaces are already phase-aligned at the head — only
their tails differ.

That makes the fix the simplest possible thing: **trim every surface to the
common (shortest) length**. The result is sample-aligned, equal-length surfaces
— the invariant every cross-surface analysis (masking, timing, attribution)
depends on. No cross-correlation, no shifting: the starts are aligned, so
there's nothing to shift.

This is deliberately NOT a GCC-PHAT / lag-recovery alignment. We measured that
the offset is a pure stop-length ramp; recovering and removing a per-surface
*start* lag would be solving a problem this capture pipeline doesn't have, and
would carry fragilities (narrowband sources, self-reverberant stems) for no
benefit.

**Two different length questions live here.** :func:`trim_to_common_length`
reconciles the surfaces against *each other*; :func:`measure_capture_span`
reconciles the whole capture against the span the manifest DECLARED. A capture
can pass the first and fail the second — every surface equal length, and the set
covering a different stretch of the song than the render asked for.

**Honest limit of this approach.** It corrects LENGTH drift only, and ASSUMES
the heads are sample-aligned — it does NOT verify that. The assumption is
calibration-proven for the current pipeline (δ=0), and :class:`AlignmentReport`
surfaces the length drift it does correct. But a *future* capture whose starts
were mis-aligned yet happened to be equal-length would hit the no-op path and
feed phase-misaligned content downstream with NO visible drift — a silent wrong
answer this trim cannot catch. If the capture mechanism ever changes (e.g. the
AUD-4S8T source-side stop fix alters timing), add a cheap head cross-correlation
guard here: :func:`cross_correlation_peak_lag`, below, is exactly that
measurement, and :data:`PDC_TOLERANCE_SAMPLES` is the residual it must stay
inside.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np

from .io import CaptureSet, Surface
from .section import TempoSegment, declared_span_seconds

# How far a stem's content may sit from the master's before the two are no
# longer usefully called aligned: 64 samples, ~1.3 ms at 48 kHz. That is inside
# one audio buffer at every session size Live offers (128 / 256 / 512), so a
# residual under it is buffer granularity rather than a compensation failure —
# Live's PDC can be sample-accurate but is buffer-granular under some
# conditions. Anything beyond it is a real, audible time offset.
PDC_TOLERANCE_SAMPLES = 64


def cross_correlation_peak_lag(
    stem: np.ndarray,
    master: np.ndarray,
    *,
    max_lag_samples: int | None = None,
) -> int:
    """Sample lag at which ``master`` is best explained by ``stem``.

    Positive lag = master arrives later than stem (the expected PDC case).
    Operates on the mono sum so stereo phase tricks don't bias the peak.
    Both inputs must be stereo float arrays of equal length.

    ``max_lag_samples`` bounds the search to ±that many samples. Unbounded, the
    peak is free to land on a musical coincidence — two different parts sharing
    a downbeat a bar apart correlate strongly at a lag no device chain could
    produce. A caller asking "is this stem time-shifted relative to that one"
    knows the delay range it cares about and says so; a caller measuring a
    known-shared signal (a stem against the master carrying it) leaves it open.
    """
    if stem.shape != master.shape:
        raise ValueError(
            f"stem {stem.shape} and master {master.shape} must match"
        )
    from scipy.signal import correlate, correlation_lags

    stem_mono = stem.mean(axis=1)
    master_mono = master.mean(axis=1)
    # SciPy's FFT-based correlate. mode='full' returns 2N-1 lags; we read
    # the peak and convert its index to a signed lag in samples.
    xcorr = correlate(master_mono, stem_mono, mode="full", method="fft")
    lags = correlation_lags(master_mono.size, stem_mono.size, mode="full")
    magnitude = np.abs(xcorr)
    if max_lag_samples is not None:
        # Mask rather than slice: the lag array stays index-aligned with the
        # correlation, so the recovered lag is still read straight off it.
        magnitude = np.where(np.abs(lags) <= max_lag_samples, magnitude, -np.inf)
        if not np.any(np.isfinite(magnitude)):
            return 0
    return int(lags[int(np.argmax(magnitude))])


@dataclass(frozen=True)
class SurfaceTrim:
    """How one surface was trimmed to the common length."""

    track_id: str
    surface_kind: str
    original_length: int
    trimmed_samples: int  # tail samples dropped to reach the common length


@dataclass(frozen=True)
class AlignmentReport:
    """Audit trail for a :func:`trim_to_common_length` pass.

    Surfaces the capture drift so the correction is visible, not silent — the
    read side (mix-review, the Critic, a human) can see how far apart the
    per-surface recordings finalized and how much tail was dropped to align
    them. ``max_drift_ms`` is the headline number a human cares about.
    """

    method: str
    common_length: int
    sample_rate: int
    max_drift_samples: int
    max_drift_ms: float
    surfaces: tuple[SurfaceTrim, ...] = ()

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "common_length": self.common_length,
            "sample_rate": self.sample_rate,
            "max_drift_samples": self.max_drift_samples,
            "max_drift_ms": self.max_drift_ms,
            "surfaces": [
                {
                    "track_id": s.track_id,
                    "surface_kind": s.surface_kind,
                    "original_length": s.original_length,
                    "trimmed_samples": s.trimmed_samples,
                }
                for s in self.surfaces
            ],
        }

    @property
    def human_summary(self) -> str:
        """One-line, user-facing description of the correction applied.

        Shaped for the mix-review / analysis surface: states the drift and what
        was done about it, and points at the only knob the user controls when
        the drift is large (a lower audio buffer does NOT help — the ramp is
        wall-clock, not buffer-bound — so we don't suggest it)."""
        if self.max_drift_samples == 0:
            return "Capture surfaces were already equal length; no trim needed."
        return (
            f"Capture surfaces finalized up to {self.max_drift_ms:.0f} ms apart "
            f"(their starts are sample-aligned); trimmed all to a common "
            f"{self.common_length} samples so analysis sees aligned, "
            f"equal-length stems."
        )


def trim_to_common_length(
    capture: CaptureSet,
) -> tuple[CaptureSet, AlignmentReport]:
    """Trim every surface to the shortest surface's length.

    Returns a new :class:`CaptureSet` whose master, stems and returns are all
    the common (minimum) length, plus an :class:`AlignmentReport` documenting
    the per-surface trim. A no-op (drift 0) when the surfaces are already equal
    length — so synthetic, equal-length fixtures pass through untouched.
    """
    surfaces = [capture.master, *capture.stems, *capture.returns]
    lengths = [s.audio.shape[0] for s in surfaces]
    common = min(lengths)
    longest = max(lengths)

    trims = tuple(
        SurfaceTrim(
            track_id=s.track_id,
            surface_kind=s.surface_kind,
            original_length=s.audio.shape[0],
            trimmed_samples=s.audio.shape[0] - common,
        )
        for s in surfaces
    )
    aligned = dataclasses.replace(
        capture,
        master=_trim(capture.master, common),
        stems=[_trim(s, common) for s in capture.stems],
        returns=[_trim(r, common) for r in capture.returns],
    )
    report = AlignmentReport(
        method="trim_to_common_length",
        common_length=common,
        sample_rate=capture.sample_rate,
        max_drift_samples=longest - common,
        max_drift_ms=(longest - common) / capture.sample_rate * 1000.0,
        surfaces=trims,
    )
    return aligned, report


def _trim(surface: Surface, n: int) -> Surface:
    if surface.audio.shape[0] == n:
        return surface
    return dataclasses.replace(surface, audio=surface.audio[:n])


# How far the captured audio may run from the span the manifest declares before
# the capture is no longer describing itself. A quarter beat: three real captures
# of the same song were measured (2026-09-09), and the two healthy ones sat inside
# 0.05 beats of their declared span while the defective one ran 1.06 beats long.
# A quarter beat is an order of magnitude clear of both, so this is a bright line
# rather than a tuned threshold, and it stays meaningful if the healthy spread
# doubles.
DEFAULT_SPAN_TOLERANCE_BEATS = 0.25


@dataclass(frozen=True)
class CaptureSpan:
    """Whether the captured audio is as long as the manifest says it is.

    :func:`trim_to_common_length` reconciles the surfaces against *each other*;
    this reconciles the whole capture against what the render *declared*. The two
    are independent failures: the surfaces can agree perfectly among themselves
    and still, together, cover a different stretch of the song than
    ``[start_at_beat, stop_at_beat + ring_out_beats]``.

    ``excess_beats`` is signed — positive means more audio than declared. It is
    a LENGTH statement and nothing more: a capture that armed early and one that
    disarmed late produce the same number, and telling them apart needs the
    authored onsets, which this module does not have.
    """

    declared_beats: float
    declared_seconds: float
    captured_seconds: float
    excess_beats: float
    tolerance_beats: float

    @property
    def within_tolerance(self) -> bool:
        return abs(self.excess_beats) <= self.tolerance_beats

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "declared_beats": self.declared_beats,
            "declared_seconds": self.declared_seconds,
            "captured_seconds": self.captured_seconds,
            "excess_beats": self.excess_beats,
            "tolerance_beats": self.tolerance_beats,
            "within_tolerance": self.within_tolerance,
        }

    @property
    def human_summary(self) -> str:
        """One-line, user-facing description, shaped for the mix-review surface."""
        if self.within_tolerance:
            return (
                f"Captured audio spans the declared "
                f"{self.declared_beats:.0f} beats (within "
                f"{self.tolerance_beats:.2f} beat)."
            )
        direction = "longer than" if self.excess_beats > 0 else "shorter than"
        return (
            f"Captured audio is {abs(self.excess_beats):.2f} beats {direction} "
            f"the {self.declared_beats:.0f} beats the manifest declares. Every "
            f"beat and section window in this report is computed on that "
            f"stretched span, so the numbers are offset by up to that much. "
            f"Whether the extra audio is at the head or the tail is not "
            f"measurable from length alone."
        )


def _declared_tempo_is_constant(
    start_beat: float,
    stop_beat: float,
    tempo_segments: Sequence[TempoSegment],
) -> bool:
    """Does the declared tempo hold one value across ``[start_beat, stop_beat]``?

    Any ramp, or any change inside the span, means no.
    """
    inside = [
        s for s in tempo_segments
        if s.bpm > 0 and s.start_beat < stop_beat
    ]
    if not inside:
        return False
    if any(str(s.ramp) == "linear" for s in inside):
        return False
    # A change strictly inside the span, or differing tempi among the segments
    # that cover it, both mean the span is not one constant tempo.
    if any(start_beat < s.start_beat < stop_beat for s in inside):
        return False
    return len({float(s.bpm) for s in inside}) == 1


def measure_capture_span(
    capture: CaptureSet,
    tempo_segments: Sequence[TempoSegment] = (),
    *,
    tolerance_beats: float = DEFAULT_SPAN_TOLERANCE_BEATS,
) -> tuple[CaptureSpan | None, str | None]:
    """Compare the captured audio's duration against the manifest's declared span.

    Returns ``(span, skip_reason)`` — exactly one is non-``None``. The reason is
    returned rather than swallowed because a check that declines silently is
    indistinguishable from one that passed, which is the defect this whole
    measurement exists to end.

    Measures the MASTER, which after :func:`trim_to_common_length` carries the
    common length. Per-surface lengths must not be used: the returns routinely
    finalize a third of a beat after the master on a perfectly healthy capture
    (the stop-length ramp this module's docstring describes), so a per-surface
    comparison flags every capture ever made.

    **This compares audio against the DECLARED tempo, so it answers only where
    the declared tempo is one constant across the span.** The push layer
    materializes only the bar-1 tempo today (the non-bar-1-tempo gap), so a song
    declaring variable tempo renders at a single tempo and its declared duration
    is not what was played — a mismatch there would say nothing about the
    capture. Declining is self-healing: it stops applying once variable-tempo
    rendering lands, and there is no threshold to revisit.
    """
    stop_beat = capture.stop_at_beat + capture.ring_out_beats
    declared_beats = stop_beat - capture.start_at_beat
    declared_seconds = declared_span_seconds(
        capture.start_at_beat, stop_beat, tempo_segments,
    )
    if declared_seconds is None or declared_seconds <= 0:
        return None, (
            "no usable tempo map was supplied, so the wall-clock duration the "
            "declared beat span SHOULD take is unknown and the captured audio "
            "cannot be checked against it"
        )
    if not _declared_tempo_is_constant(
        capture.start_at_beat, stop_beat, tempo_segments
    ):
        return None, (
            "the song declares a tempo change across the captured span, and the "
            "push layer materializes only the bar-1 tempo, so the declared "
            "duration is not what was rendered — a span comparison here would "
            "measure the push gap, not the capture"
        )

    captured_seconds = capture.master.audio.shape[0] / capture.master.sample_rate
    # Convert the excess to beats at the span's own average rate rather than a
    # nominal bpm, so a variable-tempo song reports an excess in the beats it
    # actually has.
    beats_per_second = declared_beats / declared_seconds
    return CaptureSpan(
        declared_beats=declared_beats,
        declared_seconds=declared_seconds,
        captured_seconds=captured_seconds,
        excess_beats=(captured_seconds - declared_seconds) * beats_per_second,
        tolerance_beats=tolerance_beats,
    ), None


__all__ = [
    "DEFAULT_SPAN_TOLERANCE_BEATS",
    "PDC_TOLERANCE_SAMPLES",
    "AlignmentReport",
    "CaptureSpan",
    "SurfaceTrim",
    "cross_correlation_peak_lag",
    "measure_capture_span",
    "trim_to_common_length",
]
