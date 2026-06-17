# Snapshot can't durably carry a nested-device param override on a `preset_query` instrument

**Date:** 2026-06-17
**Severity:** medium — silent durability loss. A hand-tweaked nested param (deep
inside a rack loaded via `preset_query`) is reverted on every from-scratch
rebuild+push, with no warning. The agent/user believes a documented mix fix is
durable; the rebuild silently restores the preset default.

## Repro (swell, real)

1. `21 Voice Lead` instrument is captured as `preset_query` "Synth Vox Ai" (an
   Instrument Rack → Wavetable). Portable, loads the preset incl. its wavetable
   waveform.
2. By ear, the nested Wavetable's `LFO 1 Sync` was set Free→**Tempo** (+ `LFO 1
   S. Rate` 1/8→**1/2**) live via MCP at path `[{1,1},{1,1}]` (decisions/22 #8).
   It was NEVER baked (the snapshot stores the instrument as `preset_query`, no
   nested chains/params).
3. A from-scratch rebuild + push (2026-06-16) reloaded the instrument from
   `preset_query` → **LFO reverted to Free / 1.00 Hz** (the out-of-time wobble
   the fix removed is back). No warning.

## Root cause

`capture._replay_devices` (and `create_device`) accept `preset_query` **XOR** a
full `chains` dump:
- `preset_query` → loads the preset (incl. un-parameterizable bits: the Wavetable
  waveform, samples). Only **top-level** `params_dialed` are applied afterward —
  there is no path to override a param on a NESTED device of the preset-loaded
  instrument.
- adding a `chains` array to a `preset_query` device doesn't override — `_replay_rack_chains`
  **creates** new nested chains (duplication/conflict).
- The full-capture refresh (`capture execute`) sidesteps this by DROPPING
  `preset_query` and dumping the instrument as explicit `chains` + `params_dialed`.
  But for a Wavetable the loaded **waveform is not a DeviceParameter**, so the
  dump can't reproduce the timbre — replacing `preset_query` with the dump risks
  losing the instrument's core sound. (Also bloats: swell's curated 52 KB snapshot
  → 1.3 MB full dump; 37k-line diff.)

So there is **no clean representation** for "load instrument X from its portable
preset, then override nested param P" — the exact shape needed for a by-ear tweak
on a preset instrument.

## Code locations (`src/hallucinote/capture.py`)

- `_replay_devices` (~L168): `preset_query = d.get("preset_query")` (~L202) →
  `create_device(..., preset_uri=preset_uri, preset_query=preset_query, ...)`
  (~L228, the two are mutually exclusive). The `params_dialed` loop (~L243) sets
  params **on `device_id` only** — the just-created top-level device, never a
  descendant. `nested = d.get("chains")` (~L292) → `_replay_rack_chains` (~L339)
  which calls `M.create_device_chain` + recurses `_replay_devices` (i.e. it
  CREATES the subtree; it does not resolve-and-override an existing one).
- Capture side: `compile_snapshot` / `assemble_snapshot_via_probes` (the
  `capture execute` path, ~L64 / nested walk ~L691) already probes nested params
  at every depth — but emits them only in the full `chains` dump form (and drops
  `preset_query` when it does). So the *read* exists; the *authorable override
  representation + the replay apply-path* are what's missing.
- `M.create_device` / `M.set_device_parameter` already accept a deep NodeAddr
  `path` (that's how the live MCP setter reaches `[{1,1},{1,1}]`), so the
  apply-path primitive exists; replay just never calls it for a preset device's
  descendants.

## Minimal synthetic repro (no swell needed)

1. Hand-author a snapshot with one track whose instrument is a rack via
   `preset_query` (e.g. any factory Instrument Rack wrapping a synth).
2. In Live, dial a param on a NESTED device of that rack (depth ≥ 1).
3. `capture execute` → the refresh DROPS `preset_query` and dumps the full
   `chains`; OR hand-add a `params_dialed`/`chains` override to the
   `preset_query` device and `build.py` + push → the override either duplicates
   chains or is ignored. Either way the by-ear nested value is not reproduced
   from the portable seed.

## Impact

Any nested param dialed by ear on a `preset_query` instrument is volatile across
rebuilds. Today the only durable homes are (a) the saved `.als` (lost on a
from-scratch rebuild), or (b) re-saving the instrument preset (manual, mutates a
shared user-library preset). decisions/22 #8's claim "a normal rebuild+push won't
reset it" is **wrong** — it does.

## Proposed fix

Add a `param_overrides` field to a `preset_query` (or `preset_uri`) device entry:
a flat list of `{path, name, value[, normalized][, value_items]}`, where `path`
is the NodeAddr descent (`[{chain_index, device_position}, ...]`) to the nested
device, relative to the loaded instrument. Example for the swell case:

```json
{
  "name": "Synth Vox Ai", "class": "Instrument Rack",
  "preset_query": {"root": "instruments", "pattern": "Synth Vox Ai"},
  "param_overrides": [
    {"path": [{"chain_index": 1, "device_position": 1},
              {"chain_index": 1, "device_position": 1}],
     "name": "LFO 1 Sync", "value": "Tempo", "value_items": ["Free", "Tempo"]},
    {"path": [{"chain_index": 1, "device_position": 1},
              {"chain_index": 1, "device_position": 1}],
     "name": "LFO 1 S. Rate", "value": "1/2", "normalized": 0.38095238}
  ]
}
```

Replay: after `create_device(preset_query=...)` loads the instrument, resolve
each override's nested device by `path` (the existing NodeAddr resolver) and
`set_device_parameter` on it — **no `create_device_chain`**, so no duplication
and the preset's waveform/samples survive. This keeps portability (the seed is
still `preset_query`) while making by-ear nested tweaks durable. Capture (`capture
execute`) should emit `param_overrides` for a preset-seeded device's non-default
nested params instead of dropping `preset_query` for a full dump.

Until shipped: document the manual MCP re-apply as a per-song runbook step (as
swell now does — see its `voice-lfo-sync-rebuild-fragility` annotation), and/or
warn at push time when a `preset_query` instrument had nested non-default params
at last capture.

## Workaround in use (swell, 2026-06-17)

LFO re-applied live via MCP; user saves the `.als`. A `decisions`/annotation
records the manual re-apply step for the next from-scratch rebuild.
