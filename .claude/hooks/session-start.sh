#!/bin/bash
# SessionStart setup for Claude Code on the web.
#
# A fresh remote container has no Python deps, so the test suite can't run until
# the two editable packages + dev tooling are installed. This makes a web session
# test-ready automatically. Local devs manage their own venv (see README) — this
# is gated to remote sessions only.
#
# Run tests with:  python3 -m pytest -n auto -q
#   NOT the bare `pytest` on PATH — that's a separate uv-tool interpreter that does
#   NOT have these packages installed.
set -euo pipefail

# Remote (Claude Code on the web) only.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

# CLAUDE_PROJECT_DIR is set by Claude Code for real hook runs; fall back to the
# script's own location (.claude/hooks/) so the script is robust and locally testable.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${CLAUDE_PROJECT_DIR:-$(cd "$SCRIPT_DIR/../.." && pwd)}"

# Fast path: on a cached/resumed container the editable installs already exist.
if python3 -c "import hallucinote, pytest, hallucinote_mcp" 2>/dev/null; then
  echo "[session-start] hallucinote dev env already present — skipping install."
  exit 0
fi

echo "[session-start] installing hallucinote (editable) + dev tooling..."

# Root package + dev extras (pytest, pytest-xdist, hypothesis), into the python3
# interpreter. --no-build-isolation keeps it fast and avoids re-resolving the build
# backend on every fresh container.
pip install -e '.[dev]' --no-build-isolation -q

# The MCP package must be importable — hallucinote_mcp/tests/conftest.py does
# `from hallucinote_mcp import schema`. Install --no-deps: its full dev extras try to
# uninstall a debian-managed PyJWT (RECORD file not found) and abort.
pip install -e ./hallucinote_mcp --no-deps --no-build-isolation -q

# Best-effort: the hallucinote_mcp SERVER tests (test_server.py, test_resources.py)
# need the mcp SDK stack (mcp -> pydantic, anyio, ...). It won't install cleanly here
# (pip can't uninstall debian's PyJWT), so attempt it but NEVER fail setup over it —
# those two modules stay an accepted env gap; the main ~2214-test suite is unaffected.
if pip install mcp --no-build-isolation -q >/dev/null 2>&1; then
  echo "[session-start] mcp SDK installed (hallucinote_mcp server tests enabled)."
else
  echo "[session-start] note: mcp SDK unavailable; hallucinote_mcp server tests skipped (known env gap)."
fi

echo "[session-start] ready. Tests: python3 -m pytest -n auto -q  (use 'python3 -m pytest', not bare 'pytest')."
