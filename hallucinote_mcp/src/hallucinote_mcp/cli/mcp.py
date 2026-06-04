"""``hallucinote-mcp remove-mcp-config`` — the uninstall config-cleanup subcommand.

The uninstall skill calls this instead of hand-editing JSON: the atomic delete
lives in tested Python (:mod:`mcp_config`). There is no longer an *install*
counterpart — since INS-7V2D the ``hallucinote`` plugin provides the server via
its bundled uv launch, so the install skill never writes an ``mcpServers`` entry.
This command still clears any *legacy* registrations a pre-plugin install wrote.
"""
from __future__ import annotations

import argparse
import json

from .. import install_paths as P
from .. import mcp_config as mc


def run_remove_mcp_config(args: list[str]) -> int:
    """Delete every ``hallucinote-mcp`` registration across all config scopes."""
    parser = argparse.ArgumentParser(prog="hallucinote-mcp remove-mcp-config")
    parser.add_argument("--cwd", default=None, help="Project dir to scan (default: cwd).")
    try:
        ns = parser.parse_args(args)
    except SystemExit as exc:
        return int(exc.code or 2)

    removed: list[dict] = []
    try:
        for entry in P.existing_mcp_config_files(cwd=ns.cwd):
            if mc.delete_entry(entry.path, tuple(entry.json_pointer)):
                removed.append(entry.as_dict())
    except mc.InstallError as exc:
        print(json.dumps({"ok": False, "error": str(exc), "removed": removed}, indent=2))
        return 1

    print(json.dumps({"ok": True, "removed": removed}, indent=2))
    return 0


__all__ = ["run_remove_mcp_config"]
