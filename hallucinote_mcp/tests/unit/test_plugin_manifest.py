"""Contract: the plugin launches its bundled MCP server via uv, version-locked.

INS-7V2D — the plugin no longer declares a bare `command: hallucinote-mcp` PATH
console-script (which decoupled the running server from the plugin version and
needed the install skill's abs-path-override hack). It runs the BUNDLED server
with uv from a committed `uv.lock` into a `${CLAUDE_PLUGIN_DATA}` env, so the
server code AND its full dependency closure match the installed plugin version.

These assertions are the contract; see `.prawduct/artifacts/plans/INS-7V2D/design.md`.
"""
from __future__ import annotations

import json
import pathlib

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
_PLUGIN_JSON = _REPO_ROOT / ".claude-plugin" / "plugin.json"
_UV_LOCK = _REPO_ROOT / "uv.lock"


@pytest.fixture(scope="module")
def mcp_entry() -> dict:
    assert _PLUGIN_JSON.exists(), f"plugin.json missing at {_PLUGIN_JSON}"
    manifest = json.loads(_PLUGIN_JSON.read_text(encoding="utf-8"))
    servers = manifest.get("mcpServers", {})
    assert "hallucinote-mcp" in servers, "plugin.json must declare the hallucinote-mcp server"
    return servers["hallucinote-mcp"]


def test_launch_uses_uv_not_a_bare_path_binary(mcp_entry):
    # The regression guard: NEVER revert to the PATH-dependent bare console-script.
    assert mcp_entry["command"] == "uv", (
        "the server must launch via uv (version-locked, PATH-independent), "
        f"not a bare console-script — got command={mcp_entry['command']!r}"
    )


def test_launch_runs_the_bundled_workspace_from_plugin_root(mcp_entry):
    args = mcp_entry["args"]
    # uv runs the workspace bundled in the (read-only) plugin dir...
    assert "run" in args and "--project" in args
    proj = args[args.index("--project") + 1]
    assert proj == "${CLAUDE_PLUGIN_ROOT}", (
        f"--project must point at the bundled plugin payload, got {proj!r}"
    )
    # ...frozen (never mutate the committed lock) and all-packages (engine + server
    # in one env, so the lazy-imported analysis path resolves)...
    assert "--frozen" in args, "must run --frozen so the committed lock is authoritative"
    assert "--all-packages" in args, "must sync the whole workspace (engine for analysis + server)"
    # ...invoking the server entry point.
    assert args[-2:] == ["hallucinote-mcp", "serve"], f"must end in the serve entry point, got {args[-2:]}"


def test_env_redirects_venv_into_persistent_plugin_data(mcp_entry):
    # CLAUDE_PLUGIN_ROOT is read-only/ephemeral; the venv must live in the
    # persistent, writable CLAUDE_PLUGIN_DATA so it survives updates and uv can
    # write to it (the read-only-project-dir resolution).
    env = mcp_entry.get("env", {})
    assert env.get("UV_PROJECT_ENVIRONMENT") == "${CLAUDE_PLUGIN_DATA}/venv", (
        "the uv venv must be redirected into ${CLAUDE_PLUGIN_DATA}/venv "
        f"(read-only ROOT, persistent DATA) — got {env.get('UV_PROJECT_ENVIRONMENT')!r}"
    )


def test_launch_declares_a_generous_tool_exec_timeout(mcp_entry):
    # The per-server `timeout` field caps TOOL EXECUTION (e.g. long analysis renders),
    # NOT the startup/connection handshake. INS-7V2D's root-cause correction: a cold
    # first build (numpy/scipy/librosa) that exceeds the init timeout and SILENTLY DROPS
    # the server's tools (CC#60224) is governed by the MCP_TIMEOUT env var (raised to the
    # 180000ms floor; see test_startup_timeout.py), which this per-server field never
    # touched. The field stays generous so a slow render tool isn't cut off mid-call.
    timeout = mcp_entry.get("timeout")
    assert isinstance(timeout, int) and timeout >= 60000, (
        f"need a >=60s per-server tool-exec timeout for long analysis tools, got {timeout!r}"
    )


def test_uv_lock_pins_the_whole_closure(mcp_entry):
    # The version-coupling guarantee: a committed lock pins BOTH the server's mcp
    # SDK and the engine, so the resolved env matches the plugin version exactly.
    assert _UV_LOCK.exists(), "a committed uv.lock must pin the dependency closure"
    lock = _UV_LOCK.read_text(encoding="utf-8")
    assert 'name = "mcp"' in lock, "uv.lock must pin the mcp SDK"
    assert 'name = "hallucinote"' in lock, "uv.lock must pin the engine (analysis path)"
    assert 'name = "hallucinote-mcp"' in lock, "uv.lock must pin the bundled server package"
