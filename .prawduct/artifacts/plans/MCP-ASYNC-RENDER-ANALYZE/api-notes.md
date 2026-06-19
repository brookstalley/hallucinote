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
  `dispatcher.py` with `context=None`, never sent to Live). Its handlers +
  action registrations live in the **`server_side/`** package
  (`server_side/analysis.py`, `server_side/analysis_actions.py`) — moved there by
  #183 (MCP-7F2K) to stay out of `_FINGERPRINT_PATHS`. So the analyze
  `start`/`status` actions added here do NOT flip the server fingerprint or force
  a re-vendor (unlike render's Live-side `start`/`status`). The handlers reach UP
  into the fingerprinted `handlers/jobs.py` for the shared registry — the allowed
  `server_side → handlers` import direction (the isolation invariant only forbids
  the reverse).

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

### The residual Live-gated check (build-plan Done-when #2)

Done-when #2 has two axes. The **server-event-loop** axis (a `status` long-poll
freezing the server) is closed in code by the Chunk-2 dispatch fix (async tool
wrapper + `anyio.to_thread`; see "Dispatch fix" below). What remains Live-gated
is the **Live-main-thread** axis: confirm on real Live that a detached render
worker holding the transport does **not** block a concurrent unrelated call —
`ableton_session(action='info')` issued mid-render must return promptly, not hang
to timeout. `run_on_main` is a FIFO onto the main-thread queue, so an `info` read
should interleave between the worker's polls — but the realtime render load is
the unknown only Live settles. Queued in `operator-verification.md`.

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
  `start`/`status` for large ones — **Chunk 2 set the threshold (below)**.
- Single job at a time per kind is sufficient for Chunk 1; a concurrent `start`
  returns `{busy, job_id}` rather than queueing.

### Chunk 2 — analyze threshold + eta + substrate centralization (resolved 2026-06-18)
- **Threshold = documented GUIDANCE, not an auto-cutoff.** The synchronous
  `analyze` stays the one-call fast path; the agent picks `start`/`status` when
  the captures dir has many surfaces (full-band: lots of tracks + returns) or
  the song declares many sections (each adds masking/timing/cross-rhythm
  passes) — i.e. anytime the pipeline might exceed the 60s tool-call timeout.
  Surface-count and declared-section-count are the two real cost drivers (NOT a
  single wall-clock SLA — that would be false precision without profiling). The
  guidance lives in the `analyze` + `start` action help/tips (the in-band
  teaching surface). An auto-detecting threshold (sync refuses + redirects when
  it predicts >60s) was considered and deferred to Chunk 3's disposition step —
  Chunk 2 ships both paths + the guidance.
- **`eta_seconds` is None for analyze** — runtime is surface-count × audio-length
  × enabled-passes, with no realtime anchor like render's beats/tempo; reporting
  a fabricated number would be a guess, so the handle omits it honestly.
- **`status` done payload maps analyze_handler's native return into the
  locked-in `{report, report_path}` shape**: `report` is the same lightweight
  bundle the synchronous `analyze` returns (summary + finding_count +
  schema_version + analysis_code, incl. the `stale` flag); the full per-stem
  MixReport JSON stays on disk at `report_path`. (The `status_result` analyze
  branch was unexercised after Chunk 1 — no analyze jobs existed — so Chunk 2 is
  the first to lock it.)
- **Substrate centralized in `jobs.py`**: the 45s long-poll window
  (`DEFAULT_STATUS_LONG_POLL_S`) and the daemon-worker spawn (`spawn_daemon(fn,
  *, name)`) moved out of render.py so render + analyze share one definition —
  the long-poll is "one knob, not two that drift". render's worker still
  marshals onto Live's main thread; analyze's is a plain server-process thread
  (pure DSP, no Live), the keystone-risk-free half.

### Dispatch fix — async tool wrapper (resolved 2026-06-18, Chunk-2 Critic finding)

**The long-poll froze the whole server.** A Chunk-2 Critic review found (and we
verified in `mcp==1.26.0`) that FastMCP runs a **synchronous** tool function
INLINE on the event-loop thread — `func_metadata.call_fn_with_arg_validation`
does `return fn(**args)` for a sync fn, no `to_thread`. Our `server.py` tool
`wrapper` was sync, so a `status` long-poll (`terminal_event.wait(45)`, or
render's 60s socket read) **blocked the entire MCP event loop** for the wait
window — every concurrent tool call queued behind it. This violated the design's
hard requirement (api-notes / build-plan Done-when #2: *a concurrent unrelated
call must not hang behind a running job*). The single-agent `start→poll→poll`
flow never noticed (the polling agent is the sole caller and intends to wait),
but the guarantee was hollow.

**Fix:** make the `server.py` tool wrapper `async def` and run the synchronous
`handle_tool_call` under `anyio.to_thread.run_sync` (FastMCP **awaits** an async
tool, keeping the loop free). It covers ALL 13 tools, so it also fixes render's
`status` (Chunk 1) — the loop no longer blocks on its socket read. De-risked
before adopting: `client.send` opens a **fresh socket per call** (no shared-socket
race under true concurrency) and Live's `run_on_main` already FIFO-serializes
main-thread touches, so concurrent forwarded calls stay correct. The busy guard
became a real race once dispatch is concurrent, so the `active()`-then-`create()`
check was replaced with an atomic `JobRegistry.create_if_idle()` (one lock
acquisition; exactly one of N concurrent starts claims the slot). Proven headless:
`test_status_longpoll_does_not_block_concurrent_tool_calls` (help served *during*
a status long-poll), `test_tool_wrappers_are_async_*`, and a 32-thread
`create_if_idle` atomicity test.

**Forward-note — the next ceiling is `anyio`'s thread limiter, not the event
loop.** `anyio.to_thread.run_sync` draws from a default capacity of **40**
worker threads. Each in-flight `status` long-poll occupies one thread for up to
~45s, so the 41st *concurrent* tool call would queue behind the busy threads
(the loop itself stays free — this is a thread-pool bound, not the inline-block
bug this section fixes). Irrelevant under the single-agent
`start`→poll→poll pattern these actions serve (concurrency ~2–3), but if
multi-agent rendering/analysis ever lands, raise the limiter
(`anyio.to_thread.current_default_thread_limiter().total_tokens`) rather than
re-architecting — consistent with keeping concurrency at the app/server layer,
not baked into the wire shape.
