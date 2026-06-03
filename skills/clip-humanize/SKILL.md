---
name: clip-humanize
description: Humanize a clip's note velocities by a jitter percentage. Reads canonical notes from the Hallucinote DB (Live API gap #4 means we can't read notes from Live), applies per-note jitter in Python, and writes the result via `ableton_clip(action='replace_notes')`.
argument-hint: <track-index> <clip-index> [jitter-percent=10]
user-invocable: true
disable-model-invocation: false
---

# /clip-humanize

You humanize the velocities of one clip's notes by ±jitter_percent.

$ARGUMENTS

## Important — Live API gap #4

This server cannot READ a clip's notes (no per-note IDs from Live's API — see `ableton://guides/gaps`). Humanization is a Hallucinote-side compute that requires the source notes from the DB (or regeneration from a generator). The MCP can only WRITE the result via `ableton_clip(action='replace_notes', ...)`.

## Steps

1. **Source the canonical note array** for this clip from the Hallucinote DB (preferred — `M.get_clip_notes(conn, clip_id)`) OR regenerate from the song's generator. You need the full array — partial updates are not possible.

2. **Apply per-note velocity jitter** in Python/SQL space. `jitter_percent=N` means the jitter range is ±(N/100)*127 velocity units (MIDI velocity is 1-127). Pseudocode:
   ```python
   for note in notes:
       delta = uniform(-1.0, 1.0) * (jitter_percent / 100.0) * 127
       note["velocity"] = clamp(note["velocity"] + delta, 1, 127)
   ```
   Decide whether to floor at the original velocity vs. symmetric around it based on the project's musical taste — for groove humanization, symmetric is conventional; for "make this passage softer" symmetric-but-biased-down is closer to what the user usually wants.

3. **Push the result.** Call `ableton_clip(action='replace_notes', track_index=<track-index>, location='session', clip_index=<clip-index>, notes=<jittered array>)`. This REPLACES the entire note array — any manual edits since the canonical version are lost; warn the user if you suspect drift.

## Defaults

- Default `jitter-percent` if omitted: 10 (a subtle humanization). Typical range: 3 (barely perceptible) to 25 (loose, lo-fi feel).
- For multi-clip humanization (humanize a section), invoke per-clip in sequence — there is no batch replace.
