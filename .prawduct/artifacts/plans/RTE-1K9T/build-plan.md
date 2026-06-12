# RTE-1K9T — Track Routing — Build Plan

**Design:** `./design.md` (requirements, discovery findings, decisions — read first).
**Scope:** track input/output routing + monitor state, end-to-end (MCP → DB → push → pull) +
the PRE-MAIN submaster convention. **TRK-2H6K (groups) deferred** (D2).
**Effort:** L. **Branch:** `feature/rte-1k9t-track-routing`. **Base for PR/Critic:** `develop`.

**Governance:** medium+ work → Critic per chunk (or rolled-up at PR per
`feedback_critic_cadence_for_small_chunks` for the small symmetric chunks 02/05). Tests are
contracts; capability-probe, never whitelist (`feedback_third_party_devices_require_capability_probing`).

---

## Thin vertical slice first

**Chunk 01 is the spine:** one real routing write MCP→Live, by `display_name`, capability-probed,
with tests — independently useful (replaces raw `ableton_probe` for routing). Everything else
(input/monitor, DB, push, pull, convention) hangs off it.

---

## Chunks

### Chunk 01 — MCP track OUTPUT-routing actions  ·  status: pending
**Deliverables**
- `ableton_track(action='set_output_routing', track_index, type_display_name, channel_display_name?)`
  and `action='get_output_routing'` in `actions/track.py` + handlers in `handlers/track.py`.
- Mirror `device.py`'s pattern: capability-probe `available_output_routing_types`, resolve target by
  `display_name` via a shared `_find_routing_by_display_name`, set `output_routing_type`
  (+ optional `output_routing_channel`); `get` returns current + available (no raise when absent).
- Reuse/extract the device-side `_find_routing_by_display_name` / `_enumerate_available` helpers into
  a shared module rather than copy-paste (avoid the MIX-6D2N-style duplication).

**Acceptance criteria**
- Routing an audio track's output to a named bus succeeds and reads back the new `display_name`.
- Unknown `type_display_name` → teaching error **listing the source track's actual available targets**.
- Source-dependence respected (a bare MIDI track legitimately lacks audio-track targets — error, not crash).
- Tests in `test_actions_track.py` mirroring `test_actions_device.py` L2037–2089 (by-name, with-channel,
  unknown-type-lists-available). All green.

### Chunk 02 — MCP track INPUT-routing + monitor state  ·  status: pending
**Deliverables**
- `set_input_routing` / `get_input_routing` on `ableton_track` (symmetric to chunk 01).
- Monitor state: `set_property(property='monitoring_state', value=In|Auto|Off)` (or a dedicated
  action) reading/writing `current_monitoring_state` — **required for the bus to pass routed audio**.

**Acceptance criteria**
- A receiving audio track can be set Monitor=In and have its input routing read back.
- Tests mirror chunk 01; monitor-state round-trips. Green.

### Chunk 03 — DB schema + routing mutator (+ events)  ·  status: pending
**Deliverables**
- Add routing to the `tracks` model (D4: columns on `tracks` — output routing kind/target/channel,
  input routing, `monitoring_state`). Confirm columns-vs-side-table against `schema.sql` shape before
  committing the DDL.
- Mutator `set_track_routing(...)` emitting `E.TRACK_ROUTING_SET` (follow `set_track_mixer` exactly).
  Target modeled as a reference `{kind: master|track|sends_only|ext_out, target_track_id?}` + channel.
- DB tests in `tests/unit/db/test_mutations.py` (round-trip, event emission, master/sends_only/track-target).

**Acceptance criteria**
- A routing write goes through the mutator and emits exactly one event; reload reconstructs it.
- A track-target reference survives (FK to `tracks.id`); deleting the target is handled sanely.
- No raw SQL in callers (`feedback_mutator_discipline`). Green.

### Chunk 04 — Push integration (new `routing` phase)  ·  status: pending
**Deliverables**
- New `routing` phase in `plan.py` `_PHASE_NAMES` **after `mix`, before `devices`** (D5).
- `plan_push_routing` (in `sync/push/`): for each track with DB routing, resolve the target-track link
  and emit `ableton_track(action='set_output_routing'/'set_input_routing'/monitor)` by `display_name`.
- Fingerprint-gate so unchanged routing never re-emits (match the existing mix/send gating).

**Acceptance criteria**
- Pushing a DB-authored PRE-MAIN layout (tracks→bus, bus→master, bus Monitor=In) materializes the
  routing in a fresh set; re-push is a no-op.
- Push tests (new `test_push_routing.py`) cover plan-level + execute-path. Green.

### Chunk 05 — Pull integration  ·  status: pending
**Deliverables**
- Ingest routing in `plan_pull_mix` (probe `output_routing_type.display_name` etc.); `_apply_track_routing`
  maps the Live display_name back to a DB target reference and calls `set_track_routing`.
- Pull tests in `tests/unit/sync/test_pull_mix.py` (manual reroute in Live → DB ingest via mutator).

**Acceptance criteria**
- A routing change made in Live pulls into the DB through the mutator (events fall out). Green.

### Chunk 06 — PRE-MAIN submaster convention + docs  ·  status: pending
**Deliverables**
- A worked, tested example authoring the submaster pattern on the new primitives (create audio bus →
  route instrument tracks → bus → master → Monitor=In) — as a song-authoring conventions-doc entry
  (and/or a thin `/route-to-bus` skill if it earns it; do not gold-plate).
- Document the **automation-fidelity caveat** (perform today; lossless gated on CLP-AUD2) where a
  song author will see it (conventions doc), linking the design doc — don't restate
  (`feedback_link_dont_summarize`).

**Acceptance criteria**
- The convention is reproducible from the doc using only shipped actions (no raw `ableton_probe`).
- The caveat is discoverable; no claim that lossless master automation is "solved."

---

## Verification (whole-plan)
- Full suite green (current baseline: 3371 passed / 0 failed / 2 skipped @ 2026-06-12).
- Live smoke: author + push a PRE-MAIN submaster in a scratch set; confirm audio sums through the bus
  (Monitor=In) and a `perform_batch` volume ride on the bus lands.
- Critic review (base `develop`); reflection captured before close.

## Backlog linkage
- Closes **RTE-1K9T**. Defers **TRK-2H6K** (note added). Relates: MAW-4K7P (this is the no-`.als`
  alternative path to master-like automation), TPL-2D8K (a template could pre-place the bus),
  CLP-AUD2 / ENV-8H1T (the lossless-bus-automation follow-on).
