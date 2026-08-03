"""Retention window over capture takes (`hallucinote.takes`).

The sweep deletes multi-gigabyte directories, so these tests pin the guards as
hard as the happy path: what must survive, what must never be reachable, and
that planning writes nothing.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from hallucinote import takes as T


def _make_take(
    root: Path,
    name: str,
    *,
    captured_at: str | None = None,
    wav_bytes: int = 1024,
    pinned: bool = False,
    status_state: str | None = None,
    manifest: bool = True,
) -> Path:
    """Build a take dir shaped like a real render's output."""
    take = root / name
    take.mkdir(parents=True)
    if manifest:
        payload = {"schema_version": "1", "song_slug": "demo"}
        if captured_at is not None:
            payload["captured_at"] = captured_at
        (take / T.MANIFEST_FILENAME).write_text(json.dumps(payload), encoding="utf-8")
    (take / "master.wav").write_bytes(b"\0" * wav_bytes)
    if pinned:
        (take / T.PIN_FILENAME).write_text("", encoding="utf-8")
    if status_state is not None:
        (take / T.STATUS_FILENAME).write_text(
            json.dumps({"state": status_state}), encoding="utf-8"
        )
    return take


# --- listing + ordering ----------------------------------------------------


def test_list_takes_orders_by_manifest_captured_at_not_dir_name(tmp_path):
    """A hand-named dir must not shadow a newer timestamped render.

    'v' (0x76) sorts above every '2026…' (0x32), so name-ordering would put the
    hand-named take first and the sweep would delete the genuinely newest
    render. Ordering keys on the manifest's captured_at instead.
    """
    _make_take(tmp_path, "v4-seam-verse2", captured_at="20260101T000000Z")
    _make_take(tmp_path, "20260607T035338Z", captured_at="20260607T035338Z")

    ordered = [t.path.name for t in T.list_takes(tmp_path)]

    assert ordered == ["20260607T035338Z", "v4-seam-verse2"]


def test_list_takes_ignores_dirs_without_a_manifest(tmp_path):
    """A stray directory is not a take, so the sweep can never reach it."""
    _make_take(tmp_path, "20260607T000000Z", captured_at="20260607T000000Z")
    (tmp_path / "scratch-notes").mkdir()
    (tmp_path / "scratch-notes" / "keep-me.txt").write_text("x", encoding="utf-8")

    assert [t.path.name for t in T.list_takes(tmp_path)] == ["20260607T000000Z"]


def test_list_takes_returns_empty_for_missing_root(tmp_path):
    assert T.list_takes(tmp_path / "nope") == []


def test_take_size_counts_the_whole_directory(tmp_path):
    take = _make_take(tmp_path, "20260607T000000Z", wav_bytes=2048)
    (take / "track-01.wav").write_bytes(b"\0" * 4096)

    (listed,) = T.list_takes(tmp_path)

    # 2048 + 4096 WAV bytes plus the manifest's own bytes.
    assert listed.size_bytes > 6144


# --- keep-window classification --------------------------------------------


def test_plan_sweep_keeps_the_newest_n_and_sweeps_the_rest(tmp_path):
    for i in range(4):
        _make_take(tmp_path, f"take-{i}", captured_at=f"2026060{i}T000000Z")

    plan = T.plan_sweep(tmp_path, keep=2)

    assert [t.path.name for t in plan.kept] == ["take-3", "take-2"]
    assert [t.path.name for t in plan.sweep] == ["take-1", "take-0"]


def test_plan_sweep_with_keep_zero_sweeps_every_unprotected_take(tmp_path):
    _make_take(tmp_path, "take-0", captured_at="20260601T000000Z")
    _make_take(tmp_path, "take-1", captured_at="20260602T000000Z")

    plan = T.plan_sweep(tmp_path, keep=0)

    assert len(plan.sweep) == 2
    assert plan.kept == ()


def test_plan_sweep_rejects_a_negative_keep(tmp_path):
    with pytest.raises(ValueError, match="keep must be >= 0"):
        T.plan_sweep(tmp_path, keep=-1)


def test_plan_sweep_writes_nothing(tmp_path):
    for i in range(4):
        _make_take(tmp_path, f"take-{i}", captured_at=f"2026060{i}T000000Z")
    before = sorted(p.name for p in tmp_path.iterdir())

    plan = T.plan_sweep(tmp_path, keep=1)

    assert len(plan.sweep) == 3
    assert sorted(p.name for p in tmp_path.iterdir()) == before


def test_reclaimable_bytes_sums_only_the_swept_takes(tmp_path):
    _make_take(tmp_path, "take-0", captured_at="20260601T000000Z", wav_bytes=5000)
    _make_take(tmp_path, "take-1", captured_at="20260602T000000Z", wav_bytes=9000)

    plan = T.plan_sweep(tmp_path, keep=1)

    assert plan.reclaimable_bytes == plan.sweep[0].size_bytes
    assert plan.reclaimable_bytes < 9000  # take-1 survived, so its bytes aren't counted


# --- the guards ------------------------------------------------------------


def test_pinned_take_survives_past_the_window(tmp_path):
    _make_take(tmp_path, "take-0", captured_at="20260601T000000Z", pinned=True)
    for i in range(1, 4):
        _make_take(tmp_path, f"take-{i}", captured_at=f"2026060{i}T000000Z")

    plan = T.plan_sweep(tmp_path, keep=1)

    assert "take-0" in [t.path.name for t in plan.kept]
    assert "take-0" not in [t.path.name for t in plan.sweep]


def test_pinned_take_does_not_consume_a_keep_slot(tmp_path):
    """Pinning a reference take must not silently evict a working one."""
    _make_take(tmp_path, "pinned", captured_at="20260601T000000Z", pinned=True)
    _make_take(tmp_path, "older", captured_at="20260602T000000Z")
    _make_take(tmp_path, "newer", captured_at="20260603T000000Z")

    plan = T.plan_sweep(tmp_path, keep=2)

    # Both unpinned takes fit the window of 2; the pin is additional, not a
    # competitor for a slot, so nothing is swept at all.
    assert plan.sweep == ()
    assert {t.path.name for t in plan.kept} == {"pinned", "older", "newer"}


def test_in_flight_take_is_never_swept(tmp_path):
    _make_take(
        tmp_path, "running", captured_at="20260601T000000Z", status_state="running"
    )
    _make_take(tmp_path, "newer", captured_at="20260603T000000Z")

    plan = T.plan_sweep(tmp_path, keep=1)

    assert plan.sweep == ()


def test_terminal_status_take_is_sweepable(tmp_path):
    """state=done means the render is over — retention applies normally."""
    _make_take(tmp_path, "done", captured_at="20260601T000000Z", status_state="done")
    _make_take(tmp_path, "newer", captured_at="20260603T000000Z")

    plan = T.plan_sweep(tmp_path, keep=1)

    assert [t.path.name for t in plan.sweep] == ["done"]


def test_force_overrides_the_in_flight_guard(tmp_path):
    """A render that died leaves state=running forever; force clears it."""
    _make_take(
        tmp_path, "stale", captured_at="20260601T000000Z", status_state="running"
    )
    _make_take(tmp_path, "newer", captured_at="20260603T000000Z")

    plan = T.plan_sweep(tmp_path, keep=1, force=True)

    assert [t.path.name for t in plan.sweep] == ["stale"]


def test_protected_dir_is_never_swept(tmp_path):
    """The render path protects the dir it is about to write into."""
    incoming = _make_take(tmp_path, "incoming", captured_at="20260601T000000Z")
    for i in range(3):
        _make_take(tmp_path, f"take-{i}", captured_at=f"2026060{i + 2}T000000Z")

    plan = T.plan_sweep(tmp_path, keep=1, protect=(incoming,))

    assert "incoming" not in [t.path.name for t in plan.sweep]


def test_protect_matches_through_an_unresolved_path(tmp_path):
    """A protect entry with '..' segments must still match the take it names."""
    _make_take(tmp_path, "incoming", captured_at="20260601T000000Z")
    _make_take(tmp_path, "newer", captured_at="20260609T000000Z")
    indirect = tmp_path / "newer" / ".." / "incoming"

    plan = T.plan_sweep(tmp_path, keep=1, protect=(indirect,))

    assert plan.sweep == ()


# --- execution -------------------------------------------------------------


def test_execute_sweep_removes_planned_takes_and_leaves_the_rest(tmp_path):
    for i in range(4):
        _make_take(tmp_path, f"take-{i}", captured_at=f"2026060{i}T000000Z")
    plan = T.plan_sweep(tmp_path, keep=2)

    result = T.execute_sweep(plan)

    assert sorted(p.name for p in tmp_path.iterdir()) == ["take-2", "take-3"]
    assert len(result.removed) == 2
    assert result.freed_bytes > 0
    assert result.failures == ()


def test_execute_sweep_collects_failures_without_aborting(tmp_path, monkeypatch):
    """One stuck directory must not strand the rest of the reclaimable space."""
    for i in range(3):
        _make_take(tmp_path, f"take-{i}", captured_at=f"2026060{i}T000000Z")
    plan = T.plan_sweep(tmp_path, keep=0)
    doomed = plan.sweep[-1].path  # the oldest

    real_rmtree = T.shutil.rmtree

    def _flaky(path, *a, **kw):
        if Path(path) == doomed:
            raise OSError("Device or resource busy")
        return real_rmtree(path, *a, **kw)

    monkeypatch.setattr(T.shutil, "rmtree", _flaky)
    result = T.execute_sweep(plan)

    assert len(result.removed) == 2
    assert [p for p, _ in result.failures] == [doomed]
    assert doomed.exists()


def test_execute_sweep_on_an_empty_plan_is_a_no_op(tmp_path):
    _make_take(tmp_path, "only", captured_at="20260601T000000Z")
    plan = T.plan_sweep(tmp_path, keep=5)

    result = T.execute_sweep(plan)

    assert result.removed == ()
    assert result.freed_bytes == 0
    assert (tmp_path / "only").exists()


def test_sweep_only_reaches_immediate_subdirs_of_the_captures_root(tmp_path):
    """A song's durable files sit beside captures/ and must be unreachable."""
    song = tmp_path / "songs" / "demo"
    captures = song / "captures"
    captures.mkdir(parents=True)
    (song / "captured_session.json").write_text("{}", encoding="utf-8")
    (song / "build.py").write_text("# build", encoding="utf-8")
    (song / "analysis").mkdir()
    (song / "analysis" / "20260607T000000Z.json").write_text("{}", encoding="utf-8")
    for i in range(3):
        _make_take(captures, f"take-{i}", captured_at=f"2026060{i}T000000Z")

    T.execute_sweep(T.plan_sweep(captures, keep=0))

    assert (song / "captured_session.json").exists()
    assert (song / "build.py").exists()
    assert (song / "analysis" / "20260607T000000Z.json").exists()
    assert list(captures.iterdir()) == []


# --- configuration ---------------------------------------------------------


def test_keep_from_env_reads_the_variable(monkeypatch):
    monkeypatch.setenv(T.ENV_KEEP, "5")
    assert T.keep_from_env() == 5


def test_keep_from_env_defaults_when_unset(monkeypatch):
    monkeypatch.delenv(T.ENV_KEEP, raising=False)
    assert T.keep_from_env() == T.DEFAULT_KEEP


@pytest.mark.parametrize("raw", ["", "two", "-1", "3.5"])
def test_keep_from_env_falls_back_on_a_bad_value(monkeypatch, raw):
    """A typo'd env var must never widen the sweep — it falls back, not to 0."""
    monkeypatch.setenv(T.ENV_KEEP, raw)
    assert T.keep_from_env() == T.DEFAULT_KEEP


@pytest.mark.parametrize("raw", ["0", "false", "no", "off", "OFF"])
def test_sweep_disabled_by_env(monkeypatch, raw):
    monkeypatch.setenv(T.ENV_SWEEP, raw)
    assert T.sweep_enabled() is False


@pytest.mark.parametrize("raw", ["1", "true", "yes", "anything"])
def test_sweep_enabled_by_default_and_for_other_values(monkeypatch, raw):
    monkeypatch.setenv(T.ENV_SWEEP, raw)
    assert T.sweep_enabled() is True


def test_sweep_enabled_when_unset(monkeypatch):
    monkeypatch.delenv(T.ENV_SWEEP, raising=False)
    assert T.sweep_enabled() is True


# --- import hygiene --------------------------------------------------------


def test_module_imports_without_the_numpy_analysis_stack():
    """The MCP server imports this on the render path and is stdlib-only at
    startup — so `takes` must not drag in numpy/librosa the way
    `hallucinote.audio` does."""
    code = (
        "import sys;"
        "sys.modules['numpy'] = None;"
        "sys.modules['librosa'] = None;"
        "import hallucinote.takes as t;"
        "print(t.DEFAULT_KEEP)"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src")},
    )

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == str(T.DEFAULT_KEEP)


def test_format_bytes_scales_units():
    assert T.format_bytes(512) == "512 B"
    assert T.format_bytes(2048) == "2.0 KB"
    assert T.format_bytes(5 * 1024**2) == "5.0 MB"
    assert T.format_bytes(3 * 1024**3) == "3.0 GB"
