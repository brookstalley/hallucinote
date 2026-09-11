---
lifecycle: completed
archived: 2026-09-08
unbuilt_at_archive: "no readable `## Status` roster — completeness cannot be read, and an unreadable plan is not evidence of completion"
maintained: false
---

> **Archived — no longer maintained.** This plan records what was built, not what will be. Do not edit it to reflect later changes; write those where they are true.

# ARR-7M3D — Independent Spec Review (adversarial)

**Reviewer:** independent DESIGN critic (did NOT author the design).
**Verdict: REVISE.** Three real defects; two are blocking correctness bugs the
design's own claims actively paper over. The design is otherwise unusually
well-grounded — the DR-1 source-of-truth discovery is real, the migration
precedent is exact, ruler-not-stamp is explicit with a lock test, BOTH-SIDES is
honored, and the by-ear call is flagged-not-guessed. The blockers are narrow and
cheaply fixable in the plan before building.

Grounding I verified against the actual code (so these findings aren't
speculative):

- `Arrangement.materialize` (arrangement.py:372-376) genuinely does NOT pass
  `energy` to `M.create_section` — DR-1's root-cause claim is TRUE.
- `sections` schema (schema.sql:128-137) has no energy column — TRUE.
- `_ADDED_COLUMNS` + `_check_schema_canary` migration pattern with the
  `sends.intended_rt60_s` precedent (connection.py:115-119) is EXACT as claimed.
- `lufs_s_median` on `LoudnessMetrics` (report.py:50), `skipped_analyses` on
  `MixReport` (report.py:491), `to_json_dict` explicit-serializer pattern, scipy
  ≥1.11 dep — all verified present.
- mix-review SKILL.md has MEASURE (§2) + INTERPRET (§3) with the feed-bullet
  pattern; the floors `_MASKING_REPORTING_FLOOR`/`_TIMING_MIN_CONFIDENCE` exist.
- `_extract_song_structure` does `dict(row)` (analysis.py:539,546) so the new
  column "rides for free" — TRUE.

---

## BLOCKING

### B1 — Spearman ρ can be `nan` (tied/constant correlate), which the shape forbids AND breaks JSON

The design asserts (design §2, §4; DR-5) that "Spearman ρ itself needs NO
threshold to report" and "always lands" — used to justify why ρ is the
ever-present scalar and only the per-pair gate is by-ear. **This is false.** I
probed `scipy.stats.spearmanr` directly:

- All-ties / constant measured input (e.g. a flat-loudness render, or two
  sections measuring identical LUFS) → `statistic = nan` (with a
  `ConstantInputWarning`).
- `MixReport.energy_realization.correlate_rho: dict[str, float]` (DR-2) has no
  `nan`/`None` provision.

Worse, the report is serialized with **default `json.dumps`** (analysis.py:457,
no `allow_nan=False`), which emits a bare `NaN` token — **invalid JSON** that
strict consumers (`JSON.parse`, the eval judge, any non-Python reader) reject.
A tied/flat-loudness section set therefore writes a report file that breaks
downstream parsing — a silent correctness defect that masquerades as "ρ always
lands."

This is the *exact* class the project has been burned by repeatedly:
"DSP with a detection front-end: calibrate against real cases, don't assert from
intuition" — the assumption "ρ always lands" is intuition; the real function
returns `nan` on ties.

**Fix (in the plan, before building chunk 3):**
1. DR-2: change `correlate_rho` to `dict[str, float | None]` (or drop the key
   for an undefined correlate) and define the undefined-ρ contract: when
   `spearmanr` returns `nan` (ties / constant measured), record the correlate as
   `None` and add a `skipped_analyses` entry naming *why* ("loudness ρ undefined:
   measured values tied across sections") — never serialize `nan`.
2. Chunk 3 acceptance criteria must add a test for the tied/constant case
   (declared `[A:0.3,B:0.6,C:0.9]` with measured loudness all-equal → ρ is
   `None`/skipped, not `nan`), alongside the existing monotonic and inversion
   tests. The current criterion-4 test set (perfect-monotonic, deliberate
   inversion, curvilinear-monotonic) silently omits the degenerate case that
   actually breaks.
3. Confirm the JSON write path either passes `allow_nan=False` (so a stray `nan`
   fails loud instead of writing invalid JSON) or that all ρ are `None`-or-finite
   by construction. Either is acceptable; silently writing `NaN` is not.

### B2 — Name-keyed section join silently mis-pairs repeated section names — and the design's own cited example triggers it

Chunk 3 criterion 2 and chunk 4 criterion 1 both join declared energy to
measured sections **"by name, the join key the lens uses."** But:

- The `sections` table has **no UNIQUE constraint on `name`** (schema.sql:131 is
  bare `TEXT NOT NULL`; the only uniqueness is `UNIQUE(song_id, start_bar)` on
  *sibling* tables — sections has none on name).
- Repeated section names are normal and intended: the arrangement model supports
  `vary()` / recapitulation (arrangement.py — `vary`, Motif `reference`), so
  "Chorus" appears 2-3 times. Two sections named "Chorus" with **different
  energy** is precisely the **Nobile energy-drop-into-(final-)chorus** case the
  design itself holds up as the ruler-not-stamp authorship example (design §2,
  citing arrangement-model.md:238).

A name-keyed join collapses or mis-pairs those rows: the lens correlates the
wrong measured window against the wrong declared energy, and the headline
deliverable (per-section declared-vs-measured) is *wrong on the exact song shape
the design says it must respect*. This is not an edge case — it's the central
case.

The robust key exists and is already in hand: both `SectionMetrics`
(report.py:401, `start_beat`) and the DB section row (`start_bar`, the de-facto
per-song ordering identity) carry position. `_collect_sections` builds
`SectionWindow(name, start_beat, end_beat)` in DB order.

**Fix (in the plan):** join by **section position** (start_beat / start_bar), or
equivalently by the **ordered index** of the section list (declared energy list
and `per_section` are both in section order from the same DB read) — NOT by
name. Update chunk 3 criterion 2, chunk 4 criterion 1, and DR-2's
`sections_ranked`/`EnergyInversion` to carry an unambiguous section identity
(start_beat or index) so two same-named sections stay distinct in the report and
in the surfaced inversion. Add a chunk-3 test with two same-named sections at
different energies + different measured loudness, asserting they're paired
correctly (this test FAILS under a name-keyed join — it's the lock).

---

## WARNING

### W1 — `update_section` mutator path drops energy (chunk 1 only covers `create_section`)

Chunk 1 threads energy through `create_section` and the existing-row update tuple
(correctly — I verified create_section.py:43-54 compares `(end_bar, color,
notes_md)`, so omitting energy there would make a changed-energy re-materialize
return `unchanged` and silently NOT persist; the design caught this). **But there
is a second mutator:** `update_section` (score.py:100) with an allowlist
`_SECTION_FIELDS = {"name", "start_bar", "end_bar", "color", "notes_md"}`
(score.py:97). It does not include `energy`, so a partial update of a section
can never change its energy — and a caller passing `energy=` would hit the
`unsupported fields` `ValueError`.

Chunk 1's "Done when" names only `create_section`. Either (a) add `energy` to
`_SECTION_FIELDS` and `update_section`'s handling, or (b) explicitly flag in the
plan that `update_section` does NOT support energy and why (e.g., energy is only
authored via materialize today) — per "never silently drop a requirement,"
silence here is the failure mode. Pick one and write it into chunk 1.

### W2 — `lufs_s_median` itself can be `nan`/missing for an out-of-capture or too-quiet section

`SectionMetrics` windows are "clamped to the captured extent; a section that
falls entirely outside the capture is recorded in `skipped_analyses`"
(report.py:404). A section that's in-capture but too quiet, or whose loudness is
`nan` from a degenerate window, would feed `nan` into the ρ input alongside the
energy ranks — and `spearmanr` propagates `nan`. The design's degrade-to-exclude
logic only covers NULL *declared* energy (the AUTHOR side), not NULL/`nan`
*measured* values (the MEASURE side). Chunk 3 should specify: a section whose
measured correlate is missing/`nan` is excluded from that correlate's ρ (and
named in `skipped`), exactly as a NULL-energy section is — symmetric handling on
both sides of the join. Tie this to the B1 fix (same `nan` discipline).

### W3 — Chunk 6 declares `Type: doc-only` but its "Done when" includes a backlog code/data edit and a `/critic ... cumulative` gate

Chunk 6 is `Type: doc-only` (correct for the SKILL.md / arrangement-model.md
prose edits), but criterion 5 ("Backlog: mark verifiable signal met; record
spectral correlate as a follow-on") edits `.prawduct/backlog.md`, and criterion 6
runs `final + cumulative`. The `Type note` says "`cumulative-final` if this ships
as one PR." Two cleanups: (1) `doc-only` + `cumulative-final` are different axes
(Type vs the cumulative marker) — the plan should declare `Type: cumulative-final`
explicitly on the last chunk if it's the single-PR bundle (per planning.md §"Choosing
a Chunk Type"), so the `/pr create` cumulative gate is actually triggered rather
than left conditional. (2) Confirm the backlog edit is in-scope for a `doc-only`
chunk (it is — backlog is prose/state, not executable code — but say so, since
`doc-only` "skips test-evidence checks"). Minor, but the Type/marker ambiguity
could let the cumulative gate slip.

---

## NOTES (builder's call — not blocking)

- **N1 — DR-5 by-ear flag is handled correctly.** The surfacing threshold is
  deferred-not-guessed, mirrors the existing `_MASKING_REPORTING_FLOOR` /
  `_TIMING_MIN_CONFIDENCE` calibrated constants, and is routed to
  `operator-verification.md` for the human-ear fine-tune since Live is unattended.
  This satisfies the run constraint. Note: B1 interacts — the "is this inversion
  notable" gate operates on per-pair *magnitude*, which is well-defined even when
  the aggregate ρ is `nan`, so the inversion list can still surface usefully on a
  tied-ρ render. Worth stating explicitly in chunk 5 so the e2e read doesn't go
  dark when ρ is undefined.

- **N2 — Verifiable signal is fully covered.** The item's signal ("a read-side
  check that takes arr.energy_curve + a MixReport and reports per-section
  declared-vs-measured intensity divergence ... wired into /mix-review") maps to:
  DR-1 (persist energy), chunk 3 (the lens: ρ + inversions), chunk 4 (handler
  lift), chunk 6 (mix-review wiring). No requirement silently dropped. The
  spectral correlate (DR-3) is a flagged deferral recorded in the plan and the
  proposed arrangement-model.md delta — legitimate per DISCOVERED-FROM-FRICTION,
  not a drop.

- **N3 — Ruler-not-stamp is genuinely enforced**, not just asserted: chunk 3
  criterion 3 is a lock test ("output contains ONLY measurements ... a test that
  would FAIL if a future edit made the lens emit a corrected curve"). The
  ordinal-not-linear (Spearman-not-Pearson) choice is grounded in research §3 and
  protects against the calibrated-scale STAMP. Good.

- **N4 — Chunk 1 is a genuine thin vertical slice** (Arrangement → DB column →
  handler read-back, end to end, no lens math), correctly `final`-mode as the
  architectural keystone, with the migration round-trip + consumer-grep boundary
  investigation. This is exactly right.

- **N5 — MIX-3S7P collision** is investigated and low-risk today (MIX-3S7P has no
  mix-review edit in flight); the additive-bullet-in-distinct-section mitigation
  + re-read-before-edit instruction (chunk 6 crit 1) is adequate. Carry the flag.

- **N6 — Calibration-first discipline** (chunk 2) for the onset-density correlate
  correctly honors the C7 learning: print real per-section densities before
  locking assertions, degrade to loudness-only ρ if the detector reads sun-zone
  poorly. Good — but ensure the degrade path interacts cleanly with B1 (a
  dropped density correlate is a missing key, not a `nan`).

---

## Requirements Confidence assessment

The plan's **Medium** is honest and correctly justified, but B1 and B2 mean the
"each statable in one sentence, methodology closed" claim is slightly
over-confident on the MEASURE-side mechanics: the ρ contract has an undefined
case the design treats as impossible, and the join key is wrong for the central
authorship shape. These don't drop it below Medium (both are local, cheaply
fixed in-plan, and the early `final`-mode chunks would likely catch them), but
the plan should add B1/B2 to the "two assumptions that keep it from High" list —
they are two MORE assumptions (ρ always finite; name is a unique join key) that
turned out false, so naming them keeps the confidence claim honest.
