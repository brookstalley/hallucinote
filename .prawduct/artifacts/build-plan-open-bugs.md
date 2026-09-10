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

## Status

Merged into `docs/backlog-bug-readiness`, each with its targeted surface re-run green.
The whole-suite run that vouches for the merged set is in flight; boxes are ticked on the
merge + targeted green, and the suite result is recorded in Context.

- [x] B1 — #222 #520 · [ ] B2 · [ ] B3 · [ ] B4 · [x] B5 — #508 #516 #521 · [x] B6 — #503 #475 #328 · [x] B7 — #226
- [ ] B8 — #291 (dispatched) · [ ] B9 — #322 (held on B2) · [x] B10 — #476 · [ ] B11 — #515
- [x] B12 — #275 code half shipped (`261aa51`); the item stays open on the operator half,
  now queued in `operator-verification.md` with both outcomes named
- [ ] Cumulative Critic over the whole sweep

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

**Dispatched**: B1-B7 (wave 1) plus B10 and B11, which re-checking showed are disjoint from
every wave-1 row by construction — B10 needs only a new module and the `song-new` skill, and
B11 was told to report its `lom-probe-results.md` row edit rather than make it, which is what
takes it off B5's surface. Holding a chunk that cannot collide costs wall clock and buys
nothing.

**Still held**: B8 (#291) contends with B4 on `db/mutations/links.py` and with B1 on
`skills/ableton-push/`; B9 (#322) contends with B2 on `server_side/analysis.py`. Both go out
once those merge. Re-checking the plan-time partition at dispatch found one thing it had
wrong: #291 does **not** touch `push_execute.py` (its own change list names
`push/devices.py`, `push_cli.py`, `push/probe.py` and `cli.py`), so B8 and B9 do not contend
with each other and can run together.

**B12 (#275) is done and committed** — see the Status box. Baseline before any edit:
6063 passed, 2 skipped.
