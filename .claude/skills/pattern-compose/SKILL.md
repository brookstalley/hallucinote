---
name: pattern-compose
description: Generate a named rhythmic pattern (trip-hop / tresillo / bossa / swing-8ths / straight-16ths / shuffle / boom-bap) into an arrangement clip on a track at a given start bar. Authors notes in Hallucinote-space and pushes via `ableton_clip(action='create', notes=...)`.
argument-hint: <track-index> <pattern-kind> <bars> <start-bar>
user-invocable: true
disable-model-invocation: false
---

# /pattern-compose

You compose a `<bars>`-bar `<pattern-kind>` pattern on `<track-index>`, placed at `<start-bar>` in the arrangement. The note array is generated in Hallucinote-space, then written to a new arrangement clip in one MCP call.

$ARGUMENTS

## Recognized pattern kinds

`trip-hop`, `tresillo`, `bossa`, `swing-8ths`, `straight-16ths`, `shuffle`, `boom-bap`. For unrecognized kinds, refuse with a teaching message naming the valid choices — OR generate the notes directly via the user's own pattern library and skip this skill.

## Steps

1. **Generate the note array** for the pattern in Hallucinote-space (a generator function under `hallucinote.generators.*` OR write the array directly based on the pattern's known shape). Length should be `<bars>` bars; each note dict needs `{pitch, start_time (beats), duration (beats), velocity}`. For drum patterns, use the General MIDI drum map (kick=36, snare=38, closed-hat=42, open-hat=46) or a project-specific map.

2. **Create the arrangement clip** with the notes in one call:
   ```
   ableton_clip(action='create',
       track_index=<track-index>,
       location='arrangement',
       kind='midi',
       start_beats=(start_bar - 1) * 4,
       length=<bars> * 4,
       notes=<from step 1>)
   ```
   The atomic create-and-populate avoids the two-call create-then-replace pattern. **4/4 assumption** — `(start_bar - 1) * 4` and `<bars> * 4` both assume four beats per bar. For other meters, convert `bar → beats` via the song's time-signature map before the call.

3. **(Optional) name the clip:** `ableton_clip(action='rename', track_index=<track-index>, location='arrangement', clip_index=<from step 2>, name=<pattern-kind>)`.

## Notes

- Beats on the wire are quarter-note beats (Live's BPM is the quarter pulse), independent of meter. The conversion above is bars → beats, not beats → beats.
- For non-4/4 patterns, generators in `hallucinote.generators.*` accept a `beats_per_bar` kwarg (W14-B); within-bar layout still assumes a 4/4 shape, so hand-author non-4/4 patterns where that matters.
