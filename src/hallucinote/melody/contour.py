"""hallucinote.melody.contour — contour shape, climax, and variability for a line.

Contour is melody's OWN dimension (melody-model.md §2) — the up/down shape neither
harmony nor feel carries. The research (Cornelissen et al.; §3.7) is decisive that
melodic contour does NOT cluster into discrete categorical types, so the coarse
``shape`` label here is a REPORTED summary of a continuous quantity — never a
categorical claim about the line and never a target to hit. What it carries:

  * **apex** (climax) — the highest pitch and its normalized position (0..1) along
    the line. A single focal high point is a near-universal shaping device; its
    PLACEMENT is a free authored choice (early, golden-section, or a final lift).
  * **shape** — a coarse arch / ascending / descending / valley / level summary
    from the first/middle/last thirds' mean pitch — a continuous central-tendency
    read, deliberately NOT an Adams/Huron discrete typology (§3.7). The canonical
    "arch" is itself style-specific (Chinese folksong averages descend), so the
    label is descriptive, not normative.
  * **variability** — the direction-change count and the signed-interval stdev: the
    steep-vs-flat gradient that tracks melodic recognition (Müllensiefen & Halpern;
    §3.B2 — flat contours read as forgettable). REPORTED as a fact, genre-relative.

Stdlib only; it reports, it never edits a note.
"""
from __future__ import annotations

import statistics
from typing import Literal, Sequence

ContourShape = Literal[
    "ascending", "descending", "arch", "valley", "level", "insufficient-data"
]

# Two thirds-means within this many semitones read as "the same height" — keeps a
# wobbly-but-flat line from being mislabeled an arch/valley. A whole tone.
_LEVEL_TOLERANCE = 2.0

# A coarse shape needs at least this many notes to be meaningful (three thirds).
_MIN_SHAPE_NOTES = 3


def apex(pitches: Sequence[int]) -> tuple[int, float]:
    """``(highest pitch, normalized position 0..1)`` of the FIRST time the line
    reaches its peak. Position is ``index / (n − 1)``; a single-note line is
    ``(pitch, 0.0)``. Reports where the line crests — early, central, or a late
    lift — without judging which is right."""
    ps = [int(p) for p in pitches]
    if not ps:
        raise ValueError("apex of an empty line")
    if len(ps) == 1:
        return ps[0], 0.0
    peak = max(ps)
    idx = ps.index(peak)
    return peak, idx / (len(ps) - 1)


def direction_changes(intervals: Sequence[int]) -> int:
    """Count of sign flips in the moving-interval sequence (unisons skipped) — how
    many times the line turns around. A monotone climb is 0; a zigzag is high."""
    last_sign = 0
    changes = 0
    for iv in intervals:
        s = (iv > 0) - (iv < 0)  # -1 / 0 / +1
        if s == 0:
            continue
        if last_sign != 0 and s != last_sign:
            changes += 1
        last_sign = s
    return changes


def gradient_stdev(intervals: Sequence[int]) -> float:
    """Population stdev of the SIGNED intervals — a steep/varied line scores high,
    a flat/static line near 0 (§3.B2). 0.0 for fewer than two intervals."""
    if len(intervals) < 2:
        return 0.0
    return statistics.pstdev(float(iv) for iv in intervals)


def _third_means(pitches: Sequence[int]) -> tuple[float, float, float]:
    ps = [float(p) for p in pitches]
    n = len(ps)
    lo, hi = n // 3, 2 * n // 3
    return (
        statistics.fmean(ps[:lo] or ps[:1]),
        statistics.fmean(ps[lo:hi] or ps[lo:lo + 1]),
        statistics.fmean(ps[hi:] or ps[-1:]),
    )


def contour_shape(pitches: Sequence[int]) -> ContourShape:
    """A COARSE shape summary from the first/middle/last thirds' mean pitch — a
    descriptive read of a continuous quantity (§3.7), never a categorical verdict.

    ``level`` when all three thirds sit within ``_LEVEL_TOLERANCE`` (no net shape);
    ``arch``/``valley`` when the middle is clearly higher/lower than both ends;
    else ``ascending``/``descending`` by the end-vs-start direction.
    """
    if len(pitches) < _MIN_SHAPE_NOTES:
        return "insufficient-data"
    start, mid, end = _third_means(pitches)
    if max(start, mid, end) - min(start, mid, end) <= _LEVEL_TOLERANCE:
        return "level"
    tol = _LEVEL_TOLERANCE
    if mid > start + tol and mid > end + tol:
        return "arch"
    if mid < start - tol and mid < end - tol:
        return "valley"
    return "ascending" if end > start else "descending"
