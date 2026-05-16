# hallucinote

AI-assisted Ableton Live songwriting workflow. Houses song projects (concept docs + MIDI generators) and — eventually — a DB-backed intermediary for note-level authoring.

## Status

Pre-alpha. Currently a script-per-song layout with `gen_notes.py` files generating MIDI note arrays that are pushed into Ableton via the AbletonMCP server.

## Layout

```
songs/
  falling-walking/
    falling-walking.md   # song concept, decisions, agent context
    gen_notes.py         # source of truth for every MIDI clip
docs/
  mcp-requirements.md    # gaps in AbletonMCP that block this workflow
```

## Dependencies

Talks to the [AbletonMCP](https://github.com/uisato/ableton-mcp-extended) server. Local dev assumes a sibling clone at `../ableton-mcp-extended/`. The `.mcp.json` in this repo points there.

## Future direction

See `docs/mcp-requirements.md` § "Future direction — Database as MIDI source of truth" for the architecture this is heading toward.
