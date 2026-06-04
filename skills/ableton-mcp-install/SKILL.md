---
name: ableton-mcp-install
description: Install Hallucinote MCP for use with Ableton Live. Vendors the Remote Script into Live's User Library, installs the HallucinoteAnalyzer device, raises the MCP startup timeout in ~/.claude/settings.json so the first-run cold build doesn't time out, confirms the plugin-provided `hallucinote-mcp` server is connected (the plugin launches it via uv — the skill writes no mcpServers entry), and tells the user the one-time Ableton Preferences click. Use when the user wants to set up Hallucinote MCP for the first time, reinstall after a Python or Ableton update, or move the install to a different Live version.
---

# /ableton-mcp-install

Three pieces:

1. **Remote Script** — Python files in Live's User Library, loaded as a Control Surface.
2. **MCP server** — provided by the `hallucinote` plugin (it launches the bundled
   `hallucinote-mcp` via `uv run` from a committed lock). The skill writes **no**
   config; it just confirms Claude Code sees the server.
3. **One Ableton Preferences click** — the user does this; you tell them how.

Every filesystem mutation runs through **tested, atomic CLI subcommands** in the
`hallucinote_mcp` package — `install-remote-script`, `install-analyzer`. This skill
*orchestrates*: it runs preflight, makes the decisions a human should confirm, and
invokes those subcommands. It never hand-authors copy / delete / JSON-edit shell.
(A previous version did, and a zsh glob once aborted mid-copy, leaving a
half-installed Control Surface; the atomic vendor — stage → verify → swap — makes
that structurally impossible.)

The copy's excludes, the verification, and the atomic vendor live in tested Python
(`install_ops.py`); path + prerequisite (`uv`) detection lives in
`install_paths.py`. Don't re-derive any of it in the skill body.

## Step 1 — Preflight

```bash
python -m hallucinote_mcp.cli preflight
```

(If import fails, stop and tell the user to `pip install hallucinote-mcp`. On
Windows, if `python` opens the Microsoft Store, use `py -3`.)

The JSON report blocks you act on:

- **`live.is_running`** — `true` → refuse (Live caches Control Surfaces at startup and can lock files); `null` → ask the user to confirm Live is fully quit (⌘Q, not just the window).
- **`platform == "linux"`** → warn (Live doesn't officially ship for Linux); show the Wine candidate and ask before proceeding.
- **`user_library.candidates`** — the User Library options (Step 2).
- **`live.installed_versions`** — multiple entries sharing one User Library is normal (one install covers all); empty → ask before continuing.
- **`uv.present`** — `false` → the bundled MCP server **can't launch** (the plugin runs it via `uv run`). Tell the user to install uv (`brew install uv`, or `curl -LsSf https://astral.sh/uv/install.sh | sh`) and restart Claude Code, then re-run. This probes the install-process PATH; the authoritative check is whether `/mcp` lists the server (Step 4).
- **`mcp_configs.malformed`** — non-empty → stop; tell the user to fix/delete those files (uninstall's `remove-mcp-config` refuses to edit malformed JSON anyway).
- **`remote_script.candidates[*]`** — `installed: true` with `matches_mcp_server: false` is a stale install → this run is an **update** (Step 3 replaces it). `matches_mcp_server: true` → already current; you may skip to Step 4.
- **`mcp_configs.containing_entry`** — pre-existing `hallucinote-mcp` registrations from a *legacy* (pre-plugin) install; not needed for install (the plugin provides the server), but worth noting so the user can clean them via `/ableton-mcp-uninstall` if a stale entry shadows the plugin.

## Step 2 — Choose the User Library

Default: the first `user_library.candidates` entry with `exists: true`; if none
exist, use `user_library.default` and tell the user you'll create it. If the user
moved their User Library inside Live (Preferences → Library), ask for the path.
Confirm the chosen path before any mutation.

## Step 3 — Install the Remote Script

One atomic command stages the vendored package (excludes applied in Python),
verifies it, and swaps it into place with rollback:

```bash
python -m hallucinote_mcp.cli install-remote-script --user-library "<chosen User Library>"
```

- **Updating an existing install?** Preflight showed `installed: true`. Confirm
  the overwrite with the user, then add `--force` — a clean remove-and-replace,
  not a merge.
- The command prints JSON: `{"ok": true, "replaced_existing": ..., "verify": {"ok": true, "missing": [], "unexpected": []}}`. If `ok` is false or `verify.ok` is false, **stop** and show the user the `error` / `missing` / `unexpected` fields — the live install was *not* touched (the staged tree failed verification before any swap).

You do not hand-author the copy, the excludes, or a sanity check; they live in
`install_ops.vendor_remote_script` / `verify_remote_script` and are unit-tested.

## Step 3d — Install the HallucinoteAnalyzer device

`HallucinoteAnalyzer.amxd` is a Max for Live device that lands in
`Presets/Audio Effects/Max Audio Effect/`. It requires **Max for Live, which
ships only with Live Suite.** Probe, then ask:

```bash
python -c "from hallucinote_mcp.install_paths import max_for_live_available; print(max_for_live_available())"
```

Today this returns `None` (Live's edition isn't reliably detectable) — ask:
*"Is your Live edition Suite? The HallucinoteAnalyzer requires Max for Live, which
ships only with Suite."* If it isn't Suite, you may still install it — non-render
workflows work without it; let the user decide.

**First, check `preflight`'s `analyzer` block for the chosen User Library** (it
mirrors `remote_script`: `analyzer.source_fingerprint` + one
`analyzer.candidates[*]` entry per candidate, each with `installed`,
`installed_fingerprint`, and a `matches` bool). The `.amxd` is binary, so this is
a raw-byte content fingerprint, not the Remote Script's version string. Branch on
the candidate matching the chosen User Library:

- **`installed: true` and `matches: true`** → the installed device is
  byte-identical to the bundled source. **Skip this step entirely** — no copy, no
  overwrite prompt. (Re-running install used to blindly re-prompt to overwrite an
  identical device — INS-4H8M.)
- **`installed: true` and `matches: false`** → the installed device differs
  (newer, or Max-GUI-customized). Confirm the overwrite with the user, then
  install with `--force` below.
- **`installed: false`** → fresh install; run without `--force`.

Install atomically:

```bash
python -m hallucinote_mcp.cli install-analyzer --user-library "<chosen User Library>"
```

Add `--force` to overwrite an existing device **only after confirming** (the
`matches: false` case above) — the user may have customized it via the Max GUI.
Prints `{"ok": true, "target": ..., "replaced_existing": ...}`; on `ok: false`,
show the error.

## Step 4 — Raise the MCP startup timeout, then confirm the server is connected

The server is **provided by the `hallucinote` plugin** — it launches the bundled
`hallucinote-mcp` via `uv run --frozen` from a committed lock, into a per-plugin
environment (INS-7V2D). The install skill writes **no** MCP config: the old
absolute-path-override hack is gone, because the uv launch is PATH-independent and
already version-coupled to the plugin. **Don't hand-author a config entry; that's
exactly what the plugin model replaces.**

> ⚠️ **The first launch builds the server's Python environment, and that can take
> ~1–2 minutes.** The bundled server carries numpy/scipy/librosa (~70 MiB) for its
> audio analysis. On a genuinely-cold first run — and the first run after any
> plugin update (the lock changes) — that build can exceed Claude Code's **default
> 30 s MCP startup window** and show `hallucinote-mcp` as **failed** in `/mcp`
> until the env is ready (CC#60224). It is **one-time**: every later session starts
> instantly.

Raise the startup timeout once so a cold build fits (idempotent — never lowers a
higher value you've set):

```bash
python -m hallucinote_mcp.cli set-startup-timeout
```

This writes `env.MCP_TIMEOUT` (3 min) into `~/.claude/settings.json` — the only
channel that reaches a plugin-provided server's *startup*. It takes effect **the
next time Claude Code starts**, so it protects future cold events (the next plugin
update); this session's env is usually already warm by now. (The per-server
`timeout` in the plugin manifest governs *tool execution*, not startup, so it
cannot cover this — that was the INS-7V2D cold-start bug.) Prints
`{"ok": true, "action": "set"|"raised"|"kept", ...}`.

Then check `/mcp` (or the session's MCP list): is `hallucinote-mcp` listed?

- **Listed** → done. The plugin provides it; nothing to write.
- **Not listed / shows "failed" right after a fresh install or plugin update** →
  it most likely **raced a cold build**. Tell the user the env builds on first run
  (~1–2 min); once the session's pre-warm prints "MCP env ready" (or a couple of
  minutes pass), run `/mcp` to reconnect — a warm connect is ~2 s. If it still
  isn't listed after the env is warm, the `hallucinote` plugin isn't loaded/enabled
  — have the user install/enable it (`/plugin install hallucinote@hallucinote`, or
  `--plugin-dir .` for a source checkout), then `/mcp`. Confirm `uv.present` was
  `true` in preflight (Step 1); if not, uv is the blocker, not the timeout.

## Step 5 — Hand off (the MCP connection is the gotcha, then open the conversation)

This is the user's first contact as a **music person**, not a developer of this
project. Two parts: finish the mechanical install (the one Ableton click + the
MCP reconnect — the update case has a trap), then a warm, capability-honest
invitation that opens an intent conversation. **Do not** print a static command
menu — that surfaces a vending-machine framing and teaches nothing.

### 5a — Finish the install (classify fresh vs update)

Classify from the preflight report you already have:

- **Update / reinstall** — preflight showed a Remote Script already installed
  (`remote_script.candidates[*].installed == true`) and/or `hallucinote-mcp` was
  already listed in `/mcp` (Step 4 found it connected). Only the server **code**
  changed.
- **Fresh install** — neither was true before this run. Claude Code has never
  loaded this server.

> **Critical, update case:** if *you (the agent)* ran this skill through the live
> `hallucinote-mcp` connection, you just replaced the code that connection runs.
> **Your current bridge is now stale** — it holds the pre-update server in memory
> until the subprocess is respawned. You cannot do this yourself; the user must
> reconnect. **Do not report the install as working until they have.** The
> completion gate is a `/mcp` reconnect, not a vibe.

Print the checklist for the matching case **as Markdown, NOT inside a code fence**
— the checkboxes and strikethrough only render outside a fence. Mark each line:

- something you (the agent) already did → `- [x] ~~**Me** — …~~`
- something the user still must do → `- [ ] **You** — …`

Fill from what you actually did (don't claim a step you skipped); interpolate real
version strings from preflight.

**Update / reinstall** — render as:

- [x] ~~**Me** — Remote Script re-vendored in the User Library (old copy removed first, atomically)~~
- [x] ~~**Me** — version handshake will match (server `<package.version>` == vendored)~~
- [x] ~~**Me** — MCP server: provided by the `hallucinote` plugin (uv-launched from the committed lock) — nothing written~~
- [ ] **You** — Reopen Ableton Live so it loads the refreshed Control Surface (the *Hallucinote* slot is almost certainly still assigned — just reopen; re-check Preferences only if not)
- [ ] **You** — Run `/mcp` → `hallucinote-mcp` → reconnect *(required to finish)*

Then, as plain prose: the reconnect is REQUIRED and only the user can do it — the
session that ran this install is still talking to the PRE-UPDATE server, and
reconnecting respawns it on the new code (a full Claude Code restart also works).
If a version-mismatch shows up after reconnect, the user should fully quit Live
and reopen — Live caches Control Surface modules at startup, so a stale module can
linger.

**Fresh install** — render as:

- [x] ~~**Me** — Remote Script installed in the User Library (atomic, verified)~~
- [x] ~~**Me** — HallucinoteAnalyzer device installed~~
- [x] ~~**Me** — MCP server: provided by the `hallucinote` plugin (uv-launched), nothing written~~
- [x] ~~**Me** — Raised the MCP startup timeout in `~/.claude/settings.json` (first-run cold-build safety)~~
- [ ] **You** — In Ableton Live: Preferences → Link, Tempo & MIDI → select *Hallucinote* in any free Control Surface slot (Input/Output = None)
- [ ] **You** — Load the server in Claude Code: run `/mcp` (or restart Claude Code) so it picks up `hallucinote-mcp`

Then, as plain prose, set the first-run expectation: **the very first launch builds
the server's Python environment and can take ~1–2 minutes** (it carries
numpy/scipy/librosa for audio analysis). If `hallucinote-mcp` shows as *failed* in
`/mcp` on that first run, it just raced the build — wait for the session's
"MCP env ready" notice (or a couple of minutes), then run `/mcp` to reconnect. It is
one-time; every later session starts instantly.

Then point them at a first action — *"load falling-walking"* (push the bundled
example song into Live) or *"start a new song"* (scaffold from a prompt) — and note
that `/ableton-mcp-uninstall` reverses every step if something looks wrong.

### 5b — The handoff (compose it; don't print a menu)

**Read `docs/capability-truth.md`.** Then write a short, warm invitation that:

- Is **capability-honest in musical/dimensional terms** — name a few things
  Hallucinote does well (groove, harmony, arrangement, sound design, mix), drawn
  from the Capability Truth table, as *example invitations*.
- **Names the thin dimensions honestly** when relevant, and **inverts the gap into
  an invitation** — melody *authoring* is ◐ and vocal synthesis is ✗, but a topline
  sketched in Ableton round-trips in *and the melody lens reads it*, so the move is
  *"bring me your melody, I'll build the track under it and read whether the line lands."*
- **Opens an intent conversation** — invite the user to say what they want to make,
  in their own words and references ("a song like the Stranger Things theme" is a
  perfectly good spec). Don't ask them to pick a "mode"; read their intent and
  proceed collaboratively.
- **Never confabulates.** If it isn't ✓ or ◐ in the Capability Truth table, don't offer it.

Keep it to a few sentences — an open door, not a manual. The goal is that the
user's next message is "I want to make…", and you continue from there.

## Edge cases

- **Permission denied** on the User Library: tell the user; don't try sudo. The
  CLI surfaces the OS error in its JSON.
- **Live is running**: refuse (Step 1 caught this).
- **Multiple Live installs**: they share one User Library by default — one install
  covers all. Ask only if the user configured per-version libraries.
- **uv missing**: preflight's `uv.present == false` → the plugin can't launch the
  server. Have the user `brew install uv` (or the curl bootstrap) and restart
  Claude Code before relying on the bridge. The install skill writes no config, so
  there's no fallback to a hand-authored entry — uv is the prerequisite.
- **`hallucinote-mcp` not in `/mcp`**: the plugin isn't loaded — install/enable it
  (`/plugin install hallucinote@hallucinote`), then `/mcp`. Nothing for this skill
  to write.
- **OneDrive Documents redirection (Windows)**: preflight's `user_library.candidates`
  already includes both `OneDrive\Documents\…` and `Documents\…`; use whichever
  exists, ask if both.

## When things look wrong

See `ableton://guides/error-recovery` — version-handshake errors, Control Surface
dropdown failures, import errors in Live's `Log.txt`.

## Uninstall

`/ableton-mcp-uninstall` reverses every step (the same CLI subcommands in reverse).
