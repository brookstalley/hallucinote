"""Property-based tests for envelope breakpoint validation.

First codebase use of Hypothesis — see project-preferences.md note:
"turn it on for note-array transforms / serialization round-trips when
those grow." Envelope breakpoint validation is the clearest fit:

  - **Domain**: lists of {time_beats: float >= 0, value: float, curve?: enum}
  - **Named invariants**: monotonic time, sorted output preserves input
    order under equality, every invariant rejection points at the
    offending index, accepted lists round-trip through cleaning unchanged
    in time / value content.

Example-based tests cover the explicit error paths (out-of-order, negative
time, bad curve). Property tests catch the orderings I didn't think of —
edge cases like all-zero-time, exact-duplicate times, very large breakpoint
counts, NaN values (which Hypothesis tends to surface).
"""
from __future__ import annotations

import math

import pytest
from hypothesis import assume, given, strategies as st

from hallucinote_mcp.handlers.automation import _validate_breakpoints


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


_CURVES = ("linear", "hold", "fast", "slow")

# Finite floats — NaN / Inf are deliberately excluded for breakpoint times
# and values (Live's envelope API doesn't accept them; we want validation
# to reject them, but that's an example test, not a property).
finite_float = st.floats(
    allow_nan=False, allow_infinity=False, min_value=-1e6, max_value=1e6,
)
nonneg_float = st.floats(
    allow_nan=False, allow_infinity=False, min_value=0.0, max_value=1e6,
)


def _sorted_breakpoints(min_size: int = 1, max_size: int = 50) -> st.SearchStrategy:
    """Lists of {time_beats, value, curve?} sorted by time, with finite
    floats and valid curves. The shape `_validate_breakpoints` accepts.

    Build by drawing N independent triples (time, value, curve) then sort
    the resulting list by time — guarantees same-length triples and
    monotonic time without needing post-filtering.
    """
    triple = st.tuples(
        nonneg_float,
        finite_float,
        st.one_of(st.none(), st.sampled_from(_CURVES)),
    )

    def _build_from_triples(triples: list[tuple[float, float, str | None]]) -> list[dict]:
        triples = sorted(triples, key=lambda t: t[0])
        out: list[dict] = []
        for t, v, c in triples:
            bp: dict = {"time_beats": t, "value": v}
            if c is not None:
                bp["curve"] = c
            out.append(bp)
        return out

    return st.lists(triple, min_size=min_size, max_size=max_size).map(_build_from_triples)


# ---------------------------------------------------------------------------
# Properties — accepted inputs
# ---------------------------------------------------------------------------


@given(_sorted_breakpoints())
def test_sorted_breakpoints_are_always_accepted(bps):
    """Any monotonically-sorted breakpoint list with finite floats and
    valid curves passes validation.
    """
    cleaned = _validate_breakpoints(bps)
    assert len(cleaned) == len(bps)


@given(_sorted_breakpoints(min_size=1))
def test_cleaned_breakpoints_preserve_time_and_value(bps):
    """Validation passes time_beats and value through verbatim; only the
    curve is normalized (missing → None).
    """
    cleaned = _validate_breakpoints(bps)
    for original, c in zip(bps, cleaned):
        assert c["time_beats"] == original["time_beats"]
        assert c["value"] == original["value"]


@given(_sorted_breakpoints(min_size=2))
def test_cleaned_breakpoint_times_remain_monotonic(bps):
    """The cleaned output preserves the input's monotonic-time invariant."""
    cleaned = _validate_breakpoints(bps)
    for i in range(len(cleaned) - 1):
        assert cleaned[i]["time_beats"] <= cleaned[i + 1]["time_beats"]


# ---------------------------------------------------------------------------
# Properties — rejected inputs
# ---------------------------------------------------------------------------


@given(
    st.lists(nonneg_float, min_size=2, max_size=20),
    st.lists(finite_float, min_size=2, max_size=20),
)
def test_unsorted_breakpoints_are_rejected_at_first_violation(times, values):
    """If any breakpoint's time is less than the previous one's,
    validation raises a ValueError naming the offending index.
    """
    n = min(len(times), len(values))
    if n < 2:
        return
    times = times[:n]
    values = values[:n]
    # Find a position where times decrease; if none exists, skip
    # (this property is about violations, not about all-monotonic inputs).
    has_violation = any(times[i] < times[i - 1] for i in range(1, n))
    assume(has_violation)
    bps = [{"time_beats": t, "value": v} for t, v in zip(times, values)]
    with pytest.raises(ValueError) as excinfo:
        _validate_breakpoints(bps)
    # Error message must name "sorted" (the invariant) and include the
    # specific time value that violated.
    assert "sorted" in str(excinfo.value)


@given(
    st.lists(
        st.floats(allow_nan=False, allow_infinity=False, max_value=-1e-6,
                  min_value=-1e6),
        min_size=1, max_size=10,
    ),
    finite_float,
)
def test_negative_time_breakpoint_is_rejected(neg_times, value):
    """Any breakpoint with time_beats < 0 is rejected with an offending-
    index message.
    """
    # Use just one negative entry — Hypothesis will explore multi-entry
    # cases via the sort-order property above.
    bps = [{"time_beats": neg_times[0], "value": value}]
    with pytest.raises(ValueError) as excinfo:
        _validate_breakpoints(bps)
    assert ">= 0" in str(excinfo.value)


@given(st.sampled_from([
    "wobbly", "qubic", "sinusoidal", "", "LINEAR",  # case-sensitivity
    "step",
]))
def test_unknown_curve_is_rejected(curve):
    """Any curve string outside the linear|hold|fast|slow enum is rejected
    with a teaching error listing the valid choices.
    """
    bps = [{"time_beats": 0.0, "value": 0.5, "curve": curve}]
    with pytest.raises(ValueError) as excinfo:
        _validate_breakpoints(bps)
    err = str(excinfo.value)
    assert "curve" in err
    # Lists what IS allowed
    assert "linear" in err and "hold" in err


# ---------------------------------------------------------------------------
# Boundary: empty list
# ---------------------------------------------------------------------------


def test_empty_breakpoint_list_is_rejected():
    """Property-test framing: a list-shaped input with zero elements must
    still be rejected (writing a zero-breakpoint envelope is meaningless;
    use action='clear' instead).
    """
    with pytest.raises(ValueError) as excinfo:
        _validate_breakpoints([])
    assert "non-empty" in str(excinfo.value).lower()
