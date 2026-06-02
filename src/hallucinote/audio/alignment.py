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
— the invariant ``deconvolve_ir`` and every cross-surface analysis (masking,
timing, attribution) depend on. No cross-correlation, no shifting: the starts
are aligned, so there's nothing to shift.

This is deliberately NOT a GCC-PHAT / lag-recovery alignment. We measured that
the offset is a pure stop-length ramp; recovering and removing a per-surface
*start* lag would be solving a problem this capture pipeline doesn't have, and
would carry fragilities (narrowband sources, self-reverberant stems) for no
benefit. The per-surface trim amounts ARE surfaced in :class:`AlignmentReport`
so the drift is visible, not silently assumed — if a future capture ever starts
*mis*-aligned, that shows up as analysis garbage with the drift in plain sight,
not a silent wrong answer.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any

from .io import CaptureSet, Surface


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
    "AlignmentReport",
    "SurfaceTrim",
    "trim_to_common_length",
]
