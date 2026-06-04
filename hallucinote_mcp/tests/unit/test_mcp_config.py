"""Tests for mcp_config.py — the uninstall config-cleanup mutations.

Since INS-7V2D the ``hallucinote`` plugin provides the MCP server via its bundled
uv launch (PATH-independent), so there is no *install* write path: the old
PATH-detection truth table + absolute-path-override hack (``plan_mcp_config`` /
``merge_server_entry`` / ``configure-mcp``) retired. What remains is the atomic
delete/read/write the uninstall skill uses to clear *legacy* registrations.
CLI tests redirect the config paths so they never touch the real ~/.claude.json.
"""
from __future__ import annotations

import json
import pathlib

import pytest

from hallucinote_mcp import install_paths as P
from hallucinote_mcp import mcp_config as mc
from hallucinote_mcp.cli import main


# --- the install write path is gone (new contract) -------------------------

def test_configure_mcp_subcommand_is_retired():
    """The plugin provides the server now — the install skill never writes config,
    so `configure-mcp` no longer exists. (Regression guard against re-introducing
    the PATH-override hack.)"""
    assert not hasattr(mc, "plan_mcp_config"), "the PATH-detection truth table must be gone"
    assert not hasattr(mc, "merge_server_entry"), "the install merge/write helper must be gone"
    # The CLI no longer dispatches it: unknown command → exit 2.
    assert main(["configure-mcp", "--registered", "true"]) == 2


# --- read / write / delete (uninstall still needs these) -------------------

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
