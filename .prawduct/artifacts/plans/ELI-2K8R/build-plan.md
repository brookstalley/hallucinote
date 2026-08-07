---
artifact: build-plan
version: 1
scope: eli-2k8r
depends_on:
  - artifact: elicitation-and-stage-exit-criteria
  - artifact: intent-collaboration-model
  - artifact: generator-altitude-policy
governed_by:
  - artifact: elicitation-and-stage-exit-criteria
    dispositions:
      - "constraint 2 (`one consolidated turn`) is AMENDED, not dropped — replaced by a shape invariant (every turn carries new work; <=2 questions). The failure it bounded (sequential blank-question Q&A) is still forbidden by the `ask` register's definition"
      - "constraint 1 (`propose, don't interrogate`) is NARROWED to craft. For identity dimensions a recommendation is now a defect, not the requirement"
      - "constraint 4 (`load-bearing AND unstated only`) is RETAINED and given the owner test that makes it operable"
      - "the three-state ledger + DESCRIBED-BUT-UNBUILT are RETAINED unchanged; only their *reason* is re-centred on the composer rather than on machine accountability"
  - artifact: generator-altitude-policy
    dispositions:
      - "ruler-vs-stamp is EXTENDED from the generator layer to the agent's own conduct; no generator rule changes"
  - artifact: intent-collaboration-model
    dispositions:
      - "the three registers are UNCHANGED. /song-brief Ask/Show/Note is a DIFFERENT trichotomy (what the stage does) from directed/volunteered/directed-but-under-articulated (where a request came from); the skill now states the mapping instead of claiming identity between them"
      - "the third register trigger is unchanged (an ask the composer cannot yet specify). Explicit delegation (you pick) is recorded as earning the same move for the same reason — an addition to the register reach, not a narrowing"
      - "propose-and-react is NARROWED for identity: a recommendation now closes a fork the composer should own. The discipline still governs craft and every handed-back choice"
last_validated: 2026-08-07
---

## Requirements Confidence

**Level:** High

**Why:** The requirement is an owner ruling given verbatim in session:
*"hallucinote is a tool to help music composition, performance, production,
arrangement. It is NOT an AI music generator"*, plus *"the last thing a creative
person wants is to have all the choices taken away."* Both are already ratified
one level down — `docs/VISION.md` ("the target is not 'AI fills in a chord
progression'"; "the depth of collaboration scales with the user") and
`docs/song-authoring-conventions.md` § *Generator altitude — ruler vs stamp*. The
work is propagating an existing principle to a surface that never inherited it,
not inventing one.

The defect is **reproduced, not hypothesised**: a live stage-0 run in this
session produced a ~900-word single turn carrying 8 fully-argued proposals, and
silently omitted *vocals* — must-have #4 in `docs/song-new-checklist.md`. Root
cause is structural and verified by reading the artifacts: the 7-row sweep table
in `skills/song-brief/SKILL.md` contains **none** of the checklist's five
must-haves. It is composed entirely of should-haves (#6 tempo, #7 meter, #8
harmony, #9 production) and gap-closers (#15, #16, #17) — the design artifact
says why in as many words: *"Drawn from what actually bit v1."* A regression list
was serving as an elicitation agenda.

**Open assumptions / unknowns:**

- [ASSUMPTION: the runtime agent has only the skill, not this design conversation
  | HIGH impact | stated by the owner] Every change is therefore judged on
  whether it changes what a *cold* agent finds easy. Exhortation ("be concise")
  is assumed to fail; the table it walks, and a worked example it can
  pattern-match, are assumed to work. This is why Chunk 2 exists as its own
  deliverable rather than as prose inside Chunk 1.
- [ASSUMPTION: identity dimensions number ~5 and are stable across genres |
  MEDIUM impact | inferred] Derived from the checklist's five must-haves plus
  what the owner's own sample questions reached for. If a later song finds a
  sixth, it is added — the list is a floor, not a schema.
- The review checkpoints (`/compose-review`, `/mix-review`) surface "a producer's
  question, never a verdict" and carry the same wall risk. **Deliberately out of
  scope** — filed, not silently dropped.

## Problem

1. **What problem are we solving?** Following `/song-brief` as written produces
   one wall of fully-argued proposals that pre-decides the composer's identity
   choices and omits must-have dimensions.
2. **What does success look like?** A cold agent with only the skill, given the
   session's original prompt, opens with <=2 *open* identity questions, a short
   read of what it hears, and a flag — and never pre-decides key, vocals or
   production stance.
3. **What's out of scope?** The song itself; downstream stages (3-7) keep
   driving stop-less; the two review checkpoints.

## Chunks

### Chunk 01: The owner test replaces the defect list

 Rebuild
  `skills/song-brief/SKILL.md`'s sweep around *whose choice is it* (identity =
  composer, craft = agent), seeded from the checklist's must-haves so vocals
  cannot fall out again. Add the third register (`note`) and the missing
  anti-pattern (the over-argued proposal). Replace "one consolidated turn" with
  the shape invariant.
  *Done when:* the skill's table contains all five must-haves; craft dimensions
  are named as never-asked; both anti-patterns are stated with examples.

### Chunk 02: The worked example

 A good stage-0 turn and the bad one, side by
  side, in the skill. This is the anti-wall mechanism for a cold agent, which
  pattern-matches examples more reliably than it follows rules.
  *Done when:* both turns are in the skill, the bad one is labelled with which
  rule each part violates.

### Chunk 03: Propagate the norm

CLAUDE.md (the stop-list bullet, the pedagogical carve-out, and re-scoping
"creative product prompts" to *finish the craft, never author the identity*),
`docs/song-workflow.md` (stage 0 prose, the stance block, stage 1, and the
canonical exit-criteria row), `skills/song-workflow`, `skills/song-new`,
`docs/skills.md`, `docs/song-new-checklist.md`, `docs/song-authoring-conventions.md`
(extend ruler-vs-stamp to the agent), `.prawduct/project-state.yaml`
(`interaction_patterns` — the binding classification register), and an amendment
record on the adopted artifact.

*Done when:* **no surface still instructs the superseded behaviour, in any
wording.** Deliberately not phrase-scoped — an earlier draft of this criterion
said *no surface says "one consolidated turn"*, which greps clean while the
substance survives as "propose and read their reaction" three files away. The
check is behavioural: for each surface, does an agent reading **only** that
surface ask identity openly and decide craft silently? Passages that are
deliberately preserved (the change log; the artifact's ratified text) carry an
explicit supersession marker rather than being edited.

**Critic mode:** cumulative

## Status

- [x] Chunk 01 — the owner test replaces the defect list
- [x] Chunk 02 — the worked example
- [x] Chunk 03 — propagate the norm

## Verification

Docs/skills only, but **the suite is evidence, not just a baseline**:
`tests/unit/test_song_lifecycle_doc_parity.py` asserts directly over `CLAUDE.md`,
`docs/skills.md`, `docs/song-workflow.md`, `skills/song-workflow/SKILL.md` and
this design's own artifact — it exists because the *previous* landing of this
stage drifted three surfaces. Chunk 3 extends it with five assertions locking
the identity/craft contract across six instruction surfaces (owner test
reachable everywhere · the identity floor · vocals specifically · the
over-argued-proposal anti-pattern · no surface reinstating the one-turn bound).
Each was mutation-checked: break the contract and the assertion fails.

**What the suite cannot cover, and who closes it.** The value of this work is
behavioural, and the session that wrote it holds far more context than a runtime
agent will — so it cannot run its own acceptance test. Enqueued for the operator
in `.prawduct/operator-verification.md` (ELI-2K8R), with the prompt and the
six-point rubric.
