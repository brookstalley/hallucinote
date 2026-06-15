# NODE-ADDR — Uniform node-path addressing + the feature matrix

**Backlog item:** `DEV-9K7N` (filed 2026-06-15; `closes: DEV-7K4H`; related `DEV-3W9R` macros, `DEV-4X2N` analysis-extract).
**Status:** DESIGN / REVIEWED (2026-06-15). Build plan next; not yet built.
**Critic (2026-06-15):** 2 warnings + 4 notes, no blocking; architecture validated, every load-bearing
claim re-verified first-hand. All 6 findings reconciled in-doc (inline `Critic W1/W2/note a–d` tags).
W1 = depth-0 was an empirical result not a code ceiling (§6.5); W2 = feature chunks DO re-vendor, only
the *address grammar* is frozen (§3/§5). Findings: `.prawduct/.critic-findings.json`.
**Supersedes:** the narrower `DEEP-RACK-READ` read-side-params framing (folded in as Slice 1 below).
**Extends:** `DEEP-RACK-ADDR` (shipped 2026-06-14) — that unified addressing for the *device sub-tree*
(`device_path`). This generalizes the same idea to *every node kind* and factors features off it.
**Source:** recurring nested-rack durability gap (`incoming-bugs/archives/2026-06-14-nested-nested-rack-params-…md`,
swell guitar + Voice-Lead LFO), backlog `DEV-7K4H` / "gap #17b", per-drum-routing gap.
**Decisions locked (user, 2026-06-15):** (a) it's an addressing × feature matrix — solve addressing
*once*, layer features independently; (b) canonical address = **structured positional node-path**;
a **named string rendering** is *generated* from it for humans, never parsed back.

---

## 0. The thesis

The nested-device pain keeps recurring because every operation reinvents "how do I reach a thing
that's N levels deep," each with its own ceiling. The fix is to recognize two **independent axes**:

- **Addressing** — *what* node you're operating on (a track, a return, a chain, a device, at any
  depth). Solve this **once**, uniformly. An address does not know what feature you'll apply.
- **Feature** — *what* you do to the addressed node (set a param, set routing, set chain mixer
  state, map a macro, set a zone). Each feature is added independently, on top of the one address.

`DEEP-RACK-ADDR` already proved the factoring on a slice of the matrix: `set_parameter`,
`get_parameters`, `load`, `write_envelope`, perform-automation all take the *same* `device_path`
and none know their depth. NODE-ADDR finishes the factoring: generalize the address to all node
kinds, then features become "add a column + a capability probe," never "invent a new reach."

> **The matrix is the once-and-for-all answer to "are we patching instances?"** — instances stop
> when no feature owns its own addressing.

---

## 1. The address model (canonical = structured + positional)

```
NodeAddr = {
  parent:   { kind: "track" | "return" | "master", index?: int },   # the root (master has no index)
  path:     [ { chain_index: int, device_position: int }, … ],        # 1-based descent steps (may be empty)
  terminal: "track" | "return" | "master" | "device" | "chain",       # WHAT the address ends ON
}
# NOTE (2026-06-15): `drum_pad` was DROPPED from the frozen enum after the predecessor probes —
# every per-drum feature lives on the DrumChain (reachable via `chain`). See §1.5 + probe-findings.md.
```

- **`device_path` becomes a special case:** `terminal: "device"` with the same `path` steps. The
  generalization is the explicit `terminal` + first-class `parent.kind` + the ability to **end on a
  chain** (today a chain is only a *waypoint to a device*, never a destination — that's the missing
  primitive routing/mixer-state need).
- **~~`drum_pad` is a distinct terminal~~ — FALSIFIED by probe (2026-06-15), terminal DROPPED.** The
  completeness audit *assumed* choke/pad-mute/transpose lived on `DrumPad` distinct from its chain. The
  predecessor probe (probe-findings.md, spot-verified) proved the opposite: `choke_group`(int, settable),
  `out_note`(transpose; =60 vs `in_note`=36), `mute`/`solo`, and the chain mixer all live on the
  **`DrumChain`** — reachable today via the `chain` terminal. `DrumPad` carries only redundant
  `mute`/`solo`/`name` + a fixed `note` index. So a pad terminal buys nothing; the `chain` terminal
  covers per-drum authorship. **Bonus wall:** per-chain *audio output* routing does NOT exist on a
  DrumChain (`available_output_routing_types` raises `AttributeError`) → Chunk C re-scopes to
  choke + out_note + chain-mixer (no separate audio output).
- **Positional, not named, is the key.** Positions are stable across a `build.py` rebuild because a
  rack preset reload is deterministic (DEEP-RACK-ADDR §5). Names are display only.
- **The leaf field is an operation argument, NOT part of the address.** The address resolves to a
  *node*; `set_parameter(addr, name="Volume", …)` / `set_routing(addr, output="Ext. Out/3")` name
  the field. (Automation's target is `(node, param)` — the op still carries the param; one boundary.)
- **A `NodeAddr` must be usable as an operation *value*, not only as the target (completeness-audit
  finding).** Device sidechain source and macro mappings have values that are themselves node/param
  addresses (a sidechain points at a source track; a macro maps to a param on a nested device). The
  wire + schema must let an address appear as an argument value, not just the addressed target.

### 1a. One resolver, one DB path-builder, one renderer
- **Resolver** (`handlers/`): generalize `_resolve_device_path` → `_resolve_node(parent, path, terminal)`.
  Walk parent → steps → terminal; teaching-error at each failed step (out-of-range, non-rack descent,
  terminal-kind mismatch). For `terminal: "chain"` the last step is a `chain_index` with no
  `device_position`.
- **DB path-builder** (`db/queries.py`): generalize `get_device_nesting_path` → `get_node_path(node_id)`
  — already walks `parent_rack_device_id` up to the track/return root for devices; extend to return a
  chain/track terminal. Pure DB, no live round-trips.
- **Renderer** (new, pure fn): `render_node_addr(conn, addr) -> str`, e.g.
  `track 3 ▸ "Guitar-Dual Amped Heavy" ▸ "Guitar Dead Notes"`. Names from resolved rows; **generated
  for decisions/annotations/logs, never the lookup key.** Retires the opaque `[{1,1},{1,1}]` in
  decisions/22.

### 1b. Load unit ≠ param-set unit (how nested devices actually manifest)

Nesting in a song is **not** authored device-by-device. `build.py` loads **one** device — a rack
preset (`Synth Vox Ai`, a drum rack, `Guitar-Dual Amped Heavy`) — and the **preset instantiates its
entire internal tree**. Two different granularities:

- **Load unit = the top-level rack/preset.** One `load`; the nested tree arrives with it. Push must
  *never* load nested devices (DEEP-RACK-ADDR §3c already gets this right).
- **Param-set unit = individual nested devices, N levels deep.** The by-ear dialed values
  (`LFO 1 Sync`, sampler Voices, a chain Limiter) are *deltas on top of* the preset's defaults.

This reframes what capture owes (Slice 1): it does **not** capture nested structure *in order to load
it* — the preset owns loading. It captures, for each nested device:
1. the **addressing skeleton** — device rows + 1-based positions, so `get_node_path` is computable and
   matches the reloaded preset's structure (positional determinism), and
2. the **dialed param values** on those nested devices.

On rebuild: push loads the *one* preset → the tree appears → push re-applies the dialed deltas by
`NodeAddr`. The skeleton is addressing-only; loading stays preset-driven.

> **Capture granularity — RESOLVED (OQ5, §8, live-probed):** record only params where
> `value != DeviceParameter.default_value`, uniform top-level + nested. `default_value` rides the
> per-device `get_parameters` read (zero extra reads; no read-before-write at push). Fallback for the
> quantized params where `default_value` raises: always-capture the minority, or a bounded preset-cache.
> Kills the "99.9% defaults" bloat without a throwaway-preset diff in the common case.

---

## 1.5 Probe results — wire-freeze amendments (2026-06-15)

The four hard-predecessor LOM probes (Critic note c — gate the wire freeze) are **complete**, run
read-only against the open swell set and spot-verified. Full evidence: **`./probe-findings.md`**. The
freeze decisions that change this design:

1. **`drum_pad` terminal DROPPED.** Frozen terminal enum = **`track | return | master | device | chain`**.
   Choke/out_note/mute/solo/chain-mixer all live on the `DrumChain`, reached via `chain`. (§1 amended.)
2. **NodeAddr-as-value KEPT but scoped to a *track*-terminal NodeAddr** (sidechain source = a
   `RoutingType.display_name` = a track name). Macro→param mapping *targets* are **not LOM-readable**
   (`has_macro_mappings`/`macros_mapped` are presence-only) → the value grammar carries a track NodeAddr,
   not device/param-depth addresses.
3. **Send pre/post-fader = `UNSUPPORTED_IN_LIVE`** (no pre/post property on `MixerDevice` or the send
   `DeviceParameter`) — confirms the §2b suspicion; static documented stub, not `NOT_IMPLEMENTED`.
4. **Return/master routing:** *input AND output routing are buildable* (`NOT_IMPLEMENTED`) on both —
   `available_input_routing_types` has 30 real entries; this **refutes OQ4's `UNSUPPORTED_IN_LIVE`
   pre-classification for input**. Only **monitor state** is the wall (`UNSUPPORTED_IN_LIVE` — "Main and
   Return Tracks have no monitoring state").

**Chunk scope deltas (carried into build-plan.md):** Chunk C (per-drum) → choke + out_note + chain mixer
(no separate audio output — a hard wall). Chunk D (macros) → values/names/variations buildable; the
macro→param *mapping* is `UNSUPPORTED_IN_LIVE` (Live exposes no target). **DEV-3W9R's core ask (author a
macro→param mapping) is largely unreachable** — flagged, not silently dropped.

---

## 2. The decoupling is one-directional (capability probing) — this is the pushback that holds

Addressing is fully feature-agnostic. **Operations are NOT node-agnostic** — Live's matrix is sparse
and ragged, and pretending otherwise would lie about the LOM. **The feature set is OPEN, not five**
(completeness audit, 2026-06-15 — see §6): the codebase already authors ~8 distinct features and the
LOM holds more unbuilt. The table below is **illustrative + living**, not a closed enumeration — the
*address* is the frozen/complete thing; features layer on indefinitely.

| Feature | node kinds it applies to | status | distinct from |
|---|---|---|---|
| device parameters (incl. device on/off) | device | shipped | — |
| mixer state (vol/pan/mute/solo/arm) | track/return/master; **chain = read-only gap** | shipped (chain write = gap) | — |
| send levels (→return) | track/return | shipped | vector, not scalar |
| **output** routing (+channel) | track shipped; **return/master = NOT_IMPLEMENTED** (probe: buildable); **per-drum-chain audio out = UNSUPPORTED_IN_LIVE** (probe: AttributeError) | shipped (track) | input |
| **input** routing (+channel) | track shipped; **return/master = NOT_IMPLEMENTED** (probe: 30 real types, not the assumed wall) | shipped (track) | output |
| **monitor state** (In/Auto/Off) | track | shipped | input routing |
| **device sidechain source** | device | shipped (own phase) | track routing; value *is a NodeAddr* |
| name + color metadata | all nodes | shipped | — |
| macro **values + names** | rack device | **unbuilt** (NOT_IMPLEMENTED) | mapping target |
| macro **mapping target** (macro→which param) | rack device | **UNSUPPORTED_IN_LIVE** (probe: LOM exposes no target) | macro value |
| macro variations / snapshots (Live 12) | rack device | **unbuilt** (NOT_IMPLEMENTED — `variation_count`/`store_variation` present) | macro mapping |
| key/velocity/chain-select zones | rack chain / selector rack | **unbuilt** | — |
| choke group / out_note / chain mute-solo | **chain** (DrumChain — probe: NOT on DrumPad) | **unbuilt** | device |
| crossfade assign | track | **unbuilt** (minor) | — |
| send pre/post mode | send | **UNSUPPORTED_IN_LIVE** (probe: no pre/post property) | — |

**Boundary (so these aren't miscounted as more features):** automation/envelopes is a *subsystem that
consumes the address* (already address-aware, DEEP-RACK-ADDR), not a node property. Clips, notes,
arrangement, cues, tempo, meter, scenes-as-launch are separate models, not node-tree authorship.

So: **the address doesn't know about features; every feature operation MUST capability-probe the
resolved node and teaching-error if the feature isn't supported there.** This is the project's own
law (`feedback_third_party_devices_require_capability_probing` — probe + adapt, never whitelist). A
symmetric "any feature at any address" model is the one part of the URI instinct to reject.

### 2a. The matrix is agent-facing documentation — published ahead, referenced from errors

The capability matrix above isn't just an internal design note — it's the **support contract the agent
needs in advance** so it doesn't attempt impossible operations and burn turns on errors. Two delivery
surfaces (Living Documentation):

- **Published ahead as an MCP resource** — e.g. `ableton://reference/node-feature-matrix` (sibling of
  the existing `ableton://reference/{scales,device-params}`), read at no turn cost. The agent consults
  it *before* authoring (which node kinds support routing? can a master strip route? does an
  instrument-rack chain have per-chain output?). Add a `/song-workflow`/conventions pointer so it's
  discoverable.
- **Referenced from every teaching error.** When a capability probe rejects an unsupported op, the
  error names the node kind, the feature, and points back to the matrix — closing the loop instead of
  leaving the agent to guess: e.g. *"output routing is not addressable on a `master` node (it has no
  output route). Supported nodes for routing: track, drum-rack chain. See
  ableton://reference/node-feature-matrix."*

This makes the sparse matrix a *feature*, not a limitation the agent rediscovers by trial. Generation
should be **single-source**: the matrix resource and the runtime capability probes derive from one
table, so docs can't drift from enforcement (a probe that says "no" and a doc that says "yes" is the
exact incoherence this avoids). Where Live's truth is device-specific (third-party plugins), the
published cell is "probe at runtime" and the teaching error carries the probed result.

### 2b. Tri-state capability model + the lightweight stub (user refinement, 2026-06-15)

A binary "supported / not" is a lie — "✗" was doing two different jobs. Every (feature × node-kind)
cell is **tri-state**:

- **SUPPORTED** — built; the real handler runs.
- **NOT_IMPLEMENTED** — Live *can* do it on this node; Hallucinote hasn't built the op. A roadmap gap a
  request can change. → a lightweight **stub** returns a typed `NOT_IMPLEMENTED` response (+ backlog
  pointer).
- **UNSUPPORTED_IN_LIVE** — Live's LOM genuinely can't, on this node kind/version. A hard wall the
  agent must route around, not wait for. → typed teaching error.

**Why tri-state matters: it's *actionable*.** It tells the agent (and humans) whether to *wait / file a
request* (NOT_IMPLEMENTED) or *route around it permanently* (UNSUPPORTED_IN_LIVE) — never a generic "no."

**The stub mechanism (genuinely lightweight).** The single-source table (§2a) carries each cell's
state. The dispatcher consults it: SUPPORTED → real handler; NOT_IMPLEMENTED → one **generic stub
responder** (a deferred feature is *one table row*, not a handler — that's the whole cost);
UNSUPPORTED_IN_LIVE → typed teaching error. This makes every deferred feature (macro variations,
crossfade, send pre/post) **addressable + discoverable** — attempting one returns a clean typed stub,
not silence or "unknown action." The table is the one source the published resource, the stubs, and the
teaching errors all derive from — they can't drift. **(Critic note a):** the table is a **typed data
structure**, not prose, and a **cross-consumer consistency test** asserts all three readers (resource,
stub dispatch, teaching errors) resolve from it — "can't drift" is *enforced by a test*, not asserted.

**Two refinements (capability-probe rule):**
- **Static vs probe-determined.** Some UNSUPPORTED cells are *structural* (master has no output route —
  always true); some are *device-specific* (does this plugin expose `S/C On`? does this rack support
  chain zones?). The stub does **static-first, then probe**: structural cells answer from the table;
  device-specific cells resolve the node + capability-probe and return the probed evidence. "✗ on
  master" and "✗ on a plugin" are different mechanisms.
- **Version-scoped.** "Live 12.4 can't" may become "Live 13 can." Static cells note the Live version
  they hold for; device-specific cells **always re-probe** (never cache a stale "no") so a Live update
  isn't permanently blocked by a frozen verdict.

**Stubs are thoroughly documented, not bare flags (user, 2026-06-15).** A `NOT_IMPLEMENTED` cell isn't a
lone status — its single-source row carries: a one-line *description* of the feature, the *reason* it's
not built (vs Live-impossible), *Live-support evidence* (the LOM surface that proves Live can, so the
classification is honest), a *workaround* if one exists (e.g. "set in Live's UI, capture via
`/song-snapshot`"), and a *how-to-request* pointer (backlog tag). The published resource (§2a) renders
all of it; the runtime stub response and teaching errors carry/cite it. One source — doc, stub, and
error can't disagree. (Testing: assert every stubbed cell carries the documented fields.)

**Honesty caveat — classify by probe, not assumption (Chunk A). PROBED 2026-06-15 (probe-findings.md):**
Each cell's tri-state must be LOM-confirmed before it's documented. Probe-confirmed walls
(`UNSUPPORTED_IN_LIVE`): **send pre/post-fader mode** (no pre/post property on `MixerDevice` or the send
`DeviceParameter`); **macro→param mapping target** (LOM exposes `has_macro_mappings`/`macros_mapped`
presence only, never the destination); **per-drum-chain audio output routing**
(`available_output_routing_types` raises on DrumChain); **monitor state on return/master** ("no
monitoring state"). Probe-confirmed `NOT_IMPLEMENTED` (buildable): macro **values/names**, macro
**variations** (`variation_count`/`store_variation` present), crossfade assign
(`MixerDevice.crossfade_assign`), and **return/master input+output routing** (30 real routing types —
the earlier OQ4 `UNSUPPORTED_IN_LIVE` guess for *input* was wrong). The tri-state records the *probed*
truth, never a guess.

This subsumes the OQ2 "defer with a logged note" idea: deferred features aren't logged-and-invisible —
they're **stubbed as documented NOT_IMPLEMENTED**, machine-visible and one row from becoming real.

---

## 3. Build sequencing — one release, chunked build/test

**Release gate (user, 2026-06-15): ship only when the full in-scope feature set is built + tested** — no
foundation-only or partly-featured release. But the *build* is chunked granularly: each chunk is built
and tested on its own before the single release. The tri-state stub (§2b) is the build-time scaffold
that makes this clean — after the addressing chunk, every unbuilt feature answers `NOT_IMPLEMENTED`, so
the addressing chunk is independently testable and each later chunk is an isolated stub→handler
conversion. Big-bang (rewrite addressing + all features in one undifferentiated push) is the risk this
chunking avoids.

**Chunk A — the uniform address primitive [WIRE FLIP → re-vendor].**
Land the *full* `NodeAddr` on the wire + the one resolver, DB path-builder, and renderer — **all
terminal kinds** (`track`/`return`/`master`/`device`/`chain`/`drum_pad`), since addressing is holistic
(OQ1). Stand up the single-source capability table + generic stub responder (§2b) so every not-yet-built
feature answers `NOT_IMPLEMENTED` and every Live-impossible cell answers `UNSUPPORTED_IN_LIVE`.
**Migrate** existing `device_path` callers to `NodeAddr` (no dual surface). **(Critic note d):** this is
*not* throwaway-deletion — `device_path` is a **shipped contract** (DEEP-RACK-ADDR, consumed by ~5 ops:
get_parameters/set_parameter/load/write_envelope/perform). Migrating it must **operator-verify every
migrated caller in Live**, not just the new path; the no-dual-surface principle holds, but the
verification surface is the full shipped contract.
**Hard predecessor (Critic note c): probe the `drum_pad` and addresses-as-value LOM surfaces BEFORE
freezing the wire.** Freezing the terminal enum / value grammar on an unprobed surface is the one place
OQ1's "design against real consumers" discipline is at risk — so the probe gates the freeze, it doesn't
follow it.
Test: resolver × every terminal × depth; capability table tri-state; stub responses.

**Chunk B — params read-side durability (the proven pain; the vertical slice that proves the pipeline).**
Params already write/store/push at depth-N — only *acquisition* is missing. Deterministic `capture
execute` on the `client.send` bridge (retire the agent-orchestrated `capture_plan` — its *code* walks
one nesting level by design and *raises* on rack-in-rack, but agent orchestration doesn't reliably
realize even that depth-1: swell captured 0 nested, §6.5); extend the pull planners depth-N via
`NodeAddr` (closes gap #17b); the
acquisition + symmetry tests DEEP-RACK-ADDR couldn't write (§6.4). Proves capture→DB→push end-to-end on
the one feature that's otherwise complete. This is the load-bearing fix for "SAVE the .als or lose it."
Capture filters to non-default params via `default_value` (OQ5, §8) — uniform top-level + nested — so the
read-side never stores the "99.9% defaults"; the `default_value` field is added to `get_parameters` in
Chunk A's wire flip.

**Chunks C…N — one per in-scope feature, each a stub→handler conversion.** Migrate the shipped-8 onto
`NodeAddr`, then build the new ones (per-drum routing/choke, macros, zones, chain mute/solo, …). Each =
schema columns + capability probe + capture/push + tests, reusing `NodeAddr` — **no addressing
re-design** (the `NodeAddr` grammar is frozen in Chunk A; features never change the address). **But
(Critic W2): each chunk touches `handlers/`/`actions/`, which are in `_FINGERPRINT_PATHS`, so it *does*
flip the MCP fingerprint → re-vendor.** Since we release once, that's **one** re-vendor at release; during
the build, re-vendor per chunk to test against Live. The benefit of freezing the address isn't
"no re-vendor" — it's "no re-*design* of the address; features slot in without touching the grammar."
Independently testable because the stub isolated it; order by demand (per-drum routing — the origin case
— first).

**At release:** in-scope features are SUPPORTED; consciously out-of-scope minors ship as honest
`NOT_IMPLEMENTED` stubs (pending OQ2 confirm); Live-impossible cells are `UNSUPPORTED_IN_LIVE`. This
supersedes the earlier "Slice 1 rides device_path" alternative (OQ1: full shape up front) and the "land
features only when a song needs them" framing (in-scope features all build before the one release).

---

## 4. What we delete / correct (Coherent Artifacts)
- **Delete** the false "Python can't call MCP tools directly" claim in `capture.py` + `capture_cli.py`
  docstrings — the engine already calls `client.send` (push/pull execute). The belief shaped the broken
  capture design.
- **Correct** the bug record + `DEV-7K4H`: they read "depth-N *addressing* is the gap," but addressing
  shipped. The real residual is "acquisition + the rest of the node-address matrix."
- **Correct** DEEP-RACK-ADDR build-plan Chunk 2 status: "capture + push depth-N ✓" → "*replay* + push
  depth-N ✓; *acquisition* deferred to this work."
- Once Slice 1 lands, retire the agent-orchestrated capture prose in `/song-snapshot` + `capture_plan`.

---

## 5. Risks
- **Second addressing change in two days.** DEEP-RACK-ADDR just shipped `device_path`. Generalizing now
  means migrating those call sites again. Justified: it's a strict superset and lands the *final* wire
  shape so features never re-flip it. The alternative (per-feature addressing) is the instance-patching
  we're killing. Confidence: high this is the right time, given the user's "solve once" decision.
- **Wire flip → re-vendor** (Chunk A touches `actions/` + `handlers/`). Per Critic W2, feature chunks
  C…N also touch `handlers/`/`actions/` (in `_FINGERPRINT_PATHS`) → they re-vendor too; what's frozen is
  the *address grammar*, not the fingerprint. One re-vendor at release; per-chunk during Live testing.
  Coordinate with any Live-side session.
- **Connection contention** — capture opens `client.send` connections concurrent with the MCP server.
  Proven safe: the Remote Script is thread-per-client, no single-owner lock; push already does this.
- **Determinism** — a node's positional path from the DB must match the live preset's structure. Same
  assumption push already relies on; resolver teaching-errors on a missing path rather than mis-targets.
- **Scope discipline** — Slice 2+ features land *when a song needs them*, not speculatively
  (Proportional Effort). The address is the only thing built ahead of need.

---

## 6. Verification log (2026-06-15, first-hand against source)
All load-bearing claims re-checked against code (two scouts disagreed once on capture, so each direct):
1. **Push is genuinely depth-N** — `push/devices.py:406,417-424`: computes `device_path` from
   `get_device_nesting_path`, recurses unbounded; `:355-356` attaches it. ✓
2. **Push runs on the bridge, no agent** — `push_execute.py:10`; `execute_push(send_fn=…)` via
   `client.send`. ✓
3. **Capture has no `execute`** — `capture_cli.py:159-198`: only `plan`/`diff`/`merge`/`migrate`. ✓
4. **The regression test never exercised acquisition** — `test_push_devices.py:417-437`
   (`test_capture_replay_push_roundtrip_depth2_nested_param`) builds the nested snapshot as a **dict
   literal** and feeds it to `replay_capture`; covers replay→push, skips Live→JSON. It *can't* cover
   acquisition — there's no `capture execute` with an injectable `send_fn`. False green. ✓
5. **swell's real snapshot — worse than "depth-1"** — audit of
   `../hallucinote-songs/songs/swell/captured_session.json`: 64 top-level devices (30 with params),
   **0 nested devices, deepest = depth 0** — despite `/song-snapshot` prose saying "recurse to any
   depth." Realized depth ≠ prose depth ⇒ deterministic `capture execute` (Slice 1) is load-bearing. ✓
   **Interpretation (per §1b):** swell *does* have nested devices live — they arrive from loading a
   single rack preset. The "0 nested" means the snapshot records the *load unit* but never the
   *addressing skeleton + dialed deltas* on the internals — which is precisely why a deep by-ear value
   reverts on rebuild. The finding is more damning, not less: the nested devices exist and are
   invisible to capture. **Precision (Critic W1):** `capture_plan`'s *code* DOES walk one nesting level
   (`capture.py:631`; rack-in-rack explicitly out of scope, "replay raises on encounter") — so "depth 0"
   is the *empirical result* in swell (agent orchestration not realizing even depth-1, plus swell's deep
   params being rack-in-rack beyond the supported level), NOT a code ceiling. This *strengthens* the case
   for deterministic `capture execute`: agents don't reliably execute even the depth the code supports.

The bridge the user asked about (direct Python→Live, simple API) **already exists** as
`hallucinote_mcp.client.send(Request(tool, action, params))` — a generic TCP RPC to the Remote Script
(port 9878, multi-client). A *new* parallel bridge would duplicate handler intelligence (capability
probing, enum handling, address resolution) → rejected. Adopt the existing one.

**Completeness audit (2026-06-15) — "is there a 6th/7th feature hiding?" Yes.** Two parallel sweeps
(codebase coverage + LOM surface) found the "five" undercounts: the codebase already authors **~8**
distinct node features (the five collapsed the routing family — output is separate from **input** and
**monitor** — and missed **device sidechain source** and **name/color metadata**), and the LOM holds
more unbuilt (macro mappings, **macro variations**, zones, **drum-pad choke/transpose**, crossfade
assign, send pre/post). The feature set is **open**, so the design's frozen unit is the *address*, not
the feature list. Two findings affect the wire freeze: **(a)** `terminal` needs a **`drum_pad`** kind
(choke/pad-mute/transpose live on `DrumPad`, not its `Chain`); **(b)** a `NodeAddr` must be a valid
operation **value** (sidechain source + macro targets are addresses). Both folded into §1/§2.

---

## 7. Testing strategy
- **Resolver** unit tests: every `terminal` kind × depths 0/1/2/3, out-of-range, non-rack descent,
  terminal-kind mismatch, depth cap.
- **DB path-builder**: node → positional path for each terminal kind; root → empty path.
- **Renderer**: positional addr → stable named string; round-trips names from resolved rows.
- **Capability probe**: each feature op teaching-errors on an unsupported node kind (the §2 holes).
- **Capability-table cross-consumer consistency (Critic note a):** one test asserts the published
  resource, the stub dispatch, and the teaching-error text all resolve from the single typed table — so
  doc/stub/error can't diverge.
- **`default_value` filter** (OQ5): non-default detection from a fixture param set incl. a quantized
  param that *raises* on `default_value` (the Snap case) → falls back correctly; zero read-before-write.
- **Acquisition round-trip (the gap §6.4 missed):** fake `send_fn` returns a depth-2 nested tree with a
  dialed param → `capture execute` → param in DB → push → re-emitted. No Live.
- **Per-feature round-trips** as each Slice-2 feature lands (routing, mixer-state, …).
- **Operator (Live):** set swell `21 Voice Lead` `LFO 1 Sync` (depth-2) via `NodeAddr`, `/song-snapshot`,
  rebuild + push, confirm it survives — *without* saving the .als.

---

## 8. Open questions for the user
1. **Slice 0 timing — DECIDED (2026-06-15):** land the full `NodeAddr` wire shape up front. Rationale:
   DEEP-RACK-ADDR is validated (refactor-on-top risk gone) and everything ships in one release (no
   partly-shipped state), so the only surviving concern — designing the address against real consumers
   — becomes a *design-order* discipline: **design every in-scope feature's addressing needs before the
   wire freeze.** Build params first as the thin vertical slice; the address still lands in Slice 0.
2. **Release feature scope — RESOLVED (2026-06-15):** one release, gated on the full in-scope set built +
   tested (§3); build chunked granularly with the stub as scaffold. **Build set:** the 8 (migrated) +
   per-drum routing/choke + macros + zones + chain mute/solo. **Shipped as documented `NOT_IMPLEMENTED`
   stubs:** macro variations, crossfade assign, send pre/post (the last pending Chunk-A probe — may be
   `UNSUPPORTED_IN_LIVE`, §2b). Stub documentation is thorough (description/reason/Live-evidence/
   workaround/request), single-sourced.
3. **`drum_pad` terminal (§1) + addresses-as-values (§1) — PROBE-RESOLVED (2026-06-15):** `drum_pad`
   **DROPPED** (per-drum features are on the DrumChain → `chain` terminal). NodeAddr-as-value **KEPT but
   scoped to a track-terminal NodeAddr** (sidechain source); macro→param mapping targets are not
   LOM-readable so they don't justify a device/param-depth value. See §1.5 / probe-findings.md.
4. **`returns`/`master` routing scope — RESOLVED (2026-06-15) + PROBE-CORRECTED:** fold into the routing
   chunk, don't track separately — routing is a `NodeAddr` op + capability probe, so return/master
   routing is "the same op on a return/master terminal." Build return + master *output* routing.
   **CORRECTION (probe-findings.md): return/master *input* routing is ALSO buildable** — the LOM exposes
   30 real `available_input_routing_types` on both (the earlier "no audio input ⇒ `UNSUPPORTED_IN_LIVE`"
   was wrong); classify input as `NOT_IMPLEMENTED`. Only **monitor state** on returns/master is
   `UNSUPPORTED_IN_LIVE` ("no monitoring state"). Routing-feature design flag: split targets into
   **portable** (internal — Master/track/Sends-Only) vs **machine-specific** (physical I/O) — capture
   both, warn on cross-machine push of physical targets (same hazard as `browser_path` portability).
5. **Capture granularity (§1b) — RESOLVED (2026-06-15, live-probed):** filter at capture via the LOM
   `DeviceParameter.default_value`, applied **uniformly** to top-level + nested (don't special-case
   nested). Probe evidence: `default_value` returns a real float on continuous params (the bulk where
   bloat lives) but **raises `"no default value available for this type of parameter"` on some
   quantized/enum params** (confirmed on Simpler "Snap"). There is **no `is_modified`/`is_default`
   boolean** — comparison is the mechanism. Design:
   - Add `default_value` to the `get_parameters` response (small handler change — rides Chunk A's wire
     flip). It returns with `value` in the **one read per device** capture already does → default-detection
     is **zero extra reads**, and there is **no read-before-write at push** (capture stores only
     non-defaults; push emits only what's stored).
   - Store only params where `value != default_value`. Kills the "thousands of params, 99.9% defaults" bloat.
   - **Fallback** for params where `default_value` raises: always-capture the minority; OR (complete +
     intent-isolating) a **bounded preset-reference** — load each *unique* preset once, cache post-load
     values, diff instances against the cache (cost O(unique presets), not O(devices)).
   - **Caveat:** `default_value` is the *intrinsic* default, not the *preset-loaded* value, so this
     over-captures the preset's own non-defaults (harmless for durability). Isolating *only* by-ear intent
     needs the bounded preset-reference — defer unless preset-heavy racks bloat.
   - **Falsifiable deferral trigger (Critic note b):** swell *already* uses rack presets, so the
     "defer the bounded cache" call is testable, not hand-wavy — after Chunk B, measure swell's captured
     non-default count per device + total snapshot growth; if a single preset contributes more than ~25
     over-captured (preset-non-default-but-not-by-ear) params, or snapshot size grows >2× vs the
     by-ear-delta count, build the bounded preset-cache. Otherwise the intrinsic-default filter stands.
6. **Governance wrapper — DECIDED (2026-06-15): file now, build follows.** This is a *now* step, not
   deferred work and not a parallel feature: promote NODE-ADDR to a tracked `/prawduct:backlog` item
   *before* the build plan, so the build proceeds under governance (item → this doc → build plan → chunked
   build + Critic per chunk). The build set is unchanged (one release, Chunks A→N). Reconcile the
   overlapping items: **DEV-7K4H** → *subsumed*; **macro-mapping** → a *feature chunk* in-release;
   **analysis-extract** → *linked, unblocked-by-Chunk-A* (the only piece that may be a fast-follow, since
   it *consumes* NODE-ADDR rather than being part of it). Lands "node-path addressing" as a requirement
   before code.
