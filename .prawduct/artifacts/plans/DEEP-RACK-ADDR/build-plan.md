# DEEP-RACK-ADDR — Build Plan

Branch: `fix/deep-rack-addressing` (to create). Critic mode: **cumulative** (base `develop`),
per chunk for medium+ chunks. Design: `./design.md`.

Resolves the Severity-H capability gap: rack devices nested 2+ levels deep are unreadable,
unsettable, un-automatable, and — the killer — **non-durable** (capture stores depth-1 params,
push drops them, so a `build.py` rebuild reverts any deep fix).

## Requirements Confidence: **High**
- Firsthand-scoped bug + four independent code investigations + a live probe of the exact
  swell case (track 4 → "Guitar-Dual Amped Heavy" → nested "Guitar" rack → "Guitar Dead
  Notes" MultiSampler at depth 2).
- DB verified depth-N capable already → no schema/mutator changes.
- Addressing model locked: positional `device_path` + name read-back.

## Dependency ordering (critical)
Chunk 1 (wire primitive + resolver) MUST land before Chunk 2 (push), or push will fall back
to the depth-2 `set_parameter_in_rack` and silently re-cap depth at 2 (design §8). Chunks 3
and 4 depend on Chunk 1's primitive; they are independent of each other.

---

### Chunk 1: canonical `device_path` primitive + shared resolver (read/set/enumerate) [FLIP]
Thin vertical slice — after this you can READ and SET a param at any depth in a live set
(not yet durable).
- **handlers/device.py:** add `_resolve_device_path(parent, device_index, device_path)` — the
  one recursive walk; teaching errors per level + depth cap.
- **actions/device.py:** add optional `device_path` ParamSpec to `set_parameter`,
  `get_parameters`, `load`. `get_device_chains` recurses → reports each device's
  `{name, class_name, is_rack, device_path}`.
- **Retire** `set_parameter_in_rack` + `load_in_rack` (fold into the path); grep+update
  skills/ + docs/ references (discovery sub-step — no silent break).
- **Tests:** `_resolve_device_path` unit (depth 0/1/2/3, out-of-range, non-rack descent, cap);
  handler depth-N get/set/enumerate against a synthetic nested structure.
- **Re-vendor:** required (actions/ + handlers/ flip the fingerprint).

### Chunk 2: snapshot durability — capture + push depth-N (THE unblocker)
- **capture.py:** delete the `_depth > 0` raise; replay already handles params at any depth.
- **db/queries.py:** add `get_device_nesting_path(conn, device_id)` → positional path from the
  DB hierarchy alone (no live round-trips).
- **sync/push/devices.py:** recurse `get_device_chains_for_rack_device` → emit `set_parameter`
  with the unified `device_path` for each nested device's dialed params. (Nested devices are
  NOT loaded by push — they arrive with the rack preset; push only sets their params.)
- **Tests:** capture→DB→push round-trip of a depth-2 nested param — assert re-emitted on push
  (the swell regression: a deep fix survives a rebuild). `get_device_nesting_path` unit.
- **No re-vendor** (engine/sync only; no wire-shape change) — but depends on Chunk 1's wire.

### Chunk 3: nested-rack `device_parameter` automation [FLIP]
- **actions/automation.py:** add `device_path` to `write_envelope` + `perform_batch`.
- **perform handler `_arc_addressing`:** resolve target via `_resolve_device_path` (reuse).
- **sync/push/envelopes.py `classify_envelope_route`:** lift the
  `parent_rack_device_id → unroutable` gate; route nested → `perform` with the path from
  `get_device_nesting_path`. Keep the *session-clip* nested case as an honest teaching skip
  (Live 12.4 LOM gap — `Clip.create_automation_envelope` can't address nested params).
- **Tests:** nested `device_parameter` envelope routes to `perform` + materializes; session-
  clip nested case emits the documented skip (not a silent drop).
- **Re-vendor:** required (actions/automation.py flips the fingerprint).

### Chunk 4: voices accessor (ask #4 — `MultiSampler`)
- Probe via the new depth-N `get_parameters`: is "Voices" a `DeviceParameter`?
  - **Yes** → already covered; add a round-trip test, document, done.
  - **No (LOM property)** → add a generic settable-property accessor on the device handler
    (probe + adapt, never whitelist). Durability for non-parameter properties is out of the
    `device_parameters` table scope → flag a small follow-up explicitly (do not silently
    drop).
- **Tests:** per the branch taken.
- **Re-vendor:** required only if the property accessor adds a wire action.

---

## Re-vendor note
Chunks 1 and 3 flip the MCP fingerprint → `Re-vendor: required`. Bundle into one re-vendor at
release / dev (`/mcp` respawn THEN `/ableton-mcp-install`, in that order — see the
MASTER-PREFADER-TP re-vendor sequence: server must respawn so running==disk before the
version-pinned install).

## Coordination
This branch edits MCP handlers + the sync layer — possible overlap with a parallel session.
Resolve before building: worktree-isolate this branch, or confirm the other session is
song/Live-side. (Design + planning are collision-free; building is not.)

## Status
- [x] Chunk 1: canonical device_path primitive + shared resolver
- [ ] Chunk 2: snapshot durability — capture + push depth-N
- [ ] Chunk 3: nested-rack device_parameter automation
- [ ] Chunk 4: voices accessor

**Context (Chunk 1 done):** `_resolve_device_path` (handlers/device.py) is the
one canonical descent — `device_index` + `[{chain_index, device_position}…]` to
any depth, positional (never `is`), teaching error per failed step + depth cap
16. `set_parameter` / `get_parameters` / `load` (with `chain_index`) gained
optional `device_path`; `get_device_chains` now recurses the whole tree and
reports `is_rack` + `device_path` per device. `set_parameter_in_rack` /
`load_in_rack` RETIRED (zero production callers; tests migrated, docs +
conventions/gaps guides updated). MCP suite green (1226). Re-vendor required
(actions/ + handlers/ flip the fingerprint) — bundle with Chunk 3 at release.
Next: Chunk 2 (capture + push depth-N) — push must emit `set_parameter` with
`device_path`, NOT the retired in_rack triple (design §8 risk).
