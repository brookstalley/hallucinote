"""Job registry for async start+poll MCP actions (MCP-9R3T)."""
from __future__ import annotations

import threading

from hallucinote_mcp.handlers.jobs import Job, JobRegistry, default_registry


class TestJobRegistry:
    def test_create_returns_running_job_with_unique_id(self):
        reg = JobRegistry()
        a = reg.create(kind="render", dir="/tmp/a")
        b = reg.create(kind="render", dir="/tmp/b")
        assert a.state == "running" and b.state == "running"
        assert a.job_id != b.job_id
        assert a.job_id.startswith("render-")
        assert reg.get(a.job_id) is a

    def test_get_unknown_returns_none(self):
        assert JobRegistry().get("nope") is None

    def test_active_returns_most_recent_running_of_kind(self):
        reg = JobRegistry()
        r1 = reg.create(kind="render", dir="/tmp/1")
        an = reg.create(kind="analyze", dir="/tmp/a")
        r2 = reg.create(kind="render", dir="/tmp/2")
        assert reg.active("render") is r2  # most recent running render
        assert reg.active("analyze") is an
        reg.mark_done(r2.job_id, {"manifest": {}})
        assert reg.active("render") is r1  # r2 no longer running

    def test_active_none_when_all_terminal(self):
        reg = JobRegistry()
        j = reg.create(kind="render", dir="/tmp/1")
        reg.mark_failed(j.job_id, "boom")
        assert reg.active("render") is None

    def test_recent_ids_newest_first_filtered_by_kind(self):
        reg = JobRegistry()
        r1 = reg.create(kind="render", dir="/1")
        a1 = reg.create(kind="analyze", dir="/a")
        r2 = reg.create(kind="render", dir="/2")
        assert reg.recent_ids(kind="render") == [r2.job_id, r1.job_id]
        assert reg.recent_ids() == [r2.job_id, a1.job_id, r1.job_id]
        assert reg.recent_ids(limit=1) == [r2.job_id]

    def test_mark_done_sets_state_result_and_fires_terminal(self):
        reg = JobRegistry()
        j = reg.create(kind="render", dir="/tmp")
        assert j.terminal_event.is_set() is False
        reg.mark_done(j.job_id, {"manifest": {"surfaces": 3}, "status": "ok"})
        assert j.state == "done"
        assert j.result == {"manifest": {"surfaces": 3}, "status": "ok"}
        assert j.terminal_event.is_set() is True

    def test_mark_failed_sets_error_and_fires_terminal(self):
        reg = JobRegistry()
        j = reg.create(kind="render", dir="/tmp")
        reg.mark_failed(j.job_id, "render blew up")
        assert j.state == "failed"
        assert j.error == "render blew up"
        assert j.terminal_event.is_set() is True

    def test_update_progress_replaces_progress(self):
        reg = JobRegistry()
        j = reg.create(kind="render", dir="/tmp")
        reg.update_progress(j.job_id, {"current_beat": 8, "target_beat": 64})
        assert j.progress == {"current_beat": 8, "target_beat": 64}
        reg.update_progress(j.job_id, {"current_beat": 32, "target_beat": 64})
        assert j.progress["current_beat"] == 32

    def test_mutators_on_unknown_id_are_noops(self):
        reg = JobRegistry()
        # Must not raise — the worker may race a vanished job in theory.
        reg.mark_done("nope", {})
        reg.mark_failed("nope", "x")
        reg.update_progress("nope", {"a": 1})


class TestJobWaitTerminal:
    def test_wait_returns_false_while_running_true_after_terminal(self):
        reg = JobRegistry()
        j = reg.create(kind="render", dir="/tmp")
        assert j.wait_terminal(timeout=0.01) is False  # still running
        # A background finisher fires the terminal event mid-wait.
        threading.Timer(0.05, lambda: reg.mark_done(j.job_id, {"manifest": {}})).start()
        assert j.wait_terminal(timeout=2.0) is True
        assert j.state == "done"


class TestResultShapes:
    def test_render_start_result(self):
        j = Job(job_id="render-x", kind="render", dir="/cap", eta_seconds=90,
                expected_stop_beat=64)
        out = j.start_result("POLL ME")
        assert out == {
            "job_id": "render-x", "kind": "render", "state": "running",
            "eta_seconds": 90, "poll": "POLL ME",
            "captures_dir": "/cap", "expected_stop_beat": 64,
        }

    def test_analyze_start_result_uses_report_dir_and_omits_stop_beat(self):
        j = Job(job_id="analyze-y", kind="analyze", dir="/rep", eta_seconds=12)
        out = j.start_result("POLL")
        assert out["report_dir"] == "/rep"
        assert "captures_dir" not in out
        assert "expected_stop_beat" not in out

    def test_render_status_done_carries_manifest(self):
        j = Job(job_id="render-z", kind="render", dir="/cap")
        j.state = "done"
        j.result = {"manifest": {"surfaces": 3}, "manifest_path": "/cap/m.json",
                    "status": "incomplete"}
        out = j.status_result()
        assert out["state"] == "done"
        assert out["manifest"] == {"surfaces": 3}
        assert out["manifest_path"] == "/cap/m.json"
        assert out["render_status"] == "incomplete"

    def test_render_status_failed_carries_error(self):
        j = Job(job_id="render-z", kind="render", dir="/cap")
        j.state = "failed"
        j.error = "no frames captured"
        out = j.status_result()
        assert out["state"] == "failed"
        assert out["error"] == "no frames captured"
        assert "manifest" not in out

    def test_running_status_has_progress_no_result(self):
        j = Job(job_id="render-z", kind="render", dir="/cap")
        j.progress = {"current_beat": 10, "target_beat": 64, "frames_received": 5}
        out = j.status_result()
        assert out["state"] == "running"
        assert out["progress"]["current_beat"] == 10
        assert "manifest" not in out and "error" not in out


def test_default_registry_is_a_process_singleton():
    assert default_registry() is default_registry()
