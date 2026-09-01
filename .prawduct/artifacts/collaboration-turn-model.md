# Collaboration turn model — reading the turn, building to the hearable unit

**Status:** **built — awaiting the operator session** (2026-09-01). All six
chunks are built and committed (chunk 06 ticks on its cumulative review); what no prose plan can prove is whether a
*cold* agent actually holds the conversation to the user's hand-off, and the
operator session queued in
[`operator-verification.md`](../operator-verification.md) is the acceptance test
for that. Owner questions were resolved at discovery
(see *Resolved by the owner*). Direction: re-weight the behavioral norms so the
user leads the creative project; no "modes"; the hearable-unit bound is a hard
rule on *offering* a hearing, never on requiring one; evals deferred to the
external eval framework, with the evidence corpus seeded now. **Build plan:**
[`plans/COLLAB-TURN/build-plan.md`](plans/COLLAB-TURN/build-plan.md).

**Read with:** `onboarding-and-teaching-model.md` (the stance this makes
operational — third register, read the request not the requester, collaborate
by default), `intent-collaboration-model.md` (propose-and-react, learn-back),
`elicitation-and-stage-exit-criteria.md` (the one-turn brief this supersedes in
part), and the evidence in
[`collaboration-corpus/`](collaboration-corpus/README.md).

---

## The problem, in the owner's words

> my one complaint is it does a poor balance of assisting the user versus taking
> over and building too much before discussing. […] it should NOT just take off
> and run with that prompt. […] it should explore what aspects of Swift's
> writing and production the user wants, where they're opinionated, where they
> want collaboration, where they just want an assistant to go. […] it's better
> to err on the side of asking the user, but never in way that feels like an
> inquisition or which makes the user feel dumb.

And, three weeks earlier, the same complaint the first time (CTM-07):

> the last thing a creative person wants is to have all the choices taken away.
> I would be very disappointed if I shared that initial prompt and you just ran
> off and built the whole thing.

The stance is already written down — the onboarding model's "never
assume-and-go", the third register, the vision's "you keep the deciding vote".
The behavior does not follow it. This document is about why, and what changes.

## Why the last fix did not hold

The first complaint produced a rewrite of the opening turn. The next take had
the best opening turn in the corpus (CTM-19) — and then declared *"That's
identity resolved. Scaffolding now"* while the user's answers were still
arriving (CTM-09). The problem moved one exchange later. That is the signature
of a structural cause, not a wording one. Five mechanisms, each with a case:

1. **Two complaints were collapsed onto one dial.** The June complaint was
   procedural stops (*"scaffold done, what next?"*, CTM-12). It became the
   loudest norms in the repo: stop only on high-stakes decisions; the burden of
   proof for stopping is high; skill boundaries are not checkpoints. The
   collaborative stance was written as a carve-out to those rules. Under
   pressure the agent obeys the hard rule and treats the carve-out as optional.
   The agent named the inversion itself: it *"asked permission for craft and
   took authorship of identity."*
2. **The one-turn brief solved correctness, not ownership.** It exists so no
   gap travels downstream dressed as a decision (the phantom Shifter), and it
   was bounded to one turn partly to be watchable on camera. It says nothing
   about who owns which choice, and it tells the agent that after the turn
   *"the stage closes"* and it may not ask again. What follows is a 186- or
   333-tool-call build (CTM-10).
3. **The collaborative register fires on the wrong prompts.** The skill works
   by parsing ambiguities out of a spec. On a directive prompt that works
   (CTM-16). On an open, hedged prompt there is no spec to parse, so the agent
   writes one and reports it (CTM-01). The register switches on exactly where
   the user's uncertainty is lowest.
4. **The user is starved of audio, and audio is where their best direction
   comes from.** *"Shouldn't I be hearing something?"* forty-five minutes in,
   with zero notes (CTM-11); a whole song built in one pass and deleted unheard
   (CTM-10). Once audio flowed, the user's steering became dense and precise
   within minutes. The design already says intent is discovered
   retrospectively; the workflow front-loads every decision and renders last.
5. **The delegation axis does not exist in the model.** The brief tracks
   dimensions and their state, not who owns them. Worse, two documents
   disagree about references: the checklist treats *"like X"* as a compressor
   (*"collapses 5 other answers into one"*) and the third register treats it
   as an opener. The compressor reading is the one that produces "run off and
   build".

Two amplifiers: structured pickers were offered four times on creative
questions and never once answered by picking (CTM-05, 08, 14); and the creative
turn arrived wrapped in governance advisories and status footers (CTM-13),
which tell the user they are talking to an engineering agent — the same prior
the host CLI already carries.

---

## The model

Three things a good collaborator does, each with its own lever.

### 1. Read the turn, not the session

No modes. The owner writes music two ways — a broad sketch of a whole song, or
a deep exploration of one idea — and is rightly sceptical that everyone does,
or that software should branch on it. What varies along that axis is the
**hearable unit**: the smallest thing that, once heard, tells the user whether
the idea works. In a deep exploration it is one idea (a negative glissade over
sixteen bars). In a sketch it might be eight bars of chorus with drums, bass
and harmony — nowhere near the whole song. The unit shifts within a session
(Tapestry shrank to `rug`; the demo song grew a ninety-second intro). The agent
does not need to know which "mode" it is in. It needs to answer, every turn:
*what is the smallest thing this person is trying to hear next?* — and build no
further than that before they hear it.

The second read is **what kind of turn this is**. Six kinds recur in the
corpus, and nearly every failure is a misread here:

| Kind | Sounds like | Authorizes |
|---|---|---|
| **directing** | "16 bars, every note in Cmaj, negative glissade up" | execute |
| **reacting** | "measure 34 is abrupt" | adjust what they heard; re-hear |
| **exploring** | "out of curiosity…", "I honestly don't know" | think with them; **touch nothing** |
| **asking** | "where does the triad mute start and end?" | answer; nothing else |
| **delegating** | "use your judgment", "you pick" | decide this item, silently |
| **handing-off** | "let's hear it", "new live set", "go" | build the hearable unit |

Only **directing** and **handing-off** authorize building. The Tapestry
rebuilds were exploring turns read as directing (CTM-02); *"DO NOT do it, just
thinking"* (CTM-03) is the user doing this classification for the agent.

### 2. Know when they are done — and make being wrong cheap

The agent cannot know when the user is done. Neither can a person. What a good
collaborator does is read the signals, then arrange things so a misread costs
little. Both halves are load-bearing; the second is the one nobody has built.

**The signals** are pragmatic, not musical (full list with citations in the
corpus README):

- An answer that *adds a noun* is not a closure. A reply that only selects
  among what was offered closes the item; one that brings a new dimension means
  the user has more (CTM-09).
- A reply that opens a dimension you did not ask about means *keep listening*.
- A message arriving while you are working means the hand-off was misjudged.
  Queued mid-turn messages are the mechanical form of this.
- Hedges downgrade a turn to exploring.
- Silence on an item you asked about is "still thinking", not "agreed", unless
  the user has handed off. Identity never closes by inference.

**Making wrongness cheap** is structural: if the agent only ever builds one
hearable unit before the user reacts, misjudging "done" costs one short unit,
not a song deleted unheard. Better reading without this bound just moves the
cliff. The two are one design, not two options.

### 3. The status offer

The move the owner described:

> "hey, we've got a pretty good idea of harmony, want to hear that in a short
> arrangement, or keep going? We haven't discussed instrumentation…"

It works because of three properties, named so they can be taught:

- **It names what is settled**, so it can be corrected in a word.
- **It offers hearing as an option, not a default.** "Keep going" is a real,
  zero-cost answer.
- **It names the untouched without asking about it.** Naming is an invitation;
  asking is a demand. Someone who does not care about instrumentation says
  "you pick" and it is delegated. Someone who does now has a door. Nobody is
  quizzed.

**When it fires:** when the settled material has reached a hearable unit *and*
the user's last turn was a closure rather than an opening. If the last turn
opened something, the agent follows the opening. If nothing is hearable yet,
the agent proposes one concrete thing toward it. The status offer is not a
stage; it is what the agent says when it has nothing to follow and something to
play.

**The bound is on the offer, not on the listening.** The hard rule is: *never
author past one hearable unit without having offered a hearing.* It is never:
*the user must listen to continue.* Insisting that someone listen (or pretend
to) in order to proceed is bad UX and is the inquisition in another costume.
"Keep going" is a complete answer and authorizes the next unit, after which the
offer is made again — **unless the decline carried a scope**. *"Build the whole
thing, I'll listen at the end"* delegates the hearing rhythm; the agent records
it in the brief's owner column and stops offering until that scope is reached.
An offer repeated after it was declined with scope is nagging, and nagging is
how a good rule gets routed around.

### 4. The brief becomes a ledger with an owner column

Today a dimension is DECIDED, UNDECIDED or NOT-APPLICABLE. Add **who owns it**:
*yours* / *offer me options* / *mine*. The delegation map falls out of the
conversation rather than being asked for: "you pick" writes *mine*; an
opinionated correction writes *yours*; "hmm, what would you do?" writes
*options*. The brief is updated every turn, not written once and obeyed. This
also resolves the "never ask the user to pick a mode" tension: the agent never
offers to take the work away, but it may — humanely — ask where the user wants
their hands on it, and it records what it learns.

### 5. Loaded prompts open the domain

A **loaded prompt** is a few words that carry many implications: a genre, a
form, an era, an artist, a term of art. *"Write a symphony"* implies movements,
a duration in the tens of minutes, orchestration, key relationships, thematic
development. *"Make a rap song"* implies a beat and a tempo range, a flow the
agent cannot voice (a gap to invert, not to hide), lyrical content, sampled
versus synthesized production, an era and a region. *"An atmospheric ambient
piece"* implies texture over pulse, drift, timbre as the subject, a long
duration, harmonic stasis or slow motion. *"Sounds like Taylor Swift"* implies
an era, a writing stance, a production world. The words are short; the song
they imply is not.

This is the third register in its general form, and the reference artist is
one rare instance of it — not a special case to over-index on. The move is the
same for all of them:

1. **Unpack the word.** Name, briefly, what it implies for this song.
2. **State which implications you are taking as read**, so they are
   correctable in a word.
3. **Ask about the two or three where the user's answer would change the song
   most.** Not the whole list. Not a form.

For the symphony: *"I'm hearing four movements, twenty-five to forty minutes,
a full orchestra. The two things that shape everything else: is there a
programme — a story it tells — or is it absolute music? And is the harmonic
language Romantic, or later?"* For the ambient piece: *"Texture over pulse,
long, slow harmonic drift — say if any of that is wrong. The one thing I can't
guess: is it a place, or a state of mind? That decides whether it's field
recordings and space, or pads and breath."*

Then read the answer, propose one concrete thing, get it into Live, and offer a
hearing. The delegation ask, phrased so nobody feels dumb: *"Tell me where you
want your hands on this and I'll bring you options there. The rest I'll just
make, and you can redirect anything."*

---

## Constraints

- **All of this is behavior in prose.** No hook or lint can enforce a
  conversational register. Verification is a scenario brief plus a rubric
  judged over a floating transcript — the eval framework being built outside
  this repo. The corpus is seeded now so it has something to run against.
- **The runtime agent has less context than the design conversation.**
  Whatever we write must work cold, from `CLAUDE.md` plus one skill. Norm
  precedence has to be right in `CLAUDE.md`, because it is the only surface
  loaded every session.
- **The opposite failure is real** (CTM-12). Raising stop frequency across the
  board brings the June complaint back. The distinction is *kind* of stop, not
  frequency.
- **The host is turn-based and a long build is deaf.** Sixty of sixty-nine of
  the user's messages in one session were typed mid-turn. The real dial is how
  much gets built between moments the user can hear and react.
- **Cost cuts the other way from intuition.** A few short turns are cheap next
  to a build that is thrown away.

---

## Decisions taken (owner, 2026-09-01)

- **Re-weight the norms.** "The user leads the creative project" becomes the
  primary norm; stop-less is scoped to procedural stops.
- **No modes.** Sketch-vs-exploration is a continuous read of the hearable
  unit, made every turn.
- **Evals live elsewhere.** No eval harness is built here. The corpus under
  `collaboration-corpus/` is the evidence base it will consume.

## The norms — APPLIED 2026-09-01. The live text is `CLAUDE.md`.

Both this section and *What changes* were drafts, and both are now built. The
draft norm text that stood here has been **deleted rather than kept**: the
shipped version in `CLAUDE.md` gained the precedence guards, the picker rule and
the no-decision-record-while-their-messages-are-arriving clause, so a copy left
here would be a second, weaker set of norms in the file every skill points at as
the place the vocabulary is defined — and this artifact is exempt from the drift
lock, so nothing would catch it diverging further.

**To read the norms, read [`CLAUDE.md`](../../CLAUDE.md) → *Hallucinote
Behavioral Norms*. To amend them, amend them there.** What this artifact still
owns, and what the norms cite it for, is everything above: the diagnosis, the
five structural causes, the model, and the evidence corpus behind each rule.

The surfaces that changed, all shipped: `CLAUDE.md`, `skills/song-brief`,
`skills/song-new`, `skills/getting-started`, `skills/song-workflow`,
`docs/song-workflow.md`, `docs/song-new-checklist.md`, `README.md`,
`docs/quickstart.md`, `docs/skills.md`, and both MCP text surfaces. The build
plan is [`plans/COLLAB-TURN/build-plan.md`](plans/COLLAB-TURN/build-plan.md);
the change-log entry carries `scope=collab-turn`.


## Resolved by the owner (2026-09-01)

1. **The hearable-unit bound is a hard rule — on the offer.** Never author past
   one unit without having *offered* a hearing. Never require the user to
   listen to continue: insisting on a listen (or a pretend one) is bad UX. A
   decline with scope is remembered.
2. **Song work stays in songs workspaces.** When song work starts inside a
   governed repo, warn: governance framing may conflict with the creative
   conversation.
3. **Hearing rhythm is per hearable unit, offered not required.** Same rule as
   (1); the status offer is the vehicle.
4. **Do not over-index on the reference artist.** It is one rare instance of
   the general case — an underspecified prompt that nevertheless carries many
   implications (*"write a symphony"*, *"make a rap song"*, *"an atmospheric
   ambient piece"*). The rule is written for the general case; see *Loaded
   prompts open the domain*.

## Deliberately not built

- No eval, no judge, no scenario runner — external.
- No schema for turn kinds or the owner column — prose in the brief, per the
  standing preference for LLM judgment over deterministic structure.
- No lint. Aesthetic and conversational judgement never fails a build.
