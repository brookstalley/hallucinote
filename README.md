# Hallucinote

**An LLM-native music composition and production environment.**

You describe musical intent in plain language — *"write a stereotypical metal ballad using I–V–IV"*, *"make a 10-minute ambient soundscape in E major"* — and Claude composes the song against a SQLite source of truth, then pushes it into Ableton Live through an in-repo MCP server. Edits in Live pull back through the same path. Songs become forkable like git repos.

**New here?** Install (below), then follow the [**Quickstart**](docs/quickstart.md) to build your first song in about 10 minutes. Want the big picture first? See [`docs/VISION.md`](docs/VISION.md). For what shipped, see [`CHANGELOG.md`](CHANGELOG.md).

## What you can do

- **Compose a song from a prompt.** `/song-new <slug> [initial instructions]` scaffolds the directory using <slug> as folder name (this will also be used for various filenames); the agent writes a `build.py` against the generator library, materializes a SQLite DB, and pushes the result into a running Ableton Live set.
- **Iterate by talking.** *"raise the verse ghost snares"*, *"swap the chorus walk for a fill at bar 12"*, *"use a giant gated reverb on the chorus drums"*, *"route the drums through a sub-bus and glue-compress it"* — the agent edits `build.py` (or the DB directly) and re-pushes. Re-runs are idempotent.
- **Pull manual edits back.** Tweak faders, mutes, sends, or notes in Live, then run `/ableton-pull` to fold the changes back into the song's DB.
- **Share songs across machines.** A song is a directory you commit to git. The compat check generates a `REQUIREMENTS.md` of third-party plugins the collaborator needs to install; see [`docs/collaboration.md`](docs/collaboration.md) for the round-trip.

### Limitations

Known limitations are listed at the bottom of [`CHANGELOG.md`](CHANGELOG.md#known-limitations).

## Requirements

- **Ableton Live 12** on **macOS or Windows**. 
- **Python 3.10 or newer.** On Windows, if `python` opens the Microsoft Store, use `py -3` everywhere `python` appears below.
- **[uv](https://docs.astral.sh/uv/)** — the Python package/environment manager. The plugin launches the bundled `hallucinote-mcp` server with uv, which builds an isolated, **version-locked** environment from the plugin's committed `uv.lock` (so the running server always matches the plugin you installed — no separate install, no PATH/venv juggling). Install with `brew install uv` (macOS), `winget install astral-sh.uv` (Windows), or the [official installer](https://docs.astral.sh/uv/getting-started/installation/).
- **Claude Code.** Install instructions: <https://claude.ai/code>.

## Install

Hallucinote has two halves:

- the **plugin** — the `/hallucinote:*` skills **plus the bundled `hallucinote-mcp`
  server**. The plugin carries the server's source and a committed `uv.lock`, and
  Claude Code launches it with **uv** into a version-locked, isolated environment.
  You do **not** install the server separately, and there's no PATH/venv to
  activate — see [Requirements](#requirements) for the one-time `uv` install.
- the **engine** — the `hallucinote` Python package that your songs' `build.py`
  composes against. This still needs installing in the environment that runs
  `build.py` (it isn't on PyPI yet, so install it from a clone — below).

Your **songs** live in their own git repo (a workspace with a `hallucinote.toml`
marker), not in this repo — see [`docs/VISION.md`](docs/VISION.md) ("a song is a git repo").

**To just use Hallucinote** (not hack on the framework):

1. **Install `uv`** if you don't have it (see [Requirements](#requirements)).
2. **Install the plugin from GitHub** — in Claude Code:
   ```text
   /plugin marketplace add brookstalley/hallucinote
   /plugin install hallucinote@hallucinote
   ```
   This installs the `/hallucinote:*` skills and the bundled MCP server; uv builds
   the server's locked environment on first launch (pre-warmed at session start).
3. **Install the engine** for composing — clone this repo and editable-install it
   (see [Clone and install](#1-clone-and-install)). Until it ships to PyPI this local
   install is required for `build.py`. (This is the *composing* environment and is
   separate from the plugin's bridge server above — see the note in that section.)
4. Run `/hallucinote:ableton-mcp-install` once (the Ableton Remote Script — the
   one thing the plugin can't do for you), then `/hallucinote:song-new`.

**To develop the framework** (live-edit the `skills/` and server in this checkout),
load the plugin from your working tree instead of installing it — Claude Code,
started from your **songs repo**:

```bash
claude --plugin-dir /path/to/hallucinote
```

Skills appear as `/hallucinote:song-new`, …; uv launches the bundled server from
your checkout. (`--plugin-dir` is per-session — it doesn't persist across launches;
alias it if you use it often.) You still install the engine (step 3) and run the
Remote Script installer (step 4).

### 1. Clone and install 

This installs the **engine** (`hallucinote`) plus the `hallucinote_mcp` package into
your composing environment — `build.py`'s push path imports `hallucinote_mcp` as a
library. This is **separate from the plugin's MCP _bridge_ server**: the plugin bundles
its own copy of the server and runs it with uv (you don't manage that one). Same package,
two roles; keep this checkout on the same version as your installed plugin so they agree
(why, and how to check: [docs/engine-pin.md](docs/engine-pin.md)).

**macOS / Linux:**
```bash
git clone https://github.com/brookstalley/hallucinote.git
cd hallucinote
python -m venv .venv && source .venv/bin/activate
pip install -e . -e ./hallucinote_mcp
```

**Windows (PowerShell):**
```powershell
git clone https://github.com/brookstalley/hallucinote.git
cd hallucinote
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e . -e .\hallucinote_mcp
```

To enable development (mostly to enable running the test suite), add the `[dev]` extras (pytest, pytest-xdist, hypothesis) on either package:

```bash
pip install -e '.[dev]' -e './hallucinote_mcp[dev]'
```

### 2. Install the Ableton Remote Script

> ⚠️ **Quit Ableton Live before this step.** The installer refuses to copy into a running Live (on Windows the copy may fail silently because Live holds the old files locked).

Start Claude Code in this directory and run the install skill:

```bash
claude
```

> *"/ableton-mcp-install"*

The skill copies the Remote Script into Live's User Library, installs the HallucinoteAnalyzer device, and tells you how to enable the **Hallucinote** Control Surface in Live's settings. (The `hallucinote-mcp` server itself is provided by the plugin and launched via uv — the skill doesn't wire that up.) It has interactive checkpoints (which Live version to target, whether to overwrite) so don't try to run it headlessly.

### 3. Wire up Ableton, restart Claude Code

In Ableton Live's menu bar:

1. **Live → Preferences** (macOS) or **Options → Preferences** (Windows).
2. Open the **Tempo & MIDI** tab.
3. In any free **Control Surface** slot (the first column in the MIDI Ports table), open the dropdown and select **Hallucinote**.
4. Leave the **Input** and **Output** columns set to **None** — Hallucinote talks to Live through the Control Surface socket only.
5. Close Preferences.

Then **quit and reopen Claude Code** so the plugin's `hallucinote-mcp` server connects (uv builds its locked environment on first launch). Leave Ableton running.

### 4. Verify the bridge

From Claude Code:

> *"please get the current set's info from Ableton"*

You should get back tempo, signature, track counts, and master strip state from the current Live set.

## Try it

Setup is one-time. Day to day: open Live, start Claude Code in your **songs workspace** (a repo with a `hallucinote.toml` marker — see [`docs/quickstart.md`](docs/quickstart.md)), and talk.

### Compose a song

> *"Let's make a 2-minute punk rock song that condenses the chord progressions of Beethoven's 5th into those 2 minutes. Four parts: drums, bass, lead guitar, and vocals on a staccato synth. Call it punk-fate."*

The agent runs `/song-new punk-fate` to scaffold `songs/punk-fate/` in your workspace, picks instrument chains, writes a `build.py` against the generator library, builds `punk-fate-<branch>.db`, and pushes the result into Live through **fourteen ordered phases**:

```
tempo → meter → tracks → returns → scenes → clips → mix → routing → devices → device sidechain → envelopes → performed automation → arrangement → cues
```

When it finishes you have a fully-built session — named tracks, returns, clips, device chains, the mix, and any signal routing — ready to play. Iterate by talking — *"the bridge feels flat, lift the lead an octave there"* — and ask Claude to push again; re-runs are idempotent. (Already have a songs repo? Just name a song — *"load falling-walking into Live"* — and Claude builds + pushes it the same way.)

### Pull manual edits back

After tweaking faders, mutes, or sends in Live:

> *"pull my Ableton edits back into the DB"*

`/ableton-pull` diffs Ableton against the DB and writes the changes through the standard mutator path.

### Share a song with a collaborator

Commit `songs/<slug>/` to git and push. The collaborator clones the repo, installs Hallucinote, then runs `/ableton-push <slug>` — the skill probes Live's installed plugins, runs the compat check, and refuses-and-confirms before pushing if any third-party plugin in the song is missing on their machine. Full walkthrough plus the three portability cases in [`docs/collaboration.md`](docs/collaboration.md).

## Troubleshooting

The first five things that go wrong, in roughly the order people hit them.

### "Hallucinote MCP version mismatch" / "version handshake missing"

The MCP server (`hallucinote-mcp` running as a subprocess) and the Live-side Remote Script have diverged. After a `git pull` that touched `hallucinote_mcp/`, the Remote Script copy in Live's User Library is stale.

**Fix:** rerun `/ableton-mcp-install`, then **fully quit and reopen Ableton Live**. The `/mcp` reconnect command in Claude Code is not enough — Live caches Control Surface modules at startup, and the stale module lives inside Live's process. Quit Live (not just close the document), then reopen it.

To preview the drift without reinstalling, run `python -m hallucinote_mcp.cli preflight` and look at the `remote_script.candidates[*]` block. `matches_mcp_server: false` is the signal.

### `python: command not found`, or "Python 3.10+ required"

`python` is missing from your PATH, or it resolves to an older interpreter. The install skill checks this at Step 1.0 and refuses on <3.10.

**Fix:** use whichever invocation works in your shell — `python3`, `py -3`, or activate the virtualenv first (`source .venv/bin/activate` / `.\.venv\Scripts\Activate.ps1`). On Windows, if typing `python` opens the Microsoft Store, install from <https://python.org> or use `py -3`. Use the same invocation everywhere downstream (`pip`, `python -m hallucinote_mcp.cli preflight`) — picking different identifiers in different steps is a common silent bug.

### Claude Code in your project doesn't see the MCP server

`.mcp.json` is per-project. The install skill writes it into the current working directory; if you ran the skill from `~` or `/tmp`, that's where `.mcp.json` landed — not in your project.

**Fix:** `cd` into your project directory first, then rerun `/ableton-mcp-install`. The skill's Step 1.0 checks cwd for project markers (`.git`, `pyproject.toml`, etc.) and warns when none are present, but you can land in this trap on a project with no markers.

### Live's Preferences shows no "Hallucinote" in the Control Surface dropdown

The Remote Script didn't end up in the User Library Live is actually using. Common causes: Ableton was running during install (silent file lock on Windows); the wrong Live version's User Library got picked when multiple installs exist; you moved your User Library in Live's Preferences and the installer didn't know.

**Fix:** `python -m hallucinote_mcp.cli preflight` shows `user_library.candidates` and `live.installed_versions`. Confirm Live is closed, then rerun `/ableton-mcp-install` and explicitly pick the User Library matching the Live version you actually use. If your User Library has been relocated, give the install skill that path when it asks.

### `ableton_session(action='info')` hangs or returns "no connection"

Either Live isn't running, or you didn't assign the Hallucinote Control Surface slot in Step 3 above, or you assigned it but didn't quit/reopen Claude Code afterward so the MCP entry isn't loaded.

**Fix:** open Live; check **Preferences → Link, Tempo & MIDI** shows **Hallucinote** in a Control Surface slot; quit Claude Code and reopen it in the project directory.

## Learn more

| If you want to… | Read |
|---|---|
| Build your first song, step by step | [`docs/quickstart.md`](docs/quickstart.md) |
| See every command (skill) you can ask for | [`docs/skills.md`](docs/skills.md) |
| Understand the design philosophy | [`docs/VISION.md`](docs/VISION.md) |
| Write or edit a song's `build.py` | [`docs/song-authoring-conventions.md`](docs/song-authoring-conventions.md) |
| Share a song with a collaborator | [`docs/collaboration.md`](docs/collaboration.md) |
| Look something up / fix a problem | [`docs/faq.md`](docs/faq.md) |
| Contribute code | [`CONTRIBUTING.md`](CONTRIBUTING.md) |
| Get precise about an overloaded term | [`docs/terminology.md`](docs/terminology.md) |

## Project layout

```
src/hallucinote/      # composition library: db, generators, sync, capture
hallucinote_mcp/      # in-repo MCP server (13 unified Ableton tools)
skills/               # the /hallucinote:* Claude Code skills the plugin ships
tools/                # scaffolding + maintenance scripts
docs/                 # quickstart, skills, VISION, collaboration, FAQ, schemas, …
tests/                # platform-level tests
```

This is the **framework** repo. Your **songs live in a separate workspace repo** (a folder with a `hallucinote.toml` marker), not here — each song is a self-contained directory: `build.py`, `captured_session.json`, `tests/`, `decisions/`, `annotations/`, and a per-branch SQLite DB (gitignored). See [`docs/song-authoring-conventions.md`](docs/song-authoring-conventions.md) for the conventions and [`docs/snapshot-schema.md`](docs/snapshot-schema.md) for the snapshot format.

## Development

```bash
pytest -n auto --dist loadgroup            # full suite (requires [dev] extras)
python -m hallucinote_mcp.cli preflight    # inspect install state
```

`.mcp.json` is gitignored — its `command` field is per-environment. See `.mcp.json.example` for the canonical shape.

After editing anything under `hallucinote_mcp/actions/` or `hallucinote_mcp/handlers/`, rerun `/ableton-mcp-install` and fully quit + reopen Live — the Control Surface caches at startup, so Live's copy must be refreshed for changes to take effect.

## License

MIT. See [`LICENSE`](LICENSE).
