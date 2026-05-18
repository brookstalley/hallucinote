# hallucinote-mcp

Ableton Live MCP server with **10 unified tools** and action dispatch — designed for
agents that need broad Ableton control without paying the context cost of a 50-tool
surface.

## Why ten?

Empirical research (Anthropic, Speakeasy, Copilot) shows model effectiveness degrades
sharply past ~25 MCP tools and collapses past ~50. Most narrow setters can be
consolidated: `ableton_track(action='set_property', property='volume', value=0.7)`
replaces a separate `set_track_volume` tool. The full architectural rationale lives
in the parent repo at `docs/mcp-tool-design.md`.

## Status

**Active scaffold.** Wave M-0 lays the package, dispatcher, wire protocol, and
install skills. Tool actions land chunk-by-chunk in M-1 through M-7. See
`.prawduct/artifacts/build-plan.md` in the parent repo for the chunk schedule.

## Install

```bash
pip install hallucinote-mcp
```

Then open Claude Code in any project and run the install skill — it locates Ableton
Live's User Library, copies the Remote Script into place, writes the MCP config,
and tells you the one-line Ableton Preferences click:

```
/ableton-install-mcp
```

The skill body lives at `.claude/skills/ableton-install-mcp/SKILL.md` in the
Hallucinote repo. Claude Code discovers it automatically when the repo is
checked out; no manual copy step needed.

Uninstall is symmetric: `/ableton-uninstall-mcp`.

## The ten tools

| Tool | Scope |
|---|---|
| `ableton_session` | Global state, master, transport, view, tempo, signature, snapshot |
| `ableton_track` | Tracks: lifecycle, mixer state, sends |
| `ableton_return` | Return tracks |
| `ableton_clip` | Session + arrangement clips (lifecycle, set_property, replace_notes) |
| `ableton_note` | Within-clip note operations |
| `ableton_device` | Devices on tracks / returns |
| `ableton_automation` | Envelopes across seven target families |
| `ableton_arrangement` | Arrangement layout + cue points |
| `ableton_scene` | Session-view scenes |
| `ableton_browser` | Instruments, effects, plugins |

Every tool answers `action='help'` with a structured menu — required / optional
params, examples, tips — generated from the shared schema. Errors carry recovery
hints: valid action list, missing-param list, an example, a `hint` string.

## Development

```bash
pip install -e .[dev]
pytest
```

The package is split so the Remote Script side (which runs inside Ableton Live's
embedded Python 3.7+ and has no access to PyPI) only depends on the standard
library. The FastMCP server side (which runs as a normal Python process) imports
`mcp`. See `hallucinote_mcp/install_paths.py` for the file partition.

## Thanks

Inspired by [AbletonMCP](https://github.com/ahujasid/ableton-mcp) and
[ableton-mcp-extended](https://github.com/uisato/ableton-mcp-extended) — they proved
the concept that an MCP can usefully drive Ableton Live. `hallucinote-mcp` is a
ground-up reimplementation with a different tool surface (10 unified instead of
~50 narrow) and a declarative-first dispatcher; no source code is carried over.

## License

MIT. See `LICENSE`.
