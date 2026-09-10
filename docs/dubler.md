# Dubler pitch modulation round-trip

> **When does this apply to me?** Read this only if you record gestural or
> microtonal MIDI with [Dubler](https://vochlea.com/) (or similar pitch-bend-
> heavy input) and want that pitch modulation to survive a pull→regenerate
> round-trip. **Status: blocked, and not on a build we can do** — Live's Python
> API has no surface for either shape this feature needs. Skip it for ordinary
> note-based composition.

Round-trip support for Dubler-recorded clips would be: user sings → Dubler
records pitched MIDI → Hallucinote pulls the clip → Hallucinote infers musical
intent or regenerates a modified take. The same path would unblock microtonal
authorship.

It is blocked in both of the two modes Dubler can emit in. That was not
obvious when this note was first written — it turned on an empirical fork, and
the fork has since been answered against us.

## Background

Pitch bend in a Dubler-recorded clip is MIDI events inside the clip, not a clip
envelope. Live's UI shows it under "clip envelopes" but the underlying data is a
stream of channel-voice PB messages. Hallucinote models `clip_pitch_bend` as a
clip-scoped envelope (breakpoints) — the right shape for authored automation, a
lossy shape for dense gestural recordings.

Three Live LOM gaps shape — and close — the design:

- `Clip.envelope_target_for_pitch_bend()` is rejected at the C++ boundary,
  blocking both write and read for the channel-PB envelope-shaped path. See
  `hallucinote_mcp/src/hallucinote_mcp/resources/guides/gaps.md` → *MIDI CC +
  pitch-bend clip envelopes*.
- `Clip.get_notes_extended()` returns notes only; there is no
  `get_pitch_bend_events()` / `get_cc_events()` on the clip object. Raw MIDI
  event reads are unavailable.
- **There is no per-note expression surface in the LOM at all** — the finding
  that closes this note. See below.

## The fork that decided everything, and how it was decided

The design used to turn on one question: **does Dubler emit MPE or channel
pitch bend?** MPE mode was the live branch — each note carries its own pitch
axis, which was assumed to map onto `target_kind='note_expression'`,
`axis='pitch'`.

**That assumption was false, and it was never about Dubler.** Live's Python API
projects no per-note expression surface whatsoever (#515):

- `Clip.envelope_for_note(pitch, start_beats, axis)` — the call this note's
  build sketch was written against — **never existed on any Live version**.
  Three independent probes agree: the shipped Live binary's symbol table
  resolves every other `Clip` LOM method and resolves this one zero times;
  Cycling '74's published Live 12 LOM reference lists no note-scoped envelope
  accessor; and a GitHub-wide code search returns dozens-to-hundreds of hits
  for real LOM methods and not one Ableton-related hit for this one.
- Nothing replaces it under another name. `note_expression`,
  `expression_envelope`, `note_envelope`, `per_note_envelope`,
  `get_note_expression` and `mpe_enabled` all resolve zero times against the
  binary, and `MPE` / `per-note` / `pressure` / `timbre` / `slide` return
  nothing across the whole Live 12 LOM reference. Live's own MPE editing exists
  internally and is simply not exposed to Python.

So the MPE branch does not depend on how Live *stores* a Dubler take. Even if
Live retained every note's pitch axis perfectly, there would be no call to read
it with and none to write it back. **Both branches of the fork are blocked**,
for two different reasons, and neither is a naming problem waiting on the right
probe.

Full research, with the re-runnable probe recipes:
`.prawduct/artifacts/research-envelope-lom-gaps.md` → *does
`Clip.envelope_for_note` exist?*

## What this means for the surfaces that mention `note_expression`

The kind is still addressable end to end inside Hallucinote — it just cannot
reach Live:

| Surface | Status |
| --- | --- |
| DB schema for per-note pitch envelopes (`target_kind='note_expression'`, `target_note_id`, `parameter_path` = axis) | rows can be stored; nothing can push them |
| `ableton_automation(action='write_envelope', target_kind='note_expression')` | **refused** — `NotImplementedError` naming the reason and the working route |
| `read_envelope` / `get_envelope` / `clear` for the same kind | **refused**, identically |
| Push / pull planners' `note_expression` emission (`sync/push/envelopes.py`, `sync/pull/envelopes.py`) | still emit the call; the call now refuses at the boundary instead of raising `AttributeError` from inside Live |
| `generators.follow_pitch(bend='note_expression')` | **refused at author time** — it no longer writes rows that could only fail at push |

There is no verification recipe to run. The previous version of this note ended
with one (record a glide, then call `read_envelope` with
`target_kind='note_expression'`); it probes a surface that does not exist, and
running it can only return the refusal above.

## What can carry a pitch gesture

**Monophonic only, and it is a stopgap rather than a fix.** Ride a real device
parameter and gesture-record it:
`ableton_automation(action='perform_batch')` with a `device_parameter` arc.
Verified on Live 12.4.5: `[performed_automation] 1/1 ok`, `automation_state` →
1.

One parameter rides the whole voice, so two notes sounding together cannot bend
apart — which is exactly what `note_expression` was for. Two caveats decide
which parameter:

- Operator's `A Fine` is a **unipolar ratio tail**, range `[0.0, 1000.0]` — a
  set of `-60` is refused, so there is no way to go flat from rest. Its
  interval is `1200 * log2(Coarse + Fine/1000)`, so `Fine=100` is **+165
  cents**, not a linear cent offset.
- `Pitch` (MidiPitcher) is **not** an alternative: its `Pitch` parameter is
  semitone-quantized, so it steps rather than glides.

For dense gestural material there is also the plain option the API does
support: author the take once in Live and leave it alone. No DB round-trip, no
regenerate, no version control of the gesture data — but the sound survives.

## If this is ever revisited

The unblocking event is Ableton exposing a per-note expression surface in the
Live Python API — not a Hallucinote build, and not another probe of the current
one. If that ships:

1. Re-run the symbol-table probe in
   `.prawduct/artifacts/research-envelope-lom-gaps.md`; a non-zero resolve is
   the signal.
2. Only then does the discovery question become live again — `plan_pull_envelopes`
   iterates **DB** envelopes and round-trips edits to ones the DB already knows
   about; it does not discover envelopes authored only in Live, which is exactly
   the Dubler-recording case (new notes plus new pitch gestures, no prior rows).
   Note discovery itself is partly there — `clip-notes` pull diffs Live notes
   against DB notes; the per-note **envelope** discovery pass on those notes is
   what would be missing.
3. Cost to price in at that point: probing three axes × N notes is O(3N) Live
   API calls per clip — 600 reads for a 200-note vocal phrase — so measure
   before committing to an unconditional probe rather than an opt-in one.
