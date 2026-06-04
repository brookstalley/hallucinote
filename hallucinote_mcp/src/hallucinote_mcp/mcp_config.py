"""MCP-config *mutation* for the uninstall skill.

``install_paths.py`` *detects* config state (where ``hallucinote-mcp`` is
registered, which files are malformed). This module performs the atomic
delete/rewrite the uninstall skill needs to clear stale registrations.

There is no longer an *install* write path: since INS-7V2D the ``hallucinote``
plugin provides the server via its bundled uv launch (PATH-independent), so the
install skill never hand-writes an ``mcpServers`` entry — confirming ``/mcp``
shows the plugin-provided server is the whole job. The old PATH-detection truth
table + absolute-path-override hack (``plan_mcp_config`` / ``merge_server_entry``)
retired with that change. Uninstall still removes any *legacy* entries a
pre-plugin install wrote, so the delete machinery stays. Stdlib-only.
"""
from __future__ import annotations

import json
import os
import pathlib

from .install_ops import InstallError


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
    "delete_entry",
    "read_config",
    "write_config_atomic",
]
