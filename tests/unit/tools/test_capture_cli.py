"""Tests for `tools/capture_cli.py` CLI surface (W12-B `diff` subcommand)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]


def _run(*args: str, check: bool = False) -> subprocess.CompletedProcess:
    """Run `hallucinote.tools.capture_cli` (installed module) with the given args."""
    return subprocess.run(
        [sys.executable, "-m", "hallucinote.tools.capture_cli", *args],
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


# ---------------------------------------------------------------------------
# SNP-8R4K chunk 2 — `migrate` subcommand (clean a committed snapshot at rest)
# ---------------------------------------------------------------------------

ANALYZER = "HallucinoteAnalyzer"


def _analyzer_entry(index: int) -> dict:
    return {
        "index": index, "name": ANALYZER,
        "class": "Max Audio Effect", "class_name": "MxDeviceAudioEffect",
    }


def _polluted_snap() -> dict:
    """Unstamped snapshot carrying analyzer entries on a track and a return."""
    return {
        "song": {"tempo": 120.0, "signature": "4/4", "master": {"volume": 0.85}},
        "returns": [{
            "index": 1, "name": "Reverb", "volume": 0.85,
            "devices": [
                {"index": 1, "name": "Reverb", "class": "Reverb"},
                _analyzer_entry(2),
            ],
        }],
        "tracks": [{
            "index": 1, "name": "Drums", "type": "midi", "volume": 0.6,
            "devices": [
                {"index": 1, "name": "Operator", "class": "Operator"},
                _analyzer_entry(2),
                {"index": 3, "name": "EQ Eight", "class": "EQ Eight"},
            ],
        }],
    }


def test_migrate_cleans_polluted_snapshot_and_prints_report(tmp_path: Path) -> None:
    snap_path = tmp_path / "captured_session.json"
    _write_snapshot(snap_path, _polluted_snap())

    proc = _run("migrate", str(snap_path))
    assert proc.returncode == 0, proc.stderr

    cleaned = json.loads(snap_path.read_text())
    # Analyzer-free, dense positions, stamped.
    assert cleaned["snapshot_version"] == 1
    track_devs = cleaned["tracks"][0]["devices"]
    assert [d["name"] for d in track_devs] == ["Operator", "EQ Eight"]
    assert [d["index"] for d in track_devs] == [1, 2]
    assert all(d["name"] != ANALYZER for d in track_devs)
    return_devs = cleaned["returns"][0]["devices"]
    assert [d["name"] for d in return_devs] == ["Reverb"]

    # The report is printed (never silent): per-parent removals + total.
    out = proc.stdout
    assert "stripped 2 analyzer device entries" in out
    assert "track 'Drums': removed 1" in out
    assert "return 'Reverb': removed 1" in out


def test_migrate_is_noop_on_clean_stamped_snapshot(tmp_path: Path) -> None:
    snap_path = tmp_path / "captured_session.json"
    clean = {
        "snapshot_version": 1,
        "song": {"tempo": 120.0, "signature": "4/4", "master": {"volume": 0.85}},
        "returns": [{"index": 1, "name": "Reverb", "volume": 0.85}],
        "tracks": [{"index": 1, "name": "Drums", "type": "midi", "volume": 0.6}],
    }
    _write_snapshot(snap_path, clean)
    before = snap_path.read_text()

    proc = _run("migrate", str(snap_path))
    assert proc.returncode == 0
    assert "already clean (v1)" in proc.stdout
    # No-op: the file is byte-for-byte unchanged.
    assert snap_path.read_text() == before


def test_migrate_missing_file_returns_two(tmp_path: Path) -> None:
    proc = _run("migrate", str(tmp_path / "absent.json"))
    assert proc.returncode == 2
    assert "snapshot not found" in proc.stderr
