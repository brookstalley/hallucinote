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

    def test_create_if_idle_creates_when_slot_free(self):
        reg = JobRegistry()
        job, created = reg.create_if_idle(kind="analyze", dir="/rep")
        assert created is True
        assert job.kind == "analyze" and job.state == "running"
        assert reg.get(job.job_id) is job

    def test_create_if_idle_returns_existing_when_busy(self):
        reg = JobRegistry()
        first, c1 = reg.create_if_idle(kind="render", dir="/a", eta_seconds=10)
        second, c2 = reg.create_if_idle(kind="render", dir="/b")
        assert c1 is True and c2 is False
        assert second is first  # the live job, not a new one
        assert reg.recent_ids(kind="render") == [first.job_id]  # only one created

    def test_create_if_idle_is_per_kind(self):
        reg = JobRegistry()
        r, _ = reg.create_if_idle(kind="render", dir="/r")
        a, created = reg.create_if_idle(kind="analyze", dir="/a")
        # A running render does NOT block claiming the analyze slot.
        assert created is True and a is not r

    def test_create_if_idle_reclaims_after_terminal(self):
        reg = JobRegistry()
        first, _ = reg.create_if_idle(kind="analyze", dir="/a")
        reg.mark_done(first.job_id, {"report": {}, "report_path": None})
        second, created = reg.create_if_idle(kind="analyze", dir="/b")
        assert created is True and second is not first  # slot freed on terminal

    def test_create_if_idle_is_atomic_under_concurrent_starts(self):
        """The async dispatch wrapper lets two `start` calls run on different
        threads at once; the busy guard must let EXACTLY ONE claim the slot (no
        two concurrent renders). A barrier maximizes the contention window."""
        reg = JobRegistry()
        n = 32
        barrier = threading.Barrier(n)
        results: list = [None] * n

        def worker(i: int) -> None:
            barrier.wait()  # release all threads into create_if_idle together
            results[i] = reg.create_if_idle(kind="render", dir=f"/tmp/{i}")

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        created = [r for r in results if r[1] is True]
        assert len(created) == 1, "exactly one start must claim the slot"
        winner = created[0][0]
        # Every loser got the SAME live job back (a busy handle pointing at it).
        for job, was_created in results:
            if not was_created:
                assert job.job_id == winner.job_id
        # And the registry holds exactly one render job, not 32.
        assert reg.recent_ids(kind="render") == [winner.job_id]


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
