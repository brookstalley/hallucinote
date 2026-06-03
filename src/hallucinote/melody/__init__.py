"""hallucinote.melody — the line layer (read side first).

Phase 2a ships the SYMBOLIC melody lens (``lens``): a build-time, render-
independent read-side analyzer over an authored monophonic line — the melodic
counterpart to ``theory.lint`` (harmony) and ``performance.lens`` (feel). It
measures the genre-general substrate facts (contour, intervallic proximity,
range/alphabet, harmonic fit) and classifies a line ``active`` / ``static`` /
``insufficient-data`` (the genre-safe read), framed as coaching questions, never a
universal verdict — because there is no universal "good melody" function
(melody-model.md §1).

Phase 2b adds the AUTHORING side (``profile``): a declared :class:`MelodicProfile`
mirroring the proven ``performance.realization.PerformanceProfile`` — read-only
declared intent the lens grades AGAINST (it has NO ``apply_*``; pitch is the
musical idea). Given a profile, the lens emits profile-relative coaching QUESTIONS
on top of the unchanged neutral facts. The within-line motivic-economy reading and
the profile-relative shaped-vs-aimless reading land alongside it (melody-model §4,
§7).

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
from hallucinote.melody.economy import repetition_coverage
from hallucinote.melody.segmentation import (
    per_phrase_contours,
    phrase_boundaries,
    phrase_segments,
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
    ShapedReading,
    analyze_arrangement,
    analyze_melody,
)
from hallucinote.melody.profile import (
    Appetite,
    ContourIntent,
    MelodicProfile,
)

__all__ = [
    # lens (read side)
    "MelodyFinding",
    "MelodicLine",
    "SectionMelodyResult",
    "MelodyReport",
    "SectionMelody",
    "Classification",
    "ShapedReading",
    "analyze_melody",
    "analyze_arrangement",
    # profile (authoring side, phase 2b)
    "MelodicProfile",
    "Appetite",
    "ContourIntent",
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
    # economy (within-line motivic-economy / repetition)
    "repetition_coverage",
    # segmentation (LBDM phrase boundaries + per-phrase contour)
    "phrase_boundaries",
    "phrase_segments",
    "per_phrase_contours",
    # harmony fit
    "HarmonyFit",
    "analyze_harmony_fit",
    "classify_tone",
]
