# ENV-7G4K — Build Plan (performed automation: master/group/return)

Item: gesture-recorded scripted ramps for the automation surface session clips
can't reach (envelope, L/L, `stage: design` → ready; AUD-1M4V stage 0b, user lock
"must-have early"). Design: `.prawduct/artifacts/plans/ENV-7G4K/design.md`;
requirements R3.2 + probe evidence linked there. One branch
(`feature/env-7g4k-performed-automation`), one PR into `develop`.

## Requirements Confidence: **Medium**

- **Problem (one sentence):** Master/group/return mixer and device-parameter moves —
  the canonical electronic transition craft — are unauthorable because session-clip
  envelopes can't host them and arrangement automation has no LOM write surface.
- **Success (one sentence):** A `mixer_volume` envelope authored on the master track
  in build.py is performed into Live's arrangement automation by push (fingerprint-
  gated, wall-clock visible), with `automation_state == 1` confirming the write.
- **Out of scope (one sentence):** Audio-track envelopes (ENV-8H1T), clip-locked
  return device envelopes (ENV-4M2T residual), `.als` editing as a write path, and
  any pull/read of arrangement automation (no LOM surface).

**Why Medium, not High:** the mechanism is probe-verified end-to-end on master and
return, but two behaviors the design leans on are unprobed — group-host recording
and re-record-overwrite — and both are resolved by cheap chunk-01 probe steps, not
by building.

**Open assumptions / unknowns:**

- `[ASSUMPTION: re-performing a changed arc over the same span cleanly overwrites the
  previously recorded automation (Live punch-over behavior); the fingerprint gate
  depends on this — probed in chunk 01 before the handler is written | HIGH impact |
  user can veto the in-push re-perform model if probe disproves]`
- `[ASSUMPTION: ~10 Hz value stepping driven off current_song_time produces
  musically-smooth recorded ramps (Live interpolates between recorded points);
  resolution tuned in the chunk 03 Live smoke if audible stepping appears | MED
  impact | user can override]`
- `[ASSUMPTION: per-segment curve_kind (fast/slow) is approximated by denser
  interpolation of the curve shape during the ramp, not by Live-side curve objects
  (recorded automation has no LOM curve surface) | LOW impact | defer]`

**What would raise confidence:** the two chunk-01 `ableton_probe` steps (group host +
re-record overwrite) — wire calls against the running Live, no restart cycle.

## Status

- [x] Chunk 01: probes + `ableton_automation perform` action (thin slice)
- [ ] Chunk 02: envelope eligibility — target kinds, routing replaces refusal
- [ ] Chunk 03: push phase + fingerprint gate + Live smoke
- [ ] Chunk 04: docs, guides, backlog closeout
Context: chunk 01 CODE built 2026-06-10 on feature/env-7g4k-performed-automation:
`perform` action + handler (runs_on_worker, lock under live_state_lock,
record_mode settle-poll per probe 10, per-step finally restore incl.
re_enable_automation, beat-space interp with linear/hold/fast/slow) + 24 unit
tests + LOCK_USERS audit entry. Chunk 01 step 0 verdicts landed 2026-06-11
(lom-probe-results.md rows 12/13): (b) re-record overwrite **CONFIRMED** —
same-span re-perform fully replaces the prior arc, automation_state stays 1 —
the HIGH-impact fingerprint-gate assumption holds; chunk 03 unblocked. (a)
group-host recording remains **blocked on one human action** (no group track
exists, LOM can't create one, Accessibility not granted for a scripted Cmd+G);
`env7g4k-probe-driver.py group` runs it unattended once a group exists. Per the
original probe doc this is opportunistic re-verification of a track-kind-
agnostic mechanism — carried into chunk 03's Live smoke (real song sets have
groups), NOT a chunk 02 blocker; chunk 02 group eligibility ships per design
decision 3 with the verdict noted pending.
Parallel item CLP-AUD1 already merged (PR #157); schema.sql rebase burden
now falls on this branch.

## Scaffolding

Existing project — no scaffold work. Unit tests in `hallucinote_mcp/tests/unit/`
(bridge) and `tests/unit/` (engine), fakes for Live contexts per existing handler
tests. Verification beyond tests: integration smoke against real Live 12.4.1
(entry added to `tests/integration/test_live_smoke.md`), evidence into
`.prawduct/operator-verification.md` for the audible/visual half.

## Coordination with CLP-AUD1 (parallel stage-0 sibling)

Shared file, disjoint regions: `src/hallucinote/db/schema.sql` (this item edits the
`envelopes` CHECK + adds `performed_automation`; CLP-AUD1 edits `clips`). Mechanical
rebase-on-merge, whichever lands second. No other overlap (this item never touches
`clips`/notes surfaces; CLP-AUD1 never touches envelopes/push).

---

## Chunk 01 — probes + `perform` action on the bridge (thin slice)

The architectural risk lives here: realtime worker-thread handler, async transport
state, gesture lifecycle. Prove it end-to-end before the engine learns about it.

Probe first (via the shipped `ableton_probe` tool, wire calls): (a) group-track
gesture recording — repeat probe 4's master sequence on a group track's
`mixer_device.volume`; (b) re-record overwrite — perform a second, different ramp
over the same span and confirm the first is replaced (read back is impossible;
verify via `automation_state` + a `.als` dump diff). Record verdicts in
`docs/research/audio-first-class/lom-probe-results.md` (append, same format).

Then the action: `perform` on the existing `ableton_automation` tool — new action
entries in `hallucinote_mcp/src/hallucinote_mcp/actions/automation.py`, handler in
`hallucinote_mcp/src/hallucinote_mcp/handlers/automation.py` per design.md "Bridge
changes" (runs_on_worker, `run_on_main` per Live touch, `live_state_lock` around
transport, `finally:` state restore, beat-space interpolation off
`current_song_time`, settle-poll for `record_mode` — never same-call read-back).

- **Type:** code
- **Foreign API:** ableton-live-lom (gesture/transport recording surface)
- **Deliverables:** `hallucinote_mcp/src/hallucinote_mcp/actions/automation.py`,
  `hallucinote_mcp/src/hallucinote_mcp/handlers/automation.py`; probe appendix in
  `docs/research/audio-first-class/lom-probe-results.md`; unit tests in
  `hallucinote_mcp/tests/unit/` (fake-Live: gesture ordering, state restore on
  exception, settle-poll, breakpoint interpolation incl. hold/fast/slow, param
  validation, wire-path regression per the probe-tool precedent).
- **Acceptance criteria:** `ableton_automation(action='perform', ...)` against the
  fake context records the exact begin_gesture → ramp → end_gesture → restore
  sequence; both probe verdicts appended; full bridge suite green.
- **Done when:**
  0. verify-api — the two probe runs above, verdicts recorded (this is the chunk's
     `verify-api` step; mechanism source: `lom-probe-results.md` probes 4/4b/10)
  1. Acceptance criteria met and tests pass
  2. `/prawduct:critic` run (inference: chunk) and blocking findings resolved
  3. Committed and chunk marked `[x]` in Status

## Chunk 02 — envelope eligibility: target kinds + routing replaces refusal

Engine-side per design.md "DB / engine changes": add `return_mixer_volume` /
`return_mixer_pan` to the `envelopes` CHECK in `src/hallucinote/db/schema.sql`
(+ mutator mapping in `src/hallucinote/db/mutations/` — kind → expected FK columns);
rewrite the W10-F dual-layer kind-refusal into routing eligibility (mutator side
`_envelope_track_kind_refusal`, planner side
`src/hallucinote/sync/push/envelopes.py::_warn_unreachable_track_kind`): master /
group / return-side targets become creatable and route to the perform path; `audio`
hosts keep their refusal (ENV-8H1T's scope) with the message updated to say so; the
now-false "route to a sub-bus instead" teaching for master is deleted. Add the
`performed_automation` table + its event-emitting mutator.

- **Type:** code
- **Deliverables:** `src/hallucinote/db/schema.sql`,
  `src/hallucinote/db/mutations/` (envelope kind map + performed-state mutator +
  event constant), `src/hallucinote/sync/push/envelopes.py` (routing predicate);
  tests in `tests/unit/db/test_mutations.py` + `tests/unit/sync/`.
- **Tests:** create master/group mixer envelope succeeds + emits event (was:
  refusal); return-mixer target kinds round-trip with CHECK enforced (wrong FK
  shape raises); audio-host refusal retained with new message; performed-state
  mutator emits event paired with state change; fingerprint helper is
  order-stable and changes when any breakpoint/target field changes.
- **Acceptance criteria:** a build.py-style script can author every wave-1 target
  (design.md decision 3) with no refusal; eligibility predicate cleanly partitions
  session-clip vs perform vs refused-audio.
- **Done when:**
  1. Acceptance criteria met and tests pass
  2. `/prawduct:critic` run (inference: chunk) and blocking findings resolved
  3. Committed and chunk marked `[x]` in Status

## Chunk 03 — push phase + fingerprint gate + Live smoke

New push phase after envelopes in `src/hallucinote/sync/push/plan.py` (+ a
`src/hallucinote/sync/push/` module for it): select perform-eligible envelopes,
fingerprint vs `performed_automation`, emit one `perform` call per changed arc; plan
output names each arc, its estimated wall-clock (span / tempo), states the transport
will play, and lists skipped-unchanged arcs (design.md decision 2 — Visible Costs).
Apply layer records performed-state + event on success; a failed perform surfaces as
a plan warning, never a silent skip. Integration smoke: new numbered entry in
`tests/integration/test_live_smoke.md` — author master volume ride + master-chain
device sweep + return send ride, push twice (second push must skip all arcs as
unchanged), verify `automation_state` + audible/`.als` evidence.

- **Type:** code
- **Visual change:** yes (recorded automation is audible/visible in Live —
  operator-verification entry at chunk close)
- **Deliverables:** `src/hallucinote/sync/push/plan.py`, new
  `src/hallucinote/sync/push/perform.py`; tests in
  `tests/unit/sync/test_push_song.py` (+ siblings); smoke entry in
  `tests/integration/test_live_smoke.md`.
- **Tests:** phase emits perform calls only for changed fingerprints; unchanged →
  skipped + reported; wall-clock estimate honors tempo map; apply records state +
  event; failure path warns and leaves fingerprint unwritten (next push retries).
- **Acceptance criteria:** the backlog item's core signal — a master `mixer_volume`
  envelope authored in build.py lands as arrangement automation via push, second
  push is a no-op; smoke executed against real Live with evidence recorded.
- **Done when:**
  1. Acceptance criteria met and tests pass (incl. real-Live smoke executed)
  2. `/prawduct:critic` run (inference: chunk) and blocking findings resolved
  3. Committed and chunk marked `[x]` in Status; operator-verification entry added

## Chunk 04 — docs, guides, backlog closeout

`docs/` capability-truth + the gaps guide (`ableton://guides/gaps` source) updated:
master/group/return automation moves from "can't" to "performed via push"; song-
authoring docs gain the performed-arc note (wall-clock + transport-plays). Backlog
pass via `/prawduct:backlog`: ENV-7G4K → shipped on merge; ENV-4M2T note narrowed to
its clip-locked-device residual; AUD-1M4V umbrella note (stage 0b done). Change-log
entry (canonical `prawduct:` tag form, status=merged at PR merge).

- **Type:** cumulative-final
- **Deliverables:** docs + guide files (located at build time — grep for the
  current refusal teaching text), `.prawduct/change-log.md`, backlog updates via
  the skill.
- **Acceptance criteria:** no doc/guide still claims master/group/return automation
  is unreachable; change-log entry present.
- **Done when:**
  1. Acceptance criteria met and tests pass
  2. Committed, then `/prawduct:critic cumulative` against `develop...HEAD` clean —
     the `/prawduct:pr create` gate (base: develop)
  3. Chunk marked `[x]` in Status; backlog pass via `/prawduct:backlog` as above

## Early Feedback Milestone

**Milestone chunk:** 01 — a hand-driven `ableton_automation perform` call records a
real master-volume ride into the user's Live set (the must-have-early lock made
tangible before any engine plumbing).

## Governance Checkpoints

**Commit & PR cadence:** commit per chunk after its Critic passes; one PR into
`develop` after Chunk 04's cumulative review passes (`/prawduct:pr`, base develop).

- After Chunk 01: review probe verdicts vs the two HIGH/MED assumptions — if either
  disproves, stop and re-plan before the engine chunks build on the model.
- After Chunk 03: review the wall-clock/skip reporting against Visible Costs before
  docs declare the surface authorable.
