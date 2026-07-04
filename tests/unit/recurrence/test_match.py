"""Unit tests for the recurrence matcher — SYNTHETIC fixtures only (test-location
convention: NO song-specific data in tests/unit/). Each variation type is recovered
on a synthetic motif + a known transform; containment, tiling, breathed jitter, and
honest non-match are pinned."""
from __future__ import annotations

import hallucinote.generators.variations as V
from hallucinote.recurrence.match import (
    _MATCH_TOL,
    match_all_in_layer,
    match_motif_in_window,
)


def _n(pitch: int, start: float, dur: float, vel: int = 80, tags=None) -> dict:
    return {"pitch": pitch, "start_beats": start, "duration_beats": dur,
            "velocity": vel, "tags": list(tags or [])}


# A simple 4-note ascending motif, one 0-based 4-beat cycle.
_MOTIF = [_n(60, 0.0, 0.5), _n(64, 1.0, 0.5), _n(67, 2.0, 0.5), _n(72, 3.0, 1.0)]


def _tile(notes, *offsets):
    """Tile a motif (or transform) at each offset into one layer."""
    out: list[dict] = []
    for off in offsets:
        out.extend(V.shift(notes, off))
    return out


def test_exact_recovery_on_tiled_shifted_layer():
    """An exact quote tiled + shifted into a layer reads `exact` (Δst=0) — the
    polyrhythm thin-slice shape: the matcher slides M across the tiling grid."""
    layer = _tile(_MOTIF, 10.0, 14.0, 18.0)
    res = match_motif_in_window(_MOTIF, layer)
    assert res is not None
    assert res.variation == "exact"
    assert res.coverage == 1.0
    assert res.transpose == 0


def test_transpose_recovery():
    """A constant +5-semitone shift reads `transpose +5`, intervals preserved."""
    layer = _tile(V.transpose(_MOTIF, 5), 0.0)
    res = match_motif_in_window(_MOTIF, layer)
    assert res is not None
    assert res.variation == "transpose +5"
    assert res.transpose == 5
    assert res.coverage == 1.0


def test_octave_down_transpose():
    """The chorus2 escalation shape: an octave-down copy reads `transpose -12`."""
    res = match_motif_in_window(_MOTIF, V.transpose(_MOTIF, -12))
    assert res is not None
    assert res.variation == "transpose -12"
    assert res.transpose == -12


def test_augment_recovery():
    """A 2× augment (onsets AND durations scaled) reads `augment ×2`."""
    res = match_motif_in_window(_MOTIF, V.augment(_MOTIF, 2.0))
    assert res is not None
    assert res.variation == "augment ×2"
    assert res.factor == 2.0
    assert res.coverage == 1.0


def test_diminish_recovery():
    """A 2× diminish reads `diminish ×2` (factor reported as the inverse)."""
    res = match_motif_in_window(_MOTIF, V.diminish(_MOTIF, 2.0))
    assert res is not None
    assert res.variation == "diminish ×2"
    assert res.factor == 2.0


def test_invert_recovery():
    """An inversion around the first pitch reads `invert`."""
    res = match_motif_in_window(_MOTIF, V.invert(_MOTIF))
    assert res is not None
    assert res.variation == "invert"
    assert res.coverage == 1.0


def test_retrograde_recovery():
    """A time-reversal reads `retrograde` — M's span derived from M (N2)."""
    res = match_motif_in_window(_MOTIF, V.retrograde(_MOTIF))
    assert res is not None
    assert res.variation == "retrograde"
    assert res.coverage == 1.0


def test_fragment_recovery():
    """A bare fragment [0,2) of M (its first half) reads `fragment[..)` with
    partial coverage — NOT a whole-motif op."""
    frag = V.fragment(_MOTIF, 0.0, 2.0)  # first two notes
    res = match_motif_in_window(_MOTIF, frag)
    assert res is not None
    assert res.variation.startswith("fragment[")
    assert res.coverage < 1.0


def test_diminish_then_fragment_composition():
    """The integration-trade 2-op shape: diminish(fragment(M, 0, half), 2) reads
    `diminish∘fragment ×2` (the bounded composition DR-2)."""
    frag = V.fragment(_MOTIF, 0.0, 2.0)   # first half (2 notes)
    transformed = V.diminish(frag, 2.0)
    res = match_motif_in_window(_MOTIF, transformed)
    assert res is not None
    assert res.variation == "diminish∘fragment ×2"
    assert res.factor == 2.0


def test_containment_extra_notes_still_reads_exact():
    """W3 regression: a motif tiled into a layer that ALSO carries extra non-motif
    notes (the climax-organ superset shape) reads `exact` via containment — the
    extra notes do not collapse it to `derived`."""
    layer = _tile(_MOTIF, 0.0, 4.0)
    # Extra sustained chord hits in the SAME layer (the FUSION_CHORD analogue).
    layer += [_n(48, 0.0, 8.0), _n(55, 0.0, 8.0), _n(50, 4.0, 4.0)]
    res = match_motif_in_window(_MOTIF, layer)
    assert res is not None
    assert res.variation == "exact"
    assert res.coverage == 1.0


def test_velocity_difference_does_not_change_reading():
    """DR-4 regression: a recall differing ONLY in velocity reads `exact` — velocity
    is not recurrence-identity-bearing."""
    boosted = [{**n, "velocity": 127} for n in _MOTIF]
    res = match_motif_in_window(_MOTIF, boosted)
    assert res is not None
    assert res.variation == "exact"


def test_unrelated_layer_no_recall():
    """A layer with none of M's structure reports NO recall (no false positive)."""
    unrelated = [_n(40, 0.0, 1.0), _n(41, 1.0, 1.0), _n(38, 2.0, 1.0), _n(39, 3.0, 1.0)]
    assert match_motif_in_window(_MOTIF, unrelated) is None


def test_partial_above_floor_reads_derived():
    """A near-match the matcher cannot name as a clean op OR a contiguous fragment,
    but covering >= the floor, reads `derived` with its coverage — honest, never
    silently dropped, never a clean op. Here M's onsets 0 and 2 appear (the
    on-pattern subset) but the interior notes 1 and 3 are absent, so NEITHER half is
    a complete fragment — the only honest reading is a derived partial. This is the
    real busy-layer shape (an organ bubble incidentally carrying some of the motif's
    pitches at the right relative onsets)."""
    partial = [_n(60, 0.0, 0.5), _n(67, 2.0, 0.5)]
    res = match_motif_in_window(_MOTIF, partial)
    assert res is not None
    assert res.variation == "derived"
    assert 0.5 <= res.coverage < 1.0


def test_breathed_jitter_within_tolerance_recovers_augment():
    """B1 regression — the breathed-outro shape, with the REAL breath pipeline (the
    C7 calibrate-against-the-real-pipeline discipline): an `augment ×2` recall run
    through the actual `apply_profile(BREATH)` (the correlated 1/f onset perturbation
    the song's outro `05 Lead` carries) still reads `augment ×2`. Breath jitter does
    not collapse the recall to `derived`."""
    from hallucinote.performance.realization import BREATH, apply_profile

    aug = V.augment(_MOTIF, 2.0)
    breathed = apply_profile(aug, BREATH, seed=5005)   # same shape as _seed_for(outro, lead)
    res = match_motif_in_window(_MOTIF, breathed)
    assert res is not None
    assert res.variation == "augment ×2"


def test_jitter_beyond_tolerance_does_not_read_clean_op():
    """B1 boundary: an augment recall with an interior note displaced WELL BEYOND the
    calibrated tolerance (3× tol) does not read a clean whole-motif `augment ×2` — no
    single clean factor covers every note, so the matcher honestly degrades to a
    lower-coverage partial / `derived`, never a false full quote. The tolerance is
    the boundary, and the degradation is reported, not hidden."""
    aug = V.augment(_MOTIF, 2.0)   # onsets 0, 2, 4, 6
    # Displace the 3rd note (onset 4) by 3× tolerance — no clean ×f maps all four.
    broken = [
        {**n, "start_beats": n["start_beats"] + (_MATCH_TOL * 3.0 if i == 2 else 0.0)}
        for i, n in enumerate(aug)
    ]
    res = match_motif_in_window(_MOTIF, broken)
    # The FULL `augment ×2` (whole-motif, coverage 1.0) is NOT falsely reported.
    assert res is None or res.coverage < 1.0 or res.variation == "derived"


def test_match_all_in_layer_reports_distinct_variations():
    """A layer that quotes M as BOTH a bare fragment AND a diminish∘fragment reports
    BOTH distinct variations — neither silently dropped (N1, the integration-trade
    shape). A full-motif quote elsewhere is not required for this."""
    frag = V.fragment(_MOTIF, 0.0, 2.0)
    layer = _tile(frag, 0.0)                       # bare fragment at 0
    layer += _tile(V.diminish(frag, 2.0), 8.0)     # diminish∘fragment at 8
    results = match_all_in_layer(_MOTIF, layer)
    variations = {r.variation for r in results}
    assert any(v.startswith("fragment[") for v in variations)
    assert "diminish∘fragment ×2" in variations


def test_full_quote_subsumes_its_own_fragments():
    """When a layer carries the WHOLE motif (coverage 1.0), its internal halves are
    NOT separately reported — a fragment of an already-reported full quote is not an
    independent recall (keeps the read meaningful)."""
    layer = _tile(_MOTIF, 0.0)
    results = match_all_in_layer(_MOTIF, layer)
    assert all(r.coverage >= 1.0 - 1e-9 for r in results)
    assert any(r.variation == "exact" for r in results)


def test_zero_interval_motif_recalls_against_repeated_pitch_layer():
    """REC-4Z8Q: a repeated-pitch motif (pedal/drone/ostinato — interval set {0})
    must recall against a layer that repeats that pitch. The interval-overlap
    fast-skip computed layer_intervals over DISTINCT pitches, so a layer's repeated
    pitch produced no 0-interval and the motif was falsely skipped (returned [])
    before any per-onset scan."""
    pedal = [_n(60, 0.0, 0.5), _n(60, 1.0, 0.5), _n(60, 2.0, 0.5)]
    layer = _tile(pedal, 0.0, 4.0)  # the pedal recurs at beat 0 and beat 4
    results = match_all_in_layer(pedal, layer)
    assert results, (
        "a repeated-pitch motif must recall against a layer that repeats the pitch"
    )
    assert any(r.coverage >= 1.0 - 1e-9 for r in results)


def test_fast_skip_preserved_for_multi_interval_motif_vs_disjoint_layer():
    """The zero-interval exemption (REC-4Z8Q) must not defeat the dominant-cost
    fast skip: a pitched multi-interval motif against a layer that shares NO
    interval still returns [] (no false recall) — the drum-layer skip case the
    optimization exists for."""
    # _MOTIF's pitch-pair intervals are {3,4,5,7,8,12}. A percussion-style layer
    # on pitches 36/37/38 has intervals {1,2}, disjoint from the motif's.
    perc = [_n(36, 0.0, 0.25), _n(37, 1.0, 0.25), _n(38, 2.0, 0.25),
            _n(36, 4.0, 0.25), _n(37, 5.0, 0.25), _n(38, 6.0, 0.25)]
    assert match_all_in_layer(_MOTIF, perc) == []
