---
name: song-workflow
description: >-
  The song-creation lifecycle map — the phases of making a song here, the skill that runs each, each stage's definition of done, and the three checkpoints agents most often miss (`/song-brief` before scaffolding, `/compose-review` after composing, `/mix-review` after the mix), and where in the loop the user first hears something (after the first hearable unit — offered, never required). READ THIS FIRST for any song work: when the user asks to make / build / write / compose / arrange / mix a song, or when you're unsure which skill comes next. Carries the rule that a stage may not emit an unresolved gap. The stance is creativity-first (intent is the ruler; aesthetics never block) with the tools to go as deep as the art demands. Links to docs/song-workflow.md for the full depth and the research corpus.
argument-hint: "[phase or topic — optional]"
user-invocable: true
disable-model-invocation: false
allowed-tools: Read
---

# /song-workflow — the map for making a song here

Making a song is a **loop, not a line**: you elicit, scaffold, compose the first
**hearable unit**, push it, **offer** to play it, and circle back — the rest of
the song is built the same way, one unit at a time, each offered before the next
is authored. The first pass through the loop is short on purpose: the user hears
something before the palette for twelve tracks exists, not after. This skill is
the map of that arc — which skill runs each phase, where the hearing sits, and
the three checkpoints that are easy to skip and shouldn't be. The depth (the
*why*, grounded in the research) is
[docs/song-workflow.md](../../docs/song-workflow.md); this is the at-a-glance
version. The vocabulary — *hearable unit*, *turn kind*, *the status offer*,
*decline with scope*, *owner column* — is defined in
[collaboration-turn-model.md](../../.prawduct/artifacts/collaboration-turn-model.md)
and short-defined in [CLAUDE.md](../../CLAUDE.md), which loads every session;
this skill uses the words and does not redefine them.

## Creativity first, depth on demand

Hallucinote is a **producer, not a gatekeeper**. Never decline a directed
request; never make a creative decision for the user without surfacing it; treat
every measurement as a producer's *question* ("is the chorus landing?"), never a
verdict. Aesthetic choices — a near-silent part, a drone, a dissonance, an odd
meter — are valid art and never fail a build. And the toolkit is a convenience,
never a ceiling: when a helper doesn't reach far enough, drop a level — down to
hand-authored notes if that's what the art needs.

The producer's pacing is a **two-sided rule**, and both halves are load-bearing:
**never stop to summarize-and-ask** at a procedural seam — a finished phase is
not a decision point, and "scaffold done, what next?" is the failure the
stop-less norm exists to prevent; and **never build past a hearable unit without
offering to play it** — the unit is the bound on what you author unheard, and
"the whole song, rendered last" is the failure the hearing offer exists to
prevent. Keep only the first half and the user hears nothing for an hour; keep
only the second and every seam becomes a checkpoint. The offer is for what the
user left open: a choice they directed, or a hearing rhythm they set ("build it
all, I'll listen at the end"), is theirs and is not re-opened.

## The arc

0. ⭐ **Elicit the brief** — **`/song-brief`**. Before scaffolding, hold the
   conversation that ends at the user's hand-off: ask the two or three identity
   questions you cannot guess, propose the rest as redirectable reads (never a
   questionnaire), and keep reading each reply — an answer that adds a noun is
   not a closure, and identity never closes by inference. Output is
   `annotations/01-the-brief.md` — the origin record, updated every turn, and
   the source of the tempo / meter / section values `/song-new` needs as
   arguments. What the user directed is taken as read, not re-asked; when a
   directed prompt leaves nothing applicable open, there is nothing to ask —
   execute. The conversation is the design's, not this skill's:
   [collaboration-turn-model.md](../../.prawduct/artifacts/collaboration-turn-model.md).
1. **Frame the intent** — `/song-new` scaffolds the song *from the brief's
   values*; `/song-context` recalls prior intent. At an elementary fork the user
   hasn't directed (key, the central tension, what the chorus does), *propose and
   read their reaction* — don't auto-decide. Before re-touching a part you've
   worked before, `/song-attempts` recalls what was already tried (and reverted)
   so you don't re-propose a dead end. Composing to a sample, `/sample-lens` reads
   the line (pitch centre, phrases, detector fires against bars) first.
2. **Pick instrument chains** — `/song-pick-instruments`. The chain (instrument +
   FX + sends) is authorship that ships in the snapshot — sound design *is*
   composition, not a mix-time todo.
3. **Compose the parts** — `/compose-part` (author-as-code in `build.py`).
   Melody, feel, and form are authorship: microtiming feel is baked in at
   generation time, not humanized after. **Compose the first hearable unit
   first** — one part, one section — and get it into the user's ears: one full
   `/ableton-push` creates and links the structure (that is `/compose-part`'s
   precondition — its scoped `push-notes` only reaches already-linked clips,
   and errors per clip otherwise), after which each pass is audible in Live as
   soon as it exists. Then **offer** a hearing, as the status offer: what is
   settled, hear it or keep going, what has not come up (named, not asked). It
   fires when a unit is hearable *and* the user's last turn closed something;
   if their last turn opened something, follow the opening instead, and if
   nothing is hearable yet, propose one concrete thing toward it. "Keep going"
   is a complete answer and authorizes the next unit; a decline with scope is
   recorded in the brief's owner column and not re-asked. After they listen, a
   listening report is a *reacting* turn, not authorization: interpret it,
   adjust what they pointed at, name any confound in your own study's design,
   offer at most one concrete next move, and wait. Then the next unit, the same
   way — never the rest of the song in one pass.
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
   M4L add-on; `/compose-review` is the symbolic alternative, on Standard too). Interpret the
   MixReport against intent — masking, loudness, feel, energy per section.
8. **Snapshot + iterate** — `/song-snapshot` (the single durable mix bake) and
   `/ableton-pull` (build.py-staging). Then loop back to compose or mix. As you iterate, log what you
   *tried* and how it turned out — especially reverted dead ends — to the **attempt
   ledger** (the two review checkpoints propose the entries; recall via `/song-attempts`),
   so each loop starts smarter instead of re-running a move that already failed.
   The hearing offer rides every pass, not just the first: each loop through
   compose ends at a unit the user could hear, and the offer is made again —
   unless they declined with a scope that has not yet been reached.

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
[elicitation-and-stage-exit-criteria.md](../../.prawduct/artifacts/elicitation-and-stage-exit-criteria.md)
for the three states, and
[collaboration-turn-model.md](../../.prawduct/artifacts/collaboration-turn-model.md)
for the conversation, the hearable unit and the status offer.

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

If you only remember four things: **before you scaffold, run `/song-brief`;
after you compose, run `/compose-review`; after you analyze, run `/mix-review`;
and after the first hearable unit is in Live, offer to play it before you build
the next** — offered, never required, and not re-offered inside a scope the user
declined.

## Go deeper

[docs/song-workflow.md](../../docs/song-workflow.md) carries the full lifecycle,
the **five expertise layers**, and links into the research corpus
(arrangement · melody · performance · masking · intent). The depth ladder:
helpers → review lenses → the research → hand-author. Go as far down as the art
demands.

Rare side-paths live off the mainline so the common case stays simple — e.g.
**alternate tunings** (non-12-TET songs): load the `.ascl` in Live, `/tuning-pull`
to capture it, author in scale degrees. → [docs/alternate-tunings.md](../../docs/alternate-tunings.md).
