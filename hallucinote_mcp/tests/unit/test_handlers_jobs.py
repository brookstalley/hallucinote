"""Job registry for async start+poll MCP actions (MCP-9R3T)."""
from __future__ import annotations

import threading

from hallucinote_mcp.handlers.jobs import Job, JobRegistry, default_registry


class TestJobRegistry:
    def test_create_returns_running_job_with_unique_id(self):
        reg = JobRegistry()
        a = reg.create(kind="render", detail={"captures_dir": "/tmp/a"})
        b = reg.create(kind="render", detail={"captures_dir": "/tmp/b"})
        assert a.state == "running" and b.state == "running"
        assert a.job_id != b.job_id
        assert a.job_id.startswith("render-")
        assert reg.get(a.job_id) is a

    def test_get_unknown_returns_none(self):
        assert JobRegistry().get("nope") is None

    def test_recent_ids_newest_first_filtered_by_kind(self):
        reg = JobRegistry()
        r1 = reg.create(kind="render", detail={"captures_dir": "/1"})
        a1 = reg.create(kind="analyze", detail={"report_dir": "/a"})
        r2 = reg.create(kind="render", detail={"captures_dir": "/2"})
        assert reg.recent_ids(kind="render") == [r2.job_id, r1.job_id]
        assert reg.recent_ids() == [r2.job_id, a1.job_id, r1.job_id]
        assert reg.recent_ids(limit=1) == [r2.job_id]

    def test_mark_done_sets_state_result_and_fires_terminal(self):
        reg = JobRegistry()
        j = reg.create(kind="render", detail={"captures_dir": "/tmp"})
        assert j.terminal_event.is_set() is False
        reg.mark_done(j.job_id, {"manifest": {"surfaces": 3}, "status": "ok"})
        assert j.state == "done"
        assert j.result == {"manifest": {"surfaces": 3}, "status": "ok"}
        assert j.terminal_event.is_set() is True

    def test_mark_failed_sets_error_and_fires_terminal(self):
        reg = JobRegistry()
        j = reg.create(kind="render", detail={"captures_dir": "/tmp"})
        reg.mark_failed(j.job_id, "render blew up")
        assert j.state == "failed"
        assert j.error == "render blew up"
        assert j.terminal_event.is_set() is True

    def test_update_progress_replaces_progress(self):
        reg = JobRegistry()
        j = reg.create(kind="render", detail={"captures_dir": "/tmp"})
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
        job, created = reg.create_if_idle(kind="analyze", detail={"report_dir": "/rep"})
        assert created is True
        assert job.kind == "analyze" and job.state == "running"
        assert reg.get(job.job_id) is job

    def test_create_if_idle_returns_existing_when_busy(self):
        reg = JobRegistry()
        first, c1 = reg.create_if_idle(kind="render", detail={"captures_dir": "/a"}, eta_seconds=10)
        second, c2 = reg.create_if_idle(kind="render", detail={"captures_dir": "/b"})
        assert c1 is True and c2 is False
        assert second is first  # the live job, not a new one
        assert reg.recent_ids(kind="render") == [first.job_id]  # only one created

    def test_create_if_idle_is_per_kind(self):
        reg = JobRegistry()
        r, _ = reg.create_if_idle(kind="render", detail={"captures_dir": "/r"})
        a, created = reg.create_if_idle(kind="analyze", detail={"report_dir": "/a"})
        # A running render does NOT block claiming the analyze slot.
        assert created is True and a is not r

    def test_create_if_idle_reclaims_after_terminal(self):
        reg = JobRegistry()
        first, _ = reg.create_if_idle(kind="analyze", detail={"report_dir": "/a"})
        reg.mark_done(first.job_id, {"report": {}, "report_path": None})
        second, created = reg.create_if_idle(kind="analyze", detail={"report_dir": "/b"})
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
            results[i] = reg.create_if_idle(kind="render", detail={"captures_dir": f"/tmp/{i}"})

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
        j = reg.create(kind="render", detail={"captures_dir": "/tmp"})
        assert j.wait_terminal(timeout=0.01) is False  # still running
        # A background finisher fires the terminal event mid-wait.
        threading.Timer(0.05, lambda: reg.mark_done(j.job_id, {"manifest": {}})).start()
        assert j.wait_terminal(timeout=2.0) is True
        assert j.state == "done"


class TestResultShapes:
    def test_render_start_result(self):
        j = Job(
            job_id="render-x", kind="render", eta_seconds=90,
            detail={"captures_dir": "/cap", "expected_stop_beat": 64},
        )
        out = j.start_result("POLL ME")
        assert out == {
            "job_id": "render-x", "kind": "render", "state": "running",
            "eta_seconds": 90, "poll": "POLL ME",
            "captures_dir": "/cap", "expected_stop_beat": 64,
        }

    def test_analyze_start_result_uses_report_dir_and_omits_stop_beat(self):
        j = Job(
            job_id="analyze-y", kind="analyze", eta_seconds=12,
            detail={"report_dir": "/rep"},
        )
        out = j.start_result("POLL")
        assert out["report_dir"] == "/rep"
        assert "captures_dir" not in out
        assert "expected_stop_beat" not in out

    def test_detail_rides_both_the_start_and_the_status_payload(self):
        """``detail`` is the generalization of the old per-kind ``dir``: one
        dict merged into BOTH payloads, so a new job kind publishes its own
        facts without a third arm on a two-way ``if kind ==`` branch."""
        j = Job(
            job_id="main_thread-abc", kind="main_thread",
            detail={"label": "ableton_device('load')", "elapsed_s": 121.5},
        )
        for out in (j.start_result("POLL"), j.status_result()):
            assert out["label"] == "ableton_device('load')"
            assert out["elapsed_s"] == 121.5

    def test_main_thread_status_done_carries_the_calls_own_result(self):
        """An escalated caller that polls to ``done`` must get what the Live
        call returned — otherwise it learns only that the work ended, and has
        to re-issue the very call that is now finished."""
        j = Job(job_id="main_thread-abc", kind="main_thread",
                detail={"label": "x", "elapsed_s": 1.0})
        j.state = "done"
        j.result = {"result": {"loaded_class_name": "Reverb"}}
        out = j.status_result()
        assert out["result"] == {"loaded_class_name": "Reverb"}
        assert "manifest" not in out and "report" not in out

    def test_main_thread_status_does_not_borrow_analyzes_terminal_keys(self):
        """The terminal branch names every kind. A bare ``else`` used to mean
        'analyze', so a third kind would have silently published ``report`` /
        ``report_path`` keys it never had."""
        j = Job(job_id="main_thread-abc", kind="main_thread", detail={})
        j.state = "done"
        j.result = {"result": None}
        out = j.status_result()
        assert "report" not in out and "report_path" not in out

    def test_render_status_done_carries_manifest(self):
        j = Job(job_id="render-z", kind="render", detail={"captures_dir": "/cap"})
        j.state = "done"
        j.result = {"manifest": {"surfaces": 3}, "manifest_path": "/cap/m.json",
                    "status": "incomplete"}
        out = j.status_result()
        assert out["state"] == "done"
        assert out["manifest"] == {"surfaces": 3}
        assert out["manifest_path"] == "/cap/m.json"
        assert out["render_status"] == "incomplete"

    def test_render_status_carries_an_advisory_the_render_did_not_refuse_on(self):
        """The render is async, so this projection is the ONLY path from a
        render result to a caller — and it is an allowlist, so a handler that
        adds an advisory and stops there has added nothing.

        Chunk 04 shipped exactly that: a soloed-chain warning on the render
        result, four green tests calling `render_handler` in-process, and a key
        the projection dropped in production. An in-process handler test cannot
        see this boundary at all; this is the test that can.
        """
        j = Job(job_id="render-z", kind="render", detail={"captures_dir": "/cap"})
        j.state = "done"
        j.result = {
            "manifest": {"surfaces": 3}, "manifest_path": "/cap/m.json",
            "status": "ok",
            "warning": "1 soloed rack chain(s) during this render: ...",
        }
        out = j.status_result()
        assert out["warning"] == j.result["warning"]

    def test_render_status_omits_the_advisory_when_there_is_none(self):
        """Present only when there is something to say. An always-set key makes
        "nothing to report" and "reported nothing" the same payload."""
        j = Job(job_id="render-z", kind="render", detail={"captures_dir": "/cap"})
        j.state = "done"
        j.result = {"manifest": {}, "manifest_path": "/cap/m.json", "status": "ok"}
        out = j.status_result()
        assert "warning" not in out

    def test_render_status_failed_carries_error(self):
        j = Job(job_id="render-z", kind="render", detail={"captures_dir": "/cap"})
        j.state = "failed"
        j.error = "no frames captured"
        out = j.status_result()
        assert out["state"] == "failed"
        assert out["error"] == "no frames captured"
        assert "manifest" not in out

    def test_running_status_has_progress_no_result(self):
        j = Job(job_id="render-z", kind="render", detail={"captures_dir": "/cap"})
        j.progress = {"current_beat": 10, "target_beat": 64, "frames_received": 5}
        out = j.status_result()
        assert out["state"] == "running"
        assert out["progress"]["current_beat"] == 10
        assert "manifest" not in out and "error" not in out


def test_default_registry_is_a_process_singleton():
    assert default_registry() is default_registry()
