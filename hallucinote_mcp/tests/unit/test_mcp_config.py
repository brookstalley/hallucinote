"""Tests for mcp_config.py — the MCP-config decision table and atomic mutations.

The decision is a pure 5-row truth table; merge/write/delete are atomic and never
clobber sibling servers. CLI tests redirect the global config path so they never
touch the real ~/.claude.json.
"""
from __future__ import annotations

import json
import pathlib

import pytest

from hallucinote_mcp import install_paths as P
from hallucinote_mcp import mcp_config as mc
from hallucinote_mcp.cli import main


# --- plan_mcp_config truth table -------------------------------------------

def test_plan_error_when_command_missing():
    plan = mc.plan_mcp_config(command_path=None, on_path=False, already_registered=False)
    assert plan.action == "error"


def test_plan_skip_when_registered_and_on_path():
    plan = mc.plan_mcp_config(
        command_path=pathlib.Path("/usr/bin/hallucinote-mcp"),
        on_path=True, already_registered=True,
    )
    assert plan.action == "skip"
    assert plan.path is None


def test_plan_registered_not_on_path_writes_absolute_at_user_scope(monkeypatch, tmp_path):
    monkeypatch.setattr(mc, "mcp_config_global_path", lambda: tmp_path / ".claude.json")
    abs_cmd = pathlib.Path("/venv/bin/hallucinote-mcp")
    plan = mc.plan_mcp_config(
        command_path=abs_cmd, on_path=False, already_registered=True,
        scope="project", cwd=tmp_path,  # scope is ignored — override forces user scope
    )
    assert plan.action == "write"
    assert plan.path == tmp_path / ".claude.json"      # user scope, not project
    assert plan.command == str(abs_cmd)                 # absolute


def test_plan_unregistered_on_path_writes_bare(monkeypatch, tmp_path):
    monkeypatch.setattr(mc, "mcp_config_local_path", lambda cwd=None: tmp_path / ".mcp.json")
    plan = mc.plan_mcp_config(
        command_path=pathlib.Path("/usr/bin/hallucinote-mcp"),
        on_path=True, already_registered=False, scope="project", cwd=tmp_path,
    )
    assert plan.action == "write"
    assert plan.path == tmp_path / ".mcp.json"
    assert plan.command == "hallucinote-mcp"            # bare


def test_plan_unregistered_not_on_path_writes_absolute(monkeypatch, tmp_path):
    monkeypatch.setattr(mc, "mcp_config_global_path", lambda: tmp_path / ".claude.json")
    abs_cmd = pathlib.Path("/venv/bin/hallucinote-mcp")
    plan = mc.plan_mcp_config(
        command_path=abs_cmd, on_path=False, already_registered=False, scope="user",
    )
    assert plan.action == "write"
    assert plan.command == str(abs_cmd)


def test_plan_unknown_scope_raises():
    with pytest.raises(mc.InstallError):
        mc.plan_mcp_config(
            command_path=pathlib.Path("/x"), on_path=True, already_registered=False, scope="bogus",
        )


# --- merge / write / read / delete -----------------------------------------

def test_merge_preserves_siblings_and_top_level():
    config = {"otherKey": 1, "mcpServers": {"someone-else": {"command": "x"}}}
    merged = mc.merge_server_entry(config, "hallucinote-mcp", ("serve",))
    assert merged["otherKey"] == 1
    assert merged["mcpServers"]["someone-else"] == {"command": "x"}
    assert merged["mcpServers"]["hallucinote-mcp"] == {"command": "hallucinote-mcp", "args": ["serve"]}
    # original not mutated
    assert "hallucinote-mcp" not in config["mcpServers"]


def test_write_config_atomic(tmp_path):
    path = tmp_path / "nested" / ".mcp.json"
    mc.write_config_atomic(path, {"mcpServers": {"hallucinote-mcp": {"command": "x"}}})
    assert json.loads(path.read_text())["mcpServers"]["hallucinote-mcp"]["command"] == "x"
    assert list(tmp_path.glob("**/.*.tmp-*")) == [], "no temp file should remain"


def test_read_config_missing_returns_empty(tmp_path):
    assert mc.read_config(tmp_path / "absent.json") == {}


def test_read_config_malformed_raises(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(mc.InstallError):
        mc.read_config(bad)


def test_delete_entry_top_level(tmp_path):
    path = tmp_path / ".mcp.json"
    mc.write_config_atomic(path, {"mcpServers": {"hallucinote-mcp": {"command": "x"}, "keep": {}}})
    assert mc.delete_entry(path, ("mcpServers", "hallucinote-mcp")) is True
    data = json.loads(path.read_text())
    assert "hallucinote-mcp" not in data["mcpServers"]
    assert "keep" in data["mcpServers"], "sibling must survive"


def test_delete_entry_nested_project_pointer(tmp_path):
    path = tmp_path / ".claude.json"
    mc.write_config_atomic(path, {"projects": {"/p": {"mcpServers": {"hallucinote-mcp": {}}}}})
    assert mc.delete_entry(path, ("projects", "/p", "mcpServers", "hallucinote-mcp")) is True
    assert json.loads(path.read_text())["projects"]["/p"]["mcpServers"] == {}


def test_delete_entry_absent_is_false(tmp_path):
    path = tmp_path / ".mcp.json"
    mc.write_config_atomic(path, {"mcpServers": {}})
    assert mc.delete_entry(path, ("mcpServers", "hallucinote-mcp")) is False
    assert mc.delete_entry(tmp_path / "nope.json", ("mcpServers", "hallucinote-mcp")) is False


def test_delete_entry_malformed_raises(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("nope", encoding="utf-8")
    with pytest.raises(mc.InstallError):
        mc.delete_entry(bad, ("mcpServers", "hallucinote-mcp"))


# --- CLI (redirected away from the real ~/.claude.json) --------------------

def test_cli_configure_mcp_skip(monkeypatch, capsys):
    monkeypatch.setattr(P, "hallucinote_mcp_command",
                        lambda: (pathlib.Path("/usr/bin/hallucinote-mcp"), True))
    code = main(["configure-mcp", "--registered", "true"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0 and payload["ok"] is True and payload["action"] == "skip"


def test_cli_configure_mcp_writes_user_scope(monkeypatch, tmp_path, capsys):
    cfg = tmp_path / ".claude.json"
    monkeypatch.setattr(P, "hallucinote_mcp_command",
                        lambda: (pathlib.Path("/usr/bin/hallucinote-mcp"), True))
    monkeypatch.setattr(mc, "mcp_config_global_path", lambda: cfg)
    code = main(["configure-mcp", "--scope", "user", "--registered", "false"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0 and payload["action"] == "write"
    assert json.loads(cfg.read_text())["mcpServers"]["hallucinote-mcp"]["command"] == "hallucinote-mcp"


def test_existing_mcp_config_files_accepts_str_cwd(monkeypatch, tmp_path):
    """Regression: the CLI passes --cwd as a str; install_paths must coerce to Path
    (it previously did cwd.resolve() and raised AttributeError on a str)."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))  # hermetic global scan
    (tmp_path / ".mcp.json").write_text('{"mcpServers": {"hallucinote-mcp": {}}}', encoding="utf-8")
    entries = P.existing_mcp_config_files(cwd=str(tmp_path))  # str, not Path
    assert any(e.path == tmp_path / ".mcp.json" for e in entries)


def test_cli_remove_mcp_config(monkeypatch, tmp_path, capsys):
    local = tmp_path / ".mcp.json"
    local.write_text(json.dumps({"mcpServers": {"hallucinote-mcp": {"command": "x"}}}), encoding="utf-8")
    monkeypatch.setattr(
        P, "existing_mcp_config_files",
        lambda cwd=None: [P.MCPConfigEntry(local, ("mcpServers", "hallucinote-mcp"))],
    )
    code = main(["remove-mcp-config"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0 and payload["ok"] is True and len(payload["removed"]) == 1
    assert "hallucinote-mcp" not in json.loads(local.read_text())["mcpServers"]
