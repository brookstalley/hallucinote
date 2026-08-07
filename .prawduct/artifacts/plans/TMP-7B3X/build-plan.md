---
artifact: build-plan
version: 1
scope: tmp-7b3x
depends_on:
  - artifact: elicitation-and-stage-exit-criteria
  - artifact: sync-boundary-contract
governed_by:
  # No `## Direction` section governs the score half of the DB — the repo's only
  # one (plans/BAK-7D2V/design.md) covers mix-bake durability. The artifacts
  # below bind this work through their prose; each records a disposition.
  - artifact: sync-boundary-contract
    dispositions:
      - "phase 2 `time_signature_map` emits one `set_signature` for the bar-1 row and warns for the rest → conforms (the warn text gets louder; the emitted calls are unchanged)"
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
  warn-and-skip and gets a louder, more truthful message. Recorded here rather
  than silently reinterpreted.

## The problem, success, and non-goals

**Problem.** `add_time_signature_point` and `update_time_signature_point` refuse
any `start_bar > 1.0`. The stated reason is a Live limitation — Live 12.4's MCP
has no `song_signature` automation target — so a projection limit is being
enforced in the source of truth. The consequence is that the DB cannot record
that a song *is* in changing or odd meter.

**Success.** A song DB round-trips a real meter map (4/4 at bar 1, 3/4 at bar 5,
7/4 at bar 9) through the mutators; the bar-floor guard at `< 1.0` still refuses;
the "this cannot reach Live" statement is made exactly once, at the push planner,
as a loud warn that names what Live will actually show; and no document still
claims the DB refuses within-song meter.

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
   non-bar-1 warn becomes explicit about the projection: the DB holds the
   authored meter, Live will show only the bar-1 value, and the felt meter has to
   live in note placement and accent until the materialization path exists. It
   also names the coherence hazard that the guard was incidentally masking — the
   arrangement authoring layer computes bar positions against a single uniform
   `beats_per_bar` while push translates bar positions through the meter map, so
   the two disagree once a non-bar-1 row exists.
3. Tests — the four W10-H refusal tests in
   `tests/unit/db/test_score_extensions.py` are replaced by tests of the new
   contract (post-bar-1 add accepted and event-emitting, post-bar-1 update
   accepted, a three-point map round-trips in order, idempotent re-add still
   returns `unchanged`, bar-floor still refuses). `tests/unit/sync/test_push_score.py`'s
   `_ts_insert_raw` helper is retired in favour of the mutator, and a planner
   test asserts the warn names the projection.
4. Docs — the "Meter (4/4 vs. other)" block in
   `docs/song-authoring-conventions.md` is rewritten to say the DB records the
   true meter and Live is the lossy projection, and to carry the arrangement-layer
   caveat. Every other page asserting the refusal (`docs/song-workflow.md`, the
   `/song-brief` and `/song-new` skills, the README, `api-contract.md`,
   `nonfunctional-requirements.md`, `docs/song-new-checklist.md`) is corrected
   with it. The release record is a `.prawduct/change-log.md` entry —
   `CHANGELOG.md` is frozen at v1.5.0 and its "Meter-ratchet refusal (H1)" line
   correctly records what shipped then.
5. Ride-along, outside the meter work and recorded rather than silent: the
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
  `ableton_session(set_signature)` call (the bar-1 row) and a warn whose text
  names both the Live gap and what the DB still holds.
- `grep -rn "meter ratchets can't reach Live" src/ tests/ docs/` returns nothing.
- Full suite green (`python -m pytest`, no path argument), ruff + mypy clean.

**Done when:** acceptance criteria met, `/prawduct:critic` run and findings
dispositioned, TMP-7B3X closed and TMP-4J6Q's scope note updated via
`/prawduct:backlog`.

## Status

- [x] Chunk 01: Lift the meter refusal into the projection layer

Context: Chunk 01 shipped on `fix/tmp-7b3x-meter-source-of-truth` (2026-08-07);
suite green at 4877 passed / 2 skipped, ruff + mypy clean, TMP-7B3X archived.
The blocker it existed to clear is cleared: the demo song's brief can now carry
a true meter map. The TOUR plan is parked, not finished — `active_build_plan`
pointed at it before this cycle and should point back at it once this branch
merges, with Chunk B1 as the next TOUR work.
