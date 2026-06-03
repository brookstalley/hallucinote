# Hallucinote

**An LLM-native music composition and production environment.**

You describe musical intent in plain language — *"write a stereotypical metal ballad using I–V–IV"*, *"make a 10-minute ambient soundscape in E major"* — and Claude composes the song against a SQLite source of truth, then pushes it into Ableton Live through an in-repo MCP server. Edits in Live pull back through the same path. Songs become forkable like git repos.

**New here?** Install (below), then follow the [**Quickstart**](docs/quickstart.md) to build your first song in about 10 minutes. Want the big picture first? See [`docs/VISION.md`](docs/VISION.md). For what shipped, see [`CHANGELOG.md`](CHANGELOG.md).

## What you can do

- **Compose a song from a prompt.** `/song-new <slug> [initial instructions]` scaffolds the directory using <slug> as folder name (this will also be used for various filenames); the agent writes a `build.py` against the generator library, materializes a SQLite DB, and pushes the result into a running Ableton Live set.
- **Iterate by talking.** *"raise the verse ghost snares"*, *"swap the chorus walk for a fill at bar 12"*, *"use a giant gated reverb on the chorus drums"* — the agent edits `build.py` (or the DB directly) and re-pushes. Re-runs are idempotent.
- **Pull manual edits back.** Tweak faders, mutes, sends, or notes in Live, then run `/ableton-pull` to fold the changes back into the song's DB.
- **Share songs across machines.** A song is a directory you commit to git. The compat check generates a `REQUIREMENTS.md` of third-party plugins the collaborator needs to install; see [`docs/collaboration.md`](docs/collaboration.md) for the round-trip.

### Limitations

Known limitations are listed at the bottom of [`CHANGELOG.md`](CHANGELOG.md#known-limitations).

## Requirements

- **Ableton Live 12** on **macOS or Windows**. 
- **Python 3.10 or newer.** On Windows, if `python` opens the Microsoft Store, use `py -3` everywhere `python` appears below.
- **Claude Code.** Install instructions: <https://claude.ai/code>.

## Install

Hallucinote has two halves: the **plugin** (the `/hallucinote:*` skills + the
`hallucinote-mcp` server, installed into Claude Code) and the **engine** (the
`hallucinote` Python package that `build.py` composes against). Your **songs**
live in their own git repo (a workspace with a `hallucinote.toml` marker), not
in this repo — see [`docs/VISION.md`](docs/VISION.md) ("a song is a git repo").

**To make music — install from a local checkout** (the path today; the plugin
and engine both live in this repo):

1. Clone + editable-install this repo (see [Clone and install](#1-clone-and-install) below) — that
   gives you the **engine** and the plugin's `skills/`.
2. In your **songs repo**, start Claude Code with the plugin loaded from your
   checkout:

   ```bash
   claude --plugin-dir /path/to/hallucinote
   ```

   Skills appear as `/hallucinote:song-new`, …; the `hallucinote-mcp` server
   auto-connects.
3. Run `/hallucinote:ableton-mcp-install` once (the Ableton Remote Script — the
   one thing the plugin can't do for you), then `/hallucinote:song-new`.

> **One-line install, once it's published.** After the first release (the plugin
> on the default branch + the engine on PyPI), setup collapses to:
> ```bash
> # in Claude Code:  /plugin marketplace add brookstalley/hallucinote
> #                  /plugin install hallucinote@hallucinote
> pip install 'hallucinote[live]'
> ```
> Until then, use the local-checkout path above (the plugin currently lives on
> `develop`, not the default branch a marketplace install reads).

### 1. Clone and install 

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

### 2. Install the Ableton Remote Script and MCP entry

> ⚠️ **Quit Ableton Live before this step.** The installer refuses to copy into a running Live (on Windows the copy may fail silently because Live holds the old files locked).

Start Claude Code in this directory and run the install skill:

```bash
claude
```

> *"/ableton-mcp-install"*

The skill copies the Remote Script into Live's User Library, writes `.mcp.json` for this project, and tells you how to enable the MCP plugin in Live's settings. It has interactive checkpoints (which Live version to target, whether to overwrite, project vs. global config) so don't try to run it headlessly.

### 3. Wire up Ableton, restart Claude Code

In Ableton Live's menu bar:

1. **Live → Preferences** (macOS) or **Options → Preferences** (Windows).
2. Open the **Tempo & MIDI** tab.
3. In any free **Control Surface** slot (the first column in the MIDI Ports table), open the dropdown and select **Hallucinote**.
4. Leave the **Input** and **Output** columns set to **None** — Hallucinote talks to Live through the Control Surface socket only.
5. Close Preferences.

Then **quit and reopen Claude Code in this repo** so it picks up the new `.mcp.json`. Leave Ableton running.

### 4. Verify the bridge

From Claude Code:

> *"please get the current set's info from Ableton"*

You should get back tempo, signature, track counts, and master strip state from the current Live set.

## Try it

Setup is one-time. Day to day: open Live, start Claude Code in this repo, talk.

### Load the example song

`songs/falling-walking/` is the canary song — a D-minor electronic piece used to gate every push planner and mutator change.

1. Open Ableton Live with an empty set (Hallucinote already selected as the Control Surface from setup).
2. In this repo, run `claude`.
3. Say:

> *"load falling-walking into Live"*

Claude builds `songs/falling-walking/falling-walking-<branch>.db` from `build.py`, then drives `/ableton-push` to materialize it through MCP — tempo → meter → tracks → returns → clips → mix → devices → envelopes → arrangement → cues. When it finishes you have a fully-built session in Live.

### Compose a new song

> *"Let's make a 2-minute punk rock song that condenses the chord progressions of Beethoven's 5th into those 2 minutes. Four parts: drums, bass, lead guitar, and vocals on a staccato synth. Call it punk-fate."*

The agent runs `/song-new punk-fate` to scaffold `songs/punk-fate/`, writes a `build.py` against the generator library, builds `punk-fate-<branch>.db`, and pushes the result into Live. Iterate by talking — *"the bridge feels flat, lift the lead an octave there"* — and ask Claude to push again.

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
hallucinote_mcp/      # in-repo MCP server (12 unified Ableton tools)
songs/<slug>/         # one directory per song: build.py + snapshot + tests
tools/                # scaffolding + maintenance scripts
docs/                 # quickstart, skills, VISION, collaboration, FAQ, schemas, terminology
tests/                # platform-level tests (per-song tests live under songs/<slug>/tests/)
```

Each song under `songs/` is self-contained — `build.py`, `captured_session.json`, `tests/`, `decisions/`, `annotations/`, and a per-branch SQLite DB (gitignored). See [`docs/song-authoring-conventions.md`](docs/song-authoring-conventions.md) for the conventions and [`docs/snapshot-schema.md`](docs/snapshot-schema.md) for the snapshot format.

## Development

```bash
pytest -n auto --dist loadgroup            # full suite (requires [dev] extras)
python -m hallucinote_mcp.cli preflight    # inspect install state
```

`.mcp.json` is gitignored — its `command` field is per-environment. See `.mcp.json.example` for the canonical shape.

After editing anything under `hallucinote_mcp/actions/` or `hallucinote_mcp/handlers/`, rerun `/ableton-mcp-install` and fully quit + reopen Live — the Control Surface caches at startup, so Live's copy must be refreshed for changes to take effect.

## License

MIT. See [`LICENSE`](LICENSE).
