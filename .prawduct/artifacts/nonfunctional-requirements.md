---
artifact: nonfunctional-requirements
version: 1
depends_on:
  - artifact: architecture
last_validated: 2026-08-06
---

# Non-Functional Requirements

Most conventional NFR categories don't apply to a single-user desktop tool: there is no
scale target, no availability SLO, no concurrent-user load, no capacity plan. What
follows is the short list that genuinely constrains design.

## Latency — one hard external constraint

The agent host imposes a **wall-clock timeout on a single tool call**, progress
notifications do **not** reset it, and there is no wake-on-done. This is not tunable
from our side.

**Requirement:** any operation that can plausibly exceed it exposes `start` (returns a
job id) + `status` (poll) rather than blocking. Rendering an arrangement and multi-stem
analysis both crossed this line; the synchronous `render` action was retired because of
it. Socket read timeouts are selected per (tool, action) and must exceed the handler's
own long-poll window, or the transport severs a call that was healthy.

## Availability of the server process

**Requirement:** no single tool call may block the MCP event loop. FastMCP runs
synchronous tool functions inline, so one blocking `def` handler freezes the whole
server for every other call. Handlers are `async` and dispatch through
`anyio.to_thread`. This is an availability requirement, not a style preference.

## Startup

**Requirement:** the MCP server is **stdlib-only at import time**. The Remote Script
imports it inside Live, where the heavy audio stack is unavailable and slow startup is
user-visible. Engine imports are lazy, at call time.

## Idempotency

**Requirement:** push is re-runnable. It diff-reconciles and skips already-current
state, so re-pushing changes what the user asked for and leaves everything else alone.
A push phase that reapplies unconditionally is a defect — it was a real one in the
`devices` phase.

## Correctness over completeness

**Requirement:** when a value cannot round-trip faithfully, **refuse or skip with a
warning — never write the wrong value.** Device enums with no normalized wire form are
skipped; a mid-song tempo or meter change is stored faithfully and its skip is
reported on the push report's operator channel, because the limit is Live's
renderer, not the model. Silent data loss is never
the fallback. This is a stated product value, not a limitation to be engineered away
quietly.

## Test-suite integrity

**Requirement:** the full suite runs with **no path argument**. `testpaths` covers
`tests/`, `hallucinote_mcp/tests/` and `songs/`; a path-scoped run silently skips the
rest. CI enforces this, and so must local verification before any "green" claim.

## Direction

Ratified 2026-08-10. The requirements above are the norms; two are homed here, the rest
point at the artifact that owns them.

- **The MCP server is stdlib-only at import time; engine imports are lazy, at call time.**
  Why: the Remote Script imports the server *inside Live*, where the heavy audio stack
  (numpy/scipy/librosa/soundfile) is unavailable and slow startup is user-visible. This is
  a narrow rule about **import time in the MCP server** — the engine depends on that stack
  freely at runtime, and the plugin's uv environment carries it deliberately. Trimming
  those dependencies to "shrink the build" breaks analysis; moving an engine import to
  module scope breaks the Remote Script.

- **The full test suite runs with no path argument.**
  Why: `testpaths` spans three trees, so a path-scoped run silently skips the others and
  reports green over untested code — a false "green" claim is worse than a slow one,
  because it is acted on. CI enforces it; local verification before any "green" claim must
  match.
  Rulings: [[In a git worktree, pin `pythonpath` in pytest config — a bare `pytest` silently tests the PRIMARY checkout]]

- Latency (`start` + `status` for long operations), event-loop availability (`async`
  handlers), and push idempotency are ratified in
  [`architecture.md`](architecture.md) § Direction.
- "Correctness over completeness" — refuse-and-teach, never write the wrong value — is
  ratified in [`api-contract.md`](api-contract.md) § Direction.
