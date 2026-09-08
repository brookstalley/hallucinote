---
artifact: build-plan
version: 2
scope: perform-start-position
branch: fix/perform-start-position
depends_on:
  - artifact: api-contract
  - artifact: sync-boundary-contract
  - artifact: boundary-patterns
governed_by:
  - artifact: sync-boundary-contract
    dispositions:
      - "planner↔apply result-key contract is explicit and versioned → conforms (the perform_batch arc payload gains additive fields only)"
      - "a phase that could not DETERMINE its state must not report OK → conforms (this plan is that rule applied to the perform pass)"
partition: serial — 02 and 03 both consume the primitive 01 builds, and 04 consumes the per-arc outcome field 02 adds
last_validated: 2026-09-08
---

## Requirements Confidence

**Level:** High

**Why:** The defect, its blast radius and its mechanism are all established by
direct operator evidence in issue #471, not inferred. The reporter isolated the
root cause against the live set and posted the A/B measurement that proves it:
locating with `song.current_song_time` and then calling `start_playing()` rolls
the transport from Live's **start playing position**, which
`current_song_time` does not move. Same set, same parameter, same span, minutes
apart — `updates_written` 0 before the cue jump, 27 after.

**Open assumptions / unknowns:**

- [ASSUMPTION: `CuePoint.jump()` is the only LOM surface that moves the start
  playing position | HIGH impact | operator can override] The LOM exposes no
  writable start-position property. The reporter verified `jump()` empirically
  and Live's own docstring states the semantics ("when not playing, simply move
  the start playing position"). If a better primitive exists, Chunk 01 is the
  single place it would be swapped in.
- [ASSUMPTION: creating and immediately deleting a temporary locator is an
  acceptable transient set mutation | MED impact | operator can override] Needed
  only when no cue already sits at the target beat. It costs two Undo entries.
  The alternative — playing from the nearest earlier cue and letting each arc's
  window gate the writes — costs unbounded pre-roll wall-clock on a beat-345
  arc, which for a realtime pass is the worse trade.
- Live cannot be driven from this session. Every mechanism chunk lands with unit
  coverage against fakes plus an `operator-verification.md` entry; the fakes
  cannot prove the Live-side behaviour and this plan does not claim they do
  (`learnings.md`: the 2026-05-17 fakes mirrored what we *thought* Live exposed
  and the unit suite never saw the divergence).

**What would raise confidence:** the operator-verification entries in Chunk 05,
run against the `songs/alien` set that produced the report.

## Status

- [x] Chunk 01: `handlers/_transport.py` — locate the start playing position, and prove where the playhead actually landed
- [ ] Chunk 02: `perform_batch` locates the start position and refuses a pass that did not roll into its span
- [ ] Chunk 03: the render capture path and `session` transport get the same treatment
- [ ] Chunk 04: per-arc perform outcomes reach the push report
- [ ] Chunk 05: artifacts, change-log, learnings, operator verification, backlog

Context: Plan written 2026-09-08 against issue #471 on branch
`fix/perform-start-position` (off `develop` @ 6339887). Chunk 01 built and
green; its Critic review is deferred to Chunk 02, which is the first diff where
the primitive has a caller to judge it against. Next: Chunk 02.

## Verification Strategy

Unit tests drive fake `Song` objects that model the defect directly: a fake whose
`current_song_time` setter moves a *playhead* field while `start_playing()` reads
a *separate* start-position field. That fake reproduces #471 exactly, so every
test in Chunks 01-03 fails convincingly without the fix — which is the only
honest way to test a Live behaviour this session cannot exercise.

Beyond tests: Chunk 05 enqueues operator verification for the two things only
Live can answer — that the cue jump moves the start position on a real set, and
that a perform against a set with pre-existing lanes now records.

## Build Chunks

### Chunk 01: `handlers/_transport.py` — locate the start playing position, and prove where the playhead actually landed

- **Description:** The defect is one missing primitive used in three places, so
  it gets built once. Two functions: `locate_start_position`, which moves Live's
  start playing position (not just the playhead) to a target beat; and
  `assert_playhead_within`, which reads back where the transport ACTUALLY rolled
  from after `start_playing()` and raises naming the observed beat when it is
  outside the expected window. The second is the load-bearing one: it is
  mechanism-independent, so it converts this entire failure class from silent
  divergence into a loud error even if the locate primitive itself is wrong.
- **Depends on:** none
- **Artifacts consumed:** `boundary-patterns.md` (Live-touch bout discipline),
  `learnings.md` (never verify a transport write by reading the same property
  back in the same callback; worker-thread settle polls, never main-thread)
- **Deliverables:** new `hallucinote_mcp/src/hallucinote_mcp/handlers/_transport.py`
  — `locate_start_position(context, target_beats, *, settle_timeout_s)` returning
  the method actually used (`existing_cue` / `temporary_cue` / `playhead_only`)
  and the beat it settled at; `assert_playhead_within(context, low, high, ...)`.
  The temporary-cue path reuses the proven `cue_create` recipe in
  `hallucinote_mcp/src/hallucinote_mcp/handlers/arrangement.py` (seek → settle on
  the worker thread → toggle → scan `song.cue_points` for the new entry), jumps
  to the cue it created, then toggles it away and verifies it is gone.
- **Tests:** unit — a cue already at the target is jumped, never toggled (a
  toggle would DELETE the operator's locator); no cue → created, jumped, deleted,
  and the set's cue list is byte-identical afterwards; a target past
  `last_event_time` refuses with a teaching error rather than toggling at a
  clamped position; no cue API → `playhead_only` reported, never a silent success;
  `assert_playhead_within` accepts an in-window beat and raises naming the
  observed beat for one outside it.
- **Acceptance criteria:** against the split-field fake (playhead ≠ start
  position), `locate_start_position` leaves the START position at the target;
  the same test fails against a bare `current_song_time` write.
- **Critic mode:** deferred to Chunk 02
  <!-- A primitive with no caller is half a risk surface: the judgeable question
       is whether perform_batch uses it correctly, and that diff does not exist
       until 02. Reviewing 01 alone would spend a pass on an interface nobody
       has consumed yet and then need a second one anyway. -->
- **Done when:**
  1. Acceptance criteria met and tests pass
  2. Committed and chunk marked `[x]` in Status (its review lands with Chunk 02)

### Chunk 02: `perform_batch` locates the start position and refuses a pass that did not roll into its span

- **Description:** Apply the primitive at the site the bug was reported against,
  and close the reporting half. `perform_batch` currently seeks, settle-verifies
  the seek (PSH-4L6C), then plays — and PSH-4L6C's settle poll passes cleanly in
  the failure, because `current_song_time` really does read the target while
  stopped. The seek was never the lie; the start position was. After
  `start_playing()` the realized playhead is asserted inside the union span, so
  a transport that rolled from beat 348 for a span of 8..24 fails loudly instead
  of breaking out of the ramp loop on its first tick with zero writes. Each arc
  also carries an explicit `outcome`, so `updates_written == 0` is a stated
  non-recording rather than something a reader has to derive from two fields.
- **Depends on:** Chunk 01
- **Artifacts consumed:** `api-contract.md` (the `perform_batch` arc payload)
- **Deliverables:** in
  `hallucinote_mcp/src/hallucinote_mcp/handlers/automation.py` — the arm/seek
  bout calls `locate_start_position`; a realized-playhead assertion between
  `start_playing()` and the ramp loop; per-arc `outcome` (`recorded` /
  `unverified`) and `outcome_reason` added to each arc in the result, with
  `updates_written == 0` and `automation_state != 1` both mapping to
  `unverified`.
- **Tests:** unit — the split-field fake reproduces #471 (a pass whose start
  position is past the union span) and the handler now raises naming both beats
  instead of returning `ok`; an arc that ramps normally reports
  `outcome: recorded`; a degenerate sub-tick window reports `unverified` with
  `updates_written: 0`; the restore path still disarms `record_mode` and closes
  every gesture on the new failure path.
- **Acceptance criteria:** the reproduction test fails against `develop`'s
  handler and passes here; no perform result can carry `outcome: recorded`
  with `updates_written: 0`.
- **Done when:**
  1. Acceptance criteria met and tests pass
  2. `/prawduct:critic` run and blocking findings resolved
  3. Committed and chunk marked `[x]` in Status

### Chunk 03: the render capture path and `session` transport get the same treatment

- **Description:** The same seek-then-play assumption is written into two more
  places, and one of them states it as a guarantee in an operator-facing note.
  `render.py` seeks to `start_at_beat - pre_roll_beats` and plays; its engine
  pre-flight samples whether the transport ADVANCES but never whether it is in
  the right PLACE, so a render can capture minutes of the wrong section and
  report a healthy capture. `session.py`'s `_PLAY_SEMANTICS_NOTE` tells the
  operator that "in a clean transport state, seek then play locates-and-plays:
  the render capture path relies on exactly that" — which is the false belief
  that cost the reporter six hours, shipped as documentation.
- **Depends on:** Chunk 01
- **Artifacts consumed:** `operational-spec.md` (render capture contract)
- **Deliverables:** in
  `hallucinote_mcp/src/hallucinote_mcp/handlers/render.py` — the capture locates
  the start position, and the pre-flight asserts position as well as advancement,
  naming the observed beat when it is wrong. In
  `hallucinote_mcp/src/hallucinote_mcp/handlers/session.py` — `seek` moves the
  start playing position and reports which method did it, so the operator's own
  seek-then-play read-back workflow (the one that produced the evidence table in
  #471) is trustworthy; `_PLAY_SEMANTICS_NOTE` rewritten to state what is
  actually true.
- **Tests:** unit — a render whose start position is stale fails the pre-flight
  with the observed beat named, rather than capturing; `seek` moves the start
  position on the split-field fake; the existing engine-off pre-flight test still
  distinguishes "engine off" from "wrong place" (two causes, two messages).
- **Acceptance criteria:** no handler in the package reaches `start_playing()`
  for a positioned pass without having located the start position — asserted by
  a grep-style test over the handlers package, so a fourth site cannot be added
  silently.
- **Done when:**
  1. Acceptance criteria met and tests pass
  2. `/prawduct:critic` run and blocking findings resolved
  3. Committed and chunk marked `[x]` in Status

### Chunk 04: per-arc perform outcomes reach the push report

- **Description:** Ask 3 of the issue. A realtime phase that spends minutes of
  wall clock and reports `ok (1 call)` tells the author nothing; the reporter had
  to find the divergence by ear. `record_perform_result` already refuses a
  fingerprint on `updates_written == 0`, so the gap is not the policy — it is
  that a recorded arc produces no line at all, and only failures are visible.
  Every arc gets a stated outcome in the push report.
- **Depends on:** Chunk 02
- **Artifacts consumed:** `sync-boundary-contract.md` (apply-layer warning
  channels), `push-execute-design.md`
- **Deliverables:** in `src/hallucinote/sync/push/perform.py` —
  `record_perform_result` prefers the handler's explicit `outcome` where present
  and keeps the `automation_state` / `updates_written` checks as the floor for an
  older server. In `src/hallucinote/sync/push/plan.py` —
  `apply_push_results` gains a keyword-only `notes_sink` so the apply layer has a
  BENIGN channel (today it has only the actionable one, which rides
  `.last-push-errors.json`; a per-arc roll-up there would make a clean push look
  failed). In `src/hallucinote/sync/push_execute.py` — wire `notes_sink` to the
  existing `warning_messages` list that the push state file already surfaces.
- **Tests:** unit — a mixed batch (one recorded, one unverified, one skipped
  unchanged) produces one roll-up line naming all three and exactly one
  actionable warning; an all-recorded batch produces the roll-up and no
  actionable warning; a result from a server predating `outcome` still routes on
  `updates_written` (the floor).
- **Acceptance criteria:** the push report names every arc the perform phase
  touched and what happened to it.
- **Done when:**
  1. Acceptance criteria met and tests pass
  2. `/prawduct:critic` run and blocking findings resolved
  3. Committed and chunk marked `[x]` in Status

### Chunk 05: artifacts, change-log, learnings, operator verification, backlog

- **Description:** Close the loop. The learning here is worth more than the fix:
  a Live property that reads back the value you wrote can still not be the
  property that governs the behaviour you want, and this codebase already carries
  a sibling rule (`learnings.md`: never verify a transport write by reading the
  same property back) that this defect walked straight past because the read-back
  was honest and the property was wrong.
- **Depends on:** Chunks 01-04
- **Artifacts consumed:** all of the above
- **Deliverables:** `.prawduct/learnings.md` rule; `.prawduct/change-log.md`
  entry (`type=fix | scope=perform-start-position`, no `release=` key);
  `api-contract.md` and `sync-boundary-contract.md` updated for the additive arc
  fields and the `notes_sink` parameter; `.prawduct/operator-verification.md`
  entries for the two Live-only questions; `CHANGELOG.md`; the two descoped asks
  filed via `/prawduct:backlog` (see Descoped below).
- **Tests:** none — documentation.
- **Type:** cumulative-final
- **Visual change:** no
- **Done when:**
  1. Artifacts updated and the backlog items filed
  2. Committed, then `/prawduct:critic cumulative` run and blocking findings resolved
  3. Chunk marked `[x]` in Status

## Descoped — stated, not dropped

Issue #471 carries four asks. Two are built here (asks 2 and 3, as Chunks 02 and
04) and two are deliberately not, each for a reason that changed once the
reporter found the root cause:

- **Ask 1 — verify each arc by sampling the parameter back across its span
  instead of trusting `automation_state`.** Written before the mechanism was
  known, when read-back shape was the only diagnostic available from outside. It
  is now superseded by cheaper and stronger signals: `updates_written` is a
  direct count of what the pass wrote, and the realized-playhead assertion in
  Chunk 02 catches the failure before the pass even runs its ramp. Read-back
  sampling would also cost a seek-and-read per arc per push against a write-only
  surface. Filed to the backlog as a defence-in-depth follow-up rather than
  built, because the argument for it is now weaker than the argument for the two
  guards that replace it — not because it is wrong.
- **Ask 4 — prefer the `session_clip` route wherever the span allows it.** A
  routing-policy change to `classify_envelope_route`, not a bug fix, and the
  reporter's own caveat names real consequences (`insert_step`-only, so a ramp
  must be authored as an explicit staircase). It deserves its own design pass
  against the authoring layer. Filed to the backlog.

Both are filed in Chunk 05, so neither survives only in this paragraph.

## Governance Checkpoints

**Commit & PR cadence:** commit per chunk after its Critic review passes. Chunk
05 carries the `cumulative` review that makes the branch PR-ready.

- After Chunk 01: confirm the primitive's shape before two more call sites depend
  on it.
- After Chunk 03: the handlers package changed, so the MCP wire fingerprint
  flips — a re-vendor and a Live relaunch are required before any operator
  verification means anything.
- After Chunk 05 (cumulative): full-bundle review.
