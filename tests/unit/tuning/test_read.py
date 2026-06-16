"""read_tuning_system: the None/12-TET branch (built) + the loaded stub (held).

The None branch is grounded in a live reading (api-notes-tuning.md): a 12-TET
Set reads ``song.tuning_system`` as ``{"type": "NoneType", "value": None}``. The
loaded branch is deliberately a stub until verify-api captures the LOM dict
shapes — these tests pin that contract so closing the stub is a visible change.
"""
from __future__ import annotations

import pytest

from hallucinote.tuning.read import TuningExtractionNotReady, read_tuning_system


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


def test_loaded_tuning_extraction_is_stubbed():
    # A non-None tuning read must NOT silently guess a shape — it raises the
    # marked stub error pointing at verify-api. Close this once shapes are known.
    with pytest.raises(TuningExtractionNotReady, match="not implemented yet"):
        read_tuning_system({"name": "19-EDO", "note_tunings": {"value": [1, 2, 3]}})


def test_unconfirmed_null_value_shape_does_not_silently_no_op():
    # Narrowness guard (Critic warning): a dict whose top-level `value` is None
    # but is NOT the confirmed NoneType wrapper must fall through to the loud
    # stub, never be mistaken for "no tuning loaded" against an unobserved shape.
    with pytest.raises(TuningExtractionNotReady):
        read_tuning_system({"value": None, "type": "TuningSystem"})


def test_stub_error_is_a_notimplementederror():
    # Subclasses NotImplementedError so a caller can degrade-to-12-TET on the
    # specific type while generic "not built" handling still catches it.
    assert issubclass(TuningExtractionNotReady, NotImplementedError)
