"""Contract: the SessionStart first-run nudge fires exactly once (ONBOARD-M4L A2).

The plugin ships a second SessionStart hook (`hooks/first_run_nudge.py`, declared in
`hooks/hooks.json`) that, on the FIRST session after install, hands Claude a
SessionStart `additionalContext` object telling it to greet the user and offer
`/hallucinote:getting-started`. It must:

  * on first run, emit the nudge JSON on stdout AND record a `.onboarded` marker in
    ``${CLAUDE_PLUGIN_DATA}``;
  * on every later run (marker present), stay completely silent on stdout — a stray
    line would inject into Claude's context every session;
  * NEVER fail the session (exit 0 on every branch), mirroring the prewarm hook so it
    behaves identically on macOS and Windows.
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
_HOOK_SCRIPT = _REPO_ROOT / "hooks" / "first_run_nudge.py"
_HOOKS_JSON = _REPO_ROOT / "hooks" / "hooks.json"


def _run_hook(root: pathlib.Path, data: pathlib.Path) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["CLAUDE_PLUGIN_ROOT"] = str(root)
    env["CLAUDE_PLUGIN_DATA"] = str(data)
    return subprocess.run(
        [sys.executable, str(_HOOK_SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _additional_context(result: subprocess.CompletedProcess) -> str:
    payload = json.loads(result.stdout)  # raises if stdout isn't clean JSON
    hook_out = payload["hookSpecificOutput"]
    assert hook_out["hookEventName"] == "SessionStart"
    return hook_out["additionalContext"]


def test_first_run_emits_the_nudge_and_records_the_marker(tmp_path):
    root = tmp_path / "plugin_root"
    data = tmp_path / "plugin_data"
    root.mkdir()
    data.mkdir()

    result = _run_hook(root, data)

    assert result.returncode == 0, result.stderr
    ctx = _additional_context(result)
    assert "getting-started" in ctx, "the nudge must point at /hallucinote:getting-started"
    assert "Hallucinote" in ctx, "the nudge must greet the user"
    # The once-only marker is recorded so the next session is silent.
    assert (data / ".onboarded").exists(), "first run must record the .onboarded marker"


def test_second_run_is_silent(tmp_path):
    root = tmp_path / "plugin_root"
    data = tmp_path / "plugin_data"
    root.mkdir()
    data.mkdir()

    first = _run_hook(root, data)
    assert first.stdout != "", "first run should emit the nudge"

    second = _run_hook(root, data)  # marker now present
    assert second.returncode == 0, second.stderr
    assert second.stdout == "", (
        f"an already-onboarded session must keep stdout clean for SessionStart, "
        f"got {second.stdout!r}"
    )


def test_missing_plugin_data_never_fails_the_session(tmp_path):
    root = tmp_path / "plugin_root"
    root.mkdir()
    env = dict(os.environ)
    env["CLAUDE_PLUGIN_ROOT"] = str(root)
    env.pop("CLAUDE_PLUGIN_DATA", None)

    result = subprocess.run(
        [sys.executable, str(_HOOK_SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, "CLAUDE_PLUGIN_DATA unset must exit 0"
    assert result.stdout == "", (
        f"the no-DATA skip path must keep stdout clean for SessionStart, got {result.stdout!r}"
    )


def test_hooks_json_declares_the_nudge_on_session_start():
    decl = json.loads(_HOOKS_JSON.read_text(encoding="utf-8"))
    session_start = decl.get("hooks", {}).get("SessionStart", [])
    commands = [
        h.get("command", "")
        for group in session_start
        for h in group.get("hooks", [])
    ]
    assert any("first_run_nudge.py" in c for c in commands), (
        f"SessionStart must invoke first_run_nudge.py — got {commands!r}"
    )
    # Located via the plugin-root env var, not a hard-coded path.
    assert any(
        "${CLAUDE_PLUGIN_ROOT}" in c and "first_run_nudge.py" in c for c in commands
    ), "the nudge command must locate its script via ${CLAUDE_PLUGIN_ROOT}"
    # Cross-platform: launched via python (uv run --no-project python), never bash.
    assert all("bash " not in c for c in commands), (
        f"hooks must not launch via bash (Windows has no guaranteed bash) — {commands!r}"
    )


def test_nudge_script_present():
    assert _HOOK_SCRIPT.exists(), f"nudge script missing at {_HOOK_SCRIPT}"
    # Launched via `python <script>.py`, so it needn't be marked executable.
