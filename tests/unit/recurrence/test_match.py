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
    # The partial NAMES the op it partially matches (here the untransposed quote)
    # rather than reading as a nameless `derived`.
    assert res.variation == "derived (exact, 0.50)"
    assert 0.5 <= res.coverage < 1.0
    # The TIER rides on the field, not on the label's prefix — the wrapper used to
    # rebuild its result without `derived=`, so this exported entry point reported
    # every tier-4 guess as a clean recall to any consumer following the documented
    # contract.
    assert res.derived is True


def test_a_clean_op_is_not_derived_through_the_window_wrapper():
    """The other half of the tier signal: a named op must come back `derived=False`,
    or reading the field would be no better than prefix-matching the label."""
    res = match_motif_in_window(_MOTIF, V.transpose(_MOTIF, -12))
    assert res is not None
    assert res.derived is False
    assert res.coverage == 1.0


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


# --------------------------------------------------------------------------
# The FACTORED (pitch_map, time_map) search: composed recalls, the independently
# relaxable duration axis, and partials that name their op.
# --------------------------------------------------------------------------

# The `missing` coda shape, rebuilt synthetically (test-location convention: no
# song data in tests/unit/). A 3-note motif whose payoff recall returns an octave up
# with its onset spacing exactly halved while the notes keep their sung lengths —
# `transpose(+12) ∘ onset-diminish(0.5)` with free durations.
_REACH = [_n(59, 0.0, 1.5), _n(63, 4.0, 2.0), _n(66, 8.0, 1.5)]
_REACH_CODA = [_n(71, 32.0, 1.5), _n(75, 34.0, 1.5), _n(78, 36.0, 1.0)]


def test_transposed_and_onset_diminished_recall_is_named():
    """The payoff-recall shape: a motif restated an octave up with its onset spacing
    halved but its durations freely re-sung is recovered as the COMPOSED op, with the
    duration relaxation reported rather than hidden.

    Regression: the scale-candidate generator paired on RAW pitch equality, so a
    recall that had moved on BOTH axes proposed no factor at all and the whole layer
    read as no recall — the composer could not tell "my recall doesn't land" from
    "the lens can't see it"."""
    layer = _REACH_CODA + [_n(76, 38.0, 2.0)]   # + the landed coda extension note
    results = match_all_in_layer(_REACH, layer)
    assert results, "the composed transpose+diminish recall must not read as no recall"
    top = results[0]
    assert top.coverage == 1.0
    assert top.variation == "transpose +12 ∘ diminish ×2 (durations free)"
    assert top.transpose == 12
    assert top.factor == 2.0
    assert top.duration_match is False
    assert top.cell_offset_beats == 32.0


def test_free_durations_require_full_onset_and_pitch_coverage():
    """R4 guard: relaxing the duration axis is not a rubber stamp. The same shape with
    ONE pitch wrong does not become a full free-duration match — it degrades to a
    partial that names the op it nearly matched."""
    broken = [_n(71, 32.0, 1.5), _n(74, 34.0, 1.5), _n(78, 36.0, 1.0)]
    results = match_all_in_layer(_REACH, broken)
    assert results
    assert all(r.coverage < 1.0 for r in results)
    assert not any("durations free" in r.variation for r in results)
    assert results[0].variation == "derived (transpose +12 ∘ diminish ×2, 0.67)"


def test_free_duration_tier_not_entered_for_two_note_motifs():
    """R4's >= 3-note gate: on a two-note motif, a free duration axis would leave only
    two onsets and two pitches deciding the match — too little evidence to call a
    recall. The tier is not entered, so no full-coverage free-duration reading appears."""
    two = [_n(59, 0.0, 1.5), _n(66, 8.0, 1.5)]
    layer = [_n(71, 32.0, 1.5), _n(78, 36.0, 1.0)]   # +12, onsets halved, durations free
    results = match_all_in_layer(two, layer)
    assert not any("durations free" in r.variation for r in results)
    assert all(r.coverage < 1.0 for r in results)


def test_partial_recall_names_its_op():
    """R6/R8: an abandoned 2-of-3 quote — the authored "the attempt breaks off" shape —
    surfaces as a partial that NAMES the transform it partially matches, so the review
    can say the lens sees the attempt, not just that something derived happened."""
    attempt = [_n(71, 0.0, 1.5), _n(75, 2.0, 1.5)]   # the first two notes, +12, halved
    res = match_motif_in_window(_REACH, attempt)
    assert res is not None
    assert res.variation.startswith("derived (")
    assert "transpose +12" in res.variation
    assert 0.5 <= res.coverage < 1.0


def test_existing_calibration_recalls_are_unchanged():
    """The three calibrated recalls the module docstring pins keep their EXACT labels
    and coverages under the factored search — a machine-tight `augment ×2` must not
    be re-labelled as something composed, and the containment `exact` must not
    degrade."""
    from hallucinote.performance.realization import BREATH, apply_profile

    # machine-tight augment, and the same augment run through the real breath pipeline
    tight = match_motif_in_window(_MOTIF, V.augment(_MOTIF, 2.0))
    assert tight is not None and tight.variation == "augment ×2"
    assert tight.coverage == 1.0 and tight.duration_match is True
    breathed = match_motif_in_window(
        _MOTIF, apply_profile(V.augment(_MOTIF, 2.0), BREATH, seed=5005))
    assert breathed is not None and breathed.variation == "augment ×2"
    assert breathed.coverage == 1.0

    # machine-tight diminish∘fragment
    trade = match_motif_in_window(_MOTIF, V.diminish(V.fragment(_MOTIF, 0.0, 2.0), 2.0))
    assert trade is not None and trade.variation == "diminish∘fragment ×2"
    assert trade.coverage == 0.5

    # containment `exact` amid extra non-motif notes in the same layer
    busy = _tile(_MOTIF, 0.0, 4.0) + [_n(48, 0.0, 8.0), _n(55, 0.0, 8.0), _n(50, 4.0, 4.0)]
    superset = match_motif_in_window(_MOTIF, busy)
    assert superset is not None and superset.variation == "exact"
    assert superset.coverage == 1.0


def test_busy_layer_scan_stays_bounded(monkeypatch):
    """R3: the factored search costs no more per alignment than the enumerated one did.

    Counted, not timed (a wall-clock assertion on an 800-onset layer is a flake): the
    disjoint drum layer never reaches a containment probe at all (the interval
    fast-skip still fires), and a busy PITCHED layer's probe count stays bounded by a
    per-alignment constant — the closed Δ set × the closed factor set — rather than
    growing with the layer."""
    import hallucinote.recurrence.match as M

    calls = {"n": 0}
    real = M._contains

    def counting(*a, **kw):
        calls["n"] += 1
        return real(*a, **kw)

    monkeypatch.setattr(M, "_contains", counting)

    # 800 onsets on percussion pitches disjoint from the motif's interval set.
    drums = [_n(36 + (i % 3), i * 0.25, 0.25) for i in range(800)]
    assert M.match_all_in_layer(_MOTIF, drums) == []
    assert calls["n"] == 0, "the interval fast-skip must still cut the drum layer"

    # A busy pitched layer DOES scan; the cost stays a constant per alignment.
    calls["n"] = 0
    busy = [_n(60 + (i % 13), i * 0.5, 0.25) for i in range(200)]
    M.match_all_in_layer(_MOTIF, busy)
    alignments = len({n["start_beats"] for n in busy})
    assert calls["n"] <= 120 * alignments


# A 6-note motif, so its natural halves are 3 notes each — long enough for a
# TRANSPOSED fragment to still be evidence.
_LONG = [_n(60, 0.0, 0.5), _n(62, 1.0, 0.5), _n(64, 2.0, 0.5),
         _n(67, 3.0, 0.5), _n(69, 4.0, 0.5), _n(71, 5.0, 1.0)]


def test_transposed_fragment_is_recovered_when_the_fragment_is_evidence():
    """D2: a fragment quoted a fifth up is still that fragment. Requiring the fragment
    to be UNTRANSPOSED made every transposed partial quote invisible — the same
    whitelist failure as the composed whole-motif recall."""
    frag = V.fragment(_LONG, 0.0, 3.0)        # the first three notes
    res = match_motif_in_window(_LONG, V.transpose(frag, 7))
    assert res is not None
    assert res.variation == "transpose +7 ∘ fragment[0,2.5)"
    assert res.coverage == 0.5


def test_transposed_fragment_below_the_evidence_floor_does_not_inflate_a_busy_layer():
    """The other side of the same rule: a TWO-note fragment under a free pitch map is
    only "some interval occurs somewhere", which the layer-level interval fast-skip
    already establishes. On a busy layer it would otherwise match at a dozen
    transpositions and bury the real recall under near-duplicates, so the composed
    search carries the same >= 3-note evidence floor the free-duration tier does.

    A dense chromatic run against a 4-note motif (halves of two notes each) must
    report the untransposed reading only — not one per transposition."""
    chromatic = [_n(60 + (i % 13), i * 0.25, 0.25) for i in range(400)]
    results = match_all_in_layer(_MOTIF, chromatic)
    assert [r.variation for r in results] == ["fragment[0,1.5)"]
