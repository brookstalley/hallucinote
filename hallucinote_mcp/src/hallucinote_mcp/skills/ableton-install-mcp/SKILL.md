---
name: ableton-install-mcp
description: Install Hallucinote MCP for use with Ableton Live. Copies the Remote Script package into Live's User Library, writes the MCP server entry into `.mcp.json` (or `~/.claude.json` if requested), and tells the user the one-time Ableton Preferences click. Use when the user wants to set up Hallucinote MCP for the first time, reinstall after a Python or Ableton update, or move the install to a different Live version.
---

# /ableton-install-mcp

You install `hallucinote-mcp` for the user. Three pieces:

1. **Remote Script** — Python files vendored into Ableton Live's User Library; Live
   loads them as a Control Surface.
2. **MCP server config** — a JSON entry that points Claude Code at `hallucinote-mcp serve`.
3. **One Ableton Preferences click** — the user does this; you tell them how.

The install logic lives in this skill body deliberately. Cross-platform install scripts
break on every Live update; natural-language instructions adapt.

## Preconditions

Confirm before you touch anything:

1. **Package is installed.** Run:
   ```bash
   python -c "import hallucinote_mcp; print(hallucinote_mcp.__version__)"
   ```
   If this fails, tell the user to `pip install hallucinote-mcp` first and stop.

2. **Live is not running.** Live caches Control Surface listings at startup; an install
   while Live is open won't appear until restart, and on Windows the copy may fail
   silently because Live has the old files locked.

3. **Live version.** Ask which (11 vs 12). Live 11's embedded Python is 3.7; Live 12's is
   3.11. The Remote Script is pure stdlib and runs against both, but knowing this helps
   if troubleshooting is needed later.

## Step 1 — Find the install source

Ask Python where the package lives and what the install layout should look like:

```bash
python -c "from hallucinote_mcp.install_paths import package_root, default_user_library, describe_install_layout; print('SOURCE:', package_root()); ul = default_user_library(); print('USER LIBRARY (default):', ul); print(describe_install_layout(ul))"
```

This prints:
- The filesystem path of the installed `hallucinote_mcp` package (the **source**).
- The default User Library path for the platform (the **target parent**).
- A preview of the layout to be created.

Confirm the User Library path with the user — if they've set a custom location in
Ableton's Preferences → Library, ask them for it.

## Step 2 — Copy the Remote Script

Target directory:
```
<User Library>/Remote Scripts/Hallucinote/
```

Create it if missing. **Do not overwrite** an existing `Hallucinote/` directory without
asking the user — they may have a customized version.

Inside `Hallucinote/`, create two things:

1. **`__init__.py`** — a tiny stub Live uses as the Control Surface entry point. Get
   the exact content from:
   ```bash
   python -c "from hallucinote_mcp.install_paths import remote_script_stub_text; print(remote_script_stub_text())"
   ```
   Write that string to `<User Library>/Remote Scripts/Hallucinote/__init__.py`.

2. **`hallucinote_mcp/`** — a copy of the package itself, minus the files Live's
   embedded Python doesn't need. Get the exclude list from:
   ```bash
   python -c "from hallucinote_mcp.install_paths import REMOTE_SCRIPT_EXCLUDE; print('\n'.join(REMOTE_SCRIPT_EXCLUDE))"
   ```

   On macOS / Linux, use rsync to copy with excludes:
   ```bash
   rsync -a \
     --exclude='server.py' \
     --exclude='cli' \
     --exclude='tests' \
     --exclude='__pycache__' \
     --exclude='*.pyc' \
     "<SOURCE from Step 1>/" \
     "<User Library>/Remote Scripts/Hallucinote/hallucinote_mcp/"
   ```

   On Windows, use PowerShell `Copy-Item -Recurse` then remove the excluded paths,
   or use `robocopy` with `/XD` flags. The skill's job is to get the paths right and
   issue the command — adapt to the user's shell.

**Sanity check:** after copying, the directory tree should look like:
```
<User Library>/Remote Scripts/Hallucinote/
  __init__.py                     # from remote_script_stub_text()
  hallucinote_mcp/
    __init__.py
    schema.py
    wire.py
    dispatcher.py
    client.py
    install_paths.py
    handlers/
      __init__.py
    remote_script/
      __init__.py
      _control_surface.py
      server.py
      dispatch.py
```

There should be **no** `server.py` directly under `hallucinote_mcp/` (that one is FastMCP-dependent — excluded).

## Step 3 — Write the MCP server config

Default: project-local `.mcp.json` in the current working directory. Ask if the user
wants a global config (`~/.claude.json` under the `mcpServers` key) instead.

The entry:
```json
{
  "mcpServers": {
    "hallucinote-mcp": {
      "command": "hallucinote-mcp",
      "args": ["serve"]
    }
  }
}
```

If the file exists, merge — do not overwrite other entries. If a `hallucinote-mcp`
entry already exists, ask before replacing.

**Verify `hallucinote-mcp` is on PATH:**
```bash
which hallucinote-mcp   # or: where hallucinote-mcp  on Windows
```

If it isn't, the install used a venv that isn't shimmed into the user's shell. Either:
- Tell the user how to activate the venv before launching Claude Code, OR
- Change the config's `command` to the full path printed by `python -c "import sys, hallucinote_mcp; print(sys.executable.replace('python', 'hallucinote-mcp'))"` (rough — verify it exists before writing it).

## Step 4 — Tell the user the Ableton click

Print this verbatim:

```
hallucinote-mcp install complete!

One last step in Ableton Live:
  1. Open Live.
  2. Preferences → Link, Tempo & MIDI.
  3. In any free "Control Surface" slot, select "Hallucinote".
  4. Leave "Input" and "Output" as "None".

After that, Hallucinote MCP is live. Restart Claude Code in this project so it
picks up the new MCP entry, then try:  ableton_session(action='help')
```

## Edge cases — handle them, don't paper over

- **Permission denied** on the User Library: tell the user; do not try `sudo`. They own that decision.
- **Existing `Hallucinote/` Remote Script folder**: ask before overwriting.
- **Live is running**: refuse to overwrite. Live has the files open; the copy may silently fail or produce a broken install.
- **Windows path length limits**: Live's loader sometimes balks at deep paths. If the User Library path is unusually deep, suggest the user move the User Library to a shallower location.
- **Multiple Live installs (11 + 12)**: Live remembers the User Library per-install. Ask which one this install is for.

## When things look wrong

If after the install + the Preferences click, Live doesn't show "Hallucinote" in the
Control Surface dropdown:

1. Wrong folder name. Must be exactly `Remote Scripts/Hallucinote/` (capital H).
2. Missing `__init__.py` at the `Hallucinote/` root.
3. Import error inside the Remote Script — check Live's log:
   - macOS: `~/Library/Preferences/Ableton/Live <version>/Log.txt`
   - Windows: `%APPDATA%\Ableton\Live <version>\Preferences\Log.txt`
4. Live cached the old listing. Quit Live completely and reopen.

## Uninstall

`/ableton-uninstall-mcp` reverses every step of this skill.
