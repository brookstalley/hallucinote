"""Process-local job registry for long-running async MCP actions.

Background: Claude Code has no wake-on-done for MCP tools and the tool-call
timeout is a transport-agnostic wall-clock limit, so a multi-minute render or a
many-surface analysis MUST use a **start + poll** pattern (see
``.prawduct/artifacts/plans/MCP-ASYNC-RENDER-ANALYZE/api-notes.md`` for the full
design + the persisted-shape lock-in). ``start`` kicks the work onto a detached
worker and returns a job handle immediately; ``status`` long-polls this registry.

**One registry instance per process.** ``ableton_render`` runs Live-side (its
worker marshals onto Live's main thread), so render jobs live in the Remote
Script process; ``ableton_analysis`` runs in the MCP server process (pure DSP),
so analyze jobs live there. Both halves import this module, so the module-level
``_REGISTRY`` singleton is naturally per-process — and a ``status`` poll, routed
to the same tool that started the job, always reaches the right process's
registry. The registry is the in-memory source of truth across MCP calls within
a process's lifetime; render additionally writes ``status.json`` to disk as a
crash-resilient heartbeat (handled by the render handler, not here).
"""
from __future__ import annotations

import datetime as dt
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Literal
from uuid import uuid4

JobState = Literal["running", "done", "failed"]
JobKind = Literal["render", "analyze"]

# The status long-poll window — how long a ``status`` call waits for a job to
# leave ``running`` before returning, so the agent's poll loop is a handful of
# calls, not a busy spin. Sized UNDER the 60s per-tool-call timeout in
# ``.claude-plugin/plugin.json`` (the very limit that makes a synchronous
# render/analyze false-fail), leaving ~15s for forward + serialize. Shared by
# EVERY async ``status`` handler (render + analyze) so the window is one knob,
# not two that drift — the api-notes "(raise the long-poll, the socket timeout,
# AND plugin.json's timeout together)" treats it as a single lever. Render's
# status additionally rides a socket (``client._STATUS_READ_TIMEOUT``, sized
# just above this); analyze's status is in-process (no socket) so this is its
# only ceiling.
DEFAULT_STATUS_LONG_POLL_S: float = 45.0


def _utc_now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class Job:
    """One async job. Mutable: the worker thread advances ``state``/``progress``
    while ``status`` polls read it; the registry lock guards every field write.

    **Concurrency invariant.** Readers (``start_result`` / ``status_result``)
    read these fields WITHOUT the lock. That is safe only because every write is
    a whole-reference SWAP (``job.progress = dict(...)``, ``job.state = ...``,
    never an in-place ``job.progress[k] = v`` / ``job.result`` mutation), so a
    reader sees the old or new object atomically under CPython's GIL — never a
    torn one. The terminal ``result``/``error`` read is additionally ordered
    behind ``terminal_event.set()``. Keep it that way: never mutate ``progress``
    or ``result`` in place. (A free-threaded / no-GIL build would need an
    explicit per-read lock here.)

    The wire-facing state vocabulary is ``running | done | failed`` (NOT the
    on-disk ``status.json`` ``error`` legacy term — the render worker maps
    ``error -> failed`` when it lands the terminal record).
    """

    job_id: str
    kind: JobKind
    dir: str  # captures_dir (render) | report_dir (analyze), absolute
    state: JobState = "running"
    created_at: str = field(default_factory=_utc_now_iso)
    updated_at: str = field(default_factory=_utc_now_iso)
    eta_seconds: int | None = None
    expected_stop_beat: int | None = None  # render only
    progress: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] | None = None  # set on state == "done"
    error: str | None = None  # set on state == "failed"
    # Set when the job reaches a terminal state, so ``status`` can long-poll
    # (wait for completion) instead of busy-spinning. repr-excluded — it is
    # control machinery, not data.
    terminal_event: threading.Event = field(
        default_factory=threading.Event, repr=False
    )

    def wait_terminal(self, timeout: float) -> bool:
        """Block up to ``timeout`` s for the job to finish; True if terminal."""
        return self.terminal_event.wait(timeout=timeout)

    def start_result(self, poll_text: str) -> dict[str, Any]:
        """The immediate ``start`` payload: a small handle + poll instruction."""
        out: dict[str, Any] = {
            "job_id": self.job_id,
            "kind": self.kind,
            "state": self.state,
            "eta_seconds": self.eta_seconds,
            "poll": poll_text,
        }
        if self.kind == "render":
            out["captures_dir"] = self.dir
            if self.expected_stop_beat is not None:
                out["expected_stop_beat"] = self.expected_stop_beat
        else:
            out["report_dir"] = self.dir
        return out

    def status_result(self) -> dict[str, Any]:
        """The ``status`` payload: current state + progress, plus the terminal
        result (manifest/report) or error once finished."""
        out: dict[str, Any] = {
            "job_id": self.job_id,
            "kind": self.kind,
            "state": self.state,
            "progress": dict(self.progress),
        }
        if self.kind == "render":
            out["captures_dir"] = self.dir
        else:
            out["report_dir"] = self.dir
        if self.state == "done" and self.result is not None:
            if self.kind == "render":
                out["manifest"] = self.result.get("manifest")
                out["manifest_path"] = self.result.get("manifest_path")
                # 'ok' | 'incomplete' from the render itself (distinct from the
                # job state, which is 'done' once the render returns at all).
                out["render_status"] = self.result.get("status")
            else:
                out["report"] = self.result.get("report")
                out["report_path"] = self.result.get("report_path")
        if self.state == "failed" and self.error is not None:
            out["error"] = self.error
        return out


class JobRegistry:
    """Thread-safe map of ``job_id -> Job`` with insertion order retained.

    Order is kept so ``create_if_idle`` can find the most recent running job (the
    one-at-a-time busy guard) and ``recent_ids`` can name recent jobs in an
    unknown-job error.
    """

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._order: list[str] = []
        self._lock = threading.Lock()

    def _build_job(
        self,
        *,
        kind: JobKind,
        dir: str,
        eta_seconds: int | None,
        expected_stop_beat: int | None,
    ) -> Job:
        return Job(
            job_id=f"{kind}-{uuid4().hex[:12]}",
            kind=kind,
            dir=dir,
            eta_seconds=eta_seconds,
            expected_stop_beat=expected_stop_beat,
        )

    def create(
        self,
        *,
        kind: JobKind,
        dir: str,
        eta_seconds: int | None = None,
        expected_stop_beat: int | None = None,
    ) -> Job:
        job = self._build_job(
            kind=kind, dir=dir, eta_seconds=eta_seconds,
            expected_stop_beat=expected_stop_beat,
        )
        with self._lock:
            self._jobs[job.job_id] = job
            self._order.append(job.job_id)
        return job

    def create_if_idle(
        self,
        *,
        kind: JobKind,
        dir: str,
        eta_seconds: int | None = None,
        expected_stop_beat: int | None = None,
    ) -> "tuple[Job, bool]":
        """Atomic one-at-a-time-per-kind claim. Returns ``(job, created)``:

          - ``(existing, False)`` if an active (``running``) job of ``kind``
            already holds the slot — the caller returns a ``busy`` handle.
          - ``(new_job, True)`` otherwise — the slot is claimed under the lock.

        The check + insert happen under ONE lock acquisition, closing the
        ``active()``-then-``create()`` TOCTOU: with the async dispatch wrapper
        (server.py) two ``start`` calls can run on different threads
        concurrently, so a non-atomic check could let both pass and launch two
        workers. This is the start handlers' busy guard."""
        with self._lock:
            for job_id in reversed(self._order):
                existing = self._jobs[job_id]
                if existing.kind == kind and existing.state == "running":
                    return existing, False
            job = self._build_job(
                kind=kind, dir=dir, eta_seconds=eta_seconds,
                expected_stop_beat=expected_stop_beat,
            )
            self._jobs[job.job_id] = job
            self._order.append(job.job_id)
            return job, True

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def recent_ids(self, kind: JobKind | None = None, limit: int = 5) -> list[str]:
        with self._lock:
            ids = [
                job_id
                for job_id in reversed(self._order)
                if kind is None or self._jobs[job_id].kind == kind
            ]
        return ids[:limit]

    def update_progress(self, job_id: str, progress: dict[str, Any]) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job.progress = dict(progress)
            job.updated_at = _utc_now_iso()

    def mark_done(self, job_id: str, result: dict[str, Any]) -> None:
        self._finish(job_id, state="done", result=result, error=None)

    def mark_failed(self, job_id: str, error: str) -> None:
        self._finish(job_id, state="failed", result=None, error=error)

    def _finish(
        self,
        job_id: str,
        *,
        state: JobState,
        result: dict[str, Any] | None,
        error: str | None,
    ) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job.state = state
            job.result = result
            job.error = error
            job.updated_at = _utc_now_iso()
            job.terminal_event.set()


# Per-process singleton (see module docstring). Handlers default to this; tests
# inject their own instance via the handler ``_registry`` seam.
_REGISTRY = JobRegistry()


def default_registry() -> JobRegistry:
    return _REGISTRY


def spawn_daemon(fn: Callable[[], None], *, name: str) -> None:
    """Run ``fn`` on a detached daemon thread — the default worker spawn for
    async ``start`` actions.

    Detached + daemon so the worker outlives the originating ``start`` request
    (the job keeps advancing after ``start`` returns) yet never blocks process
    exit. Render's worker additionally marshals onto Live's main thread via
    ``run_on_main``, which is reachable from any thread and outlives the request
    (verify-api: mechanism A); analyze's worker is pure server-process DSP, so
    it needs no main-thread marshaling at all. ``name`` labels the thread for
    server-log postmortems.
    """
    threading.Thread(target=fn, name=name, daemon=True).start()


__all__ = [
    "Job",
    "JobRegistry",
    "JobKind",
    "JobState",
    "default_registry",
    "spawn_daemon",
    "DEFAULT_STATUS_LONG_POLL_S",
]
