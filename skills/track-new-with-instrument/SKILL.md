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

1. **Create the track.** Call `ableton_track(action='create', kind='midi', name=<name>)`. If the user supplied an `index`, pass `index=<N>`. Capture the returned `track_index`.

2. **Load the instrument.** Call `ableton_device(action='load', node={'parent': {'kind': 'track', 'index': <from step 1>}, 'terminal': 'track'}, kind=<browser display name>, preset_uri=<instrument-uri>)` (a `track` terminal loads onto the track's main chain). `kind` is REQUIRED — pass the browser display name (`Operator`, `Wavetable`, `Drum Rack`, etc.; see `ableton://guides/conventions`).

3. **Set initial volume** (only if supplied). `ableton_track(action='set_property', track_index=<from step 1>, property='volume', value=<initial-volume>)`.

4. **Postlude:** call `ableton_render(action='ensure_loaded')` silently.

## Notes

- This is a single workflow, not a clip-population workflow. After the track + instrument exist, compose with `ableton_clip(action='create', ..., notes=[...])` separately.
