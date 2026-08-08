# `push_cli execute` — design

**Status.** Design locked 2026-05-20; **IMPLEMENTED** (chunk W10-E2 — `src/hallucinote/sync/push_execute.py`). **HISTORICAL design record** — kept for the rationale; the shipped code is the source of truth. Unrelated to the arrangement/harmony/performance dimension work.

## Problem (measured)

The 2026-05-20 neon-feedback test session (93 bars, 29 session clips, 3,867
notes) measured the agent-side dispatch path as the v1.0 ceiling: every
`ableton_clip(action='create', notes=[…])` MCP call ships its full notes
array as inline JSON inside the agent's tool-use block, which the agent
then carries in its context for the rest of the session. ~500 KB across 29
calls for one song. The cost is the agent's own context budget, not MCP
round-trip latency.

Chunking by track doesn't help: the bytes flow through the agent either
way. The only fix is **moving the dispatch loop off the agent**.

## Architectural fact

`hallucinote_mcp/client.py:send()` is a public-ish surface: any Python
process can open a short-lived TCP socket to Live's Remote Script on
`DEFAULT_PORT` (9878) and ship a `wire.Request`. The MCP server uses this;
`push_cli` already imports from the same package. Bulk mechanical dispatch
of pre-planned mutator calls doesn't need an LLM in the loop.

The W10-E2 backlog entry ruled this out on a misread — *"Python-side MCP
client access (not available)"*. True but irrelevant: we don't need MCP
client access. We need Live client access, which is `hallucinote_mcp.client`.

## Design

Add `push_cli execute <session_id> (--song SLUG | --db PATH)` as a new
subcommand. The agent invokes it once via Bash; bytes never enter the
agent's context.

### Loop shape (pseudocode)

```
phases = push.plan_push_song(conn, song_id, session_id)
for phase in phases:
    plan = phase.plan_fn()         # fresh — sees latest ableton_links
    if not plan.calls:
        # PSH-ARRPROBE: two causes, two statuses.
        record phase as "incomplete" if plan.blocked_reasons else "skipped"
        continue
    results = []
    for call in plan.calls:
        req = wire.Request(tool=call.tool, action=call.args["action"],
                           params={k: v for k, v in call.args.items() if k != "action"})
        try:
            resp = client.send(req)
        except LiveConnectionError as exc:
            write_state(outcome="connection_lost", phase=phase.name, ...)
            return EXIT_CONNECTION_LOST
        results.append({
            "key":    call.key,
            "tool":   call.tool,
            "ok":     resp.ok,
            "result": resp.result if resp.ok else None,
            "error":  resp.error if not resp.ok else None,
        })
    # apply only writes for ok=True; failed entries are skipped internally
    apply_push_results(conn, results, session_id=session_id, actor="sync", ...)
    if any(not r["ok"] for r in results):
        write_state(outcome="partial", phase_halted=phase.name, ...)
        return EXIT_PARTIAL
write_state(outcome="ok", ...)
return 0
```

### Failure semantics (the contract)

1. **Connection lost → halt immediately.** `LiveConnectionError` from
   `client.send` means Live is unreachable. No point continuing.

2. **Per-call error → accumulate within the phase, halt at phase boundary.**
   Phases are real dependency boundaries (tracks before clips, clips before
   notes, devices before envelopes). Plowing past a broken phase manufactures
   cascading failures that obscure root causes. So: finish the current phase
   (so the LLM sees the full pattern of errors at once), then halt.

3. **No internal retry.** Re-running `execute` IS the retry — push is
   idempotent (W10-A), so already-applied rows skip on re-run. Internal
   retry hides intermittent bugs. Two deliberate, structural exceptions (not
   transient-error retries):
   - **Devices convergence re-plan (SYN-9F2L).** A device loaded *this* pass
     gets its `ableton_links` row at apply-time — *after* its parameters were
     planned — so its dialed params were unplannable in the primary pass. After
     a clean devices phase, the executor re-runs the devices planner once and
     dispatches only the NEW calls (already-dispatched keys are filtered out, so
     nothing re-sends). Without it the params silently never land: the next
     push's planner sees no DB change and skips the phase. This is a
     same-pass *convergence*, not a retry of a failed call.
   - **set_parameter wire-form fallback ladder (SYN-9F2L).** A `set_parameter`
     the handler refuses with a known, structural reason gets ONE re-shaped
     attempt: a `value_display` write refused as an enum retries with
     `value_type='enum'`; one refused for a missing display curve retries with
     the DB's `value_normalized`. A successful fallback is recorded on the
     result (`set_parameter_fallback`); a still-failing write halts the phase
     normally. One shape substitution, not open-ended retry.

4. **Apply runs per phase** so `ableton_links` updates before the next
   phase plans. Successful results land in the DB even when later calls
   in the same phase fail.

5. **No auto-clear.** If partial state is too tangled to trust, the
   operator invokes a separate `/ableton-push --clean` flow (or clears Live
   manually). `execute` never wipes Live state on its own.

6. **Plan-time hard error → halt the phase WITHOUT dispatching (SYN-6B4Q).**
   A planner can set `PushPlan.errors` when the DB describes something that
   can never be materialized in Live (e.g. a cue past the composed song
   length). The executor halts that phase up front — no calls go out, since
   nothing should half-apply — with the DB-grounded message in the errors
   file. This is distinct from a per-call failure (#2): there's no Live
   round-trip, and the message teaches the authoring fix, not a runtime
   symptom.

7. **Benign warning → surface, don't fail (SYN-6B4Q, SYN-9F2L).** Some
   outcomes are informational, not failures, and live in the `warnings` channel
   (outcome stays `ok`, exit 0) so they never read as a halt cause. Two
   sources feed it:
   - **Deferred cues (SYN-6B4Q).** A `cue_create_batch` run in
     `on_out_of_range='skip'` mode reports cues it DEFERRED (ahead of Live's
     current arrangement extent) in `skipped_out_of_range`; the call succeeded,
     and the deferred cues land on the next push once content covers them.
   - **Planner alerts (SYN-9F2L).** A planner records an operator-actionable,
     non-fatal warning via `PushPlan.alert()` (e.g. a params_dialed write with
     no writable form — "the dialed intent was NOT pushed"). The executor
     drains a plan's `alerts` (including the devices convergence re-plan's,
     deduped) into `warnings`. This is severity-, not phase-, scoped: any
     planner can raise one. It is DISTINCT from `PushPlan.notes` — the
     diagnostic channel ("no tempo_map rows; nothing to push", "not linked yet;
     rerun after apply") that the executor does NOT surface — and from
     `PushPlan.errors` (#6), which halt.

### Artifacts (the agent-facing contract)

`execute` writes two files next to the DB (i.e. inside `songs/<slug>/`):

**`.last-push-state.json`** — what happened, per phase:

```json
{
  "ts": "2026-05-20T22:14:08Z",
  "song_id": "...",
  "session_id": "...",
  "outcome": "ok | incomplete | partial | connection_lost",
  "phase_halted": "clips",          // null on ok
  "current_phase": null,            // PSH-5T9D: phase executing now; null at the terminal flush (as here — this is a finished, halted run)
  "scope": null,                    // PSH-2R7K: phase-targeting filter; null for a full run
  "phases": [
    {"name": "tempo_map",      "status": "ok",      "calls_ok": 1, "calls_failed": 0},
    {"name": "time_signature", "status": "skipped", "calls_ok": 0, "calls_failed": 0},
    {"name": "tracks",         "status": "ok",      "calls_ok": 8, "calls_failed": 0},
    {"name": "clips",          "status": "halted",  "calls_ok": 27, "calls_failed": 2},
    {"name": "mix",            "status": "pending", "calls_planned": 3},
    {"name": "arrangement",    "status": "incomplete", "calls_ok": 0, "calls_failed": 0,
     "blocked_reasons": ["arrangement: no Live arrangement probe for track '…' …"]}
  ],
  "errors_file": ".last-push-errors.json", // null when no errors
  "warnings": []                            // SYN-6B4Q: benign warnings (deferred cues); [] when none
}
```

Phase `status` values: `ok` (all calls succeeded), `skipped` (planner emitted
zero calls — idempotent re-push), `incomplete` (PSH-ARRPROBE: the planner
refused to plan work whose precondition it could not DETERMINE — a failed probe,
a missing link — and said why in `blocked_reasons`; may co-exist with successful
calls when only part of the phase was undeterminable), `halted` (one or more
calls failed OR the plan carried a hard error; phase did not necessarily
round-trip to Live), `pending` (phase not attempted due to upstream halt).

`incomplete` exists because collapsing "nothing to do" and "could not tell, so
did nothing" into one `skipped` let a first push report `OK — all 14 phases
completed` over an empty arrangement. An incomplete phase does NOT halt the run
(later phases still get their chance) but the terminal `outcome` becomes
`incomplete` and the exit code `EXIT_PARTIAL` — a push that left the song
un-materialized must never exit 0. `blocked_reasons` is present only on phases
that have them, so a reader can branch on the key alone.

**`current_phase` + per-phase flush (PSH-5T9D).** The state file is now written
**after every phase** (and once at the terminal state), not only at exit — so it is
**pollable mid-run** for phase-level progress. `current_phase` names the phase
executing at the moment of the flush (`null` at the terminal write). `execute` also
streams a per-phase start/finish line to **stderr** (stdout stays the single
parseable summary), with a distinctive heads-up for the multi-minute realtime
`performed_automation` phase so it isn't mistaken for a hang.

**`scope` + phase-targeting (PSH-2R7K).** `execute` accepts `--only PHASE`,
`--start-at`/`--from PHASE`, `--stop-after PHASE`, and `--resume` (continue from the
last run's `phase_halted`). `scope` records the filter (`{"only": …}` /
`{"start_at": …, "stop_after": …}`) or `null` for a full run, so a scoped run's state
file is never mistaken for a full push. Filtering is **by phase name** (order-agnostic
— it composes with a future phase reorder) and validated against the canonical phase
list (a typo teaches with the valid names). The coherence gate + idempotency are
unchanged: a scoped run is still safe because every phase's already-linked branch is a
no-op. `--start-at` does **not** satisfy dependencies — resuming at `clips` requires
`tracks` to have run in a prior pass (the operator's resume contract).

`warnings` (SYN-6B4Q) is an additive field: benign, non-failing messages
(e.g. cues deferred past Live's current arrangement extent). An `ok` push can
carry warnings with no errors file; readers default to `[]` when it's absent.

**`.last-push-errors.json`** — full forensics, written only when there are
errors:

```json
{
  "ts": "2026-05-20T22:14:08Z",
  "phase": "clips",
  "errors": [
    {
      "key": "clip:abc-123",
      "tool": "ableton_clip",
      "action": "create",
      "args_summary": {"track_index": 5, "clip_index": 2, "length_beats": 16, "notes_count": 8},
      "error": "RuntimeError: Couldn't create clip — slot occupied",
      "hint": "..."  // from wire.Response, when present
    }
  ],
  "grouped_by_error": [
    {"error_substring": "Couldn't create clip", "count": 2, "affected_keys": ["clip:abc-123", "clip:def-456"],
     "tool": "ableton_clip", "action": "create", "hint": null}
  ]
}
```

**Why `args_summary` not `args`.** Notes payloads are the whole point of
the design — we will NOT dump them inline in a file the agent reads.
`args_summary` strips large arrays into counts (`notes_count`, `breakpoints_count`)
and keeps small scalars (`track_index`, `clip_index`, `length_beats`, names).
Enough to diagnose; not enough to blow the agent's context.

### Stdout summary

A one-page text summary goes to stdout for the agent's tool-result block.
Small by design — full detail lives in the JSON files.

```
push_cli execute: PARTIAL — halted at phase 'clips' (4/10 phases ok)

  ✓ tempo_map       1/1 ok
  ✓ time_signature  skipped (nothing to push)
  ✓ tracks          8/8 ok
  ✓ returns         2/2 ok
  ✗ clips           27/29 ok, 2 failed → halted
  · mix             pending (3 calls planned)
  · devices         pending
  · envelopes       pending
  · arrangement     pending
  · cues            pending

errors: songs/neon-feedback/.last-push-errors.json
state:  songs/neon-feedback/.last-push-state.json

Halt cause (phase 'clips'):
  - ableton_clip.create: "Couldn't create clip — slot occupied" (2 calls)
    next: fix the cause in build.py / the snapshot, rebuild, then re-run execute (idempotent — applied rows skip)
```

The "Halt cause" block (PSH-4E2W) names cause + suggested next step per
grouped pattern so the agent acts without opening the errors file. The
`next:` line prefers the responder's `hint`; hint-less device.load
failures point at REQUIREMENTS.md, connection-class halts at the
Live-side checklist, anything else at the generic fix-rebuild-rerun loop.

### Exit codes

| Code | Meaning                               | Re-run behavior                          |
|------|---------------------------------------|------------------------------------------|
| 0    | All phases ok                         | n/a                                      |
| 1    | Partial — halted at phase boundary    | Idempotent re-run picks up where it left |
| 2    | Connection lost                       | Re-run after Live is reachable           |

Usage errors (bad args) follow argparse's default — the parser exits before
`execute_push` runs. We don't define a distinct exit code for that case;
ill-formed invocations are operator errors, not state errors.

### What stays on the MCP per-call path

`execute` is the bulk-push fast path. Anything that needs LLM judgment
stays on the existing per-call MCP dispatch:

- `probe-and-link` (decisions on unmatched tracks/returns)
- Confirmation gates (W12-C unmatched-list)
- Post-push UX message (W10-B)
- Interactive iteration (single clip edits, parameter nudges, A/B comparisons)

The agent's `/ableton-push` skill flows: probe-and-link via MCP → confirmation
gates via MCP → `push_cli execute` once → read state file → report.

## Implementation surface

- `src/hallucinote/sync/push_cli.py`:
  - New `_cmd_execute(args)` and `execute` subparser
  - Factor the dispatch loop into a separate function taking
    `send_fn: Callable[[Request], Response]` so tests can inject a fake
- `src/hallucinote/sync/push_execute.py` (new): the dispatch loop + state
  writers. Pure Python, no I/O outside the file writes + the `send_fn` calls.
- `tests/unit/sync/test_push_execute.py` (new): exercises happy path,
  per-call error accumulation, halt-at-phase-boundary, LiveConnectionError
  immediate halt, idempotent re-execute, state/errors file shape, and a
  mid-execute probe asserting per-phase link visibility.

## Out of scope

- Streaming subcommand protocol (bidirectional stdin/stdout). Not needed —
  one-shot execute with file output covers the bandwidth problem.
- Subagent harness. Not needed — `execute` removes the agent from the inner
  loop entirely.
- Resume-from-phase-N. Not needed — idempotent re-run is functionally
  equivalent and simpler to reason about.
- Auto-clear / clear-and-restart. Separate user-invokable path, future
  backlog if the diagnose-and-fix flow proves insufficient.
- Live-side changes. The wire protocol and Remote Script are untouched.

## Tests (full list)

1. **Happy path** — synthetic 3-phase plan, all calls ok → state shows
   all ok, no errors file.
2. **Per-call error in middle phase** — phase runs to completion, errors
   collected, halt before next phase, downstream phases marked pending.
3. **Multiple errors same phase** — grouped-by-error block shows the pattern.
4. **`LiveConnectionError`** — immediate halt, state shows `connection_lost`,
   no apply for that phase.
5. **Idempotent re-execute** — fake plan returns zero calls on second pass
   (simulating already-applied state); state shows all phases skipped.
6. **Apply runs per phase** — phase 1 results land in DB before phase 2
   plans (verified by inspecting `ableton_links` between phases via a side
   probe in the test).
7. **`args_summary` redaction** — a call with a 100-note payload produces
   an error whose `args_summary` carries `notes_count: 100` and no `notes`
   key.
8. **Exit codes** — assert each of {0, 1, 2} for the three outcomes.
