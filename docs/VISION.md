# Vision

Hallucinote is an LLM-native music composition and production environment. Ableton Live is the rendering engine.

The song is structured data, not a binary `.als` — and that data is the source of truth: notes, durations, chords, automation values, effect timings, arrangement. The git-tracked `build.py` and captured-session snapshot are what you commit and fork; they build into a SQLite database (with an append-only event log) that is the working state Ableton renders from. Ableton is the speaker, not the score.

Change flows both ways. Today that means the *symbolic* layer: MIDI edits, hand-drawn automation, mixer and device state all come back through `/hallucinote:ableton-pull` into the DB. **Audio does not** — a recorded vocal take lives only in the `.als`, and closing that loop is a goal, not a shipped feature ([known issues](known-issues.md)). Where the round-trip exists, the DB and Ableton agree.

The LLM has full access via MCP — read every note, write every parameter, generate new sections, restructure arrangements, run bulk operations. That is what makes this different from AI features bolted onto a DAW: the model sees structure, not pixels.

## The bet

Two bets, both unproven, both load-bearing:

1. **Structure makes the model competent.** If the LLM sees the song as semantic objects — tags like `ghost` / `downbeat`, section roles, generator-call provenance, an event log of every change — it can collaborate at the level of musical ideas rather than guessing at MIDI bytes. A diff is not "33 notes changed." It is "raised verse ghost snares +5, swapped the chorus walk for an embellishment, added a fill at bar 12."

2. **Songs should be forkable.** A song is a git repo. Branch a chorus variant, A/B against main, throw it away. Two collaborators on different continents can each run the song against their own Ableton, push and pull edits like code.

   The combination worth building is a specific one: text that is *diffable at the level of musical intent* (`raised verse ghost snares +5`, rather than a changed XML node), driving a **mainstream DAW people already finish records in**, with an agent holding complete read/write access to the structure. Plain-text music has a long line behind it — TidalCycles, Sonic Pi, SuperCollider, ChucK, Lilypond, and [DAWproject](https://github.com/bitwig/dawproject) as an open interchange format — and this sits in that line, aimed at those three properties at once.

## Why

- **Move composers up the ladder of abstraction.** "Add a bassline that holds notes between the kicks from drum part A and drum part B." That should work. Today an LLM can describe that idea; with structured access to the song, it can build it.

- **A collaborator that is more than competent.** The target is not "AI fills in a chord progression." The target is: ask for two drum parts at 95 and 100 BPM with a bassline weaving between the kicks of both, and get back something musical. Polyrhythmic, polytempic, sectionally aware — the kind of arrangement that takes a skilled producer hours to lay out by hand.

- **Production moves without the scripting detour.** Bulk operations you would otherwise have to write a script to reach: humanize every backbeat by ±2%, sidechain every sustained pad note to the nearest kick, transpose only the notes tagged `bell`. The DB plus MCP makes these one-liners. The musical judgment about *whether* to do it is untouched; what drops is the mechanical cost of finding out.

- **Big experiments cost almost nothing.** Branching a song is `git checkout -b`. Trying a half-time bridge, a key change, a different drummer feel — reversible, diff-able, reviewable. The fear of breaking something you spent two weeks on goes away.

- **Songs are testable.** Because the song is structured data, you can assert over it. "Bass aligns with kick within 10ms in the verse." "No track is missing pan placement." "Master has a limiter." Quality checks that today take a producer's ear and patient listening become assertions the song carries with it — to verify a change worked, to catch a regression after a fork, to keep the song coherent as it evolves.

- **Reach music Ableton was not built for.** Polytempic pieces encoded by positioning events on a 1/64 grid against one nominal tempo. Microtonal music via Max for Live or per-voice pitch bend. None of this is easy. But the DB representation makes it possible, where the DAW alone makes it actively hostile.

- **Composers anywhere on the spectrum.** Hobbyist with no theory, working producer, thirty-year veteran. Same as an LLM coding agent serving a middle-schooler and a senior engineer: the interface is conversation, and the depth of collaboration scales with the user. The beginner gets a collaborator that explains its choices well enough to argue with; the veteran gets leverage, and a second opinion that can be checked against numbers. Both keep the deciding vote: the tool surfaces its taste explicitly, with reasoning attached, so you can see it and overrule it.

## What

- **DB-backed materialized state.** Schema in `src/hallucinote/db/schema.sql`. Mutators in `db/mutations/` paired with an append-only event log. Every write a row, every write an event.

- **Pure generators.** `generators/*` produce note arrays with semantic tags. No DB or MCP coupling. The library a human-or-LLM composes against.

- **The song as a multi-dimensional structured object.** Beyond raw notes, a song is authored along *structure intents* — form, **energy** (the intensity arc), **harmony** (key/mode/progression — a modeled substrate the parts compose *against*, with a build-time conformance lint) — rendered by *realization layers* (the **performance** layer: microtiming, dynamics, articulation as authorship) over instrument-chain *subsystems*, all sitting on the raw note floor. The organizing dimension taxonomy + design foundation: [`.prawduct/artifacts/arrangement-model.md`](../.prawduct/artifacts/arrangement-model.md) and [`performance-model.md`](../.prawduct/artifacts/performance-model.md).

- **A song you can measure.** Captured per-stem audio + the score feed an analysis pipeline — loudness, inter-track **masking**, per-part **timing/feel**, cross-rhythm, and a **mix-review *against declared intent***. This is how "songs are testable" becomes real for the things only an ear used to catch: quality checks become assertions the song carries. (`ableton_render` / `ableton_analysis`; the masking analyzer.)

- **Plan-based Ableton sync.** `sync/push.py` returns a plan of MCP tool calls; the agent executes; results flow back via `apply_push_results`. Pure, testable, reorder-safe.

- **Bidirectional sync.** Edits made in Ableton come back into the DB — diff-and-apply through the mutator + event path. Pull reads notes by Live's stable per-note IDs (`clip.get_notes_extended()`), so per-note edits round-trip precisely.

- **Full LLM access via MCP.** Every read, every write, every generator parameter. Nothing hidden behind a UI the model cannot see.

- **Songs as git repos.** A song is a directory: source code (`build.py`), generator outputs, a SQLite DB. Clone the repo, run `build.py`, you have the song on your machine against your Ableton. Or sync from a checked-in DB snapshot. Either path reproduces the song.

## Non-goals

- **A general DAW.** Ableton is the rendering engine. Hallucinote leans on it, does not compete with it.

- **A non-LLM authoring tool.** Anyone can write Python against the library. That is not who this is for. Every design choice favors the LLM workflow.

- **A live performance system.** This is a composition and production tool; live-stage performance happens downstream, in Ableton, with a rendered song. *(Distinct from the **performance realization layer** — [`performance-model.md`](../.prawduct/artifacts/performance-model.md) — which authors a song's rendition **feel** (microtiming, dynamics, articulation) at compose time. Authoring how a part is played is in scope; performing it live on a stage is not.)*

- **A walled garden *of ours*.** Open formats throughout: SQLite, Python, git, standard MCP. Your songs stay readable and composable from the repo whatever becomes of us. The dependency that is real: Ableton Live is where they get heard, and the measured mix review wants Max for Live — priced below.

## What this costs

Naming the hard parts so they do not surprise us:

- **The price of entry is Ableton's.** A Live 12 licence, plus Max for Live (bundled with Suite, an add-on for Standard) for the measured mix review. We chose a mainstream DAW on purpose — the point is to author into the tool producers already finish records in — and that choice carries Ableton's price tag.

- **Microtonal and polytempic music is real work.** The DB models it cleanly; getting Ableton to render it requires Max for Live, per-voice pitch routing, or 1/64-grid event positioning. Doable. Not free.

- **Bidirectional sync: round-trip lands; three-way merge doesn't (yet).** `/ableton-pull` ingests mixer, devices, params, arrangement, and per-note edits safely. The remaining cost is conflict resolution, not safety: pull is **"Ableton wins"** (no three-way merge), and note pitch/time *moves* rotate the DB UUID (velocity/mute preserve it). A merge-policy ceiling, not data loss. Surgical Ableton-side note *writes* stay stubbed (use whole-clip replace).

- **The DB is the contract.** Schema changes have to migrate carefully. The mutator-plus-event discipline is the only thing that makes a future event-store flip cheap rather than a rewrite. Drift here is expensive.

- **LLM-as-composer is unproven at this depth.** "Structured access lets the model collaborate musically" is the bet. We will find places where it does not, and the answer will sometimes be more structure, sometimes better prompts, sometimes a different generator API. We learn by shipping songs.
