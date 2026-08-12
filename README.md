# Hallucinote

**Make music in Ableton Live by describing it to Claude — composition, sound design, and mix, authored as code you can version and fork.**

[![CI](https://github.com/brookstalley/hallucinote/actions/workflows/ci.yml/badge.svg)](https://github.com/brookstalley/hallucinote/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Platform](https://img.shields.io/badge/Ableton%20Live%2012-macOS%20%7C%20Windows-black)

![The punk-fate prompt and creative brief in Claude Code, beside the finished four-track arrangement it built in Ableton Live](docs/assets/hero.png)

You describe a song; Claude writes it as code — `build.py` for the notes, a snapshot for the instruments and mix — and pushes it into a running Live set. A song is a git directory, not a binary `.als` you hope to find again.

---

## See it

> *"Make a 2-minute punk song that crams the chord progression of Beethoven's 5th into those two minutes. Drums, bass, lead guitar, and vocals on a staccato synth. Call it punk-fate."*

That one sentence kicked off a forty-minute session — brief, composition, sound
design, push, render, one measured mix correction — that ended with a finished
four-track song playing in Live. A listening session the same day made it
*sound* like the brief:

[![Punk Fate — full song waveform](docs/assets/tour-chapter2.png)](docs/assets/tour-chapter2.mp3)

**[▶ Listen — punk-fate, 1:58](docs/assets/tour-chapter2.mp3)** · The finished song ships here as source: [`examples/punk-fate/`](examples/punk-fate/).

Getting there runs fourteen ordered phases:

```
tempo → meter → tracks → returns → scenes → clips →
mix → devices → routing → device-sidechain → envelopes →
performed automation → arrangement → cues
```

Then press play. Don't like the bridge? *"Lift the lead an octave there, and make the chorus drums drag."* Claude edits the code and re-pushes, changing what you asked for and leaving the rest alone.

**Beat by beat, with the transcript, the screenshots and the mix numbers: [the tour](docs/tour.md).**

## How it works

![The lifecycle: a prompt becomes authored code, lands in Live, and the agent listens back](docs/assets/lifecycle.svg)

- **You talk; Claude authors code.** Notes, arrangement and automation in `build.py`; instruments, chains and the dialed mix in a snapshot. Sound design ships with the song, so it arrives sounding the way it should.
- **Push materializes; pull ingests.** Push drives the song into a fresh or existing set; pull folds your manual Live edits back in. Re-runs are idempotent.
- **The agent listens.** Ask *"is the chorus landing?"* and Claude reads the composition — or renders the set and measures masking, loudness and groove — against the intent you stated.

## What to ask for

- **Any genre, any shape.** Conceptual (*"a song about overcoming loss"*), musical (*"a Baroque prelude in G minor from a single broken-chord figuration"*), or stylistic (*"Duran Duran if they dropped acid with Black Sabbath"*).
- **Under-specify on purpose.** Claude works out what your prompt leans on (`/hallucinote:song-brief`) — key, tempo, what a named turn means musically — and comes back **once** with proposals you can wave through or redirect in a word.
- **Share and fork.** A collaborator clones the directory; Hallucinote checks their plugins first and names anything missing.

## Status

Actively developed, and honest about the rough edges:

- **Platforms:** Ableton Live 12 on macOS and Windows (Ableton ships no Linux build).
- **Editions:** the full authoring loop runs on **any Live 12 edition, Standard included**. Only the measured mix review needs **Max for Live** (Suite or the add-on); without it, review is by ear against the symbolic analysis.
- **Boundaries:** Claude authors MIDI and the mix; a recorded vocal take can't yet be read back through the bridge.

The rest, each with its workaround: [**Known issues**](docs/known-issues.md).

## Install

The plugin is **self-contained** — skills, Ableton bridge and composing engine in one managed environment. Nothing else to clone or track.

**1. Prerequisites** — [Claude Code](https://claude.ai/code), Ableton Live 12, Python 3.10+, and [uv](https://docs.astral.sh/uv/) (`brew install uv` on macOS, `winget install astral-sh.uv` on Windows).

**2. Install the plugin** — in Claude Code:

```text
/plugin marketplace add brookstalley/hallucinote
/plugin install hallucinote@hallucinote
```

**3. Connect Ableton** — quit Live, run **`/hallucinote:ableton-mcp-install`** (it installs the Remote Script and analyzer, the one thing the plugin can't do for you). Reopen Live and assign **Hallucinote** to a free Control Surface slot in **Preferences → Link, Tempo & MIDI**. Restart Claude Code.

**4. Verify** — ask Claude *"get the current set's info from Ableton."* Tempo, signature and track counts coming back means the bridge works.

**Hacking on the framework itself?** Load it from your checkout with `claude --plugin-dir /path/to/hallucinote` — see [`CONTRIBUTING.md`](CONTRIBUTING.md).

## Your first song

Open Live with an empty set, start Claude Code wherever your songs live (any folder — Claude offers to create the workspace), and describe a song. Unsure about your setup? Run **`/hallucinote:getting-started`** first.

The [**Quickstart**](docs/quickstart.md) walks the first song end to end in ten minutes.

## Troubleshooting

- **"Version mismatch" / "handshake missing"** — bridge and Remote Script have diverged, usually after an update. Rerun `/hallucinote:ableton-mcp-install`, then **fully quit and reopen Live** (it caches Control Surface modules at startup).
- **Session info hangs or "no connection"** — Live isn't running, the Control Surface slot isn't assigned, or Claude Code wasn't restarted after assigning it.
- **Anything else** — ask Claude to **run preflight**; it reports what the installer can and can't find. More in the [FAQ](docs/faq.md).

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

This is the framework. Your songs live in their own repo, one directory each: build code, mix snapshot, decisions, tests.

## License

MIT. See [`LICENSE`](LICENSE).
