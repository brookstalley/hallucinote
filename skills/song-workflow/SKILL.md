---
name: song-workflow
description: >-
  The song-creation lifecycle map — the phases of making a song here, the skill that runs each, each stage's definition of done, and the three checkpoints agents most often miss (`/song-brief` before scaffolding, `/compose-review` after composing, `/mix-review` after the mix). READ THIS FIRST for any song work: when the user asks to make / build / write / compose / arrange / mix a song, or when you're unsure which skill comes next. Carries the rule that a stage may not emit an unresolved gap. The stance is creativity-first (intent is the ruler; aesthetics never block) with the tools to go as deep as the art demands. Links to docs/song-workflow.md for the full depth and the research corpus.
argument-hint: "[phase or topic — optional]"
user-invocable: true
disable-model-invocation: false
allowed-tools: Read
---

# /song-workflow — the map for making a song here

Making a song is a **loop, not a line**: you elicit, scaffold, compose, push to
Live, mix, and circle back. This skill is the map of that arc — which skill runs
each phase, and the three checkpoints that are easy to skip and shouldn't be.
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

0. ⭐ **Elicit the brief** — **`/song-brief`**. Before scaffolding: form a musical
   read *silently*, then split what the song depends on by **whose choice it is**.
   **Identity** (what it should do to someone, whether anyone is singing, the
   harmonic world, what it sounds like, the shape) is the composer's — ask openly,
   no recommendation. **Craft** (BPM, meter arithmetic, voicings, generators, mix
   moves) is yours — decide and show, never ask. Bounded by shape, not a turn
   count: every turn carries new work, ≤2 questions. Output is
   `annotations/01-the-brief.md` — the origin record, and the source of the
   tempo / meter / section values `/song-new` needs as arguments. Silent when a
   directed prompt leaves nothing open.
1. **Frame the intent** — `/song-new` scaffolds the song *from the brief's
   values*; `/song-context` recalls prior intent. At an elementary fork the user
   hasn't directed (key, the central tension, what the chorus does), *ask it
   openly* — don't auto-decide, and don't staple a recommendation to it (that
   closes the fork). Before re-touching a part you've worked before,
   `/song-attempts` recalls what was already tried (and reverted) so you don't
   re-propose a dead end.
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
6. **Capture + analyze** — **`/render-analyze`** runs `ableton_render` →
   `ableton_analysis` in one step and hands back just the MixReport summary
   (the render + analyze are realtime/long start+poll actions, so it delegates
   their poll loops to a subagent — keeping the plumbing out of your context).
   The MixReport it builds is what step 7 reads.
7. ⭐ **Read the mix** — **`/mix-review`** (needs Max for Live — Suite or the
   M4L add-on; `/compose-review` is the any-edition alternative). Interpret the
   MixReport against intent — masking, loudness, feel, energy per section.
8. **Snapshot + iterate** — `/song-snapshot` (the single durable mix bake) and
   `/ableton-pull` (build.py-staging). Then loop back to compose or mix. As you iterate, log what you
   *tried* and how it turned out — especially reverted dead ends — to the **attempt
   ledger** (the two review checkpoints propose the entries; recall via `/song-attempts`),
   so each loop starts smarter instead of re-running a move that already failed.

## A stage may not emit an unresolved gap

Under-specifying is the user's prerogative; **closing the gap is the stage's
job** — by deciding it in-stage (propose, read the reaction) or by marking it
explicitly open. What is forbidden is passing an unresolved gap downstream *in
the clothes of a decision*: a docstring naming a device nobody built, a brief
naming a destination with no route. Nothing fails when that happens — the build
runs clean and the push reports OK — which is exactly why it needs a rule.

Every dimension a stage touches ends **DECIDED**, **UNDECIDED** (named, with an
owner), or **NOT-APPLICABLE** (recorded, never asked about). Only UNDECIDED
blocks a stage. Not-applicable is a real answer you reach by your own judgement
— an ambient piece has no drum style to specify, and asking anyway reads as
incompetence.

Each stage's **definition of done** is in
[docs/song-workflow.md](../../docs/song-workflow.md#stage-exit-criteria); the
design is
[elicitation-and-stage-exit-criteria.md](../../.prawduct/artifacts/elicitation-and-stage-exit-criteria.md).

## The three checkpoints agents miss

`/song-brief` (step 0) **specifies** the work; `/compose-review` (step 4) and
`/mix-review` (step 7) apply the framework's *ear* to it. None is optional
polish.

`/song-brief` runs before you scaffold, because `/song-new` takes tempo, meter
and the section list as **required arguments** — skip the brief and you invent
those three values to make a command run, and the invented values become the
song.

Reach for the other two after a compositional pass and after an analysis pass
respectively, or whenever the user asks "does this work?", "is the hook
landing?", "how's the mix?", "is anything masking the vocal?", "what's
missing?". Both surface a producer's question (never a score) and learn revealed
intent back so they never re-flag a choice you've confirmed.

If you only remember one thing: **before you scaffold, run `/song-brief`; after
you compose, run `/compose-review`; after you analyze, run `/mix-review`.**

## Go deeper

[docs/song-workflow.md](../../docs/song-workflow.md) carries the full lifecycle,
the **five expertise layers**, and links into the research corpus
(arrangement · melody · performance · masking · intent). The depth ladder:
helpers → review lenses → the research → hand-author. Go as far down as the art
demands.

Rare side-paths live off the mainline so the common case stays simple — e.g.
**alternate tunings** (non-12-TET songs): load the `.ascl` in Live, `/tuning-pull`
to capture it, author in scale degrees. → [docs/alternate-tunings.md](../../docs/alternate-tunings.md).
