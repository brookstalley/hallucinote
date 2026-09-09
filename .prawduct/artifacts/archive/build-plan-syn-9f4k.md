---
lifecycle: completed
archived: 2026-09-08
maintained: false
---

> **Archived — no longer maintained.** This plan records what was built, not what will be. Do not edit it to reflect later changes; write those where they are true.

# Build Plan — SYN-9F4K: fail loud on empty-rack load (push devices phase)

**Branch:** `fix/syn-9f4k-empty-rack-fail-loud` (worktree `../hallucinote-wt-syn9f4k`)
**Base:** develop (95dddaf) · **Baseline:** affected suite 134 passed (full suite at verify)
**Critic mode:** cumulative (worktree is gate-blind → Critic runs via independent Agent on `develop..HEAD`, PR via gh — see [[feedback_worktree_governance_gates_blind]])
**Work type:** bugfix (M) — root cause confirmed; needs a regression test. Engine-only (no MCP wire change → no fingerprint flip, no re-vendor, no operator-verify).

## Confidence check

- **Problem:** On a FRESH push, a rack-preset device whose preset identity doesn't
  resolve loads as an empty shell (`chain_count == 0`). The planner still authored
  nested-chain param / chain-property writes for it; in the executor's devices-phase
  convergence pass those writes each fail `IndexError: chain_index N out of range
  [1, 0]` — hundreds of cascade errors that bury the real cause (the empty load).
  (incoming-bug 2026-06-20 fresh-push-loads-rack-presets report, fix #3, deferred to
  this item. Primary empty-rack cause already fixed by SYN-RACK-PRESET-RELINK; this
  is the diagnostics half.)
- **Success:** A fresh push of a song whose rack loads with `chain_count == 0` (DB
  authored nested content) halts the devices phase on ONE clear "preset content did
  not load" error per empty rack — the doomed nested writes are never dispatched. A
  re-push onto an already-populated set (chains present in Live, even with no DB
  selector) still emits its nested writes (the 8 `test_push_devices.py` no-selector
  cases unchanged).
- **Out of scope:** Persisting a durable portable preset identity at capture
  (`preset_query`) — that's the separate capture-side fix #2, already noted as a
  follow-up. Touching the planner (`plan_push_devices`) — the fix is purely runtime
  in the executor (the planner stays unchanged, so the no-selector tests are
  untouched by construction).

## Decisions locked (the 2026-06-21 design note + this scoping)

- **Engine-only, runtime probe in the execute loop.** Reuse the existing read-only
  `ableton_device(action='get_device_chains')` handler to read each freshly-loaded
  rack's RUNTIME chain count. NOT the rejected static-planner variant (breaks
  re-push) nor the load-handler variant (false-positives on a legit-empty preset),
  and NOT adding `chain_count` to the load result (would flip the MCP fingerprint).
- **Suppression key = `actual chain_count == 0` AND pending dependent nested writes**
  — never selector-absence. "Pending dependent nested writes" IS the expected-content
  signal (the planner only emits them when the DB authored nested content), and it is
  exactly the set where a cascade is possible. A loaded rack with no pending nested
  writes is never probed (a legitimately-empty preset stays silent).
- **Safety law: suppress-on-confident-empty, keep-on-any-doubt.** A probe that fails
  (None) or reports > 0 keeps every write — the guard can only escalate a genuine
  empty load into a clear halt, never invent one. Mirrors `device_param_diff.py`.
- **Halt, not a benign warning.** "Preset content did not load" is a genuine failure
  (the song's instrument is missing) — recorded as an error so the devices phase
  halts PARTIAL, but on ONE message per empty rack instead of the cascade.

## Files

- NEW `src/hallucinote/sync/push/empty_rack_guard.py` — pure-ish
  `partition_doomed_nested_writes(calls, *, probe_fn, name_fn=None)`; derives
  candidate racks from the calls themselves (groups dependent writes by their
  `(parent, device_index)` — that pair IS a rack's live address), probes each,
  and splits into `(survivors, empty_rack_failures)`. Unit-testable with a fake
  `probe_fn` + plain call objects. Models `device_param_diff.py`.
- `src/hallucinote/sync/push_execute.py` — `_probe_rack_chain_count` (reuses
  `get_device_chains`) + `_loaded_rack_name_fn` (best-effort rack display-name for
  the message, from this pass's load calls) + `_empty_rack_result_entries`
  (failures → synthetic `results` + `error_records`). Run the guard at BOTH
  devices-phase dispatch sites — the main dispatch (catches a re-push against a
  rack that is linked but still loads empty) AND the convergence pass (catches the
  fresh-load case). (W1 fix: the load link commits even on a halted push, so a
  re-push re-emits the nested writes in the main dispatch, not convergence — both
  sites must guard or the cascade returns on every push after the first.)
- NEW `tests/unit/sync/test_empty_rack_guard.py` — the helper: suppress-when-empty,
  keep-when-populated, keep-on-probe-failure, rack-own-params-survive, no-probe-when-
  no-dependent-writes, parent+index disambiguation, chain-terminal dependency, order.
- `tests/unit/sync/test_push_execute.py` — executor end-to-end: fresh unlinked rack
  + nested param; empty load (`chain_count 0`) → PARTIAL halt, one error, nested
  write NOT dispatched; populated variant (`chain_count 1`) → nested write dispatched,
  OK.

## Acceptance

- Empty-rack fresh push → `result.outcome == "partial"`, exactly one error matching
  "preset content did not load", the nested `set_parameter` never dispatched.
- Populated rack → nested writes dispatched, `outcome == "ok"`.
- All existing `test_push_devices.py` / `test_push_execute.py` / `test_push_devices_diff.py`
  green (no planner change; no-selector cases untouched).

## Status

- [x] Single chunk — empty-rack guard + executor wiring + tests.
  - Guard derives candidate racks from the calls (group by `(parent, device_index)`),
    runs at BOTH devices-phase dispatch sites (main + convergence). Engine-only.
  - 4375 passed, 2 skipped (full suite). New: `test_empty_rack_guard.py` (22) +
    3 executor e2e (fresh empty / populated / re-push empty), cascade modeled.
  - Independent cumulative Critic (worktree-blind → Agent on `caab81c^..HEAD`):
    PASS-WITH-WARNINGS → W1 (re-push reintroduces cascade) + W2 (test didn't model
    cascade) both fixed → verify-resolutions = RESOLVED, no new blocking findings.

**Context:** Code-complete on `fix/syn-9f4k-empty-rack-fail-loud` (2 commits:
caab81c first pass, 0ff75bb Critic-resolution rework). Pending USER go: merge to
develop, then backlog SYN-9F4K → shipped (closed-by the branch/PR) + archive the
already-archived incoming-bug stays as-is, + reflection.

## Done when

- [x] New + existing tests green (full suite).
- [x] Independent cumulative Critic — blocking findings resolved (verify-resolutions RESOLVED).
- [ ] Merge to develop (user go) → backlog SYN-9F4K → shipped. Reflection captured.
