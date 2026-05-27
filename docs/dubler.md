# Dubler pitch modulation round-trip

Round-trip support for Dubler-recorded clips: user sings → Dubler records pitched MIDI → Hallucinote pulls the clip → Hallucinote infers musical intent or regenerates a modified take. The same path unblocks microtonal authorship.

## Background

Pitch bend in a Dubler-recorded clip is MIDI events inside the clip, not a clip envelope. Live's UI shows it under "clip envelopes" but the underlying data is a stream of channel-voice PB messages. Hallucinote currently models `clip_pitch_bend` as a clip-scoped envelope (breakpoints) — the right shape for authored automation, a lossy shape for dense gestural recordings.

Two stacked Live 12.4 LOM gaps shape the design:
- `Clip.envelope_target_for_pitch_bend()` is rejected at the C++ boundary — blocks both write and read for the channel-PB envelope-shaped path. See `hallucinote_mcp/src/hallucinote_mcp/resources/guides/gaps.md:82-96`.
- `Clip.get_notes_extended()` returns notes only; no `get_pitch_bend_events()` / `get_cc_events()` on the clip object. Raw MIDI event reads are unavailable.

The fork that decides everything: **does Dubler emit MPE or channel pitch bend?**
- **MPE mode** → each note carries its own pitch axis. Maps to `target_kind='note_expression'`, `axis='pitch'`, which DOES work on Live 12.4 (gaps.md:94-96). Round-trip is feasible.
- **Channel PB mode** → blocked. Best we could do is "author once in Live, never touch again" — no DB round-trip, no regenerate, no version-control of the gesture data.

## What's already wired (MPE path)

If Dubler emits MPE (or can be switched to it), the structural foundation is mostly already in place:

| Surface | Status | Reference |
| --- | --- | --- |
| DB schema for per-note pitch envelopes | ✅ | `src/hallucinote/db/schema.sql:422-428` (`target_kind='note_expression'`, `target_note_id`, `parameter_path` = axis) |
| Write: `note_expression` axis=`pitch` | ✅ | `ableton_automation(action='write_envelope', target_kind='note_expression', axis='pitch')` — `hallucinote_mcp/src/hallucinote_mcp/handlers/automation.py:294-310` |
| Read: per-target envelope read | ✅ | gaps.md:28-38 — works for all 7 target_kinds EXCEPT `clip_cc` / `clip_pitch_bend` |
| Pull round-trip for DB-known envelopes | ✅ | `src/hallucinote/sync/pull.py:831-832` (`_emit_pull_note_expression`) |

## The actual missing piece — discovery

`plan_pull_envelopes` iterates **DB envelopes** and round-trips edits to envelopes the DB already knows about. It does **not** discover envelopes authored only in Live. See `src/hallucinote/sync/pull.py:738-744`:

> Discovering envelopes authored only in Live (...) is filed as a separate workstream.

Dubler recording is exactly that case: new notes + new pitch gestures, no prior DB rows. A Dubler-record pull cycle needs to discover both the notes AND their attached `note_expression` envelopes.

Note discovery itself is partly there — `clip-notes` pull diffs Live notes against DB notes. What's missing is the per-note **envelope** discovery pass on those notes.

## Critical empirical unknown

The prior analysis was theoretical — "MPE maps cleanly to `note_expression`." It has not been verified that **Live's recording side** stores Dubler MPE-recorded per-note pitch as data accessible via `clip.envelope_for_note(pitch, start_beats, axis='pitch')`. If Live instead retains it as channel PB on multiple channels (one per MPE note), the MPE path collapses back into the blocked channel-PB path.

This must be answered before any build.

### Verification recipe

1. Confirm Dubler MIDI output mode: **MPE / Multi-channel** (Dubler settings → MIDI output).
2. Arm a MIDI track in Live. Record a short clip with one held note plus a clear, slow pitch glide (e.g. C4 sliding up to E4 over 2 beats).
3. From a Claude turn, call:
   ```
   ableton_automation(
     action='read_envelope',
     target_kind='note_expression',
     track_index=<the recorded track>,
     location='session',
     clip_index=<the recorded clip>,
     note_pitch=<the played pitch, e.g. 60>,
     note_start_beats=0.0,
     axis='pitch',
   )
   ```
4. **Pass:** breakpoints come back tracing the glide → MPE path is real.
5. **Fail:** empty result or `NotImplementedError` → Live records MPE as channel PB internally; separate problem, the round-trip stays blocked for now.

If MPE mode also lights up axes `pressure` and `timbre` (Dubler may expose volume / brightness as per-note MPE axes), the same verification on those axes is cheap to add.

## Build sketch (conditional on verification passing)

A single chunk on the pull pipeline:

1. **Note-pull extension.** After `plan_pull_clips` mutates notes for a clip, add a per-note `note_expression` discovery pass:
   - For each note in the clip, probe `clip.envelope_for_note(pitch, start, axis)` for each axis in `('pitch', 'pressure', 'timbre')`.
   - Sample via `read_envelope` at the existing default resolution (1/96 beat — gaps.md:38).
   - Treat ≤1 distinct sample as "no envelope" (same rule as `plan_pull_envelopes` — pull.py:754).
2. **DB write.** For each non-empty envelope, mutate via the existing `create_envelope` / `replace_breakpoints` paths (no new mutator needed). The `note_expression` shape is already enforced by the schema CHECK.
3. **Symmetry with push.** The push side already emits `write_envelope` for `note_expression` from the DB — once notes + their envelopes are in the DB, the round-trip closes.
4. **Tests.** New unit tests around the discovery pass (fake `envelope_for_note` returning breakpoints for some notes, None for others). Manual end-to-end: record-pull-push-rerecord against a real Dubler take.

Open design questions to raise during the build:
- **Discovery cost.** Probing three axes × N notes is O(3N) Live API calls per clip. For a 200-note vocal phrase, that's 600 reads. Worth a quick measurement before committing to the unconditional-probe design vs. opt-in (e.g. only on tracks tagged "MPE input").
- **Backwards compatibility.** Existing songs' clips would suddenly grow `note_expression` rows on next pull. Confirm with the user whether this is desired (probably yes — it's the round-trip completing) or whether it should be opt-in per song / per track.

## Next steps

1. **User runs the verification recipe.** Empirical answer determines whether this is a backlog chunk or a deferred multi-year wait on Ableton.
2. **If verification passes,** file a build-plan chunk for the discovery pass on `plan_pull_clips`. Pull request shape: one feature branch off `develop`, single chunk, Critic at the end.
3. **If verification fails,** file a backlog entry noting Live's MPE recording stores per-note pitch as channel PB; revisit on Live API updates.
