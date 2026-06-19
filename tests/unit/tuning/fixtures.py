"""Shared tuning fixtures + a test-local Scala reader.

The shipping package writes ``.ascl`` but ships **no parser** (pull-from-Live
only). The writer's round-trip contract — "data → ``.ascl`` text → re-readable
cents" — therefore needs a reader that lives *only in the tests*. ``parse_scl``
is a minimal, spec-faithful Scala reader used to prove the writer emits a valid,
re-readable file; it must never migrate into the package.
"""
from __future__ import annotations

import math

from hallucinote.tuning.model import TuningData


def _edo(name: str, n: int, *, period_cents: float = 1200.0, ref: int = 60) -> TuningData:
    """An N-equal-division tuning of ``period_cents`` (default the octave)."""
    step = period_cents / n
    cents = tuple(round(step * k, 6) for k in range(1, n + 1))
    # Pin the period to the last step exactly so the invariant holds regardless
    # of rounding (the writer/round-trip tolerance would absorb it either way).
    cents = cents[:-1] + (period_cents,)
    return TuningData(
        name=name, step_count=n, period_cents=period_cents,
        reference_note=ref, step_cents=cents,
    )


def _ji_major() -> TuningData:
    """A 5-limit just major scale — unequal steps, octave period."""
    ratios = (9 / 8, 5 / 4, 4 / 3, 3 / 2, 5 / 3, 15 / 8, 2 / 1)
    cents = tuple(round(1200.0 * math.log2(r), 6) for r in ratios)
    cents = cents[:-1] + (1200.0,)  # pin octave
    return TuningData(
        name="JI 5-limit major", step_count=7, period_cents=1200.0,
        reference_note=60, step_cents=cents,
    )


def _bohlen_pierce() -> TuningData:
    """13 equal divisions of the tritave (3/1) — a genuinely non-octave period."""
    tritave = 1200.0 * math.log2(3.0)  # ~1901.955 cents, NOT 1200
    return _edo("Bohlen-Pierce", 13, period_cents=tritave)


EDO_12 = _edo("12-EDO", 12)
EDO_19 = _edo("19-EDO", 19)
JI_MAJOR = _ji_major()
BOHLEN_PIERCE = _bohlen_pierce()

# Every distinct shape: octave-EDO, fine-EDO, unequal-JI, non-octave.
ALL_TUNINGS = (EDO_12, EDO_19, JI_MAJOR, BOHLEN_PIERCE)


# --- Captured live LOM read (verify-api, 2026-06-19) -----------------------
#
# The exact ``song.tuning_system`` shapes probed off a real loaded tuning —
# **Wendy Carlos gamma** (20 equal divisions of the 3/2 fifth; a genuine
# *non-octave* tuning) — via ``ableton_probe(action='get', ...)``. Verbatim from
# the probe ``value`` fields; see ``api-notes-tuning.md``. This is the assembled
# dict the ``/tuning-pull`` skill hands ``read_tuning_system`` (each scalar/list
# is one probe; ``reference_pitch`` is two nested ``.octave`` / ``.index_in_octave``
# gets). It grounds ``read.py``'s loaded-tuning extraction in a real reading, not
# a guessed shape.
GAMMA_LOADED_RAW = {
    "name": "Wendy Carlos gamma",
    "note_tunings": [
        0.0, 35.09775161743164, 70.19550323486328, 105.29325103759766,
        140.39100646972656, 175.48875427246094, 210.5865020751953,
        245.6842498779297, 280.7820129394531, 315.8797607421875,
        350.9775085449219, 386.07525634765625, 421.1730041503906,
        456.270751953125, 491.3684997558594, 526.4662475585938,
        561.5640258789062, 596.6617431640625, 631.759521484375,
        666.8572387695312,
    ],
    "number_of_notes_in_pseudo_octave": 20,
    "pseudo_octave_in_cents": 701.9550170898438,
    "reference_pitch": {"octave": 3, "index_in_octave": 0},
}

# The TuningData ``read_tuning_system`` must derive from GAMMA_LOADED_RAW: drop
# the implicit unison (note_tunings[0] == 0.0), append the period as the final
# degree, and resolve reference_note = (3+2)*12 + 0 = 60 (Ableton C3=60).
GAMMA_EXPECTED = TuningData(
    name="Wendy Carlos gamma",
    step_count=20,
    period_cents=701.9550170898438,
    reference_note=60,
    step_cents=tuple(GAMMA_LOADED_RAW["note_tunings"][1:]) + (701.9550170898438,),
)


def parse_scl(text: str) -> tuple[str, int, list[float]]:
    """Minimal spec-faithful Scala reader → (description, count, cents list).

    Rules (huygens-fokker scl_format): ``!`` lines are comments; the first
    non-comment line is the description, the second is the integer note count,
    the rest are pitch lines. A value containing ``.`` is cents; ``/`` or a bare
    integer is a ratio (converted to cents). Trailing inline content after the
    value (e.g. ``! name``) is ignored.
    """
    non_comment = [ln for ln in text.splitlines() if not ln.lstrip().startswith("!")]
    description = non_comment[0]
    count = int(non_comment[1].strip())
    cents: list[float] = []
    for line in non_comment[2 : 2 + count]:
        token = line.strip().split()[0]
        if "." in token:
            cents.append(float(token))
        elif "/" in token:
            num, den = token.split("/")
            cents.append(1200.0 * math.log2(float(num) / float(den)))
        else:
            cents.append(1200.0 * math.log2(float(token)))
    return description, count, cents
