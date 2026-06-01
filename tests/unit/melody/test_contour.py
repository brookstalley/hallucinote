"""melody.contour — apex, direction-change / gradient variability, coarse shape.

Contour is melody's OWN dimension. The coarse ``shape`` label is a continuous-
summary read (not a discrete typology — §3.7), so the tests pin the thirds-mean
logic for each summary (level / arch / valley / ascending / descending) and the
apex / variability primitives.
"""
from __future__ import annotations

from hallucinote.melody.contour import (
    apex,
    contour_shape,
    direction_changes,
    gradient_stdev,
)


def test_apex_is_peak_and_first_occurrence_position():
    assert apex([60, 67, 64]) == (67, 0.5)       # peak mid-line
    assert apex([67, 60, 64]) == (67, 0.0)       # peak at the start
    assert apex([60, 64, 70]) == (70, 1.0)       # peak at the end
    assert apex([60]) == (60, 0.0)               # single note


def test_direction_changes_counts_turns_skipping_unisons():
    assert direction_changes([2, 2, -1, -1]) == 1     # up then down
    assert direction_changes([2, -2, 2, -2]) == 3     # zigzag
    assert direction_changes([1, 1, 1]) == 0          # monotone climb
    assert direction_changes([2, 0, -2]) == 1         # a unison does not reset


def test_gradient_stdev_flat_vs_varied():
    assert gradient_stdev([2, 2]) == 0.0          # constant gradient -> flat
    assert gradient_stdev([2]) == 0.0             # < 2 intervals
    assert gradient_stdev([2, -2]) == 2.0         # mean 0, spread 2


def test_contour_shape_summaries():
    assert contour_shape([60, 62, 64, 66, 68]) == "ascending"
    assert contour_shape([68, 66, 64, 62, 60]) == "descending"
    assert contour_shape([60, 64, 72, 64, 60]) == "arch"
    assert contour_shape([72, 64, 60, 64, 72]) == "valley"
    assert contour_shape([60, 61, 60, 61, 60]) == "level"      # within a whole tone
    assert contour_shape([60, 64]) == "insufficient-data"      # < 3 notes
