# ARR-9K4T — Design: cross-instrument / arrangement-level recurrence READ

**Stage:** DESIGN (design-only; no production code). **Item:** measurement-coverage
gap (effort M, impact L). RECURRENCE/FORM is a first-class AUTHORED dimension
(`Arrangement.motif()` registers atoms; `generators.variations` transforms them;
recapitulation is load-bearing in sun-zone-done). The AUTHORING side ships; the
READ side does not exist. This design adds the read — a render-free symbolic lens
that, given an in-memory `Arrangement`, reports **which registered motifs recur
where (and as which variation)** plus a **motivic-economy summary**, wired into
`/compose-review`. Research foundation: `research.md` (this dir) — linked, not
restated.

---

## 0. Confidence-check (the three questions)

- **Problem:** RECURRENCE is authored but unmeasured — no tool verifies a
  registered motif was actually recalled in a later section, detects a
  recapitulation and its variation type, or reports motivic economy (small
  recurring cell-set vs scattered). A dimension authored but unmeasured is
  half-built (the BOTH-SIDES principle the harmony/melody/performance lenses each
  satisfied).
- **Success:** `recurrence_report()` (the per-song convention) +
  `hallucinote.recurrence.analyze_arrangement(arr)` returns, for sun-zone-done, the
  three named recalls **stated as observable lens output the section model can
  actually emit** (W4 resolution — there is no addressable `climax` arrangement
  section; "climax" is the last cells *within* the single 32-bar `integration`
  section, `INTEG_CELLS`, `build.py:218-224`; the lens keys by arrangement section,
  not sub-section cell label):
  - **`polyrhythm-cloud` recurs in the `integration` section on layer `04 Organ`**
    (beat offset ≈ 64 within the section — the climax cells, `INTEG_CELLS` bar 16 ×
    BPB 4) **as a tiled QUOTE** (variation `exact`, transpose Δst=0, via containment);
  - **`no-time-stab` recurs in the `integration` section on layer `05 Lead`** (beat
    offsets ≈ 32–48 — the trade cells) **as `diminish∘fragment`** (`build.py:1002`);
  - **`no-time-stab` recurs in the `outro` section on layer `05 Lead`** (beat offset
    ≈ 32) **as `augment ×2`** (`build.py:1063`) — this layer is BREATHED (B1), so the
    recall must recover under the calibrated breathed tolerance, not exact-grid.

  The test asserts the **specific variation** for each named recall (not merely "a
  recall was found" — see N1; a `derived`-everywhere result must fail the signal),
  plus a motivic-economy summary, and `tools/recurrence_lens.py` surfaces this to
  `/compose-review`. Render-free, pure-stdlib, info-only (never a verdict).
- **Out of scope:** undirected discovery of UNregistered recurring cells
  (COSIATEC's job; MEL-1A7K's deferred line-level n-gram read); audio-side
  anything; any "is this recapitulation *good*?" verdict (style-relative —
  Temperley, `research.md` §2); detecting recall under ARBITRARY transform
  compositions (bounded to single-op + the two 2-op fixtures the song uses, see §4).

---

## 1. The both-sides shape

RECURRENCE already has a partial author side and **no** read side. The taxonomy
(`arrangement-model.md` "The primitives") lists FOUR recurrence-relevant
primitives, and a load-bearing structural finding from `research.md` §1 shapes
this whole design:

| Primitive | Author side (today) | Read side (this item) |
|---|---|---|
| **Motif** | `Arrangement.motif(name, notes)` — registers a named atom (`arrangement.py:126`) | the registry is the lens's query set ✓ |
| **Variation op** | the canonical six in `generators/variations.py` | matcher recovers WHICH op was applied ✓ |
| **Reference / recap** | **DOES NOT EXIST as a link** — see Decision-Record 1 | the central design fork |
| **Recurrence (delta)** | `vary()` (`arrangement.py:418`) | covered by motif-recall detection where the delta quotes a motif |

**The structural finding (verified by reading the code):** `Arrangement` stores
`self.motifs` (name→`Motif`) but has **no `reference()` method** (`grep "def
reference"` returns nothing; the only hits are docstrings). The taxonomy's
"Reference / recap" row is **documented-but-unbuilt**. Recaps are realized by
passing `motif.notes` as a raw list into composer functions — e.g. in
sun-zone-done:

- `_integration_play(kit, prog, poly.notes, no_time.notes)` (`build.py:1303`) —
  `poly.notes` flows to `_integration_climax_organ` → `_polyrhythm_callback`,
  which **tiles** the registered 2-bar cell via `V.shift(motif_notes, c*cell)`
  then the whole thing is `V.shift(..., start_beat)` (`build.py:769,890,1017`).
- `_outro_lead(ob, no_time.notes)` → `_augmented_no_time` →
  `V.augment(no_time_motif, 2.0)` then velocity-softened then `V.shift`
  (`build.py:1035,1315`).

So **there is no link to "follow"** — the read-side must either DETECT the recall
from realized notes, or the model must first ADD an authored link. That is
Decision-Record 1 (the central fork).

### What the lens IS (the both-sides MEASURE side)

A pure symbolic lens `hallucinote.recurrence` — sibling to `theory.lint`,
`melody.lens`, `performance.lens` — that, per (motif × section), reports:

- **recall**: did this registered motif appear in this section's realized layers?
- **variation**: as which transform (an `exact` quote, or a recovered single op:
  `transpose Δst`, `augment ×f`, `diminish ×f`, `invert`, `retrograde`,
  `fragment[window]`, `shift`), or a recovered 2-op composition the fixtures use
  (`diminish∘fragment`), or `derived` (a partial/over-threshold match the matcher
  can't fully name — reported honestly, never silently missed).
- **where**: section name + the layer (track) it was found on + the beat offset.

And per song:

- **motivic-economy summary**: cell-set size (distinct registered motifs actually
  recalled), recall coverage (fraction of registered motifs that recur at least
  once beyond their home section), and a **compression-ratio proxy** (`research.md`
  §2 — realized note-mass ÷ encoded size, the COSIATEC ⟨P,V⟩ shape with P GIVEN
  rather than discovered). Reported as a FACT, never a verdict.

It mirrors the established lens contract: frozen dataclasses, a local `Severity`
Literal, an explicit `to_dict()` boundary, **every finding `severity="info"`**
(authored recurrence choice is not an error — Temperley style-relativity,
`research.md` §2), `ok` always True (kept for interface parity).

### Ruler-not-stamp boundary (made explicit)

- The lens **never invents a recurrence** and never tells the composer "recall
  this motif here" — that is the art (the model is explicit: "how the fusion
  sounds" is the composer's, `arrangement-model.md` Reference/recap row).
- It **measures and reports**: which registered atom recurred, under which
  algebraic transform, and the economy facts. It is a RULER (removes the
  bookkeeping of "did my quote actually land, and as what?") — info/coaching
  surfaced through `/compose-review`, never a build gate.
- The economy summary is **descriptive, never prescriptive**: a through-composed
  piece is *legitimately* less economical than a minimalist one (Temperley). The
  lens reports the number; it never says "be more economical." No "scattered
  material" verdict — only the cell-set-size / coverage / compression facts that
  *feed* a composer's own judgment, exactly as `melody.lens` reports step↔leap
  without verdicting "shaped vs aimless."

---

## 2. Boundary vs MEL-1A7K (must not overlap) — made explicit

`research.md` §5 carries the table; the load-bearing distinction:

- **ARR-9K4T (this)** is **cross-instrument, arrangement-level**: registered
  motifs recurring across organ / lead / etc., keyed by the `Arrangement` motif
  registry. The query is **KNOWN** (the registered motifs) → it is *directed
  transform-and-match against a closed six-op algebra*. Source of truth: the motif
  graph + per-section layers.
- **MEL-1A7K (deferred)** is **one monophonic line's internal n-gram repetition**
  — UNKNOWN query → undirected discovery (`melody/lens.py` docstring ~L48-50:
  "Motivic-economy / n-gram repetition readings … are friction-driven
  follow-ons", line-level, NOT-YET). It needs an n-gram / IDyOM-style read within a
  single line.

These do not overlap and must not: ARR-9K4T reads the *form/recap* structure
intent and **does not re-implement melody's line reading**. When MEL-1A7K
eventually ships its line-level n-gram read, the two lenses report on different
units (the arrangement's registered motifs vs. a single line's internal cells)
and both feed `/compose-review`. The collision is on the SKILL wiring only — see §7.

---

## 3. Module + surface layout (mirror the melody lens exactly)

```
src/hallucinote/recurrence/
    __init__.py            # re-export analyze_arrangement, analyze_recurrence, dataclasses
    lens.py                # RecurrenceReport / SectionRecurrence / MotifRecall / RecurrenceFinding
                           #   + analyze_recurrence(sections) + analyze_arrangement(arr)
    match.py               # the directed transform-and-match core (pure note-arithmetic)
    economy.py             # the motivic-economy summary (cell-set, coverage, compression proxy)
src/hallucinote/tools/
    recurrence_lens.py     # CLI mirroring tools/melody_lens.py — feeds /compose-review
tests/unit/recurrence/
    test_match.py  test_economy.py  test_lens.py  __init__.py
```

**The adapter lives on the arrangement; the lens stays a leaf** (same topology as
melody). `Arrangement` gains `section_recurrence_inputs()` returning a list of a
new decoupled `SectionRecurrenceInput` dataclass (carrying section name, beat
span, layers, and — crucially — the section's start beat so a tiled recall's
absolute offset can be normalized). The motif registry (`arr.motifs`) is passed
alongside. `analyze_arrangement(arr)` is a thin wrapper kept in `recurrence/lens.py`
(NOT on `arrangement.py`) so the recurrence layer never makes the arrangement
depend on it at runtime — identical to how `melody.lens.analyze_arrangement`
imports the `Arrangement` only under `TYPE_CHECKING`.

**Critical contract — the recurrence lens scans ALL layers; it takes NO layer
filter (W2 resolution).** This is the one place where mirroring melody is a TRAP.
`section_melody_inputs(melody_layers=…)` restricts to the monophonic lead
(`MELODY_LAYERS = ("05 Lead",)`, `build.py:69`) because a *line* read is meaningless
on chordal/drum layers. But cross-instrument recurrence is the whole point of this
lens: the **polyrhythm-cloud recall lands on `04 Organ`** (`build.py:1017` →
`_integration_climax_organ`), the no-time recalls land on `05 Lead`, and a drum
motif could in principle recur on `01 Drums`. `section_recurrence_inputs()` therefore
returns EVERY layer of every section (no `recurrence_layers` parameter, no default
exclusion) — and `recurrence_report()` (§ per-song convention) must NOT thread a
layer filter through. Mirroring `melody_report()`'s `melody_layers=MELODY_LAYERS`
argument would silently DROP the polyrhythm-on-Organ recall (the thin-slice signal
of Chunk 1). The build-plan asserts the polyrhythm recall is found specifically on
`04 Organ` so a Lead-only regression fails loud.

### The per-song convention

`recurrence_report()` in each song's `build.py`, mirroring `melody_report()`
(`build.py:1843`): build the in-memory arrangement with a GM-default kit, call
`hallucinote.recurrence.analyze_arrangement(arr)`, return the `RecurrenceReport`.
`tools/recurrence_lens.py` imports the song's `build.py`, calls
`recurrence_report()`, and prints the reading (exit 3 if the song hasn't wired it,
exactly like `melody_lens.py`).

---

## 4. The matcher — directed transform-and-match (the core algorithm)

The matcher answers: *was registered motif M recalled in section S's layers, and
as which variation?* M is a single 0-based cycle (the registered atom); S's layers
are TILED, SHIFTED realizations. Per `research.md` §3 and `learnings.md:390`
("Variation ops are tiling-safe only on single-cycle motifs"), the matcher must
align the single-cycle M against tiled positions in the layer — naive whole-span
comparison false-negatives.

**Algorithm (per motif M, per layer L in section S):**

1. **Normalize both to a comparable signature.** Reduce each to an onset-sorted
   list of `(start_beats, pitch, duration_beats)` triples (velocity and tags are
   not identity-bearing for recall — a recall can be re-voiced in dynamics, as the
   outro's velocity-softened augment shows). Drop to a relative frame: subtract the
   first onset (so absolute placement / `shift` is factored out — `shift` is the
   placement utility, not a recurrence-identity change).
2. **Slide a window of M's span across L** at each candidate cell offset (M.span,
   2·M.span, … the tiling grid) AND test the obvious transforms. **Matching is
   SUBSET / CONTAINMENT, not equality (W3 resolution):** the test is *"M (under the
   transform) is PRESENT in the cell window"* — M's transformed notes ⊆ the window's
   notes (within tolerance), **extra non-motif notes in the window allowed**. This is
   load-bearing: `_integration_climax_organ` (`build.py:888-901`) returns the tiled
   polyrhythm recap PLUS two sustained `FUSION_CHORD` hits **in the same `04 Organ`
   layer**, landing at `peak = start_beat + (bars-8)·BPB` onward — so they overlap
   the LAST 8 bars of the tiling grid. With equality semantics those late cells would
   contain motif notes AND fusion notes and read `derived`, degrading the "tiled
   QUOTE" signal to a partial false-negative. With containment, the late cells'
   polyrhythm content still recovers as the QUOTE; the fusion hits are simply extra
   notes the matcher does not require M to explain. **Expected reading (recorded
   spec decision):** the early cells (clean, no fusion overlap) read `exact` (Δst=0
   transpose); the overlapped late cells ALSO read `exact`-via-containment (M ⊆
   window), NOT `derived` — the QUOTE recurs across the whole tiling grid. The recap
   is velocity-boosted (+12, in `_integration_climax_organ` ~`build.py:894`); per
   DR-4 velocity is excluded from the match signature, so the boost does not change
   the reading.

   Transforms tested per window:
   - **exact / transpose**: relative-onset pattern identical, pitches differ by a
     constant Δst (Δ=0 ⇒ exact quote) → `transpose Δst`.
   - **augment/diminish**: relative onsets AND durations scale by a constant
     factor f, pitches identical → `augment ×f` (f>1) / `diminish ×f` (f<1, report
     as `diminish ×(1/f)`).
   - **invert**: relative onsets identical, pitches satisfy `p' = 2·axis − p` for
     a constant axis → `invert`.
   - **retrograde**: onset sequence is the time-reversal → `retrograde`.
   - **fragment[a,b)**: M restricted to its `[a,b)` onset window matches L's cell
     (a sub-pattern recall) → `fragment[a,b)`.
3. **The two 2-op compositions the fixtures use** (bounded, named — NOT a general
   composition search): `diminish∘fragment` (the integration trade-cell:
   `V.diminish(V.fragment(no_time, 0,4), 2.0)`) and `augment∘(velocity-softened)`
   reducing to the augment signature (the outro — velocity is non-identity-bearing,
   so this matches as plain `augment ×2`). Apply by first fragmenting M to each of
   its natural sub-windows, then testing augment/diminish on the fragment.
4. **Tolerance — NOT uniformly `_ONSET_EPS`; the fixtures are NOT all
   machine-tight (B1 resolution).** The earlier draft assumed "the lens matches the
   pre-breath authored notes, so the tolerance is tight (~`_ONSET_EPS`)." **That
   premise is FALSE for the outro augment recall, and silently risks failing 1/3 of
   the verifiable signal.** Verified in `hallucinote-songs/songs/sun-zone-done/
   build.py`: `_build_arrangement()` calls `_breathe(outro, plan={…, "05 Lead":
   BREATH})` (`build.py:1318-1320`) — `_breathe` runs `apply_profile(notes, profile,
   seed=…)` (`build.py:1209-1214`), the correlated ≈1/f onset-deviation authoring
   pass — and `05 Lead` is exactly the layer carrying `_outro_lead → _augmented_
   no_time → V.augment(no_time, 2.0)` (`build.py:1041,1056,1063`). The breath is
   baked into `build.py` **before** the notes enter `arr.section(...)`, so there is
   **no separate post-arrangement `apply_profile` pass to read around**; the
   in-memory `Arrangement` the lens receives already carries the perturbed onsets.
   `recurrence_report()` builds the *real* (breathed) arrangement, so the outro
   recall reaches the matcher off exact beats by a non-`_ONSET_EPS` amount. The
   integration recalls (polyrhythm climax, no-time trade-cell) are on the **one**
   section that stays machine-tight (`build.py:1300` "Stays machine-tight"; outro is
   breathed). **So the tolerance is bimodal: exact-beat for the integration recalls,
   breathed for the outro recall.**

   **Resolution (chosen — Option (a), calibrate against the BREATHED worst case):**
   the match tolerance is a single value set from the **worst-case (breathed-outro)**
   measured residual, not from the machine-tight polyrhythm. Chunk 1's calibration
   print MUST run all THREE real recalls (polyrhythm climax, no-time trade-cell,
   **breathed outro augment**) through the matcher and report each one's onset/
   duration residual; the tolerance is set from the largest (the breathed outro).
   This is render-FREE (symbolic measurement of the breathed in-memory notes) and it
   *strengthens* the calibration-first discipline. Option (b) — having
   `recurrence_report()` build a non-breathed arrangement to read pre-breath notes —
   is **rejected**: it would make the lens read something the song does not actually
   ship and would diverge from the `melody_report()` mirror (melody reads the
   breathed arrangement). **The exact slack value is the one plausibly
   by-ear-adjacent dial — flagged PENDING in the build-plan** (`research.md` §6.4):
   render-free measurement surfaces the measured breathed-onset deviations; the
   tolerance is set from the measured worst-case number, not guessed, and is NOT
   assumed to be `_ONSET_EPS`.

   **The matcher must be transform-residual-robust, not onset-grid-robust.** Because
   `apply_profile` perturbs each onset by a correlated 1/f offset (NOT a uniform
   shift), the relative-onset signature of the breathed recall differs from the
   authored cycle by per-note jitter. The window-slide match therefore compares
   relative-onset signatures with the calibrated breathed tolerance (a per-note
   onset-residual budget), not an exact-grid test. The duration test (for
   augment/diminish) likewise tolerates the breathed duration jitter. This is what
   makes the breathed `augment ×2` recover as `augment ×2` rather than collapsing to
   `derived`/no-recall.
5. **Honest non-match.** If a layer-cell partially matches M (≥ a coverage
   threshold of M's notes align under some transform) but no clean op is
   recoverable, report `variation="derived"` with the coverage fraction — NEVER
   silently drop it. Below the coverage threshold ⇒ no recall reported for that
   (motif, cell). The coverage threshold is a reporting floor mirroring
   `theory.lint`'s `out_of_chord_warn` (calibrated, not a gate).

**Why this is exact, not ML (`research.md` §1):** we own BOTH the query motif (the
registry) and the transform algebra (the six pure functions). This is directed
match against a known query, not undirected mining. No corpus, no trained model.

**A known blind spot to report honestly:** the **hybrid hook** recurs (climax +
outro augment) but is NOT a *registered* motif (`_hybrid_hook()` is a free
function, never `arr.motif(...)`). A registry-keyed read cannot see its recall.
This is correct scoping — the lens reads *declared* recurrence (registered atoms),
and the fix if a composer wants the hybrid tracked is to register it
(`arr.motif("hybrid", ...)`), which is an authoring choice. The lens's docstring
and the `/compose-review` wiring must state this limitation plainly (the same
honesty as melody's "no universal good melody").

---

## 5. The motivic-economy summary (`research.md` §2 — the one cited metric)

Computed off the already-known motif set — NOT a full COSIATEC run (we have P
given, so we skip the discovery half):

- **cell-set size** — count of distinct registered motifs that recur at least once
  beyond their first (home) occurrence.
- **recall coverage** — `recurring_motifs / registered_motifs` (a motif registered
  but never recalled is a fact worth reporting — possibly dead weight, possibly
  intended one-shot material; the lens reports, never judges).
- **compression-ratio proxy** — `total recalled-section note-mass ÷ (motif-library
  note-count + per-occurrence placement/variation records)`. The COSIATEC ⟨P,V⟩
  encoding shape with P given. COSIATEC's empirical range is 2–4 (`research.md`
  §2); the lens reports the raw number, no target.

**Severity: INFO only, always.** Per Temperley's style-relativity, high vs low
economy is **not a universal good** (`research.md` §2). The summary is a reported
fact; there is deliberately NO "your material is scattered" finding. The single
INFO finding the lens may emit is the registered-but-never-recalled observation,
framed as a question ("`X` was registered as a motif but never recurs — intended
one-shot material, or a planned recall that didn't land?"), mirroring melody's
`static-line` coaching question.

---

## 6. PROPOSED canonical deltas (recorded; NOT applied — Critic governs edits)

### `arrangement-model.md`

- **"The primitives" table, Reference/recap row** — append a note that the
  recurrence READ side now exists: a build-time symbolic lens
  (`hallucinote.recurrence`) reports which registered motifs recur where and as
  which variation, plus a motivic-economy summary, parallel to the harmony
  conformance lint / melody lens / performance lens — closing the BOTH-SIDES gap
  for recurrence. Link to the lens; do not restate the method (LINK-DON'T-SUMMARIZE).
- **If Decision-Record 1 lands the `reference()` author primitive** — update the
  same row to note the link is now authored (`Arrangement.reference(motif,
  section, variation)`) and the lens verifies the declared link was realized
  (verify-the-declared-link, the harmony-lint shape). If DR-1 stays detect-only,
  the row's "documented-but-unbuilt" status is unchanged for the author side and
  the note covers only the read.

### `melody-model.md` §6 / `melody/lens.py` docstring (boundary note only)

- Add a one-line cross-reference that **cross-instrument / arrangement-level**
  motivic-recurrence reading is owned by `hallucinote.recurrence` (ARR-9K4T), and
  the deferred **line-level** n-gram motivic-economy read (MEL-1A7K) remains
  melody's, so the boundary is documented at both ends. (PROPOSED — do not edit
  the canonical doc now.)

### `skills/compose-review/SKILL.md`

- In READ (§2), after the "Line-level melody (run the lens)" block, add a
  **"Recurrence / recapitulation (run the lens)"** block: `python3 -m
  hallucinote.tools.recurrence_lens <song-slug>` reporting which registered motifs
  recur where + variation type + the motivic-economy summary. Carry the same
  honest framing: neutral facts, never a verdict; economy is style-relative; the
  hybrid-hook blind spot (only *registered* motifs are read); grade against the
  song's declared recurrence intent and LEARN-BACK.
- In "One axis per turn", the **arrangement** axis already owns
  "layering/density/contrast/energy arc" — recurrence/recapitulation is part of
  the arrangement axis (form). No new axis; one sentence noting the recurrence
  lens feeds the arrangement-axis read.

---

## 7. Collision analysis (flagged per the briefing — CORRECTED, W1 resolution)

Wiring touches `skills/compose-review/SKILL.md`. The earlier draft of this section
was factually STALE on two points; both are corrected here against the real sibling
plans (read directly, not assumed):

- **MEL-1A7K** — **DOES have plan files** (`.prawduct/artifacts/plans/MEL-1A7K/`
  contains `design.md`, `build-plan.md`, `research.md`). Its build-plan explicitly
  names a **three-way COLLISION on `skills/compose-review/SKILL.md`** among MEL-1A7K
  + ARR-9K4T + ARR-7M3D (MEL-1A7K/build-plan.md lines 40-41, 200-201, 246-247, 260 —
  "all three edit the READ step"), and treats it as coordinate-NOW work (Chunk 6,
  its `/compose-review` edit). MEL-1A7K owns the **within-line n-gram repetition**
  read.
- **ARR-7M3D** — **DOES touch `skills/compose-review/SKILL.md`** (its primary
  surface is `/mix-review`, but it also makes a *symbolic energy read* edit to
  compose-review: ARR-7M3D/research.md line 28 references `/compose-review`
  SKILL.md:84, and line 248 lists `skills/compose-review/SKILL.md` (symbolic energy
  read) among its files). The earlier draft's claim "ARR-7M3D does NOT collide with
  this item's `/compose-review` edit" was FALSE. ARR-7M3D owns the **energy
  realization** read.

**Nature of the collision: edit-surface coordination, NOT scope overlap.** The
substantive BOUNDARY is drawn consistently in ALL THREE plans and is correct — there
is no claim-overlap, only a same-file edit conflict on the READ §2 block:
- **ARR-9K4T (this)** — cross-instrument registered-motif recurrence/recapitulation.
- **MEL-1A7K** — within-line (single monophonic line) n-gram repetition.
- **ARR-7M3D** — symbolic energy-curve read (declared `energy_curve` ordering).

**Commitment (the concrete coordination):** this item authors a *distinct,
clearly-labeled* **"Recurrence / recapitulation (run the lens)"** block under READ
§2 that slots BESIDE the sibling blocks — MEL's "within-line repetition" block and
ARR-7M3D's "energy realization" block — **without double-reporting** and without
claim-overlap (the boundary note in §2 above is restated in the block). Per
`learnings.md` "A permission to collaborate must restate precedence" / the
tree-wide-sweep rule, the three blocks must not overlap in claim. **Chunk 4's
doc-parity grep checks for the sibling blocks too** (not just `recurrence_lens`
self-consistency) so a later sibling merge that displaces or duplicates this block
is caught.

No production-code file collision: `hallucinote.recurrence` is a new package; none
of the named items create it. This render-free item never touches `report.py`
(ARR-7M3D's audio surface), so there is no `report.py` collision.

---

## 8. Decision-Records

### DR-1 — Detect-only vs. add an authored `reference()` link (THE central fork)

**Context:** `research.md` §1/§6.1 — the arrangement has no recap LINK today; the
"Reference / recap" taxonomy primitive is documented-but-unbuilt. Two ways to
build the read:

- **Option A — detect-only (no model change).** The lens infers recalls from the
  realized section layers via the §4 matcher. No new `Arrangement` method.
  - *Pros:* zero author-surface change; works on EVERY existing song (incl.
    sun-zone-done) with no re-authoring; ships the read fastest (the half the
    item's impact rests on); matches the research's "detection half needs no
    literature, it's directed match."
  - *Cons:* the lens can only verify what it can *detect*; a recall the matcher
    can't name reads `derived`; it does not capture composer *intent* ("I meant
    this as a recap of X") — only realized fact.
- **Option B — add `Arrangement.reference(motif_name, *, section, variation)`**
  (the documented-but-unbuilt primitive), recording the intended link; the lens
  then **verifies the declared link was realized** (the harmony-lint shape:
  declared vs sounded).
  - *Pros:* the more complete BOTH-SIDES answer (matches how harmony / performance
    / melody were each done — author surface + realization-conformance read);
    captures intent the matcher can't infer; a declared-but-unrealized recap
    becomes a loud, honest finding ("you declared `no-time-stab` recurs in the
    outro as augment — it does NOT appear there"), which is exactly the
    realization-bug shape `theory.lint` catches for harmony.
  - *Cons:* requires re-authoring existing songs to declare links (or the read is
    empty for them); larger surface; risks an authored link drifting from the
    realized notes (mitigated — that drift IS the finding the lens surfaces).

**Decision (proposed, for Critic):** **Ship Option A first (detect-only) as the
thin slice and the MVP**, because (1) it delivers the item's verifiable signal on
the EXISTING sun-zone-done fixtures with no re-authoring, (2) the research is
explicit that the detection half needs no literature and is exact, and (3) it
satisfies DISCOVERED-FROM-FRICTION — we do not add the `reference()` author
primitive speculatively. **Then add Option B as a fast follow** *iff* friction
shows detect-only misses intent that matters (e.g. a declared recap that didn't
land and the matcher couldn't distinguish "not a recall" from "a recall I can't
name"). The build-plan sequences A as Chunks 1–4 and carries B as a flagged,
DISCOVERED-FROM-FRICTION follow-on chunk (Chunk 5), NOT silently dropped — the
both-sides completeness is named as the deferred work, mirroring how
performance/melody deferred their declared-profile grading. This keeps the
author-side primitive as a real, tracked obligation while shipping the read now.

*Trade-off accepted:* the MVP reads realized fact, not declared intent. That is
the same honesty the melody lens accepted (it reads "what's authored, not what was
declared" until the profile object existed). The deferred B is the equivalent of
melody's phase-2b.

### DR-2 — Transform-composition search depth

**Context:** `research.md` §3/§6.2 — detecting an ARBITRARY composition of the six
ops is a small but unbounded search.

**Decision (proposed):** Bound the matcher to **single-op recovery + the specific
2-op composition the fixtures use** (`diminish∘fragment`). The outro's
`augment∘velocity-soften` reduces to a single `augment` match (velocity is
non-identity-bearing). Anything beyond ⇒ reported `derived` with coverage, never
silently missed. *Rationale:* DISCOVERED-FROM-FRICTION — build for the recalls
that actually occur in the corpus; widen the search only when a real song forces a
deeper composition. A general composition search is speculative machinery (the
overcomplication tell). *Trade-off:* a future song using e.g.
`invert∘retrograde∘transpose` reads `derived` until that composition is added —
acceptable because `derived` is honest (not a false negative) and the widening is
a one-function extension.

### DR-3 — Economy metric severity and shape

**Decision (proposed):** Economy is reported as a **fact** (cell-set size,
coverage, compression-ratio proxy), `severity` not applicable to the summary
itself; the only finding the economy path emits is the
registered-but-never-recalled INFO question (§5). NO "be more economical" finding
EVER (Temperley style-relativity — `research.md` §2). *Rationale:* ruler-not-stamp
+ the melody/harmony lens precedent (info-only, questions not verdicts).
*Trade-off:* the lens won't *tell* a composer their material is scattered — by
design; it gives them the number and trusts their ear, exactly as `/compose-review`
already trusts the artist.

### DR-4 — Velocity and tags are not recurrence-identity-bearing

**Decision (proposed):** Recall identity is `(relative-onset, pitch, duration)`;
velocity and tags are excluded from the match signature. *Rationale:* the outro
recall is velocity-softened (`build.py:1042`) yet is unambiguously the same motif
augmented — a recall is re-voiceable in dynamics. *Trade-off:* a "recall" that
differs ONLY in velocity reads as exact; that is correct (it IS the same motif).

---

## 9. Requirements-confidence inputs (for the build-plan)

The matcher's correctness is **objectively checkable, render-free** against the
sun-zone-done fixtures (the polyrhythm tiled quote on `04 Organ`; the no-time
diminished-fragment in the trade cell on `05 Lead`; the no-time augment in the
**breathed** outro on `05 Lead`). The ONE plausibly by-ear-adjacent dial is the
onset/duration match tolerance (§4 step 4) — flagged PENDING in the build-plan:
measure the realized onset deviations symbolically **including the breathed-outro
worst case** (B1), set the tolerance from the measured worst-case number, do not
guess and do not assume `_ONSET_EPS`. Everything else (variation-type recovery,
economy formula, surface wiring) is symbolic and exact.

**Confidence is Medium, not High (B1/N5).** The breathed-outro tolerance is a
genuine unmeasured dial: until Chunk 1's calibration measures the breathed onset
residual, the exact tolerance is unknown (the earlier "exact-beat authored" premise
was false for the outro). The matcher's *structure* is fully understood and the
measurement is render-free and fully doable this run — so the gap is narrow and
closes inside Chunk 1 — but the honest level is Medium until that measurement lands.
