---
artifact: architecture
version: 1
depends_on:
  - artifact: product-brief
  - artifact: authorship-model
  - artifact: boundary-patterns
  - artifact: api-contract
last_validated: 2026-08-06
---

# Architecture

Hallucinote spans **four runtimes that can fail independently**, which is why this
artifact exists (`multi_process_distributed: client-server` is recorded in
`project-state.yaml`). This file names the topology and the rules that keep it
coherent. Per-boundary contract detail lives in [`boundary-patterns.md`](boundary-patterns.md)
and [`api-contract.md`](api-contract.md); where a song's authorship lives is
[`authorship-model.md`](authorship-model.md). Those aren't restated here.

## The runtimes

```
┌─ Claude Code (agent host) ──────────────────────────────────────────┐
│  Skills (/hallucinote:*) drive everything. Spawns the MCP server as │
│  a stdio subprocess; also shells out to the `hallucinote` CLI.      │
└──────┬──────────────────────────────────────┬───────────────────────┘
       │ MCP (stdio, JSON-RPC)                │ subprocess (CLI)
       ▼                                      ▼
┌─ hallucinote-mcp server ────────┐    ┌─ hallucinote engine ─────────┐
│  13 unified tools, action-      │    │  build.py execution,         │
│  dispatched. Stdlib-only at     │    │  generators, sync planners,  │
│  startup; lazy-imports the      │◀──▶│  capture/replay, analysis.   │
│  engine at call time.           │    │  Owns the SQLite DB.         │
└──────┬──────────────────────────┘    └──────────┬───────────────────┘
       │ loopback TCP 127.0.0.1:9878              │ file I/O
       │ (length-prefixed JSON)                   ▼
       ▼                                   songs/<slug>/*.db
┌─ Ableton Live ──────────────────────────────────────────────────────┐
│  Remote Script (Control Surface) — runs INSIDE Live's Python, with  │
│  Live's privileges and lifecycle. Plus the HallucinoteAnalyzer      │
│  Max for Live device on audio tracks/returns/master (Suite only).   │
└─────────────────────────────────────────────────────────────────────┘
```

All four run on **one machine**. There is no remote tier, no multi-user server, and
no network listener beyond the loopback socket. This is a local authoring tool whose
distribution is an artifact of Live being a closed application we can only reach by
injecting code into it.

## Why this topology and not a simpler one

**Live is only scriptable from inside itself.** Ableton exposes the Live Object Model
solely to Control Surface scripts running in Live's embedded Python. We cannot link
against Live, and Live will not call out. So a process boundary into Live is forced,
not chosen — and everything awkward downstream (the vendoring step, the version
handshake, the restart requirement) descends from that one constraint.

**The engine is split from the server for startup reasons.** The MCP server must be
importable by Live's Remote Script, which means **stdlib-only at module import time**.
The engine depends on numpy/scipy/librosa/soundfile. Importing the engine at server
module scope would both break the Remote Script and make server startup slow, so
analysis handlers **lazily import** the engine at call time. The plugin's uv
environment carries the heavy dependencies; that is deliberate and must not be
trimmed to "shrink the build."

## Failure independence — what breaks when each runtime dies

| Runtime | If it dies | Recovery |
|---|---|---|
| Live | Bridge calls fail with "no connection". The DB is untouched and authoritative. | Reopen Live; re-run push. |
| Remote Script | Same symptom as Live being down, but Live looks fine — the classic confusing case. | Reassign the Control Surface slot; **fully quit and reopen Live** (Live caches Control Surface modules at startup — `/mcp` alone will not reload it). |
| MCP server | Tools vanish from the agent's surface. | `/mcp` respawns the subprocess. Sufficient for engine changes; **not** for Live-side changes. |
| Engine / CLI | Build and analysis fail; the bridge still answers. | Ordinary Python error; the DB is transactional so a failed build leaves no partial state. |
| The SQLite DB | Regenerable. It is materialized state, never source. | `build.py --reset` rebuilds it from git-tracked source. |

The load-bearing invariant: **the DB is never the thing you can't afford to lose.**
Source of truth is `build.py` + `captured_session.json` in git. That is what makes
every one of these failures recoverable rather than destructive.

## The coherence problem, and the mechanism that solves it

Two halves of the *same source tree* execute in two different runtimes: the MCP server
runs from the plugin's uv environment, while a **vendored copy** of the wire-shape code
runs inside Live's User Library. Nothing forces those copies to agree — and a silent
disagreement produced the worst debugging session in this project's history (source
updates that had not propagated into Live).

The fix is a **content fingerprint**. `__version__` is `BASE_VERSION` plus a SHA-256
over the whole-file bytes of every file that defines the wire shape (actions, handlers,
dispatcher, schema, wire, remote_script — the set is `_FINGERPRINT_PATHS`). Both halves
compute it; the handshake compares them and, on drift, raises a structured *"Remote
Script outdated, re-run `/ableton-mcp-install`"* rather than failing mysteriously
several calls later.

Two rules follow, and both are easy to violate:

- **`_FINGERPRINT_PATHS` must equal the code that is both vendored into Live AND
  executed in Live** — no more, no less. Listing extra paths causes false re-vendor
  demands; omitting a real one reopens the silent-drift hole.
- **Server-side-only code goes in the top-level `server_side/` package**, which is
  excluded by simply not being listed. This is why analysis handlers don't flip the
  fingerprint while render's Live-side ones do.

## Concurrency and long operations

**Sync tools must be `async`.** FastMCP runs synchronous tool functions
inline on the event loop, so one blocking sync tool freezes the entire server. The
server wrapper is `async` and dispatches through `anyio.to_thread`. Reverting a handler
to plain `def` is a whole-server availability bug, not a style preference.

**Long operations are start+poll, never synchronous.** The agent host imposes a
wall-clock timeout on a tool call that progress notifications do not reset, and there
is no wake-on-done. So anything that can exceed it — rendering a full arrangement,
multi-stem analysis — exposes a `start` action returning a job id plus a `status`
action to poll. The synchronous `render` action was retired for exactly this reason.
Socket read timeouts are selected per (tool, action) and must exceed the handler's own
long-poll window, or the socket severs a call that was healthy.

## Data flow: push and pull

**Push** materializes DB → Live through fourteen ordered phases (tempo → meter →
tracks → returns → scenes → clips → mix → devices → routing → device-sidechain →
envelopes → performed automation → arrangement → cues). Order is a real dependency
graph, not a preference: routing needs tracks to exist, envelopes need devices.
Push is **idempotent and diff-reconciling** — it skips already-current state, so a
re-push changes what you asked for and leaves the rest alone.

Arrangement is the exception to incremental push. On the **push** side it is a
**projection** — clear, then create-and-fill from the DB, then assert integrity
(`sync/push/arrangement.py`) — because incremental reconciliation against Live's
positional, renumbering clip model produced years of whack-a-mole bugs.

**Pull** ingests Live → DB by diffing against the DB and folding manual edits back
through the same mutators that authored the state originally. Note that pull has *not*
adopted the projection model: `sync/pull/clips.py::plan_pull_arrangement_clips` still
diffs arrangement placements positionally against `arrangement_clips` rows.

The invariant that makes both safe: **every write goes through a mutator and emits an
event in the same transaction.** No raw SQL in callers, ever. That discipline is what
keeps the eventual event-store migration cheap (see [`authorship-model.md`](authorship-model.md)).

## Deployment topology

The plugin is **self-contained**: skills, bridge server, and engine ship together in
one uv-managed environment built on first launch. There is nothing on PyPI and no
separate engine to install.

One consequence bites contributors specifically. A marketplace-installed plugin
(serving `main`) **shadows** a `--plugin-dir` checkout (serving your working branch)
unless the marketplace copy is disabled via `/plugin`. On a development machine, run
two worktrees and drop the marketplace install — the rationale is in
[`docs/dev-vs-use-coexistence.md`](../../docs/dev-vs-use-coexistence.md).

## What is deliberately not modeled

- **Three nested-rack corners** — *not* nesting in general, which capture, replay and
  push handle to arbitrary depth (`_replay_rack_chains` recurses; `get_device_chains`
  returns the whole tree in one call). What remains: sidechain **pull** is not extended
  depth-N, a rack sitting on another rack's chain is outside the pull planner's scope,
  and `diff_snapshots`/`merge_snapshots` itemize one level and summarize deeper subtrees
  — a preview simplification, not a data limit.
- **Human audio.** A recorded vocal take or a hand-ridden automation lane lives only in
  the `.als`; the bridge cannot pull it into a song's source. This is a boundary, not a
  bug — see the README's Known Issues.
- **Multi-user concurrency.** Deliberately absent from the wire shape. If it ever
  arrives it belongs at the DB/application layer, where the event-store flip is its
  natural foundation — not as per-element locking or version vectors in the protocol.
- **Linux.** Ableton ships no Linux build.

## Direction

Ratified 2026-08-10. These bind future work; the narrative above describes it.

- **`_FINGERPRINT_PATHS` names exactly the code that is both vendored into Live and
  executed in Live** — no more, no less.
  Why: the fingerprint is the only thing standing between a contributor and silent
  server/Remote-Script drift, the failure that produced this project's worst debugging
  session. Listing extra paths trains contributors to ignore re-vendor demands until they
  ignore a real one; omitting a real path reopens the hole the mechanism exists to close.
  Rulings: [[A Live-side change OUTSIDE `_FINGERPRINT_PATHS` ships silently — the handshake won't tell you to re-vendor]],
  [[A staleness/version signature must be content-derived, never hand-bumped]]

- **Server-side-only code lives in the top-level `server_side/` package.**
  Why: exclusion from the fingerprint *by construction* beats exclusion by list
  maintenance — a path that must be remembered to stay off the list eventually lands on
  it. This is why analysis handlers don't flip the fingerprint while render's Live-side
  handlers do.

- **Every MCP tool handler is `async` and dispatches blocking work through
  `anyio.to_thread`.**
  Why: FastMCP runs synchronous tool functions inline on the event loop, so one blocking
  `def` handler freezes the server for every other call. Reverting a handler to plain
  `def` is a whole-server availability bug, not a style preference.

- **Any operation that can exceed the agent host's tool-call timeout exposes `start` +
  `status` rather than blocking.**
  Why: the host's wall-clock timeout is not reset by progress notifications and there is
  no wake-on-done, so a long synchronous call is *severed*, not merely slow — the
  synchronous `render` action was retired for exactly this. Socket read timeouts are
  selected per (tool, action) and must exceed the handler's own long-poll window, or the
  transport severs a call that was healthy.
  Rulings: [[A realtime / long-playback MCP action needs a read-timeout policy entry — applied at the layer EVERY recv route shares, not just one]]

- **Push is idempotent and diff-reconciling; the arrangement phase is a projection.**
  Why: a re-push must change what was asked for and leave the rest alone, or the tool is
  unsafe to run twice — a phase that reapplies unconditionally is a defect, and was a real
  one in `devices`. Arrangement is the exception because incremental reconciliation against
  Live's positional, renumbering clip model produced years of whack-a-mole bugs; settled
  push-side in brookstalley/hallucinote#350.
  Retroactivity: contain — projection is the **push**-side regime. Pull still diffs
  arrangement placements positionally (`sync/pull/clips.py::plan_pull_arrangement_clips`),
  and the pull planner is the modeled boundary between the two regimes. Convergence is
  deliberately not intended: the renumbering hazard is a write-path problem and does not
  transfer to reading. (Owner ruling, 2026-08-10 ratification.)

- **Multi-user concurrency stays out of the wire shape.**
  Why: this is a single-user, single-machine tool (see the topology above and
  [`security-model.md`](security-model.md)'s threat model). If concurrency ever arrives it
  belongs at the DB/application layer where the event log is its natural foundation —
  per-element locking or version vectors in the protocol would tax every single-user call
  forever to serve a user who does not exist.
