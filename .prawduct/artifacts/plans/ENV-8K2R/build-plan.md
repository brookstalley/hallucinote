---
artifact: build-plan
version: 1
scope: ENV-8K2R, ENV-2T9K
depends_on:
  - artifact: build-plan
    path: .prawduct/artifacts/plans/ENV-9P4T/build-plan.md
  - artifact: api-notes
    path: .prawduct/artifacts/plans/ENV-9P4T/api-notes.md
last_validated: null
---

# Complete Song-Scale Automation — ENV-8K2R hardening + ENV-2T9K fidelity: Build Plan

**Goal.** Close out the two follow-up items the ENV-9P4T merge (PR #161) spun off, so the
mix-scale performed-automation feature is *complete* rather than merely shipped:

- **ENV-8K2R** — 7 perform-handler hardening fixes from the ENV-9P4T cumulative Critic
  (two data-safety/fidelity, the rest correctness/robustness/code-health).
- **ENV-2T9K** — perform fidelity via **tempo-reduction-during-record** (the redirected
  ENV-9P4T chunk 03; the framed "adaptive tick density" approach was probe-invalidated —
  perform fidelity is realtime/scheduling-bound at ~2.5 Hz, so the only lever is slowing the
  transport so the fixed tick rate yields more breakpoints *per beat*).

Extends the shipped perform path (ENV-7G4K → ENV-9P4T). No new packages; all work is in the
existing handler (`hallucinote_mcp`), planner/apply (`src/hallucinote/sync/push`), and the
MCP client/server wire. Scaffolding / Dependency sections are **N/A**.

## Requirements Confidence

**Level:** High (ENV-8K2R — the backlog item is a file:line-cited checklist authored by the
cumulative Critic; each fix has a named surface and a verifiable signal) · High (ENV-2T9K —
the mechanism is probe-confirmed in `ENV-9P4T/api-notes.md`; only the slowdown-factor default
+ cost-model wiring are open design).

**Two packages, two test homes.** Handler fixes land in
`hallucinote_mcp/src/hallucinote_mcp/handlers/automation.py` (tested under
`hallucinote_mcp/tests`); planner/apply fixes land in `src/hallucinote/sync/push/`
(tested under `tests`). The full suite is `python3 -m pytest -q tests hallucinote_mcp/tests`.

**What needs Live (operator-gated `/mcp` reconnect + a live transport pass):** the
*recording-behavior* changes — ENV-8K2R #1 (async disarm settle), #2 (gesture-close final
value), and all of ENV-2T9K (tempo save/restore changes what gets recorded). #3/#4/#5 are
planner/client logic, fully unit-testable in-process. The Live smoke for #1/#2 + ENV-2T9K is
**batched into one reconnect at the end** — a server respawn is required for the handler code
to take effect, so per-fix reconnects would be wasteful.

**Open assumptions / unknowns:**
- `[ASSUMPTION: ENV-2T9K slowdown is a CONFIGURABLE factor with a conservative default (not a hardcoded 4×) — it trades wall-clock for fidelity (4× slower = 4× density = 4× pass duration), so the operator must be able to dial it. Default chosen in chunk 04 + surfaced as a Visible Cost | MED impact | user can override the default]`
- `[ASSUMPTION: ENV-8K2R #3's collision resolution keeps the SKIPPED-unchanged arc's recorded lane and DEFERS the colliding changed arc with an alert (mirrors the existing two-changed-arcs "keep first, defer rest" behavior) — the data-safety win is not clobbering the already-correct recorded lane | MED impact]`
- `[ASSUMPTION: ENV-8K2R #1's parametrized settle helper is called DIRECTLY on the worker thread for BOTH attributes (record_mode + session_automation_record) — routing the second through _attempt's run_on_main would nest run_on_main from the main thread and deadlock (the existing code comment at automation.py:1934 already proves this for record_mode) | HIGH impact — wrong threading deadlocks the restore path]`

**What would raise confidence:** the batched Live smoke (one reconnect) — confirms the async
disarm settles, the gesture-close endpoint lands its authored final value, and the tempo
reduction moves a 0.5-beat dip authored to 0.1 materially closer than the ~0.589 baseline.

This plan extends an existing codebase — Project Structure / Dependency sections are **N/A**.

## Status

- [x] Chunk 01 — code-health foundation (ENV-8K2R #6, #7) · NO reconnect — `_require_parent`
  gained an opt-in master branch + `_resolve_send` extracted (all 4 send_level paths use it,
  `_resolve_perform_target` delegates parent resolution); `server.py` private timeout-constant
  re-exports dropped, `test_server.py` repointed at `client.read_timeout_for` (4 duplicate
  policy-value tests removed — covered in test_client.py; 3 wiring tests consolidated to 1
  parametrized "consults the policy" test). Affected suites green (1107 MCP tests pass).
- [x] Chunk 02 — planner + apply + client robustness (ENV-8K2R #3, #4, #5) · NO reconnect —
  #3: duplicate-target preflight moved BEFORE the fingerprint gate and seeded by skipped-unchanged
  arcs too, so a changed arc colliding with an already-recorded lane is alerted, not silently
  recorded over it (both visit orders). #4: apply layer cross-checks the handler's `arc_count`
  against the returned per-arc entries (truncated/empty result now warns). #5: `ToolCall` gained
  a `read_timeout` field; the planner caps perform_batch at `union_seconds×3 + 90s` (clears the
  handler's own budget, bounds a dead worker); executor forwards it only when set (1-arg send_fn
  doubles untouched on the non-perform path). 722 sync tests pass (+5 new).
- [ ] Chunk 03 — recording-path data-safety + fidelity (ENV-8K2R #1, #2) · batched Live smoke
- [ ] Chunk 04 — ENV-2T9K perform fidelity via tempo-reduction-during-record · batched Live smoke

Context (2026-06-12, branch `feature/perform-handler-hardening` off `develop`): clean baseline
3370 passed / 2 skipped / 0 failed. **Chunk 01 done** (code-health dedup + re-export cleanup,
behavior-preserving — existing send/perform tests + new helper tests pass). Per the user's
per-chunk-Critic-skip preference for code-health chunks, no per-chunk Critic; cumulative Critic
+ batched Live smoke at the end. Next: chunk 02 (planner duplicate-target seed, planned/returned
cross-check, client read ceiling — all unit-testable, no reconnect).

## Chunks

### Chunk 01 — code-health foundation (ENV-8K2R #6, #7)

*No Live reconnect — pure refactor + test-side.*

- **#7 (dedup):** `_resolve_perform_target` (`handlers/automation.py:1551`) inlines
  send/return resolution a 4th time. Extract a `_resolve_send(context, track_index,
  return_index)` helper for the `send_level` branch and delegate the master/track/return
  parent resolution to (an extended) `_require_parent`, so the host-resolution lives in one
  place **before ENV-2T9K's chunk-04 handler change spreads it**.
- **#6 (no-back-compat-to-throwaway):** `server.py` re-imports private
  `_DEFAULT_READ_TIMEOUT` / `_ENSURE_LOADED_READ_TIMEOUT` solely so legacy `test_server.py`
  assertions pass. Repoint `test_server.py` at the public `client.read_timeout_for`, keep one
  test asserting `handle_tool_call` CONSULTS the policy, drop the private re-exports.

**Done when:** the host/send resolution has a single definition (grep proves it); `server.py`
no longer re-exports the private constants; `test_server.py` consults `read_timeout_for`;
suite green; chunk Critic clean.

### Chunk 02 — planner + apply + client robustness (ENV-8K2R #3, #4, #5)

*Unit-testable in-process — no reconnect.*

- **#3 (correctness):** `plan_push_performed_automation` (`sync/push/perform.py:299-343`)
  seeds `queued_targets` only with fingerprint-surviving (changed) arcs, so a skipped-unchanged
  arc colliding on one wire target with a changed arc records silently and corrupts the stored
  fingerprint. **Fix:** compute `perform_target_key` before the fingerprint skip and seed the
  preflight with skipped-unchanged keys too, so the collision alerts (keep the already-recorded
  skipped lane, defer the changed arc).
- **#4 (robustness):** the apply layer doesn't cross-check planned vs returned arcs — a
  short/empty `arcs` result records nothing silently. **Fix:** count/ID cross-check warning at
  the `perform_batch` apply branch.
- **#5 (robustness):** unbounded `perform_batch` wire read has no client-side ceiling — a dead
  worker on an open TCP socket blocks `push_cli` forever. **Fix:** a planner-derived explicit
  `read_timeout` (union-span estimate × factor + settle) restores a ceiling while preserving
  verification.

**Done when:** a unit test per fix (skipped+changed collision alerts; planned/returned
mismatch warns; perform_batch carries a bounded read_timeout); suite green; chunk Critic clean.

### Chunk 03 — recording-path data-safety + fidelity (ENV-8K2R #1, #2)

*Handler recording behavior — batched Live smoke at the end.*

- **#1 (data-safety, highest):** the `session_automation_record` restore
  (`handlers/automation.py:1948`) is a bare `setattr` — empirically async (2026-06-12), so it
  has a silent unapplied window. **Fix:** parametrize `_wait_for_record_mode_on_worker` over
  the attribute name and settle-verify `session_automation_record` too, calling it DIRECTLY on
  the worker thread (NOT through `_attempt`'s `run_on_main` — that deadlocks, per the existing
  code comment).
- **#2 (fidelity):** `_write_or_close` (`automation.py:1830`) closes the gesture without
  writing the final value, so the recorded endpoint is up to ~0.8 beat short of the authored
  final. **Fix:** write `interp(span_end)` immediately before `end_gesture`. (Relates to
  ENV-2T9K.)

**Done when:** unit tests against the handler fakes (parametrized settle covers both attrs;
close writes the final value before end_gesture); suite green; chunk Critic clean; queued for
the batched Live smoke.

### Chunk 04 — ENV-2T9K perform fidelity via tempo-reduction-during-record

*New handler design — batched Live smoke at the end.*

Temporarily lower the transport tempo during the `perform_batch` arc-recording pass so the
fixed ~2.5 Hz wall-clock tick rate yields proportionally more breakpoints per beat; because
`FloatEvent`s are beat-keyed, the captured automation plays back correctly at the song's real
tempo. Probe-confirmed approach (`ENV-9P4T/api-notes.md`).

- global-tempo **save/restore mid-pass** (set low before recording, restore after — must
  survive the exception path, alongside the existing record/transport restores).
- **configurable slowdown factor** (conservative default) — surfaced as a Visible Cost
  (4× slower = 4× wall-clock for the pass).
- **cost-model interaction:** the planner's union-span seconds estimate and the handler's
  wall-clock budget (`_PERFORM_WALL_CLOCK_FACTOR` path) must account for the slowdown.
- *optional* per-arc adaptive steepness — DEFER unless a flat factor proves insufficient.

**Done when:** unit tests (tempo saved/restored incl. exception path; cost estimate reflects
the multiplier); suite green; chunk Critic clean; **Live smoke**: a 0.5-beat dip authored to
0.1 records materially closer to 0.1 than the ~0.589 baseline at the reduced tempo.

## Verification / Done-when (whole effort)

1. Full suite green (`python3 -m pytest -q tests hallucinote_mcp/tests`), evidence recorded.
2. Per-chunk `/prawduct:critic` clean (blocking resolved).
3. ONE operator `/mcp` reconnect → batched Live smoke covering chunks 03 + 04.
4. `/prawduct:critic cumulative` clean before PR.
5. Backlog reconciled: ENV-8K2R → shipped (all 7 items); ENV-2T9K → shipped; both archived.
