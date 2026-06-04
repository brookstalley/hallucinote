"""Claude-Code config mutation for the install / uninstall skills.

``install_paths.py`` *detects* config state (where ``hallucinote-mcp`` is
registered, which files are malformed). This module performs the atomic
delete/rewrite the skills need.

Two write surfaces, both atomic and idempotent:

* **``mcpServers`` entries** (``delete_entry``) — the install skill never writes
  these (since INS-7V2D the plugin provides the server via its bundled uv launch,
  PATH-independent), but uninstall still removes any *legacy* entries a pre-plugin
  install wrote. The old PATH-detection truth table + absolute-path-override hack
  (``plan_mcp_config`` / ``merge_server_entry``) retired with the plugin model.
* **``env.MCP_TIMEOUT``** (``ensure_startup_timeout`` / ``unset_startup_timeout``)
  — the MCP server *startup* connection timeout. A genuinely-cold first
  ``uv sync`` (numpy/scipy/librosa, ~70 MiB) can exceed Claude Code's default
  30 s startup window and silently drop the server's tools (CC#60224, INS-7V2D
  follow-up). The intended mitigation was a "generous timeout", but the
  ``plugin.json`` per-server ``"timeout"`` field governs *tool execution*, NOT the
  startup handshake — that's ``MCP_TIMEOUT`` (env var, ms, default 30000). Plugin
  manifests can't set it, so the install skill raises it in the user's
  ``~/.claude/settings.json`` ``env`` (which Claude Code injects into spawned MCP
  subprocesses). Warm starts ignore it (they connect in ~2 s); it only bounds the
  cold-build wait.

Stdlib-only.
"""
from __future__ import annotations

import json
import os
import pathlib

from .install_ops import InstallError

# The startup-timeout floor we ensure in settings.json ``env.MCP_TIMEOUT`` (ms).
# 3 minutes: comfortably covers a cold ``uv sync`` of the numpy/scipy/librosa
# closure on a slow link, while bounding a genuinely-broken-server wait. A warm
# start connects in ~2 s regardless — this is a pure safety net for the rare cold
# path (first run / post-plugin-update lock change).
STARTUP_TIMEOUT_FLOOR_MS = 180000


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


def _parse_ms(value: object) -> int | None:
    """Best-effort parse of an ``MCP_TIMEOUT`` value to int ms; ``None`` if not."""
    if isinstance(value, bool):  # bool is an int subclass — reject it explicitly
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def ensure_startup_timeout(
    path: pathlib.Path | str,
    floor_ms: int = STARTUP_TIMEOUT_FLOOR_MS,
) -> dict:
    """Ensure ``env.MCP_TIMEOUT`` in a settings file is at least ``floor_ms``.

    Idempotent and non-destructive:

    * absent file / no ``env`` / no ``MCP_TIMEOUT`` → set it (``"set"``);
    * present but below the floor, or unparseable → raise to the floor
      (``"raised"`` / ``"repaired"``);
    * present and already ``>= floor_ms`` → leave the user's higher value
      untouched, no write (``"kept"``).

    Other ``env`` keys and other top-level keys are preserved. Refuses a malformed
    file or a non-dict ``env`` (raises :class:`InstallError`) rather than clobber
    an unexpected shape. ``MCP_TIMEOUT`` is written as a string — settings ``env``
    values are strings.

    Returns ``{"ok", "path", "action", "value", "previous"}``.
    """
    path = pathlib.Path(path)
    config = read_config(path)  # {} if absent; raises on malformed

    env = config.get("env", {})
    if not isinstance(env, dict):
        raise InstallError(
            f"refusing to edit {path}: top-level 'env' is {type(env).__name__}, not an object"
        )

    previous = env.get("MCP_TIMEOUT")
    current_ms = _parse_ms(previous)

    if previous is None:
        action = "set"
    elif current_ms is None:
        action = "repaired"  # present but unparseable → replace with a sane floor
    elif current_ms >= floor_ms:
        action = "kept"
    else:
        action = "raised"

    if action == "kept":
        return {"ok": True, "path": str(path), "action": action,
                "value": str(previous), "previous": previous}

    env["MCP_TIMEOUT"] = str(floor_ms)
    config["env"] = env
    write_config_atomic(path, config)
    return {"ok": True, "path": str(path), "action": action,
            "value": str(floor_ms), "previous": previous}


def unset_startup_timeout(
    path: pathlib.Path | str,
    floor_ms: int = STARTUP_TIMEOUT_FLOOR_MS,
) -> dict:
    """Remove ``env.MCP_TIMEOUT`` iff we set it — the symmetric uninstall step.

    Conservative: only deletes the key when its value equals our managed floor
    (i.e. we wrote it). A user-customized value is left alone (``"kept-custom"``).
    Removes a now-empty ``env`` object. Idempotent: ``"absent"`` when there's
    nothing to remove. Other keys preserved; refuses a malformed file.

    Returns ``{"ok", "path", "action", "value"}``.
    """
    path = pathlib.Path(path)
    config = read_config(path)  # {} if absent; raises on malformed

    env = config.get("env")
    if not isinstance(env, dict) or "MCP_TIMEOUT" not in env:
        return {"ok": True, "path": str(path), "action": "absent", "value": None}

    current = env["MCP_TIMEOUT"]
    if _parse_ms(current) != floor_ms:
        return {"ok": True, "path": str(path), "action": "kept-custom", "value": current}

    del env["MCP_TIMEOUT"]
    if not env:
        del config["env"]
    write_config_atomic(path, config)
    return {"ok": True, "path": str(path), "action": "removed", "value": current}


__all__ = [
    "STARTUP_TIMEOUT_FLOOR_MS",
    "delete_entry",
    "ensure_startup_timeout",
    "read_config",
    "unset_startup_timeout",
    "write_config_atomic",
]
