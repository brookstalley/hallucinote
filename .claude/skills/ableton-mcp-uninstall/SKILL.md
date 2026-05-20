---
name: ableton-mcp-uninstall
description: Cleanly remove Hallucinote MCP. Deletes the Remote Script from Ableton Live's User Library, removes the `hallucinote-mcp` entry from `.mcp.json` (or `~/.claude.json`), and tells the user the one-time Ableton Preferences click to undo. Use when the user wants to remove Hallucinote MCP, switch to a different MCP server, or troubleshoot by reinstalling from scratch.
---

# /ableton-mcp-uninstall

Symmetric counterpart to `/ableton-mcp-install`. Reverses every step using the
same detection helpers.

## Step 1 — Preflight

Run from the project directory whose `.mcp.json` you want checked —
preflight resolves `mcp_configs.local_path` from `cwd`.

```bash
python -m hallucinote_mcp.cli preflight
```

(If the `hallucinote_mcp` package has already been `pip uninstall`'d, this
will fail — that's fine. The Remote Script and MCP configs may still be on
disk; see "Uninstall after pip uninstall" at the bottom for the manual path.)

From the report:

- **`live.is_running`** — refuse to proceed if `true` (Live has the files
  open). If `null` (unknown), ask the user to confirm Live is closed.
- **`user_library.candidates`** — every candidate where `exists: true` is
  a place to check for a `Remote Scripts/Hallucinote/` directory. Most
  users have one; multi-Live-version users may have several.
- **`mcp_configs.containing_entry`** — exact list of
  `{path, json_pointer}` objects locating every `hallucinote-mcp`
  registration. Covers the three scopes: project-local `.mcp.json`,
  global top-level `~/.claude.json`, and the per-project
  `projects.<cwd>.mcpServers` scope that `claude mcp add` writes by
  default. No need to ask the user; this is the truth.
- **`mcp_configs.malformed`** — if non-empty, tell the user. We won't
  edit malformed files — they need to fix the JSON first or delete the
  config entirely.

## Step 2 — Remove the Remote Script directory

For each User Library candidate that exists, check for:
```
<User Library>/Remote Scripts/Hallucinote/
```

If found, **list its contents before deleting** and compare against the
expected layout (see `/ableton-mcp-install` Step 3c). The expected tree
is `__init__.py` at the root plus a `hallucinote_mcp/` subtree. If you
see anything else — the user might have edited files or dropped notes
there — ask before removing.

If the layout matches expectations, delete the directory:

**macOS / Linux:**
```bash
rm -rf "<User Library>/Remote Scripts/Hallucinote"
```

**Windows (PowerShell):**
```powershell
Remove-Item -Recurse -Force "<User Library>\Remote Scripts\Hallucinote"
```

If `Remote Scripts/` becomes empty after this, leave the parent in place —
it's standard Live infrastructure, not ours to clean up.

If the user has multiple Live installs (the preflight `live.installed_versions`
list had multiple entries), they share one User Library by default, so one
delete covers all of them. The exception is a user who has explicitly
configured a different User Library per Live version — ask if they did this.

## Step 3 — Remove the MCP server config entry

For each entry in `mcp_configs.containing_entry` (each is an
`{path, json_pointer}` object):

1. Read and parse the JSON at `path`.
2. Walk `json_pointer` to reach the entry's parent dict, then delete the
   final key. Example pointers:
   - `["mcpServers", "hallucinote-mcp"]` — delete `mcpServers["hallucinote-mcp"]`.
   - `["projects", "/path/to/proj", "mcpServers", "hallucinote-mcp"]` —
     delete `projects["/path/to/proj"]["mcpServers"]["hallucinote-mcp"]`
     (the `claude mcp add` default scope).
3. Leave every other key untouched (especially the rest of
   `~/.claude.json`, which holds Claude Code's project history).
4. If the parent `mcpServers` map is now empty, leave it as `{}` — don't
   delete the file or the key.

### Atomic write

JSON config files need atomic writes — a partial write can corrupt
`~/.claude.json` and lose project history. Pattern:

1. Compute the new JSON.
2. Write to `<config>.tmp` in the same directory.
3. Rename `<config>.tmp` → `<config>` (`os.replace`, `mv`, or
   `Move-Item -Force`).

If `mcp_configs.malformed` listed any of these files, don't attempt the
edit — surface the file path and tell the user to fix the JSON first.

If the user has Claude Code open while you do this, suggest a restart so
the deletion takes effect immediately.

## Step 4 — Tell the user the Ableton click

Print verbatim:

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

- **Permission denied** on the User Library or config: tell the user;
  don't escalate via `sudo` / elevated shell.
- **User wants to keep the MCP config but remove the Remote Script**
  (e.g., switching which Live install hosts it): do Step 2 only, skip
  Step 3. Ask before assuming.
- **Customized Remote Script files**: the sanity-check in Step 2 catches
  this. Ask the user — they may want to back up before deletion.
- **Malformed config file**: refuse to edit. Step 1 already surfaced
  this; the user needs to fix or delete.
- **Multiple User Library candidates with the Remote Script**: rare, but
  possible if the user moved their User Library mid-install. Iterate
  through all candidates; remove from each, confirming once per location.

## Uninstall after pip uninstall

If the package has already been `pip uninstall`'d, `python -m hallucinote_mcp.cli preflight`
will fail. The remaining cleanup is purely filesystem:

1. **Remote Script** — delete `<User Library>/Remote Scripts/Hallucinote/`.
   Find the User Library at:
   - macOS: `~/Music/Ableton/User Library`
   - Windows: `~/Documents/Ableton/User Library` or
     `~/OneDrive/Documents/Ableton/User Library` (check both)
   - Linux: `~/Ableton/User Library` (Wine / CrossOver only)
   - or wherever the user moved it via Live's Preferences → Library.

2. **MCP configs** — search for the `hallucinote-mcp` key in:
   - `<current project>/.mcp.json`
   - `~/.claude.json`
   Edit each by hand (atomically — write to `.tmp`, then rename).

3. **Live Preferences click** — same as Step 4 above.
