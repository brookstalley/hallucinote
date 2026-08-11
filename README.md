# Hallucinote

**Make music in Ableton Live by describing it to Claude — composition, sound design, and mix, authored as code you can version and fork.**

<!-- HERO: replace docs/assets/hero.svg with a real screen capture before release —
     a prompt typed into Claude Code on the left, an Ableton Live set filling in on the right. -->
![A prompt, and the Ableton Live set it built](docs/assets/hero.svg)

You describe a song in plain language. Claude writes it — the composition, the sound design, the mix — as a Python `build.py` plus a captured-session snapshot, builds that into a SQLite working state, and pushes the whole thing into a running Ableton Live set. Tweak a fader in Live and pull the change back through the same path. The song is a directory you commit to git — reproducible and forkable, not a binary `.als` you hope to find again.

It runs today on Ableton Live 12 (see [Status](#status) for what's in and what isn't), and the rest of this page gets you from zero to a playing song.

---

## See it

> *"Make a 2-minute punk song that crams the chord progression of Beethoven's 5th into those two minutes. Drums, bass, lead guitar, and vocals on a staccato synth. Call it punk-fate."*

Claude scaffolds `songs/punk-fate/`, picks an instrument chain per track, writes a `build.py` against the generator library, builds the DB, and pushes it into Live through fourteen ordered phases:

```
tempo → meter → tracks → returns → scenes → clips →
mix → devices → routing → device-sidechain → envelopes →
performed automation → arrangement → cues
```

When it finishes you have a finished session — named tracks, clips, device chains, the mix, the routing — ready to play. Don't like the bridge? *"Lift the lead an octave there, and make the chorus drums drag."* Claude edits the code and re-pushes; re-runs are idempotent, so it changes what you asked for and leaves the rest alone.

## How it works

```
   you (plain language)
        │
        ▼
     Claude ── writes ──▶  build.py  +  captured_session.json     ← the source of truth (git-tracked)
        │                              │
        │                            build
        │                              ▼
        │                         SQLite DB     ← materialized state (rebuilt from those files)
        │                          │     ▲
        │                    push  │     │  pull
        │                          ▼     │
        └──────────────────▶   Ableton Live   ◀── you tweak faders, notes, sends by hand
```

- **You talk; Claude authors code.** Composition (notes, arrangement, automation) is Python in `build.py`. The mix layer (instruments, device chains, dialed parameters, sends, routing) is a declarative `captured_session.json` snapshot. Both are git-tracked source — see the [authorship model](.prawduct/artifacts/authorship-model.md) for where each kind of thing lives and why.
- **The DB is materialized state, not the source.** `build.py` and the snapshot are the git-tracked source of truth; they build into one SQLite database (gitignored, rebuildable) that every change converges on through a mutator and an event — so the history is real and the future event-store migration is cheap.
- **Push materializes; pull ingests.** Push drives the DB into a fresh-or-existing Live set through the fourteen phases above. Pull diffs Live against the DB and folds manual edits back through the same mutators.
- **The agent listens.** Claude can render the set to audio and review the mix against your stated intent — masking, loudness, reverb, the groove — and tell you the one thing holding the chorus back, as a producer's question, not a score.

## What you can do

The `/hallucinote:*` names below are the skills Claude runs for you. You can type them, but you don't have to — describing what you want in plain language reaches the same place.

- **Compose from a prompt — any genre, any shape.** `/hallucinote:song-new <slug>` scaffolds the song; Claude writes the `build.py` and pushes it into Live. Pitch the brief however you think about music — it can be:
  - **conceptual** — *"a song about overcoming loss"*
  - **musical** — *"a Bach-style Baroque prelude in G minor built from a single broken-chord figuration"*
  - **stylistic** — *"a pure-electronica ska tune that keeps the traditional structure but goes wild with the harmony"*
  - **derivative** — *"the song Duran Duran would have written if they dropped acid with Black Sabbath"*
- **Under-specify on purpose.** A prompt isn't a spec, and you shouldn't have to write one. `/hallucinote:song-brief` works out what your prompt actually leans on — the key, the tempo, whether two sonic worlds argue in the production or only in the writing, what a named turn means musically — and comes back **once** with informed proposals you can wave through or redirect in a word. It stays quiet about what your song doesn't have: an ambient piece never gets asked about drum style.
- **Iterate by talking.** *"Raise the verse ghost snares,"* *"swap the chorus walk for a fill at bar 12,"* *"route the drums through a sub-bus and glue-compress it"* — Claude edits the code and re-pushes.
- **Treat sound design as authorship.** Device chains, dialed parameters, and sends ship in the snapshot, not in a vague post-push mix pass. A finished song has the sound it's supposed to have.
- **Pull manual edits back.** Move faders, mutes, or notes in Live, then `/hallucinote:ableton-pull` to fold them into the DB.
- **Review against intent.** `/hallucinote:compose-review` reads the composition on any edition; `/hallucinote:mix-review` reads the rendered mix — masking, loudness, groove — and needs Max for Live (see [Status](#status)).
- **Share and fork.** A song is a directory. Commit it; a collaborator clones it, and the compat check refuses-and-confirms before pushing if they're missing a third-party plugin the song uses.

## Status

Actively developed, shipping releases, and honest about the rough edges:

- **Platforms:** Ableton Live 12 on macOS and Windows. Linux is unsupported — Ableton ships no Linux build.
- **Live edition:** the authoring loop — compose, push, pull, play, and the symbolic `compose-review` — runs on **any Live 12 edition, Standard included**. The audio-analysis features (render → `mix-review` by measurement) need **Max for Live**, so they're **Suite-only**; `/hallucinote:ableton-mcp-install` asks whether you have Suite and lets Standard users skip the analyzer.
- **Audio recording is a boundary, not a feature yet.** Claude authors MIDI and the mix; a human vocal take or a hand-ridden automation lane can't be read back through the bridge.

**[Known issues](#known-issues)** lists everything else we've consciously accepted, with workarounds.

## Known issues

Limitations we know about and have consciously accepted for now — each with its workaround where one exists. (Per-release detail lives at the bottom of [`CHANGELOG.md`](CHANGELOG.md#known-limitations).)

- **Removing a sidechain in Live needs a full rebuild, not an incremental one.** A snapshot that is *silent* about a device's sidechain source is treated as "no opinion," so a sidechain authored in `build.py` survives every rebuild. The flip side: if you delete a sidechain *in Live* and re-snapshot, an incremental rebuild won't clear the old source. To drop it durably, rebuild from a fresh DB, clear it in `build.py` with `set_device_sidechain(None)`, or write an explicit null source into the snapshot.
- **Human audio can't be read back through the bridge.** Claude authors MIDI and the mix; a recorded vocal take or a hand-ridden fader-automation lane lives only in the `.als` — the bridge can't pull it into a song's source. Audio recording is a boundary, not a feature, today.
- **Measured mix review needs Max for Live (Suite).** The authoring loop — compose, push, pull, play, and the *symbolic* `/compose-review` — runs on any Live 12 edition. Only the render → analysis → `/mix-review` path needs Max for Live, so on Standard you review by ear with `/compose-review`. This split is by design (see [`docs/capability-truth.md`](docs/capability-truth.md)).
- **Mid-song tempo / time-signature changes aren't supported.** Changes before bar 1 round-trip cleanly; a mid-song change surfaces a refuse-and-teach at the call site (a real MCP gap, never silent data loss).
- **A few device-parameter enums can't round-trip.** Some Live enum parameters have no normalized form on the MCP wire; they're skipped with a warning rather than set to the wrong value. Continuous parameters round-trip cleanly.
- **A few nested-rack corners are still one level deep.** Racks nested inside racks are captured, replayed and pushed to any depth. Three narrower things aren't there yet: pulling a *sidechain* setting back from a nested device, pulling a rack that sits on another rack's chain, and the snapshot-refresh *preview*, which itemizes one level and summarizes deeper subtrees rather than listing them (a display simplification — the underlying data round-trips in full).
- **Linux is unsupported.** Ableton Live ships no Linux build; Wine/CrossOver gets a best-effort install candidate with warn-and-confirm. macOS and Windows are the supported platforms.

## Install

The plugin is **self-contained.** Installing it brings the `/hallucinote:*` skills, the `hallucinote-mcp` bridge server, **and** the composing engine your songs' `build.py` runs against — all in one uv-managed environment Claude Code builds on first launch. There's **no separate engine to clone or pip-install**, and nothing on PyPI to track.

### 1. Install prerequisites

- **[Claude Code](https://claude.ai/code)**, **Ableton Live 12**, **Python 3.10+**.
- **[uv](https://docs.astral.sh/uv/)** — `brew install uv` (macOS) or `winget install astral-sh.uv` (Windows). The plugin uses it to build its locked, isolated environment; no PATH or venv juggling.

### 2. Install the plugin

In Claude Code:

```text
/plugin marketplace add brookstalley/hallucinote
/plugin install hallucinote@hallucinote
```

This installs the skills, the bridge server, and the engine. uv builds the locked environment on first launch (a SessionStart hook pre-warms it, so later starts are instant). That's the whole install — no clone, no `pip install`.

### 3. Connect Ableton

Quit Live, then in Claude Code run **`/hallucinote:ableton-mcp-install`** (it copies the Remote Script into Live's User Library and installs the analyzer — the one thing the plugin can't do for you). Reopen Live, and in **Preferences → Link, Tempo & MIDI** assign **Hallucinote** to a free Control Surface slot (leave Input/Output as None). Restart Claude Code so the bridge connects.

### 4. Verify

> *"please get the current set's info from Ableton"*

You should get back tempo, signature, track counts, and master state. That's the bridge working.

**Hacking on the framework itself?** Load the plugin from your checkout with `claude --plugin-dir /path/to/hallucinote` instead of installing it — details in [`CONTRIBUTING.md`](CONTRIBUTING.md).

## Your first song

Setup is one-time. Day to day: open Live, start Claude Code in your **songs workspace** (a repo with a `hallucinote.toml` marker), and talk. No workspace yet? In an empty folder, ask Claude to *"set up a songs workspace here"* (or run `hallucinote init-workspace`) — it writes the `hallucinote.toml` marker, a `.gitignore` that excludes the regenerable build artifacts (the SQLite DB, captures, analysis), and `git init`s the folder, so your songs are version-controlled from the start. New to it? Run **`/hallucinote:getting-started`** — it checks your setup, creates the workspace if you need one, says what works with and without Max for Live, and points you at the first step. The [**Quickstart**](docs/quickstart.md) walks the first song end to end in about ten minutes.

## Troubleshooting

- **"Version mismatch" / "handshake missing"** — the bridge server and Live's Remote Script have diverged (usually after an update). Rerun `/hallucinote:ableton-mcp-install`, then **fully quit and reopen Live** — `/mcp` alone won't do it, because Live caches Control Surface modules at startup.
- **`ableton_session(action='info')` hangs or says "no connection"** — Live isn't running, the Control Surface slot isn't assigned, or Claude Code wasn't restarted after assigning it.

Still stuck? Ask Claude to **run preflight** — it prints a JSON report of exactly what the installer can and can't find. (The command is `python -m hallucinote_mcp.cli preflight`, but it has to run in the plugin's environment, so asking Claude is the reliable way; run from your own shell it will usually just fail to import.) More in the [FAQ](docs/faq.md). Bugs go to [issues](https://github.com/brookstalley/hallucinote/issues); please report vulnerabilities privately instead — see [`SECURITY.md`](SECURITY.md).

## Learn more

| If you want to… | Read |
|---|---|
| Build your first song, step by step | [`docs/quickstart.md`](docs/quickstart.md) |
| Understand the whole song-making lifecycle | [`docs/song-workflow.md`](docs/song-workflow.md) |
| See every command (skill) you can ask for | [`docs/skills.md`](docs/skills.md) |
| Understand the design philosophy | [`docs/VISION.md`](docs/VISION.md) |
| Write or edit a song's `build.py` | [`docs/song-authoring-conventions.md`](docs/song-authoring-conventions.md) |
| Know where a song's authorship lives, and why | [`.prawduct/artifacts/authorship-model.md`](.prawduct/artifacts/authorship-model.md) |
| Share a song with a collaborator | [`docs/collaboration.md`](docs/collaboration.md) |
| Look something up / fix a problem | [`docs/faq.md`](docs/faq.md) |
| Know what needs Max for Live, and why | [`docs/capability-truth.md`](docs/capability-truth.md) |
| See what changed in a release | [`CHANGELOG.md`](CHANGELOG.md) |
| Contribute code | [`CONTRIBUTING.md`](CONTRIBUTING.md) |
| Get precise about an overloaded term | [`docs/terminology.md`](docs/terminology.md) |

## Project layout

```
src/hallucinote/      # composition engine: db, generators, sync, capture
hallucinote_mcp/      # the MCP bridge server (13 unified Ableton tools)
skills/               # the /hallucinote:* Claude Code skills the plugin ships
docs/                 # quickstart, song workflow, conventions, FAQ, schemas, …
tools/                # scaffolding + maintenance scripts
tests/                # platform-level tests
```

This is the **framework** repo. Your **songs live in a separate workspace repo** (a folder with a `hallucinote.toml` marker) — each song a self-contained directory: `build.py`, `captured_session.json`, `decisions/`, `annotations/`, `tests/`, and a per-branch SQLite DB (gitignored).

## License

MIT. See [`LICENSE`](LICENSE).
