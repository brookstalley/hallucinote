"""The one bar ruler: `hallucinote.meter`.

These are the contract for every bar↔beat conversion in the tree. The authoring
side (`hallucinote.arrangement`) and the sync side (`hallucinote.sync.geometry`)
both resolve positions through this module, so a disagreement here is the
two-ruler bug (#566) coming back.
"""
from __future__ import annotations

import pytest

from hallucinote.meter import (
    BarGrid,
    MeterMap,
    MeterPoint,
    beats_per_bar,
    format_meter,
    parse_meter,
)


# ---------------------------------------------------------------------------
# The beat is a quarter note, whatever the meter
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "numerator,denominator,expected",
    [(4, 4, 4.0), (7, 4, 7.0), (3, 4, 3.0), (6, 8, 3.0), (7, 8, 3.5), (13, 16, 3.25)],
)
def test_beats_per_bar_counts_quarter_notes(numerator, denominator, expected):
    assert beats_per_bar(numerator, denominator) == pytest.approx(expected)


def test_parse_and_format_round_trip():
    assert parse_meter("7/4") == (7, 4)
    assert parse_meter(" 13/16 ") == (13, 16)
    assert format_meter(*parse_meter("6/8")) == "6/8"


@pytest.mark.parametrize("bad", ["7", "7-4", "x/4", "7/0", "0/4", "-7/4", ""])
def test_parse_meter_rejects_what_is_not_a_meter(bad):
    with pytest.raises(ValueError):
        parse_meter(bad)


# ---------------------------------------------------------------------------
# Construction and validation
# ---------------------------------------------------------------------------


def test_a_bar_has_one_meter():
    with pytest.raises(ValueError, match="a bar has one meter"):
        MeterMap([MeterPoint(9.0, 7, 4), MeterPoint(9.0, 5, 4)])


def test_points_are_ordered_however_they_arrive():
    m = MeterMap([MeterPoint(9.0, 7, 4), MeterPoint(1.0, 4, 4)])
    assert [p.start_bar for p in m.points] == [1.0, 9.0]


def test_a_point_before_bar_one_is_not_a_position():
    with pytest.raises(ValueError, match="1-based"):
        MeterPoint(0.0, 4, 4)


def test_uniform_is_the_bridge_from_the_beats_per_bar_scalar():
    assert MeterMap.uniform(4.0) == MeterMap.parse("4/4")
    assert MeterMap.uniform(3.0) == MeterMap.parse("3/4")
    assert MeterMap.uniform(7.0) == MeterMap.parse("7/4")


def test_a_scalar_that_is_not_a_whole_number_of_beats_must_say_its_meter():
    """3.5 beats is 7/8, but the scalar cannot say so — and 3.0 is 3/4 or 6/8."""
    with pytest.raises(ValueError, match="declare the meter"):
        MeterMap.uniform(3.5)


def test_with_point_is_idempotent_on_an_identical_redeclaration():
    m = MeterMap.parse("4/4")
    assert m.with_point(MeterPoint(1.0, 4, 4)) == m


def test_with_point_refuses_to_pick_between_two_declarations():
    m = MeterMap.parse("4/4")
    with pytest.raises(ValueError, match="already declared 4/4"):
        m.with_point(MeterPoint(1.0, 7, 4))


def test_from_rows_takes_anything_indexable_by_column_name():
    rows = [{"start_bar": 1.0, "numerator": 4, "denominator": 4}]
    assert MeterMap.from_rows(rows) == MeterMap.parse("4/4")
    assert MeterMap.from_rows([]) == MeterMap(())
    assert MeterMap.from_rows(None) == MeterMap(())


# ---------------------------------------------------------------------------
# The walk: bars -> beats
# ---------------------------------------------------------------------------


def test_an_undeclared_map_is_four_four():
    m = MeterMap(())
    assert m.beats_at(1.0) == 0.0
    assert m.beats_at(17.0) == pytest.approx(64.0)
    assert m.meter_at(99.0) == (4, 4)


def test_four_four_is_linear():
    m = MeterMap.parse("4/4")
    assert m.beats_at(1.0) == 0.0
    assert m.beats_at(17.0) == pytest.approx(64.0)
    assert m.beats_at(17.5) == pytest.approx(66.0)


def test_the_case_the_arrangement_docstring_predicted_and_could_not_fix():
    """4/4 turning 7/4 at bar 9: bar 13 is at beat 60, not 48.

    This is the divergence #566 exists to close — uniform bar math put it at
    48 (12 bars x 4) while push put it at 60 (8 x 4 + 4 x 7).
    """
    m = MeterMap([MeterPoint(1.0, 4, 4), MeterPoint(9.0, 7, 4)])
    assert m.beats_at(13.0) == pytest.approx(60.0)
    assert m.beats_at(9.0) == pytest.approx(32.0)


def test_a_borrowed_bar_shortens_the_song():
    """One bar of 3/4 at bar 9 in a 4/4 song: everything after it moves a beat
    earlier, which is the literal steal #247 wanted and could not express."""
    uniform = MeterMap.parse("4/4")
    borrowed = MeterMap(
        [MeterPoint(1.0, 4, 4), MeterPoint(9.0, 3, 4), MeterPoint(10.0, 4, 4)]
    )
    assert borrowed.beats_at(9.0) == uniform.beats_at(9.0)
    assert borrowed.beats_at(10.0) == pytest.approx(uniform.beats_at(10.0) - 1.0)
    assert borrowed.beats_at(33.0) == pytest.approx(uniform.beats_at(33.0) - 1.0)


def test_alien_s_hang_puts_the_landing_where_the_fraction_did():
    """`alien` spells its 7/4 bar at 86 as `bar N + 0.75` under a 4/4 map,
    because the arrangement could not hold the meter change. Declared as a
    meter point, chorus3 returns to INTEGER bar 89 at the same absolute beat."""
    hand_rolled = MeterMap.parse("4/4")
    declared = MeterMap(
        [MeterPoint(1.0, 4, 4), MeterPoint(86.0, 7, 4), MeterPoint(87.0, 4, 4)]
    )
    assert hand_rolled.beats_at(89.75) == pytest.approx(355.0)
    assert declared.beats_at(89.0) == pytest.approx(355.0)
    assert declared.beats_at(113.0) == pytest.approx(451.0)


def test_bars_before_the_first_point_take_that_point_s_meter():
    """A map is a description of the whole song. Its earliest point speaks for
    the bars before it, which is what Live shows for an unmarked region."""
    m = MeterMap([MeterPoint(5.0, 7, 4)])
    assert m.meter_at(1.0) == (7, 4)
    assert m.beats_at(5.0) == pytest.approx(28.0)


def test_a_fractional_bar_inside_a_changed_region():
    m = MeterMap([MeterPoint(1.0, 4, 4), MeterPoint(9.0, 7, 4)])
    assert m.beats_at(9.5) == pytest.approx(32.0 + 3.5)


def test_a_bar_before_one_is_not_a_position():
    with pytest.raises(ValueError, match="1-based"):
        MeterMap.parse("4/4").beats_at(0.5)


# ---------------------------------------------------------------------------
# The walk back: beats -> bars
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "points",
    [
        (),
        (MeterPoint(1.0, 4, 4),),
        (MeterPoint(1.0, 4, 4), MeterPoint(9.0, 7, 4)),
        (MeterPoint(1.0, 4, 4), MeterPoint(9.0, 3, 4), MeterPoint(10.0, 4, 4)),
        (MeterPoint(1.0, 6, 8), MeterPoint(33.0, 7, 8)),
        (MeterPoint(5.0, 7, 4),),
    ],
)
@pytest.mark.parametrize("bar", [1.0, 2.5, 9.0, 9.25, 10.0, 33.0, 128.75])
def test_beats_at_and_bar_at_beats_are_inverses(points, bar):
    m = MeterMap(points)
    assert m.bar_at_beats(m.beats_at(bar)) == pytest.approx(bar, abs=1e-9)


def test_the_inverse_agrees_with_the_forward_walk_without_a_bar_one_row():
    """The pair used to disagree here: the forward walk took the first point's
    meter for the bars before it and the inverse assumed 4/4, so a map whose
    earliest row is not at bar 1 round-tripped to the wrong bar."""
    m = MeterMap([MeterPoint(5.0, 7, 4)])
    assert m.bar_at_beats(28.0) == pytest.approx(5.0)


# ---------------------------------------------------------------------------
# split / join
# ---------------------------------------------------------------------------


def test_split_and_join_round_trip_across_a_change():
    m = MeterMap([MeterPoint(1.0, 4, 4), MeterPoint(9.0, 7, 4)])
    assert m.split_bar(4.5) == (4, pytest.approx(2.0))
    assert m.split_bar(9.5) == (9, pytest.approx(3.5))
    assert m.join_bar_beat(9, 3.5) == pytest.approx(9.5)


# ---------------------------------------------------------------------------
# The grid a read-side lens grades against
# ---------------------------------------------------------------------------


def test_a_uniform_grid_is_what_the_scalar_meant():
    grid = BarGrid.uniform(4.0, 16.0)
    assert grid.bar_starts == (0.0, 4.0, 8.0, 12.0)
    assert grid.bar_lengths == (4.0, 4.0, 4.0, 4.0)


def test_a_grid_across_a_change_has_bars_of_different_lengths():
    m = MeterMap([MeterPoint(1.0, 4, 4), MeterPoint(9.0, 7, 4)])
    grid = m.grid_for(8.0, 11.0)
    assert grid.bar_lengths == pytest.approx((4.0, 7.0, 7.0))
    assert grid.bar_starts == pytest.approx((0.0, 4.0, 11.0))


def test_strong_beats_are_read_against_the_bar_the_note_is_in():
    """A 7/4 bar's strong beats are its own 1 and 4.5 — not the song's 1 and 3.

    The scalar read (`beat % 4`) called beat 4 of the 7/4 bar strong because 4
    is a multiple of the song's bar length. It is an off-beat in a 7/4 bar.
    """
    m = MeterMap([MeterPoint(1.0, 4, 4), MeterPoint(9.0, 7, 4)])
    grid = m.grid_for(9.0, 11.0)  # two 7/4 bars, section-relative
    assert grid.is_strong_beat(0.0, tolerance=1e-6)
    assert grid.is_strong_beat(3.5, tolerance=1e-6)
    assert grid.is_strong_beat(7.0, tolerance=1e-6)
    assert not grid.is_strong_beat(4.0, tolerance=1e-6)
    assert not grid.is_strong_beat(2.0, tolerance=1e-6)


def test_a_grid_needs_a_span():
    with pytest.raises(ValueError, match="end_bar > start_bar"):
        MeterMap.parse("4/4").grid_for(9.0, 9.0)


def test_describe_says_what_was_declared():
    m = MeterMap([MeterPoint(1.0, 4, 4), MeterPoint(86.0, 7, 4)])
    assert m.describe() == "bar 1 -> 4/4 · bar 86 -> 7/4"
    assert MeterMap(()).describe().startswith("4/4 throughout")
