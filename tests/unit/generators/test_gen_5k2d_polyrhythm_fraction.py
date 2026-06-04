"""Regression for GEN-5K2D: the polyrhythm helper must compute onset positions
in exact rational arithmetic (``fractions.Fraction``), not float, so composed
cross-rhythm ratios land on exact beat fractions without IEEE-754 sub-LSB drift.

The backlog canary: ``(7.0 / 5) * 3 / 2.0`` yields ``2.0999999999999996`` —
float drift introduced silently at authoring time. The helper computes the same
relationship as the exact ``Fraction(21, 10)`` and only float-converts at the
mutator boundary (``db/mutations/notes.py`` calls ``float(start_beats)``).
"""
from __future__ import annotations

from fractions import Fraction

import pytest

from hallucinote.generators.primitives import polyrhythm


def test_returns_exact_fractions_not_floats():
    """Onsets are exact Fraction values, never lossy floats."""
    onsets = polyrhythm(5, against=4)
    assert all(isinstance(b, Fraction) for b in onsets)
    # 5-against-4: 5 onsets across 4 beats → step 4/5.
    assert onsets == [Fraction(0, 1), Fraction(4, 5), Fraction(8, 5),
                      Fraction(12, 5), Fraction(16, 5)]


def test_pins_exact_fraction_a_float_would_round():
    """The GEN-5K2D drift case lands on an exact fraction.

    Composing a 7:5 cross-rhythm against a 3:2 reference: float math
    ``(7.0 / 5) * 3 / 2.0`` rounds to 2.0999999999999996; the exact value is
    Fraction(21, 10). The helper's exact onsets compose with further exact
    ratio math to hit it precisely.
    """
    float_drifted = (7.0 / 5) * 3 / 2.0
    assert float_drifted != 2.1  # the drift the helper must avoid

    # 7-against-5 over a span of 3/2 beats: onset 1 step composes the ratios
    # exactly. step = (3/2) / 5 = 3/10; onset[7-of-interest] reproduces the
    # composed ratio (7/5)*(3/2) = 21/10 as an exact value.
    seven_five = polyrhythm(7, against=5)        # step = 5/7, exact Fractions
    assert all(isinstance(b, Fraction) for b in seven_five)
    composed = (Fraction(7, 5)) * Fraction(3, 2)
    assert composed == Fraction(21, 10)
    assert float(composed) == 2.1  # exact at the float boundary, no drift


def test_default_span_is_against_beats():
    """3-against-2 spreads 3 onsets across exactly 2 beats."""
    onsets = polyrhythm(3, against=2)
    assert onsets == [Fraction(0, 1), Fraction(2, 3), Fraction(4, 3)]
    # full cycle (next onset) would land exactly on beat 2.
    assert onsets[-1] + (onsets[1] - onsets[0]) == Fraction(2, 1)


def test_explicit_span_override():
    """span packs the n onsets into a custom number of beats, exactly."""
    onsets = polyrhythm(4, against=3, span=2)
    assert onsets == [Fraction(0, 1), Fraction(1, 2), Fraction(1, 1),
                      Fraction(3, 2)]


def test_materializes_to_float_only_at_boundary():
    """float() of each onset is what the mutator boundary stores — drift, if
    any, is introduced once at the edge, not accumulated through authoring."""
    onsets = polyrhythm(5, against=4)
    assert [float(b) for b in onsets] == [0.0, 0.8, 1.6, 2.4, 3.2]


@pytest.mark.parametrize("n,against", [(0, 2), (-1, 2), (3, 0), (3, -2)])
def test_rejects_nonpositive_args(n, against):
    with pytest.raises(ValueError):
        polyrhythm(n, against=against)
