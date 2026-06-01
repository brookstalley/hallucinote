"""melody.intervals — the step↔leap proximity profile, gap-fill, alphabet, range.

The symbolic feed is EXACT (it reads authored pitches), so these assert precise
values. They cover the step/leap/unison boundary, the ``None`` cases that keep a
non-moving line honest (proximity is undefined for a line that does not travel),
post-skip reversal (incl. the leap-into-a-repeat = not a gap-fill subtlety), the
register-blind alphabet, and ambitus.
"""
from __future__ import annotations

from hallucinote.melody.intervals import (
    STEP_MAX_SEMITONES,
    ambitus,
    melodic_intervals,
    pitch_alphabet_size,
    post_skip_reversal_rate,
    step_fraction,
    step_leap_unison_counts,
)


def test_melodic_intervals_are_signed_deltas():
    assert melodic_intervals([60, 64, 62, 62, 55]) == [4, -2, 0, -7]
    assert melodic_intervals([60]) == []
    assert melodic_intervals([]) == []


def test_step_boundary_is_a_major_second():
    assert STEP_MAX_SEMITONES == 2
    # 4 = M3 (leap), -2 = M2 (step), 0 = unison, -7 = P5 (leap)
    assert step_leap_unison_counts([4, -2, 0, -7]) == (1, 2, 1)
    # exactly 2 semitones is still a step; 3 is the first leap
    assert step_leap_unison_counts([2, -2, 3, -3]) == (2, 2, 0)


def test_step_fraction_over_moving_intervals_only():
    # 1 step / (1 step + 2 leaps) — the unison is excluded
    assert step_fraction([4, -2, 0, -7]) == 1 / 3
    # a line that never moves has no proximity to report
    assert step_fraction([0, 0]) is None
    assert step_fraction([]) is None


def test_post_skip_reversal_gap_fill():
    # leap +4 then step -2 (opposite direction) = a filled gap
    assert post_skip_reversal_rate([4, -2]) == 1.0
    # leap +5 then +3 (same direction) = not filled
    assert post_skip_reversal_rate([5, 3]) == 0.0
    # a leap into a REPEATED note (successor 0) is not a gap-fill
    assert post_skip_reversal_rate([5, 0, -1]) == 0.0
    # no leap with a successor -> undefined, not zero
    assert post_skip_reversal_rate([2, -2]) is None
    assert post_skip_reversal_rate([5]) is None


def test_pitch_alphabet_is_register_blind():
    # E4 (64) and E5 (76) are the same alphabet symbol (pc 4)
    assert pitch_alphabet_size([64, 76, 64]) == 1
    assert pitch_alphabet_size([60, 64, 62, 62, 55]) == 4  # C E D D G -> {C,E,D,G}


def test_ambitus_is_total_range():
    assert ambitus([60, 64, 62, 62, 55]) == 9
    assert ambitus([60]) == 0
    assert ambitus([]) == 0
