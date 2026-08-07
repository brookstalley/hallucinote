---
name: song-new
description: Scaffold a new Hallucinote song from templates, on values that are already resolved. Creates songs/<slug>/ with build.py, captured_session.json, tests/, decisions/, annotations/, attempts/ (the try→outcome ledger), and a song.md overview. Use when tempo, meter and the section list are ALREADY settled — given explicitly, or resolved by `/song-brief`. Starting from an open-ended prompt instead? Run `/song-brief` first: the scaffold takes those three values as required arguments, so invoking this against an unresolved prompt means inventing them, and the invented values become the song. Replaces the "copy from falling-walking" pattern that Wave 0 surfaced as a major onboarding friction.
user-invocable: true
disable-model-invocation: false
allowed-tools: Read, Write, Bash, Bash(pytest songs/*), Skill(song-brief)
argument-hint: >-
  <slug> "<title>" <tempo> <signature> <sections-csv> [optional: <key>] [optional: <intent>]
---

# /song-new

You scaffold a new Hallucinote song from templates, **on the values `/song-brief` resolved** — so the first composition decisions are defensible, not guessed to satisfy a command line.

$ARGUMENTS

> **Running engine commands.** The engine ships in the plugin's uv env — no separate install. Resolve `$PY` once from `ableton://server/info`'s `python`; scaffold + build run as `"$PY" -m hallucinote.cli …` (shown in full below). See [`docs/running-the-engine.md`](../../docs/running-the-engine.md).

## Read the request, not the requester (do this first)

Form **no judgment about the user's musical expertise** — no novice/expert branch, no fluency detection. Assess exactly one thing: *is this request specified enough to build a first concrete pass that matches what's in their head?* That is a property of the **ask**, not the **asker**. An expert's "four-movement symphony exploring atonality in the strings" is as underspecified as a hobbyist's "a Madonna song" — treat them identically: elicit toward *enough to start*, not enough to finish.

**Collaborate by default; clear direction always wins (precedence).** This replaces the old `make-me-X` / `scaffold-only` mode menu — collaboration is the stance, not one of two offered modes.

- When the user has **directed** a choice, execute it — don't re-propose what they already decided (directed action; obedience is unconditional — their ears are the authority). A fully-directed request, *especially* one that hands the rest back to the user ("build the skeleton, I'll take it from there"), means **build exactly what was specified and stop** — don't fork the parts they deferred into A/B questions. Over-proposing into directed work is friction.
- When they **haven't directed** an elementary choice you're about to make, **don't decide it silently** (that's auto-accompaniment) — propose it and invite reaction. A proposal the user doesn't object to is *confirmed* direction; a silent assumption is not. That line is the line between collaboration and auto-accompaniment.

**Two modes, one discipline:**

1. **Open elicitation** — request underspecified, user has more in their head: ask, lightly, *only* the load-bearing unknowns (where a wrong guess wastes real work or is a creative lock-in — tonal concept, form, the central tension). At most one or two questions before you hand them something concrete; more is interrogation.
2. **Proposal elicitation** — when open questions stop yielding direction (the user says "I don't know, you decide," repeats a vague answer, or trails off): **stop asking, start proposing.** A concrete, redirectable proposal — ideally a small set of *distinct* options. Choosing between concretes is the easiest way to discover what you actually wanted. Read "that's all I've got" as *propose now*, never *assume now*, and never *ask a fourth question*.

**The one discipline across both: never assume-and-go.** Every gap is either elicited or proposed-and-reacted-to.

**Load-bearing only; just-do-and-show the cheap choices.** Elicit at the expensive forks; make cheap-to-revise choices tastefully and *show* them — the artifact becomes the next proposal, instantly redirectable. Don't fork every elementary choice into an A/B.

**Name the why.** When you propose, carry the reasoning in *one plain collaborator's sentence* — "I held the verse back so the chorus opens up," never "this is a deceptive cadence, which in theory…". The expert skims it; the novice learns from it; you never decided which is which. The theory vocabulary only surfaces if the user reaches for it. **Never a classroom; never homework.**

**The third register — directed-but-under-articulated.** When the user asks for something they can't yet specify — "make it feel like Bach," "a pop song like Madonna" — that is neither a directive to execute nor a question to fire back. **Open the domain:** propose concrete, *hearable* options (e.g. walking bass under the kit vs late-resolving suspensions), name the why in one sentence, and offer a real choice. This fires on the **request** (the dimension is unpinned), never on a judgment that the user is a novice. **Never** silently generate a best-guess and move on — that is the core failure.

**Gap-inversion for thin dimensions.** Per the capability-honesty note below, when a request leans on a thin dimension (melody *authoring* ◐, vocal synthesis ✗), invert the gap into an invitation — "sketch your topline in Ableton and I'll build the track under it, then read whether the line lands its intent" (round-trip is fully supported; the melody lens reads the line — `/compose-review`). Caveat the thin dimension, deliver the rest, never silently substitute.

### Deliverable shape — a read, not an offered mode

Do **not** ask the user to pick "build it all for me" vs "just scaffold it" — offering the do-it-for-you path surfaces the dependence framing. **Read** the deliverable shape from what they asked, state your read in one sentence so they can correct it, and proceed:

- **Creative product prompt** ("make / build / write me a song like X" — a thing to press play on): drive end-to-end to a playable result, *collaborating on the elementary choices you'd otherwise guess at*. Skill boundaries (`/song-new` → `/song-pick-instruments` → `/ableton-push` → compose → re-push → mix) are NOT user-facing checkpoints — chain through them, stopping only for high-stakes decisions, must-answer questions, or a collaborative proposal at a creative lock-in (see CLAUDE.md "Hallucinote Behavioral Norms"). "Drive end-to-end" never means "decide the elementary musical choices silently" — propose them.
- **Scaffold request** (structured slash-command call with explicit args like `/song-new my-song "Title" 120 4/4 intro,verse,chorus`, or "set up / scaffold a song"): this *is* directed action — produce the scaffold + instrument picks + the "Next steps" report, and don't over-collaborate on choices the user deferred to a later sitting.
- **The build-it-all-for-me path exists but is never *offered*.** A user can ask for it outright ("just make me something, I trust you") and you oblige — but never put it on the table as a menu choice.

When ambiguous, state your inference ("Reading this as a finished song — I'll drive through to a playable mix, checking with you at the creative forks") and proceed.

## What you do

Two phases, in order:

**Phase 1 — Pre-composition elicitation → `/song-brief`**:

**The elicitation pass is its own stage and it runs first.** Invoke
**`/song-brief`** with the user's starting prompt. It sweeps the load-bearing
dimensions (marking each DECIDED / UNDECIDED / NOT-APPLICABLE), closes the
undecided ones in **one consolidated turn of informed proposals**, and writes
`annotations/01-the-brief.md`. `docs/song-new-checklist.md` is the dimension
reference it draws on.

**This matters structurally, not just procedurally.** The scaffold command below
takes tempo, meter and the section list as **required arguments** — exactly the
values elicitation exists to resolve. Run this skill without a brief and you
will invent those three values to make the command run, and the invented values
become the song. **Take them from the brief.**

Skip straight to Phase 2 only when the request is *directed* — a structured
`/song-new <slug> "<title>" 120 4/4 intro,verse,chorus` call, or a prompt that
already pins every applicable dimension. `/song-brief` is also silent in that
case, so invoking it costs nothing when there is nothing to ask.

This is **guidance, not a script.** Freeform exploration is allowed. The point is to surface what the user would want to fix later if you guessed wrong, before you write code.

**Stay capability-honest.** Read `docs/capability-truth.md` (the single source of truth for what Hallucinote can do *right now*, organized as song dimensions). Use it to (a) keep your inferences and offers truthful — never promise a capability that isn't ✓ or ◐ there, (b) generate an *accurate, dimensional* caveat when the request leans on a thin dimension (melody ◐, vocal synthesis ✗), and (c) **invert** a thin dimension into an invitation rather than gating the goal — e.g. "bring me your topline, sketch it in Ableton, and I'll build the track under it" (round-trip is fully supported). Caveat the thin dimension, then deliver the rest; never silently substitute.

For each non-trivial decision (especially must-haves), **write a markdown file under `songs/<slug>/decisions/`** (you'll do this in Phase 2 after the directory exists). Format: one file per decision, with the question, the answer, who decided (user / inferred / agreed-after-confirm), and the rationale. Future sessions read these via `/song-context` so the song's intent survives `/clear`.

**Phase 2 — Scaffold + first compose**:

**First, confirm you're in a songs workspace** (high-stakes: it decides where the song lives). Run `"$PY" -m hallucinote.cli init-workspace --check` and read `already_workspace`. If it's `false`, the scaffold would land in `./songs/<slug>` relative to cwd — *not* a tracked Hallucinote workspace. Surface it and offer to fix it before scaffolding: *"You're not in a songs workspace — want me to create one here? (writes the `hallucinote.toml` marker, a `.gitignore` for regenerable artifacts, and `git init`s)"* → on yes, `"$PY" -m hallucinote.cli init-workspace`; or let the user `cd` to their existing songs repo and restart. **Never scaffold into a non-workspace silently.**

Given the resolved slug + title + tempo + signature + sections (and optional key + intent from Phase 1), you:

1. Validate the inputs (slug shape, signature shape, non-empty section list).
2. Run `"$PY" -m hallucinote.cli scaffold <slug> --title "..." --tempo X --signature N/D --sections ...` to produce `songs/<slug>/`.
3. Run `"$PY" songs/<slug>/build.py --reset` to populate the song's DB from the synthetic snapshot.
4. Run `pytest songs/<slug>/tests/ -v` to confirm the shape tests pass.
5. **Write Phase 1's decisions** to `songs/<slug>/decisions/NN-<topic>.md` — one file per decision. Number prefix (`01-intent.md`, `02-genre.md`, ...) for ordering.
6. **Pick instruments** by invoking the `/song-pick-instruments` skill with the user's resolved instrumentation. Default `portability=strict` (stock Live content) unless the user signaled tolerance for third-party plugins. The picks land in `captured_session.json` either via Sweep B's `preset_query` (composer-time portable selector — see `docs/snapshot-schema.md`) or via load-then-recapture once Live is staged.
7. **Postlude:** call `ableton_render(action='ensure_loaded')` silently — **with no other params**. It loads the analyzer onto every existing surface; unlike `render`, it takes no `song_slug` (passing one errors `unknown param(s)`).
8. Report the result + tell the user what to do next.

## Gathering input

The user usually invokes this conversationally ("let's start a new song called 'punk-fate' at 160 BPM, 4/4, with intro/verse/chorus/bridge sections"). Map their words to the CLI args:

- **slug** (required) — filesystem-safe identifier: lowercase letters, digits, hyphens, underscores; no leading hyphen/underscore. Reject names with spaces/uppercase/special chars (the CLI also enforces this).
- **title** (required) — human-facing display name, free-form text. Quote it for the shell.
- **tempo** (required) — BPM as a number. For non-4/4 meters where the user gave an "eighth pulse" tempo, convert to the quarter pulse (Live's BPM is always the quarter pulse).
- **signature** (required) — `N/D` (e.g., `4/4`, `7/8`, `3/4`).
- **sections** (required) — comma-separated list (e.g., `intro,verse,chorus,outro`).
- **key** (optional) — musical key (e.g., `Dm`, `Bb`). Surface to the user that this is informational metadata, not a constraint enforced anywhere.
- **intent** (optional) — one-paragraph composer intent that goes into `songs/<slug>/<slug>.md`. If the user just gave you a vibe ("make it feel like late-night driving"), pass that as `--intent`.

If anything's missing or ambiguous, that is a gap for `/song-brief` to close —
**not** a value to default silently at the command line. Don't interrogate; one
consolidated turn of proposals settles it.

## Exit criteria — this stage is done when

- Tempo, meter and the section/bar list are **values from the brief**, not
  invented to satisfy the CLI.
- The scaffold builds (`build.py --reset`) and its shape tests pass.
- Each of the brief's substantive resolutions is filed in `decisions/`.
- Nothing this stage wrote is DESCRIBED-BUT-UNBUILT — no `<slug>.md` or decision
  record names a mechanism that doesn't exist.

Full model: [docs/song-workflow.md](../../docs/song-workflow.md#stage-exit-criteria).

## Refusal cases

The scaffolder refuses (non-zero exit) on:
- Invalid slug → ask the user to pick a valid one.
- Existing `songs/<slug>/` directory → ask the user whether to remove it (`rm -rf songs/<slug>/`) and re-run, or pick a different slug. Don't auto-delete without confirmation.

## After successful scaffold

The scaffolder writes:

```
songs/<slug>/
  build.py                 (state-converger wrapping M.build_session)
  captured_session.json    (synthetic 4 MIDI + 2 returns + master)
  <slug>.md                (overview — composer intent + structure)
  tests/test_<slug>_build.py  (shape + converger tests)
  decisions/.gitkeep
  annotations/.gitkeep
```

Two important defaults the scaffold uses:
- **Synthetic snapshot.** `captured_session.json` is generic (2 returns + 4 MIDI tracks + master) so the build runs immediately against a brand-new DB. The user should replace it by capturing a real Live snapshot once they've staged the target Live shape. Capture today is manual via `hallucinote.tools.capture_cli`.
- **State-converger build.py.** Re-running the build (no `--reset`) is a no-op when nothing changed — the converger guarantees zero net events. `--reset` is for "wipe the DB and start fresh" only.

## Final report to user

After the build + tests succeed, your behaviour depends on the **deliverable shape** you read at the start.

**Creative product prompt** — keep going. The deliverable is the playable song, not the scaffold. Don't list "next steps" as user-facing checkpoints. State briefly what you did and what you're proceeding to (instruments → push → compose → mix), then do it:

> Scaffolded `songs/<slug>/` with N decisions in `decisions/`. Proceeding to instrument picks (chains, not bare instruments — saturation + bus processing baked in per "sound design is composition"), then push to a fresh Live set, then compose with per-part feel, then mix. I'll stop only if I hit a real decision point.

Then immediately invoke `/song-pick-instruments` and continue. Compose work happens in `build.py`; sound design (chains) ships in `captured_session.json` (see `docs/snapshot-schema.md` "Sound design is authorship"). Per-part `feel` (microtiming) is baked into generator calls, not a post-hoc humanize pass. Mix-time effects (sends, sidechain, bus glue) are part of the deliverable, not a follow-up list.

**After the first compositional pass, evaluate it against intent — `/compose-review`.** Novices can generate but not yet *evaluate*; this is where the lesson consolidates. Before (and separately from) the mix, help the user hear whether the composition does what the song is trying to do — "you wanted the chorus to lift; here's whether it does; here's the one thing holding it back" — framed as a question, never a verdict. It teaches contrast and subtraction by ear, and learns section/song intent back into the corpus. Don't skip straight to mixing a composition the user hasn't been helped to hear.

**Scaffold request** — stop after the pick step. Produce the checklist the user can drive themselves:

> Scaffolded `songs/<slug>/` with N decisions recorded in `decisions/`. Next steps:
>
> 1. **Pick instruments** — I'll invoke `/song-pick-instruments` to translate the instrumentation we discussed ("vintage analog poly + acoustic drums + ...") into actual device chains (instrument + saturation + bus processing). Default `portability=strict` — stock Live content only. Tell me if you want to allow third-party plugins.
> 2. **Push the scaffold to a fresh Live set** with `/ableton-push <slug> --new-session` so the device chains materialize.
> 3. **Recapture** with `hallucinote.tools.capture_cli` so the resolved device URIs / params land in `captured_session.json`.
> 4. **Compose** — open `songs/<slug>/build.py` and replace the `=== Compose-half ===` placeholder. `songs/falling-walking/build.py` is the worked example (historical, not a literal template).

Stop after the scaffold + decisions + picks land, so the user can review and drive composition themselves.

## Workflow

```
0. "$PY" -m hallucinote.cli init-workspace --check
   → if already_workspace is false, offer to create one (high-stakes: where the song lands).
1. Validate inputs (slug, signature, sections).
2. "$PY" -m hallucinote.cli scaffold <slug> --title "..." --tempo N \
       --signature N/D --sections a,b,c [--key K] [--intent "..."]
3. "$PY" songs/<slug>/build.py --reset
4. pytest songs/<slug>/tests/ -v
5. Report.
```

## Conventions

- Per-song test files use unique basenames (`test_<slug>_build.py`, not bare `test_build.py`). Wave 0 surfaced the collision the hard way.
- Sections default to 8 bars each. The scaffold uses this for cue-point placement; the user can adjust constants in `build.py` afterwards.
- Generators today assume 4/4. For non-4/4 songs, hand-author until meter-parametrized generators ship.
- Master/group/return automation IS supported — author the envelope in `build.py`; push performs it into arrangement automation (transport plays in real time, fingerprint-gated). Plain MIDI/audio-track envelopes are also supported (ENV-9P4T): a song-spanning / clip-independent ride performs as a continuous arrangement lane; a within-one-clip ride routes through that session clip.
- **No within-song meter change can be recorded today** — `M.add_time_signature_point` raises for any `start_bar > 1.0`, per-section changes included (Live 12.4's MCP has no `song_signature` automation target). Scaffold with the song's *primary* meter as the global one. This is a **projection** limitation, not a modelling one: the song is in 7/4 if it's in 7/4. Record the true meter in the brief, mark the row open with the engine as its owner, and realize the rest as felt groove over the single ruler — never ask the user to accommodate it. See `docs/song-authoring-conventions.md` → *Meter*.
