---
lifecycle: completed
archived: 2026-09-08
unbuilt_at_archive: "no readable `## Status` roster — completeness cannot be read, and an unreadable plan is not evidence of completion"
maintained: false
---

> **Archived — no longer maintained.** This plan records what was built, not what will be. Do not edit it to reflect later changes; write those where they are true.

# NODE-ADDR Chunk C — implementation map (per-DrumChain authorship)

Origin case for the whole design: per-drum `choke_group` + `out_note` (MIDI
transpose) on a `DrumChain`, reached via the **`chain` terminal** Chunk A froze.
Stub → handler conversion + the feature half (schema/capture/push/pull).

## Scope decision (DECIDED 2026-06-15)
- **C ships `choke_group` + `out_note` only.** Chain `mute`/`solo` **write** is
  deferred to **Chunk F** (chain mixer-state: vol/pan/sends/mute/solo land
  together as "mixer state"). The build plan's "(+ mute/solo if not already in
  F)" permits this; F's spec explicitly owns mute/solo write. Avoids
  double-coverage. The matrix `choke_out_note` feature is narrowed to drop the
  "chain mute-solo" mention (mute/solo lives solely under `mixer_state`→F).
- **Non-default capture filter mirrors Chunk B exactly** (capture stores only
  non-default; push emits only stored; no read-before-write at push):
  - `choke_group`: store iff `!= 0` (0 = Live's "no choke group").
  - `out_note`: store iff `!= in_note` (a real transpose; identity is the
    default). `in_note` read transiently at capture for the compare — NOT stored
    (it's positional/read-only, not authorable).
  - Documented boundary (same class as Chunk B params): clearing a property back
    to its preset default isn't pushed — the reloaded rack preset's default
    stands. A drum kit ships choke groups only on hats; this is the right tradeoff.
- **Capability probe** lives in the handler (`determination='probe'`): a plain
  instrument-rack `Chain` has NO `choke_group`/`out_note` (LIVE-CONFIRMED
  2026-06-15 on the scratch 808 *Instrument* Rack — `describe` showed only
  mute/solo/mixer_device, no choke_group/out_note). Handler raises a teaching
  error for a non-DrumChain (mirrors `set_sidechain` on a device lacking S/C).

## Integration points (9)
1. **schema.sql** (device_chains) + **connection.py `_ADDED_COLUMNS`**: add
   `choke_group INTEGER`, `out_note INTEGER` (nullable). Canary requires both.
   Update the create_device_chain "no non-identity fields" comment.
2. **db/events.py**: `DEVICE_CHAIN_PROPS_SET = "device_chain_props_set"`.
3. **db/mutations/devices.py**: `set_chain_properties(conn, chain_id, *,
   choke_group=_UNSET, out_note=_UNSET, ...)` — UPDATE + emit, change-detecting
   (returns MutatorResult unchanged/updated). `create_device_chain` stays
   identity-only.
4. **capture.py**: `chain_authored_props(chain_entry) -> dict` helper (the
   non-default filter, single source). `_capture_nested_chains` writes
   choke_group/out_note into the snapshot chain dict; `_replay_rack_chains` calls
   `set_chain_properties` after `create_device_chain`. Pull imports the helper.
5. **handlers/device.py `_describe_chain`**: surface `choke_group`/`out_note`/
   `in_note` (getattr→None; add to entry only when present — plain chains
   unchanged). Outside the `detail=='full'` gate (summary capture needs them).
6. **handlers/device.py** new `set_chain_property_handler(context, *, node,
   choke_group=None, out_note=None)`: resolve via `resolve_node_addr` (require
   `terminal=='chain'`), capability-probe (`hasattr`), set the provided
   `chain.choke_group`/`chain.out_note`, echo the resolved address. Export in
   `__all__`. (SHIPPED with dedicated `choke_group`/`out_note` int params rather
   than a `property`/`value` pair — avoids colliding with the tool's
   string-typed `value` param and reads cleaner on the wire; pass ≥1.)
7. **actions/device.py**: `register(Action(name='set_chain_property', ...))` —
   `node_addr_spec()` + `choke_group` (int, optional, min 0) + `out_note` (int,
   optional, 0..127).
8. **sync/push/devices.py**: in `_emit_nested_param_writes`, after recursing a
   rack's chains, emit `set_chain_property` ToolCalls for each chain with a
   stored non-NULL choke_group/out_note, addressed by
   `build_node_addr(parent_kv, device_index=top_device_index,
   device_path=<path to the rack>, terminal='chain', chain_index=position)`.
   (Top-level drum rack: path=None. The rack's own path = get_device_nesting_path.)
9. **sync/pull/devices.py `_diff_nested_chains`**: after create/match of the
   chain row, diff `chain_authored_props(chain_entry)` vs the DB row → call
   `set_chain_properties` on change.
10. **node_features.py**: flip `choke_out_note` chain cell → `SUPPORTED`
    (determination='probe'); narrow title/description to choke+out_note. Update
    the cross-consumer test's expected SUPPORTED-cell count.

## Tests
- mutator: set_chain_properties create/update/unchanged + event emitted.
- capture filter: choke 0 / out_note==in_note dropped; non-default stored;
  plain-chain (no attrs) stores nothing.
- replay: snapshot chain with choke/out_note → DB row carries them.
- push: a stored choke_group/out_note emits a `set_chain_property` chain-terminal
  ToolCall; default-only chain emits none.
- pull: `_diff_nested_chains` writes a changed choke/out_note via the mutator;
  unchanged → no mutation.
- round-trip (the build-plan signal): author choke+out_note in DB → push plan
  emits → (fake-execute) → pull diff re-lands the same DB row.
- matrix: cross-consumer consistency still green after the flip.

## Live verify (operator-gated — enqueue, like A & B)
The scratch set has only an *Instrument* Rack (no DrumChain), and the new handler
isn't on the running server (primary-repo `--plugin-dir`). Positive round-trip
(choke+out_note on a real DrumChain) + negative (plain Chain → teaching error)
go to operator-verification.md; needs re-vendor + a loaded Drum Rack.
