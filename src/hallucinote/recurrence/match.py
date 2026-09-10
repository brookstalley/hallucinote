"""hallucinote.recurrence.match — the directed transform-and-match core.

The arithmetic heart of the recurrence READ side: given a registered motif M (a
single canonical 0-based cycle) and a section's realized layer L (tiled, shifted,
possibly breathed, possibly carrying extra non-motif notes), answer *was M
recalled here, and as which variation?* — by APPLYING the closed six-op variation
algebra (``generators.variations``) to M and testing for its occurrence in L.

This is a DIRECTED match against a KNOWN query (the registry), not undirected
pattern mining (research.md §1): we own both the query motif AND the transform
vocabulary, so the read is exact, render-free, pure-stdlib — no corpus, no model.

Three facts shape the algorithm (all verified against the real sun-zone-done
fixtures — design.md §4):

  * **Tiling (research.md §3, learnings.md "Variation ops are tiling-safe only on
    single-cycle motifs").** M is one clean cycle; L is M tiled across the section
    and shifted to the section start. The matcher slides M's span across the tiling
    grid rather than comparing whole spans (which false-negatives).
  * **Containment, not equality (W3).** A cell window may carry extra non-motif
    notes (the climax ``04 Organ`` layer tiles the polyrhythm recap AND adds
    sustained ``FUSION_CHORD`` hits in the same layer). The test is *M (under the
    transform) ⊆ the cell window* — extra notes are allowed, so the overlapped late
    cells still read the recall, not ``derived``.
  * **Breathed jitter (B1).** The outro ``05 Lead`` is breathed via ``apply_profile``
    (a correlated ≈1/f onset perturbation) BEFORE it enters the arrangement, so its
    onsets sit off exact beats. The matcher compares relative-onset signatures with
    a CALIBRATED tolerance (a per-note onset/duration residual budget), not an
    exact-grid test — see ``_MATCH_TOL`` below.

Identity is ``(relative-onset, pitch, duration)``; velocity and tags are NOT
recurrence-identity-bearing (DR-4) — the outro recall is velocity-softened and the
climax recap velocity-boosted, yet both are the same motif. The duration axis is
INDEPENDENTLY RELAXABLE and the relaxation is REPORTED: a recall whose relative
onsets and pitches match completely but whose durations are freely re-sung (the
common expressive-recapitulation shape — the arrival statement compresses the
rhythm while the notes keep their sung lengths) reads as its op with a
``(durations free)`` qualifier and ``duration_match=False``, never as no recall.

The transform search is FACTORED, not an enumerated list of named ops: a candidate
is a ``(pitch_map, time_map)`` pair, where ``pitch_map`` is a constant transpose Δst
(Δ=0 = an exact quote) or an inversion about an axis, and ``time_map`` is identity,
a scale ×f from the closed factor set, a retrograde, or a natural fragment of M. Every
named op is a POINT in that product (``exact`` = ``(Δ=0, identity)``, ``diminish ×2``
= ``(Δ=0, scale 0.5)``), so composed recalls — ``transpose +12 ∘ diminish ×2``,
``transpose ∘ fragment``, ``invert ∘ diminish`` — fall out of the same search and the
label is COMPOSED from the two maps rather than hand-listed. Both axes stay
anchor-derived (Δ from the window notes at relative onset ≈ 0, f snapped to
``_SCALE_FACTORS``), so the per-alignment cost stays bounded on busy layers.

A partial recall names the op it partially matches — ``derived (transpose +12 ∘
diminish ×2, 0.67)`` — rather than a nameless ``derived``: degradation is along the
whole product, not along one axis.

A RULER, not a stamp: this module measures and names; it never edits a note and
never decides whether a recall *should* be there.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

NoteDict = dict[str, Any]
Triple = tuple[float, int, float]  # (start_beats, pitch, duration_beats)

# --------------------------------------------------------------------------
# The single calibrated match tolerance (Chunk 1 step 4 — PINNED from the
# measured WORST-CASE residual, the BREATHED outro `05 Lead` `augment ×2`).
#
# Measured (calibration print over the REAL sun-zone-done, all three recalls):
#   * polyrhythm-cloud  vs climax `04 Organ`  — onset residual 0.0, dur 0.0
#       (machine-tight; the integration stays unbreathed, build.py:1300)
#   * no-time-stab      vs trade `05 Lead`     — onset residual 0.0, dur 0.0
#       (machine-tight `diminish∘fragment ×2`)
#   * no-time-stab      vs BREATHED outro `05 Lead` `augment ×2`
#       — worst per-note onset residual ≈ 0.0322 beats (apply_profile / BREATH,
#       seed _seed_for("outro","05 Lead")); duration residual 0.0 (BREATH perturbs
#       onset + velocity, not duration).
#
# The tolerance is pinned to absorb the breathed worst case (0.0322) with headroom
# so a clean `augment ×2` recovers as `augment ×2`, not `derived`, while staying
# far below the 1-beat note spacing (no false cross-note match) and far below the
# 2× SCALE that distinguishes the augment from the authored cycle. NOT `_ONSET_EPS`
# (the machine-tight integration recalls measure ~0, but the SINGLE tolerance must
# cover the breathed outro). NOT a guess — the measured 0.0322 beat breath residual
# is the load-bearing number this constant exists to absorb (~3× headroom).
_MATCH_TOL = 0.1

# Below this fraction of M's notes matched (under the best transform), no recall
# is reported for that (motif, cell) — a clean negative. At/above it but with no
# clean op recoverable, the recall is reported `derived` with its coverage (an
# honest partial, never a silent drop — design.md §4 step 5). A reporting floor
# mirroring `theory.lint`'s `out_of_chord_warn`, NOT a gate.
_COVERAGE_FLOOR = 0.5


@dataclass(frozen=True)
class MatchResult:
    """One (motif, cell) reading: the recovered variation + where + how complete.

    ``variation`` is the human-facing label COMPOSED from the recovered
    ``(pitch_map, time_map)`` pair: a bare pitch map (``exact`` / ``transpose Δst`` /
    ``invert``), a bare time map (``augment ×f`` / ``diminish ×f`` / ``retrograde`` /
    ``fragment[a,b)`` / ``diminish∘fragment ×f``), or the two joined with ``∘``
    (``transpose +12 ∘ diminish ×2``). A partial recall names the op it partially
    matches — ``derived (<op>, <coverage>)``. ``coverage`` is the fraction of M's
    notes accounted for (1.0 for a clean op; <1.0 for a partial or a fragment, which
    covers only its sub-window of M). ``cell_offset_beats`` is the recall's onset
    within the layer (absolute, section-relative). ``transpose`` carries the Δst for
    a transpose; ``factor`` the scale for augment/diminish; the rest are ``None``.

    ``duration_match`` is False when the recall matched on ``(relative-onset, pitch)``
    alone and its durations were freely re-sung — the label then carries a
    ``(durations free)`` qualifier. The distinction stays VISIBLE rather than being
    dropped from the identity triple, so an augmentation is never confused with an
    onset-only compression.

    ``derived`` marks the tier-4 fallback: no clean op was recoverable, so the reading
    is a partial account of M under the op it came closest to. It is the honest
    difference between "the layer contains this named sub-window of M" (a fragment —
    a structured claim with its own evidence floor) and "this is the most of M any op
    could explain" — two readings that can carry the SAME coverage number and mean
    very different things. Consumers weighing how much a reading is worth read this,
    never the ``derived (`` prefix of the human-facing label."""

    variation: str
    coverage: float
    cell_offset_beats: float
    transpose: int | None = None
    factor: float | None = None
    duration_match: bool = True
    derived: bool = False


def _signature(notes: Sequence[NoteDict]) -> list[Triple]:
    """Reduce notes to an onset-sorted ``(start, pitch, duration)`` list — the
    recurrence-identity signature (velocity + tags excluded, DR-4)."""
    return sorted(
        (
            (float(n["start_beats"]), int(n["pitch"]), float(n["duration_beats"]))
            for n in notes
        ),
        key=lambda spd: (spd[0], spd[1], spd[2]),
    )


def _rebased(sig: list[Triple]) -> list[Triple]:
    """Subtract the first onset so absolute placement (`shift`) is factored out —
    `shift` is the placement utility, not a recurrence-identity change (§4 step 1)."""
    if not sig:
        return []
    t0 = sig[0][0]
    return [(s - t0, p, d) for (s, p, d) in sig]


def _onset_extent(sig: list[Triple]) -> float:
    """First onset -> last onset (the augment onset-scaling reference, N2 — derived
    from the side we own, M, never the realized cell)."""
    if not sig:
        return 0.0
    return sig[-1][0] - sig[0][0]


def _within(a: float, b: float, tol: float) -> bool:
    return abs(a - b) <= tol


def _contains(
    window: list[Triple],
    pattern: list[Triple],
    *,
    tol: float,
    match_duration: bool,
) -> int:
    """Count how many pattern notes are PRESENT in the window (containment, not
    equality — W3): for each pattern ``(start, pitch, dur)`` find a window note with
    the same pitch whose onset is within ``tol`` (and, when ``match_duration``,
    whose duration is within ``tol`` of ``dur``). Each window note is consumed at
    most once. Extra window notes are allowed. Returns the matched-pattern count."""
    used = [False] * len(window)
    matched = 0
    for (ps, pp, pd) in pattern:
        best = -1
        best_err = tol + 1.0
        for i, (ws, wp, wd) in enumerate(window):
            if used[i] or wp != pp:
                continue
            if not _within(ws, ps, tol):
                continue
            if match_duration and not _within(wd, pd, tol):
                continue
            err = abs(ws - ps) + (abs(wd - pd) if match_duration else 0.0)
            if err < best_err:
                best_err = err
                best = i
        if best >= 0:
            used[best] = True
            matched += 1
    return matched


# --------------------------------------------------------------------------
# The factored search space: a candidate transform is a (pitch_map, time_map)
# pair. Both axes are ANCHOR-DERIVED, which is what keeps the per-alignment cost
# bounded on busy layers (the integration drums carry 800+ onsets).
# --------------------------------------------------------------------------


def _transpose_candidates(
    rel_pattern: list[Triple], placed: list[Triple], *, tol: float
) -> list[int]:
    """The anchor-viable constant pitch shifts Δst at one window alignment.

    The window is rebased so the ANCHOR onset = 0, and pattern note 0 sits at relative
    onset 0, so a viable Δst must map that note onto a window note at onset ≈ 0
    (within ``tol``). Probing only those deltas (usually 1-2) instead of every window
    pitch is what bounds the per-alignment cost on busy layers — a delta that cannot
    even match note 0 cannot be the recall's transpose. Ascending, so the smallest
    viable delta wins a tie."""
    if not rel_pattern or not placed:
        return []
    p0 = rel_pattern[0][1]
    return sorted({wp - p0 for (ws, wp, _wd) in placed if abs(ws) <= tol})


def _invert_axes(
    rel_pattern: list[Triple], placed: list[Triple], *, tol: float
) -> list[int]:
    """The anchor-viable inversion axes (``p' = 2*axis - p``): M's first pitch
    (``variations.invert``'s default) plus every axis that lands inverted-note-0 on a
    window pitch at the anchor onset. Same bounding argument as
    :func:`_transpose_candidates` — an axis that cannot place note 0 cannot be the
    recall's inversion."""
    if not rel_pattern or not placed:
        return []
    p0 = rel_pattern[0][1]
    axes = {p0}
    for (ws, wp, _wd) in placed:
        if abs(ws) <= tol and (wp + p0) % 2 == 0:
            axes.add((wp + p0) // 2)
    return sorted(axes)


# The augment/diminish factors the matcher recovers — the closed set the corpus
# uses (DR-2: single-op + the bounded 2-op fragment scales the fixtures need). A
# recovered ratio is accepted only if it lands within tolerance of one of these, so
# the candidate set per alignment is BOUNDED (not O(notes²)) — the read stays fast on
# busy layers (the integration drums carry 800+ onsets). Widen only when a real song
# forces a new factor (DISCOVERED-FROM-FRICTION).
_SCALE_FACTORS = (0.25, 0.5, 1.5, 2.0, 3.0, 4.0)
_SCALE_SNAP = 0.05


def _scale_candidates(
    placed: list[Triple], rel_pattern: list[Triple], *, delta: int = 0
) -> list[float]:
    """The bounded set of augment/diminish factors f to test at a window alignment,
    against the pattern AS THE PITCH MAP LEAVES IT.

    Propose f from pairing EACH motif onset (>0) against each window onset whose pitch
    is the pattern's pitch under the pitch map — ``wp == mp + delta`` (robust to
    trailing/tiled extras AND per-note breath jitter — a single span lever-arm
    amplifies one note's jitter, B1) — then KEEP only ratios within ``_SCALE_SNAP`` of
    a recognised ``_SCALE_FACTORS`` value.

    ``delta`` is the load-bearing half: pairing on RAW pitch equality proposes NO
    factor at all for a recall that is transposed AND scaled (its pitches share none
    of M's), so the time axis was invisible whenever the pitch axis had moved. Δ is
    derived first from the anchor note, then the onset pairs are matched under it. An
    inversion passes its already-inverted pattern with ``delta=0``.

    The candidate set stays bounded by the closed factor set (DR-2) regardless of
    layer size, so a busy 800-onset layer doesn't trigger O(notes²) scale probes;
    running it once per anchor-viable Δ (typically 1-2) keeps that bound. The caller's
    ``_scale_match`` then verifies full containment per surviving candidate."""
    found: set[float] = set()
    for (ms, mp, _md) in rel_pattern:
        if ms <= 0:
            continue
        for (ws, wp, _wd) in placed:
            if wp == mp + delta and ws > 0:
                ratio = ws / ms
                for fac in _SCALE_FACTORS:
                    if abs(ratio - fac) <= _SCALE_SNAP:
                        found.add(fac)
    return sorted(found)


def _scale_match(
    placed: list[Triple],
    rel_pattern: list[Triple],
    factor: float,
    *,
    tol: float,
    match_duration: bool = True,
) -> int:
    """Containment count of the (already pitch-mapped) pattern scaled by ``factor``
    against the alignment-relative window: onsets AND durations scale.

    ``match_duration=False`` relaxes the DURATION axis only — the onsets and pitches
    still have to land. That is the free-duration probe: a recall whose rhythm
    compressed but whose notes kept their sung lengths (the ``missing`` coda's
    ``transpose +12 ∘ diminish ×2``) matches on onset and pitch and fails only the
    duration residual. Its caller enters this tier only when the strict pass found
    nothing at the alignment, and reports the relaxation rather than hiding it."""
    scaled = [(s * factor, p, d * factor) for (s, p, d) in rel_pattern]
    return _contains(placed, scaled, tol=tol, match_duration=match_duration)


def _retrograde_pattern(motif_sig: list[Triple]) -> list[Triple]:
    """M retrograded, rebased — the time-axis reversal. M's span comes from M itself
    (N2): each onset becomes ``span - (start + dur)`` (``variations.retrograde``)."""
    if not motif_sig:
        return []
    span = max(s + d for (s, _p, d) in motif_sig)
    retro = sorted(
        ((span - (s + d), p, d) for (s, p, d) in motif_sig),
        key=lambda spd: (spd[0], spd[1], spd[2]),
    )
    return _rebased(retro)


def _clean_factor(f: float) -> float:
    """Snap a recovered factor to a nearby clean value so the label reads ``×2`` not
    ``×1.998`` under breathed duration jitter; falls back to 3-place rounding."""
    nearest = round(f * 2.0) / 2.0  # nearest half-integer (covers ×2, ×1.5, ×0.5)
    if abs(f - nearest) <= 0.05:
        return nearest
    return round(f, 3)


def _fmt_factor(f: float) -> str:
    return str(int(f)) if abs(f - round(f)) < 1e-9 else f"{f:g}"


def _fmt_num(x: float) -> str:
    return str(int(x)) if abs(x - round(x)) < 1e-9 else f"{x:g}"


# --------------------------------------------------------------------------
# Label composition — ONE place builds every variation string, so a composed op
# reads the same way whichever probe recovered it.
# --------------------------------------------------------------------------


def _pitch_label(delta: int | None) -> str:
    """The pitch map's name: ``""`` for an untransposed quote (the identity map adds
    nothing to the label), ``transpose Δst``, or ``invert`` (``delta is None``)."""
    if delta is None:
        return "invert"
    return "" if delta == 0 else f"transpose {delta:+d}"


def _scale_label(factor: float) -> str:
    """A recovered onset/duration scale named as augment (f>=1) or diminish (f<1,
    reported as ``diminish ×(1/f)``)."""
    if factor >= 1.0:
        return f"augment ×{_fmt_factor(_clean_factor(factor))}"
    return f"diminish ×{_fmt_factor(_clean_factor(1.0 / factor))}"


def _scale_value(factor: float) -> float:
    """The ``factor`` field for a recovered scale — always >= 1 (a diminish reports
    its inverse), matching the label."""
    return _clean_factor(factor if factor >= 1.0 else 1.0 / factor)


def _label(pitch_label: str, time_label: str, *, duration_match: bool = True) -> str:
    """Compose the human-facing variation name from the two axes.

    Both identity -> ``exact``; one axis alone -> that axis's name; both -> joined
    with ``∘``. A relaxed duration axis (R4) appends the ``(durations free)``
    qualifier, so the reader can always tell an augmentation (durations scaled with
    the onsets) from an onset-only compression."""
    if pitch_label and time_label:
        label = f"{pitch_label} ∘ {time_label}"
    else:
        label = pitch_label or time_label or "exact"
    return label if duration_match else f"{label} (durations free)"


def _derived_label(op_label: str, coverage: float) -> str:
    """A partial recall NAMES the op it partially matches — ``derived (transpose +12 ∘
    diminish ×2, 0.67)`` — instead of a nameless ``derived``, so the composer can see
    WHICH recall nearly landed, not just that something did."""
    return f"derived ({op_label}, {coverage:.2f})"


# One entry per anchor-viable pitch map applied to an ALREADY TIME-MAPPED pattern:
# ``(label, Δ-for-reporting, the mapped pattern, the pattern `_scale_candidates`
# should pair on, that pairing's Δ)``. The Δ set is derived from the pattern AS THE
# TIME MAP LEAVES IT, because the time map decides WHICH note sits at relative onset
# 0 — a retrograde puts M's LAST note there, so a Δ anchored on M's first note names
# the wrong shift and the composition silently misses.
PitchVariant = tuple[str, "int | None", list[Triple], list[Triple], int]


def _transpose_variants(
    pattern: list[Triple], placed: list[Triple], *, tol: float
) -> list[PitchVariant]:
    """The pattern under each anchor-viable constant transpose (Δ=0 included)."""
    return [
        (_pitch_label(delta), delta,
         [(s, p + delta, d) for (s, p, d) in pattern],
         pattern, delta)
        for delta in _transpose_candidates(pattern, placed, tol=tol)
    ]


def _invert_variants(
    pattern: list[Triple], placed: list[Triple], *, tol: float
) -> list[PitchVariant]:
    """The pattern under each anchor-viable inversion. An inversion pairs its
    ALREADY-inverted pattern for scale candidates, so its residual Δ is 0."""
    out: list[PitchVariant] = []
    for axis in _invert_axes(pattern, placed, tol=tol):
        inv = [(s, 2 * axis - p, d) for (s, p, d) in pattern]
        out.append(("invert", None, inv, inv, 0))
    return out



def _fragment_recall(
    rel_motif: list[Triple],
    placed: list[Triple],
    cell_offset_beats: float,
    *,
    tol: float,
) -> MatchResult | None:
    """Test whether a NATURAL fragment of M (a ``[a,b)`` onset half) is recalled at
    this alignment — under any anchor-viable pitch map (bare, or transposed) and
    either time map the fragment tier admits (identity, or a scale: the bounded 2-op
    ``diminish∘fragment`` / ``augment∘fragment``, DR-2). Derives the fragment from M
    (N2). Returns the fragment result covering the MOST of M, or ``None``.

    The pitch axis is searched here for the same reason it is searched everywhere
    else: a fragment quoted a fifth up is still that fragment, and requiring Δ=0 made
    every transposed fragment invisible. It carries the same >= 3-note evidence floor
    the free-duration tier does, for the same reason — see the loop body."""
    if not rel_motif:
        return None
    extent = _onset_extent(rel_motif)
    if extent <= 0:
        return None
    mid = extent / 2.0
    n_full = len(rel_motif)
    best: MatchResult | None = None

    def better(cand: MatchResult) -> None:
        nonlocal best
        if best is None or cand.coverage > best.coverage + 1e-9:
            best = cand

    for (a, b) in ((0.0, mid), (mid, extent + 1e-6)):
        frag = _rebased([(s, p, d) for (s, p, d) in rel_motif if a <= s < b])
        nf = len(frag)
        if nf < 2:
            continue
        cov = nf / n_full
        b_label = b if b <= extent else extent
        frag_name = f"fragment[{_fmt_num(a)},{_fmt_num(b_label)})"
        for delta in _transpose_candidates(frag, placed, tol=tol):
            # The SAME evidence floor the free-duration tier applies (R4): relaxing an
            # axis costs evidence, and a fragment already spends most of it. A 2-note
            # fragment under a FREE pitch map is just "some interval occurs somewhere"
            # — which the layer-level interval fast-skip already established — so on a
            # busy layer it matches at a dozen transpositions and buries the real
            # recall under near-duplicates. Three notes is where a transposed fragment
            # is evidence again; the untransposed quote (Δ=0) needs no such floor,
            # because it is the motif's own pitches at the motif's own interval.
            if delta != 0 and nf < 3:
                continue
            plabel = _pitch_label(delta)
            mapped = [(s, p + delta, d) for (s, p, d) in frag]
            if _contains(placed, mapped, tol=tol, match_duration=False) / nf >= 1.0 - 1e-9:
                better(MatchResult(
                    _label(plabel, frag_name), cov, cell_offset_beats,
                    transpose=delta or None))
            for f in _scale_candidates(placed, frag, delta=delta):
                # Skip a degenerate unscaled "composition" (f ≈ 1.0) — that is just
                # the bare fragment already handled above, not a diminish/augment.
                if f <= 0 or abs(f - 1.0) <= 0.05:
                    continue
                if _scale_match(placed, mapped, f, tol=tol) / nf >= 1.0 - 1e-9:
                    op = "augment" if f > 1.0 else "diminish"
                    factor = _scale_value(f)
                    better(MatchResult(
                        _label(plabel, f"{op}∘fragment ×{_fmt_factor(factor)}"),
                        cov, cell_offset_beats,
                        transpose=delta or None, factor=factor))
    return best


def _match_at_alignment(
    rel_motif: list[Triple],
    motif_sig: list[Triple],
    placed: list[Triple],
    onset: float,
    *,
    tol: float,
    min_coverage: float = 1.0,
) -> MatchResult | None:
    """The best recall of M at ONE alignment (the window rebased so ``onset`` = 0),
    searched over the FACTORED ``(pitch_map, time_map)`` product.

    Tiers, in order — the first that lands wins, so the hot path costs no more than
    the old enumerated search:

      1. **strict** — every pitch map (transpose Δ / invert) against every time map
         (identity / scale ×f / retrograde), durations enforced on the scale probes as
         before. A clean whole-motif hit returns immediately.
      2. **free durations (R4)** — the same scale probes with the DURATION axis
         relaxed, entered only because tier 1 found nothing here and only for a motif
         of >= 3 notes (on two notes, a free duration axis leaves too little evidence
         to call a recall). Reported as the op with ``(durations free)`` and
         ``duration_match=False``.
      3. **fragment** — a natural half of M under any anchor-viable pitch map, which
         carries the same >= 3-note evidence floor once the pitch axis moves.
      4. **partial** — the best sub-full coverage seen in tiers 1-2, named as
         ``derived (<op>, <coverage>)`` and returned only when it reaches
         ``min_coverage``. With the default ``min_coverage=1.0`` no partial is ever
         returned, so a caller that wants clean recalls only pays nothing for it.

    ``cell_offset_beats`` is set to ``onset`` (the recall's absolute position in the
    layer)."""
    n = len(rel_motif)
    if n == 0 or not placed:
        return None

    # A recall anchored here spans at most M's onset extent × the largest scale
    # factor (augment ×4 is the widest the closed set reaches) + tolerance. Restrict
    # the window to that span — every op places M's notes within it, so this never
    # drops a real match, but it shrinks the per-alignment window from the whole layer
    # (800+ notes) to the few tens a recall could touch (the dominant-cost cut).
    span_cap = _onset_extent(rel_motif) * max(_SCALE_FACTORS) + tol
    placed = [t for t in placed if -tol <= t[0] <= span_cap]
    if not placed:
        return None

    retro_motif = _retrograde_pattern(motif_sig)

    # The pitch axis is re-anchored PER TIME MAP: a scale keeps M's first note at
    # relative onset 0, but a retrograde puts M's LAST note there, so the two need
    # different Δ / axis sets. (The fragment tier does its own, per fragment.)
    transpose_maps = _transpose_variants(rel_motif, placed, tol=tol)
    invert_maps = _invert_variants(rel_motif, placed, tol=tol)
    retro_maps = (
        _transpose_variants(retro_motif, placed, tol=tol)
        + _invert_variants(retro_motif, placed, tol=tol)
    )

    best_partial: MatchResult | None = None

    def offer(cov: float, op_label: str, **fields: Any) -> None:
        """Record a sub-full reading as the alignment's best partial (tier 4)."""
        nonlocal best_partial
        if cov <= 0.0 or cov >= 1.0 - 1e-9:
            return
        if best_partial is None or cov > best_partial.coverage + 1e-9:
            best_partial = MatchResult(
                _derived_label(op_label, cov), cov, onset, derived=True, **fields)

    # --- tier 1: pitch axis alone (identity time map) -----------------------
    for (plabel, rdelta, mapped, _cpat, _cdelta) in transpose_maps:
        cov = _contains(placed, mapped, tol=tol, match_duration=False) / n
        label = _label(plabel, "")
        if cov >= 1.0 - 1e-9:
            return MatchResult(label, 1.0, onset, transpose=rdelta)
        offer(cov, label, transpose=rdelta)

    # --- tier 1: composed scale time map ------------------------------------
    # Collected once so the free-duration tier re-probes exactly the same candidates.
    scale_probes: list[tuple[str, "int | None", list[Triple], float]] = []
    for (plabel, rdelta, mapped, cpat, cdelta) in transpose_maps + invert_maps:
        for f in _scale_candidates(placed, cpat, delta=cdelta):
            if f > 0:
                scale_probes.append((plabel, rdelta, mapped, f))
    for (plabel, rdelta, mapped, f) in scale_probes:
        cov = _scale_match(placed, mapped, f, tol=tol) / n
        label = _label(plabel, _scale_label(f))
        if cov >= 1.0 - 1e-9:
            return MatchResult(
                label, 1.0, onset, transpose=rdelta or None, factor=_scale_value(f))
        offer(cov, label, transpose=rdelta or None, factor=_scale_value(f))

    # --- tier 1: inversion (identity time map) ------------------------------
    for (plabel, _rdelta, mapped, _cpat, _cdelta) in invert_maps:
        cov = _contains(placed, mapped, tol=tol, match_duration=False) / n
        label = _label(plabel, "")
        if cov >= 1.0 - 1e-9:
            return MatchResult(label, 1.0, onset)
        offer(cov, label)

    # --- tier 1: composed retrograde time map -------------------------------
    for (plabel, rdelta, mapped, _cpat, _cdelta) in retro_maps:
        cov = _contains(placed, mapped, tol=tol, match_duration=False) / n
        label = _label(plabel, "retrograde")
        if cov >= 1.0 - 1e-9:
            return MatchResult(label, 1.0, onset, transpose=rdelta or None)
        offer(cov, label, transpose=rdelta or None)

    # --- tier 2: the duration axis relaxed (R4) -----------------------------
    # Only reachable because tier 1 found no clean op at this alignment, and only for
    # a motif long enough that full onset+pitch coverage is still evidence: on two
    # notes, a free duration axis would make the tier a rubber stamp.
    if n >= 3:
        for (plabel, rdelta, mapped, f) in scale_probes:
            cov = _scale_match(placed, mapped, f, tol=tol, match_duration=False) / n
            label = _label(plabel, _scale_label(f), duration_match=False)
            if cov >= 1.0 - 1e-9:
                return MatchResult(
                    label, 1.0, onset, transpose=rdelta or None,
                    factor=_scale_value(f), duration_match=False)
            # The partial names the op WITHOUT the qualifier (a partial reading makes
            # no claim about the duration axis), but still records the relaxation.
            offer(cov, _label(plabel, _scale_label(f)),
                  transpose=rdelta or None, factor=_scale_value(f),
                  duration_match=False)

    # --- tier 3: a natural fragment of M ------------------------------------
    frag = _fragment_recall(rel_motif, placed, onset, tol=tol)
    if frag is not None:
        return frag

    # --- tier 4: the honest partial -----------------------------------------
    if best_partial is not None and best_partial.coverage >= min_coverage:
        return best_partial
    return None


def match_all_in_layer(
    motif_notes: Sequence[NoteDict],
    layer_notes: Sequence[NoteDict],
    *,
    tol: float = _MATCH_TOL,
) -> list[MatchResult]:
    """Every DISTINCT-variation recall of motif M in a layer (CONTAINMENT semantics,
    M ⊆ a cell window). Slides M across every tiling-grid alignment and collects the
    clean recalls, deduped by ``variation`` (keeping the highest coverage, then the
    earliest ``cell_offset_beats``). This is the honest per-layer read: a layer that
    quotes M as both a bare ``fragment`` (the reggae-cell answer) AND a
    ``diminish∘fragment`` (the trade-cell dialogue) reports BOTH — neither silently
    dropped (design.md §4 step 5; the integration-trade signal, N1).

    If NO clean recall is found anywhere in the layer, returns the single best partial
    — ``derived (<op>, <coverage>)``, naming the op it nearly matched — when it clears
    the coverage floor, else ``[]`` (no recall — honest, never a false positive). The
    partial falls out of the SAME per-alignment search as the clean recalls, so it
    degrades along the whole ``(pitch_map, time_map)`` product rather than along the
    pitch axis alone."""
    motif_sig = _signature(motif_notes)
    layer_sig = _signature(layer_notes)
    n = len(motif_sig)
    if n == 0 or not layer_sig:
        return []

    # Provably-safe fast skip (the dominant-cost cut): the smallest reportable recall
    # is a 2-note fragment, so SOME pair of M's pitches must appear in the layer at a
    # matching interval. Every op in the factored product preserves an interval up to
    # sign (transpose: same; invert/retrograde: negated; augment/diminish/fragment:
    # same pitches — and a COMPOSITION of them therefore does too). So if the layer
    # shares NO interval (signed, mod nothing — absolute semitone gap) with M's
    # pitch-pair set, no recall is possible — skip without the per-onset scan. This
    # instantly skips drum layers (percussion pitches disjoint from a pitched motif:
    # the integration drums carry 800+ onsets, the per-onset scan's worst case).
    motif_intervals = {
        abs(a - b)
        for i, (_s1, a, _d1) in enumerate(motif_sig)
        for (_s2, b, _d2) in motif_sig[i + 1:]
    }
    layer_pitches = sorted({p for (_s, p, _d) in layer_sig})
    layer_intervals = {
        abs(layer_pitches[i] - layer_pitches[j])
        for i in range(len(layer_pitches))
        for j in range(i + 1, len(layer_pitches))
    }
    # REC-4Z8Q: exempt zero-interval (repeated-pitch) motifs — pedal / drone /
    # ostinato. Such a motif has `0 in motif_intervals`, and it recalls against any
    # layer that REPEATS that pitch — a 0-semitone "interval" across two onsets. But
    # `layer_intervals` is built from DISTINCT layer pitches, so a repeated pitch
    # collapses to one and contributes no 0, making the skip fire ({0} & {} == {})
    # and the recall vanish before the per-onset scan. The fast-skip's premise
    # ("some pitch PAIR must appear at a matching interval") only holds for a motif
    # whose intervals are all non-zero; for a 0-interval motif, fall through to the
    # scan. Multi-pitch motifs (the dominant-cost drum-layer skip) are unaffected —
    # `0 not in motif_intervals` leaves their guard unchanged.
    if motif_intervals and 0 not in motif_intervals and not (motif_intervals & layer_intervals):
        return []

    rel_motif = _rebased(motif_sig)
    onsets = sorted({s for (s, _p, _d) in layer_sig})

    by_variation: dict[str, MatchResult] = {}
    best_partial: MatchResult | None = None
    # M's first note has relative onset 0, so M is anchored against each distinct
    # window onset (the whole window rebased so that onset becomes 0) and the ops are
    # tested against that alignment. Any pitch can be M's first note under a pitch
    # map, so every distinct onset is an anchor — bounded by the layer's onset count.
    placements = [[(s - o, p, d) for (s, p, d) in layer_sig] for o in onsets]
    for onset, placed in zip(onsets, placements):
        # ONE pass per alignment recovers the clean recall AND, failing that, the
        # partial — so there is no second whole-layer scan probing a single axis.
        res = _match_at_alignment(
            rel_motif, motif_sig, placed, onset, tol=tol,
            min_coverage=_COVERAGE_FLOOR)
        if res is None:
            continue
        if res.derived:
            if best_partial is None or res.coverage > best_partial.coverage + 1e-9:
                best_partial = res
            continue
        prev = by_variation.get(res.variation)
        if (
            prev is None
            or res.coverage > prev.coverage + 1e-9
            or (
                abs(res.coverage - prev.coverage) <= 1e-9
                and res.cell_offset_beats < prev.cell_offset_beats
            )
        ):
            by_variation[res.variation] = res

    if by_variation:
        results = list(by_variation.values())
        # A full-motif quote SUBSUMES its own fragments: if any whole-motif op
        # (coverage 1.0) is present, a fragment (coverage < 1.0) is just a sub-window
        # of that quote already reported — drop it (it is not an independent recall).
        # This keeps the read meaningful: the integration-trade `diminish∘fragment`
        # survives (no full-coverage no-time recall on the trade `05 Lead`), but a
        # section that quotes M whole does not ALSO list every internal half.
        has_full = any(r.coverage >= 1.0 - 1e-9 for r in results)
        if has_full:
            results = [r for r in results if r.coverage >= 1.0 - 1e-9]
        return sorted(
            results,
            key=lambda r: (-r.coverage, r.cell_offset_beats, r.variation),
        )

    # No clean recall anywhere: the best partial, naming the op it nearly matched, if
    # it clears the floor — else no recall (never silent, never a false positive).
    if best_partial is not None:
        return [best_partial]
    return []


def match_motif_in_window(
    motif_notes: Sequence[NoteDict],
    window_notes: Sequence[NoteDict],
    *,
    cell_offset_beats: float = 0.0,
    tol: float = _MATCH_TOL,
) -> MatchResult | None:
    """The SINGLE best recall of motif M in a window (CONTAINMENT, M ⊆ window). A
    clean whole-motif op (coverage 1.0) wins; a fragment beats a ``derived`` partial;
    a partial at/above the floor reports ``derived (<op>, <coverage>)``; below the
    floor is no recall.

    Thin wrapper over :func:`match_all_in_layer` returning the top-ranked recall
    (named-over-derived, then coverage). ``cell_offset_beats`` is added to the
    detected within-window offset (a base offset for the window's absolute start).
    Use :func:`match_all_in_layer` when every distinct-variation recall in a layer
    matters (the lens's per-layer read)."""
    results = match_all_in_layer(motif_notes, window_notes, tol=tol)
    if not results:
        return None
    named = [r for r in results if not r.derived]
    pool = named if named else results
    best = max(pool, key=lambda r: r.coverage)
    # `derived` rides through. It is the authoritative tier signal and its own
    # docstring tells consumers to read it instead of the label prefix — so a
    # wrapper that rebuilt the result without it made prefix-matching the only
    # thing that worked, and every tier-4 guess reached this exported entry point
    # looking like a clean recall.
    return MatchResult(
        best.variation, best.coverage, cell_offset_beats + best.cell_offset_beats,
        transpose=best.transpose, factor=best.factor,
        duration_match=best.duration_match, derived=best.derived)
