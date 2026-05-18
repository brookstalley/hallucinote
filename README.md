# Hallucinote

**An LLM-native music composition and production environment.**

Songs live as Python on top of a SQLite source of truth. An LLM agent (Claude Code) composes by calling library generators and mutators, then pushes the result into Ableton Live through an in-repo MCP server. Manual edits in Live pull back through the same path. The DB stores notes, mix state, devices, automation envelopes, and arrangement; Live is the rendering engine.

The goal is to move composers up the ladder of abstraction. Instead of dragging clips and dialing knobs, you describe musical intent ("a bassline weaving between two drum parts at 95 BPM") and the LLM builds it end-to-end against the DB. Songs become forkable like git repos — branch a chorus variant, A/B against main, throw it away.

## Quick Start

### 1. Install the package and the MCP server

```bash
git clone https://github.com/brookstalley/hallucinote.git
cd hallucinote
pip install -e '.[dev]'
pip install -e 'hallucinote_mcp[dev]'
```

### 2. Wire up Ableton + Claude Code

Open this repo in Claude Code, then say:

> *"install the Hallucinote MCP plugin"*

Claude follows the `/ableton-install-mcp` skill, which:

1. Copies the Remote Script into Live's User Library.
2. Writes `.mcp.json` for this project.
3. Tells you the one Ableton Preferences click you need to do.

After it finishes:

- **Exit Claude Code and restart it in this repo.** It needs to load the new `.mcp.json`.
- **Open Ableton Live**, go to *Preferences → Link, Tempo & MIDI*, and select **Hallucinote** in any free Control Surface slot (Input and Output stay as None).

### 3. Build the example song into the DB

```bash
python songs/falling-walking/build.py --reset
```

This rebuilds `songs/falling-walking/falling-walking.db` from scratch — the SQLite source of truth for the example song.

### 4. Push the song into a fresh Ableton set

In Claude Code (with Live open and the Hallucinote Control Surface loaded), say:

> *"push falling-walking into Ableton"*

Claude follows the `/ableton-push` skill, driving ten ordered phases (tempo → meter → tracks → returns → clips → mix → devices → envelopes → arrangement → cues) through MCP into Live. When it finishes you have a fully-built session.

### 5. (Optional) Pull manual edits back

If you tweak faders, mute toggles, or sends in Live and want them captured back to the DB, ask Claude:

> *"pull my Ableton edits back into the DB"*

This invokes `/ableton-pull`, which diffs Ableton against the DB and writes the changes through the standard mutator path — events fall out naturally.

## Status

Pre-alpha. The DB-as-source-of-truth migration is complete. Pull-side sync covers mix state, score globals, cue points, device chain structure, arrangement-clip placements, session-view clip slots, note pull via stable-ID read, and device-parameter values. Wave M closed the v1.0 surface of the in-repo MCP server (`hallucinote-mcp`) — 10 unified action-dispatch tools, replacing the legacy AbletonMCP fork dependency. Outstanding gaps are tracked in `docs/mcp-requirements.md` and `.prawduct/backlog.md`.

## Layout

```
src/hallucinote/             # the composition library
  db/                        # schema.sql + mutations.py + queries.py + events.py
  generators/                # pure musical primitives (notes + envelope generators)
  sync/                      # plan_push_* + apply_push_results + pull — DB ↔ Ableton
  capture.py                 # one-shot snapshot of a live Ableton session

hallucinote_mcp/             # the in-repo MCP server (v1.0 surface)
  src/hallucinote_mcp/       # 10 unified tools, action dispatch, install skill
  tests/                     # MCP-plugin tests

songs/
  falling-walking/
    falling-walking.md       # song concept, decisions, agent context
    build.py                 # builds the song into SQLite via the library
    captured_session.json    # initial Ableton snapshot used to seed the mix half
    tests/                   # song-specific tests (build smoke, snapshot replay)

tests/                       # platform/library tests
docs/
  VISION.md                  # product vision
  mcp-tool-design.md         # 10-tool architecture rationale
  mcp-requirements.md        # outstanding MCP capabilities
```

## Architecture in one paragraph

Every state change goes through mutators in `db/mutations.py`, which write the row AND emit an event in the same transaction. The DB is materialized state; the event log is the audit trail (and the seed for a future event-store flip). Push is plan-based: `plan_push_*` planners return `PushPlan` / `ToolCall` objects; Claude executes the plan through MCP and feeds results back via `apply_push_results`. Pull is symmetric — `plan_pull_*` probes Live, diffs against the DB, and writes through the same mutators. Generators are pure functions that emit note arrays with semantic tags (ghost, downbeat, section role) — they have no DB or MCP coupling.

## Development

```bash
pytest -n auto --dist loadgroup    # full suite; current count in .prawduct/.test-evidence.json
python -m hallucinote_mcp.cli preflight    # check install state before /ableton-install-mcp
```

The Claude Code MCP config (`.mcp.json`) is **gitignored** — its `command` field is per-environment (bare `hallucinote-mcp` when on PATH, absolute venv path when not), and contributors may want to add other MCP servers locally without sharing them with the team. See `.mcp.json.example` for the canonical entry shape.

After editing any `actions/*.py` or `handlers/*.py` in `hallucinote_mcp/`, rerun `/ableton-install-mcp` and fully quit + reopen Live — the Control Surface caches at startup, so the Live-side copy must be refreshed for changes to take effect.

## Vision

See `docs/VISION.md` for the product vision, `docs/mcp-tool-design.md` for the 10-tool MCP architecture rationale, and `docs/mcp-requirements.md` for remaining capability gaps.
