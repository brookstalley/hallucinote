"""Phase 2b — the authoring side, validated through the SHIPPED read-side lens.

The crown jewel is the CLOSED LOOP: a mechanical part, run through a declared
``PerformanceProfile``, is read by the *actual* performance lens as ``human`` —
not mechanical (it has real deviation now) and not sloppy (the deviation is 1/f-
correlated, not white). Authoring and measurement form one loop, made executable.

The other tests lock the design's load-bearing claims: structure-not-magnitude
(the verdict is invariant to the sigma dial), determinism (reproducible builds),
chord verticality, and the clamp guards.
"""
from __future__ import annotations

import pytest

from hallucinote.performance import (
    BREATH,
    HUMAN,
    LOOSE,
    PerformanceProfile,
    SectionPerf,
    analyze_performance,
    apply_profile,
    pink_noise,
)
from hallucinote.performance.correlation import STRUCTURED_ACF_MIN


def _on_grid(n, *, beat=0.5, velocity=80):
    """A dead-on-grid, single-velocity part — the lens reads it ``mechanical``."""
    return [{"pitch": 60, "start_beats": i * beat, "duration_beats": 0.25,
             "velocity": velocity, "tags": []} for i in range(n)]


def _classify(notes):
    sec = SectionPerf(name="s",
                      length_beats=max(n["start_beats"] for n in notes) + 1.0,
                      layers={"part": notes})
    return analyze_performance([sec], song_slug="t").sections[0].parts[0]


# ---------------------------------------------------------------------------
# The closed loop — mechanical → human, read by the real lens
# ---------------------------------------------------------------------------


def test_mechanical_part_becomes_human():
    mech = _on_grid(96)
    before = _classify(mech)
    assert before.classification == "mechanical"
    assert before.flat_dynamics is True

    after = _classify(apply_profile(mech, HUMAN, seed=7))
    assert after.classification == "human"
    assert after.timing_acf >= STRUCTURED_ACF_MIN     # correlated, not sloppy
    assert after.timing_stdev > 0.01                  # real deviation, not mechanical
    assert after.flat_dynamics is False               # dynamics breathe now


def test_human_realization_is_robust_across_seeds_not_a_lucky_draw():
    # At N=96 the correlation calibration puts pink-false-sloppy at ~0% — so EVERY
    # seed should read human. (The whole point of choosing a realistic part length.)
    verdicts = {_classify(apply_profile(_on_grid(96), HUMAN, seed=s)).classification
                for s in range(16)}
    assert verdicts == {"human"}


def test_realized_part_is_neither_mechanical_nor_sloppy():
    after = _classify(apply_profile(_on_grid(96), HUMAN, seed=11))
    assert after.classification not in {"mechanical", "sloppy", "insufficient-data"}


# ---------------------------------------------------------------------------
# Structure, not magnitude — the decisive design claim (§3.8)
# ---------------------------------------------------------------------------


def test_verdict_is_magnitude_invariant_but_looseness_scales():
    # All three presets read human; the human/sloppy verdict rides on correlation
    # STRUCTURE (acf), which is magnitude-invariant — while the looseness (stdev)
    # scales with the profile's sigma. This is performance-model §3.8 made a test.
    parts = {p.name: _classify(apply_profile(_on_grid(96), p, seed=3))
             for p in (BREATH, HUMAN, LOOSE)}
    assert all(part.classification == "human" for part in parts.values())
    assert (parts["breath"].timing_stdev
            < parts["human"].timing_stdev
            < parts["loose"].timing_stdev)
    # acf barely moves across a 2x magnitude span (verdict is about structure).
    acfs = [parts[n].timing_acf for n in ("breath", "human", "loose")]
    assert max(acfs) - min(acfs) < 0.05


def test_k_dial_scales_magnitude_and_zero_k_stays_mechanical():
    base = _on_grid(96)
    louder = PerformanceProfile(name="x", timing_sigma=0.02, velocity_sigma=8.0, k=2.0)
    quiet = _classify(apply_profile(base, HUMAN, seed=4))
    loud = _classify(apply_profile(base, louder, seed=4))
    assert loud.timing_stdev > quiet.timing_stdev          # k=2 ⇒ ~2x looseness
    # k=0 means "no breathing" — the part stays exactly the mechanical input.
    silent = PerformanceProfile(name="off", timing_sigma=0.02, velocity_sigma=8.0, k=0.0)
    assert _classify(apply_profile(base, silent, seed=4)).classification == "mechanical"


# ---------------------------------------------------------------------------
# Determinism + per-part streams (reproducible builds)
# ---------------------------------------------------------------------------


def test_realization_is_deterministic():
    mech = _on_grid(48)
    assert apply_profile(mech, HUMAN, seed=9) == apply_profile(mech, HUMAN, seed=9)


def test_seed_gives_independent_streams():
    mech = _on_grid(48)
    a = apply_profile(mech, HUMAN, seed=1)
    b = apply_profile(mech, HUMAN, seed=2)
    assert a != b
    # And the explicit seed overrides the profile's own seed.
    prof = PerformanceProfile(name="p", timing_sigma=0.02, velocity_sigma=8.0, seed=1)
    assert apply_profile(mech, prof) == apply_profile(mech, prof, seed=1)
    assert apply_profile(mech, prof) != apply_profile(mech, prof, seed=2)


# ---------------------------------------------------------------------------
# Musical correctness — chords move as a unit, voices breathe per note
# ---------------------------------------------------------------------------


def test_chord_onset_moves_as_a_unit():
    # Three voices share start=1.0 (a block chord) among other onsets (pitch 60);
    # after realization they must still share one onset — verticality preserved.
    chord_pitches = (72, 76, 79)
    chord = [{"pitch": p, "start_beats": 1.0, "duration_beats": 0.5,
              "velocity": 80, "tags": []} for p in chord_pitches]
    others = _on_grid(8)
    realized = apply_profile(chord + others, HUMAN, seed=5)
    chord_starts = {n["start_beats"] for n in realized if n["pitch"] in chord_pitches}
    assert len(chord_starts) == 1
    # ...but the three voices still breathe independently in velocity.
    chord_vels = {n["velocity"] for n in realized if n["pitch"] in chord_pitches}
    assert len(chord_vels) >= 2


# ---------------------------------------------------------------------------
# Guards — clamps, purity, edges
# ---------------------------------------------------------------------------


def test_input_notes_are_not_mutated():
    mech = _on_grid(16)
    snapshot = [dict(n) for n in mech]
    apply_profile(mech, HUMAN, seed=1)
    assert mech == snapshot


def test_velocity_is_clamped_to_midi_range():
    hi = [{"pitch": 60, "start_beats": i * 0.5, "duration_beats": 0.25,
           "velocity": 126, "tags": []} for i in range(32)]
    lo = [{"pitch": 60, "start_beats": i * 0.5, "duration_beats": 0.25,
           "velocity": 2, "tags": []} for i in range(32)]
    big = PerformanceProfile(name="big", timing_sigma=0.02, velocity_sigma=30.0)
    for note in apply_profile(hi, big, seed=1) + apply_profile(lo, big, seed=1):
        assert 1 <= note["velocity"] <= 127


def test_onsets_clamp_non_negative():
    # A note at absolute beat 0 must never realize to a negative start (the mutator
    # rejects those). Many seeds, in case any draws a negative downbeat offset.
    for s in range(20):
        realized = apply_profile(_on_grid(16, beat=0.5), LOOSE, seed=s)
        assert all(n["start_beats"] >= 0.0 for n in realized)


def test_timing_offsets_stay_inside_the_grid_cell():
    # Even LOOSE never pushes an onset more than half a 16th cell off, so the lens
    # recovers the deviation without snapping to a neighbour grid point.
    realized = apply_profile(_on_grid(96, beat=0.5), LOOSE, seed=2)
    for got, i in zip(realized, range(96)):
        assert abs(got["start_beats"] - i * 0.5) <= 0.08 + 1e-9


def test_empty_and_singleton_parts():
    assert apply_profile([], HUMAN) == []
    one = apply_profile(_on_grid(1), HUMAN, seed=1)
    assert len(one) == 1 and one[0]["start_beats"] >= 0.0


# ---------------------------------------------------------------------------
# PerformanceProfile — validation + the declared-intent boundary
# ---------------------------------------------------------------------------


def test_profile_validation():
    with pytest.raises(ValueError):
        PerformanceProfile(name="", timing_sigma=0.02, velocity_sigma=8.0)
    with pytest.raises(ValueError):
        PerformanceProfile(name="x", timing_sigma=-0.01, velocity_sigma=8.0)
    with pytest.raises(ValueError):
        PerformanceProfile(name="x", timing_sigma=0.02, velocity_sigma=8.0, k=-1.0)
    with pytest.raises(ValueError):
        PerformanceProfile(name="x", timing_sigma=0.02, velocity_sigma=8.0, octaves=0)


def test_profile_effective_sigmas_and_to_dict():
    p = PerformanceProfile(name="p", timing_sigma=0.02, velocity_sigma=8.0, k=1.5, seed=3)
    assert p.effective_timing_sigma == pytest.approx(0.03)
    assert p.effective_velocity_sigma == pytest.approx(12.0)
    d = p.to_dict()
    assert d == {"name": "p", "timing_sigma": 0.02, "velocity_sigma": 8.0,
                 "k": 1.5, "seed": 3, "octaves": 5}


# ---------------------------------------------------------------------------
# pink_noise — the promoted generator the correlation calibration was measured on
# ---------------------------------------------------------------------------


def test_pink_noise_is_deterministic_and_sized():
    assert pink_noise(32, seed=1) == pink_noise(32, seed=1)
    assert pink_noise(0, seed=1) == []
    assert pink_noise(-3, seed=1) == []
    assert len(pink_noise(50, seed=1)) == 50


def test_pink_noise_reads_correlated_by_the_lens_metric():
    # The promoted generator must still produce the structured series the lens
    # calls human — the contract the calibration constants depend on.
    from hallucinote.performance.correlation import lag1_autocorr
    accs = [lag1_autocorr(pink_noise(64, seed=s)) for s in range(20)]
    assert sum(accs) / len(accs) >= STRUCTURED_ACF_MIN
