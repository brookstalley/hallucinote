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

**How it makes the music.** The notes come from hand-written parametric
generators — `src/hallucinote/generators/`, plain Python: tresillo figures,
walking bass, kit abstractions, per-part microtiming. Claude's craft is
choosing which to call with which musical parameters, the way an arranger
works, and writing that choice down as code you can read and edit. What lands
in Live is MIDI and mixer state, in a session you own outright and finish
yourself.

## What about the melody?

The topline is yours to write, and the tool is built around that. Sketch it in
Live — play it in, hum-and-quantize it, however you work — and Hallucinote
builds the entire track underneath: harmony that supports the line, a groove
that sits with it, the arrangement, the sound design, the mix.

Then it holds up a mirror. `/hallucinote:compose-review` reads the line back —
contour, intervals, how it sits against the chords — and coaches it against the
intent you declared, so *"does this chorus actually lift?"* gets an answer with
reasoning attached. It measures the line; the line stays yours.

So *"an 80s synth-pop song like Madonna"* gets you the Madonna-ness that lives
in the chord moves, the groove, the arrangement and the production, built under
whatever topline you bring. The full capability table is
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
  the heavy part. They land in the song's `captures/`, alongside the MixReport
  JSONs in `analysis/`. A workspace created by Hallucinote gitignores both, so
  they stay local, regenerable build artifacts.

Those three are the whole list. Hallucinote itself runs entirely on your own
machine, so there's no account with us and no service fee on top — the Claude
plan and the Ableton licence are billed by Anthropic and Ableton, as you'd
expect. See [`SECURITY.md`](../SECURITY.md).

## Do I need to know Python?

No — for using it. You talk to Claude Code in plain language; the agent writes
the `build.py` code for you. You'll get more control if you can *read* Python
(to inspect or hand-edit a part), but it isn't required. To *contribute* to
Hallucinote itself, yes — see [`CONTRIBUTING.md`](../CONTRIBUTING.md).

## Does it work on Windows?

Yes — macOS and Windows, with **Ableton Live 12** (Ableton ships no Linux
build). Worth knowing where the mileage is, though: macOS is where Hallucinote
is developed day to day. The Windows-specific paths — User Library locations,
the Live process lookup, the Remote Script install — are implemented and
unit-tested, and CI runs on Linux with no Ableton at all, so the Windows
install has far fewer real sessions behind it than the macOS one. If something
Windows-shaped breaks, that's a real bug and we want
[the issue](https://github.com/brookstalley/hallucinote/issues) — include your
`preflight` output. See [README → Install](../README.md#install).

## Can I mix the song inside Hallucinote?

Hallucinote authors the mix as part of composing — instrument **chains**, device
settings, sends, and per-part feel ship with the song (sound design is
authorship, not a post-hoc to-do). You then push to Live and do hands-on mixing
there; pull your tweaks back with `/hallucinote:ableton-pull` to keep them. Detailed mix
*review* (masking, loudness, reverb, timing) is available via `/hallucinote:mix-review`,
which uses Max for Live (Live Suite, or the M4L add-on); `/hallucinote:compose-review`
reviews the composition against intent on Standard as well as Suite.

## When I'm done, do I have a normal Live set I can finish and release?

**Yes.** Push materializes an ordinary Ableton project — real tracks, real
clips, real devices, real return busses. From there it's plain Live: keep
arranging, comp a vocal over it, run it through your mastering chain, export
the WAV, release it.

You get both halves. The git directory is the source you can version, diff and
fork; the `.als` is a session you can finish by hand like any other. When
you're mixing in Live and want those moves to survive the next build, fold them
back with `/hallucinote:ableton-pull` and `/hallucinote:song-snapshot` (see
below). When the song is done and Live is simply where it lives now, stop
pushing and it's yours to finish.

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

## Who owns the music?

You do. The MIT licence covers Hallucinote's code; the songs you make with it
are yours, and they stay on your machine ([`SECURITY.md`](../SECURITY.md)).

The provenance is unusually legible, which helps if you ever need it: the
material comes from the generators described above plus the decisions you
made, and both are written down in `build.py`. For any bar of the song you can
see which generator produced it and which parameters were chosen.

Two things worth knowing. What you ask for is yours to be responsible for —
*"cram Beethoven's Fifth into two minutes"* works partly because that material
is public domain, and a 2019 pop single isn't. And the copyright status of
AI-assisted work is unsettled and varies by jurisdiction, with human authorship
generally the hinge; if you're releasing commercially, get advice that isn't a
FAQ entry.

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
