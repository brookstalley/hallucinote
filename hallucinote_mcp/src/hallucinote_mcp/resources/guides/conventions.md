# hallucinote-mcp — Conventions

## Indexing

- **All indices are 1-based on the wire.** `track_index=1` is the first
  track, `clip_index=1` is the first session slot or arrangement clip,
  `device_index=1` is the first device in a chain, `scene_index=1` is
  the first scene.
- Index 0 is never valid input; if you see it, that's a bug.
- Live's underlying API is 0-based; the handlers translate.

## Time positions: **beats, not bars**

- Arrangement positions (`start_beats`, `end_beats`, `position_beats`,
  `time_beats` in envelopes) are in **beats** from the song's start
  (0-based, fractional).
- The Hallucinote planner converts bar-based song positions to beats
  using the song's time-signature map before emit. The MCP layer stays
  meter-agnostic — the same wire call in different meters produces the
  same beat result.
- Live counts a beat as a quarter note regardless of meter. In 4/4 the
  bar is 4 beats; in 7/8 the bar is 3.5 beats; in 6/8 the bar is 3.

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

## Devices on tracks AND returns

Pass EXACTLY ONE of `track_index` / `return_index` (never both, never
neither). Handler validates with a teaching error if you slip.

## Notes ALL-OR-NOTHING

`ableton_clip(action='replace_notes', ...)` **replaces the entire note
array** of the clip. There is no append. To preserve manual edits, pull
the existing notes (when gap #4 lifts), mutate, then call replace_notes.

`ableton_clip(action='create', ...)` accepts an optional `notes` param
for atomic create-and-populate (single round-trip).

## Devices live above their parent

When you load a device with `ableton_device(action='load', track_index=X,
kind='Compressor')`, it appends to the END of track X's device chain.
Live 12.4 exposes no public reorder API, so the position is fixed —
plan the load order if you care about chain order.

`kind` is the device's BROWSER DISPLAY NAME (what shows up in Live's
browser tree). Examples: `'Compressor'`, `'Operator'`, `'Drum Rack'`,
`'Phaser-Flanger'`, `'EQ Eight'`. Live's internal class names
(`'Compressor2'`, `'DrumGroupDevice'`, `'PhaserNew'`, etc.) do NOT
resolve — pass what the browser shows.

For a specific preset / instrument / plugin (anything beyond built-in
Live device classes), capture the canonical URI via
`ableton_browser(action='at_path', ...)` and pass it as `preset_uri`.
Display-name matching only works for the built-in roots
(instruments / audio_effects / midi_effects / drums).

## What's NOT here (deliberate omissions)

- **Quantize / swing / groove** — these are pure-math timing transforms
  that live in Hallucinote space (DB-as-source-of-truth). Pre-grooved
  notes push via `replace_notes`. See `ableton://guides/gaps` for the
  full rationale.
- **`ableton_session(action='set_arrangement_loop')`** — moved to
  `ableton_arrangement(action='set_loop')` in Wave M-5 (correct
  semantic home, beats not bars).
- **`ableton_scene(action='insert_at')`** — absorbed into `create`
  (Live's `create_scene` primitive handles both).

The schema enforces these omissions with lock-the-surface negative tests.
