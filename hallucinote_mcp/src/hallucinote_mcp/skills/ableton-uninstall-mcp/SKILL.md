---
name: ableton-uninstall-mcp
description: Cleanly remove Hallucinote MCP. Deletes the Remote Script from Ableton Live's User Library, removes the `hallucinote-mcp` entry from `.mcp.json` (or `~/.claude.json`), and tells the user the one-time Ableton Preferences click to undo. Use when the user wants to remove Hallucinote MCP, switch to a different MCP server, or troubleshoot by reinstalling from scratch.
---

# /ableton-uninstall-mcp

Symmetric counterpart to `/ableton-install-mcp`. Reverses every step.

## Step 0 — Confirm and locate

Ask the user:
1. Is Ableton Live closed? (Don't delete files Live has open.)
2. Where is their User Library? (See `/ableton-install-mcp` Step 1 for defaults.)
3. Which MCP config did the install write to — `.mcp.json` in a project, or
   `~/.claude.json`? (If unsure, check both.)

## Step 1 — Remove the Remote Script directory

```
<User Library>/Remote Scripts/Hallucinote/
```

Delete this directory entirely. If it has the layout described in
`/ableton-install-mcp` Step 2 (`__init__.py` at the root plus a `hallucinote_mcp/`
subtree), the whole tree is ours — safe to remove.

**Sanity check before deletion**: list the contents. If you see anything you didn't
install (the user might have edited the Remote Script, dropped notes there, etc.),
ask before removing.

If `Remote Scripts/` is now empty, leave the parent in place — it's standard Live
infrastructure, not ours to clean up.

## Step 2 — Remove the MCP server config entry

Open the config file(s) and remove the `hallucinote-mcp` entry from `mcpServers`.
If the resulting `mcpServers` map is empty, you can leave it as `{}` — don't delete
the file.

For `.mcp.json` (project-local), the file is `.mcp.json` in the project root.
For the global config, it's `~/.claude.json` (the larger Claude Code config) — find
`mcpServers` inside it and remove just the `hallucinote-mcp` key.

If the user has the project open in Claude Code while you do this, suggest a Claude
Code restart so the deletion takes effect immediately.

## Step 3 — Tell the user the Ableton click

Print exactly:

```
hallucinote-mcp uninstalled.

One last step in Ableton Live (when you next open it):
  1. Preferences → Link, Tempo & MIDI.
  2. Find the Control Surface slot that has "Hallucinote" selected.
  3. Change it back to "None".

This is the only step Claude can't automate — Live writes the preference to its
own config file in a binary-ish format we don't want to touch.
```

## Edge cases

- **`pip uninstall hallucinote-mcp` was already run**: the package is gone but the
  Remote Script is still in Live's User Library. That's fine — this skill removes it
  anyway. The pip uninstall just removes the server side.
- **The user wants to keep the MCP config but remove the Remote Script** (e.g., they
  want to switch which Live install hosts it): support this with a follow-up question
  before deleting the config entry. The default is full uninstall.
- **Permission denied** on the User Library: as with install, tell the user — don't
  escalate.
