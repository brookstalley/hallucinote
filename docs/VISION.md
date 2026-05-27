# Vision

Hallucinote is an LLM-native music composition and production environment. Ableton Live is the rendering engine.

The DB is the source of truth. Notes, durations, chords, automation values, effect timings, arrangement — everything lives in version-controlled rows with an append-only event log. Ableton is the speaker, not the score. Every change is bidirectional: edits in Ableton (live MIDI capture, automation drawn by hand, audio recorded against a click) flow back. The DB and Ableton agree, always.

The LLM has full access via MCP — read every note, write every parameter, generate new sections, restructure arrangements, run bulk operations. That is what makes this different from AI features bolted onto a DAW: the model sees structure, not pixels.

## The bet

Two bets, both unproven, both load-bearing:

1. **Structure unlocks competence.** If the LLM sees the song as semantic objects — tags like `ghost` / `downbeat`, section roles, generator-call provenance, an event log of every change — it can collaborate at the level of musical ideas rather than guessing at MIDI bytes. A diff is not "33 notes changed." It is "raised verse ghost snares +5, swapped the chorus walk for an embellishment, added a fill at bar 12."

2. **Songs should be forkable.** A song is a git repo. Branch a chorus variant, A/B against main, throw it away. Two collaborators on different continents can each run the song against their own Ableton, push and pull edits like code. No binary DAW project, no email attachments. Impossible in every other tool, because everyone else's source of truth is a closed binary.

## Why

- **Move composers up the ladder of abstraction.** "Add a bassline that holds notes between the kicks from drum part A and drum part B." That should work. Today an LLM can describe that idea; with structured access to the song, it can build it.

- **A collaborator that is more than competent.** The target is not "AI fills in a chord progression." The target is: ask for two drum parts at 95 and 100 BPM with a bassline weaving between the kicks of both, and get back something musical. Polyrhythmic, polytempic, sectionally aware — the kind of arrangement that takes a skilled producer hours to lay out by hand.

- **Production tools without the production career.** Bulk operations a normal user cannot reach without scripting: humanize every backbeat by ±2%, sidechain every sustained pad note to the nearest kick, transpose only the notes tagged `bell`. The DB plus MCP makes these one-liners.

- **Big experiments cost almost nothing.** Branching a song is `git checkout -b`. Trying a half-time bridge, a key change, a different drummer feel — reversible, diff-able, reviewable. The fear of breaking something you spent two weeks on goes away.

- **Songs are testable.** Because the song is structured data, you can assert over it. "Bass aligns with kick within 10ms in the verse." "No track is missing pan placement." "Master has a limiter." Quality checks that today take a producer's ear and patient listening become assertions the song carries with it — to verify a change worked, to catch a regression after a fork, to keep the song coherent as it evolves.

- **Reach music Ableton was not built for.** Polytempic pieces encoded by positioning events on a 1/64 grid against one nominal tempo. Microtonal music via Max for Live or per-voice pitch bend. None of this is easy. But the DB representation makes it possible, where the DAW alone makes it actively hostile.

- **Composers anywhere on the spectrum.** Hobbyist with no theory, working producer, thirty-year veteran. Same as an LLM coding agent serving a middle-schooler and a senior engineer: the interface is conversation, the depth of collaboration scales with the user.

## What

- **DB-backed source of truth.** Schema in `src/hallucinote/db/schema.sql`. Mutators in `db/mutations.py` paired with an append-only event log. Every write a row, every write an event.

- **Pure generators.** `generators/*` produce note arrays with semantic tags. No DB or MCP coupling. The library a human-or-LLM composes against.

- **Plan-based Ableton sync.** `sync/push.py` returns a plan of MCP tool calls; the agent executes; results flow back via `apply_push_results`. Pure, testable, reorder-safe.

- **Bidirectional sync.** Edits made in Ableton come back into the DB. Requires note-level addressing in MCP — see `ableton://guides/gaps`. Without stable note IDs, sync-back is destructive; with them, it is diff-and-apply.

- **Full LLM access via MCP.** Every read, every write, every generator parameter. Nothing hidden behind a UI the model cannot see.

- **Songs as git repos.** A song is a directory: source code (`build.py`), generator outputs, a SQLite DB. Clone the repo, run `build.py`, you have the song on your machine against your Ableton. Or sync from a checked-in DB snapshot. Either path reproduces the song.

## Non-goals

- **A general DAW.** Ableton is the rendering engine. Hallucinote leans on it, does not compete with it.

- **A non-LLM authoring tool.** Anyone can write Python against the library. That is not who this is for. Every design choice favors the LLM workflow.

- **A live performance system.** This is a composition and production tool. Performance happens downstream, in Ableton, with a rendered song.

- **A walled garden.** No proprietary formats. SQLite, Python, git, standard MCP. If Hallucinote dies, your songs are still composable from the repo.

## What this costs

Naming the hard parts so they do not surprise us:

- **Microtonal and polytempic music is real work.** The DB models it cleanly; getting Ableton to render it requires Max for Live, per-voice pitch routing, or 1/64-grid event positioning. Doable. Not free.

- **Bidirectional sync needs MCP changes.** Note-level addressing is the gate (see `ableton://guides/gaps`). Until it lands, Ableton → DB is destructive — we push, we do not pull safely.

- **The DB is the contract.** Schema changes have to migrate carefully. The mutator-plus-event discipline is the only thing that makes a future event-store flip cheap rather than a rewrite. Drift here is expensive.

- **LLM-as-composer is unproven at this depth.** "Structured access lets the model collaborate musically" is the bet. We will find places where it does not, and the answer will sometimes be more structure, sometimes better prompts, sometimes a different generator API. We learn by shipping songs.
