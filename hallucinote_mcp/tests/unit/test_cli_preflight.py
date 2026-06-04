"""``hallucinote-mcp preflight`` — JSON report for the install / uninstall skills."""
from __future__ import annotations

import json
import sys

import pytest

from hallucinote_mcp.cli import main as cli_main
from hallucinote_mcp.cli.preflight import _build_report


def test_preflight_report_has_expected_top_level_keys():
    """The skills consume these keys by name — keep this contract stable."""
    report = _build_report()
    assert set(report.keys()) == {
        "package",
        "user_library",
        "live",
        "mcp_command",
        "mcp_configs",
        "remote_script",
        "analyzer",
        "platform",
    }


def test_preflight_report_remote_script_block_has_per_candidate_match_status():
    """The install skill uses `matches_mcp_server` to suggest re-running
    install when the vendored copy is stale (W12-D). The block carries
    one entry per User Library candidate; absent installs report
    `installed: false` + `version: null` + `matches_mcp_server: null`.

    Note: this test does NOT depend on whether the real test environment
    has a vendored install — it only asserts the shape contract.
    """
    report = _build_report()
    rs = report["remote_script"]
    assert "candidates" in rs
    assert isinstance(rs["candidates"], list)
    # One entry per User Library candidate.
    assert len(rs["candidates"]) == len(report["user_library"]["candidates"])
    for entry in rs["candidates"]:
        assert set(entry.keys()) == {
            "user_library",
            "remote_script_dir",
            "installed",
            "version",
            "matches_mcp_server",
        }
        assert isinstance(entry["installed"], bool)
        # version is either None or a non-empty string.
        assert entry["version"] is None or (
            isinstance(entry["version"], str) and entry["version"]
        )
        # matches_mcp_server is True/False (install present) or None (no install).
        assert entry["matches_mcp_server"] in (True, False, None)
        # An absent install must report None for both version + match.
        if not entry["installed"]:
            assert entry["version"] is None
            assert entry["matches_mcp_server"] is None


def test_preflight_report_is_json_serializable():
    report = _build_report()
    # Round-trip must succeed (no Path objects leaking through).
    json.dumps(report)


def test_preflight_report_package_block_includes_version_and_root():
    report = _build_report()
    assert "version" in report["package"]
    assert "root" in report["package"]


def test_preflight_report_user_library_candidates_have_exists_flag():
    """Skill picks the first candidate whose ``exists`` is True."""
    report = _build_report()
    for cand in report["user_library"]["candidates"]:
        assert "path" in cand
        assert "exists" in cand
        assert isinstance(cand["exists"], bool)


def test_preflight_report_live_block_uses_tri_state_running():
    """``is_running`` is True / False / None — None means "unknown, ask the user"."""
    report = _build_report()
    assert "is_running" in report["live"]
    assert report["live"]["is_running"] in (True, False, None)


def test_preflight_report_mcp_command_block_signals_on_path():
    report = _build_report()
    assert "path" in report["mcp_command"]
    assert "on_path" in report["mcp_command"]
    assert isinstance(report["mcp_command"]["on_path"], bool)


def test_preflight_report_platform_matches_runtime():
    report = _build_report()
    assert report["platform"] == sys.platform


def test_preflight_containing_entry_includes_json_pointer():
    """Schema contract: each entry has {path, json_pointer}.

    `claude mcp add` writes to a nested project scope; the json_pointer
    tells the uninstall skill where to delete the entry. A flat string
    list would silently drop that.
    """
    report = _build_report()
    for entry in report["mcp_configs"]["containing_entry"]:
        assert isinstance(entry, dict)
        assert "path" in entry
        assert "json_pointer" in entry
        assert isinstance(entry["json_pointer"], list)
        # Last segment is always the entry key itself.
        assert entry["json_pointer"][-1] == "hallucinote-mcp"


def test_cli_preflight_prints_valid_json(capsys):
    rc = cli_main(["preflight"])
    assert rc == 0
    out = capsys.readouterr().out
    # Should be a single JSON object, indented.
    parsed = json.loads(out)
    assert "platform" in parsed


def test_cli_preflight_help(capsys):
    rc = cli_main(["preflight", "--help"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Usage" in out
    assert "preflight" in out


def test_cli_unknown_command_still_reported(capsys):
    rc = cli_main(["nope"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "unknown command" in err
    # Help should still list preflight.
    assert "preflight" in err
