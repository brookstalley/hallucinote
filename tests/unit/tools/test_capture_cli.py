"""Tests for `tools/capture.py` CLI surface (W12-B `diff` subcommand)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
CAPTURE_CLI = REPO_ROOT / "tools" / "capture.py"


def _run(*args: str, check: bool = False) -> subprocess.CompletedProcess:
    """Run `tools/capture.py` with the given args, no shell."""
    return subprocess.run(
        [sys.executable, str(CAPTURE_CLI), *args],
        capture_output=True,
        text=True,
        check=check,
        cwd=REPO_ROOT,
    )


def _write_snapshot(path: Path, snap: dict) -> None:
    path.write_text(json.dumps(snap, indent=2))


def _make_snap() -> dict:
    return {
        "song": {"tempo": 120.0, "signature": "4/4", "master": {"volume": 0.85}},
        "returns": [{"index": 1, "name": "Reverb", "volume": 0.85}],
        "tracks": [{"index": 1, "name": "Drums", "type": "midi", "volume": 0.6}],
    }


def test_diff_exits_zero_on_identical(tmp_path: Path) -> None:
    snap = _make_snap()
    old = tmp_path / "old.json"
    new = tmp_path / "new.json"
    _write_snapshot(old, snap)
    _write_snapshot(new, snap)
    proc = _run("diff", str(old), str(new))
    assert proc.returncode == 0
    # stdout is the JSON diff; empty diff serializes as `{}`.
    assert json.loads(proc.stdout) == {}
    # stderr carries the human summary.
    assert "No changes" in proc.stderr


def test_diff_exits_one_on_changes(tmp_path: Path) -> None:
    old_snap = _make_snap()
    new_snap = _make_snap()
    new_snap["song"]["tempo"] = 132.0
    old = tmp_path / "old.json"
    new = tmp_path / "new.json"
    _write_snapshot(old, old_snap)
    _write_snapshot(new, new_snap)
    proc = _run("diff", str(old), str(new))
    assert proc.returncode == 1, f"expected exit 1 on changes, got {proc.returncode}: {proc.stderr}"
    diff = json.loads(proc.stdout)
    assert diff == {"song": {"tempo": {"old": 120.0, "new": 132.0}}}
    assert "tempo" in proc.stderr


def test_diff_missing_old_file_returns_two(tmp_path: Path) -> None:
    new = tmp_path / "new.json"
    _write_snapshot(new, _make_snap())
    proc = _run("diff", str(tmp_path / "absent.json"), str(new))
    assert proc.returncode == 2
    assert "old snapshot not found" in proc.stderr


def test_diff_missing_new_file_returns_two(tmp_path: Path) -> None:
    old = tmp_path / "old.json"
    _write_snapshot(old, _make_snap())
    proc = _run("diff", str(old), str(tmp_path / "absent.json"))
    assert proc.returncode == 2
    assert "new snapshot not found" in proc.stderr


def test_plan_subcommand_still_works() -> None:
    """The new subcommand shape preserves the legacy --plan flag."""
    proc = _run("--plan")
    assert proc.returncode == 0
    plan = json.loads(proc.stdout)
    assert isinstance(plan, list) and plan, "expected non-empty probe plan"
    assert all("tool" in entry and "purpose" in entry for entry in plan)


def test_plan_as_subcommand_works() -> None:
    proc = _run("plan")
    assert proc.returncode == 0
    plan = json.loads(proc.stdout)
    assert isinstance(plan, list) and plan
