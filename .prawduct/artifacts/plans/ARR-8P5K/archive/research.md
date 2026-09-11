---
lifecycle: completed
archived: 2026-09-08
unbuilt_at_archive: "no readable `## Status` roster — completeness cannot be read, and an unreadable plan is not evidence of completion"
maintained: false
---

> **Archived — no longer maintained.** This plan records what was built, not what will be. Do not edit it to reflect later changes; write those where they are true.

# ARR-8P5K — Research stage

**Status: n/a — research + design are already complete; this is a coherence umbrella, not a build.**
`researchDone=false` (no new primary-source research was needed or done this run).

## Why n/a

ARR-8P5K's research and design are already landed and recorded. The deep-research
pass (20 sources, 25 claims, **24 confirmed** on primary sources — Cancino-Chacón/
Widmer 2018; KTH/Director Musices; the Performance Worm, Dixon/Goebl/Widmer 2002;
Hennig et al. 2011 on 1/f timing; Iyer 2002; Danielsen 2023; Palmer 1997) is done,
and the resulting framing is recorded as the canonical **"The dimension taxonomy"**
section of [`arrangement-model.md`](../../arrangement-model.md) (lines 40–208). Do not
re-research from this artifact — link to that section; it is the source of truth
(LINK-DON'T-SUMMARIZE).

The item's own backlog entry states this explicitly: *"the FRAMING is settled and
recorded… The verifiable signal is MET (the dimensions section exists, with rationale
+ citations)"* and the open follow-ups are flagged **"friction-driven, do NOT
pre-build; let genres force each gap."** So this is not a code-build item — it is a
**coherence + decision umbrella**: keep the taxonomy accurate and self-consistent as
the sibling items land, and make the "is X a new axis?" call when a genre forces one.

## What the taxonomy already decides (the durable spine — see arrangement-model.md for full text + citations)

A song's dimensions are **not a flat list of orthogonal axes**; they sort into four
relationships, and which kind a candidate is tells you how to model it:

1. **Authored structure intents** (the bones) — form/sections, energy, harmony;
   **meter-feel** is the named candidate.
2. **Realization layers** (how bones are rendered, DERIVED not authored) —
   **performance** is the first member. *This category is the answer to "no 1000
   axes": a realization layer reads the structure intents; it does not add one.*
3. **Subsystems** (own model) — sound-design/instrument-chains; **text/flow** candidate.
4. **A composite line that reads the other dimensions** — **melody** (pitch reads
   harmony, rhythm reads feel/performance, owns contour + motivic shape).

Underneath all four: the raw **note floor** `_note(pitch, start, dur, vel)`, which
every layer degrades to. Two documented SCOPE BOUNDARIES (limitations-not-flaws):
performance is **metered-only**; melody is **pitched-discrete-monophonic-line-only**.

This satisfies the house principles directly: ONE-SOURCE-OF-TRUTH (intensity authored
once as energy, performance renders it — not two contradictable dials), RULER-NOT-STAMP
(every candidate sorted by "removes bookkeeping vs makes the musical decision"; a
melody/counterpoint generator is a stamp and stays out), BOTH-SIDES (every dimension
needs an authoring surface AND a measurement lens), DISCOVERED-FROM-FRICTION (no
speculative axes).

## Coupling map of the sibling items (the umbrella's real job: keep these coherent)

Verified against `.prawduct/backlog.md` this run. The taxonomy is the integration point
for all of them:

| Sibling | What it is | Where the taxonomy puts it | Coherence note for DESIGN |
|---|---|---|---|
| **MEL-1A7K** / **ARR-3R8F** (melody) | melody = first-class dimension; rhythm/feel collision | **composite line** (relationship 4) + reads harmony & feel | Taxonomy + `melody-model.md` already say melody is NOT a peer axis. Read-side lens shipped; declared-profile authoring + grading is the open both-sides half. ARR-3R8F is the *rhythm* slice — backlog flags it folds into performance once perf (a)/(b) land (follow-up (d)). |
| **ARR-7M3D** | energy-realization unmeasured in audio | **structure intent (energy)** — its MEASURE half | Pure both-sides gap: energy authored + symbolic-read, but the *audio* realization check is missing. Taxonomy already mandates both-sides; this is the energy lens the principle predicts. |
| **ARR-9K4T** | recurrence/form has no read-side | **structure intent (form/recurrence)** — its MEASURE half | Same both-sides shape: authoring (Motif/vary/reference) shipped, the cross-instrument recurrence/recap *read* doesn't exist. Distinct from MEL-1A7K's line-level motivic-economy slice. |
| **ARR-4M3T** | meter changes (per-section/per-bar time signature, incl. one 3/4 bar) | **meter-feel candidate** — the friction that may force the candidate into a real structure intent | **The one live coherence pressure.** ARR-4M3T was added 2026-06-02, *after* the taxonomy section (2026-05-30). The taxonomy's "swing ∈ performance; the metric grid ∈ meter-feel" split (line 132–134) is the relevant decision; ARR-4M3T is the candidate-forcing genre/song event. See "Open coherence question" below. |

## Open coherence question for the DESIGN phase (NOT a research gap)

The taxonomy frames **meter-feel** as a *candidate* structure intent and cleanly
splits *swing (∈ performance microtiming)* from *the metric grid it deviates from
(∈ meter-feel)*. **ARR-4M3T** raises a sharper, newer question the 2026-05-30 taxonomy
did not yet face: a literal **time-signature change** / odd meter / single borrowed
3/4 bar — i.e. the grid itself changing shape mid-song, not the felt-pulse-level
(half/double-time) the taxonomy's meter-feel candidate describes. These may be two
distinct sub-things both currently bucketed under "meter-feel":

- **felt pulse level** (half-time/double-time at constant signature, compound feel,
  clave) — the candidate as originally framed; and
- **literal meter / time-signature changes** (5/4, 7/8, one 3/4 bar that *shortens
  the song*) — which ARR-4M3T shows is a `plan()` + beat-math + lens-meter-awareness
  change, with a blast radius across every absolute-beat consumer.

The DESIGN deliverable for the umbrella is to record (in `arrangement-model.md`, under
Critic governance, NOT here) whether these are one structure intent or two, and whether
ARR-4M3T is now sufficient friction to promote meter-feel from *candidate* to *built*
structure intent — **without pre-building** the parts no song yet forces. This is a
decision, not new web research. Per the directive, design is done at the taxonomy
level; this is the next decision the umbrella must keep coherent.

## Verification posture (per the unattended-Live constraint)

Nothing in this umbrella requires audio render or a human ear — it is a coherence/
documentation item. The verifiable signal is structural: *"The dimension taxonomy in
`arrangement-model.md` stays coherent + accurate as the sibling items land"* (the
original signal — taxonomy section with rationale + citations — is already MET). No
by-ear calls are pending for ARR-8P5K itself. (By-ear calls live in the sibling
build items, e.g. perf-authoring's "which parts, what `k`" tune-by-ear pass, already
flagged in ARR-8P5K's backlog updates — not this umbrella's concern.)

## Sources

No new web research this run. The grounding sources are the already-verified ones
cited inline in `arrangement-model.md`'s taxonomy section (Cancino-Chacón/Widmer 2018;
KTH/Director Musices; Performance Worm; Hennig et al. 2011; Iyer 2002; Danielsen 2023;
Palmer 1997) plus the melody pass in `melody-model.md` (Savage et al. 2015; Pearce/
IDyOM). Do not restate their claims here — read those artifacts.
