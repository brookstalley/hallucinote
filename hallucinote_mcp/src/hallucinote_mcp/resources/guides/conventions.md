# Conventions

## Indexing

All indices are 1-based on the wire: `track_index=1` is the first track,
`clip_index=1` is the first session slot or arrangement clip, `device_index=1`
is the first device in a chain, `scene_index=1` is the first scene. Index 0
is never valid. Dotted parameter targets inside automation (e.g.
`device.<device_index>.parameter.<param_index>`) follow the same rule.

## Time positions: beats, not bars

Arrangement positions (`start_beats`, `end_beats`, `position_beats`,
`time_beats` in envelopes) are in **beats** from the song's start (0-based,
fractional). Live counts a beat as a quarter note regardless of meter — in
4/4 the bar is 4 beats; in 7/8, 3.5; in 6/8, 3. Bar→beat conversion is the
caller's job.

## Value ranges

| What | Range | Notes |
|---|---|---|
| Track / return / master volume | 0.0–1.0 | Normalized, NOT decibels |
| Panning | -1.0 to 1.0 | -1 = hard left |
| Send level | 0.0–1.0 | Normalized |
| Mute / solo / arm | 0 or 1 (truthy) | Coerced to bool |
| Color | int palette index | See Live's color picker |
| MIDI pitch | 0–127 | Standard MIDI |
| MIDI velocity | 1–127 | 0 = note-off |
| Tempo | 20–999 BPM | Live's bounds |
| Time signature denominator | 1, 2, 4, 8, 16, 32 | Must be power of 2 |

Out-of-range writes raise a teaching error instead of silently clamping.

## Devices on tracks XOR returns

Pass EXACTLY ONE of `track_index` / `return_index` (never both, never neither).
Handler validates with a teaching error if you slip.

## Notes replace_notes is all-or-nothing

`ableton_clip(action='replace_notes', ...)` replaces the entire note array of
the clip. There is no append. `ableton_clip(action='create', ..., notes=[...])`
accepts notes for atomic create-and-populate.

## Devices append; order is fixed

`ableton_device(action='load', ...)` appends to the END of the target chain.
Live 12.4 exposes no public reorder API — plan the load order if chain order
matters.

## `kind` is the browser display name

For built-in Live devices, `kind` is the device's **browser display name**
(what shows in Live's browser tree). Examples: `'Compressor'`, `'Operator'`,
`'Drum Rack'`, `'Phaser-Flanger'`, `'EQ Eight'`. Live's internal class names
(`'Compressor2'`, `'DrumGroupDevice'`, `'PhaserNew'`) do NOT resolve — pass
what the browser shows.

For anything beyond built-in roots (presets, instruments, plugins), capture
the canonical URI via `ableton_browser(action='at_path', ...)` and pass it
as `preset_uri`. Display-name matching only works for the built-in roots
(`instruments / audio_effects / midi_effects / drums`).

## Quantize / swing / groove not on the wire

These are pure-math timing transforms. Hallucinote owns the math; push the
result via `replace_notes`. See `ableton://guides/gaps` for the rationale.
