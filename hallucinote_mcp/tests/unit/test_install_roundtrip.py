"""End-to-end install -> uninstall round-trip through the CLI (Chunk 5).

Drives the real subcommands against a temp User Library and project, asserting a
clean install and a clean, idempotent uninstall. HOME is redirected so the
user-scope config path and the global config scan never touch the real
~/.claude.json.
"""
from __future__ import annotations

import json

from hallucinote_mcp.cli import main


def _run(capsys, *argv):
    code = main(list(argv))
    return code, json.loads(capsys.readouterr().out)


def test_full_install_uninstall_roundtrip(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))  # hermetic: never touch the real ~/.claude.json

    ul = tmp_path / "User Library"
    rs_dir = ul / "Remote Scripts" / "Hallucinote"
    amxd = ul / "Presets" / "Audio Effects" / "Max Audio Effect" / "HallucinoteAnalyzer.amxd"
    project = tmp_path / "proj"
    project.mkdir()
    local_cfg = project / ".mcp.json"

    # --- install ---
    code, out = _run(capsys, "install-remote-script", "--user-library", str(ul))
    assert code == 0 and out["ok"] and out["verify"]["ok"]
    assert (rs_dir / "hallucinote_mcp" / "remote_script" / "__init__.py").is_file()
    assert not (rs_dir / "hallucinote_mcp" / "server.py").exists()  # the anchored exclude held

    code, out = _run(capsys, "install-analyzer", "--user-library", str(ul))
    assert code == 0 and out["ok"]
    assert amxd.is_file()

    code, out = _run(capsys, "configure-mcp", "--registered", "false",
                     "--scope", "project", "--cwd", str(project))
    assert code == 0 and out["ok"] and out["action"] == "write"
    assert "hallucinote-mcp" in json.loads(local_cfg.read_text())["mcpServers"]

    # --- uninstall (the mirror) ---
    code, out = _run(capsys, "uninstall-remote-script", "--user-library", str(ul))
    assert code == 0 and out["removed"] is True
    assert not rs_dir.exists()
    assert (ul / "Remote Scripts").is_dir()  # left Live infrastructure in place

    code, out = _run(capsys, "uninstall-analyzer", "--user-library", str(ul))
    assert code == 0 and out["removed"] is True
    assert not amxd.exists()

    code, out = _run(capsys, "remove-mcp-config", "--cwd", str(project))
    assert code == 0 and out["ok"] and len(out["removed"]) == 1
    assert "hallucinote-mcp" not in json.loads(local_cfg.read_text()).get("mcpServers", {})

    # --- idempotent re-uninstall ---
    code, out = _run(capsys, "uninstall-remote-script", "--user-library", str(ul))
    assert out["removed"] is False
    code, out = _run(capsys, "remove-mcp-config", "--cwd", str(project))
    assert out["removed"] == []
