# INS-7V2D — Plugin-bundled MCP server via uv (version-locked distribution)

`status: design · added: 2026-06-04 · source: user · related: TPL-2D8K, INS-4H8M, SYN-2M9P, DEV-1F9X`

## Problem (observable)

The `hallucinote-mcp` MCP server is distributed as a **PATH console-script** that the
user installs separately (`pip install -e ./hallucinote_mcp`). The plugin's
`plugin.json` declares `command: hallucinote-mcp` (a bare PATH lookup). This decouples
the *server version* from the *plugin version*: nothing guarantees the running server
matches the plugin/skills it was built against. The install skill papers over the PATH
fragility by writing an **absolute-path override** into `~/.claude.json` when the binary
isn't on PATH (engine in an unactivated venv) — `skills/ableton-mcp-install/SKILL.md`
L114-128, backed by `hallucinote_mcp/.../mcp_config.py`. That override is a workaround,
not a coupling.

User intent (2026-06-04, verbatim shape): *"tightly couple versioning so you always have
the same MCP server the repo is built against."*

## Success

`/plugin install hallucinote@hallucinote` (or `--plugin-dir .`) ships a server whose code
**and entire resolved dependency closure** match the installed plugin version, launched
with **no PATH dependency, no venv-activation ritual, no separate pip install of the
server**, reproducible per-platform, rebuilt only when the plugin updates.

## Out of scope

- `build.py`'s `import hallucinote` in the **songs** repo — a separate process with its
  own environment. Songs build against an installed/pinned engine (the framework⇄songs
  split, memory `project_root_contract_shipped`). The clean long-term answer is the engine
  on PyPI + a song-side version pin; until then a git/path pin. This item only aligns the
  pin so the two envs don't drift — it does not solve song-side engine delivery.
- Publishing the engine to PyPI (separate effort).
- Rewriting the MCP transport to drop the `mcp` SDK (rejected — see Decisions).

## Research basis (why uv, not "activate a venv")

Confirmed against primary docs (2026-06-04):

1. **Claude Code spawns stdio MCP servers with a sanitized environment** — the subprocess
   does **not** inherit the launching shell's `PATH` or activated virtualenv. So
   "activate the venv, then launch claude" is unreliable *by design*, not just inelegant.
   ([CC MCP docs](https://code.claude.com/docs/en/mcp), modelcontextprotocol/python-sdk#1520)
2. **`${CLAUDE_PLUGIN_ROOT}` is read-only/ephemeral; `${CLAUDE_PLUGIN_DATA}` is persistent
   and the documented home for Python virtualenvs/caches.** The blessed pattern for plugin
   deps: *"compares the bundled manifest against a copy in the data directory and
   reinstalls when they differ"* (docs ship the npm example; we do the uv analog).
   ([Plugins reference — env vars](https://code.claude.com/docs/en/plugins-reference#environment-variables))
3. **`uv` is the ecosystem standard for Python MCP servers** (Anthropic's MCP quickstart
   launches Python servers with `uv --directory … run`). `UV_PROJECT_ENVIRONMENT` exists
   precisely to redirect uv's venv out of a read-only project dir.
   ([uv projects](https://docs.astral.sh/uv/guides/projects/),
   [UV_PROJECT_ENVIRONMENT](https://pydevtools.com/handbook/how-to/how-to-customize-uvs-virtual-environment-location/))
4. **Cold-start timeout risk:** a slow first run (resolving numpy/scipy/librosa) can exceed
   the MCP init/probe timeout and **silently drop the server's tools** (CC#60224). Mitigated
   by pre-warming in a SessionStart hook + a committed lock + a generous startup timeout.
   > **Correction (follow-up, 2026-06-04 — `cold-start-timeout-fix.md`):** the "generous
   > timeout" below was placed in `plugin.json`'s per-server `"timeout"` field, which Claude
   > Code applies to **tool execution**, NOT the **startup** handshake. Startup is governed by
   > the `MCP_TIMEOUT` env var (ms, default **30000**); the per-server field never raised it,
   > so cold starts got 30 s and timed out anyway. The fix raises `MCP_TIMEOUT` via
   > `~/.claude/settings.json` `env` (install skill / committed dev settings). The pre-warm
   > hook also **cannot** prevent this on its own: SessionStart hooks *race* the MCP spawn and
   > can't block it — so the startup timeout, not the hook, is load-bearing.
5. **`mcp` cannot be vendored:** it pulls `pydantic-core` (Rust), `cryptography`, `rpds`,
   `_cffi_backend` — platform×Python-version `.so` files. Let pip/uv fetch the right wheel;
   never commit a `vendor/` tree. (verified against the local `.venv`)
6. **Plugin-root `.mcp.json` has a known env-expansion bug** (CC#9427) — declare the server
   in `plugin.json`'s inline `mcpServers`, not a plugin-root `.mcp.json`.

## Decision

**Bundle the server in the plugin; run it with uv from a lockfile into a `CLAUDE_PLUGIN_DATA`
environment.** Rejected alternatives:

- **Activate venv before claude** — broken by design (research #1).
- **PATH console-script (status quo)** — no version coupling, needs the abs-path-override hack.
- **Vendor `mcp`** — impossible (research #5).
- **Drop the `mcp` SDK, hand-roll MCP-over-stdio** — would shed ~14 deps incl. compiled
  ones, but is a real transport rewrite + ongoing spec maintenance. Not worth it.

## Architecture

**Mental model:** plugin *source* is read-only + versioned (`CLAUDE_PLUGIN_ROOT`); the
runtime *env* is persistent + writable (`CLAUDE_PLUGIN_DATA`); a manifest-diff hook rebuilds
the env only when the lock changes.

1. **uv workspace.** Root `pyproject.toml` gains `[tool.uv.workspace]` with members `.`
   (engine `hallucinote`) + `hallucinote_mcp` (server). A committed **`uv.lock`** pins the
   whole closure (mcp + numpy/scipy/librosa/pyroomacoustics/soundfile/pyloudnorm). The lock
   IS the coupling guarantee. **The server package keeps its `mcp`-only `dependencies`** —
   the engine reaches the runtime env by syncing the *workspace* (`--all-packages`), NOT by
   `hallucinote_mcp` hard-depending on `hallucinote`. This preserves the import-time
   isolation contract (memory `project_mcp_server_stdlib_only`): the server still starts
   stdlib+mcp-only; analysis lazy-imports the engine, which is present in the env.
2. **Pre-warm hook (plugin SessionStart).** Diff the bundled `uv.lock` against a copy in
   `CLAUDE_PLUGIN_DATA`; on mismatch `uv sync --frozen --all-packages` into
   `$CLAUDE_PLUGIN_DATA/venv` and copy the lock. Pre-warms before the server's init
   handshake → dodges CC#60224. This is the plugin analog of the repo's existing
   `.claude/hooks/session-start.sh` (which is remote-only and pip-based — left as-is for
   the dev repo's own sessions).
3. **Launch (plugin.json inline `mcpServers`).**
   ```jsonc
   "hallucinote-mcp": {
     "command": "uv",
     "args": ["run", "--frozen", "--all-packages",
              "--project", "${CLAUDE_PLUGIN_ROOT}", "hallucinote-mcp", "serve"],
     "env": { "UV_PROJECT_ENVIRONMENT": "${CLAUDE_PLUGIN_DATA}/venv" },
     "timeout": 60000
   }
   ```
   **Self-healing, NOT `--no-sync` (decided 2026-06-04, C1 Critic).** The launch omits
   `--no-sync` so it is correct *standalone*: if the C2 pre-warm hook hasn't run (first
   launch, or a hook↔spawn race) `uv run` builds the DATA env on demand. `--frozen` reads
   the committed lock from the read-only root (read is fine) and installs into
   `UV_PROJECT_ENVIRONMENT` (DATA) — it never writes the root and never network-resolves
   (the lock is authoritative). When the hook HAS pre-warmed, the launch is a near-instant
   consistency no-op. `--no-sync` would be marginally faster but FAILS when the env isn't
   pre-built, making correctness depend on hook ordering — rejected. Self-heal + a generous
   **`MCP_TIMEOUT`** (the startup timeout — see the Correction in Research #4; the per-server
   `"timeout"` field here is tool-exec only) + the C2 pre-warm hook are belt-and-suspenders;
   the only slow path is a genuinely-cold uv cache on first launch, which `MCP_TIMEOUT` covers
   (the hook can't — it races the spawn).
4. **uv is the one prerequisite.** Install-skill preflight detects it and offers
   `brew install uv` / the curl bootstrap. It *replaces* the venv ritual + the separate
   server pip-install + the abs-path-override hack.
5. **Install-skill simplification.** The `configure-mcp` abs-path-override path
   (`mcp_config.merge_server_entry` write branch) **retires** — the plugin launch no longer
   depends on PATH, so the `skip` case becomes universal. `mcp_config.py` + its contract
   tests (`test_mcp_config.py`) shrink to whatever (if anything) remains.
6. **Engine-pin alignment (drift guard).** The plugin ships the engine version it locked;
   the install/scaffold ensures the song repo pins the same version (couples to INS-4H8M
   drift-fingerprinting). Records the pin so server-env and song-env can't silently diverge.

## Risks & mitigations

- **Cold start** (heavy first sync) → pre-warm hook + committed lock + a generous
  **`MCP_TIMEOUT`** (settings `env`; the *startup* timeout — see the Correction in Research #4.
  The original `timeout: 60000` in `plugin.json` is tool-exec only and did NOT cover this).
  Residual: hook/MCP-spawn ordering race → `MCP_TIMEOUT` covers it (the hook can't block the
  spawn); if a build still overruns it, the env is warm by then → a `/mcp` reconnect is ~2 s,
  and the pre-warm hook emits SessionStart `additionalContext` so Claude proactively says so.
- **uv prerequisite** → one-time binary install, far less fragile than a per-launch ritual;
  preflight bootstraps.
- **Two environments** (plugin DATA env + song env) → uv's global wheel cache dedupes the
  heavy wheels on disk; align via the shared engine pin (#6).
- **Heavier server env** (numpy now always present) → conscious trade: analysis is
  first-class, so the env carries the engine; pre-warm makes start instant. The isolation
  contract is preserved at the *package-metadata* layer, not by starving the env.

## Verification

- **Local (this machine, no reinstall):** `UV_PROJECT_ENVIRONMENT=<tmp> uv sync --frozen
  --all-packages` builds the env; `uv run --no-sync … hallucinote-mcp serve` launches the
  server (clean startup) and `import hallucinote` resolves in that env. Proves the whole
  mechanism minus Claude-Code-spawns-it.
- **Reinstall-gated (operator):** install the plugin, restart Claude, confirm the
  `hallucinote-mcp` tools connect within the startup window (`MCP_TIMEOUT`) on first launch
  and after a plugin update (lock-change → rebuild) — and that if the first launch shows the
  server failed, a `/mcp` reconnect connects within ~2 s once the env is warm. Enqueue in
  `.prawduct/operator-verification.md`.
