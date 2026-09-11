---
lifecycle: completed
archived: 2026-09-08
unbuilt_at_archive: "1 of 5 Status items still unticked (Chunk 5 — DEFERRED: authored reference() link (build only on friction)) — the scope shipped, but this plan did not finish with it"
maintained: false
---

> **Archived — no longer maintained.** This plan records what was built, not what will be. Do not edit it to reflect later changes; write those where they are true.

# ARR-9K4T — Build Plan: cross-instrument recurrence READ

Design: `design.md` (this dir). Research: `research.md` (this dir). Both linked,
not restated.

## Requirements Confidence: **Medium**

- Problem, success, scope are each statable in one sentence (design.md §0).
- The matcher operates on data we fully own (the motif registry + the closed six-op
  transform algebra) — directed match against a known query, not undirected mining
  (research.md §1). No corpus, no ML, no foreign API.
- The thin-slice fixtures are concrete and already in the tree
  (`hallucinote-songs/songs/sun-zone-done/build.py`: the polyrhythm tiled quote on
  `04 Organ` `build.py:769,888,1017`; the no-time diminished-fragment on `05 Lead`
  `build.py:1002`; the no-time augment on `05 Lead` `build.py:1063`).
- The established lens contract (theory.lint / melody.lens / performance.lens) is
  the proven shape to mirror — frozen dataclasses, local `Severity`, `to_dict()`,
  info-only.

**Why Medium, not High — the one open dial (B1):** the symbolic match TOLERANCE
(onset / duration residual budget) is a genuine unmeasured value. The earlier draft
asserted "the fixtures are authored on exact beats so exact match holds
(~`_ONSET_EPS`)" — **that premise is FALSE for the outro augment recall**, which is
BREATHED via `apply_profile` (`build.py:1318-1320`, `05 Lead` carries the augment)
before it enters the arrangement. So the tolerance is bimodal: exact-beat for the
two integration recalls (the one machine-tight section) and breathed-jitter for the
outro recall. The single tolerance must be set from the **breathed worst case**, not
the machine-tight polyrhythm. This is a PENDING by-ear-adjacent call below — but
render-free and fully resolvable this run (symbolic measurement of the breathed
in-memory notes in Chunk 1). **What raises it to High:** Chunk 1's calibration print
measures the breathed-outro onset/duration residual across all three recalls and
locks the tolerance from the worst case; until then, Medium is the honest level
(planning.md §Requirements Confidence — this is exactly the symptom the field
exists to catch).

**Foreign API:** none (pure-stdlib symbolic lens; no Ableton/MCP/SDK surface).
Live is not touched — this is render-free, like the theory/melody/performance lenses.

---

## Verification strategy

- **Tests** (pytest, mirrors `tests/unit/melody/`): unit tests for the matcher
  (each variation type recovered on a synthetic motif+transform; tiling alignment;
  honest `derived` and no-recall cases), the economy summary (cell-set size,
  coverage, compression proxy on synthetic registries), and the lens
  (`analyze_recurrence` over synthetic `SectionRecurrenceInput`s; `analyze_arrangement`
  over a synthetic `Arrangement`).
- **Product exercise (render-free, the real consumer path):** run `python3 -m
  hallucinote.tools.recurrence_lens sun-zone-done` and confirm it reports
  `polyrhythm-cloud` recurring in the integration climax (tiled quote),
  `no-time-stab` recurring in the integration trade-cell (`diminish∘fragment`) and
  the outro (`augment ×2`), plus the economy summary. This is the VERIFIABLE SIGNAL
  from the item, exercised exactly as `/compose-review` will. sun-zone-done lives
  in the sibling `hallucinote-songs` repo; the lens resolves it via the
  project-root contract (`workspace.resolve_song_dir`, the same path
  `tools/melody_lens.py` uses) — so wiring `recurrence_report()` into that song's
  `build.py` is the live-fixture step (Chunk 4).
- **Calibration-first discipline** (`learnings.md` "DSP with a detection
  front-end" / the C7 story): even though this is symbolic (no audio detection
  front-end), Chunk 1 runs the REAL sun-zone-done motifs+layers through the matcher
  and PRINTS the alignment offsets/residuals BEFORE locking test assertions — the
  tiling-alignment math (`learnings.md:390`) is exactly the place a convenient
  synthetic fixture would hide a bug. **Critically, the calibration print runs ALL
  THREE real recalls — including the BREATHED outro augment on `05 Lead` (B1)** —
  and reports the worst-case onset/duration residual; the tolerance is locked from
  the breathed worst case, NOT from the machine-tight polyrhythm. Calibrating only
  the polyrhythm (the earlier plan) would lock a tolerance too tight to see the
  breathed outro recall and silently fail 1/3 of the verifiable signal.
- **No `/mix-review`, no Live render** — render-free by design.

---

## Chunks (vertically sliced, dependency-ordered)

### Chunk 1 — Thin slice: detect the polyrhythm tiled QUOTE end-to-end

The thin vertical slice through the whole architecture: matcher core → lens →
report, proving one real recall is detected before widening to all variation types.

- **Type:** code
- **Done when:**
  1. `src/hallucinote/recurrence/match.py` recovers an **exact / transpose** recall
     of a single-cycle motif inside a TILED, SHIFTED layer (the polyrhythm case:
     `_polyrhythm_callback` tiles the 2-bar cell and `V.shift`s it to the section
     start). The matcher normalizes both sides to relative-onset
     `(start, pitch, duration)` signatures and slides M's span across the tiling
     grid (design.md §4 steps 1–2). **Matching is SUBSET / CONTAINMENT, not equality
     (W3):** M's transformed notes ⊆ the cell window, extra non-motif notes allowed —
     the climax-organ layer is a superset (recap + `FUSION_CHORD` hits in the same
     `04 Organ` layer, `build.py:888-901`), so the overlapped late cells must still
     read `exact`-via-containment, not `derived`. The matcher compares relative-onset
     signatures with the calibrated **tolerance** (a per-note onset-residual budget),
     NOT an exact-grid test — see step 4 (the tolerance must absorb breathed jitter).
  2. `src/hallucinote/recurrence/lens.py` defines the report dataclasses
     (`RecurrenceReport` / `SectionRecurrence` / `MotifRecall` / `RecurrenceFinding`)
     mirroring the melody-lens contract: frozen, local `Severity` Literal,
     `to_dict()` boundary, `RecurrenceReport.ok` (always True — info-only),
     `RecurrenceReport.blocking` (always empty, parity). `analyze_recurrence(sections,
     motifs, *, song_slug)` runs the matcher per (motif × section × layer).
  3. **Calibration print (no assertion yet) — ALL THREE real recalls (B1):** a
     throwaway snippet runs the REAL sun-zone-done motifs against their real layers
     through the matcher and PRINTS the recovered offset/variation/residual for each
     of: (a) `polyrhythm-cloud` vs the climax `04 Organ` layer (machine-tight, the
     superset W3 case); (b) `no-time-stab` vs the trade-cell `05 Lead` (machine-tight
     `diminish∘fragment`); and **(c) `no-time-stab` vs the BREATHED outro `05 Lead`
     (`augment ×2`)** — the outro lead is breathed via `apply_profile`
     (`build.py:1318-1320`), so its onsets are perturbed off exact beats by a
     non-`_ONSET_EPS` amount. Eyeball that the quote/fragment/augment are found at
     the right cell offsets before locking the assertion (learnings.md "calibrate
     against real cases"; tiling alignment AND breath jitter are the traps). Build
     the REAL (breathed) arrangement here — same notes `recurrence_report()` will
     hand the lens; do NOT read a non-breathed variant (design.md §4 step 4 rejects
     Option (b)).
  4. **PENDING by-ear call resolved-to-measured — from the WORST CASE (B1):** from
     the calibration print, record the measured onset/duration residual for each of
     the three recalls and SET the single match tolerance from the **largest (the
     breathed outro)** — NOT from the machine-tight polyrhythm. The two integration
     recalls will measure ~`_ONSET_EPS` (exact-beat); the breathed outro will measure
     a larger 1/f jitter residual, and that is the value the tolerance must absorb so
     `augment ×2` recovers (not `derived`/no-recall). Do NOT guess and do NOT assume
     `_ONSET_EPS` — the value is pinned to the measured worst-case number and noted in
     `match.py` as a calibrated constant with the rationale comment (cite the breathed
     residual). (Live is unattended; this is a symbolic measurement of the breathed
     in-memory notes, fully doable this run — no render, no human ear.)
  5. Unit tests: `test_match.py` proves exact + transpose recovery on a synthetic
     motif tiled+shifted into a layer; `test_lens.py` proves `analyze_recurrence`
     reports the recall with section + track + variation. Tests use synthetic
     fixtures (NO song-specific data in `tests/unit/`, per the test-location
     convention in the briefing).
  6. Full test suite passes; `/critic` (inference picks `chunk`) blocking findings
     resolved.
  7. Committed; chunk marked `[x]` in Status.
- **Critic mode:** (inference → `chunk`; this is a multi-chunk plan, non-final).
- **Governance checkpoint:** architecture-validation point — after this chunk the
  matcher→lens→report path is proven on one real recall.

### Chunk 2 — Full variation-type recovery + honest non-match

Widen the matcher from exact/transpose to the rest of the closed six ops + the one
2-op fixture composition, with honest `derived` / no-recall handling.

- **Type:** code
- **Done when:**
  1. `match.py` recovers: `augment ×f`, `diminish ×f`, `invert`, `retrograde`,
     `fragment[a,b)` (design.md §4 step 2), plus the bounded 2-op
     `diminish∘fragment` (the integration trade-cell, `build.py:1002`) per
     DR-2. The outro augment matches as plain `augment ×2` (velocity excluded from
     the signature per DR-4). **The augment/diminish recovery must tolerate the
     breathed onset/duration jitter (B1)** — the duration-scale test and the
     relative-onset test both use the calibrated tolerance from Chunk 1, so the
     BREATHED outro `augment ×2` recovers as `augment ×2`, not `derived`. `retrograde`
     derives M's span from M itself (the side it owns), not from the realized cell
     (N2).
  2. Honest non-match: a partial match ≥ a coverage reporting-floor reports
     `variation="derived"` with the coverage fraction; below-floor reports no
     recall for that (motif, cell) — NEVER a silent drop (design.md §4 step 5). The
     coverage floor is a calibrated reporting constant (mirrors `theory.lint`'s
     `out_of_chord_warn`), not a gate.
  3. Unit tests: each variation type recovered on a synthetic motif+transform; a
     synthetic `derived` case (a near-match the matcher can't fully name); a clean
     no-recall case (an unrelated layer); a **containment regression** — a synthetic
     motif tiled into a layer that ALSO contains extra non-motif notes reads `exact`
     (W3, the climax-organ superset shape), not `derived`. DR-4 regression: a
     velocity-only-different recall reads exact. **B1 regression:** a synthetic
     `augment ×2` recall with per-note onset jitter within the calibrated tolerance
     reads `augment ×2` (the breathed-outro shape — jitter does not collapse it to
     `derived`); the SAME recall with jitter beyond tolerance reads `derived` (the
     tolerance is the boundary, honestly reported).
  4. Full suite passes; `/critic chunk` blocking resolved.
  5. Committed; chunk marked `[x]`.
- **Critic mode:** (inference → `chunk`).

### Chunk 3 — Motivic-economy summary (the one cited metric)

Add the description-length-style economy summary off the known motif set
(research.md §2; design.md §5).

- **Type:** code
- **Done when:**
  1. `src/hallucinote/recurrence/economy.py` computes: **cell-set size** (distinct
     registered motifs recalled beyond their home section), **recall coverage**
     (`recurring / registered`), and the **compression-ratio proxy** (recalled
     note-mass ÷ [library note-count + per-occurrence records], the COSIATEC ⟨P,V⟩
     shape with P given). All as reported FACTS.
  2. The economy summary is attached to `RecurrenceReport` (a frozen
     `MotivicEconomy` dataclass with `to_dict()`). The ONLY finding the economy
     path emits is the registered-but-never-recalled INFO question (design.md §5);
     there is deliberately NO "be more economical" finding (DR-3, Temperley
     style-relativity — assert in a test that no such finding kind exists).
  3. Unit tests: economy figures on a synthetic registry (one recalled motif, one
     never-recalled); the never-recalled INFO question fires; assert the report
     emits no economy verdict finding and no `blocking`/`warning` from the economy
     path (info-only contract).
  4. Full suite passes; `/critic chunk` blocking resolved.
  5. Committed; chunk marked `[x]`.
- **Critic mode:** (inference → `chunk`).

### Chunk 4 — Wire into `/compose-review`: adapter, CLI, song hookup, doc deltas

The surface chunk — bring the read to the consumer exactly as the melody lens is
wired. This is where the VERIFIABLE SIGNAL is exercised on the live fixture.

- **Type:** code
- **Done when:**
  1. `Arrangement.section_recurrence_inputs()` adapter returns
     `SectionRecurrenceInput`s (section name, beat span, layers, section start
     beat); `recurrence.lens.analyze_arrangement(arr, *, song_slug)` is the thin
     wrapper (kept in `recurrence/lens.py`, imports `Arrangement` only under
     `TYPE_CHECKING` — the leaf-not-cycle topology, design.md §3). **The adapter and
     the wrapper take NO layer filter (W2) — they scan EVERY layer of every section**
     (`section_recurrence_inputs()` has no `recurrence_layers` parameter and no
     melody-style default exclusion; `analyze_arrangement` has no `melody_layers`
     analogue). This is the deliberate divergence from the melody adapter
     (`section_melody_inputs(melody_layers=…)` restricts to the lead): cross-instrument
     recurrence is the whole point, and the polyrhythm recall lives on `04 Organ`, not
     the lead. Adapter test mirrors the melody adapter test BUT asserts that a
     non-lead layer's notes survive into the inputs (a Lead-only filter would fail
     this test).
  2. `src/hallucinote/tools/recurrence_lens.py` mirrors `tools/melody_lens.py`:
     imports a song's `build.py`, calls `recurrence_report()`, prints the reading
     (human + `--json` + `--section`); exit 2 = no such song, exit 3 = song hasn't
     wired `recurrence_report()`. Includes the honest framing in the rendered
     header (neutral facts, never a verdict; economy is style-relative; the
     registered-motifs-only blind spot — design.md §4 hybrid-hook note).
  3. `recurrence_report()` wired into sun-zone-done's `build.py` (sibling repo): build
     the in-memory arrangement with `Kit.gm_default()`, call `analyze_arrangement(arr,
     song_slug="sun-zone-done")`, return the report. **Do NOT mirror
     `melody_report()`'s `melody_layers=MELODY_LAYERS` argument (W2):** `recurrence_
     report()` passes NO layer filter — `analyze_arrangement` scans every layer.
     `melody_report()` restricts to `("05 Lead",)` because a line read is meaningless
     on chordal/drum layers; the recurrence lens must see `04 Organ` (the polyrhythm
     recall) too, so a naive mirror would silently drop the primary thin-slice signal.
     Build the REAL (breathed) arrangement — the same notes the lens reads in
     production (B1; design.md §4 step 4 rejects a non-breathed variant). **NOTE: this
     edit is in the `hallucinote-songs` repo, not the engine repo — split the commit
     accordingly (the song repo builds against the installed engine).**
  4. `skills/compose-review/SKILL.md` gains a "Recurrence / recapitulation (run the
     lens)" block under READ §2 + the one-sentence "no new axis; recurrence is part
     of the arrangement axis" note (design.md §6), with the honest caveats and the
     boundary note. **The block is authored to slot BESIDE the sibling READ-§2 blocks
     without double-reporting (W1):** MEL-1A7K's "within-line repetition" block AND
     ARR-7M3D's "energy realization" block also land in READ §2 (all three plans name
     this three-way same-file edit conflict; design.md §7). Restate the boundary in
     the block — recurrence = cross-instrument registered atoms; MEL = within-line
     n-gram; ARR-7M3D = energy curve — so no two blocks overlap in claim. If a sibling
     has already landed its block at edit time, place this block adjacently and do not
     duplicate its content; if not, leave the boundary note so the sibling slots in.
  5. **Live-fixture exercise (the VERIFIABLE SIGNAL) — stated as OBSERVABLE lens
     output (W4 + W2 + N1):** `python3 -m hallucinote.tools.recurrence_lens
     sun-zone-done` reports the three named recalls exactly as the section-keyed lens
     can emit them (there is no `climax` arrangement section — it is the late cells
     within the single `integration` section, `INTEG_CELLS`; design.md §0):
     - `polyrhythm-cloud` recurs in the **`integration`** section on layer
       **`04 Organ`** (beat offset ≈ 64 — the climax cells) as variation **`exact`**
       (transpose Δst=0, via containment — the late cells overlap the `FUSION_CHORD`
       hits, W3, yet still read `exact`, not `derived`);
     - `no-time-stab` recurs in the **`integration`** section on layer **`05 Lead`**
       (beat offsets ≈ 32–48 — the trade cells) as **`diminish∘fragment`**;
     - `no-time-stab` recurs in the **`outro`** section on layer **`05 Lead`**
       (BREATHED) as **`augment ×2`**.
     + the economy summary. **The song-level test in the song's repo
     (`songs/sun-zone-done/tests/`) asserts the SPECIFIC variation for each named
     recall (N1) — `exact` / `diminish∘fragment` / `augment ×2`, the section, AND the
     layer (`04 Organ` for the polyrhythm, `05 Lead` for the two no-time recalls) —
     NOT merely "a recall was found."** A `derived`-everywhere or Lead-only result must
     FAIL the test (W2: the polyrhythm-on-`04 Organ` assertion fails loud if a layer
     filter sneaks in; N1: `derived` does not satisfy the QUOTE/augment/fragment
     signal). The thin-slice positive fixtures are from research.md §4. A synthetic
     scattered/no-recall arrangement is the negative case (in `tests/unit/recurrence/`).
  6. **Doc-parity guard** (`learnings.md` "When a doc or duplicated contract IS the
     deliverable, lock it with a drift/parity test" + "Pattern sweeps are tree-wide"):
     tree-wide grep that `recurrence_lens` is referenced consistently across
     `skills/`, and the SKILL block's lens-command matches the actual CLI module
     path. **Also grep for the sibling READ-§2 blocks (W1):** confirm the
     "Recurrence / recapitulation" block coexists with (does not displace or
     duplicate) MEL-1A7K's within-line-repetition block and ARR-7M3D's energy-
     realization block when those have landed — and that the three boundary claims do
     not overlap. If a sibling block is absent (not yet merged), the boundary note
     placeholder must still be present so the sibling slots in. If a doc index pattern
     like melody's authoring-API test applies, mirror it.
  7. Full suite passes; `/critic` runs — this is the LAST chunk of a multi-chunk
     plan: declare **`Type: cumulative-final`** so `/critic cumulative` runs against
     `merge-base...HEAD` in addition to the chunk's `final` review (the cross-chunk
     integration check + the `/pr create` gate). Resolve blocking findings.
  8. Committed; chunk marked `[x]`; build-plan Status updated.
- **Type (override):** `cumulative-final` (last chunk, single-PR plan).
- **Governance checkpoint:** before-completion — the full read path is exercised on
  the live fixture and the docs reflect the code.

### Chunk 5 — DEFERRED (DISCOVERED-FROM-FRICTION, not silently dropped): authored `reference()` link (DR-1 Option B)

The both-sides completeness — `Arrangement.reference(motif, *, section, variation)`
recording the intended recap link + the lens verifying the declared link was
realized (the harmony-lint declared-vs-sounded shape). This is the equivalent of
melody/performance's deferred declared-profile grading.

- **Type:** code
- **Status:** DEFERRED. **Build only if friction shows detect-only misses intent
  that matters** (design.md DR-1) — e.g. a declared recap that didn't land where
  the matcher can't distinguish "not a recall" from "a recall I couldn't name."
  Carried as a tracked obligation (backlog it at PR time so the both-sides
  half-built state is explicit, mirroring how ARR-8P5K tracks performance's
  deferred halves). **Not part of this PR's scope** — named here so it is never
  silently dropped (the both-sides principle says a dimension authored but
  unmeasured is half-built; this records that the author-LINK side is the
  remaining half).
- **Done when (if built):** `Arrangement.reference(...)` records links; the lens
  reports declared-but-unrealized recaps as a loud INFO finding (the realization-bug
  shape, never blocking — ruler-not-stamp); arrangement-model.md Reference/recap
  row updated to note the link is now authored.

---

## PENDING by-ear calls (Live unattended this run)

1. **Match tolerance (onset/duration residual budget)** — Chunk 1 step 4. The single
   plausibly by-ear-adjacent dial. **NOT effectively exact (B1):** the outro augment
   recall is on `05 Lead`, which `_breathe` runs through `apply_profile`
   (`build.py:1318-1320`) — a correlated ≈1/f onset perturbation — BEFORE the notes
   enter the arrangement, so its onsets are off exact beats by a non-`_ONSET_EPS`
   amount. The two integration recalls ARE machine-tight (~`_ONSET_EPS`), but the
   tolerance is a SINGLE value and must absorb the worst case. Resolution: render-FREE
   symbolic measurement — the calibration print surfaces the measured residual for ALL
   THREE recalls (incl. the breathed outro); the tolerance is SET from the LARGEST
   measured number, NOT guessed and NOT assumed `_ONSET_EPS`. The PENDING flag exists
   so the value is *pinned to the measured breathed residual* rather than assumed away.
   No human ear required — the breathed onsets are deterministic (seeded
   `apply_profile`) and measurable symbolically, fully resolvable this run. If the
   measured breathed residual is large enough that a clean `augment ×2` cannot be
   distinguished from `derived`, that is a real finding to surface (not to hide under
   a loose tolerance) — but the augment is a 2× duration/onset SCALE, far larger than
   1/f jitter, so the expected outcome is clean recovery.

(No other by-ear calls: variation-type recovery, the economy formula, and the
surface wiring are symbolic and exact. The lens is render-free; nothing here is
render-gated.)

---

## Status

- [x] Chunk 1 — Thin slice: polyrhythm tiled quote end-to-end
- [x] Chunk 2 — Full variation-type recovery + honest non-match
- [x] Chunk 3 — Motivic-economy summary
- [x] Chunk 4 — Wire into /compose-review (adapter, CLI, song hookup, doc deltas) [cumulative-final]
- [ ] Chunk 5 — DEFERRED: authored reference() link (build only on friction)

**Context:** Chunks 1–4 DONE (DR-1 Option A, detect-only) — the read ships on the
existing sun-zone-done fixtures with no re-authoring. The matcher→lens→report→CLI
path is proven on all three real recalls (calibration-first):
- **Match tolerance PINNED to `_MATCH_TOL = 0.1`** (`match.py`), from the measured
  WORST-CASE breathed-outro residual ≈ 0.0322 beats (apply_profile/BREATH on
  `05 Lead`); the two integration recalls are machine-tight (~0). Loose tol gave
  WRONG variations (A read `augment ×2.13`, C read `exact`), proving the tight
  calibrated value is load-bearing.
- **Verifiable signal** (`python3 -m hallucinote.tools.recurrence_lens sun-zone-done`)
  reports the three named recalls: `polyrhythm-cloud`/integration/`04 Organ`/`exact`
  (containment), `no-time-stab`/integration/`05 Lead`/`diminish∘fragment ×2`,
  `no-time-stab`/outro/`05 Lead`/`augment ×2`, + economy (cell-set 2/2, coverage
  100%, compression-proxy 2.23, in COSIATEC's 2–4 band).

Engine-repo edits (branch `feature/arr-9k4t-recurrence-lens`):
`src/hallucinote/recurrence/{__init__,match,lens,economy}.py`,
`src/hallucinote/tools/recurrence_lens.py`, `src/hallucinote/arrangement.py`
(`section_recurrence_inputs()` adapter, NO layer filter — W2),
`skills/compose-review/SKILL.md` (Recurrence/recap READ §2 block + boundary note),
`.prawduct/artifacts/arrangement-model.md` (read-side note), `tests/unit/recurrence/`
(34 synthetic tests). Song-repo edit (separate commit, branch
`feature/arr-9k4t-recurrence-report` in `hallucinote-songs`):
`songs/sun-zone-done/build.py` (`recurrence_report()`, NO layer filter) + 4 song
tests asserting the specific variation/section/layer per real recall.

Chunk 5 (the authored `reference()` link, DR-1 Option B) is the tracked deferred
both-sides half — NOT built (no friction yet showed detect-only misses intent).

---

## Review resolution (REVISE → resolved)

Independent review verdict was **REVISE** (1 blocking, 4 warnings). All resolved in
design.md + build-plan.md; no requirement weakened. Code claims re-verified against
the real `hallucinote-songs/songs/sun-zone-done/build.py` before editing.

- **B1 (BLOCKING) — breathed-outro tolerance gap → RESOLVED.** Confirmed the outro
  `05 Lead` (carrying `_augmented_no_time` / `augment ×2`) IS breathed via
  `_breathe → apply_profile` (`build.py:1318-1320`) before entering the arrangement,
  while integration stays machine-tight (`build.py:1300`). Chose **Option (a)**:
  the single match tolerance is calibrated from the **breathed worst case**, not the
  machine-tight polyrhythm. design.md §4 step 4 rewritten (bimodal tolerance,
  transform-residual-robust matcher, Option (b) rejected); §0/§9 corrected; build-plan
  Confidence dropped to **Medium** (N5); Verification + Chunk 1 step 3/4 now measure
  all three recalls incl. the breathed outro and lock from the worst case; Chunk 2
  step 1/3 add the breathed-jitter recovery + boundary regression; PENDING entry
  rewritten (no longer "effectively exact"). Render-free, resolvable this run.
- **W1 — stale §7 collision analysis → RESOLVED.** Corrected the facts: MEL-1A7K
  HAS plan files and names a three-way COLLISION on `skills/compose-review/SKILL.md`;
  ARR-7M3D DOES touch compose-review (symbolic energy read, research.md:28,248).
  §7 rewritten as edit-surface coordination (not scope overlap); committed to
  authoring the "Recurrence / recapitulation" block to slot beside the sibling
  blocks without double-reporting; Chunk 4 step 4 + step 6 doc-parity grep now check
  the sibling blocks.
- **W2 — all-layers scan vs `melody_report()` mirror → RESOLVED.** Confirmed the
  polyrhythm recall is on `04 Organ` (`build.py:1017`) and `MELODY_LAYERS=("05 Lead",)`
  (`build.py:69`). design.md §3 adds an explicit "scans ALL layers, NO layer filter"
  contract; Chunk 4 step 1/3/5 state `recurrence_report()` passes no filter and assert
  the polyrhythm recall on `04 Organ` so a Lead-only regression fails loud.
- **W3 — climax-organ superset / containment semantics → RESOLVED.** Confirmed
  `_integration_climax_organ` returns recap + `FUSION_CHORD` hits in the same layer
  (`build.py:888-901`). design.md §4 step 2 specifies **subset/containment** (M ⊆
  cell window, extra notes allowed) and records the expected reading (late cells read
  `exact`-via-containment, not `derived`); Chunk 1 step 1 + Chunk 2 step 3 add the
  containment regression.
- **W4 — "integration climax" over-promises → RESOLVED.** Confirmed there is no
  `climax` arrangement section (it's the bar-16 cell within the single `integration`
  section, `INTEG_CELLS` `build.py:218-224`). §0 + Chunk 4 step 5 restate the criteria
  as observable lens output (section + layer + beat offset + specific variation).
- **N1/N2 folded in:** Chunk 4 step 5 asserts the SPECIFIC variation per recall (not
  "found something"); Chunk 2 step 1 notes `retrograde` derives span from M.
