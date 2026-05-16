"""``hallucinote-mcp serve`` — boots the FastMCP server.

Referenced from ``.mcp.json`` once the MCP config has been written by the
install skill::

    {
      "mcpServers": {
        "hallucinote-mcp": {
          "command": "hallucinote-mcp",
          "args": ["serve"]
        }
      }
    }
"""
from __future__ import annotations

import logging
import sys

from ..server import create_server


def run_serve(args: list[str]) -> int:
    """Start the FastMCP server. Returns an exit code on shutdown."""
    if args and args[0] in ("-h", "--help"):
        print(
            "Usage: hallucinote-mcp serve\n"
            "\n"
            "Starts the FastMCP server over stdio. Used by .mcp.json — there\n"
            "are no flags. Configure host/port via the install skill.\n"
        )
        return 0

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        stream=sys.stderr,
    )
    logger = logging.getLogger("hallucinote_mcp")
    logger.info("hallucinote-mcp starting")

    server = create_server()
    server.run()  # blocks; FastMCP handles its own stdio loop
    return 0


__all__ = ["run_serve"]
