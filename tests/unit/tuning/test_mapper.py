"""degree_to_midi: pure arithmetic + the documented 0–127 clamp."""
from __future__ import annotations

import pytest

from hallucinote.tuning.mapper import degree_to_midi

from .fixtures import EDO_19


def test_degree_zero_period_zero_is_reference_note():
    assert degree_to_midi(EDO_19, 0, 0) == EDO_19.reference_note


def test_one_full_period_advances_by_step_count():
    # In Live consecutive MIDI numbers are consecutive scale degrees, so a whole
    # period up is exactly step_count semitones-of-MIDI up.
    base = degree_to_midi(EDO_19, 0, 0)
    assert degree_to_midi(EDO_19, 0, 1) == base + EDO_19.step_count
    assert degree_to_midi(EDO_19, 0, 2) == base + 2 * EDO_19.step_count


def test_degree_and_period_compose_additively():
    assert degree_to_midi(EDO_19, 5, 1) == (
        EDO_19.reference_note + EDO_19.step_count + 5
    )


def test_negative_degree_is_well_defined():
    assert degree_to_midi(EDO_19, -3, 0) == EDO_19.reference_note - 3


@pytest.mark.parametrize(
    "degree,period,expected",
    [
        (1000, 0, 127),    # far above → clamps to top
        (0, 100, 127),     # far above via period → clamps to top
        (-1000, 0, 0),     # far below → clamps to bottom
        (0, -100, 0),      # far below via period → clamps to bottom
    ],
)
def test_clamps_to_midi_range(degree, period, expected):
    assert degree_to_midi(EDO_19, degree, period) == expected


def test_period_defaults_to_zero():
    assert degree_to_midi(EDO_19, 7) == degree_to_midi(EDO_19, 7, 0)
