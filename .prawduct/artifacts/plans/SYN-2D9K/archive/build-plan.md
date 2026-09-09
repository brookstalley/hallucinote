---
lifecycle: completed
archived: 2026-09-08
unbuilt_at_archive: "no readable `## Status` roster — completeness cannot be read, and an unreadable plan is not evidence of completion"
maintained: false
---

> **Archived — no longer maintained.** This plan records what was built, not what will be. Do not edit it to reflect later changes; write those where they are true.

# Build plan — SYN-2D9K: prune orphaned `device_parameters` on replay

**Backlog:** SYN-2D9K (`.prawduct/backlog.md`). Branch: `fix/syn-2d9k-param-orphans` (worktree off develop).
**Refs:** `backlog SYN-2D9K`.
**Related:** BLD-RESET (sibling-in-`replay_capture`: the soft-reset preservation gap that lets these linger), SNP-2H9F.

## Requirements Confidence

**Level:** High

**Why:** Root cause is verified against the real DB + capture in the report and reconfirmed by code map; the fix is the *exact* reconcile the pull path already performs (`sync/pull/devices.py:1181-1193`), mirrored into the replay path; the mutator to reuse already exists and emits an event. Problem, success, scope each statable in a sentence.

**Open assumptions / unknowns:**
- `[ASSUMPTION: a snapshot device entry with NO "params_dialed" key means "no opinion, preserve DB params" — only an entry that CARRIES the key (present, possibly empty {}) reconciles | MED impact | user can correct / override]` — this mirrors the sidechain tri-state precedent (absent = no-opinion, explicit-empty = clear, present = set; `capture.py:368-387`, `tests/unit/capture/test_sidechain_snapshot.py`). Capture-produced snapshots *always* emit `params_dialed` (the full dialed set), so for them the reconcile is effectively unconditional and the bug is fixed; the absent-key carve-out only protects hand-authored partial snapshots. The alternative (drop unconditionally, treating absent ≡ empty ≡ drop-all) is simpler and matches the pull path literally but risks nuking params for a hand-authored snapshot that omits the key — rejected as the default for that reason.
- `[ASSUMPTION: reconcile runs for every device unconditionally (not gated on a detected class change) | LOW impact | user can override]` — matches the pull precedent and the "`params_dialed` is authoritative" invariant; "class changed" is just the most acute trigger, not the only one (a param set that merely shrinks orphans too).

**What would raise confidence:** N/A (High).

## Root cause (bugfix discipline)

A device's `device_parameters` rows orphan when its class/identity changes (e.g. Alien Voice's instrument swapped Operator→Analog in `captured_session.json`) and **nothing prunes them**:

1. `create_device` (`db/mutations/devices.py:409-454`) matches the existing row by `(chain_id, position)` and **UPDATEs in place** on a class change — the device `id` is reused, so its old children are never CASCADE-deleted.
2. `_replay_devices` (`capture.py:388-404`) **upserts** each snapshot param via `M.set_device_parameter` but never deletes DB params absent from `params_dialed`.
3. `replay_capture` runs `actor='sync'`, outside `build_session`; even inside one the converger *explicitly exempts* `device_parameter` from its delete sweep (`db/mutations/build.py:412`). And `reset_song_content` (the soft `--reset`, `db/mutations/links.py:18-127`) **deliberately preserves** `device_parameters`.

So the DB carried 116 valid Analog + 92 stale Operator params; the 92 fail forever at the `devices` push phase (`ValueError: parameter 'A Coarse' not found`) → cryptic HALT. **The asymmetry:** device *chains* already get drop-clears-stale reconciliation; `device_parameters` do not. **The precedent already exists on the pull side** (`sync/pull/devices.py:1181-1193` loops `M.remove_device_parameter` for every DB param name absent from the live read) — this is a replay-vs-pull asymmetry, not a missing capability.

## Chunk 1 — prune orphan params in `_replay_devices`  [status: done — 346186b, chunk-Critic clean]

- **Description:** After the param-upsert loop in `_replay_devices`, reconcile the per-device param SET: for a device whose snapshot entry carries `params_dialed`, read the device's current DB params (`Q.get_device_parameters`) and `M.remove_device_parameter` each whose `name` is not in the snapshot's `params_dialed` keys. Skip the reconcile entirely when the device entry has no `params_dialed` key (no-opinion; see Open assumptions). Mirror `sync/pull/devices.py:1181-1193`. Because `_replay_rack_chains` recurses through `_replay_devices`, this automatically covers nested-rack devices at every depth.
- **Depends on:** none.
- **Deliverables:** edit to `src/hallucinote/capture.py` (`_replay_devices`, the param section ~388-404). **No new mutator, no schema change** — reuse `remove_device_parameter` (`src/hallucinote/db/mutations/devices.py:746`, emits `DEVICE_PARAMETER_REMOVED`), satisfying the mutator-discipline learning (no raw SQL in callers; every write emits an event).
- **Tests:** new regression tests modeled on `tests/unit/capture/test_chunk_c_chains.py::test_re_replay_clears_a_dropped_prop` (replay snap1 → re-replay snap2-with-set-changed → assert DB pruned). Add to `tests/unit/capture/test_capture.py` (or alongside the chunk_c re-replay tests):
  - (a) **param shrink** — replay a device with `params_dialed {A,B,C}`, re-replay with `{A}` → B/C gone, A survives.
  - (b) **class swap** — replay an Operator (`class_name` "Operator", its param set), re-replay the same `(chain,position)` as Analog "Metalic Lead" with the Analog param set → all Operator-only params gone, Analog params present (the exact bug shape).
  - (c) **idempotency** — re-replay an unchanged snapshot → no `DEVICE_PARAMETER_REMOVED` event emitted, params unchanged (assert via the event log / mutator return, matching the no-spurious-event idiom in `replace_drum_pad_mappings`/`replace_device_param_overrides`).
  - (d) **absent-key preserve** — re-replay a device entry with `params_dialed` key *omitted* → existing DB params untouched (locks the carve-out; cross-references the sidechain `test_absence_is_no_opinion_not_clear_on_rebuild` contract, with a comment explaining params follow the *same tri-state* — present-empty clears, absent preserves — so a reviewer doesn't read it as inconsistent).
- **Acceptance criteria:** the four tests pass; full `pytest` (engine + capture suites) green; a re-replay/`--reset` of a class-swapped snapshot leaves the DB param set == the snapshot's `params_dialed` (no orphans), so a subsequent `devices` push has nothing to 404 on.
- **Critic mode:** (inferred — `chunk` for this non-final chunk)
- **Done when:**
  1. Acceptance criteria met and tests pass
  2. `/prawduct:critic` run and blocking findings resolved
  3. Committed and chunk marked `[x]` in Status

## Chunk 2 — make the device-phase orphan error teach (defense-in-depth)  [status: done — engine suite 2983 green. Built as a pure `_orphan_param_hint` helper wired at the push_execute failure-record site (overrides the MCP value-range hint); no MCP fingerprint flip]

- **Description:** When `set_parameter` 404s mid-`devices` push, replace the value-range-debugging hint with one that names the real cause. **As built:** the planner (`push/devices.py`) only *emits* the call; the failure + the misleading MCP value-range hint surface at *execution*, so the fix lands in `src/hallucinote/sync/push_execute.py` at the failure-record site — a pure `_orphan_param_hint(tool, action, err_msg, parameter_name)` helper that, on a `set_parameter` "not found", returns a hint naming the stale-orphan-from-class-change cause + the rebuild cure, overriding `hint` before it's recorded. Backstop for any *other* orphan source (a DB built before Chunk 1, an out-of-band param mismatch) — Chunk 1 is the actual fix.
- **Depends on:** Chunk 1.
- **Deliverables:** edit to `src/hallucinote/sync/push_execute.py` (the `_orphan_param_hint` helper + one wiring line at the failure-record site — no behavior change to the push itself, hint text only).
- **Tests:** extend the existing push-devices unit tests to assert the new hint text fires on a parameter-not-found failure (the failure-surface is already exercised; assert the message, not new control flow).
- **Acceptance criteria:** a simulated parameter-not-found failure yields the orphan-aware hint; existing push-devices tests green.
- **Type:** cumulative-final
- **Critic mode:** (declared via `Type: cumulative-final` — the chunk's own review IS the one `/prawduct:critic cumulative`)
- **Done when:**
  1. Acceptance criteria met and tests pass
  2. Committed and chunk marked `[x]` in Status
  3. `/prawduct:critic cumulative` run against `merge-base...HEAD` and blocking findings resolved (the `/prawduct:pr create` gate)

**Out of scope (deferred):** report option 2 — surfacing orphans pre-HALT in `compat check` / the push coherence gate (`param_orphan` bucket). Once Chunk 1 prunes on every rebuild the orphans don't survive to push time, so the pre-HALT probe is lower-value; it's a larger coherence-gate change. Note in the backlog if wanted; don't build here.

## Verification strategy

Pure engine fix — **no MCP fingerprint flip, no re-vendor, no Live required** (the change is in `capture.py`/`push/devices.py`, not the Live-side Remote Script). The deterministic unit tests (esp. case (b), the class-swap, which reproduces the exact 92-orphan shape) are the primary verification. Optional operator-confirm (songs repo + Live, not in this repo): rebuild `alien` and run `push execute --song alien --only devices` — the previously-failing 92 params no longer 404. This is confirmation, not a gate; the unit tests carry the contract.

## Governance checkpoints

**Commit & PR cadence:** commit per chunk after `/prawduct:critic chunk` passes (Chunk 1); PR after Chunk 2's one `/prawduct:critic cumulative` passes.
- After Chunk 1: `chunk` review — the reconcile logic + the four regression cases (esp. the absent-key carve-out, the most-likely-to-be-challenged decision).
