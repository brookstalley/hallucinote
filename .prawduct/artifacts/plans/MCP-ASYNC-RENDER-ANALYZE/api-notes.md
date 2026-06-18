# Chunk 1 verify-api findings + persisted-shape lock-in

**Status:** verify-api complete (resolved from code, 2026-06-18 — no Live needed
for the A/B decision; one residual Live check remains, see below). This is the
build plan's Chunk-1 Done-when #0. Read before coding the substrate.

## Process topology (confirmed by reading the code)

- **`ableton_render(render)` runs Remote-Script-side, inside Live.** The handler
  (`handlers/render.py:render_handler`) drives the transport and reads
  `current_song_time` through `context.run_on_main(...)` throughout — it is
  `needs_remote` (forwarded over TCP), executed against the RS's
  `LiveContext`. The MCP server process only forwards and blocks on
  `client.send` (render's socket read-timeout is `None` —
  `client._READ_TIMEOUTS[("ableton_render","render")]`). The 60s false-failure
  is the **outer Claude Code↔server tool timeout**, not the inner socket.
- **`ableton_analysis(analyze)` runs in the MCP server process** (pure DSP,
  numpy, lazy-imported engine; `runs_server_side=True`, dispatched at
  `dispatcher.py` with `context=None`, never sent to Live).

⇒ **Two registries, one per process.** render-job state must live in the RS
process; analyze-job state in the server process. They share the same
`JobRegistry` *class* but are distinct process-local singletons. A `status`
poll is routed to the same tool that started the job, so it always reaches the
right process's registry.

## A-vs-B decision: **mechanism A (detached worker) — VIABLE**

The keystone risk was whether a worker spawned by `start()` can keep marshalling
onto Live's single main thread *after the start request returns*.

**`run_on_main` (`remote_script/dispatch.py:98`) is thread-agnostic.** It
enqueues `fn` onto Live's main-thread queue via `schedule_message(0, fn)` (a
Control-Surface primitive alive for the whole session, **not** tied to a
request) and blocks the *calling* thread on a `threading.Event` until Live's
main loop drains the queue. So:

- A detached daemon worker thread can call `run_on_main` indefinitely after the
  originating request returns — the scheduler outlives the request.
- The existing `_wait_for_capture` loop **already** polls transport via
  `run_on_main` *during playback* and refreshes `status.json` each poll — proof
  the main-thread queue drains while the transport rolls. Moving that exact loop
  onto a worker thread changes nothing it depends on.
- Job state persists across MCP calls in a **process-global registry** in the RS
  process (one process serves every client connection; each connection already
  runs on its own daemon thread via `RemoteScriptServer._handle_client`).

**Mechanism B (agent-driven long-poll) stays as the fallback** — and the
long-poll `status` action is built either way, so selecting B later needs no
redesign, only deleting the worker spawn.

### The ONE residual Live-gated check (build-plan Done-when #2)

Confirm on real Live that a detached render worker holding the transport does
**not** block a concurrent unrelated call: `ableton_session(action='info')`
issued mid-render must return promptly, not hang to timeout. `run_on_main` is a
FIFO onto the main-thread queue, so an `info` read should interleave between the
worker's polls — but the realtime render load is the unknown only Live settles.
Queued in `operator-verification.md`.

## Persisted shape — LOCK-IN (every future poller depends on this)

### `status.json` (on disk, written by the render worker — already exists)
Unchanged from today; the worker keeps writing it as the crash-resilient
heartbeat and terminal marker:
```
{ "state": "running" | "done" | "error",
  "current_beat": float, "target_beat": float, "frames_received": int }
```
(Terminal `error` carries `"error": str`; `done` is written after the manifest.)

### Job record (in-memory registry — the new lock-in)
```
job_id:           str   # "<kind>-<uuid4 hex[:12]>", opaque & unique
kind:             "render" | "analyze"
state:            "running" | "done" | "failed"   # the wire vocabulary
created_at:       str   # ISO-8601 UTC (server/RS clock)
updated_at:       str   # ISO-8601 UTC
dir:              str   # captures_dir (render) | report_dir (analyze), absolute
eta_seconds:      int | None
expected_stop_beat: int | None   # render only
progress:         dict  # render: {current_beat,target_beat,frames_received}
                        # analyze: {stage, ...} (coarse)
result:           dict | None    # set on state=done
error:            str  | None     # set on state=failed
```
Note the **state vocabulary is `running|done|failed`** at the registry/wire
layer; the on-disk `status.json` uses `error` (legacy) — the worker maps
`error→failed` when it lands the terminal record. Don't leak `error` as a
*state* onto the wire.

### `start` result (returned immediately)
```
{ job_id, kind, state: "running",
  captures_dir | report_dir,
  eta_seconds, expected_stop_beat?,         # render
  poll: "<instruction text>" }              # tells the agent how to poll
```

### `status(job_id)` result (long-polls ~45s, then returns)
```
{ job_id, kind, state,
  progress: {...},
  captures_dir | report_dir,         # the dir, always (symmetric with start)
  manifest?, manifest_path?,         # render, state=done
  report?,   report_path?,           # analyze, state=done (summary; full JSON on disk)
  error?: str }                      # state=failed
```

`status` **long-polls**: it waits internally up to ~45s for the state to leave
`running` before returning, so the agent loop is a handful of calls, not a busy
spin. That 45s is sized **under the 60s per-tool-call timeout** set in
`.claude-plugin/plugin.json` (the very limit that makes the synchronous render
false-fail), leaving ~15s for forward + serialize round-trip; the `status`
socket read-timeout (`client._STATUS_READ_TIMEOUT`, 60s) sits just above the
long-poll so the socket never severs the wait. To widen the window, raise the
long-poll, the socket timeout, AND plugin.json's `timeout` together. An unknown
`job_id` returns a structured error naming the most recent known jobs. A
concurrent unrelated MCP call must not block behind a running job (Done-when #2).

## Disposition (build-plan open assumptions — building on the stated defaults)
- **Retire synchronous `render`** in favor of `start`/`status` (no back-compat
  to the false-failure path) — finalized in Chunk 3.
- **Keep synchronous `analyze`** as a fast path for small captures; add
  `start`/`status` for large ones — Chunk 2 sets the threshold.
- Single job at a time per kind is sufficient for Chunk 1; a concurrent `start`
  returns `{busy, job_id}` rather than queueing.
