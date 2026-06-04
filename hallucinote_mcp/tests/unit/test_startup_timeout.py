"""Contract: ``env.MCP_TIMEOUT`` management in settings.json.

INS-7V2D follow-up. A genuinely-cold first ``uv sync`` of the bundled server's
numpy/scipy/librosa closure can exceed Claude Code's default 30 s MCP *startup*
window and silently drop the server's tools (CC#60224). The fix raises
``MCP_TIMEOUT`` (the env var that actually governs the startup handshake — the
per-server ``plugin.json`` ``"timeout"`` field governs tool execution) in the
user's ``~/.claude/settings.json`` ``env``, via tested, atomic, idempotent ops the
install / uninstall skills call instead of hand-editing JSON.

These tests pin the merge semantics: set-if-absent, raise-if-below-floor,
never-downgrade-a-higher-value, refuse-malformed, preserve-other-keys, and a
conservative uninstall that only removes the value WE wrote.
"""
from __future__ import annotations

import json
import pathlib

import pytest

from hallucinote_mcp import mcp_config as mc
from hallucinote_mcp.install_ops import InstallError

FLOOR = mc.STARTUP_TIMEOUT_FLOOR_MS


def _read(path: pathlib.Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# --- ensure_startup_timeout ----------------------------------------------------

def test_floor_is_a_sane_3_minutes():
    # The cold-build safety net must comfortably exceed Claude Code's 30 s default.
    assert FLOOR == 180000
    assert FLOOR > 30000


def test_absent_file_is_created_with_the_floor(tmp_path):
    path = tmp_path / "settings.json"
    result = mc.ensure_startup_timeout(path)

    assert result["action"] == "set"
    assert result["previous"] is None
    assert path.exists()
    assert _read(path)["env"]["MCP_TIMEOUT"] == str(FLOOR)


def test_value_is_written_as_a_string(tmp_path):
    path = tmp_path / "settings.json"
    mc.ensure_startup_timeout(path)
    assert _read(path)["env"]["MCP_TIMEOUT"] == str(FLOOR)
    assert isinstance(_read(path)["env"]["MCP_TIMEOUT"], str)


def test_adds_env_and_preserves_other_top_level_keys(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"enabledPlugins": {"x@y": True}, "hooks": {}}), encoding="utf-8")

    result = mc.ensure_startup_timeout(path)

    assert result["action"] == "set"
    data = _read(path)
    assert data["env"]["MCP_TIMEOUT"] == str(FLOOR)
    assert data["enabledPlugins"] == {"x@y": True}  # untouched
    assert data["hooks"] == {}


def test_preserves_other_env_keys(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"env": {"DEBUG": "1"}}), encoding="utf-8")

    mc.ensure_startup_timeout(path)

    env = _read(path)["env"]
    assert env["MCP_TIMEOUT"] == str(FLOOR)
    assert env["DEBUG"] == "1"  # untouched


def test_raises_a_value_below_the_floor(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"env": {"MCP_TIMEOUT": "30000"}}), encoding="utf-8")

    result = mc.ensure_startup_timeout(path)

    assert result["action"] == "raised"
    assert result["previous"] == "30000"
    assert _read(path)["env"]["MCP_TIMEOUT"] == str(FLOOR)


def test_keeps_a_higher_user_value_and_does_not_write(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"env": {"MCP_TIMEOUT": "300000"}}), encoding="utf-8")
    before = path.stat().st_mtime_ns

    result = mc.ensure_startup_timeout(path)

    assert result["action"] == "kept"
    assert _read(path)["env"]["MCP_TIMEOUT"] == "300000"  # not downgraded
    assert path.stat().st_mtime_ns == before, "a kept value must not rewrite the file"


def test_equal_to_floor_is_kept_idempotently(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"env": {"MCP_TIMEOUT": str(FLOOR)}}), encoding="utf-8")

    result = mc.ensure_startup_timeout(path)

    assert result["action"] == "kept"
    assert _read(path)["env"]["MCP_TIMEOUT"] == str(FLOOR)


def test_repairs_an_unparseable_value(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"env": {"MCP_TIMEOUT": "soon"}}), encoding="utf-8")

    result = mc.ensure_startup_timeout(path)

    assert result["action"] == "repaired"
    assert _read(path)["env"]["MCP_TIMEOUT"] == str(FLOOR)


def test_ensure_is_idempotent(tmp_path):
    path = tmp_path / "settings.json"
    first = mc.ensure_startup_timeout(path)
    second = mc.ensure_startup_timeout(path)

    assert first["action"] == "set"
    assert second["action"] == "kept"
    assert _read(path)["env"]["MCP_TIMEOUT"] == str(FLOOR)


def test_ensure_refuses_malformed_json(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{ not json", encoding="utf-8")

    with pytest.raises(InstallError):
        mc.ensure_startup_timeout(path)


def test_ensure_refuses_non_dict_env(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"env": "oops"}), encoding="utf-8")

    with pytest.raises(InstallError):
        mc.ensure_startup_timeout(path)


def test_ensure_respects_a_custom_floor(tmp_path):
    path = tmp_path / "settings.json"
    result = mc.ensure_startup_timeout(path, floor_ms=90000)

    assert result["action"] == "set"
    assert _read(path)["env"]["MCP_TIMEOUT"] == "90000"


def test_ensure_leaves_no_temp_file(tmp_path):
    path = tmp_path / "settings.json"
    mc.ensure_startup_timeout(path)
    leftovers = [p.name for p in tmp_path.iterdir() if p.name.startswith(".settings.json.tmp")]
    assert leftovers == []


# --- unset_startup_timeout -----------------------------------------------------

def test_unset_absent_file_is_a_noop(tmp_path):
    path = tmp_path / "settings.json"
    result = mc.unset_startup_timeout(path)
    assert result["action"] == "absent"
    assert not path.exists()


def test_unset_no_env_key_is_a_noop(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"enabledPlugins": {}}), encoding="utf-8")
    result = mc.unset_startup_timeout(path)
    assert result["action"] == "absent"


def test_unset_removes_our_value_and_drops_empty_env(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"env": {"MCP_TIMEOUT": str(FLOOR)}, "hooks": {}}), encoding="utf-8")

    result = mc.unset_startup_timeout(path)

    assert result["action"] == "removed"
    data = _read(path)
    assert "env" not in data, "an env left with only our key should be dropped"
    assert data["hooks"] == {}  # other keys preserved


def test_unset_keeps_other_env_keys(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps({"env": {"MCP_TIMEOUT": str(FLOOR), "DEBUG": "1"}}), encoding="utf-8"
    )

    mc.unset_startup_timeout(path)

    data = _read(path)
    assert "MCP_TIMEOUT" not in data["env"]
    assert data["env"]["DEBUG"] == "1"


def test_unset_keeps_a_user_customized_value(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"env": {"MCP_TIMEOUT": "300000"}}), encoding="utf-8")

    result = mc.unset_startup_timeout(path)

    assert result["action"] == "kept-custom"
    assert _read(path)["env"]["MCP_TIMEOUT"] == "300000", "must not clobber a custom value"


def test_unset_is_idempotent(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"env": {"MCP_TIMEOUT": str(FLOOR)}}), encoding="utf-8")

    first = mc.unset_startup_timeout(path)
    second = mc.unset_startup_timeout(path)

    assert first["action"] == "removed"
    assert second["action"] == "absent"


def test_unset_refuses_malformed_json(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{ not json", encoding="utf-8")

    with pytest.raises(InstallError):
        mc.unset_startup_timeout(path)


# --- round-trip ----------------------------------------------------------------

def test_set_then_unset_restores_a_clean_file(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"enabledPlugins": {"a@b": True}}), encoding="utf-8")

    mc.ensure_startup_timeout(path)
    mc.unset_startup_timeout(path)

    assert _read(path) == {"enabledPlugins": {"a@b": True}}, "set→unset must round-trip cleanly"
