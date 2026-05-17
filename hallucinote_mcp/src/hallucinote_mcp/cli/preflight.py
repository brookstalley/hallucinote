"""``hallucinote-mcp preflight`` — JSON report consumed by the install/uninstall skills.

Centralizes every detection the skills need so the SKILL.md bodies only
have to invoke one command and inspect the result. Pure read-only; no
filesystem mutation. Designed to be safe to run repeatedly.
"""
from __future__ import annotations

import json
import sys

from .. import __version__
from .. import install_paths as P


def _build_report() -> dict:
    """Collect every detection the install / uninstall skills consume.

    Values are JSON-encodable: ``Path``s become strings, ``None`` is preserved
    so the consumer can tell "not detected" from "empty string".
    """
    cmd_path, cmd_on_path = P.hallucinote_mcp_command()
    return {
        "package": {
            "version": __version__,
            "root": str(P.package_root()),
            "remote_script_exclude": list(P.REMOTE_SCRIPT_EXCLUDE),
        },
        "user_library": {
            "default": str(P.default_user_library()),
            "default_exists": P.default_user_library().exists(),
            "candidates": [
                {"path": str(c), "exists": c.exists()}
                for c in P.candidate_user_libraries()
            ],
        },
        "live": {
            "installed_versions": P.installed_live_versions(),
            "is_running": P.live_is_running(),
        },
        "mcp_command": {
            "path": str(cmd_path) if cmd_path else None,
            "on_path": cmd_on_path,
        },
        "mcp_configs": {
            "local_path": str(P.mcp_config_local_path()),
            "global_path": str(P.mcp_config_global_path()),
            "containing_entry": [e.as_dict() for e in P.existing_mcp_config_files()],
            "malformed": [str(p) for p in P.malformed_mcp_config_files()],
        },
        "platform": sys.platform,
    }


def run_preflight(args: list[str]) -> int:
    """Print a JSON detection report. Exit 0 always — failure modes live in the report."""
    if args and args[0] in ("-h", "--help"):
        print(
            "Usage: hallucinote-mcp preflight\n"
            "\n"
            "Prints a JSON report of everything the install / uninstall skills\n"
            "need to make decisions: package version, User Library candidates,\n"
            "installed Live versions, whether Live is running, and which MCP\n"
            "config files already mention hallucinote-mcp.\n"
        )
        return 0

    print(json.dumps(_build_report(), indent=2))
    return 0


__all__ = ["run_preflight"]
