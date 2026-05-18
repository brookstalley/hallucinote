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
    pkg_root = P.package_root()
    return {
        "package": {
            "version": __version__,
            "root": str(pkg_root),
            # Structured excludes — top-level files are anchored to the
            # package root; any-position dirs/globs match anywhere in the
            # tree. Emitting the structure (rather than a flat list) keeps
            # the install skill from having to re-derive the anchoring.
            "remote_script_exclude": {
                "top_level_files": list(P.REMOTE_SCRIPT_EXCLUDE_TOP_LEVEL_FILES),
                "dirs_any": list(P.REMOTE_SCRIPT_EXCLUDE_DIRS_ANY),
                "file_globs_any": list(P.REMOTE_SCRIPT_EXCLUDE_FILE_GLOBS_ANY),
            },
            # Pre-rendered command arguments — the install skill interpolates
            # these directly into the rsync / robocopy invocation so platform
            # quirks (rsync's leading-slash anchor, robocopy's full-path
            # /XF anchor) stay in tested Python instead of fragile markdown.
            "rsync_exclude_args": P.rsync_exclude_args(),
            "robocopy_exclude_args": P.robocopy_exclude_args(pkg_root),
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
