# Collaboration corpus — how the agent reads a creative turn, with receipts

**Status:** seed corpus, started 2026-09-01. Evidence base for
[`collaboration-turn-model.md`](../collaboration-turn-model.md) and the raw
material for a future behavioral eval. **This is not an eval.** The eval
framework is being built elsewhere and will be pulled in when it is ready; the
job here is to make sure that when it arrives there is a corpus of real
episodes, each annotated the same way, for it to run against.

## What a case is

One episode from a real session where the agent had to read a user's turn and
decide what to do. Each case records the turn verbatim, what the agent did, what
the user said next (verbatim — that is the ground truth for what the turn
meant), the *tell* that was available at the time, the move that would have
been right, and one assertion a judge could check over a floating transcript.

Positive cases are kept alongside negative ones. A rubric that only knows
failures over-corrects; the corpus has to show the shape that worked, too.

## Provenance

Sources are the local Claude Code session logs under
`~/.claude/projects/-Users-brookstalley-source-hallucinote*/`. They are **not**
committed. Each case names its source by session id prefix and UTC timestamp so
the excerpt can be re-read in place. User quotes are the repository owner's own
words, reproduced verbatim including typos, because provenance is the point.

Two record types carry the user's voice in those logs and both matter:

- `type: "user"` — sent while the agent was idle.
- `type: "queue-operation"` / `operation: "enqueue"` — typed **while the agent
  was mid-turn**. In one demo session 60 of 69 user messages were queued. A
  queued message is itself a signal (see below), so cases mark it `[Q]`.

## Frontmatter schema

```yaml
id: CTM-NN                 # stable; never renumber
source: <session-id-prefix>  # first 8 chars of the JSONL filename
repo: hallucinote | hallucinote-songs
at: YYYY-MM-DDTHH:MM        # UTC, the user turn the case is about
episode: <slug>             # which song / study
polarity: negative | positive | mixed
turn_kind: directing | reacting | exploring | asking | delegating | handing-off
agent_read_as: <same vocabulary>   # what the agent behaved as if it were
hearable_unit: <one line>   # the smallest thing the user was trying to hear next
failure: <slug or none>     # from the failure vocabulary below
queued: true | false        # was the user's next message typed mid-turn
```

### Turn kinds

| Kind | What it sounds like | What it authorizes |
|---|---|---|
| **directing** | "16 bars, every note in Cmaj, negative glissade up" | execute |
| **reacting** | "measure 34 is abrupt", "the guitar is totally gone" | adjust what they heard, re-hear |
| **exploring** | "out of curiosity…", "I honestly don't know", "just thinking" | think with them; **no mutation** |
| **asking** | "where does the triad mute start and end?" | answer; nothing else |
| **delegating** | "use your judgment", "you pick" | decide, silently, this item |
| **handing-off** | "let's hear it", "new live set", "go" | build the hearable unit |

Only **directing** and **handing-off** authorize a build.

### Failure vocabulary

| Slug | Meaning |
|---|---|
| `silent-build` | built on a turn that did not authorize building |
| `early-identity-close` | declared the identity settled while the user was still adding to it |
| `spec-sheet-elicitation` | proposals arrived as an argued list; silence treated as consent |
| `menu-over-listening` | offered a picker where the user had an idea or a nuance |
| `unilateral-time` | committed the user's next N minutes without saying so first |
| `hearing-starvation` | long build with nothing audible handed over |
| `invented-mechanism` | stated a method as done on a dimension the user had not addressed |
| `governance-in-creative-turn` | advisories / status footers inside the musical conversation |
| `procedural-stop` | stopped to summarize-and-ask with no decision on the table (the *opposite* failure; kept so the rubric stays two-sided) |
| `stale-context-carry` | reused a prior session's answers when the user asked for a fresh conversation |

## The tells (what was available at the time)

Pragmatic, not musical. Each is cited by at least one case.

1. **An answer that adds a noun is not a closure.** A reply that only selects
   among what was offered closes the item; a reply that brings a new dimension
   means the user has more. (CTM-09)
2. **A reply opening a dimension you did not ask about means keep listening.**
   (CTM-09, CTM-02)
3. **A message arriving mid-turn means the hand-off was misjudged.** Queued
   messages are the mechanical form of this. (CTM-09, CTM-04)
4. **Hedges downgrade the turn to exploring.** "out of curiosity", "just
   thinking", "I'm not sure", "may sound like crap", "I honestly don't know".
   (CTM-02, CTM-03)
5. **Silence on an asked item is "still thinking", not "agreed"**, unless the
   user has handed off. (CTM-09, CTM-07)
6. **"A different idea" means they have one.** Ask what it is before offering
   yours. (CTM-05)
7. **A directive with a stated ambiguity wants a one-sentence reading, not a
   question and not a silent choice.** (CTM-16, CTM-06)
8. **A listening report is a reacting turn.** Interpret, then propose; do not
   start building the follow-up. (CTM-17, CTM-20)

## How a future eval would consume this

- **Judged assertions** — each case ends with one; an LLM-as-judge or a human
  scores a floating transcript against it. Never string-matched.
- **Mechanical metrics** the logs already support: tool calls before the first
  audio handed to the user; user messages queued during a build; brief rows
  labelled `agreed-after-confirm` with no intervening user turn; mutating tool
  calls on a turn later classified `exploring`.
- **Scenario briefs** (persona + goal + response character + rubric), per
  `onboarding-and-teaching-model.md` → *Verifying behavioral design*, are the
  run-instructions side. This corpus supplies the rubric side and the
  calibration examples.

## Adding a case

Copy any case file, keep the schema, quote verbatim, cite the source and time,
and write one judgeable assertion. Do not paraphrase the user's sentiment into
something stronger than what they said. If a case is positive, say what made it
work — that is as load-bearing as the failures.
