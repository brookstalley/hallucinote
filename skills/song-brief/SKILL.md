---
name: song-brief
description: >-
  Turn a starting prompt into the song's brief through a conversation that ends at the user's hand-off — the elicitation stage that runs BEFORE /song-new. Sweeps the load-bearing dimensions (harmony, tempo, production stance, named narrative turns, meter, the section time budget, and the mechanism behind every named gesture), marks each DECIDED / UNDECIDED / NOT-APPLICABLE, and opens with the two or three identity questions it cannot guess while showing the craft it decided — proposals in prose, never a questionnaire, never a picker. Reads each reply before acting (an answer that adds a noun is not a closure), records who owns each choice (yours / offer me options / mine), and closes with the status offer. Writes `annotations/01-the-brief.md` as a ledger updated every turn — the song's origin record and the input to /song-new. Use whenever a song starts from a prompt rather than from explicit scaffold arguments, or when asked "what do you need to know?" / "what's underspecified here?".
argument-hint: "<the user's starting prompt, or a slug for an existing song>"
user-invocable: true
disable-model-invocation: false
allowed-tools: Read, Write, Glob, Grep, Bash, Skill(song-context), Skill(song-attempts)
---

# /song-brief — the conversation that becomes the brief

$ARGUMENTS

You turn a **starting prompt** into the song's **brief**: the origin record that
every later stage reads, and the artifact that proves no load-bearing question
was passed downstream dressed as a decision — and that no choice the user wanted
to make was made for them.

This is stage **0** of `/song-workflow`, and it runs **before** `/song-new` — not
inside it. `/song-new`'s scaffold command requires tempo, meter and the section
list as arguments, which are exactly the values this stage produces. Running it
first is what stops those values from being invented at a command line.

Design + rationale, two artifacts: the three-state model and the
no-unresolved-gap rule are
[`.prawduct/artifacts/elicitation-and-stage-exit-criteria.md`](../../.prawduct/artifacts/elicitation-and-stage-exit-criteria.md);
the conversation — turn kinds, the hearable unit, the status offer, decline with
scope, the owner column, loaded prompts — is
[`.prawduct/artifacts/collaboration-turn-model.md`](../../.prawduct/artifacts/collaboration-turn-model.md).
**Those words are defined there and short-defined in [`CLAUDE.md`](../../CLAUDE.md).**
What this file adds is where each one fires in this stage. The evidence behind every
rule below is the corpus at
[`.prawduct/artifacts/collaboration-corpus/`](../../.prawduct/artifacts/collaboration-corpus/README.md),
cited by case id.

## The two rules this stage exists to enforce

> **A stage may not emit an unresolved gap.**

Under-specifying is the user's prerogative. *Closing* the gap is the stage's job
— by deciding it here (propose, and read the reaction) or by marking it
explicitly open. What is forbidden is passing an unresolved gap downstream **in
the clothes of a decision**: a docstring that names a device nobody built, a
brief that names a destination with no route. That is not a gap, it is a lie
with a timestamp, and it is how the v1 demo song shipped an octave drop that did
not exist.

> **Identity closes when the user hands off — never by inference.**

The user leads the creative project. What the song *is* — whether anyone sings,
what the argument is about, whether it is a place or a state of mind — is theirs
until they hand it to you, and a hand-off is a turn they take (*"let's hear it"*,
*"go"*, *"you pick"*), not a silence you interpret. The stage that closed
identity by inference is CTM-09: the best opening turn in the corpus, followed
one exchange later by *"That's identity resolved. Scaffolding now"* while the
user's answers were still arriving — and every identity correction landed
within fifteen minutes, each after the artifact it contradicted was written.

The two rules pull the same way. Precedence, once, so no rule below re-opens
it: **a choice the user already directed is not yours to re-open, and a choice
they left open is not yours to close.** Nothing stated is re-asked; nothing
unstated is declared.

## Step 1 — the relevance sweep (silent)

For each dimension below ask **one** question: *does the song, as described so
far, depend on this?* Assign one of three states. Never two.

- **DECIDED** — the user pinned it, or it follows unambiguously from what they
  pinned. Restate it in the brief so it's correctable; do **not** re-ask it.
- **UNDECIDED** — the song depends on it and nobody has chosen. **This, and only
  this, is a candidate for the conversation.**
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
this is guidance, not a schema. The fuller catalogue this table condenses —
must-haves, should-haves and nice-to-haves, with the gap-closers called out — is
[`docs/song-new-checklist.md`](../../docs/song-new-checklist.md); reach for it
when a prompt leans on something the seven rows above don't cover.

**The sweep sorts by state. It does not decide what you ask.** Of the UNDECIDED
rows, only a few are *identity* — the ones where the user's answer changes what
the song is. The rest are *craft*, and craft you decide and show. Which rows are
which is the first judgement of Step 2.

**Loaded prompts.** When the prompt is a few words that carry many
implications — a genre, a form, an era, an artist, a term of art — the sweep
runs on what those words imply, not on what they say. *"Make a rap song"*
implies a tempo range and a beat before anyone mentions either. The artifact
works the symphony, the rap song and the ambient piece in full; the reference
artist (*"sounds like Taylor Swift"*) is one rare instance of the same rule, not
a special case to over-index on. **A loaded word opens its domain; it does not
answer for it.**

## Step 2 — the conversation

This is a conversation, and it ends when the user hands off. It is not a form,
not a list, and not a turn count.

### What bounds it

This stage used to be bounded to a single turn, and the bound existed for two
real reasons: a stage can *fail to converge* — each answer surfacing a follow-up
until elicitation becomes the work instead of preceding it — and a turn can
*fragment* — one proposal per message, same total questions, worse experience.
Both failures are still failures. What bounds them now is not a count of turns
but two things from the model:

- **The hearable unit** bounds *what you ask*. Every turn, ask yourself what is
  the smallest thing this person is trying to hear next, and raise only what
  decides *that*. A verse's argument does not need the outro's octave drop
  settled; it needs to know whether anyone is singing. Rows the unit does not
  depend on go to the ledger as open, with an owner and a closing stage, and
  are not raised — they will be raised by the stage that owns them, in front of
  something audible.
- **The status offer** bounds *when you stop asking*. When you have nothing to
  follow — the user's last reply closed what you asked and opened nothing — and
  enough is settled to build a unit, you make the offer (Step 4). You do not
  compose another round to chase rows they didn't address. The user's *"keep
  going"* or *"let's hear it"* is what ends the stage; your row count never is.

**The shape of every turn, not just the first.** One message per exchange,
carrying everything the current hearable unit depends on — the questions it
turns on, the craft you decided toward it, the reads you want redirected. Not
one question per message: the hearable unit narrows *which* rows you raise, it
never licenses raising them one at a time. And every turn passes the same test
as the opening one: it fits in a breath. A wall is the other failure (CTM-07:
822 words, eight argued items, no open question, closing with *"anything you
don't address, I'll take as agreed"*, and the user's first words were *"let's
pause"*). The shape that worked (CTM-19) asks two or three things, shows the
rest, and is short enough to answer at once.

### The opening turn

Open with the identity questions you cannot guess — **at most two or three** —
and decide and *show* the craft. Both halves matter: the wall and the
questionnaire are each one half without the other.

**What you ask** is what you genuinely cannot infer and the user did not state.
Not the whole UNDECIDED list — the two or three where their answer changes the
song most. On a loaded prompt: unpack the word briefly, state which implications
you are taking as read so they are correctable in a word, and ask the two or
three that matter. The precedence guard applies here as everywhere: **you ask
only about what the user left open**; a choice they directed you execute, and a
choice they said they'd handle themselves you leave alone.

**What you decide** is craft: tempo and its arithmetic, a mechanism for a named
gesture, a production read. Show each in a clause, ending with the offer to
redirect. Cheap-to-reverse choices are shown, not asked; the artifact becomes
the next proposal and is instantly redirectable. Only an expensive fork earns a
question, and only if it is the user's to answer.

**Propose; never interrogate.** Where you do ask, carry your read with the
question — *"which reads instrumental to me, but…"* — so the user is reacting to
something, not filling in a blank. A blank question is auto-accompaniment
wearing a politeness costume: it looks collaborative and transfers zero
expertise. But an identity question carries **no recommendation** — a
recommendation on identity makes disagreeing expensive, which is the wall's
whole mechanism.

**Carry the why in one plain collaborator's sentence** — *"I held the verse back
so the chorus opens up"*, never *"this is a deceptive cadence, which in
theory…"*. Never a classroom; never homework.

**Some items are statements, not questions.** Arithmetic (the time budget) and
mechanism pins (the octave drop = a master Shifter automated pre-limiter) are
things you *tell* the user, ending with "say if you want it different". They
belong in the turn because they are exactly the gaps that go unnoticed when
nobody says them out loud.

**No governance, no status footer.** A song conversation opens with the music.
Advisories and standing blocks belong to engineering turns (CTM-13).

**The exemplar** — the prompt is the 45-second rock-versus-brass song: 4/4
against 3/4 in the verses, a 5/8 industrial bridge, a 7/4 chorus where they
integrate, an outro that bends everything down an octave. The turn that worked
(CTM-19), with its opener reworded and the tempo and budget set to the
elicitation artifact's worked numbers so they match the template below:

> Read formed: the 4-against-3 argument is a structural idea, not decoration,
> and 45 seconds is enough if the chorus gets the room.
>
> Two things only you can tell me.
>
> **Is anyone singing?** You've written the call-and-response *between* two
> instrumental camps, which reads instrumental to me — but "verse/chorus" can
> equally mean a voice both camps are answering, and that decides whether the
> brass argues with the guitar or with a singer.
>
> **Is the argument about time only, or about harmony too?** They could share
> one key and fight over meter alone — or each could insist on its own note, so
> you hear the argument even when only one of them is playing.
>
> Craft, decided — say if you want it different: **132 BPM**, which costs your
> shape at intro 5 s · verse 14 s · bridge 4½ s · chorus 16 s · outro 5 s. The
> octave drop is a Shifter on the master ahead of the limiter, `Pitch Coarse`
> automated 0 → −12 across the last bar, so it catches the reverb tails without
> pushing peaks past the ceiling.
>
> A read — redirect me: when it flips to brass I hear the whole *sound* flip,
> not just the writing — a tight dry room against a big hall — and the chorus is
> where they finally land in one space.
>
> One note, no answer needed: if there is a voice, 7/4 is awkward to sing over.
> I'd keep the sung phrase inside the 4 and let the band carry the 7.

Two questions, no recommendation attached. Two craft decisions shown. One read,
explicitly redirectable. Short enough to answer in a breath.

### Reading the reply

Every reply is a turn, and you read what kind before you do anything. The kinds
and what each authorizes are in the artifact; the reads that matter most here:

- **An answer that adds a noun is not a closure.** A reply that only selects
  among what you offered closes that item. A reply that brings a *new*
  dimension means the user has more — follow it. CTM-09's reply to the harmony
  question was *"rock thinks simple and powerful wins the day… brass thinks
  nuance and modulation can be even more powerful"* — that is not "yes,
  harmony"; it is simplicity-versus-complexity arriving as a new axis, and the
  right reply ends in a question about it, not in *"identity resolved"*.
- **A reply that opens a dimension you did not ask about means keep listening.**
- **Silence on an item you asked is "still thinking", not "agreed"** — unless
  the user has handed off. You do not close it by inference, and you do not
  nag: it stays open in the ledger as *yours* (the user's to decide), and it is
  named — not asked — in the status offer.
- **Hedges downgrade the turn to exploring.** *"May sound like crap"*, *"I
  honestly don't know"*, *"just thinking"* — think with them and touch nothing.
  CTM-01 had three hedges in one prompt and was answered with a finished
  five-section study nobody had discussed.
- **A message arriving while you are working means the hand-off was
  misjudged.** Stop, read it, and re-read the one before it.
- **"A different idea" means they have one.** Ask what it is before offering
  yours (CTM-05).

Then answer what kind of turn it was, against the artifact's table. What is
specific to this stage: a **handing-off** turn ends it, and only directing and
handing-off authorize building anything.

**If you hold prior context on this prompt** — a version of the song from an
earlier session, decisions already in `decisions/` — say so and ask which way to
use it before either reciting it as settled or re-eliciting it (CTM-15:
*"I have a version of this from earlier tonight. For this take, do you want me
to start clean, or pick up where we were?"*). Context is a resource the user
can revoke.

### Pickers are not for creative questions

`AskUserQuestion` is for enumerable engineering choices — a port, a branch, a
device *class* when the user has asked you to enumerate them. Never for
character, identity, or a fork the user might answer with a description. Across
the corpus four pickers were offered on creative questions; none was answered
by picking (CTM-05, 08, 14). The picker in CTM-14 framed *what is the brass,
dramatically?* as a preset choice; the user answered the character question in
prose, corrected a factual claim, and added an idea about the drums that no
option had room for. Prose in, prose out.

### Who owns what

As the conversation runs you learn where the user wants their hands on the song
and where they want you to just make it. Record it in the ledger's **owner
column** as you learn it, never by asking for a delegation map. The three
values are written from where *you* sit: **`mine`** = you decide it;
**`yours`** = the user decides it; **`offer me options`** = bring them choices
and a read. (Only the third is phrased the way a user would say it — it is the
artifact's wording, kept because it is the one that does not make anyone feel
dumb.) So *"you pick"* writes *mine*; an opinionated correction writes *yours*;
*"what would you do?"* writes *offer me options*. You never offer to take the work
away — but you may, humanely, ask where they want their hands on it, and the
artifact's phrasing is the one that does not make anyone feel dumb.

A **decline with scope** is remembered here too. *"Build the whole thing, I'll
listen at the end"* writes the hearing rhythm as *yours* with that scope — they
decided it — and no
later stage re-offers a hearing until the scope is reached. An offer repeated
after it was declined with scope is nagging.

**Silence is a valid pass.** A fully-directed prompt with no applicable open
dimension is a directing turn: show your reads in a clause each, hand back the
brief, and let the lifecycle advance to `/song-new` without waiting for
anything. ("Advance to" is not "invoke": see Step 3.) This stage is not obliged
to find something to ask — and asking on a directed prompt is the precedence
failure in its politest form. **The hedge test gates this pass.** A hedged or
thinking-out-loud opening prompt — *"may sound like crap"*, *"a study to see
how things work"*, *"not a full song"* — is exploring, not directed, and never
qualifies, however complete its spec looks (CTM-01: three hedges, read as a
hand-off, answered with a finished study).

## Step 3 — the brief is a ledger

**What must come first is the deciding, not the file.** Steps 1 and 2 touch no
files: you sweep, you converse, and you read each reaction. Only after the
hand-off does anything get scaffolded, and the tempo / meter / section values
that go to `/song-new` are the ones this stage resolved.

The brief is **updated every turn, not written once and obeyed.** You draft it
in the conversation — each reply moves rows between states and fills the owner
column — and the file on disk is the last draft, not the first. A later stage
that learns something about identity updates it again.

**Order, and why it is this way round.** `scaffold_song` **refuses** to write
into an existing `songs/<slug>/`
([`src/hallucinote/tools/scaffold_song.py`](../../src/hallucinote/tools/scaffold_song.py)),
so the brief cannot be filed before the scaffold exists — it would block the
scaffold it is meant to feed. Draft it **in the conversation**, hand its values
to `/song-new`, then write the drafted text to
`songs/<slug>/annotations/01-the-brief.md` as the closing act of this stage.

**Do not invoke `/song-new` from inside this stage.** Hand back the resolved
values and let the lifecycle advance. Running the scaffold here is how the
required-CLI-argument trap this stage exists to remove creeps back in — and
early in the conversation the slug may not even be settled yet (propose it with
everything else).

For an **existing** song the dir is already there, so write the file directly.

```markdown
---
kind: annotation
scope: song
date: 2026-09-01
tags: [intent, origin, brief]
---

# The brief

## The prompt, verbatim

> <the user's starting prompt, unedited — typos, thinking-aloud and all>

## What is decided

| Dimension | State | Value / mechanism | Owner | Decided by |
|---|---|---|---|---|
| Vocals | DECIDED | instrumental; lead guitar carries the vocal role | yours | user |
| Tempo | DECIDED | 132 BPM | mine | inferred |
| Harmony | DECIDED | D aeolian → D major at the chorus | offer me options | agreed-after-confirm |
| Drum style | DECIDED | expressive rock kit; timpani across the brass | yours | user |
| Alternate tuning | NOT-APPLICABLE | — | — | inferred |
| Outro octave drop | DECIDED | master Shifter, `Pitch Coarse` 0 → −12, pre-limiter | mine | inferred |
| Hearing rhythm | DECIDED | offer after each unit | yours | user |

## Still open

| Dimension | Owner | Closes at |
|---|---|---|
| What "integrated" means in the chorus | yours | /compose-part, in front of the verse argument |
| Brass voice — section patch or layered horns | offer me options | /song-pick-instruments |

## Section time budget

<the arithmetic, if a duration was stated>
```

Rules for the file:

- **Verbatim prompt, unedited.** A cleaned-up version misrepresents what
  happened, and provenance is the point.
- **The owner column is written from where you sit** — `mine` = you decide it,
  `yours` = the user decides it, `offer me options` = bring them choices. A
  row learned from the conversation, never from a form. A NOT-APPLICABLE row
  has no owner.
- **`Decided by` is provenance** — `user`, `inferred`, or
  `agreed-after-confirm`. **`agreed-after-confirm` requires a user turn between
  the proposal and the label** (CTM-01 labelled two rows that way with zero user
  turns in the session). Silence is `inferred` at best, and on identity it is
  not DECIDED at all.
- **NOT-APPLICABLE rows are recorded, not omitted.** That is what lets a later
  stage tell *"we considered this and it doesn't apply"* from *"nobody looked."*
- **Every "Still open" row names an owner and the stage that closes it.** A row
  with no owner is the defect this skill exists to prevent. An identity row the
  user left unanswered at hand-off is open and *yours*, not decided and
  inferred.
- **No row may be DESCRIBED-BUT-UNBUILT** — never write a mechanism as settled
  prose unless it exists (or is listed under *Still open*).
- **`date` is the day the brief was first written**, ISO. The frontmatter is
  the schema owned by
  [`.prawduct/artifacts/song-conventions.md`](../../.prawduct/artifacts/song-conventions.md)
  (four keys used here, all allowed; unknown keys raise at index time), and the
  file is written through `write_markdown_ref` so `/song-context` can find it.

Then file the substantive resolutions as `decisions/NN-*.md` per
`docs/song-authoring-conventions.md` → *Rationale is authorship*. The brief
records the **state**; a decision record carries the **why**. **A decision
record about identity is not written while the user's messages about identity
are still arriving** — CTM-09 wrote four of them inside the window in which the
user overturned three.

## Step 4 — close with the status offer

When you have nothing to follow and enough settled to build the first hearable
unit, make the status offer — the artifact defines it; its three properties are
what make it work:

- **Name what is settled**, so it can be corrected in a word.
- **Offer the hearing as an option, not a default.** At this stage "hear it"
  means *I'll get the first unit into Live so you can hear it* — the verse
  argument, a few bars with both camps audible; not the song. "Keep going" is a
  real, zero-cost answer and authorizes exactly that unit, after which the
  offer is made again — unless the user declined with a scope.
- **Name what has not come up, without asking about it.** Naming is an
  invitation; asking is a demand. Someone who does not care about the brass
  voicing says "you pick" and it is *mine*. Someone who does now has a door.
  Nobody is quizzed — and nothing the user already directed appears in this
  list.

> *"So: instrumental, 132, the argument reaches harmony, two rooms that merge in
> the chorus. Want me to get the verse argument into Live so you can hear the two
> camps trade, or keep talking? We haven't touched what the brass actually is —
> one voice or a section — or what 'integrated' sounds like in the chorus."*

The user's reply is read like any other. *"Let's hear it"* / *"go"* is the
hand-off — the stage ends, and its values go to `/song-new`. An answer that
opens one of the named items is not a hand-off; follow it. A hand-off with
unanswered identity rows still open is allowed — the rows go to *Still open*
as *yours* with the stage that will raise them in front of something audible.

## Meter — ask what it IS, never how to fake it

The song's meter is a property of the authored work. Live's ability to represent
it is a **projection** concern and is not the user's problem.

- **Do** ask the real musical question — *"full 7-rhythm, or 4-then-3?"* — when
  the user has not already answered it. It changes the groove and it has a real
  answer; a meter the user stated is executed, not re-asked.
- **Do not** ask the user to accommodate a downstream constraint, and **never**
  offer *"we'll represent it as a global 1/4"* as though it were a creative
  option. It isn't; it's a rendering detail.

**Record the true meter map.** `M.add_time_signature_point` takes one row per
meter change, at the bar it starts on — a within-song change is ordinary authored
state, so the meter row in the brief resolves DECIDED like any other.

**What is still open, and is yours to know rather than the user's to weigh:**
only the bar-1 row reaches Live (Live 12.4's MCP has no `song_signature`
automation target), so Live's ruler reads one meter for the whole song and push
alerts about the rest. The meter therefore has to be *felt* — bar-scaled
generators and within-bar accent groupings — not read off the grid.

Second, a multi-meter song costs more to author than a single-meter one, which
is worth knowing before you encourage one — but that cost is build-time
mechanics, and it is not the user's to weigh here:
`docs/song-authoring-conventions.md` → *Meter (4/4 vs. other)* carries it.

## Existing songs

Run against a slug instead of a prompt to sweep a song that already exists:
read `annotations/`, `decisions/` and `build.py`, and report which dimensions are
UNDECIDED or DESCRIBED-BUT-UNBUILT — and which rows have no owner. `/song-context`
and `/song-attempts` recall prior intent and prior tries — read them first so
you never re-propose a settled choice or a dead end. If the user has framed a
fresh start, that framing wins over the context: say what you hold and ask
which way to use it.

## Exit criteria — this stage is done when

- The user handed off — a directing or handing-off turn, not a silence or an
  inference.
- `annotations/01-the-brief.md` exists, carrying the prompt verbatim.
- Every **applicable** dimension is DECIDED, or UNDECIDED with a named owner and
  a closing stage. NOT-APPLICABLE rows are recorded and were never asked about.
- Every applicable row carries an owner — `yours`, `offer me options` or `mine`.
- No identity row is DECIDED by inference; no row is `agreed-after-confirm`
  without a user turn behind it.
- The section time budget is costed, **if** a duration was stated.
- Every gesture the prompt names has a mechanism, or an open row.
- No row is DESCRIBED-BUT-UNBUILT.
- The status offer was made and its answer read — **or** the prompt was
  directed with no applicable dimension open, in which case the stage hands
  back and the lifecycle advances without waiting for anything. Waiting on a
  directed prompt is a stop with no decision on the table.

## Next: scaffold

`/song-new <slug> "<title>" <tempo> <meter> <sections>` — with **the brief's
values**, not invented ones. The next thing the user meets is the first
hearable unit and an offer to play it, not the rest of the song. The full
lifecycle is `/song-workflow`.
