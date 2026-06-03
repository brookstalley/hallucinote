"""melody.lens — the profile-RELATIVE shaped-vs-aimless reading (phase 2b, Chunk 3).

The architectural keystone that resolves the RECORDED universal-verdict bug
(melody-model §7): an early ``step_fraction >= 0.5 -> shaped else wandering`` rule
mislabeled the genuine third-based reggae hook as "wandering" — exactly the
universal verdict the thesis forbids. The fix is profile-RELATIVE: a line is graded
against its OWN declared aim, and ``aimless`` can fire ONLY when a DEFINITE declared
intent is contradicted — never on a silent or ``free`` profile.

Pinned here so the bug is made permanently impossible, not just deferred:
  * the reggae-hook regression (a third-based line with an arch+high-repetition
    profile reads ``shaped``, NEVER ``aimless``),
  * the universal-verdict-forbidden property (a ``free``/silent profile can NEVER
    yield ``aimless``),
  * and the aimless QUESTION (a definite intent contradicted reads ``aimless``, but
    the emitted finding is a coaching question, NEVER a verdict).
"""
from __future__ import annotations

from hallucinote.melody import (
    MelodicProfile,
    SectionMelody,
    analyze_melody,
)


def _n(pitch: int, start: float, dur: float = 0.5, vel: int = 80) -> dict:
    return {"pitch": pitch, "start_beats": start, "duration_beats": dur, "velocity": vel}


# The real sun-zone-done reggae hook (pitch, onset) — third-based, mid-register, the
# forcing function the recorded bug mislabeled (§9).
def _reggae_chillin() -> list[dict]:
    cells = [(64, 0.0), (62, 1.0), (59, 1.5), (59, 2.0), (55, 2.5), (52, 3.0),
             (59, 8.0), (69, 8.5), (55, 9.0), (52, 10.0), (55, 10.5), (59, 11.0),
             (62, 11.5), (64, 12.0)]
    return [_n(p, t) for p, t in cells]


def _level_line() -> list[dict]:
    # a near-flat wobble: no net shape -> contour_shape "level"
    return [_n(60 + (i % 2), i * 0.5) for i in range(10)]


def _arch_line() -> list[dict]:
    pitches = [60, 62, 64, 65, 67, 69, 71, 69, 67, 64, 62, 60]
    return [_n(p, i * 0.5) for i, p in enumerate(pitches)]


def _read(layers, *, profiles=None):
    sec = SectionMelody(name="s", length_beats=16.0, layers=layers, profiles=profiles)
    return analyze_melody([sec], song_slug="t").sections[0]


def _kinds(section):
    return [f.kind for f in section.findings]


# === THE KEYSTONE: the reggae-hook regression (the recorded bug, pinned) ==========

def test_reggae_hook_with_arch_high_repetition_profile_reads_shaped_never_aimless():
    """The recorded universal-verdict bug made permanently impossible: a third-based
    reggae hook declared arch + high-repetition reads ``shaped``, NEVER ``aimless``.

    Strengthened for Chunk 4: the single-cycle hook's within-line repetition coverage
    is LOW (its repetition is across loop cycles, invisible in one cycle) — yet
    because it satisfies its contour aim (a real net shape), it stays ``shaped``.
    Satisfying ANY declared aim keeps a line off the ``aimless`` verdict — the line
    is doing something it set out to do, not wandering."""
    profile = MelodicProfile(
        name="reggae-hook", contour_intent="arch", repetition_appetite="high",
    )
    sec = _read({"05 Lead": _reggae_chillin()}, profiles={"05 Lead": profile})
    line = sec.lines[0]
    # the within-line repetition number IS low (the bug-recurrence trap), and the
    # line still reads shaped because its contour aim is satisfied.
    assert line.repetition_coverage is not None and line.repetition_coverage < 0.5
    assert line.contour_shape != "level"   # it has a real net shape
    assert line.shaped_reading == "shaped"
    assert line.shaped_reading != "aimless"
    assert "aimless-line" not in _kinds(sec)


# === universal-verdict-forbidden: free / silent profile can NEVER be aimless ======

def test_free_contour_profile_over_level_line_is_ungraded_never_aimless():
    profile = MelodicProfile(name="x", contour_intent="free")
    sec = _read({"05 Lead": _level_line()}, profiles={"05 Lead": profile})
    assert sec.lines[0].shaped_reading == "ungraded"
    assert sec.lines[0].shaped_reading != "aimless"
    assert "aimless-line" not in _kinds(sec)


def test_silent_profile_over_level_line_is_ungraded_never_aimless():
    # a profile that declares neither contour_intent nor repetition_appetite
    profile = MelodicProfile(name="x", step_appetite="low")
    sec = _read({"05 Lead": _level_line()}, profiles={"05 Lead": profile})
    assert sec.lines[0].shaped_reading == "ungraded"
    assert "aimless-line" not in _kinds(sec)


def test_no_profile_is_ungraded_never_aimless():
    sec = _read({"05 Lead": _level_line()})  # no profiles=
    assert sec.lines[0].shaped_reading == "ungraded"
    assert "aimless-line" not in _kinds(sec)


# === aimless fires ONLY against a definite intent the line contradicts ============

def test_definite_arch_over_no_net_shape_line_reads_aimless_as_a_question():
    profile = MelodicProfile(name="x", contour_intent="arch")
    sec = _read({"05 Lead": _level_line()}, profiles={"05 Lead": profile})
    line = sec.lines[0]
    assert line.shaped_reading == "aimless"
    aimless = [f for f in sec.findings if f.kind == "aimless-line"]
    assert len(aimless) == 1
    # the emitted finding is a coaching QUESTION, never a verdict
    assert aimless[0].severity == "info"
    assert aimless[0].detail.endswith("?")
    assert "wandered" in aimless[0].detail  # the question, not "this melody is bad"


def test_definite_arch_over_an_arching_line_reads_shaped():
    profile = MelodicProfile(name="x", contour_intent="arch")
    sec = _read({"05 Lead": _arch_line()}, profiles={"05 Lead": profile})
    assert sec.lines[0].shaped_reading == "shaped"
    assert "aimless-line" not in _kinds(sec)


def test_different_definite_shape_is_a_reshape_question_not_aimless():
    """A measured definite shape that differs from the declared one is the
    contour-intent-mismatch RE-SHAPE question — NOT aimlessness (only a no-net-shape
    ``level`` line is aimless against a declared shape)."""
    profile = MelodicProfile(name="x", contour_intent="descending")
    sec = _read({"05 Lead": _arch_line()}, profiles={"05 Lead": profile})  # measures arch
    assert sec.lines[0].shaped_reading == "shaped"
    assert "aimless-line" not in _kinds(sec)
    assert "contour-intent-mismatch" in _kinds(sec)
