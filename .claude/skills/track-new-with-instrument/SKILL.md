---
name: track-new-with-instrument
description: Create a MIDI track and load an instrument on it in one workflow. Optional `index` controls chain position; optional `initial_volume` sets the mixer slider. Use for the common case "add a track with this instrument."
argument-hint: <name> <instrument-uri> [index=N] [initial-volume=0.7]
user-invocable: true
disable-model-invocation: false
---

# /track-new-with-instrument

You create a MIDI track, load an instrument onto it, and optionally set the initial mixer volume — all in one workflow.

$ARGUMENTS

## Steps

1. **Create the track.** Call `ableton_track(action='create', kind='midi', name=<name>)`. If the user supplied an `index`, pass `index=<N>` to place it at that chain position. Capture the returned `track_index`.

2. **Load the instrument.** Call `ableton_device(action='load', track_index=<from step 1>, kind=<Live device class name>, preset_uri=<instrument-uri>)`. `kind` is REQUIRED — look up the Live class name for the preset via `ableton://reference/device-params` (common values: `Operator`, `Wavetable`, `Simpler`, `DrumGroupDevice`). The URI's browser path is NOT a substitute — Live won't infer the class.

3. **Set initial volume** (only if the user supplied one). Call `ableton_track(action='set_property', track_index=<from step 1>, property='volume', value=<initial-volume>)`.

## Notes

- This is a single workflow, not a clip-population workflow. After the track + instrument exist, compose with `ableton_clip(action='create', ..., notes=[...])` separately.
- The instrument's display name (browser node `name`) is the loader's match key. Arc 4 / D4: pass the browser node's `name` directly — Live's internal class names like `InstrumentVector` (Wavetable) or `LoungeLizard` (Electric) no longer resolve. Examples that work: `Operator`, `Wavetable`, `Drum Rack`, `Electric`.
