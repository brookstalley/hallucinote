# ARR-8P5K — Adversarial Spec Review (independent)

**Reviewer role:** independent adversarial spec-reviewer. I did NOT write this design.
**Verdict: PASS.** No blocking defects. Three warnings + several notes recorded below.
The design + build-plan are an honest, well-scoped coherence/decision umbrella that
covers the verifiable signal without inventing code, axes, or unrequested verdicts.

Artifacts reviewed:
- `.prawduct/artifacts/plans/ARR-8P5K/design.md`
- `.prawduct/artifacts/plans/ARR-8P5K/build-plan.md`
- `.prawduct/artifacts/plans/ARR-8P5K/research.md`

Checked against (source of truth):
- `.prawduct/artifacts/arrangement-model.md` (taxonomy section + meter mentions + "NOT modeled" list + discontinuity section)
- `.prawduct/backlog.md` (ARR-8P5K, ARR-7M3D, ARR-9K4T, MEL-1A7K, ARR-4M3T, ARR-3R8F, ARR-1H9C, ARR-2B6K)
- `src/hallucinote/performance/` and `src/hallucinote/melody/lens.py` (sibling-shipped claims)

---

## Verification of the design's load-bearing claims (independently confirmed)

| Design claim | Where I checked | Result |
|---|---|---|
| Taxonomy is the canonical source; signal already MET | arrangement-model.md §"The dimension taxonomy" (lines 40+) | CONFIRMED present with rationale + citations |
| meter-feel framed as a single *candidate* | arrangement-model.md lines 54–56 | CONFIRMED |
| swing ∈ performance / metric grid ∈ meter-feel split | arrangement-model.md lines 132–134 | CONFIRMED (cited line range exact) |
| half→double-time gear-shift already a first-class discontinuity | arrangement-model.md lines 297–302 | CONFIRMED (cited line range exact) |
| "deliberately NOT modeled" list does NOT contain meter changes | arrangement-model.md lines 327–342 | CONFIRMED — list is interlock/processes/texture-mass/aleatoric/sound-design/unmetered-*feel*; D4's premise holds |
| ARR-7M3D = energy MEASURE half | backlog L413–416 | CONFIRMED |
| ARR-9K4T = recurrence MEASURE half, distinct from MEL-1A7K | backlog L420–423 | CONFIRMED (backlog itself already draws the line-vs-arrangement distinction) |
| MEL-1A7K read-side shipped, authoring/grading open | backlog L55–81; `src/hallucinote/melody/lens.py` | CONFIRMED |
| ARR-4M3T forcing event + verifiable-signal disjunct | backlog L115–128 | CONFIRMED (the decision-record disjunct the design satisfies is quoted accurately) |
| early-slam (`_interrupt_tail`) shipped + sanctioned | backlog L120 | CONFIRMED *via backlog*; the code itself lives in the private songs repo (this repo's `songs/` is empty post-split) — see Warning W2 |
| perf 2a (lens) + 2b (realization) shipped | `src/hallucinote/performance/` (lens.py, correlation.py, dynamics.py, ensemble.py, realization.py) | CONFIRMED |
| taxonomy edits NOT yet applied; plan dir untracked | `git status` | CONFIRMED — this is a clean design-phase review, no code changed yet |

The design is unusually faithful to LINK-DON'T-SUMMARIZE and its citations check out. This
is the right posture for a coherence umbrella.

---

## Findings

### BLOCKING — none.

### Warnings

**W1 — Done-when #5 names line ranges (132–134, 297–302) as coherence anchors; line-number
scoping is brittle.** The build-plan's coherence-verification step pins the swing-vs-meter
line and the discontinuity section by *line number*. Those numbers are correct **today**
(I verified both), but the very act of applying D1 inserts text into the taxonomy section
and will shift every line below it — so by the time the builder runs Done-when #5, the
"132–134 / 297–302" anchors may already be stale within the same chunk. Per the planning
"line-number scoping" trap, scope these by their structural pattern instead: *the
"swing vs meter (the boundary)" bullet* and *the "Discontinuity is first-class" bullet in
the derivative section*. **Fix:** reword Done-when #5 (and design §3's parenthetical
citations) to name the bullets by heading/anchor text, keeping line numbers only as a
"≈" convenience. Non-blocking because the targets are unambiguous by content; the risk is
a future reader trusting a number that has drifted.

**W2 — the non-promotion argument rests on a fact about code that no longer lives in this
repo.** The entire DISCOVERED-FROM-FRICTION case for keeping meter-feel a *candidate*
depends on "the early-slam interim is already shipped and solves the *felt* need with zero
blast radius." That code (`_interrupt_tail` in `songs/sun-zone-done/build.py`) is in the
**private `hallucinote-songs` repo** — this repo's `songs/` is empty after the
framework⇄songs split (confirmed). The design's claim is grounded in the **backlog**
(ARR-4M3T L120 records the same fact), so it is not a hallucinated code claim — but the
umbrella's coherence guard ("re-read the edited taxonomy against the sibling designs")
cannot actually re-verify the early-slam still exists/works from this repo. **Fix:** add
one sentence to the build-plan acknowledging that the early-slam status is taken from the
ARR-4M3T backlog record (the source of truth reachable from here), not from the song code,
so the promotion-trigger prose explicitly cites the backlog rather than implying the
reviewer verified the song. This keeps the link honest about *which* artifact carries the
fact. Non-blocking because the backlog is a legitimate source of truth and the design does
not touch that code.

**W3 — D3's necessity is under-argued against the gold-plating risk, and the build-plan's
own escape clause weakens the requirement.** The line-vs-arrangement motivic-economy
boundary D3 wants to add to the taxonomy is **already stated explicitly in ARR-9K4T's
backlog entry** (L423: "MEL-1A7K owns the melodic-LINE motivic-economy slice; this is the
*cross-instrument / arrangement-level* recurrence-realization sibling"). The design (§4)
correctly flags this and says the delta "just makes the split explicit at the taxonomy."
That is a *defensible* reason (the canonical doc, not the backlog, is the source of truth
for "which read owns motivic economy"), so D3 is not gold-plating — **but** build-plan
Done-when #3 states D3 as a hard "applied," while design §4 calls it "a *note*, not a
blocking decision … if the two siblings keep the boundary clean in their own docs, a single
cross-reference suffices." Those two are in mild tension: the plan promotes a "note" to a
checkbox. **Fix:** reconcile — either (a) commit to D3 as required and drop §4's
"single cross-reference suffices" softening, or (b) keep D3 conditional in Done-when #3
("apply D3 *unless* the sibling docs already carry the boundary, in which case record the
no-op decision"). Right now a builder could read §4 and skip D3 while the plan says it's
done — a small silent-requirement-drop risk. Non-blocking because either resolution is one
sentence and the requirement is recorded, not dropped.

### Notes (builder's discretion)

**N1 — "three kinds" vs "four relationships" framing is coherent today; confirm the deltas
don't disturb it.** The canonical taxonomy is "three kinds" (arrangement-model.md L50) +
"A fourth relationship exists: a composite line" (L70). The design's §1/§2 and research.md
use "four relationships." This is *not* a contradiction — the doc itself says
three-kinds-plus-a-fourth-relationship, and §2's "composite line (relationship 4)" matches
the doc's own "fourth relationship." None of D1–D4 touches this framing. Just have
Done-when #5's coherence read confirm the inserted meter-feel split stays inside
"structure intents" (kind 1) and does not muddy the three/four distinction.

**N2 — `melody/lens.py:48-50` citation is approximately right, not exact.** The n-gram /
motivic-economy deferral text actually sits at ~L49–51 of the module docstring (I read it).
The structural claim ("the n-gram read is deferred there") is accurate; the precise line
numbers are a convenience. Same `≈` treatment as W1 — fine for prose rationale, just don't
let it harden into a contract.

**N3 — Requirements Confidence: High is honest.** The deliverable is a bounded prose delta
to one section of one doc, the framing is settled (24/25 claims, research.md), and the one
open call (meter-feel split + non-promotion) is decided in §3 with three rejected
alternatives. I independently confirmed every premise the High rests on. No overstatement.

**N4 — Critic-mode inference (`final`, single-chunk, doc-only) is the right call** and the
plan correctly declines to override. Type: doc-only is accurate (zero executable code; the
backlog append is data, not code). No `verify-api` needed (Foreign API: none — correct,
nothing here wraps Live or any SDK).

---

## Perspective sweep (Prawduct review lenses)

- **Product:** The verifiable signal ("taxonomy stays coherent + accurate as siblings land")
  is fully covered by Done-when #1–#7. The original signal (taxonomy section exists with
  rationale + citations) is independently confirmed MET. No requirement dropped.
- **Design:** §2's decision table is the right artifact for an umbrella — it maps every
  open follow-up (a)–(d) to a named owner with its own signal, and explicitly states the
  umbrella owes NO code. ONE-SOURCE-OF-TRUTH respected (felt-pulse = feel; grid-shape =
  meter; intensity authored once as energy).
- **Architecture:** No architecture to prove; the design correctly notes the "thin vertical
  slice" rule degenerates to "the one chunk is the whole slice" for a single doc-only pass.
- **Skeptic:** I tried to find a hallucinated cross-reference, a stale line number that's a
  real defect, or a dropped follow-up. The line numbers are correct *today* (W1 is about
  future drift, not a present error); the code claims are backlog-grounded (W2); every
  follow-up (a)–(d) is accounted for. The meter-feel non-promotion is genuinely
  DISCOVERED-FROM-FRICTION-compliant: one song, already solved another way → not enough
  friction to build the literal-meter machinery. I agree with the rejection of alternatives
  (A)/(B)/(C).
- **Testing / verification:** Correctly identified as structural (doc ↔ sibling), no render,
  no by-ear. The build-plan honestly declares **zero** pending by-ear calls and correctly
  pushes the sibling by-ear calls (perf "which parts, what k"; ARR-7M3D threshold tuning)
  onto the siblings' own plans. The "no parity test for a single prose decision" reasoning
  is sound (the LINK-don't-summarize learning means there's no duplicated contract to lock;
  the recurring coherence read at sibling-landing is the guard, and ARR-8P5K staying open
  is what keeps it running).

## House hard-rule checks

- **RULER-NOT-STAMP:** PASS. §6 makes the boundary explicit and correct — the taxonomy is a
  ruler (classifies, never decides the music); the eventual literal-meter build is
  ruler-preserving (author declares the meter, lens measures; a helper that *decided where
  to insert an odd bar* is named as out-of-scope stamp). The three MEASURE-half siblings are
  lenses that REPORT, not stamps. No helper makes a musical decision; no lens emits an
  unrequested verdict.
- **BOTH-SIDES:** PASS, and handled with nuance — §1 correctly argues ARR-8P5K is the
  *meta-rule that sorts dimensions*, not a dimension, so it has no authoring/measurement
  surface of its own; its "both sides" are the taxonomy-as-authoring-aid + the coherence
  test. The siblings carry the real both-sides obligations, tracked in §2.
- **DISCOVERED-FROM-FRICTION:** PASS. No new axes; meter-feel stays candidate; text/flow +
  unmetered-time-base stay candidates/boundaries; ARR-3R8F stays folded-later. Promotion
  trigger explicitly named ("second odd-meter song OR user accepts blast radius").
- **ONE-SOURCE-OF-TRUTH / LINK-DON'T-SUMMARIZE:** PASS — the design records deltas, links to
  the models, and restates only the decision it owns.
- **Never silently drop a requirement:** PASS, with the W3 caveat that D3's conditional
  framing should be reconciled so it can't be silently skipped.

## Acceptance-criteria observability

Done-when items are observable: each delta is "section X now contains Y" (D1–D4), and the
coherence check (#5) is "re-read against §2 assertions + three named backlog entries; no
contradiction remains." These are checkable by a reader, not "it works." #5 is the closest
to subjective, but it's anchored to specific assertions and specific sibling entries, which
makes it auditable. Acceptable.
