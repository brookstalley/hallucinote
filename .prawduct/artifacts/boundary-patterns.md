# Boundary Patterns — Hallucinote

Contract surfaces where components interact. When changes cross these
boundaries, the builder investigates consumer impact before completing the
chunk. The Critic verifies investigation occurred.

## Contract Surfaces

### Database Schema (`src/hallucinote/db/schema.sql`)

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

### Mutator API (`src/hallucinote/db/mutations.py`)

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

### Sync Planner / Result API (`src/hallucinote/sync/push.py`)

- **Producer**: `push.py` — pure-data plans, no side effects.
- **Consumer**: the agent (executes MCP calls, then feeds results back).
- **Contract**:
  - `plan_push_clip` / `plan_push_arrangement` take `session_id` and read
    bindings from `ableton_links` via `Q.get_ableton_link`.
  - `apply_push_results` takes `session_id` and writes bindings via
    `M.link_db_to_ableton`.
  - `ToolCall.key` is `"<kind>:<uuid>"` — the kind selects which link is
    written when the result comes back. Exception (ENV-9P4T): the
    `perform_batch:<song>` key is ONE call whose result fans out to N
    arc-results — `apply_push_results`' `perform_batch` branch iterates
    `result["arcs"]` and correlates each to its envelope by the opaque
    `arc_id` the handler echoes back (NOT by the call key), recording each
    arc's performed-state independently on its own `automation_state`.
  - `PushPlan` carries four channels: `calls` (dispatched), `notes`
    (diagnostic — "nothing to push", "not linked yet"; NOT surfaced to the
    operator), `alerts` (SYN-9F2L — operator-actionable, non-fatal warnings),
    and `errors` (SYN-6B4Q — hard authoring errors). `push_execute` HALTS a
    phase whose plan has non-empty `errors` without dispatching (the DB
    describes something that can never be materialized); it drains `alerts`
    (deduped, including the devices convergence re-plan's) into the push
    report's benign `warnings` channel, exit stays 0. Pick the channel by
    severity: `error()` when no re-push can fix it short of changing the
    authored DB; `alert()` when the operator authored something that was
    skipped and would want to know ("the dialed intent was NOT pushed");
    `warn()` for diagnostic noise the operator shouldn't see. `to_dict()`
    serializes all four keys (additive — `alerts` is the newest).

When changing this surface:
- Any signature change breaks the agent integration. Document in the build
  plan + chunk handoff.
- New result kinds need both a planner emitter and an `apply_push_results`
  branch.
- MCP result fields a planner relies on (e.g. `cue_create_batch`'s
  `skipped_out_of_range`, SYN-6B4Q) are additive optional fields — readers
  default sanely when absent (same policy as the MixReport JSON surface).

### Pull Planner / Result API (`src/hallucinote/sync/pull.py` + `pull_cli.py`)

- **Producer**: `pull.py` — pure-data `PullPlan`s, no side effects.
- **Consumer**: the `/ableton-pull` skill (executes MCP read probes, normalizes
  responses, calls back via `pull_cli`).
- **Contract**:
  - `plan_pull_mix` (and future `plan_pull_*`) take `song_id` + `session_id`,
    walk `ableton_links` for linked rows, emit `PullCall` probes.
  - `PullCall.key` is `"<kind>"` (global) or `"<kind>:<uuid>"` (per-row) —
    dispatched by `_HANDLERS` in `apply_pull_results`.
  - Routing (RTE-1K9T) rides in the `mix-state` domain: per linked track,
    `plan_pull_mix` emits `track_output_routing:<id>` / `track_input_routing:<id>`
    / `track_monitor:<id>` (one MCP read each — the three getters are separate
    LOM surfaces). Apply maps Live's `display_name` back to a DB routing
    reference via `sync/routing_names.py` (the SAME map push reads forward, so
    the two never drift), then writes through `set_track_routing`. NULL routing
    columns are treated as Live's default route, so a first pull of an unrouted
    track is a no-op, not a churn of every NULL into an explicit default (D8).
  - Device sidechain SOURCE (SDC-7K3M) rides in its own `device-sidechain` domain
    (symmetric with push's separate `device_sidechain` phase): per device on a
    linked track/return, `plan_pull_device_sidechain` emits
    `device_sidechain_source:<device_id>` = one `ableton_device(get_input_routing)`
    read. The source is always a TRACK, so apply resolves Live's `current_type`
    (a track `display_name`) to a song-track FK by name — NOT via `routing_names`
    (that maps routing *kinds*) — and writes through `set_device_sidechain`. V1
    apply is Ableton-authoritative in the SET direction only: a distinct-track
    match is captured; self-match / name-collision / non-track input all no-op
    (auto-CLEAR on a non-track input is operator-verification-gated — Live's
    reporting of an un-sidechained device's default input is unverified).
  - `apply_pull_results` is **Ableton-authoritative** (V1 conflict policy);
    field-level diffs are tolerant of `_FLOAT_EPS` jitter so display rounding
    doesn't churn events.
  - Mutations use `actor='sync'` (matching push); pull-vs-push provenance
    lives in the event `reason` field.
  - `pull_cli.py` is the JSON-over-stdio bridge the skill calls: `plan`
    emits the PullPlan, `apply` consumes plan + results and returns an
    `ApplyResult` summary.
  - `pull_cli execute <domain> <session_id>` (Arc 3 / C3) is the
    in-process one-shot that collapses plan + probe + apply into one
    pass — does NOT touch the JSON bridge. Uses the same MCP TCP seam
    as `push_cli` (`_resolve_send_fn` → `hallucinote_mcp.client.send`);
    `plan`/`apply` remain MCP-free for the skill-driven flow.

When changing this surface:
- New `PullCall` key kinds need a `_HANDLERS` entry AND an apply branch.
- The normalized result shape per kind is documented in the `PullCall`
  docstring; the skill is responsible for normalizing raw MCP responses to it.
- Three-way merge is deferred. If you re-open conflict policy, update both
  this doc and the pull.py module docstring together.

### Event Kinds + Payloads (`src/hallucinote/db/events.py`)

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

### MixReport JSON (`src/hallucinote/audio/report.py` `to_json_dict()`)

- **Producer**: `analyze.py` `analyze_mix` → `report.to_json_dict()`, persisted
  as `songs/<slug>/analysis/<iso-ts>.json`.
- **Consumers**: `compare.py` (`diff_reports` / `resolve_baseline` read old
  reports back as raw dicts — the JSON **is** the contract, no deserializer),
  the `/mix-review` skill, calibration baselines.
- **Contract**: `schema_version` is load-bearing — `ensure_comparable` REFUSES
  to diff mismatched versions, so a bump severs baseline lineage (every saved
  report with the old version becomes undiffable). **Bump on breaking shape
  changes ONLY; additive optional fields do NOT bump.** Precedent: AUD-4W7K
  added `db_seq` + `compare_to` while `SCHEMA_VERSION` stayed `"1"` — version
  `"1"` deliberately spans both shapes, and consumers tolerate the fields'
  absence (`db_seq=None` on old reports).

When changing this surface:
- Additive optional field → no bump; ensure readers default sanely when it's
  absent (the AUD-4W7K pattern).
- Breaking change → bump, and accept (record) that existing analysis baselines
  are orphaned — or write a migration for them.

### Capture Manifest (`captures/manifest.json`)

- **Producer**: `hallucinote_mcp/handlers/render.py` (inside Live's vendored,
  hallucinote-less env) writes it; the server (`server._attach_render_db_seq`)
  injects `db_seq` into the render request because only the server side can
  read the song DB.
- **Consumers**: `audio/io.py` `load_capture` → `analyze_mix` (stamps `db_seq`
  into the MixReport), `resolve_baseline` (seq → report resolution).
- **Contract**: `db_seq` crosses three runtimes (server reads → vendored
  handler writes → engine loads). It is best-effort provenance: absent/null on
  old manifests and when the song DB can't be read — consumers must treat
  `db_seq=None` as "unknown", never an error. Field additions are additive
  (same policy as MixReport JSON).

### Remote Script Version Handshake + Server Identity (`hallucinote_mcp/__init__.py`, `resources/`, `cli/`)

- **Producer**: `__init__.py` `__version__` (`BASE_VERSION` + content fingerprint
  over `_FINGERPRINT_PATHS` = `wire.py`/`schema.py`/`dispatcher.py`/`actions`/
  `handlers`/`remote_script`). The running server exposes its identity via the
  `ableton://server/info` resource (`version`, `base_version`, `fingerprint`,
  `package_root`) — Live-independent.
- **Consumers**: the runtime handshake (`wire.py` — every dispatch); the
  `ableton-mcp-install` skill (reads `ableton://server/info`, threads it into the
  CLI); `cli/preflight.py` (`--server-version` → `matches_mcp_server` +
  `coexistence_divergence`); `cli/install.py` (`--from-package-root` +
  `--require-server-version`).
- **Contract**: the server, the vendored Remote Script, and the install CLI's
  reference must all agree on **which `hallucinote_mcp` copy is authoritative — the
  one the *plugin launches***, never the invoking interpreter's `sys.path` pick
  (INS-3W8P). `resources/` is deliberately **outside** `_FINGERPRINT_PATHS`, so
  adding/altering a resource (e.g. `server/info`) does **not** change the handshake
  fingerprint and never forces a re-vendor.

When changing this surface:
- A change to any `_FINGERPRINT_PATHS` file flips `__version__` → the vendored
  Remote Script is stale until re-vendored; say so in the chunk handoff + the
  operator-verification (it needs a Live restart, since Live caches Control Surface
  modules at startup).
- A change to the `ableton://server/info` payload shape, or to the preflight
  `server`/`coexistence_divergence` keys or the `install-remote-script` flags,
  breaks the install skill — update `skills/ableton-mcp-install/SKILL.md` in the
  same change (the `test_install_skill_consistency.py` structural test guards the
  subcommand calls; the JSON shape is the skill's contract).

### MCP Action Wire Shape (`hallucinote_mcp/.../actions/*.py`)

- **Producer**: `actions/*.py` `register(Action(...))` — the agent-facing tool
  surface. Each `Action` declares its `name`, `ParamSpec`s (the wire params), and
  the handler it dispatches to.
- **Consumers**: the agent/LLM (calls `ableton_<tool>(action=..., ...)`); the
  `sync/push/*` and `sync/pull/*` planners (emit `ToolCall`s whose `args` MUST
  match a registered action's params); the skills under `skills/` and the
  resource guides under `resources/guides/` that document actions; the
  `test_*_well_formed` / action-registration tests.
- **Contract**: the set of action **names** per tool, and each action's **param
  names + types**. Retiring an action, renaming it, or removing/renaming a param
  breaks every planner `ToolCall` and skill that uses it. Adding an OPTIONAL
  param (`required=False`) is non-breaking — existing callers omit it and the
  handler defaults it (the DEEP-RACK-ADDR pattern: `device_path` added to
  `set_parameter` / `get_parameters` / `load` / `write_envelope` and per-arc in
  `perform_batch`). Note this is DISTINCT from the version handshake below: the
  fingerprint is computed over `actions/` + `handlers/` content, so any wire-shape
  change ALSO forces a re-vendor — but a planner/skill mismatch is a logic break
  the fingerprint won't catch.

When changing this surface:
- Retiring/renaming an action or a required param → grep the WHOLE repo
  (`sync/`, `skills/`, `docs/`, `resources/guides/`, tests) for callers and
  update each; never leave a parallel/duplicate surface (no-backcompat-to-
  throwaway). Precedent: DEEP-RACK-ADDR retired `set_parameter_in_rack` /
  `load_in_rack` (zero production callers; folded into `set_parameter` /
  `load` + `device_path`/`chain_index`; tests migrated, guides updated).
- The action's params and the handler signature are two halves of one contract:
  a ParamSpec the handler doesn't accept (or vice versa) is a dispatch-time
  `TypeError`. Add/remove on both sides together.
- Re-vendor is required for any `actions/` change (it's inside the fingerprint
  paths) — say so in the chunk handoff.

## Test Levels

Tests fall into three categories that must stay disjoint: platform (the `hallucinote` library), MCP plugin (the `hallucinote-mcp` server), and song-specific. Platform and MCP tests must not load song data; song tests must not test platform/MCP behavior beyond what's incidental to the song.

| Level | Exists | When to Run | Location |
|-------|--------|-------------|----------|
| Platform — unit (mutator + event round-trip) | yes | every change to mutations / schema | `tests/unit/db/test_mutations.py`, `tests/unit/db/test_score_extensions.py` |
| Platform — unit (planner) | yes | every change to sync / link projection | `tests/unit/sync/test_push*.py`, `tests/unit/sync/test_pull.py`, `tests/unit/sync/test_mix.py` |
| Platform — unit (generators) | yes | every change to generators | `tests/unit/generators/test_*.py` |
| Platform — unit (capture / replay) | yes | every change to `hallucinote.capture` | `tests/unit/capture/test_capture.py` |
| MCP — unit | yes | every change to `hallucinote_mcp/src/` | `hallucinote_mcp/tests/unit/test_*.py` |
| MCP — integration (dispatcher round-trip) | yes | every change to dispatcher / wire / remote_script | `hallucinote_mcp/tests/integration/test_remote_script_server.py`, `test_skills_well_formed.py` |
| MCP — integration (live Ableton push) | manual; gated on MCP capability | when a chunk delivers push of a new domain | invoked by hand |
| Song — build smoke | yes (per song) | every schema or mutator change OR every change to that song | `songs/<slug>/tests/test_<slug>_build.py` (per-song convention so files stay unique under `pytest -n auto`) |
| Song — snapshot shape (capture/replay/push planner against the song's `captured_session.json`) | yes (per song) | every schema / mutator / planner change OR every change to that song's snapshot | `songs/<slug>/tests/test_capture_replay.py`, `test_push_mix_snapshot.py` |
| Song — consistency / mix hygiene | not yet (per-song; on-demand) | once a song requires it | `songs/<slug>/tests/test_*.py` |
