# ARR-9K4T — Independent Adversarial Spec Review

**Reviewer role:** independent adversarial spec-reviewer (did NOT author the design).
**Verdict: REVISE.** One BLOCKING defect (the breathed-outro tolerance gap silently
risks failing a third of the verifiable signal), plus several should-fix warnings.
The design is otherwise strong: structural claims about the codebase were
independently verified and almost all hold; the ruler-not-stamp discipline,
both-sides framing, DR records, and the thin-vertical-slice first chunk are sound.

---

## What I verified against the real code (the design's load-bearing claims)

All of these checked out, which is why the verdict is REVISE-not-reject:

- **No `reference()` link exists** — `grep "def reference" arrangement.py` → none;
  `self.motifs` dict at `arrangement.py:120`; `motif()` at `:126`. The
  "documented-but-unbuilt" structural finding (design §1, research §1) is TRUE.
- **The six+ variation ops exist** with exactly the semantics the matcher math
  assumes: `augment` scales onset AND duration uniformly (`variations.py:195`),
  `diminish = augment(1/f)` (`:212`), `invert` = `2*axis - p` (`:153`),
  `retrograde` time-reverses (`:171`), `fragment` rebases to 0 (`:223`). The
  design §4 signature-recovery formulas are arithmetically correct.
- **The melody-lens contract the design mirrors** is real: frozen dataclasses,
  `Severity` Literal, `_ONSET_EPS = 1e-6`, `TYPE_CHECKING` import of `Arrangement`
  (`melody/lens.py:58`), `section_melody_inputs` adapter on the arrangement
  (`arrangement.py:319`), info-only. The proposed module/surface layout (§3) is a
  faithful mirror.
- **`resolve_song_dir` + the `*_report()` CLI pattern** exist exactly as described
  (`tools/melody_lens.py:31,40`; `melody_report()` at sun-zone-done `build.py:1843`).
- **The fixtures exist**: `poly = arr.motif("polyrhythm-cloud", _polyrhythm_cell())`
  and `no_time = arr.motif("no-time-stab", _no_time_motif())` at `build.py:1241-1242`;
  the climax tiles `poly.notes` via `_polyrhythm_callback`/`V.shift` (`:769,890,1017`);
  the trade-cell does `V.diminish(V.fragment(no_time_notes,0,4),2.0)` (`:1002`); the
  outro does `V.augment(no_time_motif,2.0)` inside `_outro_lead` (`:1041,1063,1315`).

---

## BLOCKING

### B1 — The outro augment recall is BREATHED; the tolerance plan calibrates only the machine-tight polyrhythm, silently risking a no-match on 1/3 of the verifiable signal

**The defect.** The design's whole match-tolerance argument (§4 step 4; build-plan
Chunk 1 step 4; the single PENDING by-ear call) rests on this premise:

> "the lens matches the **pre-breath authored notes** (the in-memory `Arrangement`
> carries the authored cycle, before any `performance.apply_profile` pass), so the
> tolerance is tight … expected ~`_ONSET_EPS`, exact-beat authored."

**This premise is false for the outro.** Verified in `build.py`:
`_build_arrangement()` calls `_breathe(...)` on intro, verse1, verse2, development,
break, AND **outro** (`build.py:1254-1320`), and the breathed result is what is
passed into `arr.section(...)`. The outro breath plan **explicitly breathes the
lead** that carries the augment recall: `plan={..., "05 Lead": BREATH}`
(`build.py:1320`), and `_outro_lead` is where `_augmented_no_time(no_time_motif,
32.0)` lives (`build.py:1063`). `_breathe` applies `apply_profile(notes, profile,
seed=...)` (`build.py:1214`) — the correlated ≈1/f onset-deviation authoring pass
(`performance/correlation.py`). So the augment recall reaches the arrangement with
onsets perturbed **off exact beats by a non-`_ONSET_EPS` amount**.

There is **no separate post-arrangement `apply_profile` pass the lens can read
around** — the breath is baked into `build.py` *before* the notes enter the
arrangement. `recurrence_report()` (build-plan Chunk 4 step 3) builds the *real*
arrangement, so the section layers it hands the lens are the breathed ones.

**Why it's blocking, not a warning.** The augment-in-the-outro is one of the THREE
named verifiable-signal cases (design §0 "no-time-stab recurs … in the outro
(augmented)"; build-plan Chunk 1 step-implicit and Chunk 4 step 5 assert `augment
×2`). With a tolerance pinned to ~`_ONSET_EPS` from the machine-tight polyrhythm
(integration is the *one* section NOT breathed — `build.py:1300` "Stays
machine-tight"), the breathed augment reads `variation="derived"` or no-recall.
That is a **silent partial failure of the verifiable signal** — exactly the
"dropped requirement nobody notices" the house rules forbid. The build-plan's
calibration step measures only the polyrhythm residual, so it would *lock a
tolerance that cannot see the outro recall* and never surface the gap.

**The fix (the design must choose and record one, under Critic governance):**
- **(a) Calibrate the tolerance against the BREATHED outro augment, not just the
  machine-tight polyrhythm.** Chunk 1's calibration print MUST run all three real
  recalls (polyrhythm climax, no-time trade-cell, **outro augment**) and report the
  worst-case onset/duration residual; the tolerance is set from the *breathed*
  case. This makes the PENDING call honest (it is no longer "effectively exact" —
  the breath jitter is the real dial), and it correctly stays render-free
  (symbolic measurement of the breathed notes). This is the likely-correct fix and
  it *strengthens* the calibration-first discipline the plan already invokes.
- **(b) Match against pre-breath notes** by having `recurrence_report()` build a
  non-breathed arrangement (or expose the pre-`_breathe` layers). This contradicts
  "build the real arrangement" and would make the lens read something the song
  doesn't actually ship, so (a) is preferred. If (b) is chosen, the design must say
  so explicitly and reconcile it with the `melody_report()` mirror (melody reads
  the breathed arrangement).

Either way: the design's §4.4 sentence and the build-plan PENDING entry must stop
asserting "exact-beat authored / ~`_ONSET_EPS`" as if all three fixtures were
machine-tight. They are not. A loose-but-bounded tolerance for breathed recalls is
a *real* by-ear-adjacent dial — calibrate it from the measured breathed residual,
do not guess and do not assume it away.

---

## WARNINGS (should-fix)

### W1 — §7 collision analysis is factually STALE and understates a live three-way edit conflict on `skills/compose-review/SKILL.md`

The design §7 makes two assertions that are now false:

1. **"MEL-1A7K has no plan files yet (empty dir)."** FALSE — `.prawduct/artifacts/
   plans/MEL-1A7K/` now contains design.md, build-plan.md, and research.md (dated
   the same day). MEL-1A7K's own build-plan (lines 40-41, 201, 246-248, 260)
   **explicitly names a three-way COLLISION** on `skills/compose-review/SKILL.md`
   between MEL-1A7K, ARR-9K4T, and ARR-7M3D, and treats it as coordinate-NOW work.
2. **"ARR-7M3D does NOT collide with this item's `/compose-review` edit."** FALSE —
   ARR-7M3D/research.md lists `skills/compose-review/SKILL.md` (symbolic energy
   read) in its files (line 248) and references `/compose-review` SKILL.md:84 (line
   28). ARR-7M3D *does* touch the compose-review surface; MEL-1A7K names it as a
   collision partner there.

**Note the good part:** the substantive *boundary* (MEL = within-line n-gram;
ARR-9K4T = cross-instrument registered-motif recurrence) is drawn consistently in
BOTH plans and is correct — there is no claim-overlap, only an edit-surface
conflict. So this is a coordination/logistics staleness, not a scope collision. But
per the "Pattern sweeps are tree-wide" and "permission to collaborate restates
precedence" learnings, the design must (a) correct the stale facts, and (b) commit
to the concrete coordination: all three items edit the same READ §2 block, so this
item's "Recurrence / recapitulation" block must be authored to slot beside MEL's
"within-line repetition" block and ARR-7M3D's "energy realization" block without
contradiction or double-reporting — and Chunk 4's tree-wide-grep doc-parity guard
should explicitly check for the sibling blocks, not just `recurrence_lens`
self-consistency.

### W2 — The recurrence lens must scan ALL layers; "mirror `melody_report()`" is a trap that would MISS the polyrhythm-on-Organ recall

The polyrhythm recall lands on `"04 Organ"` (`build.py:1017` →
`_integration_climax_organ`), while the no-time recalls land on `"05 Lead"`. But
`melody_report()` passes `melody_layers=MELODY_LAYERS` where `MELODY_LAYERS =
("05 Lead",)` (`build.py:69`). Build-plan Chunk 4 step 3 instructs the builder to
wire `recurrence_report()` "mirroring `melody_report()`." A naive mirror would
restrict to the Lead and **silently drop the polyrhythm recall entirely** —
defeating the primary verifiable-signal case (the polyrhythm tiled quote is the
*thin slice* of Chunk 1).

The design body (§4) does say "per (motif × section × **layer**)" and the lens
signature has no layer filter, so the *intent* is right. But the build-plan's
"mirror `melody_report()`" instruction is in direct tension with it. **Fix:** make
the build-plan explicit that `recurrence_report()` does NOT take a `melody_layers`
filter — it scans every layer in every section (drums included; a drum motif could
recur), unlike melody which excludes chordal/drum layers. Add a Chunk-4 assertion
that the polyrhythm recall is found on `"04 Organ"` specifically, so a
Lead-only regression fails loud.

### W3 — The climax-organ layer is a SUPERSET (recap + fusion-chord hits); the matcher's window-slide must tolerate extra interleaved notes or the QUOTE reads `derived`

`_integration_climax_organ` returns `tiled-polyrhythm-recap + fusion-chord hits`
in the SAME `"04 Organ"` layer (`build.py:890-902`): the fusion strikes land at
`peak = start_beat + (bars-8)*BPB` onward, overlapping the LAST 8 bars of the
tiling grid. So the late tiling windows contain BOTH motif notes AND non-motif
fusion notes — a superset of M, not an equal-to-M window.

The design §4 step 2 says "relative-onset pattern identical." If the matcher
requires window == M (equality), the overlapped windows fail and the verifiable
signal "recurs … as a tiled QUOTE" degrades to `derived` for those cells — which
arguably does NOT satisfy the stated "QUOTE" signal. The design's `derived`/coverage
path makes this *honest* (not a false negative), and Chunk 1's calibration print is
designed to expose exactly this. But the design never states the matcher must do
**subset/containment** matching (M's notes ⊆ window under the transform), not
equality. **Fix:** §4 must specify subset-containment semantics (the motif is
*present in* the cell, extra notes allowed) and the build-plan must assert the
clean early-cell quotes read `exact` while documenting the overlapped late cells'
expected reading (clarify whether they should read `exact` via containment or
`derived` — a real spec decision, currently silent).

### W4 — "integration climax" is not an addressable arrangement section; the signal wording over-promises locational precision

The success criteria (design §0; build-plan) say recalls are reported "in the
integration **climax**." Verified: there is no `climax` arrangement section — the
climax is the last cells *within* the single 32-bar `integration` section
(`INTEG_CELLS`; `arr.section(...)` gets one `integration` section). The lens's
`SectionRecurrenceInput` is keyed by arrangement section, so the best the lens can
report is "integration / 04 Organ / beat-offset ≈256." That IS the observable
equivalent, but the spec wording ("climax") implies a granularity the section model
doesn't carry. **Fix:** restate the acceptance criterion as observable —
"`polyrhythm-cloud` recurs in the **integration** section on **04 Organ** at beat
offset ≈ N (the climax cells)" — so the test asserts what the lens can actually
emit, not a sub-section label it cannot.

---

## NOTES (builder's discretion)

- **N1 — `derived` is doing a lot of work; keep it from becoming an escape hatch.**
  The honest-non-match `derived` path is the right design, but with B1/W3 unfixed
  it could absorb two of the three signal cases and the plan would still "pass"
  (the lens reported *something*). Recommend the Chunk-4 song-test assert the
  SPECIFIC variation (`exact`/`augment ×2`/`diminish∘fragment`) for each named
  recall, NOT merely "a recall was found" — otherwise the verifiable signal is
  satisfiable by `derived`-everywhere, which is verification theater.

- **N2 — `retrograde` span recovery.** `retrograde`'s onset map uses the motif's
  latest release as the default span (`variations.py:182`). The relative-frame
  normalization (subtract first onset) handles placement, but recovering a
  retrograde requires knowing M's span; confirm the matcher derives span from M
  (which it owns) rather than from the realized cell. Minor; no fixture uses
  retrograde, so it's untested-by-corpus — fine to ship single-op retrograde with a
  synthetic-only test.

- **N3 — hybrid-hook blind spot is correctly scoped and honestly flagged** (§4):
  `_hybrid_hook` recurs but is never `arr.motif(...)`, so a registry-keyed lens
  can't see it. The design states this plainly and the docstring/SKILL must too —
  good ruler-not-stamp discipline (read *declared* recurrence, don't invent).

- **N4 — DR-1 Option A (detect-only) as MVP is well-justified.** Shipping the read
  on existing fixtures with no re-authoring, deferring the `reference()` author
  link as a tracked (not dropped) both-sides obligation, mirrors how
  melody/performance deferred their declared-profile grading. Chunk 5 is correctly
  marked DEFERRED-on-friction, not silently omitted. Good.

- **N5 — Requirements Confidence is currently "High" but B1 is a genuine unknown.**
  Given B1 (the breathed-tolerance gap is a real, unmeasured dial that the plan
  assumed away), the honest confidence is **Medium** until Chunk 1's calibration
  measures the breathed residual. The plan should say so — "High" overstates given
  the false exact-beat premise. This is exactly the symptom the Confidence field
  exists to catch (planning.md §Requirements Confidence).

---

## Cross-check summary (the briefing's specific asks)

- **Acceptance criteria observable?** Mostly — but W4 (the "climax" label) and N1
  (assert specific variation, not "found something") need tightening to be truly
  observable-behavior rather than "it works."
- **Verifiable signal fully covered, nothing dropped?** NO — B1 puts the
  outro-augment case at silent-failure risk; W2 puts the polyrhythm case at
  silent-drop risk via the `melody_report()` mirror. Both must be fixed for the
  signal to be honestly covered.
- **Ruler-not-stamp?** SATISFIED — the lens measures registered-motif recall +
  reports economy as a fact; no invented recurrence, no "be more economical"
  verdict, info-only, questions-not-verdicts (§1, §5, DR-3). Clean.
- **BOTH-SIDES?** SATISFIED for the read (this item); the author-LINK half is
  correctly tracked as deferred (DR-1 Option B / Chunk 5), not pretended-complete.
- **First chunk a genuine thin vertical slice?** YES — Chunk 1 drives matcher →
  lens → report on one real recall (the polyrhythm quote) before widening. Good
  architecture validation, with a calibration gate.
- **Foreign-API grounding?** N/A and correctly declared — pure-stdlib symbolic
  lens, no Ableton/MCP/SDK surface, render-free. No `verify-api` needed.
- **By-ear/render-gated decisions flagged?** PARTIALLY — the design flags the
  tolerance as the one PENDING dial, which is right, but B1 shows the plan
  *mis-characterized* it as "effectively exact" and scoped the calibration to the
  wrong (machine-tight) fixture. Fix B1 and the PENDING flag becomes honest.
- **Requirements Confidence honest?** NO — see N5; should be Medium until Chunk 1
  measures the breathed residual.
