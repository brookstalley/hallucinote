# hallucinote-mcp — Known Gaps

This document mirrors `docs/mcp-requirements.md` (the historical gap
analysis from the falling-walking song build) with current status as of
Wave M-5. It lists what the server CAN'T do today so you don't waste a
turn asking.

## Hard gaps (don't attempt — the action returns a teaching error)

### Note-level operations: `ableton_note(action='list'|'add'|'update'|'delete')`
**Status:** blocked by MCP gap #4 — Live's API doesn't expose stable
per-note IDs.
**Working alternative:** `ableton_clip(action='replace_notes', ...)` —
replaces the entire note array atomically. To preserve manual edits,
you'd need to read the existing notes first (which is what's blocked).
Until the gap lifts, all-or-nothing replace is the only option for
agents pushing notes.

### Envelope reads: `ableton_automation(action='list')`
**Status:** `list` (enumerate-all-envelopes) is not currently
supported. `envelope.parameter` IS accessible on Live 12.4 (the
W7-0 smoke 2026-05-19 confirmed this empirically — and the targeted
read path's existence-check now depends on it). Bulk enumeration
would still require inverting every target-resolution branch to map
each parameter back to a `(target_kind, addressing-args)` tuple —
deferred until a consumer needs it.
**Working alternative:** `ableton_automation(action='read_envelope',
target_kind=..., ...)` — Wave 6 W6-G/W6-H (2026-05-19) closed the
per-target read path via sampling-based reconstruction; W7-0
(2026-05-19) corrected the existence check to iterate
`Clip.automation_envelopes` and match by parameter identity (real
Live's `create_automation_envelope` is not idempotent on already-
bound targets, contrary to the W6-G assumption). Live exposes
only `envelope.value_at_time(t)`, so the handler samples across the
clip's range at `resolution_beats` (default 1/96 beat) and emits a
breakpoint at each step transition. Works for all 7 target_kinds
EXCEPT clip_cc / clip_pitch_bend (same Live 12.4 LOM gap that blocks
the write side). `get_envelope` is an alias for `read_envelope`.

### Track-level / clip-less mixer / pan / send / device-parameter envelopes
**Status:** Live 12.4's Python LOM exposes envelope creation only
through `Clip.create_automation_envelope(target)`. There is no
`Track.create_automation_envelope`, no atomic `Track.clear_all_envelopes`,
and `Envelope` itself has neither `clear()` nor `add_segment(...)`.
**Working alternative:** Pass `location='session'` + `clip_index`
pointing at a session clip alongside the envelope's target. The
handler routes through that clip's `clear_envelope(target) →
create_automation_envelope(target) → insert_step(time, duration,
value)` flow. Non-'hold' curve hints (linear / fast / slow) are
recorded in the request but applied as step transitions; the
response carries a `notes` field describing the fallback.

### Mixer / pan / send / device-parameter envelopes on ARRANGEMENT clips
**Status:** Live 12.4 narrows the clip-scoped path further — these
target kinds work only on SESSION clips. Calling
`write_envelope(target_kind='mixer_volume', location='arrangement',
clip_index=N)` raises a teaching `NotImplementedError` because Live's
`Clip.create_automation_envelope(target)` rejects with "Not a session
clip or parameter belongs to another track." for arrangement clips.
**Working alternative:** author the envelope on a session clip, then
`ableton_clip(action='duplicate_to_arrangement')` — the arrangement
clip inherits the envelope. (clip_cc / clip_pitch_bend / note_expression
on arrangement clips do work; only the track-level targets are
restricted.)

### Mixer / pan / send / device-parameter envelopes on the MASTER or audio tracks
**Status:** Live 12.4's `Clip.create_automation_envelope` is the only
envelope-creation surface, and the **master track cannot host clips of
any kind** — there's no Clip object to address. Audio tracks accept
audio clips, but Hallucinote v1 models clips as MIDI-only (audio-clip
support is v1.1 scope), so the v1 routing path through
`location='session' + clip_index` doesn't reach audio tracks either.
Wave 0 investigation (Group D, 2026-05-19) confirmed there's no LOM
path: `Utility` on master is dead-end (envelope creation still wants
`Clip`); Max-for-Live mirror is a sub-bus pattern, not an MCP path.
**Working alternative:** author a **sub-bus group track** (kind=`midi`)
that receives the source(s), and put the volume / pan / send / device
envelope on the group's mixer instead. The DB-mutator `create_envelope`
refuses these target kinds on master / audio / group hosts with a
teaching error (W10-F dual-layer refusal — DB + planner).

### MIDI CC and pitch-bend clip envelopes (`clip_cc` / `clip_pitch_bend`)
**Status:** Live 12.4's LOM exposes neither
`Clip.envelope_target_for_cc(N)` nor
`Clip.envelope_target_for_pitch_bend()` — the structural sentinels
the handler constructs are rejected by `Clip.clear_envelope` /
`Clip.create_automation_envelope` at the C++ boundary with
`ArgumentError ... did not match C++ signature: ...
TPyHandle<ATimeableValue>`. The handler catches that error and
surfaces a teaching `NotImplementedError`.
**Working alternative:** for CC, encode the change as a MIDI
control-change event via `ableton_clip(action='replace_notes')` —
this writes the data into the MIDI clip itself rather than as a
clip envelope. For pitch-bend, author manually in Live's clip
envelope editor, or use `target_kind='note_expression'` (pitch axis,
which DOES work).

### Arrangement-level tempo / signature automation
**Status:** Not closeable via MCP — investigated in Wave 6 W6-F
(2026-05-19). Live's `Song.tempo` IS a `DeviceParameter` on
`master_track.mixer_device.song_tempo`, but `create_automation_envelope`
is called EXCLUSIVELY on `Clip` objects across all Live versions and
all surveyed remote scripts (including Ableton's own Push). There is
no song-level path to create an arrangement-tempo envelope through
the Python LOM. `signature_numerator` / `signature_denominator` are
plain int properties, not `DeviceParameter` objects — per the
Ableton forum (t=144193), time-signature automation is unsupported
in the API entirely.
**Working alternatives:** (a) `ableton_session(action='set_tempo')`
/ `set_signature` for the bar-1 value (W5-A); (b) per-scene tempo
/ signature via `ableton_scene` — scenes carry their own values and
trigger on launch (the supported architecture for multi-section
tempo changes).

### Nested rack chain probe / push — RESOLVED for one level (W6-I/W6-J 2026-05-19)
**Status:** Wave 6 W6-I/W6-J shipped one-level-deep nested rack
support via three new actions on `ableton_device`:
`get_device_chains` (read-only probe), `load_in_rack` (browser-load
into a chain), `set_parameter_in_rack` (parameter write inside a
chain). Works for `InstrumentGroupDevice`, `AudioEffectGroupDevice`,
and `DrumGroupDevice`. Does NOT recurse into nested-nested racks
(sub-racks inside chains); recursive addressing beyond
(chain_index, nested_device_position) is filed for a future
workstream.
**Capture-side note:** the capture layer's
`{_note: "Rack — internal chain instruments not captured"}` flag
is now closeable via `get_device_chains` per top-level rack;
extending `tools/capture.py` to populate `device_chains` with
`parent_rack_device_id` is filed in the backlog.

## Partial gaps (works in V1 with restrictions)

### Sidechain configuration — GENERALIZED (W6-E 2026-05-19)
`ableton_device(action='set_sidechain')` no longer rejects device
classes. The class whitelist + the fictional `sidechain_active`
attribute have been retired in favor of capability-probing
primitives:
- `ableton_device(action='capabilities', ...)` — single-call probe
  reporting whether the device exposes input_routing_*, what its
  sidechain-shaped param names are (substring-matched across native
  + third-party naming hints), whether it's a third-party plugin.
- `ableton_device(action='set_input_routing', ..., type_display_name)`
  — uniform source routing via find-by-display_name against the
  device's `available_input_routing_types`. Devices without the API
  (Glue Compressor, Gate, Multiband Dynamics, older plugins) raise
  a teaching error pointing at workarounds.
- `ableton_device(action='get_input_routing', ...)` — symmetric
  read; returns `has_input_routing=False` without raising on
  unsupported devices.
- `set_sidechain` itself is now a convenience bundle: toggles `S/C
  On` parameter (or naming variants for third-party plugins like
  "Sidechain On", "External Sidechain", "Side Enable"), optionally
  delegates to `set_input_routing`, optionally writes `S/C Gain`.
Designed against the third-party VST/AU/CLAP ecosystem from the
start — Compressor + Compressor2 expose `input_routing_*` on the
Device class; third-party plugins with declared sidechain inputs
in their VST3/AU manifest do too. Older Live natives without the
API surface their constraint honestly.

### Session-view audio clip creation
`ableton_clip(action='create', location='session', kind='audio')`
raises NotImplementedError — Live's `clip_slot.create_audio_clip` isn't
exposed. Drag audio from Live's browser, or place audio in arrangement
view instead (`location='arrangement'`).

### Audio render + analysis
`ableton_render` / `ableton_analysis` tools are NOT in the V1 surface.
User-flagged as "sooner than later, not yet" — Wave M+1 candidate.

## Resolved gaps (just an FYI, not blockers)

These were P1/P2 items in `docs/mcp-requirements.md` that the Wave M
surface resolves:

- **gap #1** (`add_notes_to_clip` lies about replacing): renamed to
  `ableton_clip(action='replace_notes')`.
- **gap #13** (`get_cue_points` returns numeric IDs only): the
  greenfield server's `ableton_arrangement(action='cue_list')` returns
  real names.
- **gap #17b** (`get_device_parameters` raises `No module named
  'MCP_Server'`): greenfield code doesn't have the legacy fork's bug.
  `ableton_device(action='get_parameters')` works.

## Hallucinote-side compute (not MCP)

These operations are deliberately NOT exposed as MCP actions. They live
in Hallucinote-space because the DB is the source of truth for note
timing:

- **Quantize / swing** — pure-math timing transforms. Hallucinote
  computes; pushes pre-quantized notes via `replace_notes`. Backlog
  item for the Hallucinote-side module.
- **Groove templates** — same reason; Hallucinote stores grooves as DB
  rows that round-trip across songs.
- **Apply / extract groove** — same; Hallucinote owns the math.

If your task is "quantize this clip by 80%", the right path is: pull
the clip's notes (when gap #4 lifts) or regenerate, compute the
quantized array Hallucinote-side, push via `replace_notes`. The MCP
server cannot do this in-place.
