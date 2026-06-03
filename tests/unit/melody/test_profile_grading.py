"""melody.lens — profile-RELATIVE grading (phase 2b).

Chunk 1 thin slice: the single simplest gradable field (``harmonic_freedom`` vs
the already-computed non-chord-tone share) threaded end-to-end — declare a profile,
the lens emits ONE profile-relative ``info`` finding; the same line with NO profile
yields the unchanged 2a output (the conflated-state test: profile-present vs
profile-absent are distinguished). Plus the ``declared-but-unmatched`` typo finding
(enumerate-every-state) and the high-freedom suppression of the 2a ``unresolved-nct``
finding. Every finding is a coaching QUESTION (``severity="info"``), never a verdict.
"""
from __future__ import annotations

from hallucinote.melody import (
    MelodicProfile,
    SectionMelody,
    analyze_melody,
)
from hallucinote.theory.model import Progression


def _n(pitch: int, start: float, dur: float = 0.5, vel: int = 80) -> dict:
    return {"pitch": pitch, "start_beats": start, "duration_beats": dur, "velocity": vel}


# A C-major section (chord = C E G) over which a chromatic, NCT-heavy line floats:
# C#, D#, F#, A, A#, B are mostly non-chord-tones — abundant NCT share, the
# harmonic-freedom grading's input.
def _high_nct_line() -> list[dict]:
    pitches = [60, 61, 63, 66, 69, 70, 71, 66, 63, 61]  # C, C#, D#, F#, A, A#, B...
    return [_n(p, i * 0.5) for i, p in enumerate(pitches)]


def _c_major_prog() -> Progression:
    return Progression.of("C", "Ionian", ["C"], beats_per_chord=16.0)


def _analyze(layers, *, profiles=None, progression=None):
    sec = SectionMelody(
        name="verse", length_beats=8.0, layers=layers,
        progression=progression, profiles=profiles,
    )
    return analyze_melody([sec], song_slug="t")


def _kinds(report):
    return [f.kind for f in report.findings]


# --- the conflated state: profile-present vs profile-absent are distinguished ----

def test_low_freedom_profile_on_high_nct_line_fires_one_mismatch_finding():
    line = {"05 Lead": _high_nct_line()}
    profile = MelodicProfile(name="locked", harmonic_freedom="low")
    rep = _analyze(line, profiles={"05 Lead": profile}, progression=_c_major_prog())
    mismatches = [f for f in rep.findings if f.kind == "harmonic-freedom-mismatch"]
    assert len(mismatches) == 1
    f = mismatches[0]
    assert f.severity == "info"          # a coaching QUESTION, never a verdict
    assert f.detail.endswith("?")        # phrased as a question
    assert "harmonic_freedom=low" in f.detail
    assert rep.sections[0].lines[0].profile_name == "locked"


def test_same_line_with_no_profile_yields_unchanged_2a_output():
    """The conflated-state oracle: the no-profile path is byte-for-byte the 2a
    output — no harmonic-freedom-mismatch finding, profile_name is None."""
    line = {"05 Lead": _high_nct_line()}
    rep = _analyze(line, progression=_c_major_prog())  # NO profiles=
    assert "harmonic-freedom-mismatch" not in _kinds(rep)
    assert rep.sections[0].lines[0].profile_name is None


def test_low_freedom_profile_on_chord_tone_line_is_silent():
    # A pure C-E-G chord-tone line declared chord-tone-locked: matches, so no finding.
    line = {"05 Lead": [_n(p, i * 0.5) for i, p in enumerate([60, 64, 67, 72, 67, 64, 60, 55])]}
    profile = MelodicProfile(name="locked", harmonic_freedom="low")
    rep = _analyze(line, profiles={"05 Lead": profile}, progression=_c_major_prog())
    assert "harmonic-freedom-mismatch" not in _kinds(rep)


# --- enumerate-every-state: the declared-but-unmatched typo finding ---------------

def test_declared_profile_for_nonexistent_layer_yields_typo_finding():
    line = {"05 Lead": _high_nct_line()}
    profile = MelodicProfile(name="x", harmonic_freedom="low")
    rep = _analyze(line, profiles={"Vocal": profile}, progression=_c_major_prog())
    typos = [f for f in rep.findings if f.kind == "declared-but-unmatched"]
    assert len(typos) == 1
    assert typos[0].track == "Vocal"
    assert typos[0].severity == "info"
    # ...and the real line was NOT graded against the misplaced profile.
    assert rep.sections[0].lines[0].profile_name is None


# --- high freedom suppresses the 2a unresolved-nct coaching ----------------------

def test_high_freedom_profile_suppresses_unresolved_nct_finding():
    """declared harmonic_freedom="high" means floating chromatic color is the
    intended idiom — so the 2a stranded-dissonance coaching must NOT nag it."""
    line = {"05 Lead": _high_nct_line()}
    # Baseline: no profile -> the 2a unresolved-nct finding fires on this line.
    base = _analyze(line, progression=_c_major_prog())
    assert "unresolved-nct" in _kinds(base)
    # With a high-freedom profile -> suppressed.
    profile = MelodicProfile(name="free-color", harmonic_freedom="high")
    rep = _analyze(line, profiles={"05 Lead": profile}, progression=_c_major_prog())
    assert "unresolved-nct" not in _kinds(rep)
    # high freedom is NOT the low-direction mismatch either.
    assert "harmonic-freedom-mismatch" not in _kinds(rep)


# === Chunk 2: contour / apex / ambitus / step-appetite gradings (both states) ====

# A clear arch line (rises to a peak in the middle, falls back), 12 notes, ambitus
# 12 semitones, apex near the middle (~45-55%).
def _arch_line() -> list[dict]:
    pitches = [60, 62, 64, 65, 67, 69, 71, 69, 67, 64, 62, 60]
    return [_n(p, i * 0.5) for i, p in enumerate(pitches)]


def _findings_of_kind(report, kind):
    return [f for f in report.findings if f.kind == kind]


def _assert_question(finding):
    assert finding.severity == "info"
    assert finding.detail.endswith("?")


# --- contour_intent vs measured contour_shape ------------------------------------

def test_contour_mismatch_fires_when_declared_shape_differs():
    line = {"05 Lead": _arch_line()}  # measures "arch"
    profile = MelodicProfile(name="x", contour_intent="descending")
    rep = _analyze(line, profiles={"05 Lead": profile})
    fs = _findings_of_kind(rep, "contour-intent-mismatch")
    assert len(fs) == 1
    _assert_question(fs[0])
    assert "descending" in fs[0].detail


def test_contour_match_is_silent():
    line = {"05 Lead": _arch_line()}  # measures "arch"
    profile = MelodicProfile(name="x", contour_intent="arch")
    rep = _analyze(line, profiles={"05 Lead": profile})
    assert _findings_of_kind(rep, "contour-intent-mismatch") == []


def test_free_contour_intent_never_fires_a_contour_finding():
    line = {"05 Lead": _arch_line()}
    profile = MelodicProfile(name="x", contour_intent="free")
    rep = _analyze(line, profiles={"05 Lead": profile})
    assert _findings_of_kind(rep, "contour-intent-mismatch") == []


# --- apex_position vs measured apex ----------------------------------------------

def test_apex_mismatch_fires_when_climax_is_far_from_intended():
    line = {"05 Lead": _arch_line()}  # apex near the middle (~45%)
    profile = MelodicProfile(name="x", apex_position=1.0)  # wanted a final lift
    rep = _analyze(line, profiles={"05 Lead": profile})
    fs = _findings_of_kind(rep, "apex-position-mismatch")
    assert len(fs) == 1
    _assert_question(fs[0])


def test_apex_match_within_tolerance_is_silent():
    line = {"05 Lead": _arch_line()}  # apex near the middle
    profile = MelodicProfile(name="x", apex_position=0.5)
    rep = _analyze(line, profiles={"05 Lead": profile})
    assert _findings_of_kind(rep, "apex-position-mismatch") == []


# --- ambitus band ----------------------------------------------------------------

def test_ambitus_mismatch_fires_outside_declared_band():
    line = {"05 Lead": _arch_line()}  # ambitus 11
    profile = MelodicProfile(name="x", ambitus_min=0, ambitus_max=5)  # wanted narrow
    rep = _analyze(line, profiles={"05 Lead": profile})
    fs = _findings_of_kind(rep, "ambitus-mismatch")
    assert len(fs) == 1
    _assert_question(fs[0])


def test_ambitus_match_inside_band_is_silent():
    line = {"05 Lead": _arch_line()}  # ambitus 11
    profile = MelodicProfile(name="x", ambitus_min=7, ambitus_max=15)
    rep = _analyze(line, profiles={"05 Lead": profile})
    assert _findings_of_kind(rep, "ambitus-mismatch") == []


# --- step_appetite vs measured step_fraction band (the PENDING by-ear edges) ------

def _stepwise_line() -> list[dict]:
    # all whole-tone moves -> step_fraction = 1.0 -> "high" band
    pitches = [60, 62, 64, 62, 60, 62, 64, 62, 60, 62]
    return [_n(p, i * 0.5) for i, p in enumerate(pitches)]


def _leapy_line() -> list[dict]:
    # all wide leaps -> step_fraction = 0.0 -> "low" band
    pitches = [60, 67, 60, 67, 60, 67, 60, 67, 60, 67]
    return [_n(p, i * 0.5) for i, p in enumerate(pitches)]


def test_step_appetite_mismatch_fires_on_band_disagreement():
    line = {"05 Lead": _leapy_line()}  # step_fraction 0.0 -> "low"
    profile = MelodicProfile(name="x", step_appetite="high")  # declared proximity
    rep = _analyze(line, profiles={"05 Lead": profile})
    fs = _findings_of_kind(rep, "step-appetite-mismatch")
    assert len(fs) == 1
    _assert_question(fs[0])


def test_step_appetite_match_is_silent():
    line = {"05 Lead": _stepwise_line()}  # step_fraction 1.0 -> "high"
    profile = MelodicProfile(name="x", step_appetite="high")
    rep = _analyze(line, profiles={"05 Lead": profile})
    assert _findings_of_kind(rep, "step-appetite-mismatch") == []


# --- the PENDING by-ear edge constants are isolated + marked ---------------------

def test_appetite_edges_are_named_constants_carrying_the_pending_marker():
    """Chunk 4 sets these by ear in ONE place — assert they exist as named module
    constants (no magic numbers scattered) and the source carries the PENDING
    marker so the calibration step has a single home (design §8)."""
    import inspect

    from hallucinote.melody import lens as lens_mod

    assert isinstance(lens_mod._STEP_FRACTION_LOW_MAX, float)
    assert isinstance(lens_mod._STEP_FRACTION_HIGH_MIN, float)
    assert isinstance(lens_mod._APEX_POSITION_TOLERANCE, float)
    src = inspect.getsource(lens_mod)
    assert "PENDING by-ear calibration" in src

