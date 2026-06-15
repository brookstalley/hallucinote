# NODE-ADDR — Build Plan (`DEV-9K7N`)

Design: `./design.md` (DESIGN/REVIEWED — Critic 2026-06-15, 2 warnings + 4 notes reconciled, no blocking).
Run `/prawduct:critic` per chunk (medium+). **One release, gated on the full in-scope set built + tested**
(§3 of design); chunks are internal build/test units, not releases.

## Problem (one line)
Nested device params, and a growing set of node features, can't be authored uniformly or captured
durably: addressing is a per-op patchwork and the read-side (capture) is agent-orchestrated prose. Freeze
ONE address for every node kind; layer features (capability-probed) on it; make the read side
deterministic code on the bridge that already exists.

## Requirements confidence
- **Chunk A (addressing) — High**, but **gated on LOM probes** (drum_pad surface, addresses-as-value,
  send-pre/post classification, return/master routing surface). The probes are *predecessors to the wire
  freeze* (Critic note c), not follow-ups — freezing the terminal/value grammar unprobed is the one real
  risk. `default_value` already live-probed (exists; raises on some quantized params).
- **Chunk B (params durability) — High.** Proven pain (swell), validated machinery (replay/push depth-N
  already shipped); only acquisition is missing. The `client.send` bridge is in production (push/pull).
- **Chunks C–F (new features) — Medium.** Each needs a LOM-surface probe for its exact write path
  (per-drum out, macro-mapping API, chain zones, chain mixer state). Chunk A's probes de-risk the
  addressing half; each chunk probes its own feature half before schema design.

## Dependency ordering (critical)
1. **A before everything** — the address + resolver + capability table + stub are the spine; B and C–F
   all speak `NodeAddr` and dispatch through the table.
2. **B immediately after A** — the thin vertical slice that proves capture→DB→push end-to-end on the one
   feature whose write/store/push is already complete. Do *not* fan out to C–F before B is green; B
   flushes out the acquisition/bridge/round-trip machinery the feature chunks reuse.
3. **C–F after B, independent of each other** — each is a stub→handler conversion; order by demand
   (per-drum routing first — the origin case). Parallelizable.

## Chunk A — Addressing foundation  [WIRE FLIP → re-vendor]  (probe-gated)
**Predecessor probes (gate the wire freeze — Critic note c) — ✅ DONE 2026-06-15 (`./probe-findings.md`):**
- `drum_pad` LOM surface → **DROP the terminal.** choke_group/out_note/mute/solo/chain-mixer all on the
  `DrumChain` (reached via `chain`); `DrumPad` only duplicates mute/solo/name. Per-chain *audio output*
  routing does NOT exist (AttributeError) → re-scope Chunk C.
- addresses-as-value → **KEEP, scoped to a track-terminal NodeAddr** (sidechain source). Macro→param
  mapping targets are not LOM-readable → not in the value grammar.
- send pre/post-fader → **`UNSUPPORTED_IN_LIVE`** (no pre/post property anywhere).
- return/master routing → **input AND output buildable (`NOT_IMPLEMENTED`)** (30 real input types);
  monitor state = `UNSUPPORTED_IN_LIVE`. (OQ4 input pre-classification corrected.)

**Deliverables:**
- **Single structured `node` object** on the wire (design §1c, DECIDED 2026-06-15) — `{parent, device_index?,
  path?, terminal? (default "device"), chain_index?}`, terminals **track/return/master/device/chain** (no
  `drum_pad`). One validator `validate_node_addr` (the single source); one facade `resolve_node_addr`.
  The same object is the **as-value** shape (sidechain `source`). Boundary: direct mixer surfaces
  (`ableton_track`/`ableton_return`) keep flat addressing — not device addressing.
- One resolver `_resolve_node(parent, …, terminal, …)` (generalize `_resolve_device_path` — DONE); one DB
  path-builder `get_node_path` (generalize `get_device_nesting_path`); one `render_node_addr` (named
  string, generated, never parsed).
- **Single-source tri-state capability table** (typed data structure — Critic note a) + generic stub
  responder + published `ableton://reference/node-feature-matrix` resource; teaching errors cite it.
  Every not-yet-built feature → documented `NOT_IMPLEMENTED`; structural-impossible → `UNSUPPORTED_IN_LIVE`
  (static-first, then probe for device-specific). Minors (macro-variations, crossfade, send-pre/post)
  land here as documented stubs.
- `get_parameters` returns `default_value` (rides this flip; consumed by B).
- **Migrate** all node-addressed actions (get_parameters/set_parameter/load/write_envelope device-param/
  perform device-param/sidechain/clear device-param) + **push-translation** (`push/devices.py`,
  `push/perform.py` build the wire args) + `skills/mix-sidechain` + tests onto the `node` object;
  **no dual surface**, and **songs' build.py is untouched** (it authors DB→push).
- Retire the flat device-addressing combo (`track_index|return_index|master + device_index + device_path`)
  on those actions in favor of `node` (semantically `terminal:"device"` is the old behavior).

**Tests:** resolver × every terminal (track/return/master/device/chain) × depths 0–3 (out-of-range,
non-rack descent, terminal mismatch, depth cap); path-builder per terminal; renderer round-trips names;
capability table tri-state;
**cross-consumer consistency test** (resource ≡ stub dispatch ≡ teaching-error text, all from the table —
Critic note a); stub responses carry the documented fields.
**Operator (Live) — Critic note d:** `device_path` is a *shipped contract* (DEEP-RACK-ADDR). Verify
**every** migrated op in Live, not just the new path: a nested set_parameter, get_parameters, load,
write_envelope, and a performed arc all still hit the right nested device via `NodeAddr`.
**Re-vendor:** required (touches `actions/`+`handlers/`). **Verifiable signal:** a depth-2 param is
read+set via `NodeAddr` and a `chain` terminal resolves (DrumChain choke_group/out_note reachable); an
unbuilt feature returns a documented `NOT_IMPLEMENTED`; a structural-impossible op (send pre/post,
macro-mapping-target, per-chain audio out) returns `UNSUPPORTED_IN_LIVE`.

## Chunk B — Params read-side durability  [vertical slice]
**Deliverables:**
- Deterministic `capture execute` (new `capture_cli`/`pull_cli` subcommand) on `client.send` — walks the
  node tree in code, probes `get_parameters(addr)` at every depth; assembles via `compile_snapshot`.
  **Retire** the agent-orchestrated `capture_plan` acquisition (keep the diff/confirm gate).
- Extend pull planners (`plan_pull_nested_rack_chains`, `plan_pull_device_parameters`) depth-N via
  `NodeAddr` — closes gap #17b.
- **`default_value` capture filter** (OQ5): store only `value != default_value`, uniform top-level +
  nested; fallback for params that *raise* on `default_value` (the Snap case — always-capture the
  minority). No read-before-write at push (capture stores only non-defaults; push emits only stored).
- §4 corrections (ride here — they're about the capture path): delete the false "Python can't call MCP
  tools" docstrings (`capture.py`, `capture_cli.py`); correct the bug record's "addressing is the gap"
  framing; correct DEEP-RACK-ADDR build-plan Chunk-2 status ("replay+push depth-N; acquisition deferred
  to DEV-9K7N").

**Tests:** acquisition round-trip with a fake `send_fn` (depth-2 nested tree → `capture execute` → DB →
push → re-emitted — the gap §6.4's test missed); symmetry contract (every read surface that probes a
top-level device probes nested ones too); `default_value` filter incl. the raises-fallback.
**Bloat measurement gate (Critic note b):** after this chunk, measure swell's captured non-default count
per device + snapshot growth; if a single preset over-captures >~25 params or snapshot >2× the by-ear
delta, schedule the bounded preset-cache (else the intrinsic-default filter stands).
**Operator (Live):** set swell `21 Voice Lead` `LFO 1 Sync` (depth-2) via `NodeAddr`, `/song-snapshot`,
rebuild + push → it survives **without saving the .als.**
**Re-vendor:** none if engine/sync only (the `get_parameters` default_value change is in A).
**Verifiable signal:** the swell operator check passes; the acquisition round-trip test is green.

**Approach (understand phase 2026-06-15 — code map; ready to build):**
- **Reference impl already exists:** `pull_cli execute` (`src/hallucinote/sync/pull_cli.py:294 _cmd_execute`) = plan→probe→apply in one pass via `_execute_plan_via_mcp(plan, send_fn)` (lines 254–291), `send_fn` lazily resolved from `hallucinote_mcp.client.send` (`_resolve_send_fn`, ~250). `client.send(request: Request) -> Response(ok, result|error)` (`hallucinote_mcp/src/hallucinote_mcp/client.py:64`). Mirror this for `capture execute`.
- **`capture execute`:** new subcommand in `src/hallucinote/tools/capture_cli.py` (siblings: plan/diff/merge/migrate). Walks the node tree in code — probe session/returns/tracks, then per rack device recurse `get_device_chains` depth-N (replaces `capture_plan`'s one-level W7-B walk at `capture.py:631–689`), probing `get_parameters(node=…)` at every depth. Assemble via `compile_snapshot` (`capture.py:692`). KEEP the diff/confirm gate (`capture_cli diff` + skill's `diff_snapshots`/`format_diff_summary`).
- **Pull depth-N:** `plan_pull_nested_rack_chains` (`src/hallucinote/sync/pull/devices.py:163`) is FLAT + one-level → migrate to `NodeAddr` + recurse depth-N. `plan_pull_device_parameters` (`devices.py:227`) is ALREADY node-migrated (emits `node={parent,device_index}`) → scales once nested node-addresses are emitted.
- **`default_value` filter (OQ5):** in capture/apply, store only `value != default_value`; when `get_parameters` OMITS `default_value` (the raises case — guarded omit at `handlers/device.py:310–335`), ALWAYS-capture. Uniform top-level + nested.
- **Mutator:** `M.set_device_parameter` (`src/hallucinote/db/mutations/devices.py:478`) — upsert + emits an event. **TOMBSTONE CHECK** (learnings): if a `sync`/pull actor emits a device-param event on a build-owned row, register that kind in `build.py` `_LATEST_ACTOR_EVENTS` or the row is CASCADE-dropped on the next build sweep.
- **§4 docstrings to delete:** `src/hallucinote/capture.py:626` + `src/hallucinote/tools/capture_cli.py:5` ("Python can't call MCP tools" — false; `client.send` bridge is live).
- **Tests:** `tests/unit/capture/` (song-agnostic synthetic). Reuse the `send_fn` fake shape from `tests/unit/sync/test_pull.py` `_fake_pull_send_factory` (keys by tool/action/node). Acquisition round-trip (depth-2 nested tree → capture execute → DB → push → re-emitted); symmetry contract; `default_value` filter incl. raises-fallback.

## Chunk C — Per-drum DrumChain authorship (choke + out_note + chain mixer)  (`chain` terminal)  — first feature, origin case
**RE-SCOPED 2026-06-15 (probe):** per-chain *audio output* routing does NOT exist on a DrumChain
(`available_output_routing_types` raises) — that ambition is `UNSUPPORTED_IN_LIVE`, not a build item.
Buildable per-drum features all sit on the `DrumChain`, reached via the **`chain` terminal**: `choke_group`,
`out_note` (MIDI transpose), `mute`/`solo`, and the ChainMixerDevice (vol/pan/sends — overlaps Chunk F).
Schema: chain columns for choke_group + out_note (+ mute/solo if not already in F). Capability probe
(choke_group/out_note only resolve on a DrumChain → else `NOT_IMPLEMENTED`/`UNSUPPORTED`). Flip the C
stub → handler. Tests: round-trip a choke group + an out_note remap via the `chain` terminal.
Re-vendor: yes (handlers). Signal: a drum chain's choke group + out_note round-trip DB→push→pull.

## Chunk D — Macro values + names + variations  (`DEV-3W9R`, RE-SCOPED)
**RE-SCOPED 2026-06-15 (probe):** Live's LOM exposes **no macro→param mapping target**
(`has_macro_mappings`/`macros_mapped` are presence-only) → **DEV-3W9R's core ask (author a macro→param
mapping) is `UNSUPPORTED_IN_LIVE` and CANNOT be built.** Flagged, not silently dropped. What IS buildable:
macro **values** (the 8 macro `DeviceParameter`s), macro **names** (`name` vs `original_name`), and macro
**variations** (`variation_count`/`store_variation`/`recall_selected_variation`/`selected_variation_index`).
Schema: macro values + custom names (+ variations) on the rack `device` terminal. No `NodeAddr`-as-value
needed (no target to store). Capture/push via `NodeAddr`. Flip stub → handler; the mapping-target cell
ships as a documented `UNSUPPORTED_IN_LIVE` stub. Tests: macro value + custom name round-trip DB→push→pull;
a variation recall round-trips. Re-vendor: yes. Signal: macro value/name round-trip is green; attempting a
macro-mapping-target write returns the documented `UNSUPPORTED_IN_LIVE` stub.

## Chunk E — Key/velocity/chain-select zones
Probe rack-chain zone LOM surface. Schema: per-chain key/vel/chain-select ranges. Capability probe (only
on selector/zone-capable racks → else `UNSUPPORTED_IN_LIVE`). Capture/push via `chain` terminal. Flip
stub → handler. Tests: a velocity-layered rack round-trips. Re-vendor: yes. Signal: zone round-trip green.

## Chunk F — Chain mixer-state (incl. mute/solo write)
Today chain mute/solo are read-only; chain mixer columns don't exist. Schema: chain volume/pan/sends/
mute/solo. Capture/push via `chain` terminal. Flip stub → handler. Tests: a nested-chain mute + level
round-trips DB→push→pull. Re-vendor: yes. Signal: chain mixer round-trip green.

## Re-vendor (Critic W2)
A flips the fingerprint (wire). C–F also touch `handlers/`/`actions/` (in `_FINGERPRINT_PATHS`) → they
re-vendor too. What's frozen is the *address grammar*, not the fingerprint. **One re-vendor at release;
re-vendor per chunk while testing against Live.** Bundle; coordinate with any Live-side session.

## Out of scope / fast-follow
- **`DEV-4X2N`** (analysis-extract flatten-on-nested-rack-pull) — downstream consumer, unblocked by
  Chunk A; fast-follow after release, not an in-release chunk.
- **Documented `NOT_IMPLEMENTED` stubs** (no handler): macro variations, crossfade assign, send pre/post
  (last pending Chunk-A probe → may be `UNSUPPORTED_IN_LIVE`). They are table rows in Chunk A, not chunks.

## Coordination
Edits MCP `actions/`+`handlers/` + the sync/capture layer — the same areas a parallel Live/song session
touches. Resolve before building (worktree isolation, or confirm the other session is song-side). Run a
fresh `pytest` before any Chunk-A code review (current `prawduct-hook test-status` is stale, exit 1).

## Status
- [x] Probes (Chunk A predecessors): drum_pad, addresses-as-value, send-pre/post, return/master routing — DONE 2026-06-15 (`./probe-findings.md`; design §1.5). Wire-freeze decided: terminal enum `track|return|master|device|chain` (no drum_pad).
- [x] Chunk A: addressing foundation [FLIP] — ✅ DONE + LIVE-VERIFIED 6/6 2026-06-15 (merged to develop):
  - [x] **Spine landed + green (31 tests, full suite 3782+):** one resolver `_resolve_node` (all 5
    terminals), one validator `validate_node_addr` (the single grammar, in-object `terminal` default),
    one facade `resolve_node_addr` — all in `handlers/device.py`. `get_parameters` returns `default_value`
    (guarded; omits on the Live raise → always-capture signal for Chunk B). Purely **additive** so far
    (existing wire untouched; suite stays green).
  - [x] **Wire migration (the big atomic step):** COMPLETE + GREEN 2026-06-15 (full suite 3783 passed,
    2 skipped — exact baseline; 25 files, +876/−421). `node_addr_spec()`
    in `schema.py`; migrated actions+handlers `get_parameters/set_parameter/load/set_sidechain` (device) +
    `write_envelope/clear/perform_batch` device_parameter (automation) from flat → `node`; **flat addressing
    retired** on those (no dual surface). Push-translation via new `_core.build_node_addr` (devices/perform/
    envelopes; `push_execute` forwards `node` transparently; sidechain push uses unmigrated `set_input_routing`
    so stays flat). `skills/mix-sidechain` + `conventions.md`/`gaps.md` updated. `resolve_node_addr` now returns
    `(node, kind, idx, spec)`. **Decisions (persisted; flag for Critic):**
    - **D1 responses unchanged** — only the *input* address is frozen to `node`; handlers still echo flat
      `device_index`/`parent_kind`/`device_path` (built from the resolved spec). Keeps push/pull response-
      consumers untouched (lowest blast radius; the "no dual surface" rule is about input addressing).
    - **D2 as-value source SHIPPED** — `set_sidechain.source` is now a track/return/master-terminal node
      (replaces `source_display_name`); exercises the design's central single-object justification. Special
      non-node sources (`Main`/`No Input`) route via `set_input_routing` directly (flagged gap).
    - **D3 load via node** — track/return/master terminal = top-level load; `chain` terminal = nested load
      (subsumes the old `chain_index` param); `device` terminal = teaching error.
    - **SCOPE ASYMMETRY (flag):** plan's explicit list migrated; **read-side + shallow nav kept flat** —
      `read_envelope`/`get_envelope` (device_index), `list`/`info`/`get_routing`/`navigate_preset`/`pad_info`,
      `set_input_routing`. Rationale: plan-faithful (not in the migrated list) + they're shallow/read surfaces,
      not the device-addressing combo. RECOMMEND a follow-up to migrate the envelope read pair for full
      device_parameter uniformity. Not silently dropped — surfaced here + to the user.
    - [x] **Tests:** ALL flat-param test sites migrated to `node` (full suite green at baseline).
  - [x] Single-source tri-state capability table (typed `hallucinote_mcp/node_features.py`: `FeatureStatus` +
    `Feature`/`Cell` + `MATRIX`, 15 features LOM-confirmed) + generic stub responder (`cell_response`) +
    teaching-error generator (`teaching_error`) + published resource `ableton://reference/node-feature-matrix`
    (13th resource — PRIMER/README/conventions-guide/test counts updated) + **cross-consumer consistency test**
    (resource ≡ stub ≡ teaching-error, all from one `Cell`). 24 tests `tests/unit/test_node_features.py`.
    DONE 2026-06-15.
  - [x] `get_node_path(conn, device_id)` (generalize `get_device_nesting_path` → full NodeAddr; DB-native
    parent index) + `render_node_addr(conn, device_id)` (named string, generated never parsed) — one shared
    up-walk `_walk_node_with_rows`; legacy `get_device_nesting_path`/`get_top_level_device` refactored onto it
    (no behavior change). 14 tests `tests/unit/db/test_node_path.py`. DONE 2026-06-15.
  - [x] **Operator-verify every migrated op in Live (Critic note d)** — ✅ DONE 2026-06-15 (Live 12.4.2,
    fingerprint `c487d2b32ba7`). All 6 checks pass (set/get @ depth-2 + `default_value`, top-level load,
    perform @ depth-2 + write_envelope, `chain` terminal resolves a DrumChain, capability matrix). Surfaced
    + FIXED a **pre-existing** chain-load bug (`browser.load_item` is main-chain-only → use
    `Chain.insert_device`; also corrected the false-green fake) — see `operator-verification.md` + the
    learnings.md rule. NOT a wire-flip regression.
    Note (flagged, NOT dropped): `read_envelope`/`get_envelope` + shallow-nav surfaces kept flat per the plan
    (reads, outside the migrated set) — recommended fast-follow, not a Chunk-A gate.
- [x] Chunk B: params read-side durability — ✅ CODE DONE + GREEN 2026-06-15 (full suite green; Live operator-verify pending):
  - [x] **Deterministic `capture execute`** — `capture.assemble_snapshot_via_probes(probe, old_snapshot=)`
    walks the live set IN CODE (session/master/returns/tracks + full recursive rack tree), probing
    `get_parameters` at EVERY depth via NodeAddr `path`; assembles via `compile_snapshot` +
    `preserve_browser_paths`. Engine stays free of `hallucinote_mcp` (transport injected as a high-level
    `probe(tool, action, **params)`); `tools/capture_cli.py` `execute` subcommand builds the real probe over
    `client.send` (+ `_resolve_send_fn`/`_make_probe` mirroring pull_cli) and writes the side-by-side
    `.refresh.json`. `/song-snapshot` skill retired the by-hand probe+compile prose for `capture execute`
    (`capture_plan` kept as the hand/first-capture doc). **No re-vendor** (engine/sync/skill only).
  - [x] **`default_value` capture filter (OQ5)** — `_snapshot_param_entry`: stores only `value != default_value`
    (within ε); when Live OMITS `default_value` (the quantized raise — handler guard from Chunk A) ALWAYS
    captures (the always-capture minority). Single-source `normalize_param_value` moved DOWN to `capture.py`
    (pull `_core` had it; pull already imports capture → no cycle), so a captured-then-replayed param lands
    the same DB row a pull writes.
  - [x] **Pull depth-N** — `plan_pull_device_parameters` now walks top-level + nested devices
    (`_iter_linked_device_params` / `_walk_nested_device_params`), emitting `get_parameters(node)` with the
    nested `path` (top-level keeps the flat no-path shape — existing tests unchanged). `_apply_nested_rack_chains_for_device`
    recurses the full `get_device_chains` tree (`_diff_nested_chains`), lifting the W7-B one-level cap (#17b
    closed — addressing was the gate; Chunk A froze it). No wire change.
  - [x] **§4 corrections** — deleted the false "Python can't call MCP tools" claims (`capture.py` module +
    capture-plan section, `capture_cli.py` module); corrected the bug-record framing
    (`incoming-bugs/archives/2026-06-14-nested-nested-rack-…md`: addressing shipped, acquisition was the gap)
    + DEEP-RACK-ADDR build-plan Chunk-2 status ("capture" → "*replay* + push; acquisition deferred here").
  - [x] **Tombstone** — `device_parameter`/`device_parameter_set` already registered in `build.py`
    `_LATEST_ACTOR_EVENTS` (no new kind; capture replays as `actor='sync'`, pull as `actor='sync'` — both
    protected). Verified, no new registration needed.
  - [x] **Tests (16 new, full suite green)** — `tests/unit/capture/test_capture_execute.py` (12): acquisition
    round-trip (fake-Live probe → capture → replay → DB → push re-emit @ depth-2 — the loop the prior
    replay-only test never closed); symmetry contract (every depth probed); default_value filter incl.
    raises-fallback, enum, const-range, at-default. `tests/unit/sync/test_pull.py` (4): depth-N param node
    `path` (depth-1 + depth-2); nested-rack-chains rack-in-rack apply recursion + idempotency.
  - [ ] **Operator (Live) — pending** (enqueued in operator-verification.md): swell `21 Voice Lead`
    `LFO 1 Sync` depth-2 survives `/song-snapshot` + rebuild without saving .als; + the bloat-measurement
    gate (Critic note b: non-default count per device + snapshot growth).
- [x] Chunk C: per-DrumChain authorship — choke_group + out_note (`chain` terminal) — ✅ CODE DONE + GREEN
  2026-06-15 (impl map `./chunk-c-impl.md`; full suite green; Live operator-verify pending). **Scope: choke +
  out_note only; chain mute/solo WRITE deferred to Chunk F** (mixer-state — the matrix `mixer_state` chain
  cell owns it; the `choke_out_note` feature was narrowed to drop the mute-solo mention). The 9 touchpoints:
  - [x] **Schema** — `device_chains.choke_group` / `out_note` (nullable INT) in `schema.sql` + `_ADDED_COLUMNS`
    (canary-paired); `DEVICE_CHAIN_PROPS_SET` event; `build.py` actor-map gains `device_chain_props_set`.
  - [x] **Mutator** — `set_chain_properties` (partial, idempotent, clear-on-None; mirrors `set_track_routing`).
    `create_device_chain` stays identity-only (per-drum props ride the new mutator, not create).
  - [x] **Capture** — `chain_authored_props` (single non-default filter: choke 0 / out_note==in_note → None,
    mirrors Chunk B); `_capture_nested_chains` attaches; `_replay_rack_chains` applies (clears on re-replay).
    `_describe_chain` surfaces choke_group/out_note/in_note (drum chains only; plain chains unchanged).
  - [x] **Handler + action** — `set_chain_property_handler` (resolves `chain` terminal; capability-probes via
    `hasattr` — a plain Chain gets a teaching error, never crashes; validates + probes before any write) +
    `ableton_device(action='set_chain_property', node, choke_group?, out_note?)`.
  - [x] **Push** — `_emit_chain_property_calls` in `_emit_nested_param_writes`: each chain with a stored
    non-default prop emits a `chain`-terminal `set_chain_property` (path = the rack's own path, [] top-level).
  - [x] **Pull** — `_diff_nested_chains` diffs `chain_authored_props` vs DB → `set_chain_properties` (clears
    a now-default value; idempotent steady state — the round-trip fixed point).
  - [x] **Matrix** — `choke_out_note` chain cell flipped NOT_IMPLEMENTED → SUPPORTED (determination probe).
  - [x] **Tests (49 new, full suite green)** — mutator (`test_chain_properties.py`), capture filter + replay
    round-trip (`test_chunk_c_chains.py`), handler pos/neg/validation/atomicity (`test_set_chain_property.py`),
    push emit + nested-rack path (`test_push_devices.py`), pull diff/clear/idempotent (`test_pull.py`).
    Updated contract tests: node-features supported-list, `_EXPECTED_DEVICE_ACTIONS`.
  - [x] **Live-probe gate** — re-confirmed on the scratch 808 *Instrument* Rack: a plain `Chain` has NO
    choke_group/out_note (the negative capability case), validating the `hasattr` re-probe.
  - [ ] **Operator (Live) — pending** (enqueued): positive choke+out_note round-trip on a real DrumChain +
    durability + the plain-Chain teaching error. Needs re-vendor + a loaded Drum Rack (scratch set lacks one).
- [ ] Chunk D: macro values/names/variations (DEV-3W9R; mapping target UNSUPPORTED_IN_LIVE)
- [ ] Chunk E: zones
- [ ] Chunk F: chain mixer-state
