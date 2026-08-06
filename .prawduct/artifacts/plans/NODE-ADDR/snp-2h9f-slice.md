# SNP-2H9F — `param_overrides` on a `preset_query` device (NODE-ADDR Chunk B follow-on)

Backlog: `SNP-2H9F` (`status: design`, related `DEV-9K7N`/`DEV-7K4H`/`SNP-4K7M`).
Source report: `backlog SNP-2H9F`.
Branch: `feat/snp-2h9f-param-overrides` (off develop, in worktree `.claude/worktrees/snp-2h9f`).
Baseline at branch point: 4003 passed, 2 skipped.

## Confidence check
- **Problem:** a by-ear nested param dialed deep inside a rack loaded via `preset_query`
  reverts on every from-scratch rebuild+push, silently. The snapshot has no shape for
  "load instrument X from its portable preset, then override nested param P": `_replay_devices`
  accepts `preset_query` **XOR** a full `chains` dump, `params_dialed` only applies to the
  top-level device, and `assemble_snapshot_via_probes` (`capture execute`, NODE-ADDR Chunk B)
  emits a full `chains` dump for **every** rack and never carries `preset_query` forward
  (`preserve_browser_paths` carries only `browser_path`, top-level only — verified 2026-06-17).
- **Success:** a `preset_query` device entry carries `param_overrides: [{path, name, value[,
  normalized][, value_items]}]`; it round-trips DB→push→capture→DB durably — the nested override
  survives a from-scratch rebuild **without** dropping `preset_query` or duplicating chains, and
  without dumping the Wavetable waveform / bloating the snapshot.
- **Out of scope:** the bounded preset-reference cache (design §8 / Critic note b — defer; same
  intrinsic-`default_value` filter as Chunk B, accept preset-non-default over-capture, measure
  bloat after); macro→param mapping (unrelated, UNSUPPORTED_IN_LIVE); the live `.als` save path.

## Decision — DB representation (LOCK-IN: persisted schema)
**New table `device_param_overrides`**, modeled on `device_parameters` + a `path_json` column,
keyed `UNIQUE(device_id, path_json, name)`. Rationale + alternatives:
- A `preset_query` device has **only the top-level row** in the DB — the preset instantiates the
  nested tree at push time, so there is no nested device row to hang a `device_parameters` row on.
  Overrides must be keyed by (top-level preset `device_id`, descent `path`, param `name`).
- **Chosen: separate table** (mirrors `drum_pad_mappings` — the established pattern for a
  variable-length per-device list: own table, replace-style mutator, single coarse event). New
  tables auto-migrate onto existing song DBs via `init_db`'s `CREATE TABLE IF NOT EXISTS`
  (no `_ADDED_COLUMNS` entry — that mechanism is for new *columns* only).
- **Rejected — JSON blob column** `devices.param_overrides_json`: simpler migration but opaque to
  queries/diff and off-pattern vs `drum_pad_mappings`/`breakpoints`.
- **Rejected — a nullable `path` column on `device_parameters`**: changes a shipped table's PK
  surface (high blast radius on a core table) for no gain over an isolated bolt-on.

Consumers' future queries the schema must answer (enumerated per build-cycle lock-in rule):
push "all overrides for device X" (→ index on `device_id`); capture/pull per-(path,name) diff;
audit "what overrode this preset param" (the replace event carries `device_id` + the new
override ids + prev/new counts — the full row content is recoverable from the rows it wrote,
matching the `drum_pad_mappings_replaced` house pattern).

## Touchpoints
1. **Schema** — `device_param_overrides` table + index in `schema.sql`. New event
   `DEVICE_PARAM_OVERRIDES_REPLACED` (replace-style, coarse — mirrors drum_pad_mappings). Register in
   `build.py` `_LATEST_ACTOR_EVENTS` (tombstone protection — a sync/pull actor must not get the
   row CASCADE-dropped on the next build sweep).
2. **Mutator** — `replace_device_param_overrides(conn, device_id, overrides, actor, …)`: atomic
   delete+insert (mirrors `replace_drum_pad_mappings`), idempotent (no-op + no event when
   unchanged), validates each override's `path`/`value` shape, emits one event.
3. **Query** — `get_device_param_overrides(conn, device_id) -> list[Row]`.
4. **Replay** (`capture._replay_devices`) — after `create_device`, if entry has `param_overrides`,
   call the mutator. **Guard:** `chains` + `param_overrides` on the same entry is a `ValueError`
   (contradictory representations — the report's XOR). Reuse the BUG4 bare-numeric-value warning.
5. **Push** (`sync/push/devices.py`) — `_emit_param_override_writes`: per stored override emit a
   node-addressed `set_parameter` at `node=build_node_addr(parent_kv, device_index=<preset top
   index>, device_path=<override path>)` — **no `create_device_chain`**, so the preset
   waveform/samples survive and nothing duplicates. Extract the per-param value-form selection
   (SYN-9F2L) from `_emit_param_writes` into a shared helper (DRY). Call from `_emit_device_calls`.
6. **Capture** (`assemble_snapshot_via_probes` / `_capture_devices_for_parent`) — thread a
   preset-seeded-device identity set from `old_snapshot` (devices whose prior entry had
   `preset_query`). For a preset-seeded rack: carry `preset_query` forward + emit `param_overrides`
   (flat list, non-default-filtered, walking the `get_device_chains` tree; path = each nested
   device's `device_path`), and **omit `chains`**. Non-preset racks keep the existing `chains` dump.
7. **Tests** — mutator (idempotency/clear/validation/event); replay (overrides→DB; chains+overrides
   ValueError); push (emit at right node/path; value forms; preset waveform untouched); capture
   (preset-seeded → preset_query+param_overrides not chains; non-preset → chains); **full
   round-trip** snapshot(preset_query+param_overrides)→DB→push re-emit @ depth-2→capture→DB (fake
   probe — the verifiable signal); default-filter.
8. **Docs** — `docs/snapshot-schema.md` `param_overrides` shape + the XOR-with-`chains` rule.

## Scope boundary — pull symmetry (DEFERRED as a fast-follow, confirmed)
The verifiable signal is the **capture** round-trip (DB→push→capture→DB), which needs replay +
push + capture — all built. `/ableton-pull` is a **separate** ingestion path (manual fader/mute/
send edits), not in the signal. **Confirmed (`sync/pull/devices.py`):** pull is a **no-op** on a
stable preset device — it matches by position and only delete+recreates when the device at a slot
genuinely *changed* (user-driven, uncommon); preset_query is preserved. It does NOT emit
`param_overrides`, so a nested tweak ingested via `/ableton-pull` lands as transient nested
`device_parameters` rows (overwritten by the next snapshot-based rebuild) rather than a durable
override — a coherence gap, **not a regression**, and outside the signal. **Decision: defer
pull-symmetry as a documented fast-follow** (file under SNP-2H9F). The durable path is
`/song-snapshot` (capture), which is fixed. **Drum-rack-via-preset with authored per-chain props:**
capture keeps the full `chains` dump + warns (param_overrides is device-params only) — same
fast-follow.

## Re-vendor
None for replay/mutator/schema/capture/pull (engine + sync only — not in `_FINGERPRINT_PATHS`).
Push emits an existing wire action (`set_parameter` node-addressed — shipped in Chunk A), so **no
new MCP action/handler** and **no wire change**. The Live operator-verify (preset device override
survives a real rebuild) rides NODE-ADDR's enqueued operator-verification list.

## Status
- [x] B2.1 durability slice — schema + event + mutator + query + replay + push + tests
      (device_param_overrides table; DEVICE_PARAM_OVERRIDES_REPLACED; replace_device_param_overrides;
      get_device_param_overrides; _replay_devices param_overrides + XOR-chains guard; shared
      _param_value_fields/_param_value_kv helpers; _emit_param_override_writes; tombstone reg).
- [x] B2.2 acquisition — preserve_preset_overrides (carry preset_query + chains→param_overrides,
      chain-prop safety guard + warn); capture+round-trip tests; pull-symmetry deferred (above).
- [x] Docs (snapshot-schema.md `param_overrides` bullet).
- [ ] Full suite green + Critic.

## Test evidence
- New: tests/unit/db/test_param_overrides.py (16) + tests/unit/capture/test_param_overrides.py (14).
- Baseline 4003 → re-run full suite for the new total.
