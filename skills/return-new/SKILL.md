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

2. **Load the effect.** Call `ableton_device(action='load', node={'parent': {'kind': 'return', 'index': <from step 1>}, 'terminal': 'return'}, kind=<browser display name>, preset_uri=<effect-uri>)` (a `return` terminal loads onto the return's main chain). `kind` is REQUIRED — pass the browser display name (`Reverb`, `Delay`, `Echo`, `Compressor`, etc.; see `ableton://guides/conventions`).

3. **Initialize sends** (only if `sends-from` supplied). For each source `track_index`, call `ableton_track(action='set_send', track_index=<src>, return_index=<from step 1>, value=0.4)`.

4. **Postlude:** call `ableton_render(action='ensure_loaded')` silently.

## Notes

- Live re-prefixes return names with `<letter>-` on load (`A-Reverb`, `B-Delay`). The Hallucinote DB stores stripped names — see `docs/snapshot-schema.md` "Return names: stored stripped."
- For the rare effect class Live won't load by bare `kind` (e.g., Instrument Rack), see `ableton://guides/error-recovery`.
