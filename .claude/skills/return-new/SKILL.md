---
name: return-new
description: Create a return track + load an effect + optionally initialize sends from a list of source tracks. Use for "build a new reverb / delay / chorus bus."
argument-hint: <name> <effect-uri> [sends-from=1,2,3]
user-invocable: true
disable-model-invocation: false
---

# /return-new

You create a return track, load an effect onto it, and optionally initialize sends from a list of source tracks at a moderate level.

$ARGUMENTS

## Steps

1. **Create the return.** Call `ableton_return(action='create', name=<name>)`. Capture the returned `return_index`.

2. **Load the effect.** Call `ableton_device(action='load', return_index=<from step 1>, kind=<Live device class name>, preset_uri=<effect-uri>)`. `kind` is REQUIRED — look up the Live class name via `ableton://reference/device-params` (common: `Reverb`, `Delay`, `EchoDelay`, `Compressor2`).

3. **Initialize sends** (only if the user supplied `sends-from`). For each source `track_index` in the list, call `ableton_track(action='set_send', track_index=<src>, return_index=<from step 1>, value=0.4)`. 0.4 is a moderate default — the user can tune individual sends afterward.

## Notes

- Live re-prefixes return names with `<letter>-` on load (`A-Reverb`, `B-Delay`). The Hallucinote DB stores stripped names — see `docs/snapshot-schema.md` "Return names: stored stripped."
- For the rare effect class that Live won't load by bare `kind` (e.g., Instrument Rack — see error-recovery guide), reach for an explicit `preset_uri` or hand off to the user.
