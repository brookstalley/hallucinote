"""CLI entry points.

Console scripts declared in ``pyproject.toml``:
  - ``hallucinote-mcp serve`` — start the FastMCP server (runtime entry point
    referenced from ``.mcp.json``).

Install is skill-mediated, not console-script-mediated: see the
``ableton-mcp-install`` skill in the Hallucinote repo's ``skills/``.
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
    if command == "install-remote-script":
        from .install import run_install_remote_script

        return run_install_remote_script(rest)
    if command == "install-analyzer":
        from .install import run_install_analyzer

        return run_install_analyzer(rest)
    if command == "uninstall-remote-script":
        from .install import run_uninstall_remote_script

        return run_uninstall_remote_script(rest)
    if command == "uninstall-analyzer":
        from .install import run_uninstall_analyzer

        return run_uninstall_analyzer(rest)
    if command == "configure-mcp":
        from .mcp import run_configure_mcp

        return run_configure_mcp(rest)
    if command == "remove-mcp-config":
        from .mcp import run_remove_mcp_config

        return run_remove_mcp_config(rest)
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
        "  serve                  Start the FastMCP server (used by .mcp.json)\n"
        "  preflight              Print install / uninstall detection report (JSON)\n"
        "  install-remote-script  Atomically vendor the Remote Script into Live's User Library\n"
        "  install-analyzer       Atomically install HallucinoteAnalyzer.amxd\n"
        "  uninstall-remote-script  Remove the vendored Remote Script\n"
        "  uninstall-analyzer     Remove the installed analyzer device\n"
        "  configure-mcp          Write/skip the hallucinote-mcp MCP config entry\n"
        "  remove-mcp-config      Delete hallucinote-mcp from all config scopes\n"
        "  version                Print the package version\n"
        "  help                   Show this message\n"
        "\n"
        "Install is skill-mediated: open Claude Code in the Hallucinote repo,\n"
        "then run /ableton-mcp-install to set up the Remote Script and MCP\n"
        "config. The skill body lives at skills/ableton-mcp-install/.\n",
        file=out,
    )


__all__ = ["main"]
