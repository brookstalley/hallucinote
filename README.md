# hallucinote

LLM-native music composition and production environment. Songs live as Python build scripts on top of a SQLite source-of-truth that authors clips, mix state, devices, and automation envelopes via mutator + event-emit, then syncs bidirectionally to Ableton Live through an in-repo MCP server.

## Status

Pre-alpha. The DB-as-source-of-truth migration is complete (chunks 1-5). Pull-side sync landed in Wave 3 (mix-state, score-globals, cue-points). Wave M closed the v1.0 surface of the in-repo MCP server (`hallucinote-mcp`) — 10 unified tools with action dispatch, replacing the legacy AbletonMCP fork dependency. Every clip flows through library generators → mutators → SQLite, with push planners emitting canonical MCP calls and pull diffing Ableton state back through the same mutator path.

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

## Usage

```
pip install -e '.[dev]'
pip install -e 'hallucinote_mcp[dev]'
python songs/falling-walking/build.py --reset    # rebuild the song's SQLite DB
pytest -n auto --dist loadgroup                  # full suite (see .prawduct/.test-evidence.json for current count)
```

Pushing to Ableton goes through the `plan_push_*` planners in `hallucinote.sync.push`, then `apply_push_results` writes the projection (`ableton_sessions` + `ableton_links` tables) back. Pulling pulls Ableton state into the DB via the standard mutator path — diffs are realized as events. See the `/ableton-pull` skill for the agent surface.

## Dependencies

Talks to the in-repo `hallucinote-mcp` server (`hallucinote_mcp/`). No sibling clone or external fork is required.

The Claude Code MCP config (`.mcp.json`) is **gitignored** — its `command` field is per-environment (bare `hallucinote-mcp` when on PATH, absolute venv path when not), and contributors may want to add other MCP servers locally without sharing them with the team. See `.mcp.json.example` for the canonical entry shape.

To wire up the MCP server and the Ableton Remote Script in one step, open Claude Code in this repo and say:

> *"install the Hallucinote MCP plugin"*

Claude will locate and follow the install skill at `.claude/skills/ableton-install-mcp/SKILL.md`, which:

1. Copies the Remote Script into Live's User Library.
2. Writes `.mcp.json` with the right command shape for your environment.
3. Tells you the one Ableton Preferences click you do at the end.

Every contributor runs this once per clone (the MCP config is local, not committed).

## Vision

See `docs/VISION.md` for the product vision and `docs/mcp-tool-design.md` for the 10-tool MCP architecture rationale. `docs/mcp-requirements.md` tracks remaining capability gaps.
