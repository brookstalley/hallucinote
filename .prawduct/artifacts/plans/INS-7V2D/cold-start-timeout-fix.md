# INS-7V2D follow-up — MCP cold-start timeout fix

**Type:** bugfix (on shipped v0.9.3). **Size:** medium. **Branch:** `fix/mcp-startup-timeout-INS-7V2D`.

## Confidence check

1. **Problem (observed):** The plugin-bundled `hallucinote-mcp` server fails to connect on a
   cold start. The connection log shows the server doing a full cold `uv` build (numpy/scipy/
   librosa/llvmlite ~70 MiB) during the spawn, and the connection **times out at 30000ms**
   despite `plugin.json` declaring `"timeout": 60000`.
2. **Root cause:** the INS-7V2D design intended "a generous per-server timeout" to cover cold
   start, but put it in `plugin.json`'s per-server `"timeout"` field — which Claude Code applies
   to **tool execution**, NOT the **startup/connection** handshake. Startup is governed by the
   `MCP_TIMEOUT` env var (default **30000ms**), which was never raised. So the intended 60s
   safety net never existed for startup. (Verified empirically: log shows 30000ms; and via
   Claude Code docs on `MCP_TIMEOUT` vs `MCP_TOOL_TIMEOUT` vs per-server `timeout`.)
   The SessionStart pre-warm hook cannot prevent this: SessionStart hooks **race** the MCP
   spawn and cannot be made to block it (confirmed via docs). The pre-warm is best-effort, the
   timeout must be load-bearing.
3. **Success:**
   - A cold first run / post-plugin-update either connects within a generous startup window, or
     — if it still loses the race — the user is proactively guided to reconnect (env is warm by
     then; warm connect is ~2.3s, measured).
   - This dev repo is fixed via committed `.claude/settings.json` `env.MCP_TIMEOUT`.
   - End users get the fix: `/ableton-mcp-install` writes `MCP_TIMEOUT` into `~/.claude/settings.json`.
   - Docs **highlight** the first-run build cost (~1–2 min) + the `/mcp` reconnect recovery.
   - The pre-warm hook plumbs a proactive heads-up to Claude (SessionStart `additionalContext`)
     so Claude can tell the user when a cold build just happened and the server may need a reconnect.
   - INS-7V2D design.md corrected (timeout-field semantics).
   - Regression test on the new config op.
4. **Out of scope (explicit):**
   - Dropping `--all-packages` — falsified: `handlers/analysis.py` lazily imports the engine
     (`hallucinote.audio` → numpy/scipy/librosa) when an analysis tool runs; dropping it flips
     `_HAS_HALLUCINOTE` to False and silently breaks masking/reverb/loudness. `--all-packages`
     is a deliberate, documented design choice.
   - The genuine build-shrink (drop librosa → removes numba/llvmlite/scikit-learn) — user
     declined (the raised timeout makes build size moot; warm start is 2.3s either way).
   - Changing `plugin.json`'s per-server `"timeout"` *value* — it's a tool-exec cap; no evidence
     it's wrong. Only its DOC meaning is corrected.
5. **Requirements Confidence: High** — root cause is connection-log-proven (observed 30000ms
   startup timeout) and corroborated by Claude Code's documented `MCP_TIMEOUT` vs per-server
   `timeout` semantics; the two competing explanations (drop `--all-packages`, shrink the build)
   are falsified in item 4. Residual risk is operational (cold-build duration variance), bounded
   by the 3-min floor.

## Decision record

- **`MCP_TIMEOUT` floor = 180000ms (3 min).** Covers the user's stated "couple of minutes" cold
  build with margin; bounds a genuinely-broken-server wait at 3 min. Pure safety net — warm
  starts ignore it (connect in ~2.3s). Single source of truth: `STARTUP_TIMEOUT_FLOOR_MS`.
- **Mechanism = settings.json `env`** (not plugin.json) — the only channel that reaches a
  plugin-provided MCP server's spawn AND controls the *startup* timeout. Plugin manifests can't
  set `MCP_TIMEOUT`, so end users need the install skill to write it (user scope, applies
  wherever they author).
- **Config op, not assistant-prose** — idempotent/atomic, never downgrades a higher existing
  value; matches the existing `mcp_config.py` pattern; gives us the regression test.
- **Blocking pre-warm + additionalContext** (not async/rewake) — reliable; additionalContext
  reaches Claude right after the hook returns.

## Chunks (one work cycle; cumulative Critic at the end)

- [x] **C1 — startup-timeout config op + dev settings.** `STARTUP_TIMEOUT_FLOOR_MS`,
  `ensure_startup_timeout()` / `unset_startup_timeout()` in `mcp_config.py`; CLI
  `set-startup-timeout` / `unset-startup-timeout` + help; added `env.MCP_TIMEOUT` to this repo's
  `.claude/settings.json`. Unit tests (`test_startup_timeout.py`, 22).
- [x] **C2 — pre-warm proactive notification.** Cold-build path emits SessionStart
  `additionalContext` JSON (build happened + reconnect guidance); `hooks.json` `statusMessage`
  sets the "first run 1–2 min" expectation. Extended `test_prewarm_hook.py` for the JSON contract.
- [x] **C3 — skills + docs.** install skill: calls `set-startup-timeout` + **highlights** the
  first-run build cost & reconnect; uninstall skill: `unset-startup-timeout`; corrected
  `design.md` timeout semantics; enqueued operator-verification.

## Status

All three chunks built. Full suite **2800 passed, 268 skipped** (audio stack skipped — change is
config/CLI/docs/hook only). Warm MCP handshake measured ~2.3 s. Cumulative Critic + commit next.

## Done when

All tests pass (incl. new), `/critic cumulative` clean, design.md coherent, build plan Status
updated. (Plugin version bump / release is a separate step — not pre-bumped here.)
