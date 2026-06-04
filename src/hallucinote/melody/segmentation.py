"""hallucinote.melody.segmentation — LBDM phrase segmentation + per-phrase contour.

A line's contour is a PHRASE-level shape, not a whole-section one (Huron's melodic
arch is a phrase tendency — research C8b). On a looping hook the whole-section
contour FLATTENS to ``level`` (the per-cycle ``descending`` / ``valley`` shape is
masked) — the friction the Chunk-4 calibration surfaced on sun-zone-done's two real
hooks (build-plan DR-3). This module splits the line into phrases and recomputes the
existing contour facts PER PHRASE, locating the shape where it actually lives. It
adds no NEW measurable — it relocates ``contour.contour_shape`` / ``apex`` to the
phrase unit (research C8b: "the arch is a phrase-level tendency").

**LBDM — the cheap, deterministic, corpus-free segmenter** (Cambouropoulos, ICMC
2001; research C2). A purely-LOCAL boundary detector over the pitch-interval / IOI /
rest sequences: a **change rule** (boundary strength rises with the degree of change
between consecutive parametric values) plus a **proximity rule** (larger intervals
carry more boundary weight), combined across the three parameters, normalized, with
local peaks above a weighted-mean threshold marking phrase boundaries. No training,
no corpus — it fits the stdlib-only, render-free core exactly as ``intervals`` does.

**Named heavyweight theory, NOT shipped** (the lens's honesty pattern — model §7):
**IDyOM / Grouper** (the statistical / Temperley segmenters that beat LBDM slightly
in the canonical evaluation — research C1/C3, hybrid mean F1 ~0.66) need a trained
corpus + an ML stack. LBDM is the right cheap proxy; IDyOM is named as the theory.

Stdlib only; it reports, it never edits a note.
"""
from __future__ import annotations

from typing import Any, Sequence

from hallucinote.melody.contour import ContourShape, apex, contour_shape

NoteDict = dict[str, Any]

# Cambouropoulos's parameter weights (LBDM combines pitch-interval, IOI, and rest
# boundary strengths). The original weighting emphasizes IOI; pitch + rest share the
# remainder. These are the published LBDM weights, not a tuned parameter.
_W_PITCH = 0.25
_W_IOI = 0.50
_W_REST = 0.25

# A peak in the combined boundary-strength profile marks a phrase boundary when it
# exceeds the mean strength times this factor (the threshold-relative-to-mean rule).
# Cambouropoulos uses a threshold proportional to the profile; this k is the
# documented "above the weighted mean" peak-picking factor.
_BOUNDARY_THRESHOLD_K = 1.0

# Below this many notes a line is one phrase — too short to segment meaningfully
# (mirrors contour's _MIN_SHAPE_NOTES doubled: two phrases need >= 2 shapes' worth).
_MIN_NOTES_TO_SEGMENT = 6


def _degree_of_change(a: float, b: float) -> float:
    """The LBDM change-rule degree of change between two consecutive parametric
    values: ``|a - b| / (|a| + |b|)`` in [0, 1], and 0 when both are 0 (no change
    between two identical / absent values)."""
    denom = abs(a) + abs(b)
    if denom == 0.0:
        return 0.0
    return abs(a - b) / denom


def _boundary_strengths(values: Sequence[float]) -> list[float]:
    """LBDM boundary strength for each TRANSITION between consecutive notes, for one
    parameter sequence ``values`` (one value per transition — a pitch interval, IOI,
    or rest). Strength at transition ``i`` = ``values[i] * (change-to-left +
    change-to-right)`` — the change rule scaled by the proximity rule (the value's
    own magnitude). Returns one strength per transition."""
    n = len(values)
    if n == 0:
        return []
    strengths: list[float] = []
    for i in range(n):
        left = _degree_of_change(values[i - 1], values[i]) if i > 0 else 0.0
        right = _degree_of_change(values[i], values[i + 1]) if i < n - 1 else 0.0
        strengths.append(abs(values[i]) * (left + right))
    return strengths


def _normalized(values: Sequence[float]) -> list[float]:
    """Scale to [0, 1] by the max (0 if all-zero) — LBDM normalizes each parameter
    profile before the weighted combination so no parameter's raw units dominate."""
    hi = max(values) if values else 0.0
    if hi <= 0.0:
        return [0.0] * len(values)
    return [v / hi for v in values]


def phrase_boundaries(notes: Sequence[NoteDict]) -> list[int]:
    """LBDM phrase boundaries as note INDICES that START a new phrase (always
    includes 0). A boundary sits AFTER a transition whose combined, normalized
    boundary strength is a local peak above the weighted-mean threshold.

    Inputs per transition (note ``i`` -> ``i+1``): pitch interval (semitones), IOI
    (onset spacing, beats), and rest (gap from note ``i``'s offset to note ``i+1``'s
    onset, clamped at 0). Pure arithmetic over the note dicts — no corpus, no audio.
    Too-short lines return ``[0]`` (one phrase).
    """
    seq = sorted(
        ((float(n["start_beats"]), int(n["pitch"]), float(n.get("duration_beats", 0.0)))
         for n in notes),
        key=lambda s: s[0],
    )
    n = len(seq)
    if n < _MIN_NOTES_TO_SEGMENT:
        return [0]

    pitch_iv: list[float] = []
    ioi: list[float] = []
    rest: list[float] = []
    for i in range(n - 1):
        start_i, pitch_i, dur_i = seq[i]
        start_j, pitch_j, _dur_j = seq[i + 1]
        pitch_iv.append(float(pitch_j - pitch_i))
        ioi.append(start_j - start_i)
        rest.append(max(0.0, start_j - (start_i + dur_i)))

    sp = _normalized(_boundary_strengths(pitch_iv))
    si = _normalized(_boundary_strengths(ioi))
    sr = _normalized(_boundary_strengths(rest))
    combined = [
        _W_PITCH * sp[i] + _W_IOI * si[i] + _W_REST * sr[i]
        for i in range(n - 1)
    ]

    positive = [c for c in combined if c > 0.0]
    if not positive:
        return [0]
    threshold = (sum(positive) / len(positive)) * _BOUNDARY_THRESHOLD_K

    boundaries = [0]
    for i in range(n - 1):
        c = combined[i]
        if c <= threshold:
            continue
        # local peak: strictly greater than both neighbours (a sustained ridge is
        # one boundary, not several). The boundary STARTS the next phrase (i+1).
        left_ok = i == 0 or combined[i - 1] < c
        right_ok = i == n - 2 or combined[i + 1] <= c
        if left_ok and right_ok and (i + 1) not in boundaries:
            boundaries.append(i + 1)
    return boundaries


def phrase_segments(notes: Sequence[NoteDict]) -> list[list[NoteDict]]:
    """Split ``notes`` into per-phrase note lists at the LBDM boundaries, onset-
    sorted within each phrase. A line with no internal boundary is a single phrase."""
    ordered = sorted(notes, key=lambda n: float(n["start_beats"]))
    bounds = phrase_boundaries(ordered)
    bounds_set = set(bounds)
    segments: list[list[NoteDict]] = []
    current: list[NoteDict] = []
    for idx, note in enumerate(ordered):
        if idx in bounds_set and current:
            segments.append(current)
            current = []
        current.append(note)
    if current:
        segments.append(current)
    return segments


def per_phrase_contours(
    notes: Sequence[NoteDict],
) -> list[tuple[ContourShape, int | None, float | None]]:
    """Per-LBDM-phrase ``(contour_shape, apex_pitch, apex_position)`` — the existing
    contour facts recomputed at the PHRASE unit (research C8b). This is where the
    melodic arch actually lives: a looping hook reads ``level`` whole-section but each
    phrase keeps its real shape. ``apex_*`` is ``None`` for an empty phrase."""
    out: list[tuple[ContourShape, int | None, float | None]] = []
    for seg in phrase_segments(notes):
        pitches = [int(n["pitch"]) for n in sorted(seg, key=lambda n: float(n["start_beats"]))]
        if pitches:
            ap_pitch, ap_pos = apex(pitches)
        else:
            ap_pitch, ap_pos = None, None
        out.append((contour_shape(pitches), ap_pitch, ap_pos))
    return out
