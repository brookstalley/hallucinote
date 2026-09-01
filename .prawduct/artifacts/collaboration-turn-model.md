# Collaboration turn model — reading the turn, building to the hearable unit

**Status:** discovery, 2026-09-01. Owner-agreed direction: re-weight the
behavioral norms so the user leads the creative project; no "modes"; evals
deferred to the external eval framework, with the evidence corpus seeded now.
Open questions at the end await ratification before this becomes a build plan.

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

### 4. The brief becomes a ledger with an owner column

Today a dimension is DECIDED, UNDECIDED or NOT-APPLICABLE. Add **who owns it**:
*yours* / *offer me options* / *mine*. The delegation map falls out of the
conversation rather than being asked for: "you pick" writes *mine*; an
opinionated correction writes *yours*; "hmm, what would you do?" writes
*options*. The brief is updated every turn, not written once and obeyed. This
also resolves the "never ask the user to pick a mode" tension: the agent never
offers to take the work away, but it may — humanely — ask where the user wants
their hands on it, and it records what it learns.

### 5. References open the domain

*"Sounds like Taylor Swift"* is the third register, always. The target shape,
not a form:

> Swift covers a lot of ground — the lyric-first confessional storytelling of
> *Folklore*, the maximal synth-pop of *1989*, the country-pop of the early
> records. Which is in your ear? And are you bringing the words and melody, or
> is this about production and arrangement?

Then read the answer, propose one concrete thing, get it into Live, and ask
what they hear. The delegation ask, phrased so nobody feels dumb: *"Tell me
where you want your hands on this and I'll bring you options there. The rest
I'll just make, and you can redirect anything."*

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

## Proposed norm text (draft — not applied)

Replaces the one-turn bound in `CLAUDE.md` → *Hallucinote Behavioral Norms*;
the stop-less rule keeps its text with its scope narrowed to procedural stops.

> **Read the turn before acting.** Every user turn is one of: directing,
> reacting, exploring, asking, delegating, handing off. Only *directing* and
> *handing off* authorize building. Musing is not a request — when the user is
> thinking out loud, think with them and touch nothing.
>
> **Build to the hearable unit and no further.** The hearable unit is the
> smallest thing that, once heard, tells the user whether the idea works — one
> idea in a study, a few bars of one section in a sketch. Get it into Live, hand
> over audio, ask what they hear. A hand-off authorizes the next unit, not the
> record.
>
> **Identity closes when the user hands off, never by inference.** An answer
> that adds a new dimension means they have more. Silence on something you
> asked means still thinking.
>
> **When you have nothing to follow and something to play, make the status
> offer:** what is settled, hear it or keep going, and what has not come up —
> named, not asked.
>
> **Own what they delegated; offer options where they asked; execute where they
> directed.** Record which is which in the brief as you learn it.

## What changes (proposed)

- `CLAUDE.md` — the norm text above; stop-less rescoped; the "one consolidated
  turn" bullet retired.
- `skills/song-brief/SKILL.md` — from one turn to a conversation that ends at
  the user's hand-off; the owner column; the reference-artist rule; the status
  offer as the standard closing move. The three-state model and the
  no-unresolved-gap rule stay — they were right.
- `docs/song-new-checklist.md` §11 — references *open* the domain; delete the
  "collapses 5 answers" framing.
- `docs/song-workflow.md` + `skills/song-workflow/SKILL.md` — a hearing step
  after the first hearable unit, before the rest is composed.
- `skills/song-new/SKILL.md` — the deliverable-shape read stays; "drive
  end-to-end" is rewritten as "drive to the next hearable unit".
- Pickers — `AskUserQuestion` is for enumerable engineering decisions only;
  creative character is elicited in prose.
- Governance framing — advisories and the standing block are for engineering
  turns; a song conversation opens with the music (see open question 2).

## Open questions (owner)

1. **Hard rule or strong guidance for the hearable-unit bound?** Recommendation:
   hard rule — *never author past one hearable unit before a hearing* — because
   guidance is what decayed.
2. **Song work inside governed repos.** The demo sessions ran in the framework
   repo, which is why advisories and status footers landed inside creative
   turns; the songs-repo session had none. Options: keep song work in songs
   workspaces by rule, or tell the agent plainly that the standing block is for
   engineering turns. Recommendation: both.
3. **Hearing rhythm.** Per part, or per section? Recommendation: per hearable
   unit as the agent reads it, with the status offer as the correction if it
   reads too small.
4. **The reference-artist case.** Always open the domain, or only when the
   reference is doing most of the work? Recommendation: always; the cost is one
   short question and the failure mode is the whole complaint.

## Deliberately not built

- No eval, no judge, no scenario runner — external.
- No schema for turn kinds or the owner column — prose in the brief, per the
  standing preference for LLM judgment over deterministic structure.
- No lint. Aesthetic and conversational judgement never fails a build.
