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
- [~] Chunk A: addressing foundation [FLIP] — IN PROGRESS (worktree `feature/node-addr`):
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
    - [ ] **Tests:** migrate ALL flat-param test sites to `node` (in progress).
  - [ ] Single-source tri-state capability table (typed) + generic stub + `ableton://reference/node-feature-matrix` resource + cross-consumer consistency test.
  - [ ] `get_node_path` (generalize `get_device_nesting_path`) + `render_node_addr` (engine-side).
  - [ ] Operator-verify every migrated op in Live (Critic note d) — needs dev-server pointed at the worktree.
- [ ] Chunk B: params read-side durability (capture execute + pull depth-N + default_value filter) [vertical slice]
- [ ] Chunk C: per-drum DrumChain authorship — choke + out_note + chain mixer (`chain` terminal; re-scoped)
- [ ] Chunk D: macro values/names/variations (DEV-3W9R; mapping target UNSUPPORTED_IN_LIVE)
- [ ] Chunk E: zones
- [ ] Chunk F: chain mixer-state
