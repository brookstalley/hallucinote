# Hallucinote

**An LLM-native music composition and production environment.**

You describe musical intent in plain language — *"write a stereotypical metal ballad using I–V–IV"*, *"make a 10-minute ambient soundscape in E major"* — and Claude composes the song against a SQLite source of truth, then pushes it into Ableton Live through an in-repo MCP server. Edits in Live pull back through the same path. The DB holds notes, mix, devices, automation, and arrangement; Live is the rendering engine. Songs become forkable like git repos.

See [`docs/VISION.md`](docs/VISION.md) for the full bet.

> **Status:** Pre-alpha. The push/pull round-trip works for the v1 surface. Outstanding capability gaps live in [`docs/mcp-requirements.md`](docs/mcp-requirements.md) and `.prawduct/backlog.md`.

## Quick start

You need Ableton Live (11 or 12), Python 3.11+, and Claude Code on **macOS or Windows**. Linux is not supported for v1 — Ableton doesn't ship a native Linux build, and Hallucinote isn't tested under Wine / CrossOver (the install skill will warn and ask before proceeding if you try).

### 1. Clone and install

```bash
git clone https://github.com/brookstalley/hallucinote.git
cd hallucinote
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]' -e 'hallucinote_mcp[dev]'
```

The installs aren't optional even when driving from Claude Code: Claude Code spawns `hallucinote-mcp` as a separate subprocess, and the song build scripts import the `hallucinote` library directly.

### 2. Install the Ableton Remote Script + MCP entry

**Quit Ableton Live first** (the installer refuses to copy into a running Live). Then start Claude Code in this directory and ask it to run the install skill:

```bash
claude
```

> *"run /ableton-install-mcp"*

The skill copies the Remote Script into Live's User Library, writes `.mcp.json` for this project, and tells you the one Ableton click left to do. It has interactive checkpoints (which Live version to target, whether to overwrite, project vs. global config) so don't try to run it headlessly.

### 3. Wire up Ableton, restart Claude Code

- **Open Ableton Live** → *Preferences → Link, Tempo & MIDI* → in any free **Control Surface** slot, select **Hallucinote**. Leave Input and Output as None.
- **Quit and reopen Claude Code in this repo** so it picks up the new `.mcp.json`.

Verify the bridge from Claude Code:

> *"call ableton_session with action=info"*

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
pytest -n auto --dist loadgroup            # full suite
python -m hallucinote_mcp.cli preflight    # inspect install state
```

`.mcp.json` is gitignored — its `command` field is per-environment. See `.mcp.json.example` for the canonical entry shape.

After editing anything under `hallucinote_mcp/actions/` or `hallucinote_mcp/handlers/`, rerun `/ableton-install-mcp` and fully quit + reopen Live — the Control Surface caches at startup, so Live's copy must be refreshed for changes to take effect.
