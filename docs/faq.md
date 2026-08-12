# FAQ

Short answers with links to the canonical docs. For install/connection
problems, the [README troubleshooting section](../README.md#troubleshooting) is
the authority — this FAQ points there rather than duplicating it.

## What is Hallucinote, and who is it for?

A composition and production environment for Ableton Live where the building
happens in conversation. You say what you're going for; the song gets written
as readable code — notes, arrangement, sound design, mix — against a SQLite
source of truth, and pushed into Live through an MCP bridge. You listen, you
redirect, it rebuilds.

It suits musicians and producers who are comfortable at a command line, at any
level of musical experience. Learning: it explains its choices, and you can
argue with them. Competent but stuck on drums or mixes: it gets you past that
without derailing the track. Expert: it's leverage — bulk edits, branchable
experiments, and a measured review that will tell you when something isn't
working. See [`docs/VISION.md`](VISION.md) for the why.

## How is this different from Suno, Udio, or "AI music" in general?

Different category, different mechanism. Those are generative audio models: a
prompt goes in, a finished recording comes out, produced by a model trained on
a large corpus of other people's recordings. You can't open the result, you
made none of the decisions inside it, and the provenance of what it learned
from is contested.

**Hallucinote contains no music model of any kind.** The notes come from
hand-written parametric generators — `src/hallucinote/generators/`, plain
Python, and there is no `melody.py` in there. Claude's job is to decide *which
generators to call with which musical parameters*, the way an arranger decides,
and to write that decision down as code you can read and change. What lands is
MIDI and mixer state in your own Live set. Nothing is rendered for you.

The honest comparison isn't Suno. It's a fast, patient arranger and mix
engineer who works inside your DAW, writes down everything they did and why,
argues with you when the chorus isn't landing, and never touches your melody.

## Is using this cheating?

The same question got asked about the drum machine, the sequencer, quantize,
presets, and hiring a session player — and the answer has been the same every
time: it depends on whether the result is what you meant, and whether you can
tell. Hallucinote doesn't make the decisions that make a song yours. It won't
choose your hook and it can't tell you what the song is about; ask it to and
you'll get an honest refusal rather than a plausible imitation.

What it removes is the distance between having an idea and hearing it. In
practice that mostly means you get to *reject* more ideas per hour, which is
what taste is made of. If you finish something you're proud of, nobody is
grading the route you took.

## Why is it called "Hallucinote"?

Because the failure mode is the whole problem. An LLM asked about a DAW will
happily invent a device, a parameter, or a capability it doesn't have, and in
music production that wastes an afternoon before you notice. The name keeps the
risk in view rather than pretending it away.

The countermeasure is structural: [`capability-truth.md`](capability-truth.md)
is a maintained table of what actually works, read by the agent at first
contact and before song creation, with a standing rule that anything not in the
table as supported must not be promised. The bridge refuses-and-teaches at the
call site instead of silently doing the wrong thing, and the mix review reports
*measured* DSP numbers, not impressions. Confabulation is the thing we design
against; naming it seemed more honest than a name that implied we'd solved it.

## Will it write me a melody?

**No — and that's a design decision, not a gap we're closing.** There is no
melody generator and there won't be one. Claude writes the groove, the harmony,
the bass, the arrangement, the sound design and the mix; the lead line — the
hook, the thing people hum — is yours.

What you get instead is an arranger and a mirror. Sketch a topline in Live (or
hum it in and quantize), pull it in, and Hallucinote builds the entire track
underneath it. Then `/hallucinote:compose-review` *reads* the line back —
contour, intervals, how it sits against the chords — and coaches it against the
intent you declared. It measures; it never invents. There is no universal
"good melody" verdict on offer.

So *"write me an 80s synth-pop song like Madonna"* gets you the Madonna-ness
that lives in the dimensions we own — the chord moves, the groove, the
arrangement, the production — with two honest caveats: no synthesized vocal,
and the hook is your job. The full capability table is
[`capability-truth.md`](capability-truth.md).

## What does this cost to run?

Hallucinote itself is free and MIT-licensed. Three real costs sit behind it:

- **Ableton Live 12** — a commercial licence. **Max for Live** on top (bundled
  with Suite, a paid add-on for Standard) if you want the *measured* mix
  review; the authoring loop and the symbolic review don't need it.
- **Claude usage.** This is a long-running agentic workflow, not a chat. A song
  is composed, pushed, rendered, measured and revised over a session that can
  run tens of minutes of continuous agent work, and each measured mix pass
  hands back a sizeable analysis payload. Expect a full compose-and-mix session
  to consume a real share of a Claude plan's budget — `/cost` in Claude Code
  reports what a given session actually used.
- **Disk.** Every measured mix pass renders audio, and the per-render WAVs are
  the heavy part. They land in the song's `captures/`, which is gitignored —
  regenerable, and not something to commit. (The small MixReport JSONs in
  `analysis/` *are* checked in; they're the measurements, not the audio.)

No telemetry, no service fees, no account with us — there is no us to have an
account with. See [`SECURITY.md`](../SECURITY.md).

## Do I need to know Python?

No — for using it. You talk to Claude Code in plain language; the agent writes
the `build.py` code for you. You'll get more control if you can *read* Python
(to inspect or hand-edit a part), but it isn't required. To *contribute* to
Hallucinote itself, yes — see [`CONTRIBUTING.md`](../CONTRIBUTING.md).

## Does it work on Windows?

Yes — macOS and Windows, with **Ableton Live 12** (Ableton ships no Linux
build). Being straight with you about the mileage, though: macOS is where
Hallucinote is developed day to day, and the Windows paths — User Library
locations, the Live process lookup, the Remote Script install — are implemented
and hand-checked but see less traffic. The automated suite runs on neither
platform's Live, because CI has no Ableton to talk to. If something Windows-shaped
breaks, that's a real bug and we want [the issue](https://github.com/brookstalley/hallucinote/issues) —
include your `preflight` output. See [README → Install](../README.md#install).

## Can I mix the song inside Hallucinote?

Hallucinote authors the mix as part of composing — instrument **chains**, device
settings, sends, and per-part feel ship with the song (sound design is
authorship, not a post-hoc to-do). You then push to Live and do hands-on mixing
there; pull your tweaks back with `/hallucinote:ableton-pull` to keep them. Detailed mix
*review* (masking, loudness, reverb, timing) is available via `/hallucinote:mix-review`,
which uses Max for Live (Live Suite, or the M4L add-on); `/hallucinote:compose-review`
reviews the composition against intent on any edition.

## When I'm done, do I have a normal Live set I can finish and release?

**Yes.** Push materializes an ordinary Ableton project — real tracks, real
clips, real devices, real return busses. From there it's plain Live: keep
arranging, comp a vocal over it, run it through your mastering chain, export
the WAV, release it. Nothing about the set is special or locked, and nothing
phones home.

When the README says a song is "a git directory, not a binary `.als`," it means
the *source of truth* is text you can diff and fork — not that you're denied
the `.als`. You get both: source you can version, and a session you can finish
by hand. If you want hand-made changes to survive the next build, fold them
back with `/hallucinote:ableton-pull` and `/hallucinote:song-snapshot`
(see below). If you don't — if the song is finished and Live is where it now
lives — just stop pushing. Nothing rewrites your set behind you.

## If I build the same song twice, do I get the same result?

Yes, given the same `build.py`. The build is a deterministic state-converger:
same source, same database, same notes. Humanization is seeded — the
1/f-correlated timing and velocity "breathing" that keeps parts from sounding
mechanical comes from `apply_profile(..., seed=N)`, so it re-runs identically
rather than drifting every build. Vary the seed per part on purpose (so two
instruments don't breathe in lockstep); the value is committed with the song.

What is *not* reproducible is the **prompt**. Hand the same sentence to a fresh
session and you'll get a different song — different key, different structural
choices — because an agent is making creative decisions, not executing a
recipe. The song is reproducible; the act of composing it isn't. See
[`song-authoring-conventions.md`](song-authoring-conventions.md).

## A push overwrote my manual Live tweaks. How do I keep them?

The DB is the source of truth, so a fresh push converges Live to the DB. Before
re-pushing, fold your manual edits back into the DB:

- Faders / mutes / sends / notes → `/hallucinote:ableton-pull`.
- Device-parameter knob tweaks (and the full mix layout — params, sends, chains,
  sidechain) → `/hallucinote:song-snapshot`, the single durable mix bake. It writes
  the git-tracked `captured_session.json`, so the next `build.py` reproduces them
  (a DB-only bake would revert on rebuild).

The build holds you to it: a mix edit you pulled but didn't snapshot makes the
next `build.py` refuse to run (`StaleSnapshotError`) instead of silently
reverting it. Bake with `/hallucinote:song-snapshot` and build again — pull →
bake → build.

See the [Quickstart](quickstart.md#4-pull-manual-edits-back-optional).

## Can I share a song if my collaborator doesn't have the same plugins?

Mostly yes. A song is a directory you commit to git. On push, the compat check
probes the collaborator's installed plugins and refuses-and-confirms if a
third-party plugin is missing, generating a `REQUIREMENTS.md` of what to install.
Native Live devices and catalog-ID drift are handled automatically; bundling
sample packs is out of scope. The three portability cases are spelled out in
[`docs/collaboration.md`](collaboration.md).

## Who owns the music? And is it going to plagiarize someone?

**We claim nothing.** The MIT licence covers Hallucinote's *code*, not the
songs you make with it. Nothing you author is transmitted to us — the tool runs
locally, sends no telemetry, and makes no outbound calls of its own
([`SECURITY.md`](../SECURITY.md)). Your song directory is yours.

On plagiarism, the architecture matters more than any promise: **there is no
generative audio model in Hallucinote.** No trained music model, no sample
regurgitation, nothing lifted from a corpus. The notes come from hand-written
parametric generators (`src/hallucinote/generators/` — plain Python producing
note arrays), and Claude's job is to *call* them with musical parameters. The
one component with the highest plagiarism risk in machine-made music — the
lead melody — is the one this tool deliberately [won't write](#will-it-write-me-a-melody).

Two honest caveats. Ask for a specific existing song's material and you may
well get it — that's what "cram Beethoven's Fifth into two minutes" is *for*,
and the responsibility for what you ask is yours (that example is public
domain; a 2019 pop single isn't). And the copyright status of AI-assisted work
is unsettled and varies by jurisdiction, with human authorship generally the
hinge. Nothing here is legal advice; if you're releasing commercially, get
your own.

## Can I compose in a non-12 tuning (microtonal / 19-EDO / Bohlen-Pierce)?

Yes — a niche path built so 12-TET songs never pay for it. You think in
scale-degree indices, a mapper converts each to a MIDI integer the **unchanged**
generators consume, and Live's loaded tuning reinterprets the pitches at playback.
Push can't load the tuning for you (the LOM tuning surface is read-only), so it
instructs you to drag the cached `.ascl` in and warns if the wrong one is loaded.
Full story + current limitations: [`docs/alternate-tunings.md`](alternate-tunings.md).

## Where do the notes, automation, and arrangement actually live?

In the song's `build.py` and the SQLite DB it materializes — **not** in Live.
(Live's API can't read clip notes back, among other gaps, so the DB is the
authoritative score.) Manual *mixer* state in Live can round-trip via pull; clip
notes, automation, and arrangement are authored in `build.py`. See
[`docs/song-authoring-conventions.md`](song-authoring-conventions.md).

## It re-built the whole song — did it duplicate everything?

No. Push is **idempotent**: re-running converges Live to the DB's state instead
of stacking duplicates. Iterate freely — change something, push again.

## I get "unknown skill: hallucinote:…" — the skills don't exist.

The plugin isn't loaded in this session. Two ways that happens: you installed
from the marketplace but into a different Claude Code profile/machine, or
you're on a dev machine where the plugin loads via `--plugin-dir` and this
launch didn't pass it. Fix: install per [README → Install](../README.md#install),
or relaunch with `claude --plugin-dir /path/to/hallucinote`. Don't let a
session improvise song work without the plugin — there's no bridge to Live and
no engine environment, so it can only produce an unbuildable scaffold.

## Live won't connect, or I get a "version mismatch."

See [README troubleshooting](../README.md#troubleshooting). The two most common
fixes: assign **Hallucinote** to a Control Surface slot in Live's Preferences,
and after a `git pull` that touched `hallucinote_mcp/`, rerun
`/hallucinote:ableton-mcp-install` then fully **quit and reopen Live** (a `/mcp` reconnect
isn't enough — Live caches Control Surface modules at startup). To diagnose
install state, ask Claude to **run preflight** — the CLI lives inside the
plugin's environment, so running `python -m hallucinote_mcp.cli preflight` from
your own shell will usually just fail to import.

## How does Hallucinote find my song? It looked in the wrong place.

From a song slug, it looks — in order — at `$HALLUCINOTE_SONGS_ROOT`, then the
`hallucinote.toml` workspace marker **above** your session directory, then the
workspace that actually **holds that song** among the ones nested below your
session directory or sitting **beside** it (the usual framework-repo +
songs-repo pair). Only if nothing holds the song does a lone nested workspace
win, so a new song still scaffolds where you'd expect.

It never guesses between two real candidates: if two workspaces both hold the
slug, it says so and names them instead of picking one.

If your songs live somewhere that search can't see — a songs repo more than one
directory sideways, or several candidates — say so once:

```sh
export HALLUCINOTE_SONGS_ROOT=/path/to/your-songs/songs   # the dir holding the song dirs
```

That beats everything else, and every "couldn't resolve" message points at it.
The other reliable fix is simply to start Claude Code **inside** your songs
workspace (the folder with `hallucinote.toml`); `--plugin-dir` can still point
at the framework repo from there.

## Can I edit `build.py` by hand?

Yes. It's plain Python against the generator library, and the build is a
state-converger (running it brings the DB to match the code). The conventions —
generators, feel, kits, meter, repeated sections — are in
[`docs/song-authoring-conventions.md`](song-authoring-conventions.md).

## What can I ask Claude to do? Is there a command list?

See [`docs/skills.md`](skills.md) for the full menu. You don't have to type the
slash-commands — describe what you want and the agent picks the right skill.
