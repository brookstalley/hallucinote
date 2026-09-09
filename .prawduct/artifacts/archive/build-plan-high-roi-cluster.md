---
lifecycle: completed
archived: 2026-09-08
unbuilt_at_archive: "no readable `## Status` roster — completeness cannot be read, and an unreadable plan is not evidence of completion"
maintained: false
---

> **Archived — no longer maintained.** This plan records what was built, not what will be. Do not edit it to reflect later changes; write those where they are true.

# Build plan — High-ROI cluster (one PR)

**Type:** mixed (1 bugfix + 1 reliability mitigation + 1 doc-fix), medium.
**Branch:** `feat/high-roi-cluster` (worktree, off `develop`).
**Rollup:** ONE PR for all chunks. **Critic:** cumulative at PR time.

## Why these three (selection rationale)

Picked for **high ROI × solo-completable × no live/MCP dependency** — so the
whole lot lands in one clean, unit-tested PR with **no fingerprint flip, no
re-vendor, no operator-verification gate**. They form **two coherent commit
clusters** in adjacent areas.

Deliberately EXCLUDED (and why), so the bundle stays one-PR-clean:
- **render-analyzer ROOT-CAUSE** (don't rename returns on analyzer load) — lives
  in the `hallucinote_mcp` Remote Script → fingerprint flip + re-vendor + live
  operator-verify. Separate Live-side PR. (This plan ships the *engine-side
  defensive* half, which fully unblocks the push pipeline.)
- **2026-06-18 session-override / `probe set` no-op** — MCP-side, needs live verify.
- **CON-7K3D** — blocked (gated on a relational second song).
- **DOC-4F8M** (derived-overview rot) — stage: requirements; needs a generate-vs-warn
  discovery pass first. Different area. Follow-up.
- **WSP-3R7K** (per-tool self-ignore) — verified MOOT for this framework repo
  (no tracked songs; it matters in hallucinote-songs). Low ROI here.

## Requirements confidence: HIGH

All three root causes are traced to exact lines (below), confirmed by independent
verification this session. No external/volatile dependencies.

---

## Cluster A — symbolic lenses (recurrence / melody)

### Chunk A1 — REC-4Z8Q: recurrence matcher misses zero-interval (repeated-pitch) motifs

**Problem (live defect).** `match_all_in_layer` silently returns `[]` for any
pedal / drone / ostinato motif (a repeated single pitch), even against an
identical layer — so the recurrence lens has a blind spot for an entire class of
real motifs.

**Root cause.** `src/hallucinote/recurrence/match.py:438-450` — the provably-safe
fast-skip computes `layer_intervals` over the **distinct** layer pitches
(`layer_pitches = sorted({...})`), so a repeated pitch contributes no `0`
interval. A repeated-pitch motif has `motif_intervals = {0}`; the guard
`if motif_intervals and not (motif_intervals & layer_intervals): return []`
fires (`{0}` truthy, `{0} & {} = {}`) before the per-onset scan.

**Fix.** Exempt zero-interval motifs from the fast-skip:
`if motif_intervals and 0 not in motif_intervals and not (motif_intervals & layer_intervals): return []`.
A motif containing interval `0` (a repeated pitch) can recall against any layer
that repeats that pitch — which the distinct-pitch `layer_intervals` can't
witness — so the safe move is to not fast-skip it and let the per-onset scan
decide. Preserves the dominant-cost cut for every genuine multi-pitch motif (the
drum-layer skip the optimization exists for is unaffected).

**Acceptance / tests** (`tests/unit/recurrence/`):
- a repeated-pitch motif recalls against a layer that repeats that pitch (was 0,
  now ≥1) — pedal / drone / ostinato cases.
- the drum-layer fast-skip still fires: a pitched multi-interval motif still
  returns `[]` against a disjoint percussion layer (no perf regression).
- existing distinct-interval recalls unchanged.

**Critic:** chunk. **Backlog:** REC-4Z8Q (open · ready) → shipped.

### Chunk A2 — DOC-7K3M (scoped): symbolic-lens read-side doc gaps

**Scope (the concrete, ready subset — NOT the full read-side guide).** While in
the recurrence/melody code, close the doc gaps the triage pinned:
- `src/hallucinote/melody/profile.py:27-32` — the "grades as matched and never
  re-flags" promise needs a section-altitude / phrase-looping caveat (a profile
  is per-line; a looping phrase at section altitude can still warrant attention).
- `src/hallucinote/recurrence/lens.py` docstring — add motif minimum-distinctiveness
  / length guidance + a note on transform-group over-matching (pairs with A1:
  zero-interval motifs now match, so guidance on what's *worth* registering matters).
- `src/hallucinote/tools/templates/song/build.py.tmpl:125-146` — the scaffold
  steers `melody_report()` only at `analyze_arrangement(sun-zone-done)`; add the
  per-section `SectionMelody` + `analyze_melody` wiring note.

**Out of scope (defer):** a new user-facing `docs/melody-model.md` read-side
authoring guide — that's the larger half of DOC-7K3M; leave the backlog item open
for it, this chunk only clears the in-code doc gaps.

**Acceptance:** the three doc sites updated; DOC-7K3M backlog entry annotated
"in-code doc gaps closed; read-side guide still open." Doc-only.

**Critic:** folds into cumulative (doc-only).

---

## Cluster B — push / sync DB↔Live reliability

### Chunk B1 — render-relink: probe-and-link matches returns the render renamed

**Problem (M).** `ableton_render` auto-loads `HallucinoteAnalyzer` and (return-only)
appends ` | HallucinoteAnalyzer` to the return name. `push probe-and-link` then
can't match (`unmatched_db_returns: [Reverb]` vs
`unmatched_live_returns: [A-Reverb | HallucinoteAnalyzer]`), silently breaking
every return-targeting push phase after any render. (New report
`backlog RND-2R9K`.)

**Fix (engine-side defensive — report's option 2).** The return-name match in
`src/hallucinote/sync/push/probe.py:483-489` normalizes via
`strip_return_slot_prefix`. Extend the normalization to ALSO strip a trailing
` | HallucinoteAnalyzer` (the render's measurement-device suffix; never authored)
so probe-and-link relinks despite a render's rename. Put the suffix-strip in
`src/hallucinote/return_naming.py` (e.g. a `normalize_return_name_for_match`
helper, or extend the existing strip) so the boundary stays one place.

**Acceptance / tests** (`tests/unit/sync/`):
- a live return named `A-Reverb | HallucinoteAnalyzer` matches DB return `Reverb`
  (was `unmatched`, now `matched`).
- a normal `A-Reverb` still matches `Reverb` (no regression).
- the suffix-strip is anchored/idempotent (doesn't eat a legit ` | ` in a name).

**Scope note.** This is the *functional unblock* (relink works); the cosmetic
dirty Live name persists until the Live-side root-cause fix (separate PR — see
Excluded). Document the residual on the report + a follow-up backlog item.

**Critic:** chunk. **Backlog:** file a new item (e.g. `SYN-RENDER-RELINK`) via
`/prawduct:backlog` before build; mark shipped at PR.

---

## Order, clustering & rollup

Independent chunks (no inter-dependencies) — but commit in cluster order so the
PR reads as two coherent areas:
1. A1 (matcher fix) → 2. A2 (lens docs) → 3. B1 (render-relink).

**Commit clustering:** one commit per chunk (A1, A2, B1). Cluster A commits are
adjacent (recurrence/melody); B1 is the push/sync commit. → **one final PR**
(`feat/high-roi-cluster` → develop) covering all three.

**Done when:** full suite green; `/prawduct:critic cumulative` clean; REC-4Z8Q +
the render-relink backlog item marked shipped, DOC-7K3M annotated; one PR opened
via `gh` (worktree → gates blind, per the filed worktree-governance issue). **No
operator-verification** — the bundle is entirely engine-side + unit-tested.

## Prerequisites before build
- File the render-relink backlog item via `/prawduct:backlog`.
- Create the worktree off develop (`feat/high-roi-cluster`), establish clean
  baseline (full suite green).

## Independent review (Critic) — resolutions

Reviewed `develop..HEAD` by an independent agent. REC-4Z8Q and the docs confirmed
correct/accurate (NOTEs only). One **WARNING resolved**:

- **render-relink was applied at only 1 of ≥3 live-return↔DB match boundaries.**
  `normalize_live_return_name` was swept into the rest: `pull/mix.py`
  `_apply_return_info` (was writing the dirty ` | HallucinoteAnalyzer` name into
  the DB — source-of-truth corruption) and `_apply_sends` (silently dropped
  sends), plus `capture.py` replay (return name + sends lookup). + pull-side and
  capture-replay regression tests. Completeness re-checked: probe + mix×2 +
  capture×2 cover every live-name→DB match; the mutator is the write-boundary and
  push goes DB→Live (neither reads live names for matching).

NOTEs accepted: REC-4Z8Q exemption verified correct (transposed/contained pedals
recall; fast-skip preserved; no second skip copy); DOC-7K3M docstrings accurate;
regex anchored/idempotent; no import cycle.

**Outcome:** 4000 suite passed / 320 skipped (audio) / 0 failures. RND-2R9K filed
for the Live-side root cause (don't rename returns on analyzer load).
