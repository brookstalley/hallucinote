# Hallucinote

**Composition and production for Ableton Live. You make the calls; Claude does the building — notes, sound design and mix, as code you can read, version and fork.**

[![CI](https://github.com/brookstalley/hallucinote/actions/workflows/ci.yml/badge.svg)](https://github.com/brookstalley/hallucinote/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Platform](https://img.shields.io/badge/Ableton%20Live%2012-macOS%20%7C%20Windows-black)

![The punk-fate prompt and creative brief in Claude Code, beside the finished four-track arrangement it built in Ableton Live](docs/assets/hero.png)

Say what you're going for and it gets built into a running Live set — `build.py` for the notes, a snapshot for the instruments and mix. Then you listen, change your mind, and it rebuilds. Deciding what's right is the part that doesn't get automated, and shouldn't. What you're left with is an ordinary Ableton set you finish yourself, and a song that lives in a git directory instead of a binary `.als` you hope to find again.

---

## See it

> *"Make a 2-minute punk song that crams the chord progression of Beethoven's 5th into those two minutes. Drums, bass, lead guitar, and vocals on a staccato synth. Call it punk-fate."*

One sentence started it. What made it a song was the next forty minutes: a
brief that pinned down what *"Beethoven's Fifth as punk"* actually meant, four
parts composed and revised, sound design, a render, and one mix correction that
was measured before it was applied. A listening session the same day pushed it
further, until it *sounded* like the brief and not just like the plan:

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

- **You decide; it writes the decision down.** Notes, arrangement and automation in `build.py`; instruments, chains and the dialed mix in a snapshot. Every choice is legible afterwards — you can read what was done, and why, and change it.
- **Push materializes; pull ingests.** Push drives the song into a fresh or existing set; pull folds your manual Live edits back in. Re-runs are idempotent.
- **It listens back — and it will tell you no.** Ask *"is the chorus landing?"* and Claude reads the composition, or renders the set and measures masking, loudness and groove, against the intent *you* declared. It reports what it actually found, including when the answer is that it isn't working.

## What it isn't

**There's no music model in here.** Nothing was trained on anyone's recordings, and nothing generates audio. The notes come from hand-written generators — plain Python you can open and read — and what lands in Live is MIDI and mixer state. You aren't handed a finished track that came from somewhere else. You're handed a session you own, and you finish it.

**It won't write your hook.** No melody generator, and there won't be one. Sketch a topline and it builds the arrangement, the sound design and the mix underneath, then reads the line back and tells you whether it's landing. The part that makes a song recognizably yours stays yours.

**It doesn't take the work away — it moves where the work goes.** Laying out 32 bars of hats with a feel that isn't robotic, dialing in a sidechain, working out whether the bass is masking the kick: that comes off your plate. Knowing what the song should be, and hearing when it isn't there yet, is still the whole job.

## Who it's for

- **Learning.** It proposes with the reasoning showing — *"E minor, so the chorus can lift into the relative major"* — and names the mechanism behind whatever you asked for. You can follow the argument, push back on it, and hear what changes. That's a different thing from a button that returns a song and teaches you nothing.
- **Competent, and stuck on something.** Everyone has a part they're weakest at: drums that never quite swing, a mix that stays muddy, an arrangement that won't go anywhere. Get past it without abandoning the track or losing three days inside someone else's tutorial.
- **Expert.** Leverage, and an argument. Bulk edits you'd otherwise script by hand, a chorus variant on a branch you can A/B and throw away, and a review pass that measures masking, loudness and timing against the intent you declared — then says where it disagrees. A second opinion with numbers behind it is rarer than it should be.

## What to ask for

- **Any genre, any shape.** Conceptual (*"a song about overcoming loss"*), musical (*"a Baroque prelude in G minor from a single broken-chord figuration"*), or stylistic (*"Duran Duran if they dropped acid with Black Sabbath"*).
- **Under-specify on purpose.** Claude works out what your prompt leans on (`/hallucinote:song-brief`) — key, tempo, what a named turn means musically — and comes back **once** with proposals you can wave through or redirect in a word.
- **Share and fork.** A collaborator clones the directory; Hallucinote checks their plugins first and names anything missing.

## Status

Actively developed, and honest about the rough edges:

- **Platforms:** Ableton Live 12 on macOS and Windows (Ableton ships no Linux build).
- **Editions:** the full authoring loop is exercised on **Live 12 Standard and Suite**. Only the measured mix review needs **Max for Live** (Suite, or the add-on for Standard); without it, review is symbolic — against the score, not the audio. Intro and Lite are untested, and their track limits will bite.
- **No melody generator** — [by design](docs/capability-truth.md), as above. Vocal *synthesis* is a separate gap, and that one simply isn't built.
- **Boundaries:** Claude authors MIDI and the mix; a recorded vocal take can't yet be read back through the bridge.
- **What it costs to run:** Hallucinote is free; the Claude usage behind it isn't. A song is a long agentic session — the worked example above ran about forty minutes of continuous agent work, and each measured mix pass hands back a sizeable analysis payload. Expect a full compose-and-mix session to eat a real share of a Claude plan's budget. `/cost` reports what a session actually used. Live 12 (and Max for Live for the measured review) is the other bill.

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
