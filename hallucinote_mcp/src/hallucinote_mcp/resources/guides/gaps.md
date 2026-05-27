# Known gaps

The canonical list of CURRENT API gaps and their workarounds. The server
returns teaching errors that point here — don't waste a turn discovering them.

## Hard gaps (action returns a teaching error)

### Per-note operations
`ableton_note(action='list'|'add'|'update'|'delete')` is blocked — Live's API
doesn't expose stable per-note IDs.
**Workaround:** `ableton_clip(action='replace_notes', ...)` replaces the entire
note array atomically. Read-side is also blocked (see "Notes read" below).

### Notes read
There's no `ableton_clip(action='read_notes')` action. The capability exists
in the pull pipeline (`Clip.get_notes_extended()`).
**Workaround:** run `/ableton-pull` scoped to the song; notes land in the DB
and `Q.get_notes_for_clip(conn, clip_id)` returns the array.

### Envelope enumeration
`ableton_automation(action='list')` is not supported — bulk enumeration would
require inverting every target-resolution branch.
**Workaround:** `action='read_envelope'` reads any specific envelope via
sampling-based reconstruction. Works for 5 of 7 `target_kind`s — `clip_cc` and
`clip_pitch_bend` are not readable (same LOM gap that blocks the write side).
`get_envelope` is an alias.

### Track-level / clip-less envelopes
Live 12.4's LOM exposes envelope creation only through
`Clip.create_automation_envelope(target)`. No `Track.create_automation_envelope`.
**Workaround:** pass `location='session' + clip_index` pointing at a session
clip that holds the envelope. Non-`'hold'` curve hints (linear / fast / slow)
record as step transitions; the response carries a `notes` field describing
the fallback.

### Arrangement-clip mixer / pan / send / device_parameter envelopes
Live 12.4's `Clip.create_automation_envelope(target)` rejects these target
kinds on arrangement clips ("Not a session clip or parameter belongs to
another track.").
**Workaround:** author on a session clip, then
`ableton_clip(action='duplicate_to_arrangement')` — the arrangement clip
inherits the envelope. (`clip_cc / clip_pitch_bend / note_expression` on
arrangement clips work normally.)

### Master + audio-track envelopes (mixer / pan / send / device_parameter)
The master track cannot host clips of any kind, so there's no
`Clip.create_automation_envelope` path. Hallucinote v1 models clips as
MIDI-only, so audio tracks are also unreachable.
**Workaround:** author a sub-bus group track (`kind='midi'`) that receives the
source(s), put the envelope on the group's mixer. The DB-mutator refuses these
target kinds on master / audio / group hosts with a teaching error.

### MIDI CC + pitch-bend clip envelopes (`clip_cc` / `clip_pitch_bend`)
Live 12.4's LOM exposes neither `Clip.envelope_target_for_cc(N)` nor
`Clip.envelope_target_for_pitch_bend()` — the C++ signature rejects the
structural sentinels.
**Workaround:** for CC, encode as MIDI control-change events inside
`replace_notes` (the data lives in the clip, not as an envelope). For
pitch-bend, use `target_kind='note_expression'` (pitch axis works) or author
manually.

### Arrangement-level tempo + signature automation
Not closeable via MCP. `create_automation_envelope` is called exclusively on
`Clip` objects across all Live versions; there is no song-level path.
`signature_*` are plain int properties, not `DeviceParameter`s — automation is
unsupported in the API entirely.
**Workaround:** (a) `ableton_session(action='set_tempo' / 'set_signature')` for
the bar-1 value; (b) per-scene tempo / signature via `ableton_scene` — scenes
carry their own values and trigger on launch.

### Session-view audio clip creation
`ableton_clip(action='create', location='session', kind='audio')` raises
`NotImplementedError` — Live's `clip_slot.create_audio_clip` isn't exposed.
**Workaround:** drag audio from Live's browser, or place audio in arrangement
view (`location='arrangement'`).

## Partial gaps (works with restrictions)

### Sidechain
Works across native devices + third-party VST/AU/CLAP via capability-probing
(`ableton_device(action='capabilities' / 'set_input_routing' /
'get_input_routing')`). Devices without the API surface a teaching error.
See `ableton_device(action='help')`.

### Nested racks
One level deep is supported via `ableton_device(action='get_device_chains' /
'load_in_rack' / 'set_parameter_in_rack')` for `InstrumentGroupDevice`,
`AudioEffectGroupDevice`, `DrumGroupDevice`. Recursive nesting beyond
`(chain_index, nested_device_position)` is not supported.

## Hallucinote-side compute (not MCP)

These are deliberately NOT MCP actions — Hallucinote space owns the math
because the DB is the source of truth for note timing:

- **Quantize / swing** — pure-math timing transforms.
- **Groove templates** — DB rows that round-trip across songs.
- **Apply / extract groove** — Hallucinote owns the math.

If your task is "quantize this clip by 80%", the path is: pull or regenerate
the notes, compute the quantized array Hallucinote-side, push via
`replace_notes`. The MCP server cannot do this in-place.
