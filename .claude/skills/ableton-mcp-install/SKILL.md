---
name: ableton-mcp-install
description: Install Hallucinote MCP for use with Ableton Live. Copies the Remote Script package into Live's User Library, writes the MCP server entry into `.mcp.json` (or `~/.claude.json` if requested), and tells the user the one-time Ableton Preferences click. Use when the user wants to set up Hallucinote MCP for the first time, reinstall after a Python or Ableton update, or move the install to a different Live version.
---

# /ableton-mcp-install

You install `hallucinote-mcp` for the user. Three pieces:

1. **Remote Script** — Python files vendored into Ableton Live's User Library; Live
   loads them as a Control Surface.
2. **MCP server config** — a JSON entry that points Claude Code at `hallucinote-mcp serve`.
3. **One Ableton Preferences click** — the user does this; you tell them how.

Install **orchestration** lives in this skill body deliberately. Path layouts
and process detection live in `hallucinote_mcp.install_paths` (testable Python).
Cross-platform install *scripts* break on every Live update; the split keeps
the natural-language steps adaptable while the detection stays reliable.

## Step 1 — Preflight

### Step 1.0 — Python version + cwd sanity (W15-B)

Before running preflight, do two cheap checks:

**Python version (refuse on < 3.10).** `hallucinote_mcp` requires Python 3.10+ (PEP 604 unions, etc.). Use whichever python identifier the user will use for pip + preflight downstream (`python` / `python3` / `py -3`) — picking the same identifier here ensures the version we check is the one preflight will run. If `command not found`, ask the user which python they use before retrying; don't conflate "missing python" with "too old".

```bash
python -c "import sys; assert sys.version_info >= (3, 10), f'hallucinote-mcp requires Python 3.10+, got {sys.version_info.major}.{sys.version_info.minor}'; print(sys.version)"
```

If that command exits non-zero on the assert, **stop**. Tell the user the version their python resolves to, and that they need 3.10 or newer (pyenv / Homebrew / apt / the python.org installer all work — pick whichever they already use). Don't suggest a fix path that requires sudo.

**cwd looks like a project (warn if not).** `.mcp.json` lands in `cwd`. If `cwd` is the user's `$HOME`, `/`, `/tmp`, or has no `.git` / `pyproject.toml` / `package.json` / `Cargo.toml` / `go.mod` / equivalent project marker, that's almost certainly wrong — the user probably wants `.mcp.json` in a specific project's directory, not in their shell-default. Quick checks (use the one that fits the user's shell — the install skill is the one place we expect a fresh user, so meet them where they are):

```bash
# bash / zsh / fish (macOS, Linux, WSL, Git Bash on Windows)
[ -d .git ] || [ -f pyproject.toml ] || [ -f package.json ] || [ -f Cargo.toml ] || [ -f go.mod ] || [ -f deno.json ]
```

```powershell
# PowerShell (Windows)
Test-Path .git,pyproject.toml,package.json,Cargo.toml,go.mod,deno.json | Where-Object { $_ } | Select-Object -First 1
```

```cmd
:: cmd.exe (Windows; native if neither PowerShell nor Git Bash is preferred)
if exist .git\ (echo found) else if exist pyproject.toml (echo found) else if exist package.json (echo found) else if exist Cargo.toml (echo found) else if exist go.mod (echo found) else if exist deno.json (echo found)
```

If none returns a hit (no markers found), **show the user the current directory** and ask explicitly: "Install into `<cwd>`? If you meant another project, `cd` there first and rerun this skill." Don't refuse outright — some setups legitimately have no marker file — but make the user confirm. The cost of writing `.mcp.json` to the wrong place is high (the user will wonder for hours why Claude Code in their actual project doesn't see the MCP).

### Step 1.1 — Run preflight

Run preflight **from the project directory** the user wants the local
`.mcp.json` written to. Preflight reports `mcp_configs.local_path` based
on `cwd`, so running from the wrong directory misses an existing entry.

```bash
python -m hallucinote_mcp.cli preflight
```

(If `python` isn't on the user's PATH, try `python3` or `py -3`. If
`python` on Windows opens the Microsoft Store, use `py -3` instead. If
the package import fails, stop and tell the user to
`pip install hallucinote-mcp`.)

The report has these blocks:

- **`package`** — `version`, `root` (source for the Remote Script copy),
  `remote_script_exclude` (structured: `top_level_files` anchored to the
  package root, `dirs_any` and `file_globs_any` matched anywhere), plus
  `rsync_exclude_args` and `robocopy_exclude_args` (pre-rendered for the
  copy commands below — use these verbatim instead of hand-rolling).
- **`user_library`** — `default` path, `default_exists` flag, and
  `candidates` (each with `path` + `exists`). On Windows, multiple
  candidates handle OneDrive Documents redirection.
- **`live`** — `installed_versions` (e.g. `["11.3.21", "12.0.5"]`) and
  `is_running` (`true` / `false` / `null`).
- **`mcp_command`** — `path` (resolved `hallucinote-mcp` executable) and
  `on_path` flag.
- **`mcp_configs`** — `local_path` (`.mcp.json` in cwd), `global_path`
  (`~/.claude.json`), `containing_entry` (list of `{path, json_pointer}`
  objects locating every existing `hallucinote-mcp` registration —
  including the `projects.<cwd>.mcpServers` scope that `claude mcp add`
  uses by default), `malformed` (configs that didn't parse as JSON).
- **`remote_script`** (W12-D) — `candidates` is one entry per User Library
  candidate: `{user_library, remote_script_dir, installed, version,
  matches_mcp_server}`. `version` is the vendored copy's `__version__`
  string (or `null` when nothing's installed there); `matches_mcp_server`
  is `true` when the vendored fingerprint matches `package.version`,
  `false` on drift, `null` when no install. Surfaces stale Remote Scripts
  BEFORE Live's runtime handshake catches them — drift here is the same
  failure mode as the handshake error users see at first MCP dispatch.
- **`platform`** — `darwin` / `win32` / `linux`.

### Preflight decisions

- **`platform == "linux"`** (W15-C): Ableton Live doesn't ship for Linux. The
  install proceeds for Wine / CrossOver users — the `user_library.candidates`
  list points at `~/Ableton/User Library`, where most Wine setups land Live's
  User Library — but Hallucinote is **not tested on Linux** and the
  push/pull bridge depends on Live behaviors that may differ under Wine.
  Warn the user, show the candidate path, and ask whether to proceed. If
  they confirm, continue with the regular flow. If they back out, suggest
  macOS or Windows — those are the supported platforms for v1. Don't refuse
  outright; some users do run Live under Wine and have working setups.
- **`live.is_running == true`**: refuse to proceed. Live caches Control
  Surface listings at startup; copying while Live is open won't appear until
  restart, and on Windows the copy may fail silently because Live has the
  old files locked.
- **`live.is_running == null`** (unknown — common on locked-down Windows):
  ask the user to confirm Live is closed before continuing.
- **`live.installed_versions == []`**: warn that no Live install was
  detected. The user may not have launched Live on this machine yet (which
  is fine — preferences are created on first launch), or they may not have
  Live at all. Ask before continuing.
- **`live.installed_versions` has multiple entries**: ask which one this
  install is targeting. Live remembers its User Library per-version; the
  user may want the install in just one or in all of them.
- **`mcp_configs.malformed` is non-empty**: stop and tell the user. Show
  the path and ask them to fix or delete the file before you proceed —
  overwriting a hand-edited config could destroy state.
- **`remote_script.candidates[*].installed == true` AND
  `matches_mcp_server == false`** (W12-D): a vendored Remote Script
  exists but is out-of-sync with the running MCP server. Show the user
  the vendored `version` vs `package.version` and explain that a fresh
  copy is needed — the user is reinstalling already, so this is the
  "we're about to fix the drift you'd otherwise discover at runtime"
  signal. Continue with the install (Step 3 overwrites the vendored
  copy after confirmation). If `installed == true` AND
  `matches_mcp_server == true`, mention briefly that the vendored copy
  is already current; the user may want to skip Step 3 and just run
  Step 4 to re-confirm the MCP config entry.

## Step 2 — Choose the User Library

Default: the first `user_library.candidates` entry where `exists` is `true`.
If none exist, use the `default` value and tell the user you're about to
create it (Live writes there on first launch, but a fresh install may not
have created the directory yet).

If the user has moved their User Library inside Live (Preferences →
Library → "Location of User Library"), they need to give you that path —
ask. Don't try to parse Live's `Library.cfg` / `Preferences.cfg`; those
are binary-adjacent and not safe to read.

**Confirm the chosen path with the user** before touching the filesystem,
then preview what you're about to create:

```bash
python -c "from hallucinote_mcp.install_paths import describe_install_layout; print(describe_install_layout(r'<chosen path>'))"
```

## Step 3 — Copy the Remote Script

Target directory:
```
<User Library>/Remote Scripts/Hallucinote/
```

Create it if missing. **Do not overwrite an existing `Hallucinote/` directory**
without asking — they may have a customized version. If they confirm,
remove the old directory before copying (don't merge — stale files
left behind cause import errors that look like Live bugs).

Inside `Hallucinote/`, create two things:

### 3a. The Control Surface entry stub `__init__.py`

```bash
python -c "from hallucinote_mcp.install_paths import remote_script_stub_text; print(remote_script_stub_text())" > "<User Library>/Remote Scripts/Hallucinote/__init__.py"
```

(On Windows in PowerShell, use `Set-Content` instead of `>` to avoid the
default UTF-16 BOM. In cmd.exe, the `>` redirect works fine.)

### 3b. The vendored `hallucinote_mcp/` package

The source is `package.root` from the preflight report. The exclude args
are pre-rendered for both copy tools — use them verbatim. The anchoring
on `server.py` is **load-bearing**: `server.py` exists at the package
root (FastMCP-dependent, must skip) and inside `remote_script/` (the
Control Surface entrypoint Live LOADS). A naive unanchored exclude
strips both and silently breaks the install.

**macOS / Linux — rsync** (interpolate `package.rsync_exclude_args` as
space-separated tokens; note the leading `/` on `--exclude=/server.py`
that anchors to the source root):
```bash
rsync -a \
  <package.rsync_exclude_args joined by space> \
  "<package.root>/" \
  "<User Library>/Remote Scripts/Hallucinote/hallucinote_mcp/"
```

Example, with the args expanded for a real run:
```bash
rsync -a \
  --exclude=/server.py \
  --exclude=cli --exclude=tests --exclude=__pycache__ \
  --exclude=*.pyc \
  "<package.root>/" \
  "<User Library>/Remote Scripts/Hallucinote/hallucinote_mcp/"
```

**Windows — robocopy** (interpolate `package.robocopy_exclude_args` —
the `/XF` list starts with the absolute path to the package-root
`server.py`, which anchors the exclusion to that single location):
```powershell
robocopy "<package.root>" "<User Library>\Remote Scripts\Hallucinote\hallucinote_mcp" /E <package.robocopy_exclude_args joined by space>
```

Example, with the args expanded:
```powershell
robocopy "<package.root>" "<User Library>\Remote Scripts\Hallucinote\hallucinote_mcp" /E /XF "<package.root>\server.py" *.pyc /XD cli tests __pycache__
```

`/E` = copy subdirs including empty ones. `/XD` excludes directory names
(matched anywhere). `/XF` matches by basename anywhere too — except when
the argument is an absolute path, in which case only that exact file is
skipped (the trick that preserves `remote_script\server.py`). Robocopy
exit codes `0`-`7` are success; `8`+ are errors — check this if scripting.

If robocopy isn't available (very old Windows), fall back. Note the
explicit single-file remove only touches the package-root `server.py`,
not the `remote_script\server.py` Live needs:
```powershell
Copy-Item -Path "<package.root>\*" -Destination "<User Library>\Remote Scripts\Hallucinote\hallucinote_mcp" -Recurse
Remove-Item -Force "<User Library>\Remote Scripts\Hallucinote\hallucinote_mcp\server.py"
Remove-Item -Recurse -Force "<User Library>\Remote Scripts\Hallucinote\hallucinote_mcp\cli", "<User Library>\Remote Scripts\Hallucinote\hallucinote_mcp\tests"
Get-ChildItem -Path "<User Library>\Remote Scripts\Hallucinote\hallucinote_mcp" -Filter __pycache__ -Recurse -Directory | Remove-Item -Recurse -Force
Get-ChildItem -Path "<User Library>\Remote Scripts\Hallucinote\hallucinote_mcp" -Filter *.pyc -Recurse -File | Remove-Item -Force
```

### 3c. Sanity check

After copying, the tree should contain at minimum:
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
    actions/                      # action registry — required
    handlers/                     # action implementations — required
    remote_script/
      __init__.py
      _control_surface.py
      server.py
      dispatch.py
```

`actions/` and `handlers/` are **required**, not "comes along for the
ride." `remote_script/_control_surface.py` does
`from .. import actions as _actions` at module load — a side-effect
import that populates the Live-side action registry. Each module under
`actions/` then imports its counterpart from `handlers/`. So both
subpackages are reachable through the Remote Script import chain
that Live walks at startup. Trimming either would break the Control
Surface load.

**Implication for development**: server-side action/handler changes
are ALSO Live-side changes, because the Control Surface re-imports
these packages from Live's User Library copy at startup. After
editing any `actions/*.py` or `handlers/*.py`, you must:

1. Run `/ableton-mcp-install` to refresh Live's vendored copy.
2. Fully quit and reopen Live (Live caches Control Surface modules
   at startup; `/mcp` alone doesn't refresh the Live-side copy).
3. `/mcp` to respawn the server subprocess.

The MCP server's version-mismatch check fires loudly if these halves
drift — it fingerprints the whole `hallucinote_mcp` package and
refuses to dispatch.

Other subpackages (e.g. `prompts/`, `resources/`, `skills/`, plus
`testing.py`) come along for the ride — Live ignores anything it doesn't
load, and stripping them per-release would create a drift surface. The
load-bearing rule is the **exclude** list, not an allow list:

- There must be **no** `server.py` *directly* under `hallucinote_mcp/`
  (that one is FastMCP-dependent — excluded). `server.py` *inside*
  `remote_script/` is correct and must be present.
- There must be **no** `cli/` directory and **no** `tests/` directory
  anywhere under the copy.
- There must be **no** `__pycache__/` directories — stale bytecode from
  the source venv would confuse Live's loader (different Python ABI).

If any of those are present, the excludes didn't take effect; redo the
copy before continuing — Live's embedded Python will fail to import the
FastMCP-dependent files and abort loading the Control Surface.

## Step 3d — Copy the HallucinoteAnalyzer M4L device

The audio-analysis MVP ships a Max for Live device
(`HallucinoteAnalyzer.amxd`) that records per-stem WAVs and streams
realtime features. It must live in Live's Max Audio Effect Presets
directory so the analyzer setup (`ableton_render(action='ensure_loaded')`)
can find it via the browser.

Target:
```
<User Library>/Presets/Audio Effects/Max Audio Effect/HallucinoteAnalyzer.amxd
```

### 3d.1. Resolve source + target

```bash
python -c "from hallucinote_mcp.install_paths import analyzer_amxd_source_path, analyzer_install_target; print('src=', analyzer_amxd_source_path()); print('dst=', analyzer_install_target(r'<chosen User Library>'))"
```

If `src` doesn't exist, the package install is incomplete (likely a
partial pip install or a source checkout that omitted `m4l/`). Stop and
tell the user to `pip install --force-reinstall hallucinote-mcp`. The
analyzer is shipped inside the wheel under `hallucinote_mcp/m4l/`.

### 3d.2. Confirm before overwriting

If `dst` already exists, ask before overwriting. The user may have a
locally-customized version (rare, but a Max GUI save lands back in the
User Library — see the spec's "Authoring workflow"). Don't auto-replace
without confirmation.

### 3d.3. Copy

The `.amxd` is a binary container — do NOT route it through any text
filter. Plain file copy preserves the byte-exact content:

**macOS / Linux:**
```bash
mkdir -p "<dst-parent>"
cp "<src>" "<dst>"
```

**Windows (PowerShell):**
```powershell
New-Item -Path "<dst-parent>" -ItemType Directory -Force | Out-Null
Copy-Item -Path "<src>" -Destination "<dst>"
```

**Windows (cmd.exe):**
```cmd
mkdir "<dst-parent>"
copy /Y "<src>" "<dst>"
```

### 3d.4. Probe for Max for Live

The analyzer is an M4L device; it requires Max for Live, which ships
only with Live Suite. If the user has Live Standard or Lite, the
device will appear in their browser but fail to load with
"Max for Live not available" at runtime.

```bash
python -c "from hallucinote_mcp.install_paths import max_for_live_available; print(max_for_live_available())"
```

- Returns `True` — strong evidence M4L is available; proceed quietly.
- Returns `False` — strong evidence M4L is NOT installed; stop and
  tell the user the analyzer requires Live Suite. Don't refuse the
  rest of the install — the MCP bridge still works for non-render
  workflows; the user can decide whether to upgrade.
- Returns `None` — can't tell. Ask the user "Is your Live edition
  **Suite**? (The HallucinoteAnalyzer requires Max for Live, which
  ships only with Suite.)". Their answer decides whether to mention
  the analyzer in Step 5's hand-off.

Today the probe always returns `None` (Live's edition isn't reliably
detectable cross-version); the install skill asks every time. Future
versions tighten this when reliable signals are available.

### 3d.5. Verify

After copy, the file must exist at the target path and be byte-equal
to the source (or close to it — Live may rewrite trailing chunks on
first load, so a strict byte equality check happens BEFORE first
Live launch).

```bash
python -c "from hallucinote_mcp.install_paths import installed_analyzer_amxd; print(installed_analyzer_amxd(r'<chosen User Library>'))"
```

A `None` return means the copy didn't land — investigate (permission
denied? wrong target path?) before continuing.

## Step 4 — Write the MCP server config

Ask: project-local `.mcp.json` (default — in the current working directory)
or global `~/.claude.json`?

The entry to merge into `mcpServers`:
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
- `mcp_command.on_path == true` (and `path != null`) → use the bare string
  `"hallucinote-mcp"`. Claude Code will resolve it via PATH.
- `mcp_command.on_path == false` **and** `mcp_command.path != null` → use
  the absolute string from `mcp_command.path` (a venv-local script that
  isn't on PATH). Tell the user why: their venv isn't shimmed into PATH,
  so Claude Code couldn't find the bare name. If they later activate the
  venv globally, you can re-run install to switch back to the bare form.
- `mcp_command.path == null` → stop. The package's console script isn't
  installed anywhere on disk; tell the user to `pip install hallucinote-mcp`
  (or activate the venv where they pip-installed it) and re-run.

### 4b. Merge into the chosen config file

If the file doesn't exist, create it with just the `mcpServers` block. If
it exists, parse it, merge — **do not overwrite other entries**. If
`mcp_configs.containing_entry` already lists a `hallucinote-mcp` entry —
in this scope OR another (e.g. one written by `claude mcp add` to
`projects.<cwd>.mcpServers`) — surface the existing entry's `path` and
`json_pointer` to the user and ask before replacing.

If the chosen file is in `mcp_configs.malformed`, stop — you already
warned the user in preflight; they need to fix it first.

### 4c. Write atomically

JSON config files (especially `~/.claude.json`, which Claude Code may
write to while running) need atomic writes to avoid corruption. Pattern:

1. Compute the new JSON (parsed → modified → serialized).
2. Write to `<config>.tmp` in the same directory.
3. Rename `<config>.tmp` → `<config>` (`os.replace` on Python, or `mv` on
   Unix / `Move-Item -Force` on Windows). The rename is atomic on the same
   filesystem.

Don't write directly to the config — a crash or concurrent write mid-flight
leaves a truncated file. `~/.claude.json` is large and stateful; corrupting
it costs the user their Claude Code project history.

## Step 5 — Tell the user the Ableton click + hand off (W15-B)

Print this verbatim:

```
hallucinote-mcp install complete!

One last step in Ableton Live:
  1. Open Live.
  2. Preferences → Link, Tempo & MIDI.
  3. In any free "Control Surface" slot, select "Hallucinote".
  4. Leave "Input" and "Output" as "None".

Then restart Claude Code in this project so it picks up the new MCP entry.

Once you're back in Claude Code, try one of these to get going:
  • "load falling-walking"          — push the bundled example song into Live
  • "start a new song"              — scaffold a fresh song from a prompt
  • "/ableton-pull <slug> <id> everything"
                                   — pull current Live state into the DB

If something looks broken, /ableton-mcp-uninstall reverses every step.
```

The "Try:" lines are deliberately phrased the way a user would speak them, not as MCP tool invocations — the install skill is the first surface a brand-new user touches, and `ableton_session(action='help')` is developer syntax. The two suggested entry points (`load falling-walking` / `start a new song`) cover the two real first-time paths.

## Edge cases — handle them, don't paper over

- **Permission denied** on the User Library: tell the user; do not try
  `sudo` / elevated shells. They own that decision.
- **Existing `Hallucinote/` Remote Script folder**: ask before overwriting
  (Step 3). Remove the old directory before copying — don't merge.
- **Live is running**: refuse to overwrite (Step 1 caught this). Live has
  the files open; the copy may silently fail or produce a broken install.
- **Windows long path limits** (260 chars without long-path support): if
  the chosen User Library path is deep, robocopy will still succeed (it
  uses long-path APIs internally) but Live's loader sometimes balks.
  Suggest the user shorten the User Library path if Live can't find the
  Control Surface after install.
- **Symlinked User Library**: rsync follows symlinks by default; robocopy
  follows by default too. The Remote Script ends up at the symlink target
  — fine, just note it.
- **Multiple Live installs (11 + 12)**: Step 1 lists them. Ask which one
  (or all) — Live remembers User Library per-install.
- **Malformed `.mcp.json`** (hand-edited, comments / trailing commas):
  refuse to overwrite (Step 1 surfaced this). Ask the user to fix.
- **OneDrive Documents redirection (Windows)**: the preflight report's
  candidate list includes both `OneDrive\Documents\Ableton\User Library`
  and `Documents\Ableton\User Library`. Use whichever has `exists: true`;
  if both, ask.

## When things look wrong

### Version handshake errors at runtime

If `ableton_session(action='info')` (or any non-`help` action) returns
`"Hallucinote MCP version handshake missing"` or
`"Hallucinote MCP version mismatch"`, the two halves of the bridge have
drifted — the pip-installed server side and the vendored Remote Script
side are on different `hallucinote_mcp.__version__`.

Quick recovery (the error's `hint` field names both versions so you can
tell which side is stale):

- **Remote Script side stale (common):** rerun this skill
  (`/ableton-mcp-install`) to refresh the vendored copy, then fully quit
  and reopen Live. **`/mcp` reconnect alone won't help** because Live
  caches Control Surface modules at startup — the staleness lives inside
  Live's Python.
- **MCP server side stale:** `pip install -U hallucinote-mcp`, then run
  `/mcp` in Claude Code. `/mcp` respawns the MCP subprocess with the new
  code; no full Claude Code restart needed.

See `ableton://guides/error-recovery` for the full version-handshake
section.

### Control Surface not appearing in the dropdown

If after the install + the Preferences click, Live doesn't show "Hallucinote"
in the Control Surface dropdown:

1. Wrong folder name. Must be exactly `Remote Scripts/Hallucinote/` (capital H).
2. Missing `__init__.py` at the `Hallucinote/` root.
3. Import error inside the Remote Script — check Live's `Log.txt`. Get the
   exact path from:
   ```bash
   python -c "from hallucinote_mcp.install_paths import live_log_path; print(live_log_path('<version>'))"
   ```
4. Live cached the old listing. Quit Live completely and reopen.
5. `server.py` ended up directly under `hallucinote_mcp/` — the excludes
   didn't take. Live's embedded Python will fail to import it (missing
   FastMCP) and abort loading the Control Surface. Re-copy.

## Uninstall

`/ableton-mcp-uninstall` reverses every step of this skill.
