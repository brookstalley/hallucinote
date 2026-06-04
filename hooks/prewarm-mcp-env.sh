#!/bin/bash
# SessionStart pre-warm for the bundled hallucinote-mcp server's uv environment.
#
# INS-7V2D C2. The plugin launches the MCP server with
#   uv run --frozen --all-packages --project ${CLAUDE_PLUGIN_ROOT} hallucinote-mcp serve
#   (env UV_PROJECT_ENVIRONMENT=${CLAUDE_PLUGIN_DATA}/venv)
# A genuinely-cold first build (numpy/scipy/librosa/pyroomacoustics/...) can exceed
# the MCP init timeout and SILENTLY DROP the server's tools (CC#60224). This hook
# pre-builds the DATA env BEFORE the server's init handshake, so the launch is a
# near-instant consistency no-op. It is the plugin analog of the dev repo's own
# .claude/hooks/session-start.sh (which is remote-only + pip-based).
#
# Belt-and-suspenders, not load-bearing: the launch is self-healing (NOT --no-sync),
# so it stays correct even if this hook is skipped, races the spawn, or fails. This
# script therefore NEVER fails the session — it best-effort warms and exits 0.
#
# Diff/rebuild contract (the manifest-diff pattern, design §2): the env is rebuilt
# only when the bundled lock differs from the last-synced copy in CLAUDE_PLUGIN_DATA.
#
# Proactive heads-up (INS-7V2D follow-up): SessionStart hooks RACE the MCP spawn —
# they cannot block it — so on a cold build the spawn can lose the race and show
# the server "failed" in /mcp even though this hook then finishes the env. After a
# cold build we emit a SessionStart `additionalContext` JSON object so Claude can
# proactively tell the user to /mcp-reconnect (warm = ~2 s). Plain stdout is NOT
# injected into Claude's context for SessionStart — only the JSON object is — so the
# build-success branch must print ONLY that JSON (human progress goes to stderr).
set -uo pipefail

# CLAUDE_PLUGIN_ROOT (read-only plugin payload) and CLAUDE_PLUGIN_DATA (persistent,
# writable) are exported to plugin hook commands.
ROOT="${CLAUDE_PLUGIN_ROOT:-}"
DATA="${CLAUDE_PLUGIN_DATA:-}"
if [ -z "$ROOT" ] || [ -z "$DATA" ]; then
  echo "[hallucinote prewarm] CLAUDE_PLUGIN_ROOT/DATA unset — skipping (launch self-heals)."
  exit 0
fi

LOCK_SRC="$ROOT/uv.lock"        # the bundled, version-coupling lock (authoritative)
VENV="$DATA/venv"               # matches plugin.json's UV_PROJECT_ENVIRONMENT
LOCK_COPY="$DATA/uv.lock"       # last-synced copy; the diff sentinel

if [ ! -f "$LOCK_SRC" ]; then
  echo "[hallucinote prewarm] no uv.lock at $LOCK_SRC — skipping (launch self-heals)."
  exit 0
fi

# uv is the one prerequisite. If it's absent the install skill's preflight surfaces
# it; warming is a best-effort no-op here.
if ! command -v uv >/dev/null 2>&1; then
  echo "[hallucinote prewarm] uv not on PATH — skipping (install-skill preflight covers this)."
  exit 0
fi

# Fast path: the env is already built against THIS exact lock — nothing to do.
if [ -d "$VENV" ] && [ -f "$LOCK_COPY" ] && cmp -s "$LOCK_SRC" "$LOCK_COPY"; then
  echo "[hallucinote prewarm] MCP env already warm for the current lock — skipping."
  exit 0
fi

# Progress goes to stderr (debug log) — NOT stdout — so the success branch can emit
# a clean SessionStart additionalContext JSON object as its only stdout.
echo "[hallucinote prewarm] building the hallucinote-mcp env (first run or lock changed)…" >&2
mkdir -p "$DATA"
_start=$SECONDS
if UV_PROJECT_ENVIRONMENT="$VENV" uv sync --frozen --all-packages --project "$ROOT" 1>&2; then
  # Record the lock we just synced against so the next session can fast-path.
  cp "$LOCK_SRC" "$LOCK_COPY"
  _elapsed=$((SECONDS - _start))
  echo "[hallucinote prewarm] MCP env ready (~${_elapsed}s)." >&2
  # Hand Claude a proactive heads-up. The message is fixed text + one integer, with
  # no characters that need JSON-escaping (no quotes/backslashes/newlines).
  _ctx="[Hallucinote] The bundled MCP server environment was just built (first run or plugin update; ~${_elapsed}s). On a cold build the MCP connection can race the build and show hallucinote-mcp as failed in /mcp. If the hallucinote-mcp tools are not available this session, tell the user the environment is ready now and to run /mcp to reconnect the hallucinote-mcp server (it connects in ~2s once warm; a full Claude Code restart also works). This only happens after a build — normal sessions start instantly."
  printf '{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"%s"}}\n' "$_ctx"
else
  # Never fail the session — the self-healing launch retries the sync on demand.
  echo "[hallucinote prewarm] sync failed; the server launch will retry on demand."
fi
exit 0
