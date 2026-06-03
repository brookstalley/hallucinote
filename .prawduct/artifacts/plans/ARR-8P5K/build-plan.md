# ARR-8P5K — Build Plan (coherence umbrella, doc-only)

**Requirements Confidence: High.**
- *Problem (one sentence):* As the energy/recurrence/melody MEASURE-half siblings land
  and ARR-4M3T raises literal meter changes, the dimension taxonomy in
  `arrangement-model.md` must stay coherent and stop conflating felt-pulse with literal
  meter.
- *Success (one sentence):* The taxonomy section classifies every sibling correctly, names
  the meter-feel sub-dimension split with a recorded promotion trigger, and a reader can
  tell "deferred candidate" from "excluded by design" — verified by reading the taxonomy
  against the sibling designs.
- *Out of scope (one sentence):* Any production code, any new axis, building the
  literal-meter `plan()` machinery (that is ARR-4M3T's own item), and editing the siblings'
  own model docs (`performance-model.md`, `melody-model.md`) — only `arrangement-model.md`
  is touched here.

*What would raise confidence further:* nothing material — the framing is settled (24/25
claims confirmed, see `research.md`) and the only open call (meter-feel split + non-promotion)
is decided in `design.md` §3 with alternatives. Confidence is High because the deliverable
is a bounded prose delta to one section of one doc, fully specified in `design.md` §5.

---

## Dependency note

The taxonomy-coherence delta should land **after the sibling DESIGNS are known** (so the
"both-sides shape predicted" sentences reference the siblings' actual final shapes, not
guesses), but it does **not** depend on the siblings being *built/merged* — it references
their designs and backlog signals, which exist now. ARR-4M3T's interim (early-slam) is
already shipped, so the meter-feel delta has no code dependency. This is a single chunk;
there is no architecture to prove end-to-end, so the "first chunk is a thin vertical
slice" rule degenerates to "the one chunk is the whole slice" (doc-only coherence pass).

---

## Chunk 1 (only chunk): Taxonomy-coherence delta to `arrangement-model.md`

- **Type:** doc-only
- **Critic mode:** (inference picks `final` — single-chunk plan; the taxonomy is an
  architectural keystone whose coherence matters, so `final` is also the right depth — no
  override needed)
- **Foreign API:** none
- **Done when:**
  1. **D1 applied** — the meter-feel candidate in the structure-intents bullet is split
     into the two named sub-dimensions (felt-pulse vs literal-meter) per `design.md` §5 D1,
     with the explicit non-promotion decision and the recorded promotion trigger (second
     odd-meter song OR user accepts the literal-3/4 blast radius over the shipped
     early-slam interim), and a cross-reference to ARR-4M3T as the forcing event.
  2. **D2 applied** — the taxonomy records that the structure-intent MEASURE halves are
     being realized by named siblings (energy → ARR-7M3D, recurrence → ARR-9K4T), matching
     the both-sides principle, with harmony (ARR-1H9C) + performance (perf lens) as
     precedents. LINK to the siblings, do not restate their specs.
  3. **D3 resolved (conditional, but never silently skipped)** — apply the
     line-level (MEL-1A7K) vs arrangement-level (ARR-9K4T) motivic-economy boundary as a
     one-sentence delta to the taxonomy **unless** both sibling docs already carry the
     boundary cleanly in `arrangement-model.md`'s own text (not merely in the backlog) — in
     which case record the explicit no-op decision ("D3 no-op: boundary already canonical at
     <anchor>") in the backlog update of Done-when #7. Either way the requirement is
     discharged on the record; the canonical doc — not the backlog — must own "which read
     owns motivic economy," so a backlog-only statement does NOT satisfy the no-op branch.
  4. **D4 considered** — confirm the "deliberately NOT modeled" list does NOT list meter
     changes (they're a deferred candidate, not an excluded-by-design item like
     processes/aleatoric); apply the optional clarifying edit only if a reader could
     confuse "deferred candidate" with "excluded." Record the decision either way.
  5. **Coherence verification (the verifiable signal)** — re-read the edited taxonomy
     against `design.md` §2's coherence assertions and the three sibling backlog entries
     (ARR-7M3D, ARR-9K4T, MEL-1A7K); confirm each still classifies correctly (no sibling's
     design contradicts a taxonomy assertion) and the meter-feel split is internally
     consistent with the **"swing vs meter (the boundary)" bullet** (≈ L132–134, but
     locate it by that heading text since D1 shifts line numbers within this same chunk)
     and the **"Discontinuity is first-class" bullet** in the derivative section
     (≈ L297–302, likewise locate by heading text). No contradictions remain.
  6. **No new axes** — confirm the edit invents zero new dimensions and adds zero
     speculative machinery (DISCOVERED-FROM-FRICTION); text/flow + unmetered-time-base stay
     candidates / boundaries, ARR-3R8F stays folded-later.
  7. **Backlog updated** — append an update line to backlog ARR-8P5K recording the
     meter-feel split decision + non-promotion + that the three MEASURE-half siblings own
     the (a)–(d) realizations; and add the taxonomy-decision cross-reference to ARR-4M3T's
     entry (satisfies its decision-record disjunct). No item is closed (umbrella stays
     open; siblings stay open).
  8. **/critic run and blocking findings resolved** (final mode; doc-only → test-evidence
     checks skipped, prose-coverage + coherence reviewed).
  9. **Committed** and chunk marked `[x]` in this plan's Status.

---

## Verification strategy

This is a doc-only coherence item; "exercising the product as its consumer would" means
**reading the taxonomy as the next author/agent would** and confirming it answers "which
relationship is this candidate?" without ambiguity, and that the meter-feel split removes
the conflation ARR-4M3T exposed.

- **Primary verification = the coherence read** (Done-when 5): the edited taxonomy is
  checked against `design.md` §2 assertions + the three sibling backlog entries. A
  contradiction found here means the *taxonomy* drifted and ARR-8P5K must be revisited —
  that is the umbrella's whole purpose.
- **Source-of-truth honesty for the early-slam fact (W2):** the non-promotion argument
  rests on "the length-preserving early-slam interim is shipped and solves the *felt* need
  with zero blast radius." That code (`_interrupt_tail` in `songs/sun-zone-done/build.py`)
  lives in the **private `hallucinote-songs` repo** — this repo's `songs/` is empty
  post-split, so the coherence guard CANNOT re-verify the song code from here. The reachable
  source of truth for this fact is the **ARR-4M3T backlog record (L120)**; the
  promotion-trigger prose (D1) and §3 must cite that backlog entry as the authority for the
  early-slam's existence, not imply the song was re-verified. If the early-slam status ever
  changes, it changes in the ARR-4M3T backlog record first, which is what the coherence read
  watches.
- **Drift-guard consideration (LINK-DON'T-SUMMARIZE / "lock the doc with a parity test"
  learning):** the deltas LINK to siblings rather than restating their specs, so there is
  no duplicated contract to lock with a parity test. The one durable value worth guarding
  — the meter-feel *promotion trigger* — lives only in prose; if a future build of the
  literal-meter axis (ARR-4M3T) lands, that build must update this trigger to "promoted."
  No automated test is warranted for a single prose decision (over-engineering for
  doc-only); the coherence read at sibling-landing time is the recurring guard, and
  ARR-8P5K stays open precisely so that guard keeps running.
- **No code, no render, no audio measurement, no human ear** required. There is nothing to
  run.

---

## PENDING by-ear calls (Live unattended)

**None.** ARR-8P5K is a coherence/documentation umbrella with no audio render or by-ear
decision. (By-ear calls live in the sibling build items — e.g. perf-authoring's
"which parts, what `k`" tune-by-ear, and any divergence-threshold tuning ARR-7M3D may
flag — and are owned by those plans, not this one.)

---

## Status

- [ ] Chunk 1 — Taxonomy-coherence delta to `arrangement-model.md` (D1–D4 + coherence
      verification + backlog updates)

**Context:** Design complete (`design.md`). The single chunk applies the four PROPOSED
deltas (D1 meter-feel split + non-promotion + trigger; D2 MEASURE-half sibling status;
D3 line-vs-arrangement motivic-economy boundary; D4 optional NOT-modeled clarification) to
`arrangement-model.md`'s taxonomy section, verifies coherence against the siblings, and
updates the backlog. No code owed. Next: execute Chunk 1 under Critic governance once the
sibling designs in this batch are stable enough to reference.

---

## Review resolution

Independent spec review verdict: **PASS** (no blocking findings). The three non-blocking
warnings have been addressed in the spec (fix-the-spec, never weaken the requirement):

- **W1 (line-number scoping):** Done-when #5 and design §3 now anchor the two coherence
  targets by **heading text** — the *"swing vs meter (the boundary)" bullet* and the
  *"Discontinuity is first-class" bullet* — with line numbers kept only as a `≈`
  convenience and an explicit note that D1 shifts them within the same chunk. Robust to the
  in-chunk line drift the reviewer flagged.
- **W2 (cross-repo code-fact honesty):** the non-promotion argument's reliance on the
  shipped early-slam (`_interrupt_tail`, which lives in the private `hallucinote-songs`
  repo) now explicitly cites the **ARR-4M3T backlog record (L120)** as the source of truth
  reachable from this framework repo, in design §3, in D1's proposed delta prose, and in a
  new Verification-strategy bullet. The promotion-trigger prose no longer implies the song
  code was re-verified from here.
- **W3 (D3 requirement vs escape-clause tension):** Done-when #3 and design §4 are
  reconciled into a single conditional-but-undroppable form: apply the one-sentence
  motivic-economy boundary delta by default, OR record an explicit **no-op decision** in
  the backlog if the boundary is already canonical in `arrangement-model.md`'s own text
  (a backlog-only statement does NOT satisfy the no-op branch, because the canonical doc
  owns "which read owns motivic economy"). There is no longer any path where a builder
  reads §4 and silently skips D3 while the plan reads as satisfied.

No new code, no new axes, no canonical-doc edits were made during this revision (those
remain deferred to Chunk 1 under Critic governance). The deliverable shape is unchanged;
only the spec's anchors and requirement framing were tightened.
