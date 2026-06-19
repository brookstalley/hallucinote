"""TuningData: the locked persisted-format contract + its invariants."""
from __future__ import annotations

import pytest

from hallucinote.tuning.model import TuningData

from .fixtures import ALL_TUNINGS, BOHLEN_PIERCE, EDO_12


@pytest.mark.parametrize("tuning", ALL_TUNINGS, ids=lambda t: t.name)
def test_blob_round_trips(tuning):
    assert TuningData.from_blob(tuning.to_blob()) == tuning


def test_blob_is_compact_json_with_every_field():
    blob = EDO_12.to_blob()
    assert " " not in blob  # compact separators
    for key in ("name", "step_count", "period_cents", "reference_note", "step_cents"):
        assert f'"{key}"' in blob


def test_from_blob_rejects_missing_key():
    with pytest.raises(ValueError, match="missing required key"):
        TuningData.from_blob('{"name":"x","step_count":1,"period_cents":1.0}')


def test_step_count_must_match_step_cents_length():
    with pytest.raises(ValueError, match="must agree"):
        TuningData(
            name="bad", step_count=3, period_cents=1200.0,
            reference_note=60, step_cents=(1200.0,),
        )


def test_step_count_must_be_positive():
    with pytest.raises(ValueError, match="positive int"):
        TuningData(
            name="bad", step_count=0, period_cents=1200.0,
            reference_note=60, step_cents=(),
        )


def test_reference_note_must_be_in_midi_range():
    with pytest.raises(ValueError, match="MIDI note"):
        TuningData(
            name="bad", step_count=1, period_cents=1200.0,
            reference_note=200, step_cents=(1200.0,),
        )


def test_period_must_equal_last_step():
    with pytest.raises(ValueError, match="period_cents must equal"):
        TuningData(
            name="bad", step_count=2, period_cents=1200.0,
            reference_note=60, step_cents=(100.0, 1100.0),
        )


def test_non_octave_period_is_allowed():
    # Bohlen-Pierce repeats at the tritave, not the octave — the model must not
    # assume 1200, and its last step is the (non-octave) period.
    assert BOHLEN_PIERCE.period_cents > 1800.0
    assert BOHLEN_PIERCE.step_cents[-1] == BOHLEN_PIERCE.period_cents
