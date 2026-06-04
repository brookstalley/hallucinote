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
    server_version = __version__
    remote_script_candidates: list[dict] = []
    for cand in P.candidate_user_libraries():
        rs_dir = P.remote_script_install_dir(cand)
        installed = (rs_dir / "hallucinote_mcp").is_dir()
        vendored_version = (
            P.installed_remote_script_version(cand) if installed else None
        )
        remote_script_candidates.append({
            "user_library": str(cand),
            "remote_script_dir": str(rs_dir),
            "installed": installed,
            "version": vendored_version,
            "matches_mcp_server": (
                vendored_version == server_version if vendored_version else None
            ),
        })
    return {
        "package": {
            "version": server_version,
            "root": str(pkg_root),
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
        # MCP/Remote Script version-match per User Library candidate.
        # Surfaces drift BEFORE the runtime handshake fires — the install
        # skill uses ``matches_mcp_server`` to suggest re-running install
        # when the vendored copy is stale (W12-D MCP/Live drift visibility).
        "remote_script": {
            "candidates": remote_script_candidates,
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
