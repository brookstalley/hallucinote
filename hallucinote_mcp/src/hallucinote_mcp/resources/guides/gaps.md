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

### Envelope reads: `ableton_automation(action='list'|'get_envelope')`
**Status:** blocked by MCP envelope read surface gap.
**Working alternative:** `ableton_automation(action='write_envelope', ...)`
+ `action='clear'` / `action='clear_all'` for destructive operations.
You can push envelopes; you can't read them back.

### Arrangement-level tempo / signature automation
**Status:** Live exposes `Song.tempo` as a single value plus the
arrangement-envelope API, but `ableton_automation` doesn't have a
`song_tempo` or `song_signature` target_kind. Per-bar tempo / meter
changes can't be written through the MCP today.
**Working alternative:** `ableton_session(action='set_tempo')` /
`set_signature` set the global value (bar-1 value). Multi-point ramps
require manual Ableton-side authoring or a backlog-item resolution.

### Nested rack chain probe / push
**Status:** the capture layer flags racks as
`{_note: "Rack — internal chain instruments not captured"}`; deep probe
into `InstrumentGroupDevice` / `DrumGroupDevice` chains is not yet
implemented. Push of nested-rack device params raises a "nested-rack"
warn from `plan_push_envelopes`.
**Working alternative:** Top-level chain operations work normally.
Nested chains are a backlog item.

## Partial gaps (works in V1 with restrictions)

### Sidechain configuration
`ableton_device(action='set_sidechain')` supports Compressor and
Compressor2 in V1. Other sidechain-capable devices (Glue Compressor,
Gate, Multiband Dynamics) raise a teaching error. Backlog item for
broader device-class support.

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
