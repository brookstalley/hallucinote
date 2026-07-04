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


def test_restamp_refreshes_captured_at_without_content_change(tmp_path: Path) -> None:
    """BAK-7D2V Chunk 3: `restamp` moves captured_at forward (events.ts shape)
    and leaves every other field byte-identical — the empty-diff guard disarm."""
    import re

    snap = _make_snap()
    snap["captured_at"] = "2020-01-01T00:00:00.000Z"
    path = tmp_path / "captured_session.json"
    _write_snapshot(path, snap)

    proc = _run("restamp", str(path))
    assert proc.returncode == 0
    after = json.loads(path.read_text())
    assert re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", after["captured_at"]
    )
    assert after["captured_at"] > "2020-01-01T00:00:00.000Z"
    before = {k: v for k, v in snap.items() if k != "captured_at"}
    after_content = {k: v for k, v in after.items() if k != "captured_at"}
    assert after_content == before


def test_restamp_missing_file_returns_two(tmp_path: Path) -> None:
    proc = _run("restamp", str(tmp_path / "absent.json"))
    assert proc.returncode == 2


def test_restamp_no_target_returns_two() -> None:
    proc = _run("restamp")
    assert proc.returncode == 2


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


# ---------------------------------------------------------------------------
# NODE-ADDR Chunk B — `execute` subcommand bridge glue (_make_probe +
# _cmd_execute). The deterministic walk (assemble_snapshot_via_probes) is
# fake-probe-tested in tests/unit/capture/; these cover the CLI↔bridge wiring
# (the part with real branching), in-process so no live server is needed.
# ---------------------------------------------------------------------------

import argparse  # noqa: E402

import hallucinote.tools.capture_cli as cc  # noqa: E402


class _Resp:
    def __init__(self, ok, result=None, error=None):
        self.ok, self.result, self.error = ok, result, error


def test_make_probe_unwraps_ok_result() -> None:
    seen = {}

    def send_fn(req):
        seen["req"] = req
        return _Resp(True, {"value": 42})

    probe = cc._make_probe(send_fn)
    assert probe("ableton_session", "info", x=1) == {"value": 42}
    assert (seen["req"].tool, seen["req"].action) == ("ableton_session", "info")
    assert seen["req"].params == {"x": 1}


def test_make_probe_raises_loud_on_failure() -> None:
    """A partial snapshot would silently drop authored state -> capture aborts
    loudly rather than compiling a half-walk."""
    probe = cc._make_probe(lambda req: _Resp(False, error="boom"))
    with pytest.raises(RuntimeError, match="capture execute.*boom"):
        probe("ableton_device", "get_parameters")


def test_cmd_execute_writes_refresh_json_and_forwards_old(
    tmp_path: Path, monkeypatch
) -> None:
    out = tmp_path / "captured_session.refresh.json"
    old = tmp_path / "captured_session.json"
    _write_snapshot(old, {"snapshot_version": 1, "browser_path": {"a": "b"}})

    captured = {}

    def fake_assemble(probe, *, old_snapshot=None):
        captured["old"] = old_snapshot
        return {"snapshot_version": 1, "tracks": []}

    monkeypatch.setattr(cc, "_resolve_send_fn", lambda: (lambda req: _Resp(True, {})))
    monkeypatch.setattr(
        "hallucinote.capture.assemble_snapshot_via_probes", fake_assemble
    )

    rc = cc._cmd_execute(
        argparse.Namespace(output=str(out), old=str(old), song=None)
    )
    assert rc == 0
    # Writes the side-by-side refresh file, NOT the canonical name — the canonical
    # snapshot is left untouched (overwriting it before the user sees the diff is
    # the bug /song-snapshot exists to prevent).
    assert json.loads(out.read_text()) == {"snapshot_version": 1, "tracks": []}
    assert json.loads(old.read_text()) == {
        "snapshot_version": 1, "browser_path": {"a": "b"},
    }
    # The old snapshot is loaded + forwarded so browser_path is preserved.
    assert captured["old"] == {"snapshot_version": 1, "browser_path": {"a": "b"}}


def test_cmd_execute_needs_song_or_output(capsys) -> None:
    rc = cc._cmd_execute(argparse.Namespace(output=None, old=None, song=None))
    assert rc == 2
    assert "needs --song" in capsys.readouterr().err
