---
name: mix-sidechain
description: Set up sidechain compression on a target track from a source track. Detects an existing Compressor or loads one, then configures sidechain routing via `set_sidechain` (capability-probed; works on Compressor, Compressor2, Glue Compressor, Gate, Multiband Dynamics + plugins with the canonical `S/C On` parameter).
argument-hint: <target-track> <source-track> [compressor-uri]
user-invocable: true
disable-model-invocation: false
---

# /mix-sidechain

You configure sidechain compression on `target_track` with the trigger coming from `source_track`. Reuses an existing Compressor on the target if present; otherwise loads one.

$ARGUMENTS

## Steps

1. **List devices on the target track.** `ableton_device(action='list', track_index=<target_track>)`. Look for `class_name='Compressor2'` (the probe response's internal identifier — distinct from the browser-display `name` field). If present at index N, skip step 2 and use that `device_index`. (`list` addresses the whole chain directly, so it keeps the flat `track_index`.)

2. **Load a Compressor** if none was found. `ableton_device(action='load', node={'parent': {'kind': 'track', 'index': <target_track>}, 'terminal': 'track'}, kind='Compressor')` (a `track` terminal loads onto the track's main chain; `kind` = browser display name, see `ableton://guides/conventions`), optionally `preset_uri=<compressor-uri>` if supplied. Capture the returned `device_index`.

3. **Find the source track's index.** The sidechain `source` is addressed as a NODE-ADDR value (the as-value shape), so you need the source's 1-based index, not its name. Call `ableton_track(action='list')` and note the source track's index.

4. **Configure sidechain routing.** `ableton_device(action='set_sidechain', node={'parent': {'kind': 'track', 'index': <target_track>}, 'device_index': <from step 2>}, enabled=True, source={'parent': {'kind': 'track', 'index': <source index from step 3>}, 'terminal': 'track'}, gain_db=0.0)`. The `source` node resolves to the source's name and applies it via the input-routing primitive (a return source is `{'kind': 'return', 'index': N}` + `'terminal': 'return'`). Capability-probed — works on any device with the canonical `S/C On` parameter (Compressor / Compressor2 / Glue Compressor / Gate / Multiband Dynamics + third-party plugins matching the naming). If source-routing fails on a device without `input_routing_*` (Glue / Gate / Multiband), use `ableton_device(action='capabilities', ...)` to confirm, then fall back to manual UI routing. For the special non-node sources (`Main`, `No Input`), call `ableton_device(action='set_input_routing', ...)` directly with `type_display_name`.

5. **Tune the compressor** (optional). `ableton_device(action='set_parameter', node={'parent': {'kind': 'track', 'index': <target_track>}, 'device_index': <from step 2>}, parameter_name=..., value_display=...)`. Conservative starting point for a kick-triggered duck on a synth bus: Threshold=-24, Ratio=4, Attack=1ms, Release=120ms. Parameter names: `ableton://reference/device-params`.

## Notes

- 1-based indexing on the wire (`target_track=1` is the first track).
- The migrated device actions (`load`, `set_parameter`, `set_sidechain`) address the device with a single `node` object (NODE-ADDR); the sidechain `source` reuses that grammar as a value (a track/return/master-terminal node whose name is the routing source).
