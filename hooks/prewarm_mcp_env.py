#!/usr/bin/env python3
"""SessionStart pre-warm for the bundled hallucinote-mcp server's uv environment.

INS-7V2D C2 — Python port (cross-platform: bash isn't guaranteed on Windows, and
`python` vs `python3` differs by OS, so hooks.json launches this via the one
consistently-named hard prereq, `uv run --no-project python`).

The plugin launches the MCP server with
  uv run --frozen --all-packages --project ${CLAUDE_PLUGIN_ROOT} hallucinote-mcp serve
  (env UV_PROJECT_ENVIRONMENT=${CLAUDE_PLUGIN_DATA}/venv)
A genuinely-cold first build (numpy/scipy/librosa/pyroomacoustics/...) can exceed
the MCP init timeout and SILENTLY DROP the server's tools (CC#60224). This hook
pre-builds the DATA env BEFORE the server's init handshake, so the launch is a
near-instant consistency no-op.

Belt-and-suspenders, not load-bearing: the launch is self-healing (NOT --no-sync),
so it stays correct even if this hook is skipped, races the spawn, or fails. This
script therefore NEVER fails the session — it best-effort warms and exits 0. The
env is rebuilt only when the bundled lock differs from the last-synced copy in
CLAUDE_PLUGIN_DATA (the manifest-diff pattern).

SessionStart contract: a hook's plain stdout IS injected into Claude's context, so
EVERY branch keeps human/progress/skip chatter on stderr; only the build-success
branch prints its additionalContext JSON object on stdout.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time


def _log(msg: str) -> None:
    print(msg, file=sys.stderr)


def _same_bytes(a: str, b: str) -> bool:
    try:
        with open(a, "rb") as fa, open(b, "rb") as fb:
            return fa.read() == fb.read()
    except OSError:
        return False


def main() -> int:
    # CLAUDE_PLUGIN_ROOT (read-only plugin payload) and CLAUDE_PLUGIN_DATA
    # (persistent, writable) are exported to plugin hook commands.
    root = os.environ.get("CLAUDE_PLUGIN_ROOT", "")
    data = os.environ.get("CLAUDE_PLUGIN_DATA", "")
    if not root or not data:
        _log("[hallucinote prewarm] CLAUDE_PLUGIN_ROOT/DATA unset — skipping (launch self-heals).")
        return 0

    lock_src = os.path.join(root, "uv.lock")   # the bundled version-coupling lock
    venv = os.path.join(data, "venv")           # matches plugin.json UV_PROJECT_ENVIRONMENT
    lock_copy = os.path.join(data, "uv.lock")   # last-synced copy; the diff sentinel

    if not os.path.isfile(lock_src):
        _log(f"[hallucinote prewarm] no uv.lock at {lock_src} — skipping (launch self-heals).")
        return 0

    # uv is the one prerequisite. If it's absent the install skill's preflight
    # surfaces it; warming is a best-effort no-op here.
    if shutil.which("uv") is None:
        _log("[hallucinote prewarm] uv not on PATH — skipping (install-skill preflight covers this).")
        return 0

    # Fast path: the env is already built against THIS exact lock — nothing to do.
    if os.path.isdir(venv) and os.path.isfile(lock_copy) and _same_bytes(lock_src, lock_copy):
        _log("[hallucinote prewarm] MCP env already warm for the current lock — skipping.")
        return 0

    # Progress to stderr — NOT stdout — so the success branch can emit a clean
    # SessionStart additionalContext JSON object as its only stdout.
    _log("[hallucinote prewarm] building the hallucinote-mcp env (first run or lock changed)…")
    os.makedirs(data, exist_ok=True)
    start = time.monotonic()
    env = dict(os.environ)
    env["UV_PROJECT_ENVIRONMENT"] = venv
    try:
        # Route uv's own stdout to OUR stderr so success-branch stdout stays clean.
        result = subprocess.run(
            ["uv", "sync", "--frozen", "--all-packages", "--project", root],
            env=env, stdout=sys.stderr, stderr=sys.stderr,
        )
        ok = result.returncode == 0
    except OSError:
        ok = False

    if ok:
        try:
            shutil.copyfile(lock_src, lock_copy)
        except OSError:
            pass
        elapsed = int(time.monotonic() - start)
        _log(f"[hallucinote prewarm] MCP env ready (~{elapsed}s).")
        ctx = (
            "[Hallucinote] The bundled MCP server environment was just built "
            f"(first run or plugin update; ~{elapsed}s). On a cold build the MCP "
            "connection can race the build and show hallucinote-mcp as failed in /mcp. "
            "If the hallucinote-mcp tools are not available this session, tell the user "
            "the environment is ready now and to run /mcp to reconnect the hallucinote-mcp "
            "server (it connects in ~2s once warm; a full Claude Code restart also works). "
            "This only happens after a build — normal sessions start instantly."
        )
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": ctx,
            }
        }))
    else:
        # Never fail the session — the self-healing launch retries the sync on demand.
        _log("[hallucinote prewarm] sync failed; the server launch will retry on demand.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
