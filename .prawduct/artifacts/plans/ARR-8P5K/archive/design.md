---
lifecycle: completed
archived: 2026-09-08
unbuilt_at_archive: "no readable `## Status` roster — completeness cannot be read, and an unreadable plan is not evidence of completion"
maintained: false
---

> **Archived — no longer maintained.** This plan records what was built, not what will be. Do not edit it to reflect later changes; write those where they are true.

# ARR-8P5K — Design (coherence + decision umbrella)

**Item:** ARR-8P5K — Axis model: candidate neglected musical dimensions + possible
refactor of "axes". UMBRELLA (effort L, impact L, area arrangement).

**Type: doc-only.** No production code is owed under ARR-8P5K itself. The verifiable
signal — the canonical *"The dimension taxonomy"* section of
[`arrangement-model.md`](../../arrangement-model.md) (lines 40–208), with rationale +
citations — is **already MET** (24/25 claims confirmed; see
[`research.md`](research.md), do not restate). This design records the *consolidation
decision* that closes the umbrella's DESIGN obligation: which open follow-ups the
current sibling batch REALIZES, which stay FRICTION-DEFERRED, and the one live
coherence delta the taxonomy now owes (meter-feel under ARR-4M3T).

LINK-DON'T-SUMMARIZE governs this whole artifact: the durable content lives in
`arrangement-model.md` / `performance-model.md` / `melody-model.md` / `research.md`.
This file records *deltas and decisions*, not a re-statement of the models.

---

## 1. The both-sides shape for this item

ARR-8P5K is **not a dimension** — it is the *meta-rule that sorts dimensions* and the
both-sides discipline itself ("a dimension authored but unmeasured is half-built").
So it has no authoring-surface / measurement-lens of its own. Its "both sides" are:

- **AUTHORING surface of the umbrella** = the taxonomy section of `arrangement-model.md`
  (how a future author decides "is this candidate a structure intent / realization
  layer / subsystem / composite line?").
- **MEASUREMENT lens of the umbrella** = the *coherence test*: as each sibling lands,
  does the taxonomy still classify it correctly and stay internally consistent?
  That is the verifiable signal, and it is structural (doc ↔ siblings), not audio.

This is why the item is a *coherence umbrella*, not a build. There is no note floor to
degrade to; there is a doc to keep true.

---

## 2. Consolidation decision-record — who realizes which follow-up

The umbrella's open follow-ups are enumerated in backlog ARR-8P5K (a)–(d). The current
sibling batch maps onto them as follows. **This table is the umbrella's core decision.**

| Open follow-up (ARR-8P5K) | Taxonomy bucket | Realized by | Status |
|---|---|---|---|
| **(a)** performance READ-side lens | realization layer (performance) — MEASURE half | (shipped 2026-05-31, perf-lens 2a) | DONE — not in this batch |
| **(b)** performance AUTHORING profile | realization layer (performance) — AUTHOR half | (first primitive shipped 2026-05-31b, perf-authoring 2b) | PARTIAL — genre-baseline field, energy-coupling, declared-profile grading still open; **not in this batch** |
| **energy realization MEASURE** | structure intent (energy) — MEASURE half | **ARR-7M3D** (this batch) | being realized |
| **recurrence/form MEASURE** | structure intent (form/recurrence) — MEASURE half | **ARR-9K4T** (this batch) | being realized |
| **melody composite-line both-sides** | composite line (relationship 4) | **MEL-1A7K** (read-side shipped; declared-profile authoring + grading in flight) | being realized |
| **(c) meter-feel** | structure intent — *candidate* | **ARR-4M3T** (forcing event; build deferred) | FRICTION-PRESENT → see §3 |
| **(c) text / lyric / flow** | subsystem — *candidate* | none — no rap/chant song yet | FRICTION-DEFERRED |
| **(c) unmetered / free-time base** | scope boundary fork | none — `ARR-2B6K` boundary | FRICTION-DEFERRED |
| **(d)** fold/relate ARR-3R8F into performance | realization layer (performance) | gated on perf (a)/(b) fully landing | FRICTION-DEFERRED (2 song-local interplay sites recorded, awaiting 3rd-data-point generalization) |

**Decision: ARR-8P5K owes NO new code.** Every realization is owned by a named sibling
with its own verifiable signal. The umbrella's only DESIGN-phase deliverable is keeping
the taxonomy coherent as those land — concretely, the §3 meter-feel delta plus the
"both-sides shape predicted" sentences for the three MEASURE-half siblings.

### Why each sibling FITS the taxonomy (the coherence check, recorded)

These are the assertions the coherence lens must keep true. If a sibling's final design
contradicts one of these, the taxonomy — not the sibling — is what changed, and that is
the signal to revisit ARR-8P5K.

- **ARR-7M3D fits** as the MEASURE half of an existing structure intent (energy). It adds
  *no axis* — energy is already authored (`Arrangement.section(..., energy=)` →
  `energy_curve`); 7M3D only joins the authored curve to rendered intensity. This is
  exactly the both-sides gap the taxonomy predicts ("authored but unmeasured is
  half-built"), in the same shape harmony (ARR-1H9C lint) and performance (perf lens)
  already got. **No taxonomy change.**
- **ARR-9K4T fits** as the MEASURE half of the form/recurrence structure intent. Authoring
  (`motif()`/`vary()`/reference) shipped; 9K4T is the cross-instrument recurrence/recap
  READ. It is *distinct from* MEL-1A7K's line-level motivic-economy slice (9K4T is
  arrangement-level / cross-instrument; MEL-1A7K is the single-line read) — the taxonomy's
  "composite line vs structure intent" split is exactly what keeps these two from
  colliding. **No taxonomy change** (but see §4 — record the line-vs-arrangement
  motivic-economy boundary so the two reads don't both claim "motivic economy").
- **MEL-1A7K fits** as the composite-line relationship (relationship 4): pitch reads
  harmony, rhythm reads feel/performance, owns contour + motivic shape. The taxonomy +
  `melody-model.md` already say melody is NOT a peer axis. **No taxonomy change.**

---

## 3. The one live coherence delta — meter-feel under ARR-4M3T

This is the only DESIGN-phase pressure on the taxonomy, and it is a **decision**, not new
research (per `research.md` §"Open coherence question").

### The question

The 2026-05-30 taxonomy frames **meter-feel** as a single *candidate* structure intent
("the felt pulse — half/double-time, compound, clave; distinct from time-signature and
tempo"), and cleanly splits *swing ∈ performance microtiming* from *the metric grid ∈
meter-feel* (arrangement-model.md — the structure-intents bullet and the **"swing vs meter
(the boundary)" bullet**; ≈ L55–56 and L132–134, but located by heading text since these
shift once D1 is applied). **ARR-4M3T** (added 2026-06-02,
*after* the taxonomy) raises a sharper case the taxonomy did not yet face: a **literal
time-signature change** — an odd meter (5/4, 7/8) or a single borrowed 3/4 bar that
*shortens the song* — i.e. the grid itself changing shape mid-song, not the
felt-pulse-level the candidate describes.

### Decision (recorded here; the canonical edit lands later under Critic governance)

**These are TWO distinct sub-things, both currently bucketed under one "meter-feel"
candidate, and the taxonomy should name the split — but meter-feel stays a CANDIDATE
(not promoted to built) until a song forces the literal-meter half through `plan()`.**

Two sub-dimensions:

1. **Felt pulse level** — half-time/double-time at constant signature, compound (6/8)
   feel, clave, hemiola, metric modulation *of feel*. This is the candidate as originally
   framed. The half-time→double-time gear-shift is **already a first-class discontinuity**
   in `arrangement-model.md` (the **"Discontinuity is first-class" bullet** in the
   derivative section; ≈ L297–302, located by heading text) — so part of this
   sub-dimension is already honored as a discontinuity, not pending.
2. **Literal meter / time-signature** — the metric grid's shape per section/per bar
   (5/4, 7/8, one 3/4 bar). ARR-4M3T shows this is a `plan()` + beat-math +
   lens-meter-awareness change with a **blast radius across every absolute-beat
   consumer** (the monolithic Rhythm Gtr clip, the Amp-Type envelope, cue points,
   section bar ranges, and every read-side lens that takes a single uniform
   `beats_per_bar`). This is structurally the **same axis HOME as energy/harmony**
   (carried on the arrangement), with its own both-sides obligation (declare a section's
   meter + meter-aware reads).

**Promotion decision: NOT YET.** ARR-4M3T is *one* song's friction (sun-zone-done's
reggae→metal rude-interruption), and the **length-preserving "early slam"** interim
(`_interrupt_tail` on beat 4) is already shipped and sanctioned **per the ARR-4M3T backlog
record (L120)** — that backlog entry, not the song code, is the source of truth reachable
from this framework repo, since `_interrupt_tail` lives in `songs/sun-zone-done/build.py`
in the private `hallucinote-songs` repo (this repo's `songs/` is empty post-split, so the
coherence guard cannot re-verify the song). Per DISCOVERED-FROM-FRICTION, one song forcing
the *felt* effect (already solved zero-blast-radius) is **not** sufficient friction to
build the literal-meter machinery with its large blast radius. The taxonomy should:

- **Name the two sub-dimensions** (felt-pulse vs literal-meter) so the next author
  doesn't conflate them.
- **Keep meter-feel a CANDIDATE**, with the explicit promotion trigger recorded: *promote
  the literal-meter half to a built structure intent when a SECOND odd-meter song forces
  it, or when sun-zone-done's user decides the literal 3/4 steal is worth the blast radius
  over the early-slam interim* — whichever first. The felt-pulse half is partly honored
  today (discontinuity) and otherwise also candidate.
- **Cross-reference ARR-4M3T** as the forcing-event record and the early-slam as the
  sanctioned interim idiom.

This satisfies ARR-4M3T's own verifiable signal disjunct: *"a decision-record states
meter stays globally-4/4 with the early-slam as the sanctioned interruption idiom"* — the
umbrella records the *taxonomy-level* decision (meter-feel = two sub-dims, candidate,
promotion trigger named); ARR-4M3T, when it lands, records the *implementation-level*
decision (early-slam interim vs literal `plan()` rework). The two are not in conflict and
neither pre-builds the other.

### Alternatives considered (and rejected)

- **(A) Promote literal-meter to a built structure intent now.** Rejected: violates
  DISCOVERED-FROM-FRICTION (one song, already solved another way), and the blast radius
  (every absolute-beat consumer) is large for un-forced work. The early-slam proves the
  *felt* need is met without it.
- **(B) Collapse both sub-dims into one "meter" axis.** Rejected: they have different
  homes and different blast radii. Felt-pulse is largely a performance/feel + discontinuity
  concern (half/double-time already first-class); literal-meter is a grid-shape concern
  that rewrites beat math. Conflating them would invite authoring an inconsistent pair
  (declare 4/4 but feel half-time is *valid and common*; that's not a contradiction, it's
  two layers) — exactly the "inconsistent triple" anti-pattern the derivative section
  warns against. The split keeps ONE-SOURCE-OF-TRUTH: felt-pulse is feel; grid-shape is
  meter.
- **(C) Leave the taxonomy untouched (meter-feel = one undifferentiated candidate).**
  Rejected: ARR-4M3T is *real new friction* that exposed an ambiguity ("does meter-feel
  cover the grid changing shape, or only the felt level?"). Leaving it silent is the
  coherence drift the umbrella exists to prevent — the next author hits the same ambiguity
  cold. Naming the split costs two sentences and removes the trap.

---

## 4. Secondary coherence note — line-level vs arrangement-level motivic economy

MEL-1A7K's melody lens reads **line-level** motivic economy (within a single line);
ARR-9K4T reads **cross-instrument / arrangement-level** recurrence (which registered
motif recurs where, and as which variation). Both legitimately use the phrase "motivic
economy." To keep ONE-SOURCE-OF-TRUTH and prevent two reads silently claiming the same
verdict, the taxonomy delta should record the boundary in one sentence: *line-level
motivic economy (does this line reuse its own cells?) is the melody lens's; cross-part
recurrence/recapitulation (is the song built from a shared recurring cell-set across
instruments?) is the recurrence read's (ARR-9K4T).* This is already implied by
`melody/lens.py:48-50` deferring the n-gram read and by ARR-9K4T's own backlog framing;
the delta just makes the split explicit at the taxonomy so the two siblings don't drift
into overlap.

D3 is **conditional but never silently skippable** (resolving review W3). The canonical
doc — not the backlog — owns "which read owns motivic economy," so the default is to apply
the one-sentence delta. The only branch that skips the delta is: the boundary is *already
stated in `arrangement-model.md`'s own text* (a backlog-only statement does NOT count) — in
which case the builder records an explicit **no-op decision** ("D3 no-op: boundary already
canonical at <anchor>") in the backlog update rather than leaving D3 unaddressed. Either
the delta or the recorded no-op discharges the requirement; there is no path where a builder
reads §4 and quietly does nothing while Done-when #3 reads as satisfied. (Done-when #3 in
the build-plan encodes this conditional form.)

---

## 5. PROPOSED deltas to `arrangement-model.md` (quoted — NOT applied here)

Canonical edits land later under Critic governance. Proposed, scoped to the taxonomy
section and its meter-feel mentions:

**Delta D1 — split the meter-feel candidate into two named sub-dimensions.**
In the structure-intents bullet (line ~55), replace the parenthetical
*"Candidate: **meter-feel** (the felt pulse — half/double-time, compound, clave; distinct
from time-signature and tempo)"* with a two-sub-dimension form, approximately:

> Candidate: **meter-feel**, which on inspection (ARR-4M3T, 2026-06-02) is **two
> sub-dimensions**: (i) **felt pulse level** — half/double-time, compound, clave, hemiola;
> the felt subdivision, *distinct from* time-signature and tempo (the half→double-time
> gear-shift is already a first-class discontinuity, see below); and (ii) **literal
> meter / time-signature** — the metric grid's shape per section/bar (5/4, 7/8, a borrowed
> 3/4 bar that shortens the song). Both stay **candidates** (not built): promote (ii) to a
> built structure intent — carried on the arrangement beside energy/harmony, with `plan()`
> placing non-4/4 sections beat-accurately and the read-side lenses becoming
> meter-aware — when a **second** odd-meter song forces it, or when the user accepts the
> literal-3/4 steal's blast radius over the shipped **length-preserving early-slam**
> interim (recorded in the ARR-4M3T backlog entry, which is the source of truth for the
> early-slam's shipped status). swing stays ∈ performance; the metric grid ∈ meter-feel(ii).

**Delta D2 — record the three MEASURE-half siblings as the both-sides shape the taxonomy
predicted.** Add a short sentence (in the taxonomy section or a small "both-sides
status" addendum) noting that the structure-intent MEASURE halves are being realized by
named siblings — energy by ARR-7M3D, recurrence by ARR-9K4T — exactly as the
"authored-but-unmeasured is half-built" principle predicts, with harmony (ARR-1H9C) and
performance (perf lens) as the precedents. (LINK, don't restate the siblings' specs.)

**Delta D3 — record the line-vs-arrangement motivic-economy boundary** (one sentence,
near the melody subsection or the recurrence mention): line-level motivic economy is the
melody lens (MEL-1A7K); cross-instrument recurrence/recapitulation is the arrangement-level
read (ARR-9K4T).

**Delta D4 — (optional, low priority) update the "What is deliberately NOT modeled"
list** only if needed for coherence: meter changes are NOT in the "deliberately not
modeled" list (they are a deferred candidate, not an out-of-scope-by-design exclusion like
processes/aleatoric). No edit needed unless a reader could mistake "candidate, deferred"
for "excluded" — D1's explicit promotion trigger should prevent that. Recorded as
optional so the Critic pass can decide.

**No other deltas.** text/flow and unmetered-time-base stay as already-recorded candidates
/ scope boundaries; ARR-3R8F stays folded-into-performance-later. No new axes invented
(DISCOVERED-FROM-FRICTION).

---

## 6. Ruler-not-stamp boundary (made explicit)

The umbrella's job is *sorting* capabilities by ruler-vs-stamp, so the boundary is the
content. Explicitly, for the decisions in this design:

- **The taxonomy itself is a ruler** — it measures/classifies a candidate ("which
  relationship is this?"); it never makes the musical decision (what the meter *should*
  be, when to use 3/4, whether a chorus should lift). It scaffolds the author's reasoning.
- **The meter-feel decision is ruler-preserving.** When the literal-meter half is
  eventually built, the obligation recorded here is: an **authoring surface** (declare a
  section/bar's meter — the composer chooses 3/4, not a helper) + **meter-aware reads**
  (lenses report against the declared meter). A helper that *decided where to insert an
  odd bar* would be a stamp and is explicitly out — same posture as the harmony axis
  (author the progression; the lint only measures conformance).
- **The three MEASURE-half siblings are lenses, not stamps** — they REPORT
  declared-vs-realized divergence (energy intensity inversion, motif-recall presence) as
  info/coaching; none of them auto-corrects the song or makes a verdict the composer
  didn't ask for. This is the masking-analyzer / harmony-lint shape the taxonomy already
  mandates. (Their ruler-not-stamp boundaries are owned by their own designs; recorded
  here only as the coherence assertion the umbrella keeps true.)

---

## 7. Verification posture (Live is UP but UNATTENDED)

Nothing in this umbrella requires audio render or a human ear. The verifiable signal is
**structural**: the taxonomy section of `arrangement-model.md` stays coherent + accurate
as the siblings land (doc ↔ sibling consistency). Verification is reading the taxonomy
against the sibling designs and confirming the §2 coherence assertions hold + the §5
deltas are applied. **No by-ear / render-gated decision is pending for ARR-8P5K itself.**

By-ear calls DO exist in the sibling build items (e.g. perf-authoring's "which parts,
what `k`" tune-by-ear pass; ARR-7M3D's eventual divergence-threshold tuning if it grades
by-ear) — those belong to the siblings' build-plans, not this umbrella, and are already
flagged in ARR-8P5K's backlog updates. This umbrella flags **zero** pending by-ear calls.
