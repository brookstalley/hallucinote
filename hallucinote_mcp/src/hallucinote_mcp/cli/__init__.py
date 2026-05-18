"""CLI entry points.

Console scripts declared in ``pyproject.toml``:
  - ``hallucinote-mcp serve`` — start the FastMCP server (runtime entry point
    referenced from ``.mcp.json``).

Install is skill-mediated, not console-script-mediated: see the
``ableton-install-mcp`` skill in the Hallucinote repo's ``.claude/skills/``.
"""
from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    """Top-level CLI dispatcher.

    Returns a process exit code rather than calling sys.exit, so the function
    is testable. The console-script entry in ``pyproject.toml`` wraps this
    with the usual ``sys.exit(main())`` pattern.
    """
    args = sys.argv[1:] if argv is None else list(argv)
    if not args or args[0] in ("-h", "--help", "help"):
        _print_help()
        return 0

    command = args[0]
    rest = args[1:]

    if command == "serve":
        from .serve import run_serve

        return run_serve(rest)
    if command == "preflight":
        from .preflight import run_preflight

        return run_preflight(rest)
    if command == "version":
        from .. import __version__

        print(__version__)
        return 0

    print(f"unknown command: {command!r}", file=sys.stderr)
    print("", file=sys.stderr)
    _print_help(out=sys.stderr)
    return 2


def _print_help(out=None) -> None:
    out = out or sys.stdout
    print(
        "hallucinote-mcp — Ableton Live MCP server\n"
        "\n"
        "Commands:\n"
        "  serve              Start the FastMCP server (used by .mcp.json)\n"
        "  preflight          Print install / uninstall detection report (JSON)\n"
        "  version            Print the package version\n"
        "  help               Show this message\n"
        "\n"
        "Install is skill-mediated: open Claude Code in the Hallucinote repo,\n"
        "then run /ableton-install-mcp to set up the Remote Script and MCP\n"
        "config. The skill body lives at .claude/skills/ableton-install-mcp/.\n",
        file=out,
    )


__all__ = ["main"]
