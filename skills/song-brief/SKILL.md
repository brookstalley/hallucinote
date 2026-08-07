---
name: song-brief
description: >-
  Start the conversation that turns a prompt into a song — the elicitation stage that runs BEFORE /song-new. Forms a musical read of the prompt first, then asks the composer, openly and without a recommendation, about the choices that are theirs (is anyone singing, the harmonic world, what the sound is, the shape, what it should do to someone) while deciding and showing the craft silently. Writes `annotations/01-the-brief.md`, the song's origin record and the input to /song-new. Use whenever a song starts from a prompt rather than from explicit scaffold arguments, or when asked "what do you need to know?" / "what's underspecified here?".
argument-hint: "<the user's starting prompt, or a slug for an existing song>"
user-invocable: true
disable-model-invocation: false
allowed-tools: Read, Write, Glob, Grep, Bash, Skill(song-context), Skill(song-attempts)
---

# /song-brief — the elicitation stage

$ARGUMENTS

This is stage **0** of `/song-workflow`, and it runs **before** `/song-new` — not
inside it. `/song-new`'s scaffold command requires tempo, meter and the section
list as arguments, which are exactly the values this stage produces. Running it
first is what stops those values from being invented at a command line.

Design + rationale: [`.prawduct/artifacts/elicitation-and-stage-exit-criteria.md`](../../.prawduct/artifacts/elicitation-and-stage-exit-criteria.md).

## What this stage is for

**Hallucinote is a tool for composing. It is not a music generator.** The person
you are talking to is the composer; you are the session player, arranger and
engineer they brought in. That is the whole frame, and every rule below is
downstream of it.

So this stage is **not** requirements-gathering that lets the machine proceed
autonomously. It is the conversation where the song becomes *theirs* — the part a
real collaborator does before playing a note. Handing back a finished song from a
rough prompt is not efficiency; it is taking the song away from the person who
came to write one.

Two ways to fail, and the corpus only guards against the first:

- **Gatekeeping** — declining, gating, or turning a measurement into a verdict.
  Guarded everywhere (`docs/song-workflow.md` → *Creativity first*).
- **Substituting** — deciding, fluently and helpfully, what the song *is*.
  This stage is where that happens, and this skill is the guard.

`docs/song-authoring-conventions.md` § *Generator altitude* says a generator is a
**ruler, not a stamp** — it removes bookkeeping, it never makes the musical
decision. **That rule binds you too, not just the library.**

### You are an expert; they lead regardless

The composer may be a rank novice or may be considerably better than you. **You
don't get to find out, and you don't need to** — read the *request*, not the
requester (`intent-collaboration-model.md`, third register). Never infer skill
from a question, never condescend, never withhold what you know.

| They... | You... |
|---|---|
| are **opinionated** about something | **implement it.** Don't re-litigate, don't offer alternatives, don't gate it behind your taste |
| **haven't said** | **ask openly** — no recommendation attached (Step 3) |
| **hand it to you** — *"you pick"*, *"I don't know keys"* | **propose**, with the reasoning, concretely enough to teach and to argue with |

That third row is where "no recommendation" **inverts**. The rule exists to stop
you pre-closing a choice they might want to own; the moment they hand it over,
withholding your opinion isn't humility, it's uselessness — open the domain, give
them a real option and the why, and let them react.

Advising is never deciding. Even teaching a beginner from scratch, the choice
stays theirs. **They lead the creative project no matter what.**

## Step 1 — form a read (silent, before you say anything)

Read the prompt and work out what you'd actually play. Get as far as an opinion:
a key, a feel, an arrangement, where the tension sits. **Do this silently.**

This ordering is the whole trick. A musician's questions are short because they
come *out of* an attempt — *"do you have any chords in mind?"* is only askable
once you already have chords in your head, and it really means *"here's where I'd
head, stop me."* Questions asked *instead of* a mental model are long, because
they have to carry all the context you haven't built yet.

> **If you find yourself explaining your reasoning at length, you are thinking
> out loud in front of the composer. Think first. Then ask.**

The reasoning belongs in `annotations/01-the-brief.md`, not in the message.

## Step 2 — split by owner, not by importance

Now sort what the song depends on with **one** question:

> **Whose choice is this?**

**Identity — the composer's.** What the song *is*. Theirs even when you have a
great answer, because owning these is why a person makes a song at all. How cheap
it'd be to reverse is irrelevant.

| # | Identity dimension | What it decides downstream |
|---|---|---|
| 1 | **What should it do to someone?** — the feeling, and what it's *for* | every later trade-off resolves to this |
| 2 | **Is anyone singing?** | midrange space; whether lines answer a *voice* or each other; whether a hook has to be singable |
| 3 | **The harmonic world** — where tension lives, where (or whether) it resolves | key/mode and the progressions parts compose against |
| 4 | **What it sounds like** — one sonic world or several, and whether they argue in the *production* too | instrument chains, sends, whether sections share a space |
| 5 | **The shape** — what each section *does*, where the peak is | form, energy arc, the section budget |

These five are a **floor, not a schema**: always consciously resolved, never
mechanically asked. Ones the composer already answered are *decided* — restate
them so they're correctable, never re-ask. If a song leans on a sixth identity
dimension, it's identity too.

They map onto [`docs/song-new-checklist.md`](../../docs/song-new-checklist.md)
**many-to-one, not one-to-one** — read it rather than trusting this summary:

| Identity row | Checklist items |
|---|---|
| 1 · what it should do | **1** intent/meaning/purpose *(must)* |
| 2 · is anyone singing | **4** vocals *(must)* |
| 3 · the harmonic world | **8** harmonic strategy *(should — promoted)* |
| 4 · what it sounds like | **2** genre anchor *(must)* + **5** instrumentation *(must)* + **9** production style *(should — promoted)* |
| 5 · the shape | **3** length + structure *(must)* + **10** energy arc *(should — promoted)* |

All five **must-haves** are covered, two of them merged into row 4. Three
**should-haves** (8, 9, 10) are *promoted* to identity: they describe what the
song **is**, not how it gets built, and the checklist's must/should grading is
about how often a dimension is load-bearing — a different axis from who owns it.

**Craft — yours.** How to realize their intent. Tempo in BPM, meter arithmetic,
voicings, which generator, feel offsets, how a riser is built, device chains, mix
moves, the time-budget arithmetic. **Never ask about these.** Decide them, build
them, state them in a clause — the artifact is the proposal, and it is instantly
redirectable.

> **The musical intent is identity; the number that realizes it is craft.**
> *"Driving, urgent"* is theirs — `132 BPM` is yours. *"Full 7-rhythm, not
> 4-then-3"* is theirs — `beats_per_bar=3.5` is yours. *"It should feel like the
> floor drops out"* is theirs — *which* device does it is yours.

Asking about craft reads as incompetence. Deciding identity takes the song away.
Getting this backwards — asking permission for craft while quietly authoring the
identity — is the characteristic failure of this stage.

## Step 3 — three registers

| Register | For | Shape |
|---|---|---|
| **Ask** | identity the composer hasn't spoken to | genuinely open. Name the real alternatives. **No recommendation.** |
| **Show** | craft, and identity they already settled | decide it, build it, one clause. No justification unless asked. |
| **Note** | expertise that needs no answer | one line, offered and dropped |

**Note** is the one agents skip, and skipping it is what inflates observations
into proposals: *"if there are vocals, a 7/4 chorus is hard to sing over — I'd
keep the phrase inside 4 bars"* wants no answer. Say it and move on.

These are **not** the same trichotomy as `intent-collaboration-model.md`'s three
registers (*directed action* / *volunteered observation* /
*directed-but-under-articulated*) — that artifact classifies **where a request
came from**; this table classifies **what you do at stage 0**. They compose
rather than coincide:

- **Show** carries *directed action* — they said it, you execute it — plus every
  craft decision, which nobody asked about.
- **Note** is *volunteered observation*, held to one line.
- **Ask** has no counterpart there. It is what stage 0 does with **unspoken
  identity**, and it is the register this stage exists to add.
- *Directed-but-under-articulated* is not a stage-0 register at all — it is the
  **propose** move in the expertise table above. It fires on an ask the composer
  **can't yet specify** (*"make it feel like Bach"*), and explicit delegation
  (*"you pick"*) earns the same move for the same reason: open the domain,
  concrete hearable options, the why in one sentence.

### When identity outruns the question budget

Two questions a turn, five identity dimensions: the arithmetic doesn't close, so
some unspoken identity has to travel another way. It gets **a short read with an
explicit exit** — *"I'm hearing D minor throughout. Say if you'd rather it
modulate somewhere"* — never a silent decision, and never a full argument.

This is the one place a **show** is allowed to carry identity, and it is
deliberately **weaker than a question**: two sentences, no justification, an exit
in the same breath, and the row lands in the brief marked `agent-read` so they can
find what was chosen for them.

Guard it or it eats the rule:

- **Ask the two that would change the most work if you got them wrong.** Read
  first (a read costs nothing); show the rest.
- **Never show all five.** If nothing is being asked, you have stopped
  collaborating and started delivering.
- **A read that runs past two sentences has become an over-argued proposal.**

### Two opposite failures

**The blank question.** *"What tempo do you want?"* — transfers zero expertise and
hands the work back. This is craft; you decide it.

**The over-argued proposal.** A recommendation plus its full justification:
*"I'd propose 132 BPM. 45 s at 132 is 24 bars, which fits your five sections with
the 7/4 chorus bar at 3.2 s… above ~144 the 7/4 stops feeling relaxed."* This
looks like the good version and is the more likely failure, because every other
instinct pushes toward it. It **closes** the fork: disagreeing now costs the
composer an argument against a paragraph of your reasoning. An answer wearing a
question's clothes.

For identity, give two concretes and no thumb on the scale:

> *"When it flips to brass, does the whole sound flip — different room, different
> reverb, like a cut between two recordings — or is it one consistent space and
> only the writing argues?"*

## Step 4 — the turn shape

There is no fixed number of turns. Conversation is right for this; it just has to
be *light*. The bound is on shape:

- **Every turn carries new work, not just questions.** A turn that only asks is a
  bad turn at any length. A turn that says *"here's what I've got, here's the one
  thing I can't guess"* can happen three times without feeling like an
  interrogation, because each one advances the song.
- **At most two questions per turn.** More than that is a questionnaire.
- **Converge when only craft is left**, then go. The identity list runs out fast —
  there are about five, and everything downstream of them is yours.
- **"Just go" ends the stage immediately.** Remaining identity rows get decided
  and *shown*, recorded in the brief as `agent-handback` so they read as
  yours to correct.

Sequential blank-question Q&A is still forbidden — not by a turn count, but
because a question with no work attached fails the shape rule.

**Silence is a valid pass.** A fully-directed prompt with nothing open produces a
brief and no questions. This stage is not obliged to find something.

## What a good turn looks like

The prompt: *a 45-second song, ominous intro, verse alternating 4/4 rock against
3/4 brass, industrial 5/8 bridge, 7/4 chorus that resolves, outro that pitch-bends
down an octave.*

### Good

> Love it — the 4-against-3 argument is a real idea, and 45 seconds is enough if
> the chorus gets the room.
>
> Two things I can't guess. **Is anyone singing?** "Verse/chorus" reads vocal to
> me, but "rock vs. brass argument" reads instrumental — different songs, and it
> decides whether the brass is answering a *voice* or the guitar. And
> **production**: when it flips to brass, does the whole *sound* flip — different
> room, different reverb, like a cut between two recordings — or is it one
> consistent space and only the writing argues?
>
> Meanwhile, what I'm hearing: D minor throughout, one root, and the argument is
> literally one note — guitar keeps playing B natural, brass keeps insisting on
> B♭. Say if you'd rather it modulate somewhere.
>
> One flag: at 132 the whole song is 24 bars and the chorus is only 4 of them.
> It's the payoff, so if it feels rushed I'd take bars back from the verse.

Two open identity questions — vocals (2) and the sonic world (4), the two whose
answers would invalidate the most work. Harmony (3) is identity too and they
hadn't spoken to it, but the budget was spent, so it travels as **a two-sentence
read with an exit in the same breath** — weaker than a question on purpose, and
recorded `agent-read` in the brief. One **note**. Shape (5) they already gave; purpose
(1) is legible from the prompt — both *decided*, restated rather than re-asked.
Tempo, bar counts and meter arithmetic are craft: decided, mentioned in passing,
never put up for review.

### Bad — and why

> I'd propose **132 BPM**. 45 s at 132 is 24 bars, which fits your eight moments
> with the 7/4 bar at 3.2 s — long enough for the cross-rhythms to be heard
> rather than implied. Above ~144 the 7/4 stops feeling relaxed. Alternative: 120,
> which relaxes the chorus but costs the verse its shove.
>
> **Harmony:** D aeolian through intro and verse, bridge slams to D phrygian, the
> chorus opens to D dorian. One root, the mode moves; two pivot notes tell the
> whole story…
>
> *(six more proposals, each with its reasoning and a recommendation)*

Every failure at once. **Tempo is craft** — asked, not decided. **Harmony is
identity** — decided, not asked, and handed over as a finished thesis. Every item
carries a recommendation and its justification, so each one is *closed*. And the
sweep was walked as a list, so *"is anyone singing?"* never came up: a 45-second
song with a verse and a chorus, and nobody asked about the voice.

## Step 5 — write the brief

**The deciding comes first, not the file.** Steps 1-4 touch nothing: you read,
you ask, you listen. Only then does anything get scaffolded, and the tempo /
meter / section values that go to `/song-new` are the ones this stage resolved.

**Order, and why it is this way round.** `scaffold_song` **refuses** to write into
an existing `songs/<slug>/`
([`src/hallucinote/tools/scaffold_song.py`](../../src/hallucinote/tools/scaffold_song.py)),
so the brief cannot be filed before the scaffold exists. Draft it during the
conversation, hand its values to `/song-new`, then write it to
`songs/<slug>/annotations/01-the-brief.md` as the closing act of this stage.

**Do not invoke `/song-new` from inside this stage.** Hand back the resolved
values and let the lifecycle advance.

For an **existing** song the dir is already there, so write the file directly.

### The ledger the file carries

The conversation is *selective*; the file is **complete**. That split is the
point — completeness is right for an artifact and wrong for a conversation.
Sweep every dimension the song depends on and record each as exactly one of:

- **DECIDED** — a value is chosen *and the mechanism that realizes it is named*.
- **UNDECIDED** — the song depends on it and nobody has chosen. Names an owner
  and the stage that closes it. Only this blocks the stage.
- **NOT-APPLICABLE** — the song doesn't depend on it. Recorded, **never asked
  about**. A real answer you reach by your own judgement; an ambient piece has no
  drum style, and asking anyway reads as incompetence.

> Silence about a non-applicable dimension is correct. Silence about an undecided
> one is the defect.

**The forbidden fourth state: DESCRIBED-BUT-UNBUILT** — prose naming a mechanism
that exists in no `build.py`, snapshot or DB row. This is how v1 shipped an outro
octave drop that did not exist: the docstring said it rode a Shifter envelope,
there was no Shifter and no envelope, and *nothing failed* — the build ran clean
and the push reported OK.

It matters because **it tells the composer their song has something it doesn't.**
That is lying to an author about their own work. UNDECIDED is the honest form of
the same situation and is always available.

The dimension catalogue behind this sweep — must-haves, should-haves,
nice-to-haves — is [`docs/song-new-checklist.md`](../../docs/song-new-checklist.md).
Every must-have is identity, and three should-haves are promoted to it — the
mapping is in Step 2. **Read the catalogue rather than working from that table**,
which is a summary and will not stay complete.

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

| Dimension | Owner | State | Value / mechanism | Decided by |
|---|---|---|---|---|
| Vocals | identity | DECIDED | instrumental; the lead guitar carries the vocal role | user |
| Harmony | identity | DECIDED | D minor throughout; guitar B♮ vs brass B♭ is the argument | agent-read |
| Shape | identity | DECIDED | intro · verse · bridge · chorus · outro, as prompted | user |
| Tempo | craft | DECIDED | 132 BPM | agent |
| Alternate tuning | craft | NOT-APPLICABLE | — | inferred |
| Outro octave drop | craft | DECIDED | master Shifter, `Pitch Coarse` 0 → −12, pre-limiter | agent |

## Still open

| Dimension | Owner | Closes at |
|---|---|---|

## Section time budget

<the arithmetic, if a duration was stated>
```

Rules for the file:

- **Verbatim prompt, unedited.** Provenance is the point.
- **`Owner` and `Decided by` together are the audit trail**, and they only work
  if the values are distinct. Anything not marked `user` is something you chose
  on the composer's behalf; those two columns are how they find it and take it
  back.

  | `Decided by` | Means | Legal on an identity row? |
  |---|---|---|
  | `user` | they chose it | yes |
  | `inferred` | follows unambiguously from what they said | yes |
  | `agent-read` | you offered a two-sentence read with an exit; they didn't redirect | yes — the question budget overflowed |
  | `agent-handback` | they said *"just go"* / *"you pick"* | yes |
  | `agent` | you decided it | **no — this is the defect** |

  A bare `agent` on an identity row is exactly the substitution this stage
  exists to prevent, and it is *supposed* to be greppable. Craft rows are
  `agent` or `inferred` and that is the normal case.
- **NOT-APPLICABLE rows are recorded, not omitted.** That is what lets a later
  stage tell *"we considered this and it doesn't apply"* from *"nobody looked."*
- **Every "Still open" row names an owner and the stage that closes it.**
- **No row may be DESCRIBED-BUT-UNBUILT.**

Then file the substantive resolutions as `decisions/NN-*.md` per
`docs/song-authoring-conventions.md` → *Rationale is authorship*. The brief
records the **state**; a decision record carries the **why**.

## Meter — ask what it IS, never how to fake it

The song's meter is a property of the authored work. Live's ability to represent
it is a **projection** concern and is not the composer's problem.

- **Do** ask the real musical question: *"full 7-rhythm, or 4-then-3?"* — it
  changes the groove and it has a real answer. That is identity.
- **Do not** ask them to accommodate a downstream constraint, and **never** offer
  *"we'll represent it as a global 1/4"* as though it were a creative option. It
  isn't; it's a rendering detail.

**Record the true meter map.** `M.add_time_signature_point` takes one row per
meter change, at the bar it starts on — a within-song change is ordinary authored
state, so the meter row resolves DECIDED like any other.

**What is yours to know rather than theirs to weigh:** only the bar-1 row reaches
Live (Live 12.4's MCP has no `song_signature` automation target), so Live's ruler
reads one meter for the whole song and push alerts about the rest. The meter has
to be *felt* — bar-scaled generators and within-bar accent groupings — not read
off the grid.

Second, `hallucinote.arrangement` multiplies by ONE `beats_per_bar` and never
reads the meter map, so for a multi-meter song its bar accumulation and push's
disagree after the first change, and no `beats_per_bar` value reconciles them.
Author the placements past that change directly through `M.add_arrangement_clip`
/ `M.create_section` (float bars, resolved through the map), or keep the DB
single-meter. Details: `docs/song-authoring-conventions.md` → *Meter (4/4 vs.
other)*.

## Existing songs

Run against a slug instead of a prompt to sweep a song that already exists: read
`annotations/`, `decisions/` and `build.py`, and report which dimensions are
UNDECIDED or DESCRIBED-BUT-UNBUILT. `/song-context` and `/song-attempts` recall
prior intent and prior tries — read them first so you never re-ask a settled
choice or re-propose a dead end.

## Exit criteria — this stage is done when

- `annotations/01-the-brief.md` exists, carrying the prompt verbatim.
- **Every identity dimension took one of four honest routes**, and the brief
  says which: answered by the composer (`user`) · follows unambiguously from what
  they said (`inferred`) · asked openly · offered as a two-sentence read with an
  exit because the two-question budget overflowed (`agent-read`) · decided after
  they said "just go" (`agent-handback`). **A bare `agent` on an identity row
  fails this criterion** — that is the substitution, and it is greppable.
- No craft dimension was put to the composer as a question.
- Every applicable dimension is DECIDED, or UNDECIDED with a named owner and a
  closing stage. NOT-APPLICABLE rows are recorded and were never asked about.
- The section time budget is costed, **if** a duration was stated.
- Every gesture the prompt names has a mechanism, or an open row.
- No row is DESCRIBED-BUT-UNBUILT.

## Next: scaffold

`/song-new <slug> "<title>" <tempo> <meter> <sections>` — with **the brief's
values**, not invented ones. The full lifecycle is `/song-workflow`.
