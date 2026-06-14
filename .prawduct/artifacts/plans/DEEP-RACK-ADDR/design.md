# DEEP-RACK-ADDR — Holistic Design

**Status:** COMPLETE (2026-06-13) — all 4 chunks shipped (cumulative Critic: 0 blocking). Re-vendor required at release (Chunks 1 & 3 flip the MCP fingerprint); ask #4 property branch + the deep-param live checks are operator-verification-pending.
**Source:** `incoming-bugs/2026-06-14-nested-nested-rack-params-unreachable-read-set-automate-snapshot.md` (Severity H).
**Scope decision (user):** all four asks — depth-N read/set/enumerate, snapshot durability, nested automation, voices accessor.
**Addressing decision (user):** positional `device_path` + name read-back.

---

## 1. The reframe — the data model is already right

The Hallucinote DB already represents rack nesting to **arbitrary depth** with **zero**
schema or mutator work needed:

- `device_chains.parent_rack_device_id` is a self-referential FK — a chain hangs off a
  track, a return, **or another rack device** (CHECK enforces exactly one parent).
- `device_parameters` is keyed flat by `(device_id, name)` — a param on a device five
  racks deep is structurally identical to a top-level one.
- Mutators already recurse unbounded (`_resolve_chain_song` walks parent links to the song).
- Positions are stored and 1-based everywhere: `devices.position` (within its chain),
  `device_chains.position` (within its parent rack). **A full positional path is
  computable from the DB alone — no live LOM round-trips.**

**The bug is not a data problem.** It is a *missing addressing primitive*, reinvented six
times above a clean model, each with its own depth ceiling:

| Surface | Ceiling today |
|---|---|
| MCP `get_parameters` | depth-1 (top-level only) |
| MCP `set_parameter_in_rack` | depth-2 via a bespoke triple `(device_index, chain_index, nested_device_position)` |
| MCP `get_device_chains` | depth-2, no recursion |
| Capture (`capture.py`) | depth-1, then **raises** "nested-nested not supported" |
| Push (`push/devices.py`) | **depth-0** — only top-level chains are walked |
| Automation (`classify_envelope_route`) | depth-0, separate wire surface, `unroutable` for `parent_rack_device_id != NULL` |

Worst detail: **capture writes depth-1 params to the DB, but push is depth-0** — so even
one-level-nested params are captured, stored, and then silently dropped on the next push.
The durability bug bites at depth-1, not just depth-2.

---

## 2. The canonical primitive

One address shape, one resolver, spoken by every surface.

**Wire shape (additive, backward-compatible superset):**

```
parent:       track_index | return_index | master      (unchanged)
device_index: 1-based position of the TOP-LEVEL device on the parent's main chain (unchanged)
device_path:  optional list of { chain_index: int, device_position: int }   (NEW)
              each step 1-based; descends one rack level: pick chain `chain_index`
              inside the current rack, then device `device_position` in that chain.
```

- `device_path` **absent/empty** → the top-level `device_index` device. This is exactly
  today's `set_parameter`/`get_parameters` behavior — so existing callers are unchanged.
- `device_path = [{chain_index, device_position}]` → one level deep (replaces the
  `set_parameter_in_rack` triple: that triple *is* `device_index` + a single step).
- `device_path = [s1, s2, …]` → arbitrary depth.

`device_index` stays separate from `device_path` because the top-level device sits on the
track's *main* chain, which has no chain index. The steps in `device_path` each carry a
`chain_index` because they descend into *racks*, which do. This mirrors the LOM exactly.

**Shared resolver** (`handlers/device.py`):

```python
def _resolve_device_path(parent, device_index, device_path):
    """Resolve (parent, top-level device_index, [{chain_index, device_position}…])
    to a single Device, with a teaching error at each failed step."""
    dev = _resolve_device(parent, device_index)           # existing depth-0 resolve
    for depth, step in enumerate(device_path or (), start=1):
        chains = _resolve_rack_chains(dev)                # raises if dev isn't a rack
        chain  = _resolve_chain_by_index(chains, step["chain_index"])
        dev    = _nth_device(chain, step["device_position"])
    return dev
```

This single loop **replaces every inline depth-hardcoded walk** in `get_parameters`,
`get_device_chains`, `set_parameter`, `load`, and `set_parameter_in_rack`/`load_in_rack`.

**Read-by-name, address-by-path:** `get_device_chains` recurses to depth-N and, for each
device, reports `{ name, class_name, is_rack, device_path }`. The agent reads the human
names, then passes the reported `device_path` back to `set_parameter`/`get_parameters`. The
agent never hand-counts indices.

---

## 3. Per-surface design

### 3a. MCP read/set/enumerate (`actions/device.py`, `handlers/device.py`)
- Add an optional `device_path` `ParamSpec` (`type="list"`) to `set_parameter`,
  `get_parameters`, and `load`. The dispatcher validates the list type automatically.
- `get_device_chains`: recurse; emit each nested device's full `device_path` + names.
- **Retire `set_parameter_in_rack` and `load_in_rack`** — fold into `set_parameter`/`load`
  with `device_path`. (Their depth-2 triple is a strict subset of the path.) Per
  *no-backcompat-to-throwaway*: delete them, update any skill/doc references rather than
  keeping a parallel surface. (Discovery step: grep skills/ + docs/ for callers.)
- A defensive depth cap (e.g. 16) with a teaching error guards pathological input
  (Live can't actually nest cyclically, so this is a backstop, not a real limit).

### 3b. Capture (`src/hallucinote/capture.py`)
- Delete the `_depth > 0` raise. `_replay_devices` already handles `params_dialed` at any
  depth (it's the same function recursing) — removing the guard is the whole change on the
  capture side. The snapshot's `chains: [...]` array recurses to whatever depth Live has.

### 3c. Push (`src/hallucinote/sync/push/devices.py`) — THE unblocker
- Add `get_device_nesting_path(conn, device_id) -> [{chain_index, device_position}…]`: walk
  `devices.chain_id → device_chains.position / parent_rack_device_id` up to the
  track/return root, collecting positions, then reverse. **Pure DB, no live round-trips.**
- In the device push loop, after handling a top-level device, recurse via
  `Q.get_device_chains_for_rack_device(device_id)` → `Q.get_devices_for_chain(chain_id)`.
  For each nested device's dialed params, emit `set_parameter` with the computed
  `device_path` (NOT the depth-2 `set_parameter_in_rack` — that would re-cap depth at 2).
- **Push does not LOAD nested devices.** Nested devices arrive as part of the top-level
  rack's `preset_query` load (the rack preset is the unit of load, and is deterministic).
  Push only needs to *set dialed params* on the already-present nested devices. This keeps
  the durability fix to param emission + a recursion, and is why no schema/mutator change
  is required.

### 3d. Automation (`src/hallucinote/sync/push/envelopes.py`, perform handler)
- Add `device_path` to the `write_envelope` and `perform_batch` wire (`actions/automation.py`).
- Perform handler `_arc_addressing`: resolve the target via `_resolve_device_path` (reuse 3a).
- `classify_envelope_route`: lift the `parent_rack_device_id != NULL → unroutable` gate;
  nested `device_parameter` envelopes route to `perform` (continuous arrangement ride) with
  the `device_path` from `get_device_nesting_path`.
- **Honest remaining gap:** the *session-clip* route stays gated for nested devices — that's
  a Live 12.4 LOM limitation (`Clip.create_automation_envelope` can't address nested-rack
  params), not ours. Route nested envelopes to `perform` where possible; emit a clear
  teaching skip for the session-clip case. (Same posture the existing code documents.)

### 3e. Voices / ask #4 (`MultiSampler`)
- The depth-N `get_parameters` (3a) is the diagnostic. Two branches, decided by a probe at
  build time:
  - **Voices is a `DeviceParameter`** → already covered: readable, settable, and durable via
    the param-path work. Add a test asserting it round-trips; no new mechanism.
  - **Voices is a non-parameter LOM property** → add a generic *settable-property accessor*
    on the device handler (probe the property, attempt set, report settability as a
    finding — *capability-probe, never whitelist*). Durability for non-parameter properties
    is out of the `device_parameters` table's scope and would need a small follow-up
    (deferred sub-chunk; flag explicitly, do not silently drop).

---

## 4. The simplification (what we DELETE)

This refactor is net-negative lines where it counts:
- **Delete** `set_parameter_in_rack` + `load_in_rack` actions and their bespoke depth-2
  inline walks.
- **Delete** the `capture.py` `_depth > 0` raise.
- **Collapse** ~5 hand-rolled parent→rack→chain→device walks into one `_resolve_device_path`.
- **(Optional)** unify the per-action duplicated `track_index/return_index/master` specs
  (`_parent_addressing_specs()` is already a helper; finish the job) — low-risk tidy.

Six depth ceilings → one primitive + one resolver.

---

## 5. Edge cases & teaching errors
- Out-of-range `chain_index` / `device_position` at any step → teaching error naming the
  level and the actual count.
- A `device_path` step that lands on a non-rack device but more steps remain → teaching
  error ("step K targets a non-rack device; can't descend").
- Drum racks: a drum-rack pad's chain is addressable by `chain_index` like any chain (the
  primitive is uniform). A pad-name convenience accessor is a possible later nicety, not in
  scope.
- Push determinism: a nested device's `device_path` computed from the DB matches the loaded
  rack preset's structure because the preset is deterministic (same preset → same device
  tree). If a preset is ever non-deterministic, the param set will teaching-error on a
  missing path rather than silently mis-target.

## 6. Testing strategy
- **Unit:** `_resolve_device_path` (depth 0/1/2/3, out-of-range, non-rack descent, depth cap).
- **Unit:** `get_device_nesting_path` (DB hierarchy → positional path; top-level → empty).
- **Integration (the regression):** capture → DB → push round-trip of a depth-2 nested
  param; assert it is re-emitted on push (i.e. survives a `build.py` rebuild). This is the
  swell guitar failure, pinned.
- **Handler:** depth-N `get_parameters` / `set_parameter` / `get_device_chains` against a
  synthetic nested structure.
- **Automation:** a nested `device_parameter` envelope routes to `perform` and materializes;
  the session-clip nested case emits the honest teaching skip.
- **Operator (Live):** set the swell guitar's nested MultiSampler param via `device_path`,
  rebuild, confirm persistence.

## 7. Re-vendor & coordination
- Touches `actions/` + `handlers/` → **MCP fingerprint flips → re-vendor required** (bundles
  with any other pending flip).
- This refactor edits MCP handlers + the sync layer — the same areas a parallel session may
  touch. **Resolve coordination before building** (worktree isolation, or confirm the other
  session is song/Live-side). Design + this doc are collision-free.

## 8. Risks
- **Largest risk:** push emitting the depth-2 `set_parameter_in_rack` instead of the unified
  `device_path` — re-caps depth at 2 and looks fixed (swell passes) while the general case
  silently fails. The build plan orders the wire primitive + resolver *before* push depends
  on it, and the regression test uses depth-2 specifically.
- Session-clip nested automation stays a Live LOM gap — must be surfaced as a teaching skip,
  not silently dropped.
- Voices-as-property durability is a known deferred sub-item — flag, don't drop.
