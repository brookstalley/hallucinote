"""Structural parity against a REAL Ableton-shipped `.ascl` (Wendy Carlos gamma).

`data/wendy_carlos_gamma.ascl` is copied verbatim from Live 12 Suite's Core
Library (Tunings/EDO). It is the strongest fixture we can have short of a live
round-trip: a genuine, Ableton-authored, **non-octave** tuning (20 equal
divisions of the 3/2 perfect fifth — the period is ~702 cents, not 1200). This
locks two things: (1) our test Scala reader reads what Ableton actually writes,
and (2) our writer round-trips a real tuning's cents and stays structurally
Ableton-compatible — while being honest about the directives we deliberately
omit (we reconstruct interval structure, not the absolute reference pitch).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from hallucinote.tuning.ascl import write_ascl
from hallucinote.tuning.model import TuningData

from .fixtures import parse_scl

_GAMMA_PATH = Path(__file__).parent / "data" / "wendy_carlos_gamma.ascl"
_CENTS_TOL = 1e-3
# 3/2 (the perfect fifth) in cents — Gamma's non-octave period.
_FIFTH_CENTS = 701.9550008653875


@pytest.fixture
def gamma_text() -> str:
    return _GAMMA_PATH.read_text(encoding="utf-8")


@pytest.fixture
def gamma(gamma_text) -> TuningData:
    """Build TuningData from the real Ableton file (what a closed read.py would
    eventually produce from the LOM — here sourced from the shipped file)."""
    description, count, cents = parse_scl(gamma_text)
    return TuningData(
        name=description, step_count=count, period_cents=cents[-1],
        reference_note=60, step_cents=tuple(cents),
    )


def test_reads_ableton_file_as_a_non_octave_20_step_tuning(gamma):
    assert gamma.step_count == 20
    # The period is the 3/2 fifth, NOT the octave — the case that breaks any
    # "assume 1200" shortcut.
    assert gamma.period_cents == pytest.approx(_FIFTH_CENTS, abs=_CENTS_TOL)
    assert gamma.step_cents[-1] == pytest.approx(_FIFTH_CENTS, abs=_CENTS_TOL)
    # First listed pitch is degree 1 (the implicit unison is unlisted).
    assert gamma.step_cents[0] == pytest.approx(35.09775, abs=_CENTS_TOL)


def test_our_writer_round_trips_the_real_tuning(gamma):
    # Write the tuning with OUR writer, re-read, and confirm every cent matches
    # the real Ableton source — including the ratio-encoded `3/2` period, which
    # we emit as cents.
    description, count, cents = parse_scl(write_ascl(gamma))
    assert description == gamma.name
    assert count == 20
    for got, want in zip(cents, gamma.step_cents):
        assert got == pytest.approx(want, abs=_CENTS_TOL)


def test_writer_output_is_honest_about_omitted_directives(gamma):
    # We deliberately reconstruct interval structure only — so our output must
    # NOT fabricate a REFERENCE_PITCH / NOTE_NAMES / NOTE_RANGE it can't derive
    # from the blob. (The real file has all three; ours intentionally omits them.)
    out = write_ascl(gamma)
    assert "REFERENCE_PITCH" not in out
    assert "NOTE_NAMES" not in out
    assert "NOTE_RANGE" not in out


def test_real_file_shape_matches_what_we_expect(gamma_text):
    # Guard the fixture itself: the shipped file is the structure our research +
    # writer target (count line, ratio period, @ABL after the pitch list).
    lines = gamma_text.splitlines()
    assert "20" in [ln.strip() for ln in lines]            # the note-count line
    assert any(ln.strip().startswith("3/2") for ln in lines)  # ratio period line
    abl = [i for i, ln in enumerate(lines) if ln.startswith("! @ABL")]
    last_pitch = max(i for i, ln in enumerate(lines) if ln.strip().startswith("3/2"))
    assert min(abl) > last_pitch                            # directives follow pitches
