# Hallucinote

**Composition and production for Ableton Live.
Describe what you're after, hear it, argue with it — the song is code you can read, fork and rewrite.**

[![CI](https://github.com/brookstalley/hallucinote/actions/workflows/ci.yml/badge.svg)](https://github.com/brookstalley/hallucinote/actions/workflows/ci.yml) [![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Platform](https://img.shields.io/badge/Ableton%20Live%2012-macOS%20%7C%20Windows-black)

![The punk-fate prompt and creative brief in Claude Code, beside the finished four-track arrangement it built in Ableton Live](docs/assets/hero.png)

Say what you're going for and it gets built into a running Live set — `build.py` for the notes, a snapshot for the instruments and mix.
Then you listen, change your mind, and it rebuilds.
Because the song is code in a git directory, trying the half-time bridge or the key change costs a branch and a minute: keep it, or throw it away and try the next one.
What you end up with is an ordinary Ableton set you finish yourself.

---

## See it

> *"Make a 2-minute punk song that crams the chord progression of Beethoven's 5th into those two minutes. Drums, bass, lead guitar, and vocals on a staccato synth. Call it punk-fate."*

One sentence started it.
What made it a song was the next forty minutes: a brief that pinned down what *"Beethoven's Fifth as punk"* actually meant, four parts composed and revised, sound design, a render, and one mix correction that was measured before it was applied.
A listening session the same day pushed it further, until it *sounded* like the brief:

[![Punk Fate — full song waveform](docs/assets/tour-chapter2.png)](docs/assets/tour-chapter2.mp3)

**[▶ Listen — punk-fate, 1:58](docs/assets/tour-chapter2.mp3)** · The finished song ships here as source: [`examples/punk-fate/`](examples/punk-fate/).

Getting there runs fourteen ordered phases:

```
tempo → meter → tracks → returns → scenes → clips →
mix → devices → routing → device-sidechain → envelopes →
performed automation → arrangement → cues
```

Then press play.
Want the bridge to hit harder?
*"Lift the lead an octave there, and make the chorus drums drag."* Claude edits the code and re-pushes, changing what you asked for and leaving the rest alone.

**Beat by beat, with the transcript, the screenshots and the mix numbers: [the tour](docs/tour.md).**

## How it works

![The lifecycle: a prompt becomes authored code, lands in Live, and the agent listens back](docs/assets/lifecycle.svg)

- **You decide; it writes the decision down.** Notes, arrangement and automation in `build.py`; instruments, chains and the dialed mix in a snapshot.
  Every choice is legible afterwards — you can read what was done, and why, and change it.
- **The notes come from generators you can read.** Parametric Python — `tresillo`, `walking_bass`, kit abstractions, per-part feel.
  Claude's craft is choosing which to call and with what musical parameters, then writing that down.
  What lands in Live is MIDI and mixer state in a session you own outright.
- **Push materializes; pull ingests.** Push drives the song into a fresh or existing set; pull folds your manual Live edits back in.
  Re-runs are idempotent.
- **It listens back, and tells you straight.** Ask *"is the chorus landing?"* and Claude reads the composition, or renders the set and measures masking, loudness and groove, against the intent *you* declared — then reports what it found and what it would change.
  Real numbers, and an opinion you can overrule.

## Who it's for

- **Curious how songs get put together.** Ask for something, then ask why it works that way.
  It proposes with the reasoning showing — *"E minor, so the chorus can lift into the relative major"* — and you can overrule it and hear the difference straight away.
  You learn the craft by watching choices get made, then making better ones.
- **Playing already, and reaching further.** The arrangement you can hear in your head but would spend a week programming: a bassline weaving between two different kick patterns, thirty-two bars of hats that breathe, a polyrhythmic bridge.
  Ask for it and listen to it.
- **Deep in it.** Leverage.
  Bulk edits you'd otherwise script by hand, chorus variants on branches you A/B and discard, and a review pass that measures masking, loudness and timing against the intent you declared — then tells you where it disagrees.
  A second opinion with numbers behind it is rarer than it should be.

## What to ask for

- **Any genre, any shape.** Conceptual (*"a song about overcoming loss"*), musical (*"a Baroque prelude in G minor from a single broken-chord figuration"*), or stylistic (*"Duran Duran if they dropped acid with Black Sabbath"*).
- **Under-specify on purpose.** Claude works out what your prompt leans on (`/hallucinote:song-brief`) — key, tempo, what a named turn means musically — and comes back **once** with proposals you can wave through or redirect in a word.
- **Share and fork.** A collaborator clones the directory; Hallucinote checks their plugins first and names anything missing.

## Status

Actively developed, and honest about the rough edges:

- **Platforms:** Ableton Live 12 on macOS and Windows (Ableton ships no Linux build). macOS is where it's developed day to day; the Windows paths are implemented and unit-tested, with fewer real sessions behind them.
- **Editions:** the full authoring loop is exercised on **Live 12 Standard and Suite**.
  Only the measured mix review needs **Max for Live** (Suite, or the add-on for Standard); without it, review is symbolic: it reads the score.
  Intro and Lite are untested, and their track limits will bite.
- **The melody is yours.** Sketch a topline in Live and it arranges, sound-designs and mixes the whole track underneath, then reads the line back against your intent — contour, intervals, how it sits on the chords.
  [How that works](docs/faq.md#what-about-the-melody).
  Sung vocals are on the list; today the synth sings.
- **Boundaries:** MIDI and the mix are what it builds; a recorded vocal take can't yet be read back through the bridge.
- **What it costs to run:** Hallucinote is free; the Claude usage behind it bills to your plan.
  A song is a long agentic session — the worked example above ran about forty minutes of continuous agent work, and each measured mix pass hands back a sizeable analysis payload.
  Expect a full compose-and-mix session to eat a real share of a Claude plan's budget.
  `/cost` reports what a session actually used.
  Live 12 (and Max for Live for the measured review) is the other bill.

The rest, each with its workaround: [**Known issues**](docs/known-issues.md).

## Install

The plugin is **self-contained** — skills, Ableton bridge and composing engine in one managed environment.
Nothing else to clone or track.

**1. Prerequisites** — [Claude Code](https://claude.ai/code), Ableton Live 12, and [uv](https://docs.astral.sh/uv/) (`brew install uv` on macOS, `winget install astral-sh.uv` on Windows). uv provisions the Python the plugin needs, so you don't install one.

**2. Install the plugin** — in Claude Code:

```text
/plugin marketplace add brookstalley/hallucinote
/plugin install hallucinote@hallucinote
```

**3. Connect Ableton** — quit Live, run **`/hallucinote:ableton-mcp-install`** (it installs the Remote Script and analyzer, the one thing the plugin can't do for you).
Reopen Live and assign **Hallucinote** to a free Control Surface slot in **Preferences → Link, Tempo & MIDI**.
Restart Claude Code.

**4. Verify** — ask Claude *"get the current set's info from Ableton."* Tempo, signature and track counts coming back means the bridge works.

**Hacking on the framework itself?** Load it from your checkout with `claude --plugin-dir /path/to/hallucinote` — see [`CONTRIBUTING.md`](CONTRIBUTING.md).

## Your first song

Open Live with an empty set, start Claude Code wherever your songs live (any folder — Claude offers to create the workspace), and describe a song.
Unsure about your setup?
Run **`/hallucinote:getting-started`** first.

The [**Quickstart**](docs/quickstart.md) walks the first song end to end in ten minutes.

## Troubleshooting

- **"Version mismatch" / "handshake missing"** — bridge and Remote Script have diverged, usually after an update.
  Rerun `/hallucinote:ableton-mcp-install`, then **fully quit and reopen Live** (it caches Control Surface modules at startup).
- **Session info hangs or "no connection"** — Live isn't running, the Control Surface slot isn't assigned, or Claude Code wasn't restarted after assigning it.
- **Anything else** — ask Claude to **run preflight**; it reports what the installer can and can't find.
  More in the [FAQ](docs/faq.md).

Bugs go to [issues](https://github.com/brookstalley/hallucinote/issues); report vulnerabilities privately instead — see [`SECURITY.md`](SECURITY.md).

## Learn more

| If you want to… | Read |
|---|---|
| See everything you can ask for | [`docs/skills.md`](docs/skills.md) |
| Understand the whole song-making lifecycle | [`docs/song-workflow.md`](docs/song-workflow.md) |
| Share a song with a collaborator | [`docs/collaboration.md`](docs/collaboration.md) |
| Understand the design philosophy | [`docs/VISION.md`](docs/VISION.md) |
| Read or edit a song's `build.py` | [`docs/song-authoring-conventions.md`](docs/song-authoring-conventions.md) |
| See what changed in a release | [`CHANGELOG.md`](CHANGELOG.md) |
| Contribute code | [`CONTRIBUTING.md`](CONTRIBUTING.md) |
| Browse all the docs | [`docs/README.md`](docs/README.md) |

## Project layout

```
src/hallucinote/      # composition engine: db, generators, sync, capture
hallucinote_mcp/      # the MCP bridge server (13 unified Ableton tools)
skills/               # the /hallucinote:* Claude Code skills the plugin ships
docs/                 # quickstart, tour, conventions, FAQ, schemas, …
```

This is the framework.
Your songs live in their own repo, one directory each: build code, mix snapshot, decisions, tests.

## License

MIT.
See [`LICENSE`](LICENSE).
