"""MCP-config *decision* and *mutation* for the install / uninstall skills.

``install_paths.py`` already *detects* config state (where ``hallucinote-mcp`` is
registered, which files are malformed, whether the command is on PATH). This
module decides **what to do** about it and performs the write/delete atomically.

The decision (:func:`plan_mcp_config`) is a pure truth table keyed on two facts —
whether the command resolves on PATH and whether the server is already registered
(the skill reads the latter from ``/mcp``, which sees plugin-provided servers that
config-file scanning cannot). It deliberately does **not** try to detect "is this
plugin-provided?" — when the registered command is on PATH it works regardless of
who registered it; when it isn't, a user-scope absolute-path entry dominates a
plugin-provided one by Claude Code's scope precedence (Local > Project > User >
Plugin). Stdlib-only.
"""
from __future__ import annotations

import dataclasses
import json
import os
import pathlib

from .install_ops import InstallError
from .install_paths import mcp_config_global_path, mcp_config_local_path

SERVER_NAME = "hallucinote-mcp"
DEFAULT_ARGS: tuple[str, ...] = ("serve",)


@dataclasses.dataclass(frozen=True)
class McpConfigPlan:
    """The decided action for the ``hallucinote-mcp`` config entry.

    ``action`` is ``"skip"`` (already works), ``"write"`` (merge an entry at
    ``path`` using ``command``/``args``), or ``"error"`` (can't proceed — the
    command isn't installed). ``reason`` is a human-readable explanation the
    skill surfaces to the user.
    """

    action: str
    path: pathlib.Path | None
    command: str | None
    args: tuple[str, ...]
    reason: str


def _scope_path(scope: str, cwd: pathlib.Path | str | None) -> pathlib.Path:
    if scope == "user":
        return mcp_config_global_path()
    if scope == "project":
        return mcp_config_local_path(pathlib.Path(cwd) if cwd is not None else None)
    raise InstallError(f"unknown MCP config scope {scope!r} (expected 'user' or 'project').")


def plan_mcp_config(
    *,
    command_path: pathlib.Path | str | None,
    on_path: bool,
    already_registered: bool,
    scope: str = "user",
    cwd: pathlib.Path | str | None = None,
) -> McpConfigPlan:
    """Decide whether/where/what to write for the ``hallucinote-mcp`` MCP entry.

    The five-row truth table (see the module docstring for the rationale):

    ===============  =================  ========  ====================================
    command_path     already_registered on_path   plan
    ===============  =================  ========  ====================================
    None             -                  -         error (pip install, re-run)
    set              True               True      skip (it already launches)
    set              True               False     write absolute path at USER scope
    set              False              True       write bare command at chosen scope
    set              False              False     write absolute path at chosen scope
    ===============  =================  ========  ====================================
    """
    if command_path is None:
        return McpConfigPlan(
            "error", None, None, (),
            "hallucinote-mcp is not installed — `pip install hallucinote-mcp` and re-run.",
        )
    if already_registered and on_path:
        return McpConfigPlan(
            "skip", None, None, (),
            "hallucinote-mcp is already registered and resolves on PATH — nothing to write.",
        )
    if already_registered and not on_path:
        return McpConfigPlan(
            "write", mcp_config_global_path(), str(command_path), DEFAULT_ARGS,
            "the registered command is not on PATH — writing an absolute-path override at "
            "user scope (dominates a plugin-provided entry by scope precedence).",
        )
    target = _scope_path(scope, cwd)
    if on_path:
        return McpConfigPlan(
            "write", target, SERVER_NAME, DEFAULT_ARGS,
            f"writing the bare command at {scope} scope.",
        )
    return McpConfigPlan(
        "write", target, str(command_path), DEFAULT_ARGS,
        f"command not on PATH — writing its absolute path at {scope} scope.",
    )


def read_config(path: pathlib.Path | str) -> dict:
    """Read a config file as a dict; ``{}`` if absent; refuse if malformed."""
    path = pathlib.Path(path)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise InstallError(f"refusing to edit malformed config {path}: {exc}") from exc
    return data if isinstance(data, dict) else {}


def merge_server_entry(
    config: dict,
    command: str,
    args: tuple[str, ...] | list[str] = DEFAULT_ARGS,
) -> dict:
    """Return a new config dict with ``hallucinote-mcp`` set, siblings preserved."""
    merged = dict(config) if config else {}
    servers = dict(merged.get("mcpServers") or {})
    servers[SERVER_NAME] = {"command": command, "args": list(args)}
    merged["mcpServers"] = servers
    return merged


def write_config_atomic(path: pathlib.Path | str, config: dict) -> None:
    """Write ``config`` as pretty JSON via temp-file + ``os.replace``.

    A crash mid-write never corrupts the live config (and ``~/.claude.json``
    carries the user's whole project history — a partial write would be costly).
    """
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        tmp.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def delete_entry(path: pathlib.Path | str, json_pointer: tuple[str, ...]) -> bool:
    """Delete the entry at ``json_pointer`` and rewrite atomically.

    ``json_pointer`` is the key chain from :class:`install_paths.MCPConfigEntry`
    (e.g. ``("mcpServers", "hallucinote-mcp")`` or
    ``("projects", "<cwd>", "mcpServers", "hallucinote-mcp")``). A safe no-op
    (returns ``False``) when the file or the entry is absent — uninstall is
    idempotent. Refuses a malformed file.
    """
    path = pathlib.Path(path)
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise InstallError(f"refusing to edit malformed config {path}: {exc}") from exc

    node = data
    for key in json_pointer[:-1]:
        if not isinstance(node, dict) or key not in node:
            return False
        node = node[key]
    last = json_pointer[-1]
    if not isinstance(node, dict) or last not in node:
        return False
    del node[last]
    write_config_atomic(path, data)
    return True


__all__ = [
    "DEFAULT_ARGS",
    "McpConfigPlan",
    "SERVER_NAME",
    "delete_entry",
    "merge_server_entry",
    "plan_mcp_config",
    "read_config",
    "write_config_atomic",
]
