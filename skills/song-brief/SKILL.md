---
name: song-brief
description: >-
  Turn a starting prompt into the song's brief — the elicitation stage that runs BEFORE /song-new. Sweeps the load-bearing dimensions (harmony, tempo, production stance, named narrative turns, meter, the section time budget, and the mechanism behind every named gesture), marks each DECIDED / UNDECIDED / NOT-APPLICABLE, and puts every applicable-but-undecided one into ONE consolidated turn of informed proposals with a recommendation — never a questionnaire. Writes `annotations/01-the-brief.md`, which becomes the song's origin record and the input to /song-new. Use whenever a song starts from a prompt rather than from explicit scaffold arguments, or when asked "what do you need to know?" / "what's underspecified here?".
argument-hint: "<the user's starting prompt, or a slug for an existing song>"
user-invocable: true
disable-model-invocation: false
allowed-tools: Read, Write, Glob, Grep, Bash, Skill(song-context), Skill(song-attempts)
---

# /song-brief — the elicitation stage

$ARGUMENTS

You turn a **starting prompt** into the song's **brief**: the origin record that
every later stage reads, and the artifact that proves no load-bearing question
was passed downstream dressed as a decision.

This is stage **0** of `/song-workflow`, and it runs **before** `/song-new` — not
inside it. `/song-new`'s scaffold command requires tempo, meter and the section
list as arguments, which are exactly the values this stage produces. Running it
first is what stops those values from being invented at a command line.

Design + rationale: [`.prawduct/artifacts/elicitation-and-stage-exit-criteria.md`](../../.prawduct/artifacts/elicitation-and-stage-exit-criteria.md).

## The rule this stage exists to enforce

> **A stage may not emit an unresolved gap.**

Under-specifying is the user's prerogative. *Closing* the gap is the stage's job
— by deciding it here (propose, and read the reaction) or by marking it
explicitly open. What is forbidden is passing an unresolved gap downstream **in
the clothes of a decision**: a docstring that names a device nobody built, a
brief that names a destination with no route. That is not a gap, it is a lie
with a timestamp, and it is how the v1 demo song shipped an octave drop that did
not exist.

## Step 1 — the relevance sweep (silent)

For each dimension below ask **one** question: *does the song, as described so
far, depend on this?* Assign one of three states. Never two.

- **DECIDED** — the user pinned it, or it follows unambiguously from what they
  pinned. Restate it in the brief so it's correctable; do **not** re-ask it.
- **UNDECIDED** — the song depends on it and nobody has chosen. **This, and only
  this, goes into the turn.**
- **NOT-APPLICABLE** — the material doesn't imply it. Record it in the brief and
  **say nothing to the user.** This is a real answer you reach by your own
  judgement from the material; it never requires asking.

**Silence about a non-applicable dimension is correct. Silence about an
undecided one is the defect.**

An ambient soundscape has no drum style, no meter argument, and possibly no
tempo worth pinning. Asking anyway is not thoroughness — it reads as
incompetence. The table below is a prompt for thinking, **not a form to fill
in**; most songs will mark several rows NOT-APPLICABLE.

| Dimension | Applicable when | Why it bites |
|---|---|---|
| **Harmony** — key, mode, progression | the prompt makes any tension/release claim | "tension → dissolve → resolve" is a harmonic claim; without a key it's a mood word |
| **Tempo** | a duration is stated, or the groove depends on pulse | 45 s at 90 and at 140 BPM are different songs; the section budget is unsolvable without it |
| **Production stance** | the prompt names ≥2 sonic worlds | do the worlds argue in the production too, or only in the writing? A whole-record choice, made once |
| **Named narrative turns** | a turn is named with no musical mechanism | *"suddenly major somehow"*, *"finally integrated"* — a destination with no route |
| **Meter** | any metrical claim beyond a steady 4 | see *Meter* below — ask what it **is**, never how to fake it |
| **Section time budget** | a duration is stated **and** sections are named | v1 under-budgeted three of its own best moments; arithmetic catches this, taste doesn't |
| **Mechanism per named gesture** | the prompt names an audible event — a bend, a riser, a drop, a crash | **the most important row.** A gesture is not DECIDED until the thing that produces it is named |

Anything not in this table that the prompt clearly leans on is also fair game —
this is guidance, not a schema.

## Step 2 — one consolidated turn

Every UNDECIDED row, plus anything you're *telling* rather than *asking*, goes
into **one message**. Not sequential Q&A: ping-pong burns the user's patience and
violates the stop-less norm for real.

**Propose; never interrogate.** Each item is an informed proposal carrying its
reasoning and a recommendation, inviting a one-word reaction:

> *"I'd propose 132 BPM. 45 s at 132 is ~33 bars of budget, which fits your eight
> moments with the 7/4 chorus bar at 3.2 s — long enough for the cross-rhythms to
> be heard rather than implied. Above ~144 the 7/4 stops feeling relaxed."*

not

> *"What tempo do you want?"*

A blank question is auto-accompaniment wearing a politeness costume: it looks
collaborative and transfers zero expertise. Where a real fork exists, name the
recommendation **and** the alternative in one sentence each, so the user is
choosing between concretes.

**Carry the why in one plain collaborator's sentence** — *"I held the verse back
so the chorus opens up"*, never *"this is a deceptive cadence, which in
theory…"*. Never a classroom; never homework.

**Some items are statements, not questions.** Arithmetic (the time budget) and
mechanism pins (the octave drop = a master Shifter automated pre-limiter) are
things you *tell* the user, ending with "say if you want it different". They
still belong in the turn, because they are exactly the gaps that go unnoticed
when nobody says them out loud.

**Cheap choices are shown, not asked.** Make them tastefully and state them in a
clause; the artifact becomes the next proposal and is instantly redirectable.
Only expensive-to-reverse forks earn a proposal.

**Silence is a valid pass.** A fully-directed prompt with no applicable
undecided dimension produces a brief with a resolution table and **no questions**
— hand back the brief and let the lifecycle advance to `/song-new` without
stopping. ("Advance to" is not "invoke": see Step 3 — this stage hands back
resolved values, it never runs the scaffold itself.) This stage is not obliged
to find something.

### The bound: one turn, and it is not renegotiable

**This stage gets exactly one consolidated turn.** Whatever the user's reaction
to it is — answers, partial answers, "just go", or silence on some items — the
stage then *closes*. It does not open a second round to chase the rows they
didn't address.

An item the user left unanswered is **not** a reason to ask again. It becomes an
UNDECIDED row in the brief, with an owner and the stage that will close it, and
the work proceeds. That is the whole point of having three states: the gap
travels forward *visibly* instead of being either hidden or re-litigated.

Two failure modes this bounds, both of which look like diligence:

- **The stage that never converges** — each answer surfacing a follow-up, so
  elicitation becomes the work instead of preceding it.
- **The turn that fragments** — one proposal per message. Same total questions,
  worse experience, and it violates the stop-less norm for real.

If you find yourself composing a second turn, the correct move is to write the
open rows into the brief and start scaffolding.

## Step 3 — write the brief

**What must come first is the deciding, not the file.** Steps 1 and 2 touch no
files: you sweep, you propose, and you read the reaction. Only then does anything
get scaffolded, and the tempo / meter / section values that go to `/song-new`
are the ones this stage resolved.

**Order, and why it is this way round.** `scaffold_song` **refuses** to write
into an existing `songs/<slug>/`
([`src/hallucinote/tools/scaffold_song.py`](../../src/hallucinote/tools/scaffold_song.py)),
so the brief cannot be filed before the scaffold exists — it would block the
scaffold it is meant to feed. Draft the brief **in the turn**, hand its values to
`/song-new`, then write the drafted text to
`songs/<slug>/annotations/01-the-brief.md` as the closing act of this stage.

**Do not invoke `/song-new` from inside this stage.** Hand back the resolved
values and let the lifecycle advance. Running the scaffold here is how the
required-CLI-argument trap this stage exists to remove creeps back in — and at
Step 2 the slug may not even be settled yet (propose it with everything else).

For an **existing** song the dir is already there, so write the file directly.

```markdown
---
kind: annotation
scope: song
date: <YYYY-MM-DD>
tags: [intent, origin, brief]
---

# The brief

## The prompt, verbatim

> <the user's starting prompt, unedited — typos, thinking-aloud and all>

## What is decided

| Dimension | State | Value / mechanism | Decided by |
|---|---|---|---|
| Tempo | DECIDED | 132 BPM | agreed-after-confirm |
| Harmony | DECIDED | D aeolian → D major at the chorus | agreed-after-confirm |
| Drum style | DECIDED | expressive rock kit; timpani across the brass | user |
| Alternate tuning | NOT-APPLICABLE | — | inferred |
| Outro octave drop | DECIDED | master Shifter, `Pitch Coarse` 0 → −12, pre-limiter | inferred |

## Still open

| Dimension | Owner | Closes at |
|---|---|---|
| ... | ... | ... |

## Section time budget

<the arithmetic, if a duration was stated>
```

Rules for the file:

- **Verbatim prompt, unedited.** A cleaned-up version misrepresents what
  happened, and provenance is the point.
- **NOT-APPLICABLE rows are recorded, not omitted.** That is what lets a later
  stage tell *"we considered this and it doesn't apply"* from *"nobody looked."*
- **Every "Still open" row names an owner and the stage that closes it.** A row
  with no owner is the defect this skill exists to prevent.
- **No row may be DESCRIBED-BUT-UNBUILT** — never write a mechanism as settled
  prose unless it exists (or is listed under *Still open*).

Then file the substantive resolutions as `decisions/NN-*.md` per
`docs/song-authoring-conventions.md` → *Rationale is authorship*. The brief
records the **state**; a decision record carries the **why**.

## Meter — ask what it IS, never how to fake it

The song's meter is a property of the authored work. Live's ability to represent
it is a **projection** concern and is not the user's problem.

- **Do** ask the real musical question: *"full 7-rhythm, or 4-then-3?"* — it
  changes the groove and it has a real answer.
- **Do not** ask the user to accommodate a downstream constraint, and **never**
  offer *"we'll represent it as a global 1/4"* as though it were a creative
  option. It isn't; it's a rendering detail.

**Known engine limitation, disclose it to yourself and not to the user as a
choice:** `M.add_time_signature_point` today refuses any `start_bar > 1.0`
(Live 12.4's MCP has no `song_signature` automation target), so a within-song
meter change cannot currently be recorded in the DB. Write the true meter map
into the brief anyway and mark the row open with **the engine** as its owner. The
brief is the requirement; the code is what has to move.

## Existing songs

Run against a slug instead of a prompt to sweep a song that already exists:
read `annotations/`, `decisions/` and `build.py`, and report which dimensions are
UNDECIDED or DESCRIBED-BUT-UNBUILT. `/song-context` and `/song-attempts` recall
prior intent and prior tries — read them first so you never re-propose a settled
choice or a dead end.

## Exit criteria — this stage is done when

- `annotations/01-the-brief.md` exists, carrying the prompt verbatim.
- Every **applicable** dimension is DECIDED, or UNDECIDED with a named owner and
  a closing stage. NOT-APPLICABLE rows are recorded and were never asked about.
- The section time budget is costed, **if** a duration was stated.
- Every gesture the prompt names has a mechanism, or an open row.
- No row is DESCRIBED-BUT-UNBUILT.

## Next: scaffold

`/song-new <slug> "<title>" <tempo> <meter> <sections>` — with **the brief's
values**, not invented ones. The full lifecycle is `/song-workflow`.
