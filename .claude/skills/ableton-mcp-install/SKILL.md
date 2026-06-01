---
name: ableton-mcp-install
description: Install Hallucinote MCP for use with Ableton Live. Copies the Remote Script package into Live's User Library, writes the MCP server entry into `.mcp.json` (or `~/.claude.json` if requested), and tells the user the one-time Ableton Preferences click. Use when the user wants to set up Hallucinote MCP for the first time, reinstall after a Python or Ableton update, or move the install to a different Live version.
---

# /ableton-mcp-install

Three pieces:

1. **Remote Script** — Python files in Live's User Library; loaded as a Control Surface.
2. **MCP server config** — JSON entry pointing Claude Code at `hallucinote-mcp serve`.
3. **One Ableton Preferences click** — user does this; you tell them how.

Path layouts + process detection live in `hallucinote_mcp.install_paths` (testable Python). This skill drives the orchestration.

## Step 1 — Preflight

### 1.0 Sanity checks

**Python ≥ 3.10.** Use whichever python identifier the user will use for pip + preflight downstream (`python` / `python3` / `py -3`):

```bash
python -c "import sys; assert sys.version_info >= (3, 10), f'hallucinote-mcp requires Python 3.10+, got {sys.version_info.major}.{sys.version_info.minor}'; print(sys.version)"
```

If `command not found`, ask which python they use. If too old, stop and tell them they need 3.10+. Don't suggest sudo.

**cwd looks like a project.** `.mcp.json` lands in `cwd`. If cwd has no project marker (`.git`, `pyproject.toml`, `package.json`, `Cargo.toml`, `go.mod`, `deno.json`), confirm with the user before proceeding — the cost of writing `.mcp.json` to the wrong place is high.

```bash
[ -d .git ] || [ -f pyproject.toml ] || [ -f package.json ] || [ -f Cargo.toml ] || [ -f go.mod ] || [ -f deno.json ]
```

(On Windows PowerShell or cmd.exe, use the equivalent file-exists check.)

### 1.1 Run preflight

**Run from the project directory** the user wants `.mcp.json` written to.

```bash
python -m hallucinote_mcp.cli preflight
```

(If `python` opens the Microsoft Store on Windows, use `py -3`. If import fails, stop and tell the user to `pip install hallucinote-mcp`.)

The report has these blocks:

- **`package`** — `version`, `root`, `rsync_exclude_args` and `robocopy_exclude_args` (pre-rendered for the copy commands — use verbatim).
- **`user_library`** — `default` path, `default_exists`, `candidates` (each `{path, exists}`).
- **`live`** — `installed_versions`, `is_running` (`true` / `false` / `null`).
- **`mcp_command`** — `path` + `on_path` flag.
- **`mcp_configs`** — `local_path`, `global_path`, `containing_entry` (every existing `hallucinote-mcp` registration), `malformed`.
- **`remote_script`** — per User-Library candidate: `{installed, version, matches_mcp_server}`. Surfaces stale Remote Scripts before the runtime handshake catches them.
- **`platform`** — `darwin` / `win32` / `linux`.

### Preflight decisions

- **`platform == "linux"`**: Live doesn't ship for Linux. Warn the user, show the Wine candidate path, ask whether to proceed. Hallucinote is untested on Linux.
- **`live.is_running == true`**: refuse. Live caches Control Surface listings at startup and may lock files on Windows.
- **`live.is_running == null`**: ask the user to confirm Live is closed.
- **`live.installed_versions == []`**: warn; ask before continuing.
- **`live.installed_versions` has multiple entries**: ask which version this install targets.
- **`mcp_configs.malformed` non-empty**: stop. Show the path; ask the user to fix or delete.
- **`remote_script.candidates[*].installed == true` AND `matches_mcp_server == false`**: vendored copy is out-of-sync. Show vendored `version` vs `package.version` and continue — Step 3 overwrites it. If `matches_mcp_server == true`, the user may want to skip to Step 4.

## Step 2 — Choose the User Library

Default: first `user_library.candidates` entry with `exists == true`. If none exist, use `default` and tell the user you're about to create it.

If the user has moved their User Library inside Live, ask for the path. Don't try to parse `Library.cfg` / `Preferences.cfg`.

Confirm the chosen path with the user, then preview:

```bash
python -c "from hallucinote_mcp.install_paths import describe_install_layout; print(describe_install_layout(r'<chosen path>'))"
```

## Step 3 — Copy the Remote Script

Target: `<User Library>/Remote Scripts/Hallucinote/`. Create if missing. **Do not overwrite an existing directory without asking** — remove the old one first if confirmed (don't merge).

### 3a. Control Surface entry stub

```bash
python -c "from hallucinote_mcp.install_paths import remote_script_stub_text; print(remote_script_stub_text())" > "<User Library>/Remote Scripts/Hallucinote/__init__.py"
```

(PowerShell: use `Set-Content` to avoid UTF-16 BOM. cmd.exe: `>` works.)

### 3b. Vendored `hallucinote_mcp/` package

Source is `package.root` from preflight. **Anchoring `--exclude=/server.py` is load-bearing**: `server.py` exists at both the package root (FastMCP-dependent, must skip) and inside `remote_script/` (Live's Control Surface entrypoint, must keep). An unanchored exclude strips both and silently breaks the install.

**macOS / Linux** (interpolate `package.rsync_exclude_args`):
```bash
rsync -a <package.rsync_exclude_args joined by space> \
  "<package.root>/" \
  "<User Library>/Remote Scripts/Hallucinote/hallucinote_mcp/"
```

Expanded example:
```bash
rsync -a \
  --exclude=/server.py \
  --exclude=cli --exclude=tests --exclude=__pycache__ --exclude=m4l \
  --exclude=*.pyc \
  "<package.root>/" \
  "<User Library>/Remote Scripts/Hallucinote/hallucinote_mcp/"
```

**Windows** (interpolate `package.robocopy_exclude_args`; `/XF` list starts with the absolute path to package-root `server.py` — that's what anchors the exclusion to that single file):
```powershell
robocopy "<package.root>" "<User Library>\Remote Scripts\Hallucinote\hallucinote_mcp" /E <package.robocopy_exclude_args joined by space>
```

Expanded example:
```powershell
robocopy "<package.root>" "<User Library>\Remote Scripts\Hallucinote\hallucinote_mcp" /E /XF "<package.root>\server.py" *.pyc /XD cli tests __pycache__ m4l
```

Robocopy exit `0`-`7` = success; `8`+ = error. `/E` recurses; `/XD` excludes directories anywhere; `/XF` matches absolute paths to a single file (which is why we pass the package-root absolute path for `server.py` — a bare basename would strip `remote_script\server.py` too).

If robocopy isn't available (very old Windows), fall back. The explicit single-file remove only touches the package-root `server.py`, not `remote_script\server.py`:
```powershell
Copy-Item -Path "<package.root>\*" -Destination "<User Library>\Remote Scripts\Hallucinote\hallucinote_mcp" -Recurse
Remove-Item -Force "<User Library>\Remote Scripts\Hallucinote\hallucinote_mcp\hallucinote_mcp\server.py"
Remove-Item -Recurse -Force "<User Library>\Remote Scripts\Hallucinote\hallucinote_mcp\cli", "<User Library>\Remote Scripts\Hallucinote\hallucinote_mcp\tests", "<User Library>\Remote Scripts\Hallucinote\hallucinote_mcp\m4l"
Get-ChildItem -Path "<User Library>\Remote Scripts\Hallucinote\hallucinote_mcp" -Filter __pycache__ -Recurse -Directory | Remove-Item -Recurse -Force
Get-ChildItem -Path "<User Library>\Remote Scripts\Hallucinote\hallucinote_mcp" -Filter *.pyc -Recurse -File | Remove-Item -Force
```

### 3c. Sanity check

Tree must contain at minimum:
```
<User Library>/Remote Scripts/Hallucinote/
  __init__.py
  hallucinote_mcp/
    __init__.py
    schema.py
    wire.py
    dispatcher.py
    client.py
    install_paths.py
    actions/                      # required — populated at Control Surface load
    handlers/                     # required — counterparts to actions/
    remote_script/
      __init__.py
      _control_surface.py
      server.py
      dispatch.py
```

The excludes are load-bearing — re-copy if any of these conditions are violated:
- `server.py` directly under `hallucinote_mcp/` (must be absent — that one is FastMCP-dependent).
- `cli/`, `tests/`, `m4l/`, or `__pycache__/` directories anywhere under the copy (must all be absent).

If the excludes didn't take, Live's embedded Python fails to import the FastMCP-dependent files and aborts loading the Control Surface.

## Step 3d — Copy the HallucinoteAnalyzer M4L device

Target:
```
<User Library>/Presets/Audio Effects/Max Audio Effect/HallucinoteAnalyzer.amxd
```

Resolve source + target:
```bash
python -c "from hallucinote_mcp.install_paths import analyzer_amxd_source_path, analyzer_install_target; print('src=', analyzer_amxd_source_path()); print('dst=', analyzer_install_target(r'<chosen User Library>'))"
```

If `src` doesn't exist, the package install is incomplete — `pip install --force-reinstall hallucinote-mcp`.

If `dst` exists, ask before overwriting (the user may have customized it via Max GUI).

Copy (it's a binary container — plain file copy, no text filter):
```bash
# macOS / Linux
mkdir -p "<dst-parent>"
cp "<src>" "<dst>"
```

```powershell
# Windows PowerShell
New-Item -Path "<dst-parent>" -ItemType Directory -Force | Out-Null
Copy-Item -Path "<src>" -Destination "<dst>"
```

**Probe for Max for Live.** The analyzer requires Live Suite:

```bash
python -c "from hallucinote_mcp.install_paths import max_for_live_available; print(max_for_live_available())"
```

Today this always returns `None` (Live's edition isn't reliably detectable). Ask: *"Is your Live edition Suite? The HallucinoteAnalyzer requires Max for Live, which ships only with Suite."* If no, continue the install — non-render workflows still work; user decides whether to upgrade.

Verify the copy landed:
```bash
python -c "from hallucinote_mcp.install_paths import installed_analyzer_amxd; print(installed_analyzer_amxd(r'<chosen User Library>'))"
```

`None` means the copy didn't take — investigate permissions / target path.

## Step 4 — Write the MCP server config

Ask: project-local `.mcp.json` (default, in cwd) or global `~/.claude.json`?

Entry to merge into `mcpServers`:
```json
{
  "hallucinote-mcp": {
    "command": "hallucinote-mcp",
    "args": ["serve"]
  }
}
```

### 4a. Pick the `command` value

From the preflight report:
- `mcp_command.on_path == true` → bare string `"hallucinote-mcp"`.
- `mcp_command.on_path == false` AND `path != null` → absolute path from `mcp_command.path` (venv-local script not on PATH).
- `mcp_command.path == null` → stop. Tell user to `pip install hallucinote-mcp` and re-run.

### 4b. Merge

Parse the chosen config (create if absent). **Do not overwrite other entries.** If `mcp_configs.containing_entry` already lists `hallucinote-mcp` — in this scope or another (e.g. `projects.<cwd>.mcpServers` from `claude mcp add`) — surface it to the user and ask before replacing.

If the target is in `mcp_configs.malformed`, stop.

### 4c. Write atomically

Write to `<config>.tmp`, then rename (`os.replace` / `mv` / `Move-Item -Force`). Don't write directly — a crash mid-write corrupts `~/.claude.json` and loses the user's project history.

## Step 5 — Hand off (the MCP connection is the gotcha, then open the conversation)

This is the user's first contact as a **music person**, not a developer of this
project. Two parts: finish the mechanical install (the one Ableton click + the
MCP reconnect — the update case has a trap), then a warm, capability-honest
invitation that opens an intent conversation. **Do not** print a static command
menu — that surfaces a vending-machine framing and teaches nothing.

### 5a — Finish the install (classify fresh vs update)

The hand-off differs depending on whether this was a **fresh install** or an
**update**, and the update case has a trap that's easy to get wrong. Classify
from the preflight report you already have:

- **Update / reinstall** — `mcp_configs.containing_entry` already listed
  `hallucinote-mcp` for the chosen scope (Step 4 left it unchanged) **and/or** a
  Remote Script was already installed (`remote_script.candidates[*].installed ==
  true`). The config didn't change; only the server **code** changed.
- **Fresh install** — neither was true before this run (you wrote the
  `.mcp.json` entry in Step 4; no prior Remote Script). Claude Code has never
  loaded this server.

> **Critical, update case:** if *you (the agent)* ran this skill through the
> live `hallucinote-mcp` connection, you just replaced the code that connection
> runs. **Your current bridge is now stale** — it holds the pre-update server in
> memory and keeps behaving like the old version until the subprocess is
> respawned. You cannot do this yourself; the user must reconnect. **Do not
> report the install as working until they have.** The completion gate is a
> `/mcp` reconnect, not a vibe.

Print the checklist for the matching case **as Markdown, NOT inside a code
fence** — the checkboxes and strikethrough only render outside a fence. Mark
each line:

- something you (the agent) already did → `- [x] ~~**Me** — …~~` (checked + struck through)
- something the user still must do → `- [ ] **You** — …` (unchecked)

Fill from what you actually did (don't claim a step you skipped) and interpolate
real version strings from preflight.

**Update / reinstall** — render as:

- [x] ~~**Me** — Remote Script re-vendored in the User Library (old copy removed first)~~
- [x] ~~**Me** — version handshake will match (server `<package.version>` == vendored, same)~~
- [x] ~~**Me** — `.mcp.json` entry already present, unchanged~~
- [ ] **You** — Reopen Ableton Live so it loads the refreshed Control Surface (the *Hallucinote* slot is almost certainly still assigned — just reopen; re-check Preferences only if not)
- [ ] **You** — Run `/mcp` → `hallucinote-mcp` → reconnect *(required to finish)*

Then, as plain prose: the reconnect is REQUIRED and only the user can do it —
the Claude Code session that ran this install is still talking to the
PRE-UPDATE server, and reconnecting respawns it on the new code (a full Claude
Code restart also works, but `/mcp` reconnect is enough since the `.mcp.json`
entry didn't change). If a version-mismatch shows up after reconnect, the user
should fully quit Live and reopen — Live caches Control Surface modules at
startup, so a stale module can linger.

**Fresh install** — render as:

- [x] ~~**Me** — Remote Script installed in the User Library~~
- [x] ~~**Me** — `.mcp.json` entry written (`hallucinote-mcp`)~~
- [ ] **You** — In Ableton Live: Preferences → Link, Tempo & MIDI → select *Hallucinote* in any free Control Surface slot (Input/Output = None)
- [ ] **You** — Load the new server in Claude Code: run `/mcp` (or restart Claude Code) so it picks up the new `.mcp.json` entry

Then point them at a first action — *"load falling-walking"* (push the bundled
example song into Live) or *"start a new song"* (scaffold from a prompt) — and
note that `/ableton-mcp-uninstall` reverses every step if something looks wrong.

### 5b — The handoff (compose it; don't print a menu)

**Read `docs/capability-truth.md`.** Then write a short, warm invitation that:

- Is **capability-honest in musical/dimensional terms** — name a few things
  Hallucinote does well (groove, harmony, arrangement, sound design, mix), drawn
  from the Capability Truth table, as *example invitations* ("we could build a
  beat, flesh out a chord progression, arrange a track around an idea you have").
- **Names the thin dimensions honestly** when they're relevant, and **inverts
  the gap into an invitation** rather than apologizing — melody *authoring* is ◐
  and vocal synthesis is ✗, but a topline sketched in Ableton round-trips in *and
  the melody lens reads it*, so the move is *"bring me your melody, I'll build the
  track under it and read whether the line lands."*
- **Opens an intent conversation** — invite the user to say what they want to
  make, in their own words and references ("a song like the Stranger Things
  theme" is a perfectly good spec). Do **not** ask them to pick a "mode"; read
  their intent from what they say (start fresh, load an existing song, sketch a
  part) and proceed collaboratively — propose the elementary choices you'd
  otherwise guess at and read their reaction, rather than deciding silently.
- **Never confabulates.** If it isn't ✓ or ◐ in the Capability Truth table,
  don't offer it.

Keep it to a few sentences — an open door, not a manual. The goal is that the
user's next message is "I want to make…", and you continue from there (into
`/song-new` for a new song, or a load/pull for existing material).

## Edge cases

- **Permission denied** on User Library: tell the user; don't try sudo.
- **Existing `Hallucinote/` folder**: ask before overwriting; remove the old one before copying (don't merge).
- **Live is running**: refuse (Step 1 caught this).
- **Windows long paths**: robocopy handles long-path APIs but Live's loader sometimes balks. Suggest a shorter User Library path if needed.
- **Multiple Live installs**: ask which one (Live remembers User Library per-install).
- **Malformed config**: refuse to edit.
- **OneDrive Documents redirection (Windows)**: preflight candidates include both `OneDrive\Documents\Ableton\User Library` and `Documents\Ableton\User Library`. Use whichever exists; ask if both.

## When things look wrong

See `ableton://guides/error-recovery` — covers version-handshake errors, Control Surface dropdown failures, and import errors in Live's `Log.txt`.

## Uninstall

`/ableton-mcp-uninstall` reverses every step.
