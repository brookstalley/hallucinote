# `push_cli execute` — design

**Status.** Design locked 2026-05-20. Implementation chunk W10-E2.

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
        record phase as "skipped (idempotent)"
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
   retry hides intermittent bugs.

4. **Apply runs per phase** so `ableton_links` updates before the next
   phase plans. Successful results land in the DB even when later calls
   in the same phase fail.

5. **No auto-clear.** If partial state is too tangled to trust, the
   operator invokes a separate `/ableton-push --clean` flow (or clears Live
   manually). `execute` never wipes Live state on its own.

### Artifacts (the agent-facing contract)

`execute` writes two files next to the DB (i.e. inside `songs/<slug>/`):

**`.last-push-state.json`** — what happened, per phase:

```json
{
  "ts": "2026-05-20T22:14:08Z",
  "song_id": "...",
  "session_id": "...",
  "outcome": "ok | partial | connection_lost",
  "phase_halted": "clips",          // null on ok
  "phases": [
    {"name": "tempo_map",      "status": "ok",      "calls_ok": 1, "calls_failed": 0},
    {"name": "time_signature", "status": "skipped", "calls_ok": 0, "calls_failed": 0},
    {"name": "tracks",         "status": "ok",      "calls_ok": 8, "calls_failed": 0},
    {"name": "clips",          "status": "halted",  "calls_ok": 27, "calls_failed": 2},
    {"name": "mix",            "status": "pending", "calls_planned": 3}
  ],
  "errors_file": ".last-push-errors.json"  // null when no errors
}
```

Phase `status` values: `ok` (all calls succeeded), `skipped` (planner emitted
zero calls — idempotent re-push), `halted` (one or more calls failed; phase
ran to completion before halt), `pending` (phase not attempted due to upstream
halt).

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
    {"error_substring": "Couldn't create clip", "count": 2, "affected_keys": ["clip:abc-123", "clip:def-456"]}
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
  ✓ time_signature  skipped (idempotent)
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

Top error patterns:
  · "Couldn't create clip — slot occupied" (2 occurrences)
```

### Exit codes

| Code | Meaning                               | Re-run behavior                          |
|------|---------------------------------------|------------------------------------------|
| 0    | All phases ok                         | n/a                                      |
| 1    | Partial — halted at phase boundary    | Idempotent re-run picks up where it left |
| 2    | Connection lost                       | Re-run after Live is reachable           |
| 64   | Usage error (bad args)                | Fix args                                 |

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
- `tests/unit/test_push_execute.py` (new): exercises happy path, per-call
  error accumulation, halt-at-phase-boundary, LiveConnectionError immediate
  halt, idempotent re-execute, state/errors file shape.

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
