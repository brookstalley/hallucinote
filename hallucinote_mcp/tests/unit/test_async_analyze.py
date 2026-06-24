"""Async analyze start/status handlers (MCP-5N8K) — start backgrounds an
analysis and returns a job handle; status long-polls the registry.

``ableton_analysis`` runs in the MCP SERVER process (pure DSP, no Live), so the
async worker is a plain server-process thread — these tests use a fake
``analyze_fn`` + a capturing spawn + a report-dir seam, so they run fully
headless. The real-world payoff (a many-surface / many-section analysis that
exceeds the 60s tool-call timeout) is queued in operator-verification.md.

Siblings: ``test_async_render.py`` exercises the same substrate for render;
``test_handlers_jobs.py`` covers the JobRegistry itself.
"""
from __future__ import annotations

import threading

import pytest

from hallucinote_mcp.dispatcher import dispatch
from hallucinote_mcp.server_side.analysis import (
    analyze_start_handler,
    analyze_status_handler,
)
from hallucinote_mcp.handlers.jobs import JobRegistry
from hallucinote_mcp.wire import Request


# ---- seams -----------------------------------------------------------


def make_fake_analyze(*, report=None, on_call=None):
    """A stand-in analyze_fn returning an analyze_handler-shaped dict
    (``{report_path, schema_version, finding_count, summary, analysis_code}``)."""

    def _fn(_context, *, song_slug, captures_dir=None, compare_to=None):
        if on_call is not None:
            on_call()
        return report if report is not None else {
            "report_path": f"/songs/{song_slug}/analysis/ts.json",
            "schema_version": "1",
            "finding_count": 2,
            "summary": {"master_true_peak_dbtp": -1.0, "overshoot_count": 0},
            "analysis_code": {"signature": "abc", "stale": False},
        }

    return _fn


def _capturing_spawn():
    """A _spawn seam that captures the worker instead of running it, so a test
    controls exactly when (and whether) it runs."""
    captured: list = []
    return captured, captured.append


def _start(reg, spawn, analyze_fn, *, tmp_path, song_slug="s"):
    """Drive analyze_start_handler with the report-dir resolution seamed to
    tmp_path so no real song dir is touched."""
    return analyze_start_handler(
        None,
        song_slug=song_slug,
        _registry=reg,
        _analyze_fn=analyze_fn,
        _spawn=spawn,
        _resolve_report_dir=lambda slug: tmp_path / slug / "analysis",
    )


# ---- start: handle + worker wiring -----------------------------------


def test_analyze_start_returns_running_handle_before_worker_runs(tmp_path):
    reg = JobRegistry()
    spawned, spawn = _capturing_spawn()
    out = _start(reg, spawn, make_fake_analyze(), tmp_path=tmp_path)
    # Handle returned immediately; the worker has NOT run yet.
    assert out["job_id"].startswith("analyze-")
    assert out["state"] == "running"
    assert out["report_dir"] == str(tmp_path / "s" / "analysis")
    # eta is honestly None — analyze runtime has no realtime anchor to estimate.
    assert out["eta_seconds"] is None
    assert "poll" in out and out["job_id"] in out["poll"]
    assert "status" in out["poll"]
    job = reg.get(out["job_id"])
    assert job.state == "running"
    # Coarse progress stage while running (analyze_mix has no fine progress).
    assert job.progress == {"stage": "analyzing"}
    assert len(spawned) == 1  # worker captured, awaiting our call


def test_analyze_worker_marks_job_done_with_report(tmp_path):
    reg = JobRegistry()
    spawned, spawn = _capturing_spawn()
    report = {
        "report_path": "/songs/s/analysis/x.json",
        "schema_version": "1",
        "finding_count": 3,
        "summary": {"overshoot_count": 1},
        "analysis_code": {"signature": "h", "stale": False},
    }
    out = _start(reg, spawn, make_fake_analyze(report=report), tmp_path=tmp_path)
    spawned[0]()  # run the worker now
    job = reg.get(out["job_id"])
    assert job.state == "done"
    status = analyze_status_handler(
        None, job_id=out["job_id"], _registry=reg, _long_poll_s=0.0
    )
    assert status["state"] == "done"
    # `report` is the lightweight analyze bundle (summary + finding_count +
    # schema_version + analysis_code); `report_path` is the convenient accessor.
    assert status["report"] == report
    assert status["report_path"] == "/songs/s/analysis/x.json"
    # The stale flag survives into the status payload (drives "run /mcp first").
    assert status["report"]["analysis_code"]["stale"] is False


def test_analyze_worker_failure_marks_job_failed(tmp_path):
    reg = JobRegistry()
    spawned, spawn = _capturing_spawn()

    def boom(_context, **kw):
        raise RuntimeError("no captures dir at songs/s/captures")

    out = _start(reg, spawn, boom, tmp_path=tmp_path)
    spawned[0]()
    job = reg.get(out["job_id"])
    assert job.state == "failed"
    assert "no captures dir" in job.error
    status = analyze_status_handler(
        None, job_id=out["job_id"], _registry=reg, _long_poll_s=0.0
    )
    assert status["state"] == "failed"
    assert "no captures dir" in status["error"]


# ---- busy / validation -----------------------------------------------


def test_analyze_second_start_while_running_returns_busy(tmp_path):
    reg = JobRegistry()
    spawned, spawn = _capturing_spawn()
    first = _start(reg, spawn, make_fake_analyze(), tmp_path=tmp_path)
    # first job still running (worker not run); a second start must refuse —
    # even for a different song, the DSP runs one-at-a-time per process.
    second = _start(reg, spawn, make_fake_analyze(), tmp_path=tmp_path,
                    song_slug="other-song")
    assert second["busy"] is True
    assert second["job_id"] == first["job_id"]
    assert first["job_id"] in second["message"]


def test_analyze_status_unknown_job_id_raises_with_recent(tmp_path):
    reg = JobRegistry()
    spawned, spawn = _capturing_spawn()
    started = _start(reg, spawn, make_fake_analyze(), tmp_path=tmp_path)
    with pytest.raises(ValueError, match="unknown job_id"):
        analyze_status_handler(None, job_id="analyze-doesnotexist", _registry=reg)
    # The error names recent analyze jobs to orient the agent.
    try:
        analyze_status_handler(None, job_id="analyze-nope", _registry=reg)
    except ValueError as e:
        assert started["job_id"] in str(e)


def test_analyze_status_unknown_job_id_with_no_jobs_says_so(tmp_path):
    reg = JobRegistry()
    with pytest.raises(ValueError, match="no analyze jobs"):
        analyze_status_handler(None, job_id="analyze-x", _registry=reg)


# ---- long-poll transition (real worker thread) -----------------------


def test_analyze_status_long_polls_running_then_done(tmp_path):
    reg = JobRegistry()
    release = threading.Event()

    def blocking_analyze(_context, *, song_slug, captures_dir=None, compare_to=None):
        if not release.wait(timeout=5.0):
            raise AssertionError("test did not release the analyze")
        return {
            "report_path": "/songs/s/analysis/x.json",
            "schema_version": "1",
            "finding_count": 0,
            "summary": {},
            "analysis_code": {"signature": "h", "stale": False},
        }

    out = analyze_start_handler(  # default _spawn = real daemon thread
        None, song_slug="s", _registry=reg, _analyze_fn=blocking_analyze,
        _resolve_report_dir=lambda slug: tmp_path,
    )
    job_id = out["job_id"]
    # Worker is blocked → a short long-poll returns running with coarse progress.
    running = analyze_status_handler(
        None, job_id=job_id, _registry=reg, _long_poll_s=0.05
    )
    assert running["state"] == "running"
    assert running["progress"] == {"stage": "analyzing"}
    assert running["report_dir"] == str(tmp_path)
    # Release the analysis; a longer poll catches the terminal transition.
    release.set()
    done = analyze_status_handler(
        None, job_id=job_id, _registry=reg, _long_poll_s=2.0
    )
    assert done["state"] == "done"
    assert done["report_path"] == "/songs/s/analysis/x.json"


# ---- dispatch wiring (server-side; exceptions → structured error) ----


def test_status_unknown_job_via_dispatch_is_structured_error():
    """analyze status is runs_server_side — an unknown-job raise must come back
    as a structured ok=False response (the dispatcher's server-side boundary
    wraps it), not a raw traceback. Uses the process-default registry, which is
    empty here, so the error explains no analyze jobs have started."""
    resp = dispatch(
        Request(tool="ableton_analysis", action="status",
                params={"job_id": "analyze-nope"}),
        context=None,
    )
    assert resp.ok is False
    assert "unknown job_id" in (resp.error or "")
