"""The .ascl writer: a valid, re-readable Scala/ASCL file for every shape."""
from __future__ import annotations

import pytest

from hallucinote.tuning.ascl import write_ascl

from .fixtures import ALL_TUNINGS, BOHLEN_PIERCE, EDO_12, parse_scl

_CENTS_TOL = 1e-3  # writer emits 6 decimal places; round-trip is well within this


@pytest.mark.parametrize("tuning", ALL_TUNINGS, ids=lambda t: t.name)
def test_round_trips_through_a_scala_reader(tuning):
    description, count, cents = parse_scl(write_ascl(tuning))
    assert description == tuning.name
    assert count == tuning.step_count
    assert len(cents) == tuning.step_count
    for got, want in zip(cents, tuning.step_cents):
        assert got == pytest.approx(want, abs=_CENTS_TOL)


def test_last_pitch_line_is_the_period():
    _, _, cents = parse_scl(write_ascl(BOHLEN_PIERCE))
    # Non-octave: the final cents value is the tritave, not 1200.
    assert cents[-1] == pytest.approx(BOHLEN_PIERCE.period_cents, abs=_CENTS_TOL)
    assert cents[-1] > 1800.0


def test_unison_is_implicit_not_listed():
    # 12-EDO has 12 pitch lines (degrees 1..12), NOT 13 — the 0-cent unison is
    # implicit per the Scala convention.
    _, count, cents = parse_scl(write_ascl(EDO_12))
    assert count == 12
    assert cents[0] == pytest.approx(100.0, abs=_CENTS_TOL)  # first listed = degree 1


def test_all_pitches_emitted_as_cents():
    # Every pitch line contains a decimal point (cents), not a ratio slash —
    # uniform and correct for non-octave periods.
    body = write_ascl(BOHLEN_PIERCE).splitlines()
    pitch_lines = [
        ln for ln in body
        if ln and not ln.startswith("!") and ln.strip() not in {"13", "Bohlen-Pierce"}
    ]
    for line in pitch_lines:
        assert "." in line and "/" not in line


def test_abl_directives_follow_the_pitch_list():
    lines = write_ascl(EDO_12).splitlines()
    abl_idx = next(i for i, ln in enumerate(lines) if ln.startswith("! @ABL"))
    last_pitch_idx = max(
        i for i, ln in enumerate(lines) if ln.strip().replace(".", "").isdigit()
    )
    assert abl_idx > last_pitch_idx


def test_is_utf8_encodable():
    # @ABL files must be UTF-8 (note-name glyphs); ours must encode cleanly even
    # with a unicode tuning name.
    from hallucinote.tuning.model import TuningData

    t = TuningData(
        name="Pélog ♯", step_count=1, period_cents=1200.0,
        reference_note=60, step_cents=(1200.0,),
    )
    write_ascl(t).encode("utf-8")  # must not raise


def test_blank_name_falls_back_to_a_description():
    from hallucinote.tuning.model import TuningData

    t = TuningData(
        name="   ", step_count=1, period_cents=1200.0,
        reference_note=60, step_cents=(1200.0,),
    )
    description, _, _ = parse_scl(write_ascl(t))
    assert description.strip()  # never an empty description line
