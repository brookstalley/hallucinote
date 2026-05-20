---
name: song-new
description: Scaffold a new Hallucinote song from templates. Creates songs/<slug>/ with build.py, captured_session.json, tests/, decisions/, annotations/, and a song.md overview. Use when starting a new song from a prompt — replaces the "copy from falling-walking" pattern that Wave 0 surfaced as a major onboarding friction.
user-invocable: true
disable-model-invocation: false
allowed-tools: Read, Write, Bash(python3 -m tools.scaffold_song *), Bash(python3 songs/* --reset), Bash(pytest songs/*)
argument-hint: <slug> "<title>" <tempo> <signature> <sections-csv> [optional: <key>] [optional: <intent>]
---

# /song-new

You scaffold a new Hallucinote song from templates AND run the pre-composition elicitation pass so the first composition decisions are defensible, not guessed.

$ARGUMENTS

## Mode detection (do this first)

Decide which of two modes the invocation is in **before doing anything else**, and state your read in one sentence so the user can correct it:

- **`make-me-X` mode** — the user asked for a *finished song* ("make me a 2-minute punk song that condenses Beethoven's 5th"; "build me a lazy bossa for cocktail hour"). The implicit deliverable is the song you can press play on. Scaffold + decisions + instrument picks + push + compose + sound design + mix all happen as one continuous flow. Skill boundaries (`/song-new` → `/song-pick-instruments` → `/ableton-push` → compose → re-push → mix) are NOT user-facing checkpoints — chain through them. Stop only for high-stakes decisions or must-answer questions (see CLAUDE.md "Hallucinote Behavioral Norms").
- **`scaffold-only` mode** — the user asked for a *scaffold*, not a finished song ("set up a new song called X with these sections"; explicit args like `/song-new my-song "Title" 120 4/4 intro,verse,chorus`). Stop after Phase 2 + the instrument-pick step; produce the "Next steps" report so the user can drive composition themselves later.

Default to `make-me-X` if the user used a creative-product verb ("make / build / write me X") about a thing-to-be-experienced. Default to `scaffold-only` if the invocation looks like a structured slash-command call with explicit args, or if the user named the act of scaffolding directly ("scaffold a song," "set up a song template").

When ambiguous, state your inference ("Reading this as `make-me-X` — I'll drive through to a playable mix unless you stop me") and proceed.

## What you do

Two phases, in order:

**Phase 1 — Pre-composition elicitation** (`docs/song-new-checklist.md`):

Read what the user said. Infer everything you can. **State your inferences explicitly** — "you said 'disco prog-metal', so I'm assuming 120 BPM, 4/4, electric bass + acoustic drums, modal interchange in the bridge — say if you want different." Ask 2-3 targeted questions for the **must-haves** you genuinely can't infer (intent/purpose, genre, length/structure, vocals?, instrumentation). Default the **should-haves** (tempo/feel, time sig, harmonic strategy, production, arrangement arc) with "I'll go with N — say if you want different." Let **nice-to-haves** (references, hard constraints, hooks, density) emerge — only ask if the user volunteers something or the must-haves leave a gap.

This is **guidance, not a script.** Freeform exploration is allowed. The point is to surface what the user would want to fix later if you guessed wrong, before you write code.

For each non-trivial decision (especially must-haves), **write a markdown file under `songs/<slug>/decisions/`** (you'll do this in Phase 2 after the directory exists). Format: one file per decision, with the question, the answer, who decided (user / inferred / agreed-after-confirm), and the rationale. Future sessions read these via `/song-context` so the song's intent survives `/clear`.

**Phase 2 — Scaffold + first compose**:

Given the resolved slug + title + tempo + signature + sections (and optional key + intent from Phase 1), you:

1. Validate the inputs (slug shape, signature shape, non-empty section list).
2. Run `python3 -m tools.scaffold_song <slug> --title "..." --tempo X --signature N/D --sections ...` to produce `songs/<slug>/`.
3. Run `python3 songs/<slug>/build.py --reset` to populate the song's DB from the synthetic snapshot.
4. Run `pytest songs/<slug>/tests/ -v` to confirm the shape tests pass.
5. **Write Phase 1's decisions** to `songs/<slug>/decisions/NN-<topic>.md` — one file per decision. Number prefix (`01-intent.md`, `02-genre.md`, ...) for ordering.
6. **Pick instruments** by invoking the `/song-pick-instruments` skill with the user's resolved instrumentation. Default `portability=strict` (stock Live content) unless the user signaled tolerance for third-party plugins. The picks land in `captured_session.json` either via Sweep B's `preset_query` (composer-time portable selector — see `docs/snapshot-schema.md`) or via load-then-recapture once Live is staged.
7. Report the result + tell the user what to do next.

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

After the build + tests succeed, your behaviour depends on the mode you detected at the start.

**`make-me-X` mode** — keep going. The deliverable is the playable song, not the scaffold. Don't list "next steps" as user-facing checkpoints. State briefly what you did and what you're proceeding to (instruments → push → compose → mix), then do it:

> Scaffolded `songs/<slug>/` with N decisions in `decisions/`. Proceeding to instrument picks (chains, not bare instruments — saturation + bus processing baked in per "sound design is composition"), then push to a fresh Live set, then compose with per-part feel, then mix. I'll stop only if I hit a real decision point.

Then immediately invoke `/song-pick-instruments` and continue. Compose work happens in `build.py`; sound design (chains) ships in `captured_session.json` (see `docs/snapshot-schema.md` "Sound design is authorship"). Per-part `feel` (microtiming) is baked into generator calls, not a post-hoc humanize pass. Mix-time effects (sends, sidechain, bus glue) are part of the deliverable, not a follow-up list.

**`scaffold-only` mode** — stop after the pick step. Produce the checklist the user can drive themselves:

> Scaffolded `songs/<slug>/` with N decisions recorded in `decisions/`. Next steps:
>
> 1. **Pick instruments** — I'll invoke `/song-pick-instruments` to translate the instrumentation we discussed ("vintage analog poly + acoustic drums + ...") into actual device chains (instrument + saturation + bus processing). Default `portability=strict` — stock Live content only. Tell me if you want to allow third-party plugins.
> 2. **Push the scaffold to a fresh Live set** with `/ableton-push <slug> --new-session` so the device chains materialize.
> 3. **Recapture** with `tools/capture.py` so the resolved device URIs / params land in `captured_session.json`.
> 4. **Compose** — open `songs/<slug>/build.py` and replace the `=== Compose-half ===` placeholder. `songs/falling-walking/build.py` is the worked example (historical, not a literal template).

Stop after the scaffold + decisions + picks land, so the user can review and drive composition themselves.

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
