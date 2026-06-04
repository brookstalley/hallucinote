"""Contract: the SessionStart pre-warm hook rebuilds the MCP env only on a lock change.

INS-7V2D C2 — the plugin ships a SessionStart hook (`hooks/prewarm-mcp-env.sh`,
declared in `hooks/hooks.json`) that pre-builds the bundled server's uv environment
into ``${CLAUDE_PLUGIN_DATA}/venv`` BEFORE the server's init handshake, dodging the
CC#60224 cold-start silent-tool-drop. It must:

  * rebuild on first run (no synced copy yet) and whenever the bundled ``uv.lock``
    differs from the last-synced copy in DATA (the manifest-diff pattern);
  * fast-path (no ``uv`` call) when the env is already warm for the current lock;
  * NEVER fail the session — missing uv / missing lock / a failed sync all exit 0,
    because the launch is self-healing (design §3).

These run the real script with a STUBBED ``uv`` on PATH (no heavy build), so they
exercise the diff/rebuild/skip control flow deterministically and offline.
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
_HOOK_SCRIPT = _REPO_ROOT / "hooks" / "prewarm-mcp-env.sh"
_HOOKS_JSON = _REPO_ROOT / "hooks" / "hooks.json"

# Minimal real-binary PATH the script needs (cmp, cp, mkdir, bash builtins) WITHOUT
# leaking the host's real `uv` in — so a test that omits the stub exercises the
# uv-absent branch deterministically.
_BASE_PATH = "/usr/bin:/bin"


def _make_uv_stub(bin_dir: pathlib.Path, calls_log: pathlib.Path, *, succeed: bool = True) -> None:
    """Write a fake `uv` that logs each call and simulates a venv build."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    stub = bin_dir / "uv"
    rc = 0 if succeed else 1
    # On a simulated successful `uv sync`, materialise the target venv dir so the
    # script's "already warm" fast-path can see it next run (UV_PROJECT_ENVIRONMENT).
    stub.write_text(
        "#!/bin/bash\n"
        f'echo "$@" >> "{calls_log}"\n'
        'if [ "${1:-}" = "sync" ] && [ -n "${UV_PROJECT_ENVIRONMENT:-}" ]; then\n'
        f"  {'mkdir -p \"$UV_PROJECT_ENVIRONMENT\"' if succeed else ':'}\n"
        "fi\n"
        f"exit {rc}\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)


def _run_hook(root: pathlib.Path, data: pathlib.Path, *, path: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["CLAUDE_PLUGIN_ROOT"] = str(root)
    env["CLAUDE_PLUGIN_DATA"] = str(data)
    env["PATH"] = path
    return subprocess.run(
        ["bash", str(_HOOK_SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


@pytest.fixture()
def env(tmp_path: pathlib.Path):
    root = tmp_path / "plugin_root"
    data = tmp_path / "plugin_data"
    root.mkdir()
    data.mkdir()
    (root / "uv.lock").write_text("# lock v1\nname = \"mcp\"\n", encoding="utf-8")
    stub_bin = tmp_path / "stub_bin"
    calls = tmp_path / "uv-calls.log"
    return root, data, stub_bin, calls


def _call_count(calls_log: pathlib.Path) -> int:
    if not calls_log.exists():
        return 0
    return len([ln for ln in calls_log.read_text(encoding="utf-8").splitlines() if ln.strip()])


def _additional_context(result: subprocess.CompletedProcess) -> str:
    """Parse the hook's stdout as a SessionStart additionalContext payload.

    The build-success branch must print ONLY this JSON object on stdout (human
    progress is routed to stderr), so Claude Code injects the guidance into
    Claude's context rather than showing a bare 'hook success' line.
    """
    payload = json.loads(result.stdout)  # raises if stdout isn't clean JSON
    hook_out = payload["hookSpecificOutput"]
    assert hook_out["hookEventName"] == "SessionStart"
    return hook_out["additionalContext"]


def test_first_run_builds_the_env_and_records_the_lock(env):
    root, data, stub_bin, calls = env
    _make_uv_stub(stub_bin, calls)

    result = _run_hook(root, data, path=f"{stub_bin}:{_BASE_PATH}")

    assert result.returncode == 0, result.stderr
    assert _call_count(calls) == 1, "first run must invoke `uv sync` (no synced copy yet)"
    assert " sync " in f" {calls.read_text()} ", "must call `uv sync`, not another subcommand"
    # The synced copy is recorded so the next session can fast-path.
    assert (data / "uv.lock").read_text() == (root / "uv.lock").read_text()


def test_cold_build_emits_session_start_additional_context(env):
    root, data, stub_bin, calls = env
    _make_uv_stub(stub_bin, calls)

    result = _run_hook(root, data, path=f"{stub_bin}:{_BASE_PATH}")

    # Stdout must be a clean JSON additionalContext object (no leading human text,
    # which would make Claude Code treat the whole stream as a plain hook line).
    ctx = _additional_context(result)
    # It must steer Claude toward the /mcp reconnect recovery for the race.
    assert "/mcp" in ctx
    assert "reconnect" in ctx.lower()
    # The human-readable progress goes to stderr, not stdout.
    assert "building the hallucinote-mcp env" in result.stderr


def test_second_run_with_unchanged_lock_skips_the_build(env):
    root, data, stub_bin, calls = env
    _make_uv_stub(stub_bin, calls)
    path = f"{stub_bin}:{_BASE_PATH}"

    _run_hook(root, data, path=path)  # warms + records the copy + creates venv/
    assert _call_count(calls) == 1

    result = _run_hook(root, data, path=path)  # nothing changed → fast-path

    assert result.returncode == 0, result.stderr
    assert _call_count(calls) == 1, "an unchanged lock must NOT trigger a second `uv sync`"
    assert "already warm" in result.stdout


def test_changed_lock_triggers_a_rebuild(env):
    root, data, stub_bin, calls = env
    _make_uv_stub(stub_bin, calls)
    path = f"{stub_bin}:{_BASE_PATH}"

    _run_hook(root, data, path=path)
    assert _call_count(calls) == 1

    # Plugin updated → the bundled lock changes.
    (root / "uv.lock").write_text("# lock v2\nname = \"mcp\"\nname = \"numpy\"\n", encoding="utf-8")
    result = _run_hook(root, data, path=path)

    assert result.returncode == 0, result.stderr
    assert _call_count(calls) == 2, "a changed lock must rebuild the env"
    assert (data / "uv.lock").read_text() == (root / "uv.lock").read_text()


def test_missing_uv_never_fails_the_session(env):
    root, data, stub_bin, calls = env
    # No stub written → `uv` is absent on the trimmed PATH.
    result = _run_hook(root, data, path=_BASE_PATH)

    assert result.returncode == 0, "uv absent must exit 0 (launch self-heals)"
    assert _call_count(calls) == 0
    assert "uv not on PATH" in result.stdout


def test_missing_lock_never_fails_the_session(env):
    root, data, stub_bin, calls = env
    _make_uv_stub(stub_bin, calls)
    (root / "uv.lock").unlink()

    result = _run_hook(root, data, path=f"{stub_bin}:{_BASE_PATH}")

    assert result.returncode == 0, "a missing lock must exit 0"
    assert _call_count(calls) == 0, "no lock → nothing to sync against"


def test_failed_sync_never_fails_the_session_and_retries_next_time(env):
    root, data, stub_bin, calls = env
    _make_uv_stub(stub_bin, calls, succeed=False)
    path = f"{stub_bin}:{_BASE_PATH}"

    result = _run_hook(root, data, path=path)
    assert result.returncode == 0, "a failed sync must NOT fail the session"
    assert "retry on demand" in result.stdout
    # A failed sync must NOT record the lock copy — else a broken env would be
    # treated as warm and never retried.
    assert not (data / "uv.lock").exists(), "a failed sync must not record the synced-lock copy"

    # Next session retries (still no recorded copy).
    _run_hook(root, data, path=path)
    assert _call_count(calls) == 2, "a previously-failed sync must be retried next session"


# --- the hook is actually declared so Claude Code runs it ----------------------

def test_hooks_json_declares_the_prewarm_on_session_start():
    assert _HOOKS_JSON.exists(), f"hooks.json missing at {_HOOKS_JSON}"
    decl = json.loads(_HOOKS_JSON.read_text(encoding="utf-8"))
    session_start = decl.get("hooks", {}).get("SessionStart", [])
    commands = [
        h.get("command", "")
        for group in session_start
        for h in group.get("hooks", [])
    ]
    assert any("prewarm-mcp-env.sh" in c for c in commands), (
        "SessionStart must invoke prewarm-mcp-env.sh so the env warms before the "
        f"server handshake — got commands {commands!r}"
    )
    # It must reference the bundled script via the plugin-root env var (read-only
    # payload), not a hard-coded absolute path.
    assert any("${CLAUDE_PLUGIN_ROOT}" in c for c in commands), (
        "the prewarm command must locate its script via ${CLAUDE_PLUGIN_ROOT}"
    )


def test_prewarm_script_is_executable_and_present():
    assert _HOOK_SCRIPT.exists(), f"prewarm script missing at {_HOOK_SCRIPT}"
    assert os.access(_HOOK_SCRIPT, os.X_OK), "prewarm script must be executable"
