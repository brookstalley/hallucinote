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
sampling-based reconstruction. Three `target_kind`s raise instead: `clip_cc`
and `clip_pitch_bend` (same LOM gap that blocks the write side) and
`note_expression` (no per-note surface exists in either direction — see
"Per-note expression" below). `get_envelope` is an alias.

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
inherits the envelope. (`clip_cc / clip_pitch_bend` on arrangement clips work
normally; `note_expression` works nowhere — see "Per-note expression" below.)

### Audio-track envelopes (mixer / pan / send / device_parameter)
ENV-9P4T: audio-track hosts are authorable. A clip-independent (e.g.
song-spanning) ride routes to **perform** — a continuous arrangement lane,
like a plain/group track (the mutator admits audio; the planner infers the
route from the envelope's span: covered by one session clip → per-clip,
else → perform). An audio host is NOT a special case: it routes exactly like
a MIDI one, including the per-clip route under a covering audio session clip.

### Master / group / return envelopes — performed, not clip-hosted
The master track cannot host clips, so there is no
`Clip.create_automation_envelope` path — but these targets are no longer
refused (ENV-7G4K). `ableton_automation(action='perform_batch')`
gesture-records scripted ramps into Live's arrangement automation: the
transport plays ONCE over the union span of all changed arcs in record while
the handler steps each parameter inside its own gesture window (ENV-9P4T —
N arcs in one playthrough, not one pass per arc). Hallucinote's push routes
master/group mixer + group sends, return mixer, and master-/return-chain
device parameters through its performed-automation phase automatically
(fingerprint-gated — unchanged arcs are skipped and listed, so a hand-edited
lane survives).
**Restrictions:** write-only (recorded arrangement automation has no LOM read
surface; verify via each arc's returned `automation_state == 1`), real
wall-clock for the UNION span (the changed arcs play once together in real
time), and nested-rack device parameters are unreachable on this route too.

**Fidelity is fixed in wall-clock, not in beats.** The recorder lays down one
breakpoint per ~400 ms (a fixed ~2.5 Hz tick), whatever the tempo — so
authoring more breakpoints buys nothing, and an authored edge shorter than one
tick has no representation on this route: it records as a step on the tick
grid, not as the ramp you wrote. The only lever is `perform_batch`'s
`slowdown_factor` (>= 1.0, default off), which lowers the transport tempo for
the record pass so the same fixed tick lays down factor× more breakpoints per
beat — at factor× the wall-clock. Both directions of the trade live on that one
dial: "can I record this faster?" is answered by the tick rate being fixed
(you cannot, and a shorter pass would not have cost you fidelity either), and
"my 120 ms duck edge came out as a step" is answered by raising it (400 ms ÷
your shortest edge is the factor you need). Hallucinote's push checks this for
you — an arc carrying a sub-tick edge names the segment, the effective tick and
the required factor, and marks the phase INCOMPLETE rather than reporting a
clean ok over a ramp that did not materialize.

### MIDI CC + pitch-bend clip envelopes (`clip_cc` / `clip_pitch_bend`)
Live 12.4's LOM exposes neither `Clip.envelope_target_for_cc(N)` nor
`Clip.envelope_target_for_pitch_bend()` — the C++ signature rejects the
structural sentinels.
**Workaround:** for CC, encode as MIDI control-change events inside
`replace_notes` (the data lives in the clip, not as an envelope). For
pitch-bend, author it by hand in Live's clip envelope editor, or script the
monophonic ride below — `note_expression` is NOT an alternative; it does not
exist.

### Per-note expression / MPE (`note_expression`) — PERMANENT
Not a gap awaiting a method name: Live's Python API projects **no per-note
expression surface at all**. `Clip.envelope_for_note` never shipped (the Live
binary's symbol table resolves every other `Clip` LOM method and resolves that
one zero times; the published Live 12 LOM reference lists no note-scoped
envelope accessor; a GitHub-wide code search returns no Ableton-related hit),
and neither does anything under another name — `note_expression`,
`expression_envelope`, `note_envelope`, `per_note_envelope`,
`get_note_expression`, `mpe_enabled` all resolve zero times. Live edits MPE
internally and does not project it. So there is nothing to route a
**polyphonic** per-note bend to, and no clip-level envelope reconstructs one:
unlike `clip_cc` (encodable as control-change notes), this has no substitute.

`target_kind='note_expression'` stays on the wire and raises
`NotImplementedError` on `write_envelope`, `read_envelope` / `get_envelope`
and `clear` alike — retained so the documented call gets a reason and a route
rather than `not in [...]`. Nothing in the codebase is waiting to fill it in.

**Workaround (monophonic only, not a fix):** ride a real device parameter and
gesture-record it — `ableton_automation(action='perform_batch')` with a
`device_parameter` arc. One parameter rides the whole voice, so two notes
sounding together cannot bend apart. Two caveats decide the parameter:
Operator's `A Fine` is a **unipolar ratio tail**, range `[0.0, 1000.0]`, so
there is no way to go flat from rest, and its interval is
`1200 * log2(Coarse + Fine/1000)` — `Fine=100` is **+165 cents**, not +100.
`Pitch` (MidiPitcher) is semitone-quantized, so it steps rather than glides.

### Arrangement-level tempo + signature automation
Not closeable via MCP. `create_automation_envelope` is called exclusively on
`Clip` objects across all Live versions; there is no song-level path.
`signature_*` are plain int properties, not `DeviceParameter`s — automation is
unsupported in the API entirely.
**Workaround:** (a) `ableton_session(action='set_tempo' / 'set_signature')` for
the bar-1 value; (b) per-scene tempo / signature via `ableton_scene` — scenes
carry their own values and trigger on launch.

## Partial gaps (works with restrictions)

### Sidechain
Works across native devices + third-party VST/AU/CLAP via capability-probing
(`ableton_device(action='capabilities' / 'set_input_routing' /
'get_input_routing')`). Devices without the API surface a teaching error.
See `ableton_device(action='help')`.

### Nested racks
Supported to ARBITRARY depth via the `node` object's `path` (NODE-ADDR) — a list
of `{chain_index, device_position}` steps (both 1-based) descending from the
top-level `device_index` device. `ableton_device(action='get_device_chains')`
recurses the whole tree and reports a `device_path` (+ `is_rack`) per nested
device as a convenience — drop its steps into the node's `path` for
`set_parameter` / `get_parameters` (read or write the nested param). To load a
device INTO a nested chain, address the destination with a `chain` terminal node
(`device_index` + `chain_index`, + `path` for a deeper rack). Applies to
`InstrumentGroupDevice`, `AudioEffectGroupDevice`, `DrumGroupDevice`.

## Hallucinote-side compute (not MCP)

These are deliberately NOT MCP actions — Hallucinote space owns the math
because the DB is the source of truth for note timing:

- **Quantize / swing** — pure-math timing transforms.
- **Groove templates** — DB rows that round-trip across songs.
- **Apply / extract groove** — Hallucinote owns the math.

If your task is "quantize this clip by 80%", the path is: pull or regenerate
the notes, compute the quantized array Hallucinote-side, push via
`replace_notes`. The MCP server cannot do this in-place.
