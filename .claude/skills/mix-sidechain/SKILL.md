---
name: mix-sidechain
description: Set up sidechain compression on a target track from a source track. Detects an existing Compressor or loads one, then configures sidechain routing via `set_sidechain` (capability-probed; works on Compressor, Compressor2, Glue Compressor, Gate, Multiband Dynamics + plugins with the canonical `S/C On` parameter).
argument-hint: <target-track> <source-track> [compressor-uri]
user-invocable: true
disable-model-invocation: false
---

# /mix-sidechain

You configure sidechain compression on `target_track` with the trigger coming from `source_track`. Reuses an existing Compressor on the target if one is already present; otherwise loads one.

$ARGUMENTS

## Steps

1. **List devices on the target track** to see if a Compressor is already present: `ableton_device(action='list', track_index=<target_track>)`. Look for `class_name='Compressor2'`. If present at index N, skip step 2 and use that `device_index`.

2. **Load a Compressor** if none was found. Call `ableton_device(action='load', track_index=<target_track>, kind='Compressor2'`, optionally `preset_uri=<compressor-uri>` if supplied. Capture the returned `device_index`.

3. **Resolve the source's display name.** `set_sidechain` addresses routing by display name (`1-Drums`, `A-Reverb`, `Main`), not by index. Call `ableton_track(action='list')` and pick out the source track's `name`.

4. **Configure sidechain routing.** Call `ableton_device(action='set_sidechain', track_index=<target_track>, device_index=<from step 2>, enabled=True, source_display_name=<name from step 3>, gain_db=0.0)`. The call uses capability probing — it works on any device with the canonical `S/C On` parameter (Compressor / Compressor2 / Glue Compressor / Gate / Multiband Dynamics + third-party plugins matching the naming pattern). If source-routing fails on a device that doesn't expose `input_routing_*` (Glue / Gate / Multiband — the teaching error names the constraint), use `ableton_device(action='capabilities', ...)` to confirm, then fall back to manual UI routing.

5. **Tune the compressor** (optional, if the user asked). Call `ableton_device(action='set_parameter', ...)`. Conservative starting point for a kick-triggered duck on a synth bus: Threshold=-24, Ratio=4, Attack=1ms, Release=120ms. Canonical parameter names live in `ableton://reference/device-params`.

## Notes

- 1-based indexing on the wire (`target_track=1` is the first track).
- The `source_display_name` parameter is what Live's routing dropdown shows, not the 1-based index — the index addresses the tool call; the name addresses the routing.
