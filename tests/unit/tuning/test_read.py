"""read_tuning_system: the None/12-TET no-op + the loaded-tuning extraction.

The None branch is grounded in a live reading (api-notes-tuning.md): a 12-TET Set
reads ``song.tuning_system`` as ``{"type": "NoneType", "value": None}``. The
loaded branch is closed against the verify-api shapes captured live off Wendy
Carlos gamma (``GAMMA_LOADED_RAW``); these tests pin both the happy-path mapping
and the confirmed-shape invariants that make a misread fail loud.
"""
from __future__ import annotations

import pytest

from hallucinote.tuning.read import TuningReadError, read_tuning_system

from .fixtures import GAMMA_EXPECTED, GAMMA_LOADED_RAW


@pytest.mark.parametrize(
    "raw",
    [
        None,                                   # already-unwrapped None
        {"type": "NoneType", "value": None},    # the live-confirmed probe wrapper
        {"type": "NoneType"},                   # wrapper without an explicit value
    ],
)
def test_none_tuning_is_a_no_op(raw):
    assert read_tuning_system(raw) is None


def test_loaded_tuning_extracts_captured_shapes():
    # The verify-api close: the real Wendy Carlos gamma LOM read maps to the
    # expected TuningData — unison dropped, period appended, reference_note 60.
    assert read_tuning_system(GAMMA_LOADED_RAW) == GAMMA_EXPECTED


def test_loaded_tuning_drops_unison_and_appends_period():
    # Spell out the two shape transforms so a regression in either is legible.
    data = read_tuning_system(GAMMA_LOADED_RAW)
    assert data.step_count == 20                     # == number_of_notes_in_pseudo_octave
    assert len(data.step_cents) == 20                # 19 inner degrees + the period
    assert data.step_cents[-1] == pytest.approx(701.9550170898438)  # period is last
    assert data.step_cents[0] == pytest.approx(35.09775161743164)   # degree 1, not the 0.0 unison
    assert data.reference_note == 60                 # (octave 3 + 2)*12 + index 0


def test_reference_note_uses_ableton_c3_60_numbering():
    raw = {**GAMMA_LOADED_RAW, "reference_pitch": {"octave": 4, "index_in_octave": 9}}
    # C4=72 base + 9 → A4 = MIDI 81 in Ableton's C3=60 convention.
    assert read_tuning_system(raw).reference_note == 81


def test_unconfirmed_null_value_shape_does_not_silently_no_op():
    # Narrowness guard (Critic warning, preserved): a dict whose top-level `value`
    # is None but is NOT the confirmed NoneType wrapper must NOT be mistaken for
    # "no tuning loaded" — it falls through to extraction, which fails loud on the
    # missing fields rather than silently returning a 12-TET no-op.
    with pytest.raises(TuningReadError):
        read_tuning_system({"value": None, "type": "TuningSystem"})


def test_missing_field_raises_tuning_read_error():
    incomplete = {k: v for k, v in GAMMA_LOADED_RAW.items() if k != "reference_pitch"}
    with pytest.raises(TuningReadError, match="reference_pitch"):
        read_tuning_system(incomplete)


def test_non_unison_degree_zero_raises():
    # note_tunings[0] must be the 0-cent unison; a shifted list (e.g. cents read
    # relative to the wrong anchor) is a misread, not a valid tuning.
    shifted = {**GAMMA_LOADED_RAW, "note_tunings": [5.0, *GAMMA_LOADED_RAW["note_tunings"][1:]]}
    with pytest.raises(TuningReadError, match="unison"):
        read_tuning_system(shifted)


def test_declared_count_mismatch_raises():
    bad = {**GAMMA_LOADED_RAW, "number_of_notes_in_pseudo_octave": 19}
    with pytest.raises(TuningReadError, match="disagrees"):
        read_tuning_system(bad)


def test_tuning_read_error_is_a_value_error():
    # Subclasses ValueError so a caller can degrade on the specific type while
    # generic value-error handling still catches a malformed read.
    assert issubclass(TuningReadError, ValueError)
