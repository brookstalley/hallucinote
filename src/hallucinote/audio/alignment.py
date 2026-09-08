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
from typing import Any

import numpy as np

from .io import CaptureSet, Surface

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


__all__ = [
    "PDC_TOLERANCE_SAMPLES",
    "AlignmentReport",
    "SurfaceTrim",
    "cross_correlation_peak_lag",
    "trim_to_common_length",
]
