---
name: song-workflow
description: >-
  The song-creation lifecycle map — the phases of making a song here, the skill that runs each, the two review checkpoints agents most often miss (`/compose-review` after composing, `/mix-review` after the mix), and the expertise behind them. READ THIS FIRST for any song work: when the user asks to make / build / write / compose / arrange / mix a song, or when you're unsure which skill comes next. The stance is creativity-first (intent is the ruler; aesthetics never block) with the tools to go as deep as the art demands. Links to docs/song-workflow.md for the full depth and the research corpus.
argument-hint: "[phase or topic — optional]"
user-invocable: true
disable-model-invocation: false
allowed-tools: Read
---

# /song-workflow — the map for making a song here

Making a song is a **loop, not a line**: you scaffold, compose, push to Live,
mix, and circle back. This skill is the map of that arc — which skill runs each
phase, and the two review checkpoints that are easy to skip and shouldn't be.
The depth (the *why*, grounded in the research) is
[docs/song-workflow.md](../../docs/song-workflow.md); this is the at-a-glance
version.

## Creativity first, depth on demand

Hallucinote is a **producer, not a gatekeeper**. Never decline a directed
request; never make a creative decision for the user without surfacing it; treat
every measurement as a producer's *question* ("is the chorus landing?"), never a
verdict. Aesthetic choices — a near-silent part, a drone, a dissonance, an odd
meter — are valid art and never fail a build. And the toolkit is a convenience,
never a ceiling: when a helper doesn't reach far enough, drop a level — down to
hand-authored notes if that's what the art needs.

## The arc

1. **Frame the intent** — `/song-new` scaffolds the song; `/song-context`
   recalls prior intent. At an elementary fork the user hasn't directed (key, the
   central tension, what the chorus does), *propose and read their reaction* —
   don't auto-decide. Before re-touching a part you've worked before, `/song-attempts`
   recalls what was already tried (and reverted) so you don't re-propose a dead end.
2. **Pick instrument chains** — `/song-pick-instruments`. The chain (instrument +
   FX + sends) is authorship that ships in the snapshot — sound design *is*
   composition, not a mix-time todo.
3. **Compose the parts** — `/compose-part` (author-as-code in `build.py`).
   Melody, feel, and form are authorship: microtiming feel is baked in at
   generation time, not humanized after.
4. ⭐ **Read the composition** — **`/compose-review`**. After a first pass, read
   the composition + the melody and recurrence lenses *against intent*. Runs
   **before** the mix.
5. **Materialize in Live** — `/ableton-push` (the 14-phase push).
6. **Capture + analyze** — `ableton_render` → `ableton_analysis` builds the
   MixReport (the expensive real-time step).
7. ⭐ **Read the mix** — **`/mix-review`**. Interpret the MixReport against
   intent — masking, loudness, feel, energy per section.
8. **Snapshot + iterate** — `/song-snapshot`, `/snapshot-bake-recent-changes`,
   `/ableton-pull`. Then loop back to compose or mix. As you iterate, log what you
   *tried* and how it turned out — especially reverted dead ends — to the **attempt
   ledger** (the two review checkpoints propose the entries; recall via `/song-attempts`),
   so each loop starts smarter instead of re-running a move that already failed.

## The two checkpoints agents miss

`/compose-review` (step 4) and `/mix-review` (step 7) are **not optional
polish** — they are how the framework's *ear* gets applied to your work. Reach
for them after a compositional pass and after an analysis pass respectively, or
whenever the user asks "does this work?", "is the hook landing?", "how's the
mix?", "is anything masking the vocal?", "what's missing?". Both surface a
producer's question (never a score) and learn revealed intent back so they never
re-flag a choice you've confirmed.

If you only remember one thing: **after you compose, run `/compose-review`;
after you analyze, run `/mix-review`.**

## Go deeper

[docs/song-workflow.md](../../docs/song-workflow.md) carries the full lifecycle,
the **five expertise layers**, and links into the research corpus
(arrangement · melody · performance · masking · intent). The depth ladder:
helpers → review lenses → the research → hand-author. Go as far down as the art
demands.
