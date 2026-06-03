"""The energy-realization lens (ARR-7M3D) — the RULER's correctness contract.

Fully unit-testable against synthetic declared curves + measured correlates;
the Live render only VALIDATES it end-to-end (chunk 5). These tests prove the
lens correctness without a render:

  * deliberate inversion → ρ < 1 + exactly one named inversion
  * perfect monotonic → ρ == 1.0, zero inversions
  * ordinal-not-linear → ρ == 1.0 (Spearman sees rank, not slope)
  * tied/constant correlate → ρ is None (NOT nan) + serializes under
    json.dumps(allow_nan=False)
  * same-named sections → keyed by start_beat, not name (the join-key lock,
    FAILS under name keying)
  * measured-nan section → excluded symmetrically, ρ over the rest
  * ruler-not-stamp lock → output is measurements only, no verdict/target/curve
"""
from __future__ import annotations

import json
import math

import pytest

from hallucinote.audio.energy import LOUDNESS, ONSET_DENSITY, realize_energy
from hallucinote.audio.report import (
    EnergyRealization,
    SectionEnergy,
    _energy_realization_to_dict,
)


def _declared_abc() -> list[SectionEnergy]:
    """Three sections at increasing declared energy: A < B < C."""
    return [
        SectionEnergy(start_beat=0.0, name="A", energy=0.3),
        SectionEnergy(start_beat=16.0, name="B", energy=0.6),
        SectionEnergy(start_beat=32.0, name="C", energy=0.9),
    ]


# --------------------------------------------------------------------------- #
# ρ + inversion contract
# --------------------------------------------------------------------------- #

def test_deliberate_inversion_yields_rho_below_one_and_one_inversion():
    """Declared A<B<C, measured loudness with C QUIETER than B → ρ < 1 and
    exactly one loudness inversion: the (C,B) pair, carrying both start_beats
    and the correct deltas. The headline ARR-7M3D case."""
    declared = _declared_abc()
    # A loudest-quiet, B loudest, C between A and B → only B<->C inverts.
    measured = {LOUDNESS: {0.0: -20.0, 16.0: -10.0, 32.0: -14.0}}
    r = realize_energy(declared, measured)

    assert r is not None
    rho = r.correlate_rho[LOUDNESS]
    assert rho is not None and rho < 1.0

    loud_inversions = [i for i in r.inversions if i.correlate == LOUDNESS]
    assert len(loud_inversions) == 1
    inv = loud_inversions[0]
    # C is the higher-declared-energy section that rendered LOWER than B.
    assert inv.higher_energy_section == "C"
    assert inv.higher_energy_start_beat == 32.0
    assert inv.lower_energy_section == "B"
    assert inv.lower_energy_start_beat == 16.0
    assert inv.declared_energy_delta == pytest.approx(0.3)  # 0.9 - 0.6
    assert inv.measured_higher == -14.0
    assert inv.measured_lower == -10.0
    assert inv.measured_delta == pytest.approx(-4.0)  # inverted (< 0)


def test_perfect_monotonic_yields_rho_one_and_no_inversions():
    """Measured rank == declared rank → ρ == 1.0, zero inversions."""
    declared = _declared_abc()
    measured = {LOUDNESS: {0.0: -20.0, 16.0: -15.0, 32.0: -10.0}}
    r = realize_energy(declared, measured)

    assert r.correlate_rho[LOUDNESS] == pytest.approx(1.0)
    assert [i for i in r.inversions if i.correlate == LOUDNESS] == []


def test_ordinal_not_linear_still_rho_one():
    """A monotonic-but-curvilinear measured set still yields ρ == 1.0 — Spearman
    sees RANK, not slope (research.md §3, why Pearson was rejected). The
    measured loudness rises non-linearly but never inverts the order."""
    declared = _declared_abc()
    # Curvilinear: big jump A->B, tiny jump B->C — Pearson would underestimate,
    # Spearman reads the preserved ranking as perfect.
    measured = {LOUDNESS: {0.0: -30.0, 16.0: -12.0, 32.0: -11.5}}
    r = realize_energy(declared, measured)
    assert r.correlate_rho[LOUDNESS] == pytest.approx(1.0)
    assert [i for i in r.inversions if i.correlate == LOUDNESS] == []


# --------------------------------------------------------------------------- #
# B1 — undefined ρ contract (tied/constant) + allow_nan=False backstop
# --------------------------------------------------------------------------- #

def test_tied_constant_correlate_yields_none_not_nan(recwarn):
    """A fully-tied/constant measured correlate makes scipy return nan; the lens
    records None (NOT nan) and names the tie in skipped. No ConstantInputWarning
    leaks (it's the handled case)."""
    declared = _declared_abc()
    measured = {LOUDNESS: {0.0: -12.0, 16.0: -12.0, 32.0: -12.0}}
    r = realize_energy(declared, measured)

    assert r.correlate_rho[LOUDNESS] is None
    assert not any(
        math.isnan(v) for v in r.correlate_rho.values() if v is not None
    )
    assert any("tied/constant" in s for s in r.skipped)
    # The handled ConstantInputWarning is suppressed, not surfaced.
    from scipy.stats import ConstantInputWarning
    assert not any(isinstance(w.message, ConstantInputWarning) for w in recwarn.list)


def test_none_rho_serializes_under_allow_nan_false():
    """An EnergyRealization whose correlate_rho contains None round-trips through
    json.dumps(allow_nan=False) cleanly (→ JSON null), proving the report's
    write-path backstop accepts the lens's None-or-finite guarantee."""
    declared = _declared_abc()
    measured = {LOUDNESS: {0.0: -12.0, 16.0: -12.0, 32.0: -12.0}}
    r = realize_energy(declared, measured)
    d = _energy_realization_to_dict(r)
    # allow_nan=False is the structural backstop — must NOT raise.
    text = json.dumps(d, allow_nan=False)
    parsed = json.loads(text)
    assert parsed["correlate_rho"][LOUDNESS] is None


def test_a_stray_nan_rho_would_raise_under_allow_nan_false():
    """The backstop has teeth: a hypothetical nan in correlate_rho (a future
    regression that bypassed the None contract) makes json.dumps(allow_nan=False)
    raise — proving the write-path guard is wired, not cosmetic."""
    bad = EnergyRealization(
        correlate_rho={LOUDNESS: float("nan")},
        inversions=[],
        sections_ranked=[],
        skipped=[],
    )
    d = _energy_realization_to_dict(bad)
    with pytest.raises(ValueError):
        json.dumps(d, allow_nan=False)


# --------------------------------------------------------------------------- #
# B2 — start_beat join key (the same-named-sections lock)
# --------------------------------------------------------------------------- #

def test_same_named_sections_are_keyed_by_start_beat_not_name():
    """Two sections BOTH named "Chorus" at DIFFERENT start_beat + DIFFERENT
    declared energy (the Nobile energy-drop final chorus) with different measured
    loudness: each is paired with ITS OWN measured value (not collapsed, not
    cross-paired), and the resulting inversion names them by start_beat.

    This is the join-key lock: it PASSES under start_beat keying and FAILS under
    name keying (a name-keyed join would collapse the two "Chorus" rows)."""
    declared = [
        SectionEnergy(start_beat=0.0, name="Chorus", energy=0.9),    # hot first chorus
        SectionEnergy(start_beat=32.0, name="Verse", energy=0.5),
        SectionEnergy(start_beat=64.0, name="Chorus", energy=0.4),   # stripped final chorus
    ]
    # The first Chorus (energy 0.9) renders LOUDER; the final Chorus (0.4) renders
    # quietest — consistent with intent (no Chorus<->Chorus inversion). But the
    # final Chorus (0.4) renders LOUDER than the Verse (0.5)? No — set it quieter
    # than the verse so there's a clear, correctly-attributed inversion only if
    # the wrong section is paired. Keep it honest: final chorus is quietest.
    measured = {LOUDNESS: {0.0: -8.0, 32.0: -12.0, 64.0: -16.0}}
    r = realize_energy(declared, measured)

    # The ranked curve keeps both "Chorus" rows distinct, by start_beat.
    chorus_rows = [s for s in r.sections_ranked if s.name == "Chorus"]
    assert len(chorus_rows) == 2
    assert {s.start_beat for s in chorus_rows} == {0.0, 64.0}
    assert {s.energy for s in chorus_rows} == {0.9, 0.4}

    # Declared order by energy: final Chorus (0.4) < Verse (0.5) < first Chorus (0.9).
    # Measured: final Chorus (-16) < Verse (-12) < first Chorus (-8). Monotonic
    # with intent → ρ == 1.0, ZERO inversions. A name-keyed join would collapse
    # the two choruses (0.9 and 0.4 at the SAME key) and mis-rank, producing a
    # spurious inversion or a wrong ρ — so a clean ρ==1.0 here proves start_beat
    # keying kept them separate AND correctly paired.
    assert r.correlate_rho[LOUDNESS] == pytest.approx(1.0)
    assert r.inversions == []


def test_same_named_sections_inversion_names_by_start_beat():
    """When two same-named sections DO invert, the inversion identifies them by
    start_beat (the display name alone would be ambiguous)."""
    declared = [
        SectionEnergy(start_beat=0.0, name="Chorus", energy=0.4),
        SectionEnergy(start_beat=64.0, name="Chorus", energy=0.9),
    ]
    # The hotter (0.9) final chorus renders QUIETER than the cooler first one.
    measured = {LOUDNESS: {0.0: -8.0, 64.0: -14.0}}
    r = realize_energy(declared, measured)
    inv = [i for i in r.inversions if i.correlate == LOUDNESS]
    assert len(inv) == 1
    assert inv[0].higher_energy_start_beat == 64.0  # the hot final chorus
    assert inv[0].lower_energy_start_beat == 0.0
    assert inv[0].higher_energy_section == "Chorus"
    assert inv[0].lower_energy_section == "Chorus"


# --------------------------------------------------------------------------- #
# W2 — measured-nan symmetry
# --------------------------------------------------------------------------- #

def test_measured_nan_section_excluded_and_named():
    """A section whose MEASURED correlate is nan is excluded from that
    correlate's ρ (named in skipped), symmetric with NULL-declared exclusion; ρ
    is computed over the remaining finite sections."""
    declared = _declared_abc()
    measured = {LOUDNESS: {0.0: -20.0, 16.0: float("nan"), 32.0: -10.0}}
    r = realize_energy(declared, measured)

    # B (start_beat 16) excluded; ρ over A and C (monotonic) == 1.0. (Spearman
    # over n=2 lands at 0.9999999999999999 numerically — the lens reports the
    # raw scipy value, so the test reads it within float tolerance.)
    assert r.correlate_rho[LOUDNESS] == pytest.approx(1.0)
    assert any(
        "B" in s and "missing/nan" in s and "16" in s for s in r.skipped
    )


def test_measured_nan_drops_below_two_yields_none():
    """If excluding nan-measured sections leaves < 2 finite sections, the
    correlate's ρ is None (with a reason), not a fabricated number."""
    declared = _declared_abc()
    measured = {
        LOUDNESS: {0.0: -20.0, 16.0: float("nan"), 32.0: float("nan")},
    }
    r = realize_energy(declared, measured)
    assert r.correlate_rho[LOUDNESS] is None
    assert any("fewer than 2" in s for s in r.skipped)


def test_missing_measured_value_excluded_like_nan():
    """A section whose start_beat has NO measured entry at all (out-of-capture,
    skipped by _measure_sections) is excluded symmetrically with a nan value."""
    declared = _declared_abc()
    measured = {LOUDNESS: {0.0: -20.0, 32.0: -10.0}}  # B (16.0) absent
    r = realize_energy(declared, measured)
    assert r.correlate_rho[LOUDNESS] == pytest.approx(1.0)  # A,C monotonic
    assert any("B" in s and "16" in s for s in r.skipped)


# --------------------------------------------------------------------------- #
# <2 declared sections → None
# --------------------------------------------------------------------------- #

def test_fewer_than_two_declared_sections_returns_none():
    """Spearman needs >= 2 ranks — one declared section yields None (the caller
    records a skipped_analyses entry, never a fabricated ρ)."""
    declared = [SectionEnergy(start_beat=0.0, name="A", energy=0.5)]
    assert realize_energy(declared, {LOUDNESS: {0.0: -12.0}}) is None
    assert realize_energy([], {}) is None


# --------------------------------------------------------------------------- #
# Multi-correlate
# --------------------------------------------------------------------------- #

def test_independent_per_correlate_rho():
    """Loudness and onset_density are ranked INDEPENDENTLY (never summed into one
    intensity number — that would be a STAMP). Each gets its own ρ."""
    declared = _declared_abc()
    measured = {
        LOUDNESS: {0.0: -20.0, 16.0: -15.0, 32.0: -10.0},    # monotonic → 1.0
        ONSET_DENSITY: {0.0: 3.0, 16.0: 1.0, 32.0: 2.0},     # inverted-ish
    }
    r = realize_energy(declared, measured)
    assert r.correlate_rho[LOUDNESS] == pytest.approx(1.0)
    assert r.correlate_rho[ONSET_DENSITY] is not None
    assert r.correlate_rho[ONSET_DENSITY] < 1.0


# --------------------------------------------------------------------------- #
# DR-5 — the surfacing-floor gate (conservative default = surface everything)
# --------------------------------------------------------------------------- #

def test_default_surfacing_floor_surfaces_every_inversion():
    """The default surfacing_floor (0.0, the conservative surface-everything
    setting) keeps every genuine inversion — even a tiny one."""
    declared = _declared_abc()
    # C (0.9) renders just 0.1 LU below B (0.6) — a tiny inversion.
    measured = {LOUDNESS: {0.0: -20.0, 16.0: -10.0, 32.0: -10.1}}
    r = realize_energy(declared, measured)  # default floor 0.0
    assert len([i for i in r.inversions if i.correlate == LOUDNESS]) == 1


def test_surfacing_floor_drops_subthreshold_inversions():
    """A raised surfacing_floor (DR-5 calibration knob) drops inversions whose
    measured-delta magnitude is below it as DSP noise, while keeping larger
    ones. The lens ρ is unchanged (ρ is never gated)."""
    declared = _declared_abc()
    # C renders 0.1 below B (tiny inversion, magnitude 0.1).
    measured = {LOUDNESS: {0.0: -20.0, 16.0: -10.0, 32.0: -10.1}}
    r = realize_energy(declared, measured, surfacing_floor=1.0)
    assert [i for i in r.inversions if i.correlate == LOUDNESS] == []
    # ρ still computed over all finite sections (not gated by the floor).
    assert r.correlate_rho[LOUDNESS] is not None


# --------------------------------------------------------------------------- #
# Ruler-not-stamp lock
# --------------------------------------------------------------------------- #

def test_ruler_not_stamp_output_is_measurements_only():
    """The boundary lock: the lens output contains ONLY measurements (ρ,
    inversions, ranked declared curve, exclusion reasons) and NO re-authored
    energy / target LUFS / pass-fail grade. This test FAILS if a future edit
    makes the lens emit a verdict or a corrected curve."""
    declared = _declared_abc()
    measured = {LOUDNESS: {0.0: -20.0, 16.0: -10.0, 32.0: -14.0}}
    r = realize_energy(declared, measured)
    d = _energy_realization_to_dict(r)

    # Exactly the measurement-only key set — no extra "verdict"/"grade"/etc.
    assert set(d.keys()) == {
        "correlate_rho", "inversions", "sections_ranked", "skipped",
    }

    # No verdict/target/pass-fail vocabulary anywhere in the serialized output.
    forbidden = (
        "verdict", "grade", "pass", "fail", "target", "corrected",
        "recommended", "should", "score", "ok", "good", "bad",
    )
    flat = json.dumps(d).lower()
    for word in forbidden:
        assert word not in flat, f"ruler emitted a stamp-ish key/value: {word!r}"

    # sections_ranked echoes the DECLARED energy verbatim — the lens does not
    # rewrite it (no smoothing, no "corrected" curve).
    assert [s["energy"] for s in d["sections_ranked"]] == [0.3, 0.6, 0.9]

    # Inversions carry only measured FACTS (deltas), never a prescription.
    for inv in d["inversions"]:
        assert set(inv.keys()) == {
            "higher_energy_start_beat", "higher_energy_section",
            "lower_energy_start_beat", "lower_energy_section",
            "declared_energy_delta", "correlate",
            "measured_higher", "measured_lower", "measured_delta",
        }
