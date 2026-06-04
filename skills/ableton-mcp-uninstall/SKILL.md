---
name: ableton-mcp-uninstall
description: Cleanly remove Hallucinote MCP. Deletes the Remote Script from Ableton Live's User Library, removes the `hallucinote-mcp` entry from `.mcp.json` (or `~/.claude.json`), and tells the user the one-time Ableton Preferences click to undo. Use when the user wants to remove Hallucinote MCP, switch to a different MCP server, or troubleshoot by reinstalling from scratch.
---

# /ableton-mcp-uninstall

Symmetric counterpart to `/ableton-mcp-install`. Reverses every step using the same detection helpers.

## Step 1 — Preflight

Run from the project directory whose `.mcp.json` you want checked.

```bash
python -m hallucinote_mcp.cli preflight
```

(If the package has already been `pip uninstall`'d, this fails — see "Uninstall after pip uninstall" at the bottom.)

From the report:

- **`live.is_running`** — refuse if `true`; if `null`, ask the user to confirm Live is closed.
- **`user_library.candidates`** — every entry with `exists: true` is a place to check for `Remote Scripts/Hallucinote/`.
- **`mcp_configs.containing_entry`** — exact `{path, json_pointer}` list of every `hallucinote-mcp` registration (covers project `.mcp.json`, global `~/.claude.json` top-level, and `projects.<cwd>.mcpServers` from `claude mcp add`). No need to ask.
- **`mcp_configs.malformed`** — if non-empty, tell the user; we won't edit malformed files.

## Step 2 — Remove the Remote Script

For each User Library candidate that exists, check for `<User Library>/Remote Scripts/Hallucinote/`. List its contents before deleting; if you see anything beyond the expected `__init__.py` + `hallucinote_mcp/` tree (see `/ableton-mcp-install` Step 3c), ask before removing.

If the layout matches, delete:

```bash
# macOS / Linux
rm -rf "<User Library>/Remote Scripts/Hallucinote"
```

```powershell
# Windows
Remove-Item -Recurse -Force "<User Library>\Remote Scripts\Hallucinote"
```

Leave `Remote Scripts/` itself in place — it's standard Live infrastructure.

Multiple Live installs share one User Library by default; one delete covers all. The exception is a user who configured per-version User Libraries — ask.

## Step 3 — Remove the MCP server config entry

For each `{path, json_pointer}` in `mcp_configs.containing_entry`:

1. Read and parse the JSON at `path`.
2. Walk the json_pointer to reach the entry's parent dict; delete the final key. Examples:
   - `["mcpServers", "hallucinote-mcp"]` → delete `mcpServers["hallucinote-mcp"]`.
   - `["projects", "/path/to/proj", "mcpServers", "hallucinote-mcp"]` → delete that nested entry (the `claude mcp add` default scope).
3. Leave every other key untouched (especially the rest of `~/.claude.json`).
4. If the parent `mcpServers` map is now empty, leave it as `{}`.

### Atomic write

Write to `<config>.tmp`, then rename (`os.replace` / `mv` / `Move-Item -Force`). A partial write can corrupt `~/.claude.json` and lose project history.

If `mcp_configs.malformed` listed any of these files, don't edit — tell the user to fix the JSON first.

If Claude Code is open, suggest a restart so the deletion takes effect.

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

- **User Library moved**: the preflight candidates cover the common locations (including OneDrive redirection). If the user moved their User Library inside Live, ask for the path.
- **Multiple Live versions sharing a User Library**: one delete covers all.
- **Customized Remote Script files**: Step 2's sanity check catches this — ask before deletion.

## Uninstall after pip uninstall

If the package has already been `pip uninstall`'d, preflight fails. Manual cleanup:

1. **Remote Script** — delete `<User Library>/Remote Scripts/Hallucinote/`. User Library is typically:
   - macOS: `~/Music/Ableton/User Library`
   - Windows: `~/Documents/Ableton/User Library` or `~/OneDrive/Documents/Ableton/User Library`
   - Linux: `~/Ableton/User Library` (Wine / CrossOver only)

2. **MCP configs** — search for the `hallucinote-mcp` key in `<current project>/.mcp.json` and `~/.claude.json`. Edit each by hand (atomically — write to `.tmp`, then rename).

3. **Live Preferences click** — same as Step 4 above.
