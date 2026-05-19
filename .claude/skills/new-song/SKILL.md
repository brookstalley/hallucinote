---
name: new-song
description: Scaffold a new Hallucinote song from templates. Creates songs/<slug>/ with build.py, captured_session.json, tests/, decisions/, annotations/, and a song.md overview. Use when starting a new song from a prompt — replaces the "copy from falling-walking" pattern that Wave 0 surfaced as a major onboarding friction.
user-invocable: true
disable-model-invocation: false
allowed-tools: Read, Write, Bash(python3 -m tools.scaffold_song *), Bash(python3 songs/* --reset), Bash(pytest songs/*)
argument-hint: <slug> "<title>" <tempo> <signature> <sections-csv> [optional: <key>] [optional: <intent>]
---

# /new-song

You scaffold a new Hallucinote song from templates.

$ARGUMENTS

## What you do

Given a slug + title + tempo + signature + sections (and optional key + intent), you:

1. Validate the inputs (slug shape, signature shape, non-empty section list).
2. Run `python3 -m tools.scaffold_song <slug> --title "..." --tempo X --signature N/D --sections ...` to produce `songs/<slug>/`.
3. Run `python3 songs/<slug>/build.py --reset` to populate the song's DB from the synthetic snapshot.
4. Run `pytest songs/<slug>/tests/ -v` to confirm the shape tests pass.
5. Report the result + tell the user what to do next.

## Gathering input

The user usually invokes this conversationally ("let's start a new song called 'punk-fate' at 160 BPM, 4/4, with intro/verse/chorus/bridge sections"). Map their words to the CLI args:

- **slug** (required) — filesystem-safe identifier: lowercase letters, digits, hyphens, underscores; no leading hyphen/underscore. Reject names with spaces/uppercase/special chars (the CLI also enforces this).
- **title** (required) — human-facing display name, free-form text. Quote it for the shell.
- **tempo** (required) — BPM as a number. For non-4/4 meters where the user gave an "eighth pulse" tempo, convert to the quarter pulse (Live's BPM is always the quarter pulse).
- **signature** (required) — `N/D` (e.g., `4/4`, `7/8`, `3/4`).
- **sections** (required) — comma-separated list (e.g., `intro,verse,chorus,outro`).
- **key** (optional) — musical key (e.g., `Dm`, `Bb`). Surface to the user that this is informational metadata, not a constraint enforced anywhere.
- **intent** (optional) — one-paragraph composer intent that goes into `songs/<slug>/<slug>.md`. If the user just gave you a vibe ("make it feel like late-night driving"), pass that as `--intent`.

If anything's missing or ambiguous, ask **once**. Don't interrogate.

## Refusal cases

The scaffolder refuses (non-zero exit) on:
- Invalid slug → ask the user to pick a valid one.
- Existing `songs/<slug>/` directory → ask the user whether to remove it (`rm -rf songs/<slug>/`) and re-run, or pick a different slug. Don't auto-delete without confirmation.

## After successful scaffold

The scaffolder writes:

```
songs/<slug>/
  build.py                 (state-converger wrapping M.build_session — W12-A)
  captured_session.json    (synthetic 4 MIDI + 2 returns + master)
  <slug>.md                (overview — composer intent + structure)
  tests/test_<slug>_build.py  (shape + converger tests)
  decisions/.gitkeep
  annotations/.gitkeep
```

Two important defaults the scaffold uses:
- **Synthetic snapshot.** `captured_session.json` is generic (2 returns + 4 MIDI tracks + master) so the build runs immediately against a brand-new DB. The user should replace it by capturing a real Live snapshot once they've staged the target Live shape. Capture today is manual via `tools/capture.py`.
- **State-converger build.py.** Re-running `python songs/<slug>/build.py` (no `--reset`) is a no-op when nothing changed in build.py — W12-A guarantees zero net events. `--reset` is for "wipe the DB and start fresh" only.

## Final report to user

After the build + tests succeed, tell the user:

> Scaffolded `songs/<slug>/`. The synthetic snapshot gave you 4 MIDI tracks + 2 returns; replace `captured_session.json` once you've staged a real Live shape. Open `songs/<slug>/build.py` — the `=== Compose-half ===` placeholder is where your music goes. Push to Live with `/ableton-push <slug> <session_id>` once you've authored clips.

If you're collaborating with the user on composition immediately after scaffold, you can begin generator + mutator authoring inside the `=== Compose-half ===` block — `songs/falling-walking/build.py` is the worked example (note: historical, not a literal template).

## Workflow

```
1. Validate inputs (slug, signature, sections).
2. python3 -m tools.scaffold_song <slug> --title "..." --tempo N \
       --signature N/D --sections a,b,c [--key K] [--intent "..."]
3. python3 songs/<slug>/build.py --reset
4. pytest songs/<slug>/tests/ -v
5. Report.
```

## Conventions

- Per-song test files use unique basenames (`test_<slug>_build.py`, not bare `test_build.py`). Wave 0 surfaced the collision the hard way.
- Sections default to 8 bars each. The scaffold uses this for cue-point placement; the user can adjust constants in `build.py` afterwards.
- Generators today assume 4/4 (Wave 0 finding H2). For non-4/4 songs, hand-author until W14-B ships meter-parametrized generators.
- Master automation isn't supported (W10-F locks this in). If the user asks for master fade-out, route to a sub-bus group track first.
- Within-section meter changes aren't supported (W10-H locks this in). For meter-ratchet music, the meter map can only change between sections.
