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

1. **List devices on the target track.** `ableton_device(action='list', track_index=<target_track>)`. Look for `class_name='Compressor2'` (the probe response's internal identifier — distinct from the browser-display `name` field). If present at index N, skip step 2 and use that `device_index`.

2. **Load a Compressor** if none was found. `ableton_device(action='load', track_index=<target_track>, kind='Compressor')` (`kind` = browser display name; see `ableton://guides/conventions`), optionally `preset_uri=<compressor-uri>` if supplied. Capture the returned `device_index`.

3. **Resolve the source's display name.** `set_sidechain` addresses routing by display name, not by index — and for a track that's the **bare** `name` (`Drums`, `02 Kit Punk`), NOT the index-prefixed `1-Drums` (which fails); returns are letter-prefixed (`A-Reverb`) and the master is `Main`. Call `ableton_track(action='list')` and pass the source track's `name` verbatim.

4. **Configure sidechain routing.** `ableton_device(action='set_sidechain', track_index=<target_track>, device_index=<from step 2>, enabled=True, source_display_name=<name from step 3>, gain_db=0.0)`. Uses capability probing — works on any device with the canonical `S/C On` parameter (Compressor / Compressor2 / Glue Compressor / Gate / Multiband Dynamics + third-party plugins matching the naming). If source-routing fails on a device without `input_routing_*` (Glue / Gate / Multiband), use `ableton_device(action='capabilities', ...)` to confirm, then fall back to manual UI routing.

5. **Tune the compressor** (optional). `ableton_device(action='set_parameter', ...)`. Conservative starting point for a kick-triggered duck on a synth bus: Threshold=-24, Ratio=4, Attack=1ms, Release=120ms. Parameter names: `ableton://reference/device-params`.

## Notes

- 1-based indexing on the wire (`target_track=1` is the first track).
- `source_display_name` is what Live's routing dropdown shows — the index addresses the tool call; the name addresses the routing.
