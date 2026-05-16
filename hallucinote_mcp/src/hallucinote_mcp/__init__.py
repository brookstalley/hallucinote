"""hallucinote-mcp — unified Ableton Live MCP server.

Ten unified tools with action dispatch, designed for low-context-cost agent
interaction. See ``docs/mcp-tool-design.md`` in the parent repo for the full
architectural rationale.
"""
from __future__ import annotations

__version__ = "0.1.0"

# Re-export the tool registry constants for convenience.
from . import schema as schema  # noqa: F401
