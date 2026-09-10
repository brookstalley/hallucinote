---
artifact: build-plan
version: 2
scope: open-bug-sweep
branch: docs/backlog-bug-readiness
partition: >-
  parallel in two waves — wave 1's seven chunks own disjoint file sets by construction;
  wave 2 holds the four chunks that contend for cli.py / push_execute.py / links.py with
  each other or with wave 1, plus the one item that needs a live Live session.
last_validated: 2026-09-10
---

# Build plan — close every open `kind: bug` item

**Scope**: the 22 items returned by
`prawduct-hook backlog list --repo brookstalley/hallucinote --kind bug --state open`,
all at `stage: ready`.
**Every chunk's requirement and design is written in its GitHub issue body — the issue is
the spec.** This plan is only the partition, the sequencing and the integration contract;
nothing here re-derives a design the issue already carries.

**Integration branch**: `docs/backlog-bug-readiness` (the branch the owner named).
**Coordinator**: the session that owns this file. **Delegates**: one per chunk, each in its
own `git worktree`, briefed at `.prawduct/.delegate-brief.md` inside that tree.

## Requirements Confidence

**Level:** High for 21 of 22 — each issue carries a numbered requirement set or an explicit
acceptance list written during the 2026-09-10 bug-readiness pass, and the code sites are
cited by path and line.

**Open assumptions / unknowns:**

- [ASSUMPTION: #275 cannot be closed from this session | HIGH impact | owner can override]
  Its acceptance criterion is *"the A-Plate return device class matches
  `captured_session.json` (Hybrid Reverb) after a fresh push"* — a claim only a live Ableton
  session can settle, and Live cannot be driven from here. The code half (does the Hybrid
  Reverb load path silently fall back to stock?) is answerable statically and is what this
  plan builds; the measurement half goes to `operator-verification.md`.
- [ASSUMPTION: #328's confound is the whole bug | MED impact] The issue itself says the
  fingerprint path is *not* the confirmed cause — a stray per-branch DB may explain the
  whole report. The chunk's first deliverable is the single-DB reproduction, and "not
  reproducible, the confound explains it" is a legitimate outcome that closes the item.

## The integrator's job (coordinator, never a delegate)

1. **Create every worktree** — `git worktree add -b <branch> ../hallucinote-<slug>
   docs/backlog-bug-readiness` — and write the brief into it at
   `.prawduct/.delegate-brief.md`, so an abandoned tree is visible at a later session start.
   Never the harness's own isolation, which hands back a tree that has no name until the
   agent is already inside it.
2. **Own the two files no delegate may touch.** `src/hallucinote/cli.py` — a subcommand
   whose module does not exist yet breaks the CLI at import, so a delegate writes its module
   and tests, exercises the entry point directly, and *reports the registration line*.
   `src/hallucinote/sync/push_execute.py` in wave 2, where two chunks would otherwise
   collide on it.
3. **Merge each delegate branch** with `git merge --no-ff`. Never squash.
4. **Run the full suite** after each merge or close pair, and tick a Status box only once
   that run is green.
5. **All governance**: Critic, change-log, backlog `status=shipped` + `closed-by`, the PR.
6. **Remove the worktree** after merge — the brief is what a session start reads to notice
   an orphan.

## The integration contract

**Delegates never govern.** No Critic, no Status boxes, no `project-state.yaml`, no
change-log entry, no backlog write, no merge, no PR.

**Delegates never run heavy tests.** The ceiling is the project's ratified one
(`project-preferences.md` → *Delegate verification*): the narrowest run covering the
delegate's own diff — normally the one or two test files its diff touches, plus a targeted
grep or one real CLI invocation for anything prose- or contract-shaped. **Explicitly
forbidden**: a bare `pytest`, `pytest tests/`, anything marked `audio` or `ableton`, and any
render, capture or analysis run. A cost bound *and* a correctness one — several whole-suite
runs contending on one box each report a different total, none complete, all exiting 0.

**Delegates report, in this order**: what changed; the exact command run and its result;
assumptions made; any wording decided rather than taken from the issue, marked `proposed`;
any registration request.

## Wave 1 — seven chunks, all parallel

Ownership is disjoint by construction. A delegate that finds it needs a file owned by
another row **stops and reports** rather than editing it.

| Chunk | Items | Owns (exclusive) |
|---|---|---|
| B1 | #222 #520 | `src/hallucinote/sync/compat.py` + `tests/unit/sync/test_compat.py`; the compat/REQUIREMENTS prose in `skills/ableton-push/` and `skills/song-pick-instruments/` |
| B2 | #325 #481 #465 | `src/hallucinote/audio/` + `tests/unit/audio/`; the `curve_kind` / fader-probe threading in `hallucinote_mcp/src/hallucinote_mcp/server_side/analysis.py`; `skills/mix-review/` |
| B3 | #496 #506 #522 | `src/hallucinote/sync/push/arrangement.py`, `src/hallucinote/sync/push/plan.py`, `src/hallucinote/arrangement.py`, `src/hallucinote/sync/geometry.py`, `src/hallucinote/db/mutations/arrangement.py`, `src/hallucinote/db/schema.sql` + its `_ADDED_COLUMNS` registry |
| B4 | #519 #524 | `src/hallucinote/capture.py`, `src/hallucinote/default_scaffold.py`, `src/hallucinote/db/mutations/tracks.py`, `src/hallucinote/db/mutations/links.py`, `tests/unit/capture/` |
| B5 | #508 #516 #521 | `hallucinote_mcp/src/hallucinote_mcp/handlers/probe.py`, `.../handlers/device.py`, `.../actions/probe.py`, `.../cli/preflight.py` + their unit tests |
| B6 | #503 #328 #475 | `src/hallucinote/markdown_refs.py`, `src/hallucinote/sync/push_notes.py`, `src/hallucinote/sync/push/perform.py` + their tests; the perform section of the `gaps` guide resource |
| B7 | #226 | `src/hallucinote/recurrence/` + `tests/unit/recurrence/`; `skills/compose-review/` |

**Why these groupings.** #222/#520 are one classifier. #325/#481 both rewrite
`verify_envelope_realization`'s windowing and cannot be designed apart; #465 rides the same
report surface. #496/#506/#522 are three defects in one arrangement-push pass, and #496 owns
the schema column the other two must not race. #519/#524 are both capture-replay identity.

## Wave 2 — four chunks, dispatched once wave 1 has merged

| Chunk | Items | Owns (exclusive) | Held back because |
|---|---|---|---|
| B8 | #291 | `src/hallucinote/sync/chain_rebuild.py` (new), `sync/push/devices.py`, `sync/push/probe.py`, `sync/push_cli.py`, `docs/song-authoring-conventions.md` | contends with B4 on `db/mutations/links.py`, with B6 on the push surface, and needs a `cli.py` line |
| B9 | #322 | `hallucinote_mcp/.../remote_script/dispatch.py`, `.../remote_script/server.py`, the jobs handlers + their tests | contends with B8 on `push_execute.py` — reports the caller change, coordinator applies |
| B10 | #476 | a new scaffold-verification module + its test; `skills/song-new/` | needs a `cli.py` line |
| B11 | #515 | the `note_expression` deletion across `hallucinote_mcp/.../actions/automation.py` and handlers, `src/hallucinote/generators/follow.py`, `docs/dubler.md` | contends with B5 on the MCP action surface |

**B12 — #275, coordinator-held.** Static half only: does the device-load path silently fall
back to stock when the authored class fails to load? Fix or refute that in code. The
measurement half — *A-Plate's class matches the snapshot after a fresh push* — is enqueued in
`operator-verification.md` and the item stays open until the owner runs it.


## The chunks

Each chunk's requirement and design is written in its GitHub issue — the issue is the
spec, and nothing below re-derives one. What each row adds is the partition: what this
chunk owned exclusively, and the narrowest run that proved it.

### Chunk B1: the compat check's blind spots

- **Items:** #222 #520
- **Deliverables:** `src/hallucinote/sync/compat.py` + `tests/unit/sync/test_compat.py`; the compat / REQUIREMENTS prose in `skills/ableton-push/` and `skills/song-pick-instruments/`
- **Tests:** `uv run --frozen pytest tests/unit/sync/test_compat.py`, plus a real compat run for the REQUIREMENTS.md output — that output is the user-facing half of #222
- **Acceptance criteria:** every acceptance box in each item's issue, or an explicit statement of which could not be met here and why
- **Done when:**
  1. Acceptance criteria met and the chunk's own tests pass
  2. Merged here with `--no-ff` and the full suite green
  3. Backlog item stamped `shipped`, or its remaining half named

### Chunk B2: the automation verifier grades the wrong thing

- **Items:** #325 #481 #465
- **Deliverables:** `src/hallucinote/audio/` + `tests/unit/audio/`; the `curve_kind` threading and fader provenance in `hallucinote_mcp/.../server_side/analysis.py`; `skills/mix-review/`
- **Tests:** `tests/unit/audio/test_automation.py` + `test_analyze.py`; no render, capture or analysis run
- **Acceptance criteria:** every acceptance box in each item's issue, or an explicit statement of which could not be met here and why
- **Done when:**
  1. Acceptance criteria met and the chunk's own tests pass
  2. Merged here with `--no-ff` and the full suite green
  3. Backlog item stamped `shipped`, or its remaining half named

### Chunk B3: three defects in one arrangement pass

- **Items:** #496 #506 #522
- **Deliverables:** `sync/push/arrangement.py`, `sync/push/plan.py`, `arrangement.py`, `sync/geometry.py`, `db/mutations/arrangement.py`, `db/schema.sql` + its `_ADDED_COLUMNS` registry
- **Tests:** `tests/unit/sync/test_push.py`, `tests/unit/test_arrangement.py`, and the schema canary that guards `_ADDED_COLUMNS`
- **Acceptance criteria:** every acceptance box in each item's issue, or an explicit statement of which could not be met here and why
- **Done when:**
  1. Acceptance criteria met and the chunk's own tests pass
  2. Merged here with `--no-ff` and the full suite green
  3. Backlog item stamped `shipped`, or its remaining half named

### Chunk B4: capture-replay identity

- **Items:** #519 #524
- **Deliverables:** `capture.py`, `default_scaffold.py`, `db/mutations/tracks.py`, `db/mutations/links.py`, `tests/unit/capture/`
- **Tests:** `tests/unit/capture/` plus `test_capture_planner_isolation.py` and the mutator tests touched
- **Acceptance criteria:** every acceptance box in each item's issue, or an explicit statement of which could not be met here and why
- **Done when:**
  1. Acceptance criteria met and the chunk's own tests pass
  2. Merged here with `--no-ff` and the full suite green
  3. Backlog item stamped `shipped`, or its remaining half named

### Chunk B5: three MCP defects that report something untrue

- **Items:** #508 #516 #521
- **Deliverables:** `hallucinote_mcp/.../handlers/probe.py`, `handlers/device.py`, `actions/probe.py`, `cli/preflight.py` + their unit tests
- **Tests:** the three matching test files, plus one real `preflight` invocation — its output is #521's contract
- **Acceptance criteria:** every acceptance box in each item's issue, or an explicit statement of which could not be met here and why
- **Done when:**
  1. Acceptance criteria met and the chunk's own tests pass
  2. Merged here with `--no-ff` and the full suite green
  3. Backlog item stamped `shipped`, or its remaining half named

### Chunk B6: three small, unrelated defects

- **Items:** #328 #475 #503
- **Deliverables:** `sync/push_notes.py`, `sync/push/perform.py`, `markdown_refs.py` + their tests; the perform section of the `gaps` guide
- **Tests:** each module's own test file, plus a grep proving `slowdown_factor` is reachable from the perform section
- **Acceptance criteria:** every acceptance box in each item's issue, or an explicit statement of which could not be met here and why
- **Done when:**
  1. Acceptance criteria met and the chunk's own tests pass
  2. Merged here with `--no-ff` and the full suite green
  3. Backlog item stamped `shipped`, or its remaining half named

### Chunk B7: a composed variation the recurrence lens could not see

- **Items:** #226
- **Deliverables:** `src/hallucinote/recurrence/`, `tests/unit/recurrence/`, `skills/compose-review/`
- **Tests:** `tests/unit/recurrence/` (36 tests, well under the ceiling)
- **Acceptance criteria:** every acceptance box in each item's issue, or an explicit statement of which could not be met here and why
- **Done when:**
  1. Acceptance criteria met and the chunk's own tests pass
  2. Merged here with `--no-ff` and the full suite green
  3. Backlog item stamped `shipped`, or its remaining half named

### Chunk B8: replacing an instrument without destroying the chain below it

- **Items:** #291 (+ #323)
- **Deliverables:** new `sync/chain_rebuild.py` + its test; `sync/push/devices.py`, `sync/push/probe.py`, `sync/push_cli.py`; `docs/song-authoring-conventions.md`, `skills/ableton-push/`
- **Tests:** `test_chain_rebuild.py`, `test_push_cli.py`, `test_push_devices.py` — all against a fake `send_fn`; Live cannot be driven from here
- **Acceptance criteria:** every acceptance box in each item's issue, or an explicit statement of which could not be met here and why
- **Done when:**
  1. Acceptance criteria met and the chunk's own tests pass
  2. Merged here with `--no-ff` and the full suite green
  3. Backlog item stamped `shipped`, or its remaining half named

### Chunk B9: the timeout that was only the caller looking away

- **Items:** #322 (+ #324)
- **Deliverables:** `hallucinote_mcp/.../remote_script/`, `dispatcher.py`, `wire.py`, `handlers/jobs.py`, `handlers/session.py`, `handlers/render.py`, `actions/session.py`, the `conventions` guide; `sync/push_execute.py` for the consumer half
- **Tests:** the six test files the issue's plan names, plus `test_push_execute.py`; the socket-margin test must stay green
- **Acceptance criteria:** every acceptance box in each item's issue, or an explicit statement of which could not be met here and why
- **Done when:**
  1. Acceptance criteria met and the chunk's own tests pass
  2. Merged here with `--no-ff` and the full suite green
  3. Backlog item stamped `shipped`, or its remaining half named

### Chunk B10: making the scaffold stage's own exit criterion runnable

- **Items:** #476
- **Deliverables:** a new scaffold-verification module + its test; `skills/song-new/`
- **Tests:** the module's test plus a real entry-point invocation against a scaffolded fixture song
- **Acceptance criteria:** every acceptance box in each item's issue, or an explicit statement of which could not be met here and why
- **Done when:**
  1. Acceptance criteria met and the chunk's own tests pass
  2. Merged here with `--no-ff` and the full suite green
  3. Backlog item stamped `shipped`, or its remaining half named

### Chunk B11: retiring a target kind that cannot exist

- **Items:** #515
- **Deliverables:** the `note_expression` surface in `hallucinote_mcp/.../actions/automation.py` + handlers; `generators/follow.py`; `docs/dubler.md`; the `gaps` guide
- **Tests:** `test_actions_automation.py`, the generator test, and a grep proving nothing advertises the kind as loadable
- **Acceptance criteria:** every acceptance box in each item's issue, or an explicit statement of which could not be met here and why
- **Done when:**
  1. Acceptance criteria met and the chunk's own tests pass
  2. Merged here with `--no-ff` and the full suite green
  3. Backlog item stamped `shipped`, or its remaining half named

### Chunk B12: is the device-load path reliable?

- **Items:** #275 (code half)
- **Deliverables:** `sync/push_execute.py`'s cross-machine load fallback + `tests/unit/sync/test_push_execute.py`
- **Tests:** `test_push_execute.py`; the item's own acceptance is a live measurement and is queued for the operator
- **Acceptance criteria:** every acceptance box in each item's issue, or an explicit statement of which could not be met here and why
- **Done when:**
  1. Acceptance criteria met and the chunk's own tests pass
  2. Merged here with `--no-ff` and the full suite green
  3. Backlog item stamped `shipped`, or its remaining half named

## Status

Merged into `docs/backlog-bug-readiness`. A ticked box means the chunk merged, its own
surface re-ran green, and the whole-suite run covering it exited 0 — **6175 passed, 2 skipped**
against a 6063 baseline, the delta being the delegates' own new tests. The count going UP is
what makes that green attributable: a contended run's tell is a total that silently drops.

- [x] B1 — #222 #520 · [x] B2 — #325 #481 #465 · [x] B3 — #496 #506 #522 · [x] B4 — #519 #524
- [x] B5 — #508 #516 #521 · [x] B6 — #503 #475 #328 · [x] B7 — #226
- [x] B8 — #291 (+ #323, folded) · [x] B9 — #322 (+ #324, folded) · [x] B10 — #476 · [x] B11 — #515
- [x] B12 — #275 code half shipped (`261aa51`); the item stays open on the operator half,
  now queued in `operator-verification.md` with both outcomes named
- [x] Cumulative Critic over the whole sweep — three rounds, review closed with zero findings

### Coordinator work the merges pulled in

- `cli.py` + `docs/running-the-engine.md` registration for `verify-scaffold` (B10 reported the
  lines; a subcommand missing from that table fails `test_cli.py`).
- The three surfaces still pointing at the pytest step #476 removed — `scaffold`'s own
  next-steps print above all, since an agent reads it immediately before the fixed step.
- `skills/ableton-mcp-install/` now passes the server root it already captured, so #521's
  advisory can reach the authoritative copy instead of withholding.
- The INCOMPLETE phase wording, which asserted every gap was an undetermined precondition —
  false about the sub-tick edge #475 added.

### Filed, not fixed

- **#526** — `ableton_probe(action='call')` carries #508's string-typing hole; left out of that
  fix deliberately, and it has one real design question (`coerce_wire_value` gates on the
  property's current value, and a call argument has none).
- **#527** — `pytest hallucinote_mcp/tests/` alone fails collection. Reproduced on the
  untouched base commit, so it predates this sweep; not fixed here because the remedy touches
  shared pytest config while delegates are running against it.
- **WSP-8Q4M is NOT an open discrepancy.** A delegate flagged it as open in
  `.prawduct/backlog.md:1192`; that file is frozen history and is not read. The item is
  \#327 in the tracker of record and is already closed.

## Context

**Complete.** All twelve chunks merged into `docs/backlog-bug-readiness`; suite green at
6357 passed / 2 skipped under the declared parallel command, recorded from JUnit against
HEAD's own tree; `ruff` and `mypy` clean across 250 source files.

**Backlog:** 21 items stamped `shipped` with `closed-by`. **#275 is deliberately NOT among
them** — its code half shipped and its acceptance criterion is a measurement only a live set
can make, recorded as a comment on the issue rather than swept into the batch.

**Filed, not fixed:** #526 (`probe call` carries #508's string-typing hole, with a real design
question — the coercion gates on the property's current value and a call argument has none),
#528 (the return-position half of #524, an explicit non-goal of its parent), #529 (the render
records no fader values for #465's analysis to verify against). **#527 was filed and then
fixed** once the delegates finished and the shared-config change it needed was safe.

**Three operator sittings queued** in `operator-verification.md`, batched around one
re-vendor: the fingerprint-flipping MCP fixes plus #519's two Live class strings; #291's
`alien` witness and its verify tolerance; and #322's fence against a real wedged main thread.

**What the partition got wrong, for the next one to reuse:** the plan-time file map was right
about eleven chunks and wrong about one — #291 does not touch `push_execute.py`, so two chunks
were held apart for a collision that did not exist. Re-checking ownership at dispatch rather
than trusting the map cost minutes and bought a wave. The costlier miss was not in the map at
all: two delegates authored against the same wire contract in parallel, and nothing in the
partition could have caught it, because their FILES were disjoint. A shared contract is not a
shared file.
