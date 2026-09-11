---
description: Read a sample line against the song's bars BEFORE composing to it or tuning a detector — the implied pitch centre and how it sits in the song's key, phrase lengths in beats at the song's tempo, syllable rate, and where a named detector (scale-tone crossing, energy threshold, onset) would fire against bars, before a note of it is heard. Neutral readings, never a verdict; the reading is a proposal and the key and the register stay the user's. Use after ingesting a line ("what does this line want?", "is the F0 track usable?"), before /compose-part writes anything against it, and whenever a detector's gates are being set ("where would this fire?", "why does the cascade go off constantly?").
argument-hint: "<slug> <source> [--detector scale_tone|energy_threshold|onset --voiced-only yes|no --energy-floor dBFS|off --dwell S --spacing S] [--band-cents N | --threshold-db N] [--key Dm] [--start-bar N] [--json]   |   --file <wav> --bpm N [--key Dm]"
user-invocable: true
disable-model-invocation: false
context: fork
allowed-tools: Bash, Read
---

You are reading a **sample line against the song's bars** so the user can compose to
it, or tune a detector on it, with their eyes before their ears. The lens measures the
line (F0, formants, energy, phrases, onsets), places every reading on the song's beats
through the clip's placement and the tempo map, and prints facts a producer composes
against. It returns only the reading, so the caller's context stays clean.

> **Running engine commands.** The engine ships in the plugin's uv env. Resolve `$PY`
> once from `ableton://server/info`'s `python`; the lens runs as
> `"$PY" -m hallucinote.tools.sample_lens …`. See
> [`docs/running-the-engine.md`](../../docs/running-the-engine.md).

## The one rule

**The reading is a proposal. The key and the register stay the user's.** The lens says
"the implied centre is A3, degree 5 of D minor" — it never says the song should be in A,
never picks the octave a follower lands in, and never decides whether the line or the
music leads at a given moment. Bring the reading to the user as a reading; when a fact
invites a decision ("the centre is not a tone of the declared key"), name the decision as
theirs and offer the two or three ways it could go. Same stance as `/compose-review` and
`/mix-review`: there is no universal right answer here, only the user's intent.

## When to invoke

- **Before composing to a line** — after `hallucinote asset add` has ingested it and
  before `/compose-part` writes a bass under it, a follower over it, or a cascade off it.
  What you want first: the centre and its degree, how long the phrases are *in beats* at
  this tempo, and how fast the line moves (onsets per beat).
- **When tuning a detector** — the detectors in `hallucinote.features.events` have
  musical gates (voiced-only, an energy floor, dwell, minimum spacing), and setting them
  blind is the failure mode: real speech jitters across every band many times a second
  and an ungated detector fires continuously. Run the lens with the gates you intend,
  read the fires against bars, adjust, run again. Only then write the cascade.
- **When the F0 track looks wrong** — a spoken line whose voiced fraction is tiny, or a
  centre an octave off, is the lens telling you the range (`--fmin/--fmax`) or the source
  (score bleed under the dialogue) needs attention before anything downstream trusts it.

## Invocation

$ARGUMENTS

**Step 1 — Identify the song and the source.** The song is the active `songs/<slug>/`;
the source is a name in its `assets/manifest.json` (list them with
`"$PY" -m hallucinote.tools.asset_ingest list --song <slug>`, or read the manifest). A line not
yet ingested can be read as a bare file with `--file <wav> --bpm <tempo>` — constant
tempo, no placement, and no key unless `--key` is passed; the reading says so.

**Step 2 — Run the lens.**

```bash
# The line as placed in the song: placement, tempo and key come from the DB
"$PY" -m hallucinote.tools.sample_lens <slug> <source>

# Where a scale-tone detector would fire, with every gate stated (none defaults)
"$PY" -m hallucinote.tools.sample_lens <slug> <source> \
    --detector scale_tone --voiced-only yes --energy-floor -40 --dwell 0.08 --spacing 0.25 \
    --band-cents 30

# An energy-threshold detector (read the peak the lens prints, set the threshold below it)
"$PY" -m hallucinote.tools.sample_lens <slug> <source> \
    --detector energy_threshold --voiced-only no --energy-floor off --dwell 0.05 --spacing 0.3 \
    --threshold-db -24

# A line not yet ingested, read at a tempo and against a key
"$PY" -m hallucinote.tools.sample_lens --file takes/rivers-01.wav --bpm 92 --key Dm

# For your own reading rather than the user's: the same as JSON
"$PY" -m hallucinote.tools.sample_lens <slug> <source> --json
```

A detector needs **all four gates** on the command line; the lens refuses (exit 3) when
one is missing rather than filling it in — a gate you did not set is the number you will
tune wrong on the first real line. `scale_tone` also needs `--band-cents` and a key (the
song's, or `--key`); `energy_threshold` needs `--threshold-db`. Exit 2 means the song,
its DB, the source or the file could not be found; the message says what to do.

**Step 3 — Read it back to the user, as facts.** The reading has five parts; relay
each in a sentence, in the user's terms:

1. **Placement** — which bar the line starts and ends on, and how many beats it spans
   at this tempo. If it is placed more than once, the lens reads against the first.
2. **Pitch** — the implied centre (note, Hz, cents), the range, the pitch-class weight,
   and *against the song's key* the centre's degree — or, when the centre is not a
   scale tone, the nearest tones either side. Read the in-scale fraction as "how much of
   the line already sits in the key", not as a score.
3. **Phrases** — how many, each one's start on the bar, its length in beats and in
   seconds, and its syllable rate (onsets per second and per beat). A phrase of 1.7 beats
   at 92 bpm is a fact the user can compose a two-beat answer to.
4. **The detector** — how many fires, fires per beat, and each fire's bar position, the
   grid position it would land on, and what it saw (the tone and degree, the level, the
   onset's length). Too many fires means the gates are loose; none means they are tight;
   *which* is right is the user's ear.
5. **The bar strip** — one row per bar, `=` where the line sounds, `x` where the detector
   fires, `.` silence, `|` between beats. Show it as-is; it is the picture the rest of the
   reading describes.

Formants are reported where measured; a pure tone or an unvoiced line reads "none
measured", which is a fact about the material, not an error.

## Important

- **Read-only.** The lens writes nothing — no DB, no manifest, no annotation. What the
  user decides from it is recorded where every other creative decision is:
  `annotations/` for revealed intent, `decisions/` for a kept move's why.
- **Neutral wording, always.** "The centre is A3, the 5th of D minor" — never "the line
  is in A", never "the key should be…". If the user asks what to do with it, offer
  options with a read and let them pick; never author the key or the register.
- **A gate is tuned by ear.** The lens makes the fires visible so the user can set the
  gates before a hearing; it does not calibrate them. Keep the gates they settle on in
  the song's `build.py` beside the cascade they drive, and note the reasoning in
  `decisions/` when the gates are a substantive move.
- **Bare-file readings are provisional.** Without a song there is no placement and no
  key; a reading at `--bpm 92 --key Dm` is a sketch against assumptions the reading
  names. Re-run against the song once the line is ingested and placed.
