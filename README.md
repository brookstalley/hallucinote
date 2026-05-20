# Hallucinote

**An LLM-native music composition and production environment.**

You describe musical intent in plain language — *"write a stereotypical metal ballad using I–V–IV"*, *"make a 10-minute ambient soundscape in E major"* — and Claude composes the song against a SQLite source of truth, then pushes it into Ableton Live through an in-repo MCP server. Edits in Live pull back through the same path. The DB holds notes, mix, devices, automation, and arrangement; Live is the rendering engine. Songs become forkable like git repos.

See [`docs/VISION.md`](docs/VISION.md) for the full bet.

> **Status:** Pre-alpha. The push/pull round-trip works for the v1 surface. Outstanding capability gaps live in [`docs/mcp-requirements.md`](docs/mcp-requirements.md) and `.prawduct/backlog.md`.

## Quick start

You need:

- **Ableton Live 11 or 12** on **macOS or Windows**. Linux isn't supported for v1 — Ableton doesn't ship a Linux build, and Hallucinote isn't tested under Wine / CrossOver. The install skill will warn and ask before proceeding if you try.
- **Python 3.10 or newer.** On Windows, if `python` opens the Microsoft Store, use `py -3` everywhere `python` appears below.
- **Claude Code.** Install instructions: <https://claude.ai/code>.

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

Both packages must be installed even when driving from Claude Code: Claude Code spawns `hallucinote-mcp` as a separate subprocess, and the song build scripts import the `hallucinote` library directly.

**If you want to run the test suite**, add the `[dev]` extras (pytest, pytest-xdist, hypothesis) on either package:

```bash
pip install -e '.[dev]' -e './hallucinote_mcp[dev]'
```

The `[dev]` extras are test-only — the runtime doesn't need them.

### 2. Install the Ableton Remote Script + MCP entry

**Quit Ableton Live first** — the installer refuses to copy into a running Live (on Windows the copy may even fail silently because Live has the old files locked).

Then start Claude Code in this directory and ask it to run the install skill:

```bash
claude
```

> *"run /ableton-install-mcp"*

The skill copies the Remote Script into Live's User Library, writes `.mcp.json` for this project, and tells you the one Ableton click left to do. It has interactive checkpoints (which Live version to target, whether to overwrite, project vs. global config) so don't try to run it headlessly.

### 3. Wire up Ableton, restart Claude Code

In Ableton Live's menu bar:

1. **Live → Preferences** (macOS) or **Options → Preferences** (Windows).
2. Open the **Link, Tempo & MIDI** tab.
3. In any free **Control Surface** slot (the first column in the MIDI Ports table), open the dropdown and select **Hallucinote**.
4. Leave the **Input** and **Output** columns set to **None** — Hallucinote doesn't use MIDI in/out; it talks to Live through the Control Surface socket only.
5. Close Preferences.

Then **quit and reopen Claude Code in this repo** so it picks up the new `.mcp.json`.

Verify the bridge from Claude Code:

> *"call ableton_session with action=info"*

You should get back tempo, signature, track counts, and master strip state from the current Live set.

## Using it

Setup is one-time. Day to day: open Live, start Claude Code in this repo, talk.

### Load the example song into Live

1. Open Ableton Live (Hallucinote already selected as Control Surface from setup).
2. In this repo, run `claude`.
3. Say:

> *"load falling-walking into Live"*

Claude builds `songs/falling-walking/falling-walking.db` from its `build.py`, then drives `/ableton-push` to materialize it through MCP — tempo → meter → tracks → returns → clips → mix → devices → envelopes → arrangement → cues. When it finishes you have a fully-built session in Live.

### Compose a new song from a prompt

> *"Let's make a 2-minute punk rock song that condenses the chord progressions of Beethoven's 5th into those 2 minutes. Four parts: drums, bass, lead guitar, and vocals on synth pad. Make the vocal melody consistent with the harmonic structure. Make the whole thing super punk. Call it punk-fate."*

Claude scaffolds `songs/punk-fate/`, writes a `build.py` against the library's generators, builds `punk-fate.db`, and pushes the result into Live. Iterate by talking — *"the bridge feels flat, lift the lead an octave there"*, *"swap the chorus walk for a fill at bar 12"* — and ask Claude to push again.

### Pull manual edits back

After tweaking faders, mutes, or sends in Live:

> *"pull my Ableton edits back into the DB"*

`/ableton-pull` diffs Ableton against the DB and writes the changes through the standard mutator path; events fall out naturally.

## Troubleshooting

The first five things that go wrong, in roughly the order people hit them.

### "Hallucinote MCP version mismatch" / "version handshake missing"

The MCP server (`hallucinote-mcp` running as a subprocess) and the Live-side Remote Script have diverged. After a `git pull` that touched `hallucinote_mcp/`, the Remote Script copy in Live's User Library is stale.

**Fix:** rerun `/ableton-install-mcp`, then **fully quit and reopen Ableton Live**. The `/mcp` reconnect command in Claude Code is not enough — Live caches Control Surface modules at startup, and the stale module lives inside Live's process. Quit Live (not just close the document), then reopen it.

To preview the drift without reinstalling, run `python -m hallucinote_mcp.cli preflight` and look at the `remote_script.candidates[*]` block. `matches_mcp_server: false` is the signal.

### `python: command not found`, or "Python 3.10+ required"

`python` is missing from your PATH, or it resolves to an older interpreter. The install skill checks this at Step 1.0 and refuses on <3.10.

**Fix:** use whichever invocation works in your shell — `python3`, `py -3`, or activate the virtualenv first (`source .venv/bin/activate` / `.\.venv\Scripts\Activate.ps1`). On Windows, if typing `python` opens the Microsoft Store, install from <https://python.org> or use `py -3`. Use the same invocation everywhere downstream (`pip`, `python -m hallucinote_mcp.cli preflight`) — picking different identifiers in different steps is a common silent bug.

### Claude Code in your project doesn't see the MCP server

`.mcp.json` is per-project. The install skill writes it into the current working directory; if you ran the skill from `~` or `/tmp`, that's where `.mcp.json` landed — not in your project.

**Fix:** `cd` into your project directory first, then rerun `/ableton-install-mcp`. The skill's Step 1.0 checks cwd for project markers (`.git`, `pyproject.toml`, etc.) and warns when none are present, but you can land in this trap on a project with no markers.

### Live's Preferences shows no "Hallucinote" in the Control Surface dropdown

The Remote Script didn't end up in the User Library Live is actually using. Common causes: Ableton was running during install (silent file lock on Windows); the wrong Live version's User Library got picked when multiple installs exist; you moved your User Library in Live's Preferences and the installer didn't know.

**Fix:** `python -m hallucinote_mcp.cli preflight` shows `user_library.candidates` and `live.installed_versions`. Confirm Live is closed, then rerun `/ableton-install-mcp` and explicitly pick the User Library matching the Live version you actually use. If your User Library has been relocated, give the install skill that path when it asks.

### `ableton_session(action='info')` hangs or returns "no connection"

Either Live isn't running, or you didn't assign the Hallucinote Control Surface slot in Step 3 above, or you assigned it but didn't quit/reopen Claude Code afterward so the MCP entry isn't loaded.

**Fix:** open Live; check **Preferences → Link, Tempo & MIDI** shows **Hallucinote** in a Control Surface slot; quit Claude Code and reopen it in the project directory.

## Layout

```
src/hallucinote/             # composition library: db, generators, sync, capture
hallucinote_mcp/             # in-repo MCP server (10 unified action tools)
songs/falling-walking/       # example song: build.py + .db + tests
docs/                        # VISION, mcp-tool-design, mcp-requirements
```

## Architecture in one paragraph

Every state change goes through mutators in `db/mutations.py`, which write the row AND emit an event in the same transaction — the DB is materialized state, the event log is the audit trail. Push is plan-based: `plan_push_*` returns `PushPlan` / `ToolCall` objects; Claude executes the plan through MCP and feeds results back via `apply_push_results`. Pull is symmetric. Generators are pure functions that emit note arrays with semantic tags (ghost, downbeat, section role) — no DB or MCP coupling.

## Development

```bash
pytest -n auto --dist loadgroup            # full suite (requires [dev] extras)
python -m hallucinote_mcp.cli preflight    # inspect install state
```

`.mcp.json` is gitignored — its `command` field is per-environment. See `.mcp.json.example` for the canonical entry shape.

After editing anything under `hallucinote_mcp/actions/` or `hallucinote_mcp/handlers/`, rerun `/ableton-install-mcp` and fully quit + reopen Live — the Control Surface caches at startup, so Live's copy must be refreshed for changes to take effect.
