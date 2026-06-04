"""``hallucinote-mcp configure-mcp`` / ``remove-mcp-config`` — MCP config subcommands.

The install/uninstall skills call these instead of hand-editing JSON: the decision
(skip vs write, bare vs absolute, which scope) and the atomic merge/delete live in
tested Python (:mod:`mcp_config`). The skill supplies ``--registered`` from what
``/mcp`` shows it (which sees plugin-provided servers config-file scanning can't).
"""
from __future__ import annotations

import argparse
import json

from .. import install_paths as P
from .. import mcp_config as mc


def run_configure_mcp(args: list[str]) -> int:
    """Plan and (if needed) write the ``hallucinote-mcp`` MCP config entry."""
    parser = argparse.ArgumentParser(
        prog="hallucinote-mcp configure-mcp",
        description="Decide and apply the hallucinote-mcp MCP config entry.",
    )
    parser.add_argument("--scope", choices=("user", "project"), default="user")
    parser.add_argument("--cwd", default=None, help="Project dir for project scope (default: cwd).")
    parser.add_argument(
        "--registered", choices=("true", "false"), required=True,
        help="Whether /mcp already lists hallucinote-mcp (incl. plugin-provided).",
    )
    try:
        ns = parser.parse_args(args)
    except SystemExit as exc:
        return int(exc.code or 2)

    cmd_path, on_path = P.hallucinote_mcp_command()
    plan = mc.plan_mcp_config(
        command_path=cmd_path,
        on_path=on_path,
        already_registered=(ns.registered == "true"),
        scope=ns.scope,
        cwd=ns.cwd,
    )

    if plan.action == "error":
        print(json.dumps({"ok": False, "action": plan.action, "reason": plan.reason}, indent=2))
        return 1
    if plan.action == "skip":
        print(json.dumps({"ok": True, "action": plan.action, "reason": plan.reason}, indent=2))
        return 0

    try:
        existing = mc.read_config(plan.path)
        merged = mc.merge_server_entry(existing, plan.command, plan.args)
        mc.write_config_atomic(plan.path, merged)
    except mc.InstallError as exc:
        print(json.dumps({"ok": False, "action": "write", "error": str(exc)}, indent=2))
        return 1

    print(json.dumps({
        "ok": True,
        "action": plan.action,
        "path": str(plan.path),
        "command": plan.command,
        "reason": plan.reason,
    }, indent=2))
    return 0


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


__all__ = ["run_configure_mcp", "run_remove_mcp_config"]
