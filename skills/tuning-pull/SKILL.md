---
description: Capture the alternate tuning currently loaded in Ableton Live onto a Hallucinote song. Probes `song.tuning_system`, synthesizes a re-draggable cached `.ascl`, and records the tuning on the song so the mapper can author in it and push can warn on drift. Use for the 0.01% of songs in a non-12-TET tuning — after you've dragged an `.ascl` into Live's Tuning section and want Hallucinote to know about it. Pull-from-Live only (the LOM tuning surface is read-only; there is no set-tuning path).
user-invocable: true
disable-model-invocation: false
allowed-tools: Read, Write, Bash, mcp__hallucinote-mcp__ableton_probe
argument-hint: <song-slug>
---

You are the tuning-pull orchestrator. Read the alternate tuning loaded in Live off the LOM, hand the values to the engine, and report what was captured.

$ARGUMENTS

> **Running engine commands.** The engine ships in the plugin's uv env — no separate install. Resolve `$PY` once from `ableton://server/info`'s `python`; the command below runs as `"$PY" -m hallucinote.cli tuning-pull …`. See [`docs/running-the-engine.md`](../../docs/running-the-engine.md).

## What this does (and doesn't)

- **Does:** reads `song.tuning_system` (read-only), reconstructs a faithful, re-draggable `.ascl` (relative cents preserved — the LOM exposes no source path), writes it to `songs/<slug>/tunings/<name>.ascl`, and records `tuning_ref` + `tuning_data` on the song. After this, the song authors in the tuning via `hallucinote.tuning.mapper.degree_to_midi`, the lens output carries the 12-TET-relative caveat, and push emits the re-load instruction + drift-warn.
- **Doesn't:** load or set a tuning in Live (the LOM tuning surface is read-only — the human drags the `.ascl` in), ingest an external `.ascl` from disk (pull-from-Live only), or capture clips/mix/automation (that's `/ableton-pull`).

## Required argument

The **song slug** (its DB name; the DB lives at `songs/<slug>/<slug>.db`). If it's missing from `$ARGUMENTS`, ask — never invent.

## Workflow

### Step 1 — Probe the loaded tuning

Run each `ableton_probe` **get** below with `allow_version_mismatch=true` (the read is non-mutating, so the bypass is safe — see `api-notes-tuning.md`):

1. `path='song.tuning_system'` — **if `result.type == "NoneType"`, STOP.** No alternate tuning is loaded. Tell the user: drag the `.ascl` into Live's Tuning section (the **Tuning toggle in the Control Bar** lights up and shows the name), confirm it's active, then re-run `/tuning-pull`. Do not proceed.
2. `path='song.tuning_system.name'`
3. `path='song.tuning_system.note_tunings'`
4. `path='song.tuning_system.pseudo_octave_in_cents'`
5. `path='song.tuning_system.number_of_notes_in_pseudo_octave'`
6. `path='song.tuning_system.reference_pitch.octave'`
7. `path='song.tuning_system.reference_pitch.index_in_octave'`

### Step 2 — Assemble the probe JSON

Take the `result.value` from each get and build this object (the shape `read_tuning_system` expects — see `api-notes-tuning.md`):

```json
{
  "name": "<2 .value>",
  "note_tunings": [<3 .value>],
  "number_of_notes_in_pseudo_octave": <5 .value>,
  "pseudo_octave_in_cents": <4 .value>,
  "reference_pitch": { "octave": <6 .value>, "index_in_octave": <7 .value> }
}
```

Write it to `/tmp/tuning-pull-probe.json` via Write. Do **not** reshape the values (no rounding, no reindexing) — the engine validates the confirmed shapes and fails loud on a misread.

### Step 3 — Apply

```
"$PY" -m hallucinote.cli tuning-pull apply --song <slug> --probe /tmp/tuning-pull-probe.json
```

Writes a JSON report to stdout: `{status, song, tuning:{name, step_count, period_cents, reference_note}, tuning_ref, reload_instruction}`. `status="no-tuning-loaded"` means the probe was `None` after all (nothing was changed).

### Step 4 — Report

Show the user:

- The captured tuning: **name**, **step_count** (steps per period), **period_cents** (≠ 1200 for a non-octave tuning like Bohlen-Pierce), **reference_note** (the MIDI anchor for scale degree 0).
- The cached file at `tuning_ref` (re-draggable into Live).
- The **`reload_instruction`** verbatim — push can't load the tuning, so whoever plays the song back must drag this `.ascl` into Live's Tuning section first.

Then point at the next step: author in the tuning by computing MIDI ints with `hallucinote.tuning.mapper.degree_to_midi` inside `build.py` and feeding them into the **unchanged** generators (see `docs/alternate-tunings.md` and the worked 19-EDO example in `tests/unit/tuning/test_authoring_example.py`).

## What NOT to do

- Do not reshape probe values before writing the JSON — pass them through verbatim.
- Do not try to set/load a tuning programmatically — the LOM tuning surface is read-only; the human drags the `.ascl`.
- Do not run this for a 12-TET song — `tuning_ref` stays NULL and everything just works.
- Do not push afterward as part of this skill — pull is one direction.
