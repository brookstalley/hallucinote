"""hallucinote.melody — the line layer (read side first).

Phase 2a ships the SYMBOLIC melody lens (``lens``): a build-time, render-
independent read-side analyzer over an authored monophonic line — the melodic
counterpart to ``theory.lint`` (harmony) and ``performance.lens`` (feel). It
measures the genre-general substrate facts (contour, intervallic proximity,
range/alphabet, harmonic fit) and classifies a line ``active`` / ``static`` /
``insufficient-data`` (the genre-safe read), framed as coaching questions, never a
universal verdict — because there is no universal "good melody" function
(melody-model.md §1). The shaped-vs-aimless verdict (profile-relative), the
declared melodic-profile authoring surface + learn-back, and the motivic-economy
reading are friction-driven follow-ons.

See ``.prawduct/artifacts/melody-model.md``.
"""
from __future__ import annotations

from hallucinote.melody.contour import (
    ContourShape,
    apex,
    contour_shape,
    direction_changes,
    gradient_stdev,
)
from hallucinote.melody.harmony_fit import HarmonyFit, analyze_harmony_fit, classify_tone
from hallucinote.melody.intervals import (
    ambitus,
    melodic_intervals,
    pitch_alphabet_size,
    post_skip_reversal_rate,
    step_fraction,
    step_leap_unison_counts,
)
from hallucinote.melody.lens import (
    Classification,
    MelodicLine,
    MelodyFinding,
    MelodyReport,
    SectionMelody,
    SectionMelodyResult,
    analyze_arrangement,
    analyze_melody,
)

__all__ = [
    # lens (read side)
    "MelodyFinding",
    "MelodicLine",
    "SectionMelodyResult",
    "MelodyReport",
    "SectionMelody",
    "Classification",
    "analyze_melody",
    "analyze_arrangement",
    # intervals
    "melodic_intervals",
    "step_leap_unison_counts",
    "step_fraction",
    "post_skip_reversal_rate",
    "pitch_alphabet_size",
    "ambitus",
    # contour
    "ContourShape",
    "apex",
    "contour_shape",
    "direction_changes",
    "gradient_stdev",
    # harmony fit
    "HarmonyFit",
    "analyze_harmony_fit",
    "classify_tone",
]
