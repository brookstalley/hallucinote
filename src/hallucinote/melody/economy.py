"""hallucinote.melody.economy — the within-line motivic-economy / repetition reading.

A line's *intrinsic* repetition number: how much of the line is built from a
repeated multi-interval cell vs through-composed. This is the read-side fact the
declared ``repetition_appetite`` grades against (melody-model.md §4, §7; the
both-sides pairing), and the within-line half of the boundary with ARR-9K4T (which
owns cross-instrument / arrangement-level recurrence — §6; no shared code).

**The cheap proxy, with the heavyweight theory named** — the lens's established
honesty pattern (model §7: IDyOM is the theory, n-gram is the proxy). The proxy
here is the fraction of the line covered by its most-repeated multi-interval n-gram
over the INTERVAL sequence. Named heavyweight theory, NOT shipped: **COSIATEC /
SIATECCompress** (Meredith — maximal translatable patterns by compression, O(n²),
over-engineered for a short hook) grounded in **Kolmogorov complexity + the
perceptual simplicity principle** (research C5/C6). The n-gram self-similarity ratio
is simpler and more inspectable, and is sufficient for grading a declared appetite.

**Temperley-shaped** (research C4, the decisive design fact — what real repetition
looks like):
  * **interval-based**, not absolute pitch — a TRANSPOSED repeat still counts
    (Temperley: long-distance repeats keep scale-degree / interval identity).
  * **multi-interval** (n-gram length >= 2 intervals) — a single repeated interval
    (a run of equal steps) does NOT inflate the number; a real motivic cell is two
    or more intervals.

**The C7 null, recorded (research C7 — kill upheld on the primary source): there is
NO "make it catchier" lever here.** Motivic-rarity/repetition does NOT predict
memorability (m-type repetition features lost to global contour + tempo). The number
is a profile-relative DESCRIPTIVE fact graded against the declared appetite — NEVER
"more/less repetition => catchier", never "economical = good" (research C4: intrinsic
compression is perceptually validated only PAIRWISE, never as a single-line score).

Stdlib only; it reports, it never edits a note.
"""
from __future__ import annotations

from collections import Counter
from typing import Sequence

from hallucinote.melody.intervals import melodic_intervals

# A motivic cell is at least this many INTERVALS (>= 3 pitches) — the multi-interval
# requirement (research C4): a single repeated interval is not a cell and must not
# inflate the number.
_MIN_GRAM_INTERVALS = 2


def repetition_coverage(pitches: Sequence[int]) -> float | None:
    """The within-line repetition number: the fraction (0..1) of the line's interval
    sequence covered by its single most-repeated multi-interval n-gram.

    Over the INTERVAL sequence (transposition-invariant), for each n-gram length
    ``L >= _MIN_GRAM_INTERVALS`` find the most-frequent interval-n-gram of that
    length; its coverage is ``occurrences * L`` (capped at the interval count, since
    occurrences may overlap). The number is the max coverage fraction across all
    ``L``. A line that repeats a 3-interval cell three times scores high; a
    through-composed line scores near 0; a line of equal steps scores 0 (single
    repeated interval, ``L = 1``, is excluded by ``_MIN_GRAM_INTERVALS``).

    ``None`` when the line is too short for even one multi-interval cell to repeat
    (fewer than ``2 * _MIN_GRAM_INTERVALS`` intervals) — the number is undefined,
    not zero (the ``None``-safe discipline the lens uses throughout).
    """
    intervals = melodic_intervals([int(p) for p in pitches])
    n = len(intervals)
    if n < 2 * _MIN_GRAM_INTERVALS:
        return None

    best_coverage = 0
    max_len = n // 2  # a cell must repeat at least twice to "cover" anything
    for length in range(_MIN_GRAM_INTERVALS, max_len + 1):
        grams = Counter(
            tuple(intervals[i:i + length])
            for i in range(n - length + 1)
            # A "cell" must contain >= 2 DISTINCT intervals (research C4): a run of
            # equal intervals (e.g. a chromatic/whole-tone climb) tiles into a
            # repeated n-gram but is a SINGLE repeated interval, not a motif — it
            # must not inflate the number.
            if len(set(intervals[i:i + length])) >= 2
        )
        if not grams:
            continue
        gram, count = grams.most_common(1)[0]
        if count < 2:
            continue  # not actually repeated at this length
        coverage = min(count * length, n)
        if coverage > best_coverage:
            best_coverage = coverage

    return best_coverage / n
