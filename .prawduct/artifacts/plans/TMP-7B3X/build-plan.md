---
artifact: build-plan
version: 1
scope: tmp-7b3x
depends_on:
  - artifact: elicitation-and-stage-exit-criteria
  - artifact: sync-boundary-contract
governed_by:
  # `## Direction` sections DO govern this work. 27 norms were ratified on
  # 2026-08-10, after this plan was written, and the merge with develop brought
  # them in: `data-model.md`'s Direction is the one that bites, since it says the
  # DB is not the source of truth for what Live holds while this change makes it
  # the source of truth for what the SONG is. Those are different claims and both
  # stand — the score is authored; the set is projected — but the artifacts now
  # have to say so, which is why `api-contract.md`'s refusal illustration was
  # rewritten in this bundle. The artifacts below bind through their prose too;
  # each records a disposition.
  - artifact: sync-boundary-contract
    dispositions:
      - "phase 2 `time_signature_map` emits one `set_signature` for the bar-1 row and warns for the rest → conforms (the message moves from `notes` to `alerts` and says more; the emitted calls are unchanged)"
      - "every write goes through a mutator and emits an event → conforms (no new write path; two policy guards are deleted from existing mutators)"
  - artifact: project-preferences
    dispositions:
      - "durable prose carries the why inline rather than naming a work id → conforms (the replacement comments state the projection stance; backlog ids appear only in the backlog and the change log)"
last_validated: 2026-08-07
---

## Requirements Confidence

**Level:** High

**Why:** The requirement is an owner ruling recorded verbatim in
`elicitation-and-stage-exit-criteria.md` — *the song itself is 7/4 or whatever;
if we have to represent it as 1/4 or 1/8 in Live, fine* — and the backlog item
carries an explicit verifiable signal. The storage layer already accepts what
this enables (`time_signature_map.start_bar` is a float and the schema CHECK is
`>= 1.0`), and every downstream consumer of the map already reads multi-point
maps through meter-aware geometry helpers, which the existing planner tests
exercise via raw INSERTs. So the change is the deletion of a policy guard, not
the introduction of a capability.

**Open assumptions / unknowns:**

- [ASSUMPTION: push must keep *projecting* rather than refusing | MEDIUM impact |
  inferred from the ruling]  The backlog phrases the target as "the refusal is
  asserted at the push planner instead," but a hard planner refusal would make a
  true-7/4 song unpushable, which contradicts the ruling that representing it as
  a flat ruler in Live is acceptable. The planner therefore keeps its
  skip-and-report and gets a louder, more truthful message on the channel the
  operator actually reads. Recorded here rather than silently reinterpreted.

## The problem, success, and non-goals

**Problem.** `add_time_signature_point` and `update_time_signature_point` refuse
any `start_bar > 1.0`. The stated reason is a Live limitation — Live 12.4's MCP
has no `song_signature` automation target — so a projection limit is being
enforced in the source of truth. The consequence is that the DB cannot record
that a song *is* in changing or odd meter.

**Success.** A song DB round-trips a real meter map (4/4 at bar 1, 3/4 at bar 5,
7/4 at bar 9) through the mutators; the bar-floor guard at `< 1.0` still refuses;
the "this cannot reach Live" statement is made exactly once, at the push planner,
on the operator-facing channel (`plan.alert`, which the executor drains into the
push report — `plan.warn` writes `PushPlan.notes`, which it discards), naming
what Live will actually show; and no document still claims the DB refuses
within-song meter.

**Non-goals.** Making meter *reach* Live (TMP-4J6Q owns the materialization
mechanism). Making `Arrangement.plan()` or the read-side lenses meter-aware
(ARR-4M3T owns the authoring half). Tempo's identical gap (TMP-5K1R).

## Chunk 01: Lift the meter refusal into the projection layer

**Critic mode:** cumulative-final

**Delivers:**

1. `src/hallucinote/db/mutations/score.py` — delete the `start_bar > 1.0` refusal
   in `add_time_signature_point` and the `start_bar != 1.0` refusal in
   `update_time_signature_point`. `_require_bar_floor` stays. The replacement
   comment states the projection stance inline and retracts the stale "v1.1
   scope (per-bar-arrangement-clip workaround)" promise.
2. `src/hallucinote/sync/push/tempo.py` — `plan_push_time_signature_map`'s
   non-bar-1 message becomes a `plan.alert` (the channel the executor surfaces)
   and is explicit about the projection: the DB holds the authored meter, Live
   will show only the bar-1 value, and the felt meter has to live in note
   placement and accent until the materialization path exists. Tempo's identical
   skip message is promoted with it — the same silent drop.
3. `src/hallucinote/sync/push/arrangement.py` + `src/hallucinote/sync/geometry.py`
   — the coherence hazard the guard was incidentally masking gets a detector where
   bar positions actually become Live beats, in the arrangement and cue planners
   (the arrangement one is what `push execute --only arrangement` runs).
   `uniform_bar_math_divergences` compares each placement's meter-map beats
   against the bar-1-meter uniform beats and alerts only on the ones that differ,
   so a correct odd-meter song with nothing past the change stays quiet.
4. Tests — the four W10-H refusal tests in
   `tests/unit/db/test_score_extensions.py` are replaced by tests of the new
   contract (post-bar-1 add accepted and event-emitting, post-bar-1 update
   accepted, a three-point map round-trips in order, idempotent re-add still
   returns `unchanged`, bar-floor still refuses). `tests/unit/sync/test_push_score.py`'s
   `_ts_insert_raw` helper is retired in favour of the mutator; planner tests
   assert the projection alert lands on `plan.alerts`, and that the divergence
   alert fires for a placement past the meter change and NOT for one before it.
5. Docs — the "Meter (4/4 vs. other)" block in
   `docs/song-authoring-conventions.md` is rewritten to say the DB records the
   true meter and Live is the lossy projection, and to carry the arrangement-layer
   caveat. Every other page asserting the refusal (`docs/song-workflow.md`, the
   `/song-brief` and `/song-new` skills, the README, `api-contract.md`,
   `nonfunctional-requirements.md`, `docs/song-new-checklist.md`) is corrected
   with it. The release record is a `.prawduct/change-log.md` entry —
   `CHANGELOG.md` is frozen at v1.5.0 and its "Meter-ratchet refusal (H1)" line
   correctly records what shipped then.
6. Ride-along, outside the meter work and recorded rather than silent: the
   lifecycle doc-link parity test only validated links whose target was
   `song-workflow.md`, which is why a renamed heading left two backlog `refs:`
   dangling with the suite green. It now covers every relative `*.md#anchor` in
   the repo plus the bare `path/doc.md#anchor` form, its GitHub slugger no longer
   collapses whitespace runs, and append-only records are excluded (their links
   describe the tree as it was). Four dangling references fixed.

**Acceptance criteria:**

- `M.add_time_signature_point(..., start_bar=9.0, numerator=7, denominator=4)`
  returns an id and emits `TIME_SIGNATURE_POINT_ADDED`; `Q.get_time_signature_map`
  returns the three rows in `start_bar` order.
- `M.add_time_signature_point(..., start_bar=0.5, ...)` still raises the
  bar-floor teaching error.
- `plan_push_time_signature_map` over that map emits exactly one
  `ableton_session(set_signature)` call (the bar-1 row) and a `plan.alert` whose
  text names both the Live gap and what the DB still holds.
- `plan_push_arrangement` / `plan_push_cue_points` alert on placements past a
  meter change and stay silent for placements before it.
- `grep -rn "meter ratchets can't reach Live" src/ tests/ docs/` returns nothing.
- Full suite green (`python -m pytest`, no path argument), ruff + mypy clean.

**Done when:** acceptance criteria met, `/prawduct:critic` run and findings
dispositioned, TMP-7B3X closed and TMP-4J6Q's scope note updated via
`/prawduct:backlog`.

## Status

- [x] Chunk 01: Lift the meter refusal into the projection layer

Context: Chunk 01 shipped on `fix/tmp-7b3x-meter-source-of-truth` (2026-08-07);
suite green (counts in the evidence store), ruff + mypy clean. The branch then
sat cold for a month and was merged up with develop on 2026-09-09.
**The tracker close-out is still owed and happens at merge, not here:** issues
#221 (this work), #247 and #484 (the branch's own fate) are open, and the
earlier "TMP-7B3X archived" line referred to the markdown backlog, which froze
on 2026-08-10 and no longer records status. Closing them in the frozen file is
not available.
The blocker it existed to clear is cleared: the demo song's brief can now carry
a true meter map. The TOUR plan is parked, not finished — `active_build_plan`
pointed at it before this cycle and should point back at it once this branch
merges, with Chunk B1 as the next TOUR work.
