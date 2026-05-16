# hallucinote

AI-assisted Ableton Live songwriting workflow. Songs live as Python build scripts on top of a SQLite source-of-truth that authors clips, mix state, devices, and automation envelopes via mutator + event-emit, then syncs to Ableton through the AbletonMCP server.

## Status

Pre-alpha. The DB-as-source-of-truth migration is complete (chunks 1-5): the legacy `gen_notes.py` script-per-song layout has been retired. Every clip flows through library generators → mutators → SQLite, with push planners emitting canonical MCP calls.

## Layout

```
src/hallucinote/             # the library
  db/                        # schema.sql + mutations.py + queries.py + events.py
  generators/                # pure musical primitives (notes + envelope generators)
  sync/                      # plan_push_* + apply_push_results — DB ↔ Ableton
  capture.py                 # one-shot snapshot of a live Ableton session

songs/
  falling-walking/
    falling-walking.md       # song concept, decisions, agent context
    build.py                 # builds the song into SQLite via the library
    captured_session.json    # initial Ableton snapshot used to seed the mix half

tests/                       # ~270 tests across schema / mutators / push / generators
docs/
  mcp-requirements.md        # gaps in AbletonMCP that block this workflow
```

## Usage

```
pip install -e .
python songs/falling-walking/build.py --reset   # rebuild the song's SQLite DB
python -m pytest                                # full library test suite
```

Pushing to Ableton goes through the `plan_push_*` planners in `hallucinote.sync.push`, then `apply_push_results` writes the projection (the `ableton_sessions` + `ableton_links` tables) back. Pull-side sync is a separate wave (not yet built).

## Dependencies

Talks to the [AbletonMCP](https://github.com/uisato/ableton-mcp-extended) server. Local dev assumes a sibling clone at `../ableton-mcp-extended/`. The `.mcp.json` in this repo points there.

## Vision

See `docs/VISION.md` and `docs/mcp-requirements.md` for the architecture and outstanding MCP capabilities.
