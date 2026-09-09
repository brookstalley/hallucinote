"""Hallucinote: DB-backed MIDI authoring with Ableton sync via MCP."""

# Keep in lockstep with pyproject.toml [project].version and
# .claude-plugin/plugin.json "version" — pyproject is the canonical source of
# truth; tests/unit/test_version_parity.py fails if these drift. (NOT the same
# as the MCP server's hallucinote_mcp.BASE_VERSION, which is a decoupled
# wire-protocol epoch — bumping it per-release would force every Live user to
# re-vendor the Remote Script.)
from __future__ import annotations
__version__ = "1.8.6"
