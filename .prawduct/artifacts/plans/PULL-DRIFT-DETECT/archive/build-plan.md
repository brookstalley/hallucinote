---
lifecycle: completed
archived: 2026-09-08
unbuilt_at_archive: "no readable `## Status` roster — completeness cannot be read, and an unreadable plan is not evidence of completion"
maintained: false
---

> **Archived — no longer maintained.** This plan records what was built, not what will be. Do not edit it to reflect later changes; write those where they are true.

# PULL-DRIFT-DETECT — Build Plan

Branch: `fix/deep-rack-addressing` (same branch — small Medium fix riding the
DEEP-RACK-ADDR PR to develop). Critic: covered by the branch's final cumulative.
Source: bug report "`pull device-parameters --dry-run` is unusable as a drift detector —
reports every preset default as *added* + false *updated* on normalized params" (Severity M).

## Problem (three confirmed root causes)
`pull_cli execute device-parameters [--dry-run]` (the `/snapshot-bake-recent-changes`
engine) can neither confirm sync nor flag drift:

1. **Pollutes / false "added".** `apply_pull_device_parameters` iterates the FULL
   Live parameter surface and UPSERTS every param the DB doesn't hold
   (`existing is None → "added"`). On in-sync swell: 2452 preset defaults
   "added" — and a real (non-dry-run) apply would write all of them into the
   DB, which deliberately stores only the *dialed* set.
2. **False "updated".** The no-op check requires `display_same AND norm_same`.
   A display-only DB param (`value_normalized=NULL`) always mismatches the
   pull's freshly-computed non-NULL normalized → false "updated" on a value
   that didn't change (78 on swell).
3. **False "0 drift" on probe error.** Failed probes (version skew, etc.) become
   warnings only (`plan.py:91`); `mutations` stays 0 and the CLI exits 0 — "can't
   read" reads as "in sync." The dangerous twin.

## Fixes
- **F1 — scope to the tracked set** (`pull/devices.py apply_pull_device_parameters`):
  diff the DB-tracked params, not the full Live surface. A Live param NOT in the
  DB is a preset default the DB deliberately doesn't track → SKIP (don't add,
  don't pollute). The removal path (DB param absent from Live) stays. Rationale:
  the pull genuinely can't tell a user-dialed param from a preset default without
  the device's defaults (which it doesn't have); the default-INDEPENDENT signal
  is "a param the author already dialed CHANGED in Live." Capturing brand-new
  dialed params is the `/song-snapshot` full-recapture's job, not the lightweight
  drift bake (matches the learnings rule: narrow the pull to the default-
  independent case).
- **F2 — round-trip-aware comparison** (same function): a param is unchanged iff
  its effective value matches. Continuous (DB `value_normalized` set) → compare
  normalized within `_FLOAT_EPS` (display is a cosmetic render — don't require
  string equality). Display-only (DB `value_normalized=NULL`) → compare the
  display string. Drop the over-strict AND. On a real change the write may
  backfill normalized for a previously display-only param (fine).
- **F3 — fail loud on unreadable probes** (`pull/_core.py` ApplyResult +
  `pull/plan.py` + `pull_cli.py`): add an `unreadable` counter; increment it in
  the `ok=False` (and missing-result) branches. `_cmd_execute` returns a nonzero
  exit when `applied.unreadable > 0`. The JSON report carries `unreadable` so a
  human / the skill sees "couldn't read N probes," never a false "0 drift."
- **F4 (report split) — satisfied by F1+F3:** with defaults no longer captured,
  the report is now {mutations = dialed changed, no_ops, unreadable, warnings,
  details}. No separate `defaults_captured` channel needed.

## Skill
Update `skills/snapshot-bake-recent-changes/SKILL.md` to read the `unreadable`
field + treat a nonzero exit as "could not determine drift — do NOT proceed,"
not "0 changes."

## Tests
- F1: in-Live-only params are NOT added (rewrite `creates_when_db_empty` →
  `..._does_not_capture_untracked_live_params`; document the contract change —
  the old test codified the pollution bug).
- F2: display-only DB param (value_normalized=NULL) whose Live value is unchanged
  → no_op (the false-"updated" regression); a normalized param with display
  formatting drift but identical value → no_op; a genuine change → update.
- F3: a failed (`ok=False`) device_parameters probe → `unreadable == 1`,
  `mutations == 0`; `_cmd_execute` exits nonzero when unreadable > 0 (and 0 on a
  clean run).
- Preserve: no_op_when_identical, no_op_within_float_epsilon,
  updates_when_value_differs, removes_db_params_absent_from_live.

## Status — COMPLETE
- [x] F1 scope-to-tracked  - [x] F2 round-trip compare  - [x] F3 unreadable+exit
- [x] skill doc  - [x] tests

**Context:** All three root causes fixed. F1: `apply_pull_device_parameters`
iterates `db_by_name` (the tracked dialed set); Live-only params SKIPPED (the
2452-default pollution gone). F2: compare by the param's authoritative form —
normalized within `_FLOAT_EPS` for continuous (display is cosmetic), display
string for display-only (`value_normalized=NULL`) — dropped the over-strict AND.
F3: `ApplyResult.unreadable` counts failed/empty probes (general — all domains);
`pull_cli execute` exits 2 when `unreadable>0` and prints a stderr warning + the
report. Skill `/snapshot-bake-recent-changes` updated to check exit code +
unreadable FIRST and never read a failed run as "in sync". Tests: 7 migrated
(the capture-all-params behavior was the pollution bug — normalization tests
re-homed on the update path via a sentinel seed) + 4 new (display-only no-op,
normalized-display-drift no-op, failed-probe unreadable, CLI exit-2). Full suite
3733 passed. No re-vendor (engine/skill only). Decision recorded: the pull
genuinely can't tell a dialed param from a preset default without the device's
defaults, so the default-INDEPENDENT scope (drift over the tracked set) is the
correct semantics; full re-capture of new dialed params is `/song-snapshot`.
