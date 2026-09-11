---
lifecycle: completed
archived: 2026-09-08
maintained: false
---

> **Archived — no longer maintained.** This plan records what was built, not what will be. Do not edit it to reflect later changes; write those where they are true.

# FRICTION-BASKET — Build Plan (PSH-4E2W + WFL-7Q2N + DOC-5W8B)

The 2026-06-09 repo-wide review's "daily-loop friction basket": three small `stage: ready`
items that each tax every song's push/pull/render loop. One branch
(`feature/daily-loop-friction`), one chunk per item, one PR into `develop`
(gitflow — pass the develop base to `/prawduct:critic` and the PR reviewer,
per `feedback_pr_gate_base_is_develop`).

## Requirements Confidence: **Medium**

- **Problem (one sentence):** Every push failure forces JSON spelunking, every CLI call
  demands a remembered numeric session ID, and REQUIREMENTS.md silently drifts after
  device-changing pushes.
- **Success (one sentence):** A failed push prints a human-readable halt cause + next
  step; push/pull/render resolve the session without a numeric ID when unambiguous; a
  device-changing push leaves REQUIREMENTS.md regenerated in the same flow.
- **Out of scope (one sentence):** Any change to what the push *does* on failure
  (halt semantics, phase ordering), to the sessions schema, or to REQUIREMENTS.md's
  content format — this basket is surfacing/wiring only.

**Why Medium, not High:** PSH-4E2W and DOC-5W8B are pinned (the code paths and signals
are confirmed firsthand); WFL-7Q2N's *song-context* source is inferred, not confirmed.

**Open assumptions / unknowns:**

- `[ASSUMPTION: WFL-7Q2N song context comes from an optional --song slug arg (resolved
  like compat.py's resolve_song_dir); when neither session_id nor --song is given and
  exactly one song has sessions, use it — otherwise list candidates and exit with
  guidance | MED impact | user can correct]`
- `[ASSUMPTION: with multiple sessions for a song, "most recent" = highest ableton_sessions
  rowid, and we choose it while echoing the choice + alternatives (info, not error) —
  "unambiguous" means a well-defined ordering exists, not "exactly one session" | MED
  impact | user can override]`
- `[ASSUMPTION: DOC-5W8B regen fires at the CLI layer (push_cli, after execute_push
  returns) rather than inside the executor, keeping sync/push_execute.py free of doc
  side-effects | LOW impact | user can override]`

**What would raise confidence:** one confirmation on the WFL-7Q2N resolution rules
(assumptions 1–2); the builder proceeds on them as defaults and they're cheap to adjust.

## Status

- [x] Chunk 01: PSH-4E2W — human-readable push-halt summary
- [x] Chunk 02: WFL-7Q2N — session auto-discovery
- [x] Chunk 03: DOC-5W8B — auto-regen REQUIREMENTS.md after device-changing push
Context: All three chunks done 2026-06-10. 03: `compat.regen_requirements`
extracted; `push_cli execute` regenerates after a devices phase with applied
calls (--song), prints a stale-notice on --db-only, degrades regen failures to
a notice (waivered broad catch) so the push exit code survives; halted-push
regen pinned by test. Critic final passed (3 warnings resolved: broad-catch
contract, halted-push test, docs/collaboration.md). Remaining: cumulative
Critic vs develop + PR; backlog shipped-flips post-merge.

## Scaffolding

Existing project — no scaffold work. Tests run via `pytest` (config in `pyproject.toml`,
`tests/unit/sync/` is the home for all three chunks' tests). Verification beyond tests:
drive `push_cli` against a real song DB (see per-chunk Done-when).

---

## Chunk 01 — PSH-4E2W: failed push prints cause + next step

Today `format_summary` (`src/hallucinote/sync/push_execute.py::format_summary`) prints
only the errors filename + top error *patterns*; the agent then has to open
`.last-push-errors.json`. Carry the top error records (already in scope in
`execute_push` before the file write, same redaction as the JSON payload) into
`ExecuteResult`, and render each as a one-line cause + suggested next step (e.g. a
device-load failure → "not installed — see REQUIREMENTS.md"; fallback: the error
message verbatim). The errors file still gets written and referenced for full detail.

- **Type:** code
- **Deliverables:** `src/hallucinote/sync/push_execute.py` (`ExecuteResult` + summary
  rendering); a wording pass on the push skill doc so it relies on the summary instead
  of instructing a JSON read (locate by grepping `skills/` for `last-push-errors`).
- **Tests:** unit tests pinning that a failing `execute_push` result formats to output
  containing the halt cause text and a next-step line; redaction still holds
  (no large note-lists in the summary).
- **Acceptance criteria:** the verifiable signal from the backlog item — a failed push's
  output contains a human-readable halt summary (cause + suggested next step) without
  reading the JSON file.
- **Done when:**
  1. Acceptance criteria met and tests pass
  2. `/prawduct:critic` run (inference: chunk) and blocking findings resolved
  3. Committed and chunk marked `[x]` in Status

## Chunk 02 — WFL-7Q2N: session-ID auto-discovery, default to most recent

Add a read-side query `get_ableton_sessions_for_song(conn, song_id)` in
`src/hallucinote/db/queries.py` (read, not a mutator — mutator discipline applies to
writes only), and a shared resolver (new `src/hallucinote/sync/session_resolve.py`)
implementing: explicit session_id wins → else resolve song context (see plan
assumptions) → exactly one session: use it → several: use most recent and echo the
choice + alternatives → none: exit with guidance. Thread the resolver through **every
CLI subcommand that currently requires a positional/required session id** in
`src/hallucinote/sync/push_cli.py` and the pull/render entry points — scope by the
pattern ("subcommands taking session_id"), not by line numbers; make the arg optional.

- **Type:** code
- **Deliverables:** new `src/hallucinote/sync/session_resolve.py`;
  `src/hallucinote/db/queries.py`; `src/hallucinote/sync/push_cli.py` (+ pull/render
  CLI entry points found by the pattern sweep).
- **Tests:** unit tests for the resolver matrix (explicit id / one session / several /
  none / unknown song); a CLI-level test that `push_cli phases` resolves without an id.
- **Acceptance criteria:** the verifiable signal — push/pull/render flows resolve the
  session without the user supplying a numeric ID when an unambiguous candidate exists;
  ambiguity produces a listed, actionable message, never a guess that isn't echoed.
- **Done when:**
  1. Acceptance criteria met and tests pass
  2. `/prawduct:critic` run (inference: chunk) and blocking findings resolved
  3. Committed and chunk marked `[x]` in Status

## Chunk 03 — DOC-5W8B: auto-regen REQUIREMENTS.md after a device-changing push

Extract the body of `_cmd_write_requirements` (`src/hallucinote/sync/compat.py`) into a
callable `regen_requirements(song) -> Path` (CLI command becomes a thin wrapper). In the
`push_cli` execute flow, after `execute_push` returns, if the devices phase applied ≥1
successful call, invoke the regen and print one line ("REQUIREMENTS.md regenerated").
A halted push that still applied device changes regenerates too — the doc reflects
current set state, not push success.

- **Type:** cumulative-final
- **Deliverables:** `src/hallucinote/sync/compat.py` (extraction);
  `src/hallucinote/sync/push_cli.py` (post-execute hook).
- **Tests:** unit test that a result whose devices phase applied changes triggers regen
  (and one that a no-device-change push doesn't); extraction keeps the manual command's
  behavior pinned.
- **Acceptance criteria:** the verifiable signal — a push that changes the device set
  leaves REQUIREMENTS.md regenerated in the same flow.
- **Done when:**
  1. Acceptance criteria met and tests pass
  2. `/prawduct:critic` run (inference: final) and blocking findings resolved
  3. `/prawduct:critic cumulative` against `develop...HEAD` clean — the `/prawduct:pr
     create` gate (base: develop)
  4. Committed, chunk marked `[x]` in Status; backlog pass: PSH-4E2W / WFL-7Q2N /
     DOC-5W8B → `status=shipped` via `/prawduct:backlog` once the PR merges

## Early Feedback Milestone

**Milestone chunk:** 01 — the next real push failure already reads better.

## Governance Checkpoints

**Commit & PR cadence:** commit per chunk after its Critic passes; one PR into `develop`
after Chunk 03's final + cumulative reviews pass (`/prawduct:pr`, base develop).

- After Chunk 01: confirm the ExecuteResult shape extension didn't leak redacted payloads.
