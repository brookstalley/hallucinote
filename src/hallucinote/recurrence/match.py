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
climax recap velocity-boosted, yet both are the same motif.

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

    ``variation`` is the human-facing label (``exact`` / ``transpose Δst`` /
    ``augment ×f`` / ``diminish ×f`` / ``invert`` / ``retrograde`` /
    ``fragment[a,b)`` / ``diminish∘fragment ×f`` / ``derived``). ``coverage`` is the
    fraction of M's notes accounted for (1.0 for a clean op; <1.0 for ``derived``
    or a fragment, which covers only its sub-window of M). ``cell_offset_beats`` is
    the recall's onset within the layer (absolute, section-relative). ``transpose``
    carries the Δst for a transpose; ``factor`` the scale for augment/diminish;
    the rest are ``None``."""

    variation: str
    coverage: float
    cell_offset_beats: float
    transpose: int | None = None
    factor: float | None = None


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


def _aligned_windows(window_sig: list[Triple]) -> list[list[Triple]]:
    """The window re-expressed relative to each plausible alignment onset.

    M's first note has relative onset 0; we anchor M against each distinct window
    onset (rebasing the whole window so that onset becomes 0), then test the ops
    against that alignment. Any pitch can be M's first note under transpose, so we
    anchor at every distinct onset — bounded by the window's onset count."""
    onsets = sorted({s for (s, _p, _d) in window_sig})
    return [[(s - o, p, d) for (s, p, d) in window_sig] for o in onsets]


def _best_transpose(
    rel_pattern: list[Triple], placed: list[Triple], *, tol: float
) -> tuple[int, int] | None:
    """The constant Δst (Δ=0 = exact quote) maximizing containment of the pattern in
    the (alignment-relative) window. Returns ``(delta, matched_count)`` or ``None``.

    The window is rebased so the ANCHOR onset = 0; pattern note 0 sits at relative
    onset 0, so a viable Δst must map it onto a window note at onset ≈ 0 (within
    ``tol``). Probing only those deltas (usually 1-2) instead of every window pitch
    keeps the per-alignment cost bounded on busy layers (800+ onsets), so the
    whole-layer scan stays fast — the deltas that can't even match note 0 cannot be
    the recall's transpose."""
    if not rel_pattern or not placed:
        return None
    p0 = rel_pattern[0][1]
    deltas = sorted({wp - p0 for (ws, wp, _wd) in placed if abs(ws) <= tol})
    best: tuple[int, int] | None = None
    for delta in deltas:
        shifted = [(s, p + delta, d) for (s, p, d) in rel_pattern]
        matched = _contains(placed, shifted, tol=tol, match_duration=False)
        if best is None or matched > best[1]:
            best = (delta, matched)
    return best


# The augment/diminish factors the matcher recovers — the closed set the corpus
# uses (DR-2: single-op + the bounded 2-op fragment scales the fixtures need). A
# recovered ratio is accepted only if it lands within tolerance of one of these, so
# the candidate set per alignment is BOUNDED (not O(notes²)) — the read stays fast on
# busy layers (the integration drums carry 800+ onsets). Widen only when a real song
# forces a new factor (DISCOVERED-FROM-FRICTION).
_SCALE_FACTORS = (0.25, 0.5, 1.5, 2.0, 3.0, 4.0)
_SCALE_SNAP = 0.05


def _scale_candidates(placed: list[Triple], rel_pattern: list[Triple]) -> list[float]:
    """The bounded set of augment/diminish factors f to test at a window alignment.

    Propose f from pairing EACH motif onset (>0) against each window onset of the same
    pitch (robust to trailing/tiled extras AND per-note breath jitter — a single
    span lever-arm amplifies one note's jitter, B1), then KEEP only ratios within
    ``_SCALE_SNAP`` of a recognised ``_SCALE_FACTORS`` value. This bounds the
    candidate set to the closed factor set (DR-2) regardless of layer size, so a
    busy 800-onset layer doesn't trigger O(notes²) scale probes. The caller's
    ``_scale_match`` then verifies full containment per surviving candidate."""
    found: set[float] = set()
    for (ms, mp, _md) in rel_pattern:
        if ms <= 0:
            continue
        for (ws, wp, _wd) in placed:
            if wp == mp and ws > 0:
                ratio = ws / ms
                for fac in _SCALE_FACTORS:
                    if abs(ratio - fac) <= _SCALE_SNAP:
                        found.add(fac)
    return sorted(found)


def _scale_match(
    placed: list[Triple], rel_pattern: list[Triple], factor: float, *, tol: float
) -> int:
    """Containment count of M scaled by ``factor`` (augment/diminish: onsets AND
    durations scale; pitches identical) against the alignment-relative window."""
    scaled = [(s * factor, p, d * factor) for (s, p, d) in rel_pattern]
    return _contains(placed, scaled, tol=tol, match_duration=True)


def _invert_match(placed: list[Triple], rel_pattern: list[Triple], *, tol: float) -> int:
    """Containment count of M inverted (``p' = 2*axis - p``) for the best axis: M's
    first pitch (variations.invert's default) plus every axis that would land
    inverted-note-0 on a window pitch."""
    if not rel_pattern or not placed:
        return 0
    p0 = rel_pattern[0][1]
    axes = {p0}
    # Inverted note 0 (= 2*axis - p0) must land on a window note at the anchor onset
    # (rel ≈ 0); only those axes are viable (bounds the probe on busy layers).
    for (ws, wp, _wd) in placed:
        if abs(ws) <= tol and (wp + p0) % 2 == 0:
            axes.add((wp + p0) // 2)
    best = 0
    for axis in axes:
        inv = [(s, 2 * axis - p, d) for (s, p, d) in rel_pattern]
        best = max(best, _contains(placed, inv, tol=tol, match_duration=False))
    return best


def _retrograde_match(
    placed: list[Triple], motif_sig: list[Triple], *, tol: float
) -> int:
    """Containment count of M retrograded. M's span comes from M itself (N2): each
    onset becomes ``span - (start + dur)`` (variations.retrograde), then rebased."""
    if not motif_sig or not placed:
        return 0
    span = max(s + d for (s, _p, d) in motif_sig)
    retro = sorted(
        ((span - (s + d), p, d) for (s, p, d) in motif_sig),
        key=lambda spd: (spd[0], spd[1], spd[2]),
    )
    return _contains(placed, _rebased(retro), tol=tol, match_duration=False)


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


def _scale_result(factor: float, cell_offset_beats: float) -> MatchResult:
    """Label a recovered onset/duration scale as augment (f>=1) or diminish (f<1,
    reported as ``diminish ×(1/f)``)."""
    if factor >= 1.0:
        f = _clean_factor(factor)
        return MatchResult(f"augment ×{_fmt_factor(f)}", 1.0, cell_offset_beats, factor=f)
    inv = _clean_factor(1.0 / factor)
    return MatchResult(f"diminish ×{_fmt_factor(inv)}", 1.0, cell_offset_beats, factor=inv)


def _fragment_recall(
    rel_motif: list[Triple],
    aligned: list[list[Triple]],
    cell_offset_beats: float,
    *,
    tol: float,
) -> MatchResult | None:
    """Test whether a NATURAL fragment of M (a ``[a,b)`` onset half) is recalled —
    bare (``fragment[a,b)``) or scaled (``diminish∘fragment`` / ``augment∘fragment``,
    the bounded 2-op DR-2). Derives the fragment from M (N2). Returns the fragment
    result covering the MOST of M, or ``None``."""
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
        for placed in aligned:
            bt = _best_transpose(frag, placed, tol=tol)
            if bt is not None and bt[0] == 0 and bt[1] / nf >= 1.0 - 1e-9:
                better(MatchResult(
                    f"fragment[{_fmt_num(a)},{_fmt_num(b_label)})", cov, cell_offset_beats))
            for f in _scale_candidates(placed, frag):
                # Skip a degenerate unscaled "composition" (f ≈ 1.0) — that is just
                # the bare fragment already handled above, not a diminish/augment.
                if f <= 0 or abs(f - 1.0) <= 0.05:
                    continue
                if _scale_match(placed, frag, f, tol=tol) / nf >= 1.0 - 1e-9:
                    op = "augment" if f > 1.0 else "diminish"
                    factor = _clean_factor(f if f > 1.0 else 1.0 / f)
                    better(MatchResult(
                        f"{op}∘fragment ×{_fmt_factor(factor)}", cov, cell_offset_beats,
                        factor=factor))
    return best


def _match_at_alignment(
    rel_motif: list[Triple],
    motif_sig: list[Triple],
    placed: list[Triple],
    onset: float,
    *,
    tol: float,
) -> MatchResult | None:
    """The best clean op (or fragment) recall of M at ONE alignment (the window
    rebased so ``onset`` = 0). ``cell_offset_beats`` is set to ``onset`` (the recall's
    absolute position in the layer). Returns ``None`` if no clean op / fragment
    matches at this alignment (a ``derived`` partial is NOT reported here — that is a
    whole-layer fallback in the callers)."""
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

    best: MatchResult | None = None

    def consider(cand: MatchResult) -> None:
        nonlocal best
        if best is None or cand.coverage > best.coverage + 1e-9:
            best = cand

    bt = _best_transpose(rel_motif, placed, tol=tol)
    if bt is not None and bt[1] / n >= 1.0 - 1e-9:
        delta = bt[0]
        label = "exact" if delta == 0 else f"transpose {delta:+d}"
        consider(MatchResult(label, 1.0, onset, transpose=delta))
    for f in _scale_candidates(placed, rel_motif):
        if f > 0 and _scale_match(placed, rel_motif, f, tol=tol) / n >= 1.0 - 1e-9:
            consider(_scale_result(f, onset))
    if _invert_match(placed, rel_motif, tol=tol) / n >= 1.0 - 1e-9:
        consider(MatchResult("invert", 1.0, onset))
    if _retrograde_match(placed, motif_sig, tol=tol) / n >= 1.0 - 1e-9:
        consider(MatchResult("retrograde", 1.0, onset))

    if best is not None:
        return best
    return _fragment_recall(rel_motif, [placed], onset, tol=tol)


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

    If NO clean recall is found anywhere in the layer, returns a single ``derived``
    partial (best transpose-coverage) when it clears the coverage floor, else ``[]``
    (no recall — honest, never a false positive)."""
    motif_sig = _signature(motif_notes)
    layer_sig = _signature(layer_notes)
    n = len(motif_sig)
    if n == 0 or not layer_sig:
        return []

    # Provably-safe fast skip (the dominant-cost cut): the smallest reportable recall
    # is a 2-note fragment, so SOME pair of M's pitches must appear in the layer at a
    # matching interval. Every op preserves an interval up to sign (transpose: same;
    # invert/retrograde: negated; augment/diminish/fragment: same pitches). So if the
    # layer shares NO interval (signed, mod nothing — absolute semitone gap) with M's
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
    # Cache the alignment-relative window views once per onset (reused per probe).
    placements = [[(s - o, p, d) for (s, p, d) in layer_sig] for o in onsets]
    for onset, placed in zip(onsets, placements):
        res = _match_at_alignment(rel_motif, motif_sig, placed, onset, tol=tol)
        if res is None:
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

    # No clean recall anywhere: the best transpose-coverage partial as `derived` if
    # it clears the floor, else no recall (never silent, never a false positive).
    best_cov = 0.0
    best_onset = 0.0
    span_cap = _onset_extent(rel_motif) + tol  # derived is transpose-only (no scale)
    for onset, placed in zip(onsets, placements):
        windowed = [t for t in placed if -tol <= t[0] <= span_cap]
        bt = _best_transpose(rel_motif, windowed, tol=tol)
        if bt is not None and bt[1] / n > best_cov:
            best_cov = bt[1] / n
            best_onset = onset
    if best_cov >= _COVERAGE_FLOOR:
        return [MatchResult("derived", best_cov, best_onset)]
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
    a partial at/above the floor reports ``derived``; below the floor is no recall.

    Thin wrapper over :func:`match_all_in_layer` returning the top-ranked recall
    (named-over-derived, then coverage). ``cell_offset_beats`` is added to the
    detected within-window offset (a base offset for the window's absolute start).
    Use :func:`match_all_in_layer` when every distinct-variation recall in a layer
    matters (the lens's per-layer read)."""
    results = match_all_in_layer(motif_notes, window_notes, tol=tol)
    if not results:
        return None
    named = [r for r in results if r.variation != "derived"]
    pool = named if named else results
    best = max(pool, key=lambda r: r.coverage)
    return MatchResult(
        best.variation, best.coverage, cell_offset_beats + best.cell_offset_beats,
        transpose=best.transpose, factor=best.factor)
