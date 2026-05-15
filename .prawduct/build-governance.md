# Build Governance — Songwright

This defines **how** to build. The build plan defines **what**. Read both before starting.

## Before You Build: Confidence Check

Before any work cycle on a non-trivial change, answer three questions in one sentence each:

1. **What problem are we solving?** (Observable, not abstract.)
2. **What does success look like?** (Specific, verifiable — "user can do X and see Y," not "it works.")
3. **What's out of scope?** (What you're deliberately not doing.)

If any can't be answered in one sentence, requirements aren't clear enough to build well (Principle 6 — Requirements Precede Code). Three options:

- **Close the gap** — one targeted question or an inference to confirm
- **Sketch and confirm** — write the answers, present, proceed once confirmed
- **Proceed knowingly** — declare the unknowns in the build plan's Requirements Confidence field as Medium or Low, and accept the rework risk

Don't silently start building on guesses. Code built on unclear requirements is debt the moment it's written. Skip the check for trivial work (typo, config); apply it for any chunk that touches behavior.

## Build Cycle

Each chunk follows this cycle. Do not skip steps.

- [ ] **Clean baseline** — All tests pass. No uncommitted changes. Medium+ work uses a feature branch.
- [ ] **Read the spec** — Chunk entry in build plan + referenced artifacts. Validate targets still exist — plans go stale. Run `/learnings [topic]` for relevant rules.
- [ ] **Write tests alongside code, never after** — Tests are specification made executable. Unit for logic, integration for interactions, e2e for critical flows. When the domain involves transformations, round-trips, serialization, or complex input validation, consider property-based tests alongside example-based tests (see test-specifications for details).
- [ ] **Implement** — Make tests pass. Follow `.prawduct/artifacts/project-preferences.md`. Write idiomatic code for the project's language. Prefer simplicity.
- [ ] **Update artifacts** — Changed API surface, data model, architecture? Update the artifact now, not later.
- [ ] **Verify** — Full test suite + product verification (launch it, call it, inspect output). Mocks alone are not verification. Record test results to `.prawduct/.test-evidence.json` (see format below). **Before running tests, run `python3 tools/product-hook test-status` — exit 0 means evidence was recorded this session with all tests passing; re-running is unnecessary.**
- [ ] **Critic review** — Read the chunk's `Critic mode:` field from `build-plan.md` and run `/critic chunk` or `/critic final` accordingly. Plans without a mode default to `final` (fail-safe to thoroughness). The Critic reads test evidence from step 6; it does not re-run tests. Fix blocking findings before proceeding. See `.prawduct/critic-review.md` for per-mode behavior.
- [ ] **Reflect now, not at session end** — Append to `.prawduct/.session-reflected` while context is fresh: what the chunk delivered, what the Critic caught, what surprised you, whether the methodology helped or hindered. Capture deferred work to `.prawduct/backlog.md`. Add a durable rule to `learnings.md` only if this cycle produced one. Writing reflections at chunk boundaries (not when the user is waiting on `/clear`) is a deliberate cadence choice — do it here.
- [ ] **Commit and persist state** — Commit all work. Update the **Status** section in `build-plan.md` — mark the chunk complete (`[x]`), update the Context line with what's done and what's next. This is mandatory — context compaction can happen at any time, and an empty Status means the next chunk (or session) starts blind. A chunk is not `[x]` until its "Done when" steps are complete.

## Test Evidence

After running the full test suite in the Verify step, write `.prawduct/.test-evidence.json`:

```json
{
  "timestamp": "ISO-8601",
  "git_sha": "HEAD at time of test run",
  "command": "the command used",
  "passed": 0,
  "failed": 0,
  "skipped": 0,
  "total": 0,
  "duration_seconds": 0
}
```

**Required vs. recommended.** The validator (`tests_are_current` and the `validate-evidence` subcommand) requires `timestamp`, `passed`, `failed`, `skipped`, `duration_seconds`, and `command` with the types shown — writer typos (e.g. `ran_at`, `num_passed`) fail loud rather than parsing as silent zeros. `git_sha` and `total` are recommended metadata; extra fields (e.g. `chunk`, `branch`, `notes`) are allowed.

**Canonical count.** `.test-evidence.json` is the authoritative test count for this session. Counts may also appear in change-log entries as informational context; the JSON file is the source of truth. Don't compare counts across files — they may legitimately differ (regex fallback in the briefing, pre-run estimates in change-log drafts).

The `timestamp` field is compared against `.prawduct/.session-start` to verify evidence was recorded during this session. The Critic and PR reviewer consult `test-status` before reviewing; if evidence is from this session with all tests passing, they skip the re-run.

**Skipping redundant test runs.** Builders, the Critic, and the PR reviewer all consult `test-status` before touching the test suite. Exit 0 ("current") means the saved evidence was recorded this session with all tests passing. Exit 1 ("stale") covers: missing evidence, evidence from a previous session, failing tests, missing required fields, or schema violations.

## Gate Waivers

Some sessions truly do not need every governance gate. A docs-only typo fix does not need a Critic review; a refactor that will never get a PR does not need PR review evidence. To declare a gate N/A for the current session, write `.prawduct/.gates-waived` as a JSON object with one key per waived gate and a non-empty reason string:

```json
{
  "critic": "docs-only edit, no logic to review",
  "pr": "no PR planned for this branch"
}
```

Valid keys: `"reflection"`, `"critic"`, `"pr"`. The reason is required (empty strings are ignored as a guardrail against silent skipping). The file is **auto-deleted at the next session start** so waivers never carry across sessions. The stop hook prints `GATE WAIVERS:` and the reason for each skipped gate, so the reviewer/auditor can see what was bypassed and why.

Use waivers sparingly — they exist for honestly N/A cases, not for shortcutting work that the gate would catch. Doc-only changes are detected automatically and don't need a waiver.

## Rules

- **Tests are contracts.** Fix the code, never weaken the test. Don't delete tests or relax assertions without a documented reason.
- **Complete delivery.** Every requirement implemented or explicitly descoped.
- **Scope discipline.** Build what the plan says. No unrequested features.
- **No "pre-existing" exception.** If you find a problem, fix or flag it.
- **Persist to files.** Context doesn't survive compaction. Plans and decisions go in artifacts.
- **CLAUDE.md is instructions, not docs.** Keep project-specific content under ~150 lines. Dev commands, test workflows, key conventions belong here. Architecture descriptions, config tables, component inventories, and API catalogs do not — put those in `docs/` or `.prawduct/artifacts/`.

## Session End

Each chunk already ends with commit + Status update and a reflection appended at chunk close. Before `/clear`: verify build plan Status is current → backlog deferred work → scan `.session-reflected` and add a short synthesis only if a cross-cutting pattern emerged across chunks. If you've been reflecting at work boundaries as instructed, `/clear` is fast. Never signal "done" until these are complete.

## Completing Work

Delete `build-plan.md`. `/pr merge` does this automatically.
