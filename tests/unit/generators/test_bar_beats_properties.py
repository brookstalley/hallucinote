"""Property-based tests for beats ↔ bar conversion across the pull and
push layers.

Wave M-5 introduces `_beats_to_position_bar` in `pull.py` — the inverse of
`push._split_bar(position_bar, ts) → (bar, beat)` (composed with
`pull._join_bar_beat(bar, beat, ts) → position_bar`). The two together
form a closed conversion family that the cue-points pull now relies on.

Property invariants:
1. **Round-trip identity (single meter).** For any (position_bar > 0) in a
   pure 4/4 song: split → beats → bar should approximately recover the
   input bar.
2. **Linearity (single meter).** In 4/4, position_beats = (position_bar - 1) * 4.
3. **Monotonicity.** Increasing position_beats yields non-decreasing
   position_bar.
4. **Multi-meter section boundaries.** When two ts points exist, a beat
   position straddling the boundary lands in the correct section.

The strategy avoids the deep multi-meter combinatorics — those would need
fixtures that build sqlite3.Row-like ts maps — and focuses on the
math-only function shapes via dict-shaped substitutes.
"""
from __future__ import annotations


import pytest
from hypothesis import given, strategies as st

from hallucinote.sync.pull import _beats_to_position_bar


# A minimal Row substitute the math functions only need __getitem__ on.
class _FakeRow:
    def __init__(self, **kw):
        self._d = kw

    def __getitem__(self, k):
        return self._d[k]


def _ts(*entries) -> list:
    """Build a ts_points list of fake rows."""
    return [_FakeRow(**e) for e in entries]


# ---------------------------------------------------------------------------
# Single meter (4/4) — round-trip + linearity
# ---------------------------------------------------------------------------


nonneg_beats = st.floats(
    allow_nan=False, allow_infinity=False, min_value=0.0, max_value=1e5,
)


@given(beats=nonneg_beats)
def test_4_4_conversion_is_linear(beats: float):
    """4/4: position_bar = 1 + beats/4. Pure linear math; no surprises."""
    ts = _ts({"start_bar": 1.0, "numerator": 4, "denominator": 4})
    expected = 1.0 + beats / 4.0
    actual = _beats_to_position_bar(beats, ts)
    assert actual == pytest.approx(expected, abs=1e-9)


@given(beats=nonneg_beats)
def test_no_ts_points_assumes_4_4(beats: float):
    """Empty ts map should equal the 4/4 case (the documented fallback)."""
    actual_empty = _beats_to_position_bar(beats, [])
    actual_44 = _beats_to_position_bar(
        beats,
        _ts({"start_bar": 1.0, "numerator": 4, "denominator": 4}),
    )
    assert actual_empty == pytest.approx(actual_44, abs=1e-9)


# ---------------------------------------------------------------------------
# Monotonicity (any meter)
# ---------------------------------------------------------------------------


@given(
    a=nonneg_beats,
    b=nonneg_beats,
    numerator=st.sampled_from([3, 4, 5, 6, 7]),
    denominator=st.sampled_from([4, 8]),
)
def test_monotonic_in_beats(a: float, b: float, numerator: int, denominator: int):
    """Increasing beats should never decrease the bar position."""
    ts = _ts({"start_bar": 1.0, "numerator": numerator, "denominator": denominator})
    pa = _beats_to_position_bar(a, ts)
    pb = _beats_to_position_bar(b, ts)
    if a <= b:
        assert pa <= pb + 1e-9
    else:
        assert pa >= pb - 1e-9


# ---------------------------------------------------------------------------
# Multi-meter: section-boundary correctness
# ---------------------------------------------------------------------------


def test_multi_meter_4_4_then_7_8_boundary_at_bar_3():
    """
    Layout:
      bars 1-2: 4/4 (4 beats per bar) → 8 beats total → covers beats 0..7
      bar 3+:   7/8 (3.5 beats per bar)
        bar 3 spans beats 8..11.5
        bar 4 spans beats 11.5..15
        ...
    """
    ts = _ts(
        {"start_bar": 1.0, "numerator": 4, "denominator": 4},
        {"start_bar": 3.0, "numerator": 7, "denominator": 8},
    )
    # Beat 0 → bar 1
    assert _beats_to_position_bar(0.0, ts) == pytest.approx(1.0)
    # Beat 4 → bar 2 (one bar of 4/4 in)
    assert _beats_to_position_bar(4.0, ts) == pytest.approx(2.0)
    # Beat 8 → bar 3 (end of the 4/4 section)
    assert _beats_to_position_bar(8.0, ts) == pytest.approx(3.0)
    # Beat 9.75 → bar 3 + (1.75 / 3.5) = bar 3.5
    assert _beats_to_position_bar(9.75, ts) == pytest.approx(3.5)
    # Beat 11.5 → bar 4 (one bar of 7/8 in)
    assert _beats_to_position_bar(11.5, ts) == pytest.approx(4.0)


def test_multi_meter_extrapolates_past_last_ts_point():
    """A beat position past the last ts point's coverage should extrapolate
    in the current meter."""
    ts = _ts(
        {"start_bar": 1.0, "numerator": 4, "denominator": 4},
        {"start_bar": 3.0, "numerator": 7, "denominator": 8},
    )
    # 7/8 starts at bar 3, beat 8. 100 bars in → beat 8 + 100*3.5 = 358
    assert _beats_to_position_bar(358.0, ts) == pytest.approx(103.0, abs=1e-6)
