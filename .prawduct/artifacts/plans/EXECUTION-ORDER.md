# EXECUTION-ORDER.md — Stage 2 plan (build → independent Critic → one PR per item)

Six reviewed design bundles under `.prawduct/artifacts/plans/<ID>/`. Each becomes
**one PR**; the user merges. Per-item Critic runs are already declared inside each
build-plan's last (or only) chunk (`cumulative-final` where multi-chunk).

This document is the orchestration layer ON TOP of the per-item plans: collision
graph, the single-Live-instance serialization, dependency/coupling order, and the
recommended sequence. It does not restate the chunk specs (LINK-DON'T-SUMMARIZE).

> **Wave-plan header convention (MET-9D4H, 2026-06-04):** every build/wave plan
> header carries a top-level `## Requirements Confidence: High|Medium|Low`
> declaration (`planning.md §Requirements Confidence` — the symptom this field
> exists to catch is a Medium-confidence plan that builds before its open dial is
> resolved). It is the wave-level rollup of the per-chunk Confidence checks, NOT a
> substitute for them. This is already satisfied by all six per-item build-plans
> under `plans/<ID>/build-plan.md` (ARR-7M3D Medium, ARR-8P5K High, ARR-9K4T
> Medium, MEL-1A7K High, MIX-3S7P High, SYN-4P2D High); the field is added to new
> wave headers going forward rather than retrofitted onto already-shipped plans.

---

## 1. COLLISION GRAPH (shared edit surfaces → separate PRs that rebase on merge)

Confirmed by grep against the build-plans. Three shared surfaces:

### A. `skills/compose-review/SKILL.md` — 3-way edit, READ §2 (NOT scope overlap)

- **ARR-9K4T** — adds a "Recurrence / recapitulation" block (cross-instrument
  registered atoms).
- **MEL-1A7K** — adds a "within-line repetition" block (line-level n-gram).
- **ARR-7M3D** — *touches* compose-review only to add ONE sentence pointing at the
  new audio energy lens as the render-time complement (it OWNS `/mix-review`, not
  the compose READ block). All three plans already agree on this (MEL W1 fix,
  ARR-9K4T §7, ARR-7M3D chunk 6 crit 4).

**Boundaries are pre-negotiated and disjoint:** recurrence = cross-instrument atoms;
MEL = within-line; ARR-7M3D = the symbolic-vs-audio energy pointer. Each plan
commits to authoring its block *beside* the siblings without double-reporting, and
ARR-9K4T's chunk-4 doc-parity grep explicitly checks the sibling blocks coexist.

**Consequence:** whichever lands first sets the section skeleton; the next two
**rebase on merge** and slot their block adjacently. The third PR's author must
re-read the merged section before editing (each plan already says so). Last-lander
runs the doc-parity grep to confirm no block was displaced/duplicated.

### B. `skills/mix-review/SKILL.md` — single editor (no collision, flagged historically)

- **ARR-7M3D** (chunk 6) — MEASURE feed bullet + INTERPRET intent-gate.
- **MIX-3S7P** carries a *flag* about this file but on re-verification edits it only
  via the song-side notes / backlog — **no actual mix-review SKILL edit in MIX-3S7P's
  file list** (its touch list is song-repo tests + `decisions/08` + backlog). So this
  is a **non-collision**; ARR-7M3D is the sole editor. ARR-7M3D's chunk-6 crit 1
  still re-reads before editing (cheap insurance).

### C. `src/hallucinote/arrangement.py` — 3-way, but ADDITIVE non-overlapping methods

- **ARR-7M3D** (chunk 1) — `materialize` passes `energy=sec.energy` to
  `create_section` (one line, existing method).
- **ARR-9K4T** (chunk 4) — new `section_recurrence_inputs()` adapter (no layer filter).
- **MEL-1A7K** (chunk 1) — `section_melody_inputs(profiles=…)` passthrough +
  `analyze_arrangement` passthrough.

These are **three different methods / call-sites in one file** — semantically
independent, but they will produce **textual merge conflicts** (same file, nearby
import/method regions). **Consequence:** later landers rebase on merge; conflicts are
mechanical (additive methods, no shared logic). Low risk, but call it out so the PR
author expects a rebase rather than a surprise.

### D. `arrangement-model.md` — 3-way, ARR-8P5K is the umbrella that folds the others

- **ARR-7M3D** (chunk 6) — derivative-lens audio-realization sentence.
- **ARR-9K4T** (chunk 5, DEFERRED) — Reference/recap row IF the deferred reference()
  link ships (it will not this batch → effectively no edit).
- **ARR-8P5K** (chunk 1) — the taxonomy-coherence delta (D1–D4) that *records* the
  MEASURE-half siblings (energy→ARR-7M3D, recurrence→ARR-9K4T) by reference.

**ARR-8P5K is the coherence umbrella** — by design it lands AFTER the sibling
*designs* are stable (they are) and references them. It does not depend on siblings
being *merged*. To minimize churn it should land **last**, after ARR-7M3D's
model-doc sentence is merged, so ARR-8P5K's coherence read reflects the actual
merged text rather than a predicted one.

### Collision summary (pairs to expect a rebase between)

| Surface | Items | Type | Action |
|---|---|---|---|
| `skills/compose-review/SKILL.md` | ARR-9K4T ↔ MEL-1A7K ↔ ARR-7M3D | 3-way doc | rebase-on-merge; disjoint blocks; last runs parity grep |
| `src/hallucinote/arrangement.py` | ARR-7M3D ↔ ARR-9K4T ↔ MEL-1A7K | 3-way code (additive) | rebase-on-merge; mechanical conflicts |
| `arrangement-model.md` | ARR-7M3D ↔ ARR-9K4T(deferred) ↔ ARR-8P5K | 3-way doc | ARR-8P5K folds in LAST |
| `skills/mix-review/SKILL.md` | ARR-7M3D only | non-collision | MIX-3S7P does not edit it |

---

## 2. LIVE SERIALIZATION (ONE Ableton instance, UP but UNATTENDED)

Only **objective** Live signal is in scope this run (exit codes, scene counts, rank
correlation, dB deltas, RT60). By-ear *amounts* are surfaced, never tuned. Because
there is exactly one Live instance, the Live-touching items **must run serially** —
never two renders/pushes concurrently.

| Item | Needs Live? | What | Unattended-safe? |
|---|---|---|---|
| **SYN-4P2D** | YES (objective integration only) | push synthetic 9-section song into fresh 8-scene set; assert exit 0 + `len(scenes) ≥ 9` | YES — exit-code + scene-count, zero ear, zero render |
| **MIX-3S7P** | YES (ENTRY-GATED) | push → render → `ableton_analysis`; assert send lift `realized` (≥1.5 dB) + RT60 present | CONDITIONAL — chunk-2 gate first checks a fresh, correctly-keyed multi-stem capture; if pipeline stale (`sun-zone-done.md:99`), chunk 2 is **BLOCKED-pending-render**, chunk 1 (plan-level, no Live) is the verification floor |
| **ARR-7M3D** | YES (chunk 5) | render sun-zone-done (declared 0.25→1.0), `analyze_mix`, read `energy_realization`; assert ρ + surface inversion magnitudes | YES — Spearman ρ is fully objective; DR-5 surfacing-threshold is calibrated-from-measured, final fine-tune flagged for human ear |
| **ARR-9K4T** | NO | pure-stdlib symbolic lens; the one open dial (match tolerance) is render-FREE symbolic measurement of seeded breathed notes | n/a |
| **MEL-1A7K** | NO (render available but not required) | melody layer is pure-stdlib; chunk-4 hook measurement is deterministic + render-free | n/a |
| **ARR-8P5K** | NO | doc-only coherence umbrella | n/a |

**Serialization order for the three Live items: SYN-4P2D → MIX-3S7P → ARR-7M3D.**
SYN-4P2D first (cheapest, most robust — a default 8-scene set, no render, no stale
pipeline dependency). MIX-3S7P and ARR-7M3D both depend on the sun-zone-done render
pipeline being healthy; run them back-to-back so a single Live reopen (if the capture
is stale) serves both. **Never overlap.** If the render pipeline is stale, both
MIX-3S7P (chunk 2) and ARR-7M3D (chunk 5) degrade gracefully to their documented
no-Live floors — neither fakes a green render.

**By-ear amounts to surface (NOT tune this run):**
- MIX-3S7P: pan width (intro organ −0.30 / break steel 0.34, `mixer_pan` post-fader →
  unmeasurable); Plate-send wetness "nothing cheesy" amount; boundary-snap feel.
- ARR-7M3D: DR-5 "notable inversion" surfacing threshold (calibrated-from-measured,
  conservative default + `operator-verification.md` flag if distribution ambiguous).
- MEL-1A7K: appetite→fraction grading edges + which `MelodicProfile` each sun-zone-done
  hook declares (chunk 4 prints numbers and STOPS — creative lock-in for the user's ear).

---

## 3. DEPENDENCY / COUPLING ORDER

No item is a hard *build* dependency of another (each is a standalone PR). The
couplings are **edit-surface** (§1) and **conceptual-boundary**:

1. **MEL-1A7K ⇄ ARR-9K4T motivic-economy boundary.** MEL owns *line-level* within-line
   repetition; ARR-9K4T owns *cross-instrument/arrangement-level* recurrence. No shared
   code, different inputs. The boundary must read consistently in `/compose-review`
   (their two blocks) and is *recorded canonically* by ARR-8P5K's D3. → land MEL and
   ARR-9K4T before ARR-8P5K so D3's boundary sentence cites merged reality.

2. **ARR-8P5K folds in its siblings.** Its taxonomy delta records energy→ARR-7M3D,
   recurrence→ARR-9K4T (D2) and the MEL/ARR-9K4T economy boundary (D3). It is
   explicitly designed to land *after the sibling designs are stable* (they are now)
   and references designs+backlog, not merged code — BUT landing it last minimizes
   `arrangement-model.md` churn against ARR-7M3D's chunk-6 sentence. → **ARR-8P5K last.**

3. **ARR-7M3D internal:** chunk 1 (schema/persist) is the keystone every later chunk
   depends on; its Live render is chunk 5 (late). Independent of the other items.

4. **SYN-4P2D:** zero coupling to any other item — isolated push-phase bug. Touches
   `sync/push/*`, MCP scene handler, `ableton-push` SKILL — no overlap with the
   recurrence/melody/energy surfaces.

---

## 4. RECOMMENDED EXECUTION SEQUENCE (one-line rationale each)

1. **SYN-4P2D** — cleanest isolated bug; single chunk; zero file collisions; Live
   verification is exit-code+scene-count (most robust unattended signal). Land first.
2. **ARR-9K4T** — render-free symbolic read-side; resolves the MEL boundary partner and
   seeds the `/compose-review` + `arrangement.py` surfaces before the Live work. (One
   open dial = render-free tolerance measurement, fully resolvable this run.)
3. **MEL-1A7K** — render-free read+author side; lands its `/compose-review` block beside
   ARR-9K4T's (rebase on merge); chunk-4 hook numbers surfaced, thresholds left to ear.
4. **ARR-7M3D** — needs Live (chunk 5 render) but the lens is unit-tested first; objective
   ρ; lands the `arrangement.py` energy line + `/mix-review` edit + its 1-sentence
   compose-review pointer. Run its render in the Live serialization slot.
5. **MIX-3S7P** — Live render-gated and the most likely to hit a stale pipeline; chunk-1
   plan-level floor lands regardless; run its render adjacent to ARR-7M3D's (shared Live
   reopen). Mostly VERIFY+RECORD of already-shipped work.
6. **ARR-8P5K** — doc-coherence umbrella; lands LAST so its taxonomy read reflects the
   merged sibling text (esp. ARR-7M3D's model-doc sentence) rather than a prediction.

**Live render slot:** items 4 and 5 are the render-pipeline pair — execute their Live
renders back-to-back, serially, sharing one Live reopen if the capture is stale.
SYN-4P2D's Live touch (item 1) is independent and needs no sun-zone-done pipeline.

---

## 5. PER-ITEM PR BOUNDARY / CONFIDENCE / RESIDUAL BY-EAR

One PR per item (user merges each). Branch off `develop`, PR base `develop` (gitflow
on develop — not main). Each item's last/only chunk already declares its Critic mode
(`cumulative-final` for the multi-chunk items, `final` for the single-chunk items).

| Item | Chunks | PR | Confidence | Live-gated | Residual by-ear to surface |
|---|---|---|---|---|---|
| SYN-4P2D | 1 | one PR | High | YES (objective only) | None |
| ARR-9K4T | 4 (+1 deferred) | one PR | Medium (match tolerance — render-free, resolved in chunk 1) | No | None render-gated; tolerance is measured-not-guessed |
| MEL-1A7K | 6 (5 optional/friction-gated) | one PR | High | No | appetite→fraction edges + which profile each hook declares (chunk 4 surfaces, user's ear decides) |
| ARR-7M3D | 6 | one PR | Medium (density detector + DR-5 threshold) | YES | DR-5 "notable inversion" surfacing threshold (calibrated-from-measured; human-ear fine-tune flagged) |
| MIX-3S7P | 3 | one PR (in `hallucinote-songs` for chunks 1–2; framework backlog edit chunk 3) | High (one user-deferred fork) | YES (entry-gated) | pan width (unmeasurable); "nothing cheesy" wetness amount; boundary-snap feel. PLUS user-deferred fork: song-spanning DubDelay send (NOT a chunk) |
| ARR-8P5K | 1 | one PR | High | No | None |

**Cross-repo note:** ARR-9K4T, MEL-1A7K, ARR-7M3D each have a song-repo half
(`hallucinote-songs/songs/sun-zone-done/`) that must be a **separate commit** (the song
repo builds against the *installed* engine — `pip install -e .` of the feature branch
first). MIX-3S7P's chunks 1–2 are entirely in `hallucinote-songs`; only its chunk-3
backlog edit is in this framework repo. Sequence each song-repo commit AFTER its engine
PR's branch is installable.
