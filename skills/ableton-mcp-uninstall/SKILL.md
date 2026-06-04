---
name: ableton-mcp-uninstall
description: Cleanly remove Hallucinote MCP. Deletes the Remote Script and the HallucinoteAnalyzer device from Ableton Live's User Library, removes every `hallucinote-mcp` entry from `.mcp.json` / `~/.claude.json`, and tells the user the one-time Ableton Preferences click to undo. Use when the user wants to remove Hallucinote MCP, switch to a different MCP server, or troubleshoot by reinstalling from scratch.
---

# /ableton-mcp-uninstall

Symmetric counterpart to `/ableton-mcp-install`. Reverses every step through the
same tested, atomic CLI subcommands — `uninstall-remote-script`,
`uninstall-analyzer`, `remove-mcp-config`. The skill orchestrates; it never
hand-authors `rm`/`Remove-Item` or JSON edits.

## Step 1 — Preflight

```bash
python -m hallucinote_mcp.cli preflight
```

(If the package was already `pip uninstall`'d, this fails — see the bottom section.)

From the report:

- **`live.is_running`** — `true` → refuse; `null` → ask the user to confirm Live is fully quit.
- **`user_library.candidates`** — every entry with `exists: true` is a place to remove from.
- **`mcp_configs.containing_entry`** — every `hallucinote-mcp` registration (project `.mcp.json`, global `~/.claude.json` top-level, and `projects.<cwd>.mcpServers`); `remove-mcp-config` clears them all.
- **`mcp_configs.malformed`** — if non-empty, tell the user; the CLI refuses to edit malformed files.

## Step 2 — Remove the Remote Script (and the analyzer device)

For each User Library candidate that exists, remove both:

```bash
python -m hallucinote_mcp.cli uninstall-remote-script --user-library "<User Library>"
python -m hallucinote_mcp.cli uninstall-analyzer      --user-library "<User Library>"
```

Each prints `{"ok": true, "removed": true|false, "path": ...}` — `removed: false`
just means it wasn't there (idempotent). `uninstall-remote-script` removes the
whole `Remote Scripts/Hallucinote/` directory but leaves `Remote Scripts/` itself
(standard Live infrastructure). Multiple Live installs share one User Library by
default, so one pass covers all; ask only if the user configured per-version
libraries.

If the user customized the analyzer device via the Max GUI and wants to keep it,
skip `uninstall-analyzer`.

## Step 3 — Remove the MCP server config entries

```bash
python -m hallucinote_mcp.cli remove-mcp-config
```

(Add `--cwd "<project dir>"` if the project whose `.mcp.json` to scan isn't the
current directory.) It deletes `hallucinote-mcp` from every scope preflight found —
project `.mcp.json`, global top-level, and the per-project `claude mcp add` scope —
atomically, leaving all other servers and keys untouched, and refusing any
malformed file. Prints `{"ok": true, "removed": [ ... ]}`.

If `hallucinote-mcp` is **plugin-provided** (no config-file entry — `remove-mcp-config`
reports `removed: []`), there's nothing to delete here: to stop the plugin from
providing it, the user disables/uninstalls the plugin via `/plugin`, not this skill.

If Claude Code is open, suggest a restart (or `/mcp`) so the change takes effect.

## Step 4 — Tell the user the Ableton click

Print verbatim:

```
hallucinote-mcp uninstalled.

One last step in Ableton Live (when you next open it):
  1. Preferences → Link, Tempo & MIDI.
  2. Find the Control Surface slot that has "Hallucinote" selected.
  3. Change it back to "None".
```

## Edge cases

- **User Library moved**: preflight's candidates cover the common locations (incl. OneDrive redirection). If moved inside Live, ask for the path.
- **Multiple Live versions sharing a User Library**: one removal covers all.
- **Malformed config**: `remove-mcp-config` refuses to edit it — have the user fix the JSON first.

## Uninstall after pip uninstall

If the package was already `pip uninstall`'d, preflight (and the CLI) can't run.
Manual cleanup:

1. **Remote Script + analyzer** — delete `<User Library>/Remote Scripts/Hallucinote/`
   and `<User Library>/Presets/Audio Effects/Max Audio Effect/HallucinoteAnalyzer.amxd`.
   User Library is typically:
   - macOS: `~/Music/Ableton/User Library`
   - Windows: `~/Documents/Ableton/User Library` or `~/OneDrive/Documents/Ableton/User Library`
   - Linux: `~/Ableton/User Library` (Wine / CrossOver only)
2. **MCP configs** — remove the `hallucinote-mcp` key from `<project>/.mcp.json` and
   `~/.claude.json` (top-level and any `projects.<cwd>.mcpServers`). Edit atomically
   (write to `.tmp`, then rename).
3. **Live Preferences click** — same as Step 4 above.
