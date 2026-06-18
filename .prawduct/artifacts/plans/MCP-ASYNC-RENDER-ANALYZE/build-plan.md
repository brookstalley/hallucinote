# Build Plan — Async long-running MCP actions: render + analyze (MCP-9R3T + MCP-5N8K)

**Scope:** make `ableton_render` and `ableton_analysis(analyze)` survive the MCP
call timeout via a **start + poll** pattern, so an agent is never left blind to a
render/analysis that is still running server-side.

**Backlog:** MCP-9R3T (async render) · MCP-5N8K (async analyze). This plan
supersedes the *mechanism* both items were filed with (see Design Pivot).

**Requirements Confidence: Medium.** The pattern is verified-feasible and most of
the status plumbing already exists; the residual unknowns are a Live-threading
question and the exact process topology — both closed by Chunk 1's spike against
real Live (the thin vertical slice). Listed under Open Assumptions.

---

## Design Pivot — what the research changed (READ FIRST)

Both backlog items were filed assuming **"notify-when-done via the host
background-task channel"** (the way Claude Code surfaces a backgrounded Bash
completion). **That is infeasible in Claude Code today** — verified against
current docs + an open bug, not recalled:

- There is **no async / background / wake-on-done concept for MCP tools** (unlike
  Bash's `run_in_background`). A tool call is request→response; the agent blocks
  until the single response.
- MCP **progress notifications are received but do NOT reset/extend** the
  tool-call timeout (Claude Code bug #58687).
- The tool-call timeout is a **client-side, transport-agnostic wall-clock limit**
  (`timeout` ms per server in `.mcp.json`; default very large, but the work here
  is genuinely unbounded). Confirmed identical across **stdio, HTTP+SSE, and
  Streamable HTTP** — so changing transport changes nothing (HTTP/SSE even
  imposes a 60s first-byte minimum). **Transport is considered & rejected.**

**Feasible design = start + poll, where the `start` result *instructs the agent*
how to poll** (user-confirmed direction):

1. **`start`** runs the work server-side and returns **immediately** with a job
   handle — small payload, never holds the socket for the realtime/DSP duration:
   `{ job_id, captures_dir|report_dir, eta_seconds, expected_stop_beat? }` plus
   **instruction text** in the result: *"started; poll `<tool>(action='status',
   job_id=…)`; it long-polls ~Ns and returns `{state}`; repeat until
   `state ∈ {done, failed}`."*
2. **`status(job_id)`** returns `{ state: running|done|failed, progress,
   captures_dir|report_path, manifest?|report?, error? }`. It **long-polls** —
   waits internally up to ~45s (comfortably under the tool timeout) before
   returning `running` — so the agent's loop is a handful of calls, not a busy
   spin. A concurrent unrelated call (e.g. `ableton_session(info)`) must **not**
   hang behind a running job.
3. Raising the per-server `.mcp.json` `timeout` is a **complementary lever** (lets
   the long-poll window be generous), **not** the fix — render is unbounded.

This pattern is **transport-agnostic and notification-free**: it depends only on
two synchronous request→response calls, which every transport supports.

---

## What already exists (grounding — confirmed by reading the code)

- `client.py` `_READ_TIMEOUTS`: `("ableton_render","render"): None` — the
  **server↔Live socket is already unbounded** for render. The false-failure today
  is the **outer Claude Code↔server** tool timeout cutting the agent off while the
  server finishes and writes `manifest.json`.
- `render.py:_wait_for_capture` is **already a poll loop** that **already writes a
  `status.json` heartbeat** each poll (`state/current_beat/target_beat/
  frames_received` via `_write_status_json`). The status *data* exists; what's
  missing is a `start` that backgrounds it + a `status` **action** to read it over
  the wire + the agent-instruction text.
- `analysis.py:analyze_handler` is **pure DSP** (numpy, lazy-imported engine), runs
  in the **MCP server process**, no Live — so backgrounding it is low-risk.

## Keystone risk (de-risked in Chunk 1, against REAL Live)

Can Live's **single-threaded** Remote Script run a **detached background render
job** — a worker that keeps marshalling onto Live's main thread (`run_on_main`) to
poll transport — **after the `start` request has returned**, and serve `status`
polls against persistent job state?

- **Mechanism A (server-side worker):** `start` spawns a detached worker that runs
  the existing `_wait_for_capture` loop + writes job state; `status` reads it.
  Cleanest agent UX, but leans on Live's threading.
- **Mechanism B (agent-driven long-poll, fallback):** `start` only *arms*
  (play+record) and returns; **each `status` call** does a bounded `run_on_main`
  poll of transport+frames (≤~45s) and returns `running|done`. The loop lives in
  the **agent** (driven by `status` calls), not a server worker — more robust to
  Live's threading, slightly chattier. The long-poll `status` we want anyway makes
  B a natural fallback.

Chunk 1's `verify-api` spike picks A or B on evidence. **Analyze has no such risk**
(pure DSP thread in the server process).

---

## Open assumptions / unknowns (vetoable)

- `[ASSUMPTION: a detached worker in the Remote Script can marshal onto Live's main thread after start() returns | HIGH | Chunk-1 spike confirms A; else fall back to B (agent-driven long-poll) — no redesign, the long-poll status is built either way]`
- `[ASSUMPTION: render_handler runs in the Remote Script and analyze in the MCP server process; a job registry can persist across MCP calls in the right process | HIGH | Chunk-1 verify-api confirms topology before any handler code]`
- `[ASSUMPTION: render's synchronous action is RETIRED in favor of start/status (no back-compat to the false-failure path) | MED | user can override to keep sync render alongside]`
- `[ASSUMPTION: synchronous analyze is KEPT as a fast path for small jobs; start/status added for large ones | MED | user can override to always-async for consistency]`
- `[ASSUMPTION: a single job at a time per kind is sufficient (no concurrent renders); concurrent start returns {busy, job_id} | LOW | confirm in Chunk 1]`

---

## Chunks

### Chunk 1 — Keystone: job substrate + `ableton_render` start/status (de-risk on real Live)

> **Status 2026-06-18 — substrate BUILT (no-Live), on `feat/async-render-analyze`.**
> Done-when **#0** (verify-api → `api-notes.md`, mechanism **A** selected),
> **#1** (`handlers/jobs.py` JobRegistry + `render_start_handler` /
> `render_status_handler` reusing `_wait_for_capture` + `_write_status_json`;
> `start`/`status` actions registered; server-side absolutize extended to
> `start`; `status` socket read-timeout raised above the long-poll), and **#3**
> (25 unit tests via a Live seam; full suite green) are DONE. **#2** is
> design-confirmed (per-request sockets + thread-agnostic `run_on_main`) but its
> Live confirmation, plus **#4** (real-Live operator-verify), are QUEUED in
> `operator-verification.md` (needs an attended Live session + a re-vendor — the
> wire-shape change flips the fingerprint). **#5** (Critic + commit) in progress.
> Chunk 2 (analyze) reuses this substrate next.

The thin vertical slice that proves the **entire** architecture (job registry →
`start` returns immediately → `status` long-poll → agent-instruction text) on the
**hardest** case (render + single-threaded Live).

- **Type:** code
- **Foreign API:** ableton-live-mcp
- **Critic mode:** final  *(override — architectural keystone; later chunks build on it)*
- **Visual change:** yes  *(agent-facing `start`/`status` result shape + Live transport behavior)*
- **Done when:**
  0. verify-api — read the Remote Script + MCP server **dispatch** to confirm (a)
     process topology: where `render_handler` runs and where job state can persist
     across MCP calls; (b) whether mechanism **A** (detached worker → `run_on_main`)
     is viable on real Live, else select **B** (agent-driven long-poll). Capture
     findings in new `.prawduct/artifacts/plans/MCP-ASYNC-RENDER-ANALYZE/api-notes.md`.
  1. A minimal **job registry** (`job_id → {state, progress, dirs, error}`) in the
     correct process, backed by the existing `status.json` for cross-call/crash
     reads. `ableton_render(action='start', …)` → returns immediately with
     `{job_id, captures_dir, eta_seconds, expected_stop_beat}` + the poll
     instruction text; `ableton_render(action='status', job_id)` long-polls and
     returns `{state, progress, captures_dir, manifest?, error?}`. Reuse
     `_wait_for_capture` + `_write_status_json`; do not reimplement the wait.
  2. A running render does **not** block an unrelated MCP call (concurrent
     `ableton_session(info)` returns rather than hanging to timeout) — or, if
     Live's LOM forbids true concurrency, `start`/concurrent calls return an
     instant `{busy, job_id}` instead of hanging.
  3. Acceptance criteria met and tests pass (unit: registry state machine,
     start-returns-fast, status long-poll transitions, instruction-text shape —
     with a Live fake/seam mirroring the **verified** API).
  4. **Real-Live operator verification** (entry in `operator-verification.md`):
     render a real multi-minute song → `start` returns in < ~3 s → `status` polls
     show the beat advancing → terminal `done` with a well-formed `manifest.json` →
     no false failure; concurrent `session(info)` mid-render does not hang.
  5. `/prawduct:critic` (final) run; blocking findings resolved. Committed; chunk
     marked [x].
- **Governance checkpoint:** architecture validation — confirm A-vs-B and the
  topology before widening to analyze.

### Chunk 2 — `ableton_analysis(analyze)` start/status on the same substrate

Widen the proven pattern to analysis (low risk — pure DSP in the server process,
no Live threading).

- **Type:** code · **Critic mode:** chunk
- **Done when:**
  1. `ableton_analysis(action='start', …)` backgrounds the DSP in a server thread
     and returns `{job_id, report_dir, eta_seconds}` + poll instruction text;
     `ableton_analysis(action='status', job_id)` long-polls → `{state, progress,
     report_path?, error?}`. Reuse the Chunk-1 job registry + instruction
     convention.
  2. Disposition settled (Open Assumption): keep synchronous `analyze` as a fast
     path for small/quick captures **or** always-async — decide and document the
     trigger (e.g. surface-count / expected-seconds threshold) in the plan + tool
     help.
  3. Tests pass (registry reuse, start-fast, long-poll transitions, report
     produced). `/prawduct:critic` (chunk). Committed; [x].
- **Verification:** a many-surface capture (the case that exceeds 60 s today) →
  `start` returns fast → `status` → `done` with a written report.

### Chunk 3 — Disposition, deploy (fingerprint), in-band teaching

- **Type:** code · **Critic mode:** chunk
- **Done when:**
  1. Synchronous-action disposition finalized: retire the false-failure synchronous
     `render` (→ start/status), and apply the analyze disposition from Chunk 2.
     No back-compat to the retired false-failure path.
  2. **MCP fingerprint** handled: adding `start`/`status` to `ableton_render` /
     `ableton_analysis` changes the wire shape → flips the server fingerprint →
     **re-vendor + `/ableton-mcp-install` + operator re-verify** (note in the plan
     + a refreshed preflight/version expectation). These actions are in the MCP
     `_FINGERPRINT_PATHS`.
  3. **In-band teaching** (the start result is the teaching surface): action
     help/menus for `ableton_render` + `ableton_analysis` document start/poll;
     `ableton://guides/conventions` gains a "long-running actions = start+poll"
     section; `/song-workflow` + getting-started pointers updated.
  4. Tests + `/prawduct:critic`. Committed; [x].

### Chunk 4 — `/render-analyze` skill (the least-context payoff)

- **Type:** code  *(skill + docs)* · **Critic mode:** cumulative-final
  *(last chunk; the cumulative review is the PR-create gate)*
- **Done when:**
  1. A `/render-analyze [start_beat] [stop_beat] [--compare <seq>]` skill
     orchestrates render-`start`→poll→analyze-`start`→poll **out of the agent's
     main context** and returns to the agent **only** the MixReport `summary`
     (true-peak, overshoot count, per-section count, out-of-tolerance reverbs) +
     `report_path` + optional one-line delta vs `--compare`. Full per-stem/per-band
     JSON stays on disk.
  2. Wired into the discoverability spine (CLAUDE.md + `/song-workflow` + the MCP
     instructions render→analyze arc) per the song-workflow-spine convention.
  3. `/prawduct:critic cumulative` (the PR gate); blocking resolved. Committed; [x].
- **Governance checkpoint:** before completion — whole-trajectory review + the
  cumulative Critic as the PR-create gate.

---

## Cross-cutting

- **Build on a worktree off `develop`** (repo convention); review the branch via
  independent Agents + PR/merge via `gh` (worktree is invisible to the in-session
  Critic/PR skills).
- **Live-gated:** Chunks 1–3 need a real Live session to operator-verify; queue
  entries in `operator-verification.md`. Engine-only unit tests run headless with
  a Live seam mirroring the verified API (build fakes *after* verify-api).
- **Persisted format:** the `status.json` / job-handle shape is a lock-in (every
  future poller depends on it) — enumerate its fields in Chunk 1 before coding
  them (job_id, state vocabulary, progress shape, dir/report paths, error shape).
- **Transport:** stdio retained; HTTP/SSE considered & rejected (timeout is
  transport-agnostic; no wake-on-done on any transport).
