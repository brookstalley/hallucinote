"""tuning_probe.is_no_tuning_loaded — the ONE shared none-classifier.

Both ``tuning/read.py`` and ``sync/push/tuning_notice.py`` classify the live
``song.tuning_system`` read through this predicate, so they can never give
opposite verdicts for the same wire shape (a Critic caught that contradiction
when each had its own copy). The narrowness contract — confirmed none-shapes
only, an unconfirmed ``value: None`` is NOT "nothing loaded" — is pinned here at
the shared seam (and end-to-end in ``tuning/test_read.py``).
"""
from __future__ import annotations

import pytest

from hallucinote.tuning_probe import is_no_tuning_loaded


@pytest.mark.parametrize("raw", [
    None,                                  # unwrapped None
    {"type": "NoneType", "value": None},   # the live-confirmed probe wrapper
    {"type": "NoneType"},                  # wrapper without an explicit value
    {"path": "song.tuning_system", "type": "NoneType", "value": None},  # full get result
])
def test_confirmed_none_shapes_are_no_tuning(raw):
    assert is_no_tuning_loaded(raw) is True


@pytest.mark.parametrize("raw", [
    {"type": "TuningSystem", "value": {"__lom__": "TuningSystem"}},  # a real loaded read
    {"type": "TuningSystem", "value": None},  # unconfirmed null-value shape — NOT none
    {"value": None},                          # bare null value, no type — NOT none
    {"name": "19-EDO"},                       # some other dict
    42,                                       # non-dict, non-None
])
def test_unconfirmed_or_loaded_shapes_are_not_no_tuning(raw):
    assert is_no_tuning_loaded(raw) is False
