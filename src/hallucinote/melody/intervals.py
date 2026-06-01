"""hallucinote.melody.intervals — interval + pitch-set arithmetic for a line.

Pure pitch math over a monophonic melodic line's onset-ordered pitch sequence —
the genre-general substrate facts the research finds cross-culturally robust
(melody-model.md §3.6, §3.4):

  * the **step↔leap profile** — small intervals (a whole tone or less) vs leaps
    (a 3rd or wider). Small-interval dominance ("pitch proximity") is the single
    most robust cross-cultural melodic statistic (Savage et al. 2015), but it is a
    *tendency, not a rule* — a leap-driven idiom (a bugle call, an angular metal
    lead) is entirely valid, so this is REPORTED, never enforced.
  * **post-skip reversal** (gap-fill) — the tendency for a leap to be followed by a
    step in the OPPOSITE direction (Narmour's registral return; Schellenberg's
    reversal factor — melody-model.md §3.4).
  * **pitch-alphabet size** — the count of distinct pitch CLASSES used (the
    ≤7-scale-degree tendency — §3.6).
  * **ambitus** — the line's total range in semitones.

Stdlib only; it reports, it never edits a note. Magnitudes are *facts*, never
verdicts — the melody-model thesis (§1) is that "good" is profile-relative, not a
universal threshold, so nothing here passes or fails a line.
"""
from __future__ import annotations

from typing import Sequence

# A "step" is a major 2nd or smaller (≤ 2 semitones); ≥ 3 semitones (a minor 3rd)
# is a "leap"/"skip". Standard music-theory boundary; shared with ``harmony_fit``'s
# stepwise-resolution test so the whole layer speaks one definition of "by step".
STEP_MAX_SEMITONES = 2


def melodic_intervals(pitches: Sequence[int]) -> list[int]:
    """Signed semitone intervals between consecutive pitches (positive = upward)."""
    return [int(pitches[i + 1]) - int(pitches[i]) for i in range(len(pitches) - 1)]


def step_leap_unison_counts(intervals: Sequence[int]) -> tuple[int, int, int]:
    """``(#steps, #leaps, #unisons)``. step = 1–2 semitones; leap ≥ 3; unison = 0
    (a repeated note — motion neither by step nor leap)."""
    steps = leaps = unisons = 0
    for iv in intervals:
        a = abs(int(iv))
        if a == 0:
            unisons += 1
        elif a <= STEP_MAX_SEMITONES:
            steps += 1
        else:
            leaps += 1
    return steps, leaps, unisons


def step_fraction(intervals: Sequence[int]) -> float | None:
    """``steps / (steps + leaps)`` over the MOVING intervals (unisons excluded — a
    repeated note is not motion). ``None`` when the line never moves (all unisons,
    or a single note) — proximity is undefined for a line that does not travel."""
    steps, leaps, _ = step_leap_unison_counts(intervals)
    moving = steps + leaps
    return (steps / moving) if moving else None


def post_skip_reversal_rate(intervals: Sequence[int]) -> float | None:
    """Of every leap (``|iv| ≥ 3``) that HAS a following interval, the fraction
    whose successor moves in the OPPOSITE direction (gap-fill / registral return —
    §3.4). ``None`` when there is no leap with a successor (the metric is undefined,
    not zero)."""
    eligible = reversals = 0
    for i in range(len(intervals) - 1):
        if abs(int(intervals[i])) > STEP_MAX_SEMITONES:  # a leap
            eligible += 1
            nxt = int(intervals[i + 1])
            # opposite direction: successor is nonzero and its sign differs
            if nxt != 0 and (nxt > 0) != (int(intervals[i]) > 0):
                reversals += 1
    return (reversals / eligible) if eligible else None


def pitch_alphabet_size(pitches: Sequence[int]) -> int:
    """Distinct pitch CLASSES (0–11) the line uses — the ≤7-degree tendency (§3.6).
    Register-blind on purpose: E4 and E5 are the same alphabet symbol."""
    return len({int(p) % 12 for p in pitches})


def ambitus(pitches: Sequence[int]) -> int:
    """The line's total range in semitones (``max − min``); 0 for a single note."""
    if not pitches:
        return 0
    ps = [int(p) for p in pitches]
    return max(ps) - min(ps)
