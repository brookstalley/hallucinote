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
| Track / return / master volume | 0.0–1.0 | Normalized, NOT decibels — but `ableton_track(action='set_property', property='volume')` also accepts `value_display='-8 dB'`, and `action='info'` reports `volume_db` alongside the raw value |
| Panning | -1.0 to 1.0 | -1 = hard left |
| Send level | 0.0–1.0 | Normalized |
| Mute / solo / arm | 0 or 1 (truthy) | Coerced to bool |
| Color | int palette index | See Live's color picker |
| MIDI pitch | 0–127 | Standard MIDI |
| MIDI velocity | 1–127 | 0 = note-off |
| Tempo | 20–999 BPM | Live's bounds |
| Time signature denominator | 1, 2, 4, 8, 16, 32 | Must be power of 2 |
| Device parameter (`set_parameter`, continuous) | `[param.min, param.max]` | RAW Live value — **normalized [0,1] for many params** (a Compressor Threshold of `0.85` displays as `-3.0 dB`); some are already in native units (Output `[-36, 36]`). NOT display units. |

Out-of-range writes raise a teaching error instead of silently clamping.

**Display units (dB, ratios, ms).** Continuous `set_parameter` (and
`set_parameter_in_rack`), plus `ableton_track(action='set_property',
property='volume')`, accept `value_display` instead of `value` — a display
string like `'-18 dB'`, `'3:1'`, `'20 ms'`, `'80 Hz'`. The handler inverts
Live's display curve to the raw value for you, so you can hit a musical target
without reverse-engineering the normalized mapping. Pass EXACTLY ONE of `value`
(raw) or `value_display`. The response echoes the achieved `value_display` so
you can confirm the target landed at the parameter's display resolution. Track
`info` likewise reports `volume_db` (the fader in dB; `null` when the fader is
fully down, volume 0). Panning has no dB sense, so its `value_display` is refused.
`value_display` is refused for enum params (use `value_type='enum'`) and for the
rare params whose display can't be addressed numerically (e.g. Expansion Ratio
renders `'1 : 1.15'`, where the leading number never varies).

## Devices on tracks XOR returns

Pass EXACTLY ONE of `track_index` / `return_index` (never both, never neither).
Handler validates with a teaching error if you slip.

## Notes replace_notes is all-or-nothing

`ableton_clip(action='replace_notes', ...)` replaces the entire note array of
the clip. There is no append. `ableton_clip(action='create', ..., notes=[...])`
accepts notes for atomic create-and-populate.

## Inline note arrays: soft cap (~32 notes)

The inline `notes=[...]` channel is for trivial interactive edits. Above ~32
notes both `create` and `replace_notes` add a non-blocking `warning` to the
result: large inline arrays cost agent context and bypass the Hallucinote DB
(the next full push overwrites a clip authored only inline). For parts this
size, author the notes as code in the song's `build.py`
(`hallucinote.generators`) and materialize with `push_cli push-notes --changed`
— the array never enters the agent's context. See the `/compose-part` skill.

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
