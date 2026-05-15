# Boundary Patterns — Songwright

Contract surfaces where components interact. When changes cross these
boundaries, the builder investigates consumer impact before completing the
chunk. The Critic verifies investigation occurred.

## Contract Surfaces

### Database Schema (`src/songwright/db/schema.sql`)

- **Producer**: `db/connection.py` (init_db) materializes the schema.
- **Consumers**: `db/mutations.py` (writes), `db/queries.py` (reads), test
  fixtures, every `songs/*/build.py`, `sync/*`, future capture/replay tools.
- **Contract**: Table names, column names + types, FK + cascade rules, and
  indexes. UUID identity (TEXT) is load-bearing — mutators generate ids in
  Python via `_uuid()`.

When changing this surface:
- Update mutators **and** queries together.
- Update every `songs/*/build.py` and any tool that opens the DB.
- Re-run the full suite and rebuild falling-walking with `--reset` to verify.

### Mutator API (`src/songwright/db/mutations.py`)

- **Producer**: `mutations.py` — the only sanctioned writer.
- **Consumers**: `songs/*/build.py`, `sync/push.py`, agent code, future
  generator orchestration.
- **Contract**:
  - Keyword-only signatures, no positional args after `conn`.
  - Every mutator accepts `actor='system'`, `request_id=None`, `reason=None`.
  - Every mutator emits exactly one `events` row in the same transaction as
    its state change. `_emit` is the only path; it assigns `seq` monotonically.
  - Returns: new id (creates), list of new ids (bulk creates), or `None`
    (updates/deletes).
  - `actor` must be in `events.ACTORS`.

When changing this surface:
- Adding kwargs with defaults is non-breaking.
- Renaming or removing a mutator breaks every caller — grep the repo and
  update each one. (Chunk 1 replaced three `link_*_to_ableton` mutators with
  one generic `link_db_to_ableton`; tests + sync updated together.)

### Sync Planner / Result API (`src/songwright/sync/push.py`)

- **Producer**: `push.py` — pure-data plans, no side effects.
- **Consumer**: the agent (executes MCP calls, then feeds results back).
- **Contract**:
  - `plan_push_clip` / `plan_push_arrangement` take `session_id` and read
    bindings from `ableton_links` via `Q.get_ableton_link`.
  - `apply_push_results` takes `session_id` and writes bindings via
    `M.link_db_to_ableton`.
  - `ToolCall.key` is `"<kind>:<uuid>"` — the kind selects which link is
    written when the result comes back.

When changing this surface:
- Any signature change breaks the agent integration. Document in the build
  plan + chunk handoff.
- New result kinds need both a planner emitter and an `apply_push_results`
  branch.

### Event Kinds + Payloads (`src/songwright/db/events.py`)

- **Producer**: `mutations.py` (every emitter is a mutator).
- **Consumers**: `queries.get_events_for_*`, future replay/merge tooling, the
  audit-log UI (eventual).
- **Contract**: Event-kind constants are append-only. Payload shapes are part
  of the contract — they're how an event-store flip will reconstruct state.
  Add new kinds; never silently rename or repurpose an existing kind.

When changing this surface:
- Removing a kind breaks any saved event log — coordinate with a migration
  story.
- Payload changes should be additive (new optional keys) until replay is
  implemented.

### Ableton Projection (`ableton_sessions` + `ableton_links`)

- **Producer**: `mutations.create_ableton_session`, `mutations.link_db_to_ableton`.
- **Consumer**: `sync/push.py` (read via `queries.get_ableton_link`).
- **Contract**: Bindings are `(session_id, db_kind, db_id) -> ableton_index`.
  `db_kind` ∈ `mutations.ABLETON_LINK_KINDS`. Multiple sessions per song are
  intentional — a song can be bound to several Live sets without aliasing.

When adding a new `db_kind`:
- Extend `mutations.ABLETON_LINK_KINDS`.
- Add a planner branch in `sync/push.py` that emits a `<kind>:<uuid>` key.
- Add an `apply_push_results` branch that consumes the matching result shape.

## Test Levels

| Level | Exists | When to Run | Location |
|-------|--------|-------------|----------|
| Unit (mutator + event round-trip) | yes | every change to mutations / schema | `tests/test_mutations.py` |
| Unit (planner) | yes | every change to sync / link projection | `tests/test_push.py` |
| Unit (generators) | yes | every change to generators | `tests/test_generators.py` |
| Integration (build.py against DB) | smoke via `python songs/falling-walking/build.py --reset` | every schema or mutator change | `songs/falling-walking/build.py` |
| Integration (live Ableton push) | manual; gated on MCP capability | when a chunk delivers push of a new domain | invoked by hand |
| Song tests (consistency / mix completeness) | not yet | once Chunks 1–3 land | `songs/<name>/tests/` (planned) |
