"""Async render start/status handlers (MCP-9R3T) — start backgrounds a render
and returns a job handle; status long-polls the registry.

These exercise the substrate with a Live seam (a fake context) and a fake
render_fn, so they run headless. The real-Live behavior (a detached worker
keeping the render alive after start returns, and a concurrent call not
blocking) is queued in operator-verification.md.
"""
from __future__ import annotations

import threading
from pathlib import Path

import pytest

from hallucinote_mcp.handlers.jobs import JobRegistry
from hallucinote_mcp.handlers.render import (
    render_start_handler,
    render_status_handler,
)


# ---- Live seam -------------------------------------------------------


class FakeClip:
    def __init__(self, end_time: float) -> None:
        self.end_time = end_time


class FakeTrack:
    def __init__(self, clips: list[FakeClip]) -> None:
        self.arrangement_clips = clips


class FakeSong:
    def __init__(self, tempo=120.0, tracks=None, last_event_time=64.0) -> None:
        self.tempo = tempo
        self.tracks = tracks or []
        self.last_event_time = last_event_time


class FakeCtx:
    def __init__(self, **kw) -> None:
        self._song = FakeSong(**kw)

    @property
    def song(self) -> FakeSong:
        return self._song

    def run_on_main(self, fn):
        return fn()


def make_fake_render(*, manifest=None, status="ok", progress=None, on_call=None):
    """A stand-in render_fn that optionally emits one progress heartbeat and
    returns a manifest-shaped result."""

    def _fn(context, *, song_slug, output_dir, _status_writer=None, **kw):
        if on_call is not None:
            on_call()
        if _status_writer is not None and progress is not None:
            _status_writer(Path(output_dir), progress)
        return {
            "captures_dir": output_dir,
            "manifest_path": str(Path(output_dir) / "manifest.json"),
            "manifest": manifest if manifest is not None else {"surfaces": 3},
            "status": status,
        }

    return _fn


def _capturing_spawn():
    """A _spawn seam that captures the worker instead of running it, so a test
    controls exactly when (and whether) it runs."""
    captured: list = []
    return captured, captured.append


# ---- start: handle + worker wiring -----------------------------------


def test_start_returns_running_handle_before_worker_runs(tmp_path):
    reg = JobRegistry()
    spawned, spawn = _capturing_spawn()
    out = render_start_handler(
        FakeCtx(tempo=120.0),
        song_slug="s",
        output_dir=str(tmp_path),
        start_at_beat=0,
        stop_at_beat=64,
        ring_out_beats=8,
        _registry=reg,
        _render_fn=make_fake_render(),
        _spawn=spawn,
    )
    # Handle is returned immediately; the worker has NOT run yet.
    assert out["job_id"].startswith("render-")
    assert out["state"] == "running"
    assert out["captures_dir"] == str(tmp_path)
    assert out["expected_stop_beat"] == 64
    # eta = (64 - 0 + 8) beats / 120 bpm * 60 = 36 s
    assert out["eta_seconds"] == 36
    assert "poll" in out and out["job_id"] in out["poll"]
    assert "status" in out["poll"]
    assert reg.get(out["job_id"]).state == "running"
    assert len(spawned) == 1  # worker captured, awaiting our call


def test_worker_marks_job_done_with_manifest(tmp_path):
    reg = JobRegistry()
    spawned, spawn = _capturing_spawn()
    out = render_start_handler(
        FakeCtx(), song_slug="s", output_dir=str(tmp_path), stop_at_beat=64,
        _registry=reg, _render_fn=make_fake_render(manifest={"surfaces": 5}),
        _spawn=spawn,
    )
    spawned[0]()  # run the worker now
    job = reg.get(out["job_id"])
    assert job.state == "done"
    assert job.result["manifest"] == {"surfaces": 5}
    # status then reflects the terminal manifest.
    status = render_status_handler(
        FakeCtx(), job_id=out["job_id"], _registry=reg, _long_poll_s=0.0
    )
    assert status["state"] == "done"
    assert status["manifest"] == {"surfaces": 5}


def test_worker_failure_marks_job_failed(tmp_path):
    reg = JobRegistry()
    spawned, spawn = _capturing_spawn()

    def boom(context, **kw):
        raise RuntimeError("no frames captured")

    out = render_start_handler(
        FakeCtx(), song_slug="s", output_dir=str(tmp_path), stop_at_beat=64,
        _registry=reg, _render_fn=boom, _spawn=spawn,
    )
    spawned[0]()
    job = reg.get(out["job_id"])
    assert job.state == "failed"
    assert "no frames captured" in job.error
    status = render_status_handler(
        FakeCtx(), job_id=out["job_id"], _registry=reg, _long_poll_s=0.0
    )
    assert status["state"] == "failed"
    assert "no frames captured" in status["error"]


def test_status_writer_mirrors_progress_to_registry_and_disk(tmp_path):
    reg = JobRegistry()
    spawned, spawn = _capturing_spawn()
    progress = {"state": "running", "current_beat": 16, "target_beat": 64,
                "frames_received": 200}
    out = render_start_handler(
        FakeCtx(), song_slug="s", output_dir=str(tmp_path), stop_at_beat=64,
        _registry=reg, _render_fn=make_fake_render(progress=progress), _spawn=spawn,
    )
    spawned[0]()
    job = reg.get(out["job_id"])
    assert job.progress["current_beat"] == 16
    # The on-disk heartbeat is kept (crash-resilient / dir-watchers).
    assert (tmp_path / "status.json").exists()


def test_terminal_heartbeat_does_not_leak_into_progress(tmp_path):
    # The worker's status writer mirrors only RUNNING heartbeats into
    # job.progress; the terminal done/error write is reflected via state +
    # result, so terminal metadata must not contaminate the progress payload.
    reg = JobRegistry()
    spawned, spawn = _capturing_spawn()

    def render_with_terminal_write(context, *, output_dir, _status_writer=None, **kw):
        _status_writer(Path(output_dir), {"state": "running", "current_beat": 8})
        # The real render writes a terminal status.json before returning.
        _status_writer(Path(output_dir), {"state": "done", "manifest_path": "x"})
        return {"captures_dir": output_dir, "manifest_path": "x",
                "manifest": {"surfaces": 1}, "status": "ok"}

    out = render_start_handler(
        FakeCtx(), song_slug="s", output_dir=str(tmp_path), stop_at_beat=64,
        _registry=reg, _render_fn=render_with_terminal_write, _spawn=spawn,
    )
    spawned[0]()
    job = reg.get(out["job_id"])
    assert job.state == "done"
    # Progress retains the last RUNNING heartbeat, not the terminal write.
    assert job.progress == {"state": "running", "current_beat": 8}
    assert "manifest_path" not in job.progress


def test_expected_stop_beat_falls_back_to_content_end(tmp_path):
    reg = JobRegistry()
    spawned, spawn = _capturing_spawn()
    ctx = FakeCtx(tracks=[FakeTrack([FakeClip(80.0)])])
    out = render_start_handler(
        ctx, song_slug="s", output_dir=str(tmp_path),  # stop_at_beat omitted
        _registry=reg, _render_fn=make_fake_render(), _spawn=spawn,
    )
    assert out["expected_stop_beat"] == 80


# ---- busy / validation -----------------------------------------------


def test_second_start_while_running_returns_busy(tmp_path):
    reg = JobRegistry()
    spawned, spawn = _capturing_spawn()
    first = render_start_handler(
        FakeCtx(), song_slug="s", output_dir=str(tmp_path), stop_at_beat=64,
        _registry=reg, _render_fn=make_fake_render(), _spawn=spawn,
    )
    # first job still running (worker not run); a second start must refuse.
    second = render_start_handler(
        FakeCtx(), song_slug="s", output_dir=str(tmp_path), stop_at_beat=64,
        _registry=reg, _render_fn=make_fake_render(), _spawn=spawn,
    )
    assert second["busy"] is True
    assert second["job_id"] == first["job_id"]
    assert first["job_id"] in second["message"]


def test_start_requires_output_dir():
    with pytest.raises(ValueError, match="output_dir is required"):
        render_start_handler(
            FakeCtx(), song_slug="s", output_dir=None, stop_at_beat=64,
            _registry=JobRegistry(), _render_fn=make_fake_render(),
            _spawn=_capturing_spawn()[1],
        )


def test_status_unknown_job_id_raises_with_recent(tmp_path):
    reg = JobRegistry()
    spawned, spawn = _capturing_spawn()
    started = render_start_handler(
        FakeCtx(), song_slug="s", output_dir=str(tmp_path), stop_at_beat=64,
        _registry=reg, _render_fn=make_fake_render(), _spawn=spawn,
    )
    with pytest.raises(ValueError, match="unknown job_id"):
        render_status_handler(FakeCtx(), job_id="render-doesnotexist", _registry=reg)
    # The error names recent jobs to orient the agent.
    try:
        render_status_handler(FakeCtx(), job_id="render-nope", _registry=reg)
    except ValueError as e:
        assert started["job_id"] in str(e)


# ---- long-poll transition (real worker thread) -----------------------


def test_status_long_polls_running_then_done(tmp_path):
    reg = JobRegistry()
    release = threading.Event()

    def blocking_render(context, *, output_dir, _status_writer=None, **kw):
        if not release.wait(timeout=5.0):
            raise AssertionError("test did not release the render")
        return {
            "captures_dir": output_dir,
            "manifest_path": str(Path(output_dir) / "manifest.json"),
            "manifest": {"surfaces": 1},
            "status": "ok",
        }

    out = render_start_handler(  # default _spawn = real daemon thread
        FakeCtx(), song_slug="s", output_dir=str(tmp_path), stop_at_beat=64,
        _registry=reg, _render_fn=blocking_render,
    )
    job_id = out["job_id"]
    # Worker is blocked → a short long-poll returns running.
    running = render_status_handler(
        FakeCtx(), job_id=job_id, _registry=reg, _long_poll_s=0.05
    )
    assert running["state"] == "running"
    # Release the render; a longer poll catches the terminal transition.
    release.set()
    done = render_status_handler(
        FakeCtx(), job_id=job_id, _registry=reg, _long_poll_s=2.0
    )
    assert done["state"] == "done"
    assert done["manifest"] == {"surfaces": 1}
