# hallucinote-mcp

Ableton Live MCP server with **11 unified tools** and action dispatch — designed for
agents that need broad Ableton control without paying the context cost of a 50-tool
surface.

This package ships as part of the [Hallucinote](https://github.com/brookstalley/hallucinote)
composition environment but can also be used standalone by any MCP-capable agent
that wants structured access to a running Ableton Live set. Note: the
`ableton_annotation` tool requires the parent `hallucinote` package on the
server-side Python path (it reads/writes a per-song SQLite DB). The other ten
tools work standalone.

## Why so few tools?

Empirical research (Anthropic, Speakeasy, Copilot) shows model effectiveness degrades
sharply past ~25 MCP tools and collapses past ~50. Most narrow setters can be
consolidated: `ableton_track(action='set_property', property='volume', value=0.7)`
replaces a separate `set_track_volume` tool. The architectural rationale lives in
the parent repo at [`docs/mcp-tool-design.md`](../docs/mcp-tool-design.md).

## Install

`hallucinote-mcp` is not published to PyPI. Install it from the Hallucinote
repository as an editable package:

```bash
git clone https://github.com/brookstalley/hallucinote.git
cd hallucinote
pip install -e ./hallucinote_mcp
```

Then run the install skill from Claude Code to copy the Remote Script into Ableton
Live's User Library and write `.mcp.json` for your project:

```
/ableton-mcp-install
```

Uninstall is symmetric: `/ableton-mcp-uninstall`.

See the [main README](../README.md) for full setup including wiring Hallucinote into
Live's Control Surface slot.

## The unified tools

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
| `ableton_annotation` | Composer-intent annotations (per-song DB; requires `hallucinote`) |

Every tool answers `action='help'` with a structured menu — required / optional
params, examples, tips — generated from the shared schema. Errors carry recovery
hints: valid action list, missing-param list, an example, a `hint` string.

In addition to the tools, the server exposes **11 resources** for low-context-cost
reads (`ableton://session/snapshot`, `ableton://browser/*`, `ableton://plugins/installed`,
`ableton://reference/*`, `ableton://guides/*`). Multi-step workflows live as Claude
Code skills (`.claude/skills/` in the parent repo) — `/song-new`, `/song-pick-instruments`,
`/track-new-with-instrument`, `/return-new`, `/mix-sidechain`, `/clip-humanize`,
`/pattern-compose` — so they're assistant-callable, not just user-facing slash commands.

## Development

```bash
pip install -e .[dev]
pytest
```

The package is split so the Remote Script side (which runs inside Ableton Live's
embedded Python 3.7+ and has no access to PyPI) only depends on the standard
library. The FastMCP server side (which runs as a normal Python process) imports
`mcp`. See `hallucinote_mcp/install_paths.py` for the file partition.

## License

MIT. See [`LICENSE`](LICENSE).
