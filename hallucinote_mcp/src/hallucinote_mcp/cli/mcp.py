"""``hallucinote-mcp`` config subcommands for the install / uninstall skills.

The skills call these instead of hand-editing JSON; the atomic mutations live in
tested Python (:mod:`mcp_config`):

* ``remove-mcp-config`` — clears any *legacy* ``mcpServers`` registrations a
  pre-plugin install wrote (since INS-7V2D the plugin provides the server, so
  install writes no ``mcpServers`` entry).
* ``set-startup-timeout`` / ``unset-startup-timeout`` — raise / remove
  ``env.MCP_TIMEOUT`` in the user's settings so a cold first ``uv sync`` doesn't
  blow Claude Code's default 30 s MCP *startup* window (CC#60224, INS-7V2D
  follow-up). The per-server ``plugin.json`` ``"timeout"`` governs tool execution,
  not startup; ``MCP_TIMEOUT`` does, and only settings ``env`` reaches the spawn.
"""
from __future__ import annotations

import argparse
import json
import pathlib

from .. import install_paths as P
from .. import mcp_config as mc


def _default_settings_path() -> pathlib.Path:
    """The user-scope settings file Claude Code injects ``env`` into MCP spawns from."""
    return pathlib.Path.home() / ".claude" / "settings.json"


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


def run_set_startup_timeout(args: list[str]) -> int:
    """Raise ``env.MCP_TIMEOUT`` to the floor in the user's settings (install)."""
    parser = argparse.ArgumentParser(prog="hallucinote-mcp set-startup-timeout")
    parser.add_argument(
        "--settings", default=None,
        help="Settings file to edit (default: ~/.claude/settings.json).",
    )
    try:
        ns = parser.parse_args(args)
    except SystemExit as exc:
        return int(exc.code or 2)

    path = pathlib.Path(ns.settings) if ns.settings else _default_settings_path()
    try:
        result = mc.ensure_startup_timeout(path)
    except mc.InstallError as exc:
        print(json.dumps({"ok": False, "error": str(exc), "path": str(path)}, indent=2))
        return 1

    print(json.dumps(result, indent=2))
    return 0


def run_unset_startup_timeout(args: list[str]) -> int:
    """Remove our ``env.MCP_TIMEOUT`` from the user's settings (uninstall)."""
    parser = argparse.ArgumentParser(prog="hallucinote-mcp unset-startup-timeout")
    parser.add_argument(
        "--settings", default=None,
        help="Settings file to edit (default: ~/.claude/settings.json).",
    )
    try:
        ns = parser.parse_args(args)
    except SystemExit as exc:
        return int(exc.code or 2)

    path = pathlib.Path(ns.settings) if ns.settings else _default_settings_path()
    try:
        result = mc.unset_startup_timeout(path)
    except mc.InstallError as exc:
        print(json.dumps({"ok": False, "error": str(exc), "path": str(path)}, indent=2))
        return 1

    print(json.dumps(result, indent=2))
    return 0


__all__ = [
    "run_remove_mcp_config",
    "run_set_startup_timeout",
    "run_unset_startup_timeout",
]
