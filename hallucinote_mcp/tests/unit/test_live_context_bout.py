"""``LiveLiveContext.run_on_main`` — the main-thread bout state machine.

``remote_script/dispatch.py`` is the Live-side ``LiveContext``: it marshals
every Live API call onto Live's main thread and blocks the calling worker
until it returns. Commit 979f03a turned that from a plain
schedule-and-wait into an ADMISSION-CONTROLLED state machine, because a
``run_on_main`` timeout does NOT cancel the work — Python cannot interrupt
a running Live API call. So an overrunning bout leaves the main thread
committed while every later caller queues silently behind it, and one slow
operation becomes an unresponsive DAW.

The machine is testable without Live because ``schedule_on_main`` is
injected: these tests substitute a scheduler that runs the callback inline
(the "Live's queue drained instantly" case) or one that never runs it at
all (the "Live is wedged" case). The invariants pinned here:

  I1  A bout returns the callable's result, and re-raises the callable's
      exception ON THE CALLING THREAD as the same object — nothing escapes
      into Live's main loop.
  I2  Bout bookkeeping (``_main_bout_label`` / ``_main_bout_started``) is
      set on entry and cleared on exit — with ONE stated exception: on the
      ESCALATION path it deliberately survives the caller's exit, because
      the work survives it too (I9).
  I3  Re-entrancy: the SAME thread may nest bouts (batch handlers call
      per-item helpers that also marshal). The nested call must not
      overwrite or clear the OUTER bout's identity.
  I4  Admission: a DIFFERENT thread arriving while a bout is in flight
      waits at most ``_BUSY_ADMIT_WAIT_S`` — long enough that two ordinary
      quick calls overlapping just works — and is then REFUSED with
      ``LiveBusyError`` rather than queued.
  I5  The refusal names the in-flight operation and how long it has been
      running, and refusing does not disturb the incumbent.
  I6  ``timeout=`` overrides the context-wide ceiling for THAT bout only;
      ``None`` falls back to the context default. The admission wait is a
      separate, fixed budget spent BEFORE the bout timer starts.
  I7  A bout that outruns its ceiling ESCALATES: it reports "still running,
      do not retry", hands back a job handle, and keeps the fence closed.
      It is a report that we stopped waiting, not that the work stopped.
  I8  ``dispatcher.dispatch`` translates ``LiveBusyError`` into a refusal
      response whose error text is the raw busy message (NOT reformatted
      by the broad executor-failure catch), translates
      ``LiveWorkEscalatedError`` into an ``ok=True`` handle, and labels
      each bout ``tool('action')`` with the action's
      ``main_thread_timeout``.
  I9  Occupancy outlives the waiter. After an escalation whose callback
      has not run, another thread is REFUSED — and admitted only once the
      runner actually signals. The runner then settles the job.
  I10 A never-signalling runner is visible (``bout_status``, and the
      ``main_thread_bout`` block on ``info``) and clearable only by an
      explicit ``abandon_bout`` — never by a timer.

Wall-clock discipline: the production admission wait is 2.0 s, which is far
too long to burn in a unit suite. Tests that must exercise the wait
monkeypatch the module constant down to milliseconds — and one test pins
that the constant is really the knob the code consumes, so shrinking it in
a test cannot hide a regression in the real value.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable

import pytest

from hallucinote_mcp import schema
from hallucinote_mcp.dispatcher import (
    LiveBusyError,
    LiveWorkEscalatedError,
    dispatch,
)
from hallucinote_mcp.handlers import session as session_handlers
from hallucinote_mcp.handlers.jobs import JobRegistry
from hallucinote_mcp.remote_script import dispatch as live_dispatch
from hallucinote_mcp.remote_script.dispatch import LiveLiveContext
from hallucinote_mcp.schema import Action, register
from hallucinote_mcp.testing import isolated_actions
from hallucinote_mcp.wire import WORK_ESCALATED_CODE, Request


_SONG = object()
_APPLICATION = object()

# Short enough to keep the whole module's added wall clock in the tens of
# milliseconds; the REAL constant is pinned by
# ``test_admission_wait_constant_is_two_seconds``.
_FAST_ADMIT = 0.05


def _inline(fn: Callable[[], None]) -> None:
    """Scheduler standing in for a Live main thread that drains instantly.

    Runs the marshaled callback synchronously on the caller's thread. That
    is the honest model of the common case: ``schedule_message(0, fn)``
    into an idle Live returns in milliseconds.
    """
    fn()


class _WedgedScheduler:
    """Scheduler standing in for a Live main thread that never gets around
    to us — the exact condition ``run_on_main``'s timeout exists to report.

    Records the callbacks so a test can prove they were scheduled (and are
    still pending) rather than dropped.
    """

    def __init__(self) -> None:
        self.pending: list[Callable[[], None]] = []
        self.wedged = True

    def unwedge(self) -> None:
        """Stop stalling NEW callbacks. Already-pending ones stay pending —
        Live cannot be made to un-run work it never got to."""
        self.wedged = False

    def __call__(self, fn: Callable[[], None]) -> None:
        if self.wedged:
            self.pending.append(fn)
            return
        fn()


def _ctx(
    schedule: Callable[[Callable[[], None]], None],
    *,
    main_thread_timeout: float = 15.0,
    job_registry: JobRegistry | None = None,
) -> LiveLiveContext:
    return LiveLiveContext(
        song_factory=lambda: _SONG,
        application_factory=lambda: _APPLICATION,
        schedule_on_main=schedule,
        main_thread_timeout=main_thread_timeout,
        job_registry=job_registry,
    )


class _Occupier:
    """Holds a real bout open on a separate thread until released.

    The occupying callable blocks INSIDE the bout, so the bout lock is held
    for real — this is the only way to exercise cross-thread admission
    without Live.
    """

    def __init__(self, ctx: LiveLiveContext, label: str = "a long device load"):
        self._ctx = ctx
        self._label = label
        self.entered = threading.Event()
        self.release = threading.Event()
        self.result: Any = None
        self.error: BaseException | None = None
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="bout-occupier")

    def _run(self) -> None:
        def _hold() -> str:
            self.entered.set()
            self.release.wait(timeout=5.0)
            return "incumbent-finished"

        try:
            self.result = self._ctx.run_on_main(_hold, label=self._label)
        except BaseException as exc:  # prawduct:allow prawduct/broad-except -- test harness must carry any thread-side error back to the assertion.
            self.error = exc

    def __enter__(self) -> "_Occupier":
        self._thread.start()
        assert self.entered.wait(timeout=5.0), "occupier never entered its bout"
        return self

    def __exit__(self, *_exc: object) -> None:
        self.release.set()
        self._thread.join(timeout=5.0)
        assert not self._thread.is_alive(), "occupier thread did not finish"


# ---------------------------------------------------------------------------
# I1 — result and exception transport
# ---------------------------------------------------------------------------


def test_bout_returns_the_callables_result():
    ctx = _ctx(_inline)
    assert ctx.run_on_main(lambda: 42, label="read tempo") == 42


def test_bout_returns_none_without_confusing_it_for_a_missing_result():
    """A callable returning ``None`` is a legitimate result, not an error —
    the runner boxes results under a key and reads with ``.get``."""
    ctx = _ctx(_inline)
    assert ctx.run_on_main(lambda: None, label="set tempo") is None


def test_bout_reraises_the_callables_exception_as_the_same_object():
    """The exception must surface on the WORKER thread, not be swallowed on
    Live's main loop, and must arrive intact so the dispatcher can classify
    it (a re-wrapped exception would lose the type the dispatcher keys on).
    """
    boom = ValueError("no such track")

    def _raise() -> None:
        raise boom

    ctx = _ctx(_inline)
    with pytest.raises(ValueError) as caught:
        ctx.run_on_main(_raise, label="track info")
    assert caught.value is boom


def test_bout_captures_base_exceptions_too():
    """The runner catches ``BaseException``, not ``Exception``. A
    ``KeyboardInterrupt``-class escape from a callback would go uncaught in
    Live's main loop, where there is nobody to handle it."""

    class _Abort(BaseException):
        pass

    def _raise() -> None:
        raise _Abort("engine stop")

    ctx = _ctx(_inline)
    with pytest.raises(_Abort):
        ctx.run_on_main(_raise, label="stop")


# ---------------------------------------------------------------------------
# I2 — bout bookkeeping is set on entry and cleared on every exit path
# ---------------------------------------------------------------------------


def test_bout_state_is_visible_during_the_bout_and_cleared_after():
    ctx = _ctx(_inline)
    seen: dict[str, Any] = {}

    def _peek() -> None:
        seen["label"] = ctx._main_bout_label
        seen["started"] = ctx._main_bout_started

    before = time.monotonic()
    ctx.run_on_main(_peek, label="ableton_device('load')")
    assert seen["label"] == "ableton_device('load')"
    assert seen["started"] is not None and seen["started"] >= before
    assert ctx._main_bout_label is None
    assert ctx._main_bout_started is None


def test_bout_state_is_cleared_when_the_callable_raises():
    ctx = _ctx(_inline)

    def _raise() -> None:
        raise RuntimeError("nope")

    with pytest.raises(RuntimeError):
        ctx.run_on_main(_raise, label="doomed")
    assert ctx._main_bout_label is None
    assert ctx._main_bout_started is None
    # And the context is reusable — the lock was released, not leaked.
    assert ctx.run_on_main(lambda: "ok", label="after") == "ok"


def test_unlabelled_bout_gets_a_placeholder_label():
    """``label`` is optional; the busy/timeout messages still need something
    to name, so an unlabelled bout is recorded as a generic Live call rather
    than as ``None`` (which would read as 'no bout in flight')."""
    ctx = _ctx(_inline)
    seen: dict[str, Any] = {}
    ctx.run_on_main(lambda: seen.update(label=ctx._main_bout_label))
    assert seen["label"] == "a Live API call"


# ---------------------------------------------------------------------------
# I3 — re-entrancy: nested bouts on the same thread
# ---------------------------------------------------------------------------


def test_nested_bout_on_the_same_thread_is_admitted():
    """Batch handlers (``cue_create_batch``) hold a bout and call per-item
    helpers that marshal too. The bout lock is an RLock precisely so this
    nests instead of self-deadlocking."""
    ctx = _ctx(_inline)

    def _outer() -> str:
        return ctx.run_on_main(lambda: "inner-result", label="inner")

    assert ctx.run_on_main(_outer, label="outer") == "inner-result"


def test_nested_bout_does_not_steal_the_outer_bouts_identity():
    """The OUTER bout owns the label and the start time: it is the thing a
    refused caller needs named, and the elapsed time that matters is the
    whole outer operation's, not the current innermost step's."""
    ctx = _ctx(_inline)
    seen: dict[str, Any] = {}

    def _outer() -> None:
        seen["outer_started"] = ctx._main_bout_started

        def _inner() -> None:
            seen["label_inside_inner"] = ctx._main_bout_label
            seen["started_inside_inner"] = ctx._main_bout_started

        ctx.run_on_main(_inner, label="inner")
        # Critically: the inner bout's exit must NOT clear the outer's state.
        seen["label_after_inner"] = ctx._main_bout_label
        seen["started_after_inner"] = ctx._main_bout_started

    ctx.run_on_main(_outer, label="outer")

    assert seen["label_inside_inner"] == "outer"
    assert seen["label_after_inner"] == "outer"
    assert seen["started_inside_inner"] == seen["outer_started"]
    assert seen["started_after_inner"] == seen["outer_started"]
    # Only the outermost exit tears the bout down.
    assert ctx._main_bout_label is None
    assert ctx._main_bout_started is None


def test_a_third_thread_is_refused_while_a_nested_bout_runs(monkeypatch):
    """Nesting must not open a hole in admission control: while thread A is
    inside a nested bout, thread B is still refused."""
    monkeypatch.setattr(live_dispatch, "_BUSY_ADMIT_WAIT_S", _FAST_ADMIT)
    ctx = _ctx(_inline)
    inside_nested = threading.Event()
    release = threading.Event()
    outcome: dict[str, Any] = {}

    def _hold() -> None:
        def _nested() -> None:
            inside_nested.set()
            release.wait(timeout=5.0)

        ctx.run_on_main(_nested, label="inner step")

    holder = threading.Thread(target=lambda: ctx.run_on_main(_hold, label="batch"),
                              daemon=True)
    holder.start()
    assert inside_nested.wait(timeout=5.0)
    try:
        with pytest.raises(LiveBusyError) as caught:
            ctx.run_on_main(lambda: "should not run", label="intruder")
        # The OUTER label is what the intruder is told about.
        assert "batch" in str(caught.value)
        outcome["refused"] = True
    finally:
        release.set()
        holder.join(timeout=5.0)
    assert outcome["refused"]
    assert not holder.is_alive()


# ---------------------------------------------------------------------------
# I4 / I5 — cross-thread admission
# ---------------------------------------------------------------------------


def test_admission_is_granted_when_the_incumbent_finishes_inside_the_wait(monkeypatch):
    """The bounded wait exists so two ordinary quick calls overlapping just
    works. A caller that arrives while a short bout is in flight must be
    ADMITTED once it drains, not refused."""
    monkeypatch.setattr(live_dispatch, "_BUSY_ADMIT_WAIT_S", 1.0)
    ctx = _ctx(_inline)

    with _Occupier(ctx, label="a quick read") as occupier:
        releaser = threading.Timer(0.02, occupier.release.set)
        releaser.start()
        started = time.monotonic()
        result = ctx.run_on_main(lambda: "admitted", label="second caller")
        elapsed = time.monotonic() - started
        releaser.cancel()

    assert result == "admitted"
    assert elapsed < 1.0, "caller should have been admitted as soon as the bout drained"
    assert occupier.error is None
    assert occupier.result == "incumbent-finished"


def test_admission_is_refused_with_livebusyerror_when_the_incumbent_overruns(monkeypatch):
    monkeypatch.setattr(live_dispatch, "_BUSY_ADMIT_WAIT_S", _FAST_ADMIT)
    ctx = _ctx(_inline)
    ran = []

    with _Occupier(ctx, label="ableton_device('load')"):
        with pytest.raises(LiveBusyError):
            ctx.run_on_main(lambda: ran.append("x"), label="second caller")

    # Refused means NEVER ATTEMPTED — the callable must not have been
    # scheduled at all. That is what makes the refusal safe to surface as
    # "nothing happened" rather than "unknown state".
    assert ran == []


def test_busy_message_names_the_in_flight_operation_and_its_elapsed_time(monkeypatch):
    """A refused caller has to learn WHAT Live is doing (so it can judge
    whether to wait) and be told not to retry — retrying deepens the queue
    behind work Live cannot cancel."""
    monkeypatch.setattr(live_dispatch, "_BUSY_ADMIT_WAIT_S", _FAST_ADMIT)
    ctx = _ctx(_inline)

    with _Occupier(ctx, label="ableton_device('load')"):
        with pytest.raises(LiveBusyError) as caught:
            ctx.run_on_main(lambda: None, label="second caller")

    message = str(caught.value)
    assert "ableton_device('load')" in message
    assert "running" in message and "s)" in message  # elapsed, e.g. "(running 0.1s)"
    assert "refused rather than" in message
    assert "cannot be cancelled" in message


def test_refusal_does_not_disturb_the_incumbent_or_the_next_caller(monkeypatch):
    monkeypatch.setattr(live_dispatch, "_BUSY_ADMIT_WAIT_S", _FAST_ADMIT)
    ctx = _ctx(_inline)

    with _Occupier(ctx, label="incumbent") as occupier:
        with pytest.raises(LiveBusyError):
            ctx.run_on_main(lambda: None, label="refused")

    assert occupier.error is None
    assert occupier.result == "incumbent-finished"
    assert ctx._main_bout_label is None
    # Once the incumbent is done the context admits normally again.
    assert ctx.run_on_main(lambda: "free", label="later") == "free"


def test_the_admission_wait_is_the_module_constant(monkeypatch):
    """Proves the constant is the knob actually consumed — otherwise every
    other test here could shrink it while production regressed to something
    that hangs the caller."""
    monkeypatch.setattr(live_dispatch, "_BUSY_ADMIT_WAIT_S", 0.2)
    ctx = _ctx(_inline)

    with _Occupier(ctx, label="incumbent"):
        started = time.monotonic()
        with pytest.raises(LiveBusyError):
            ctx.run_on_main(lambda: None, label="refused")
        elapsed = time.monotonic() - started

    assert 0.15 <= elapsed < 1.0, (
        f"refusal took {elapsed:.3f}s; the wait should track "
        f"_BUSY_ADMIT_WAIT_S (0.2s here), not a hard-coded value"
    )


def test_admission_wait_constant_is_two_seconds():
    """Pins the production value the other tests monkeypatch away.

    2.0 s is the documented balance: long enough that two ordinary quick
    calls overlapping just works (Live's queue drains in milliseconds),
    short enough that a caller stuck behind a genuinely long operation
    learns promptly instead of burning its own socket timeout.
    """
    assert live_dispatch._BUSY_ADMIT_WAIT_S == 2.0


# ---------------------------------------------------------------------------
# I6 / I7 — the ceiling: the per-bout override, and what overrunning means
# ---------------------------------------------------------------------------


def _drain(wedged: "_WedgedScheduler") -> None:
    """Let Live get around to the callbacks it has been sitting on."""
    wedged.unwedge()
    pending, wedged.pending = wedged.pending, []
    for fn in pending:
        fn()


def test_per_bout_timeout_override_is_honoured():
    """Some Live operations legitimately exceed a general-purpose ceiling
    (a Max for Live instantiation, a full parameter walk). The override is
    how those actions buy a wider window without widening it for everyone.
    """
    wedged = _WedgedScheduler()
    ctx = _ctx(wedged, main_thread_timeout=30.0, job_registry=JobRegistry())

    with pytest.raises(LiveWorkEscalatedError) as caught:
        ctx.run_on_main(lambda: None, timeout=0.05, label="ableton_device('load')")

    message = str(caught.value)
    assert caught.value.waited_s == 0.05
    assert "within 0.05s" in message, message
    assert "30" not in message, "the context default must not win over the override"
    assert len(wedged.pending) == 1, "the work was scheduled, just never run"


def test_bout_without_an_override_uses_the_context_default_timeout():
    wedged = _WedgedScheduler()
    ctx = _ctx(wedged, main_thread_timeout=0.05, job_registry=JobRegistry())

    with pytest.raises(LiveWorkEscalatedError) as caught:
        ctx.run_on_main(lambda: None, label="ableton_track('info')")

    assert "within 0.05s" in str(caught.value)


def test_overrun_says_the_work_is_still_running_and_not_to_retry():
    """The single most important thing this message does: a Live API call
    cannot be interrupted, so overrunning the ceiling means 'we stopped
    waiting', NOT 'the work stopped'. A caller that reads it as failure and
    retries queues more work behind an uncancellable operation."""
    ctx = _ctx(_WedgedScheduler(), main_thread_timeout=0.05,
               job_registry=JobRegistry())

    with pytest.raises(LiveWorkEscalatedError) as caught:
        ctx.run_on_main(lambda: None, label="ableton_device('load')")

    message = str(caught.value)
    assert "ableton_device('load')" in message
    assert "STILL RUNNING" in message
    assert "Do not retry immediately" in message


def test_overrun_names_the_bout_as_a_live_api_call_when_no_label_was_given():
    """An unlabelled bout still has to be nameable in the escalation — the
    caller is being handed a handle to *something* and has to be told what."""
    ctx = _ctx(_WedgedScheduler(), main_thread_timeout=0.05,
               job_registry=JobRegistry())
    with pytest.raises(LiveWorkEscalatedError) as caught:
        ctx.run_on_main(lambda: None)
    assert "a Live API call" in str(caught.value)
    assert caught.value.label == "a Live API call"


def test_the_overrun_hands_back_a_job_handle_not_a_failure():
    """R3. The work is neither done nor failed, so neither answer is true.
    A handle is the only honest one — and it must name a job that actually
    exists in the registry the poll surface reads."""
    registry = JobRegistry()
    ctx = _ctx(_WedgedScheduler(), main_thread_timeout=0.05,
               job_registry=registry)

    with pytest.raises(LiveWorkEscalatedError) as caught:
        ctx.run_on_main(lambda: None, label="ableton_device('load')")

    exc = caught.value
    job = registry.get(exc.job_id)
    assert job is not None, "the escalation named a job that does not exist"
    assert job.kind == "main_thread"
    assert job.state == "running"
    assert job.detail["label"] == "ableton_device('load')"
    assert exc.elapsed_s >= 0.05


# ---------------------------------------------------------------------------
# I9 — occupancy outlives the waiter (the fence #322/#324 exists for)
# ---------------------------------------------------------------------------


def test_an_escalated_bout_keeps_refusing_until_the_runner_signals(monkeypatch):
    """The invariant this whole state machine exists for.

    Formerly a KNOWN GAP: ``run_on_main`` released the bout in its
    ``finally``, which runs on the overrun path too — so the gate refused
    callers who arrived WHILE we waited and admitted callers who arrived
    AFTER we gave up, i.e. it was open exactly when a retry would stack more
    work behind the still-running op. Now the bout is held by the RUNNER, and
    only the runner's own completion opens it.
    """
    monkeypatch.setattr(live_dispatch, "_BUSY_ADMIT_WAIT_S", _FAST_ADMIT)
    registry = JobRegistry()
    wedged = _WedgedScheduler()
    ctx = _ctx(wedged, main_thread_timeout=0.05, job_registry=registry)

    with pytest.raises(LiveWorkEscalatedError) as caught:
        ctx.run_on_main(lambda: "landed late", label="ableton_device('load')")
    job_id = caught.value.job_id

    # Bookkeeping SURVIVES — the stated exception to I2 — because the work
    # survives too: the callback is still sitting unrun in Live's queue.
    assert ctx._main_bout_label == "ableton_device('load')"
    assert ctx._main_bout_started is not None
    assert len(wedged.pending) == 1, "the abandoned work is still pending"

    # A second thread is REFUSED, and told what it is behind.
    refused: dict[str, Any] = {}

    def _second_thread() -> None:
        try:
            ctx.run_on_main(lambda: "must not run", label="retry")
        except BaseException as exc:  # prawduct:allow prawduct/broad-except -- carry the thread-side outcome back to the assertion.
            refused["error"] = exc

    t = threading.Thread(target=_second_thread, daemon=True)
    t.start()
    t.join(timeout=5.0)
    assert isinstance(refused.get("error"), LiveBusyError), refused
    assert "ableton_device('load')" in str(refused["error"])
    assert job_id in str(refused["error"])

    # Live finally gets to it. Now — and only now — the gate opens and the
    # job reads terminal, carrying what the call actually returned.
    _drain(wedged)
    assert ctx._main_bout_label is None
    job = registry.get(job_id)
    assert job.state == "done"
    assert job.status_result()["result"] == "landed late"
    assert ctx.run_on_main(lambda: "admitted", label="after") == "admitted"


def test_an_escalated_bout_that_raises_settles_the_job_as_failed():
    """The runner settles the job on BOTH paths. A job left ``running``
    forever is the same lie as the timeout was, only quieter."""
    registry = JobRegistry()
    wedged = _WedgedScheduler()
    ctx = _ctx(wedged, main_thread_timeout=0.05, job_registry=registry)

    def _boom() -> None:
        raise RuntimeError("no such device")

    with pytest.raises(LiveWorkEscalatedError) as caught:
        ctx.run_on_main(_boom, label="ableton_device('load')")

    _drain(wedged)
    job = registry.get(caught.value.job_id)
    assert job.state == "failed"
    assert "no such device" in job.error
    assert ctx._main_bout_label is None


def test_a_thread_that_escalated_cannot_re_enter_its_own_abandoned_bout(monkeypatch):
    """R2's re-entrancy is for a LIVE bout on the calling thread. An
    abandoned one has no owner: the escalating thread returns to the
    connection pool, and thread idents are recycled, so inheriting re-entry
    rights into abandoned work would drive a later caller straight through
    the fence."""
    monkeypatch.setattr(live_dispatch, "_BUSY_ADMIT_WAIT_S", _FAST_ADMIT)
    ctx = _ctx(_WedgedScheduler(), main_thread_timeout=0.05,
               job_registry=JobRegistry())

    with pytest.raises(LiveWorkEscalatedError):
        ctx.run_on_main(lambda: None, label="ableton_device('load')")

    # Same thread, immediately after.
    with pytest.raises(LiveBusyError):
        ctx.run_on_main(lambda: None, label="same thread again")


def test_a_nested_bout_that_never_lands_keeps_the_fence_closed(monkeypatch):
    """The outer callback returning is not the same as Live being free. A
    batch handler whose inner step is still queued leaves the main thread
    committed, so the bout must not clear on the outer's completion."""
    monkeypatch.setattr(live_dispatch, "_BUSY_ADMIT_WAIT_S", _FAST_ADMIT)
    registry = JobRegistry()

    class _WedgeAfterFirst:
        """Runs the first callback inline; queues every later one."""

        def __init__(self) -> None:
            self.pending: list[Callable[[], None]] = []
            self.seen = 0

        def __call__(self, fn: Callable[[], None]) -> None:
            self.seen += 1
            if self.seen == 1:
                fn()
            else:
                self.pending.append(fn)

    sched = _WedgeAfterFirst()
    ctx = _ctx(sched, main_thread_timeout=0.05, job_registry=registry)

    def _outer() -> None:
        ctx.run_on_main(lambda: None, label="inner step")

    with pytest.raises(LiveWorkEscalatedError):
        ctx.run_on_main(_outer, label="batch")

    # The outer callback has returned; the inner one has not. Still fenced.
    assert len(sched.pending) == 1
    assert ctx._main_bout_label == "batch"
    with pytest.raises(LiveBusyError):
        ctx.run_on_main(lambda: None, label="intruder")

    for fn in sched.pending:
        fn()
    assert ctx._main_bout_label is None


def test_a_callback_that_lands_in_the_escalation_race_window_is_not_escalated():
    """The wait can expire microseconds before the runner signals. Escalating
    then would hand back a handle to work that is already done AND leave the
    result unreported — so the escalation re-checks under the condition."""
    registry = JobRegistry()
    box: dict[str, Any] = {}

    class _LateButInTime:
        """Signals the callback only once the waiter has given up."""

        def __call__(self, fn: Callable[[], None]) -> None:
            box["fn"] = fn

    sched = _LateButInTime()
    ctx = _ctx(sched, main_thread_timeout=0.02, job_registry=registry)

    # Run the callback from a timer so it lands after the ceiling passes but
    # before the escalation acquires the condition is not deterministic —
    # instead, drive the sequence by hand: schedule, let the wait expire, run.
    original_wait = threading.Event.wait

    def _wait_then_land(self, timeout=None):  # type: ignore[no-untyped-def]
        landed = original_wait(self, timeout)
        if not landed and "fn" in box:
            box.pop("fn")()  # Live gets to it in the race window
        return original_wait(self, 0)

    threading.Event.wait = _wait_then_land  # type: ignore[method-assign]
    try:
        assert ctx.run_on_main(lambda: "just in time", label="x") == "just in time"
    finally:
        threading.Event.wait = original_wait  # type: ignore[method-assign]

    assert registry.recent_ids(kind="main_thread") == [], (
        "a callback that landed in the race window must NOT be escalated"
    )
    assert ctx._main_bout_label is None


def test_a_schedule_that_never_happens_does_not_fence_live_forever():
    """The one leak with no operator-visible cause, and the exact inverse of
    the defect this machine fixes. The RUNNER clears the bout — so a callback
    Live refused to accept would hold the fence forever with nothing to poll
    and nothing to abandon. The schedule failure releases and re-raises."""
    def _refuse(_fn: Callable[[], None]) -> None:
        raise RuntimeError("Live refused the schedule")

    ctx = _ctx(_refuse, job_registry=JobRegistry())
    with pytest.raises(RuntimeError, match="refused the schedule"):
        ctx.run_on_main(lambda: None, label="doomed")

    assert ctx._main_bout_label is None
    assert ctx.main_thread_bout() is None
    # And the context still works.
    ctx2 = _ctx(_inline)
    assert ctx2.run_on_main(lambda: "ok") == "ok"


# ---------------------------------------------------------------------------
# I10 — visibility and the explicit escape hatch (R7 / R8)
# ---------------------------------------------------------------------------


def test_bout_status_reads_the_occupied_bout_and_its_job():
    registry = JobRegistry()
    wedged = _WedgedScheduler()
    ctx = _ctx(wedged, main_thread_timeout=0.05, job_registry=registry)

    with pytest.raises(LiveWorkEscalatedError) as caught:
        ctx.run_on_main(lambda: None, label="ableton_device('load')")
    job_id = caught.value.job_id

    out = session_handlers.bout_status_handler(
        ctx, job_id=job_id, _registry=registry,
    )
    assert out["occupied"] is True
    assert out["main_thread_bout"]["label"] == "ableton_device('load')"
    assert out["main_thread_bout"]["job_id"] == job_id
    assert out["job"]["state"] == "running"
    assert out["job"]["kind"] == "main_thread"


def test_bout_status_without_a_job_id_answers_what_live_is_busy_with():
    """The read a caller has when it was REFUSED rather than escalated — it
    never received a handle, so the occupancy must be readable without one."""
    ctx = _ctx(_WedgedScheduler(), main_thread_timeout=0.05,
               job_registry=JobRegistry())
    assert session_handlers.bout_status_handler(ctx)["occupied"] is False

    with pytest.raises(LiveWorkEscalatedError):
        ctx.run_on_main(lambda: None, label="ableton_device('load')")

    out = session_handlers.bout_status_handler(ctx)
    assert out["occupied"] is True
    assert out["main_thread_bout"]["label"] == "ableton_device('load')"
    assert "job" not in out


def test_bout_status_teaches_on_an_unknown_job_id():
    registry = JobRegistry()
    ctx = _ctx(_inline, job_registry=registry)
    with pytest.raises(ValueError) as caught:
        session_handlers.bout_status_handler(
            ctx, job_id="main_thread-nope", _registry=registry,
        )
    assert "no main-thread work has been escalated" in str(caught.value)


def test_session_info_carries_the_bout_block_while_one_is_occupied():
    """R8. ``info`` is main-thread-wrapped, so it normally only ever runs
    when Live is free — the block is how a caller INSIDE a bout (a nested
    read) still sees what is holding the thread."""
    ctx = _ctx(_inline)
    seen: dict[str, Any] = {}

    def _read_info() -> None:
        seen["snapshot"] = session_handlers.info_handler(_FakeSongContext(ctx))

    ctx.run_on_main(_read_info, label="ableton_device('load')")
    block = seen["snapshot"]["main_thread_bout"]
    assert block["label"] == "ableton_device('load')"
    assert block["elapsed_s"] >= 0.0
    assert block["job_id"] is None  # not escalated — just occupied


def test_session_info_omits_the_bout_block_when_live_is_free():
    ctx = _ctx(_inline)
    assert "main_thread_bout" not in session_handlers.info_handler(
        _FakeSongContext(ctx)
    )


def test_abandon_bout_clears_occupancy_and_fails_the_job():
    """R7. The explicit escape hatch, and the reason there is no timer: a
    clear happens because an operator asked for it, having been told the work
    may still be running."""
    registry = JobRegistry()
    wedged = _WedgedScheduler()
    ctx = _ctx(wedged, main_thread_timeout=0.05, job_registry=registry)

    with pytest.raises(LiveWorkEscalatedError) as caught:
        ctx.run_on_main(lambda: None, label="ableton_device('load')")
    job_id = caught.value.job_id

    out = session_handlers.abandon_bout_handler(ctx, job_id=job_id)
    assert out["abandoned"] is True
    assert out["label"] == "ableton_device('load')"
    assert "MAY STILL BE RUNNING" in out["warning"]

    assert ctx._main_bout_label is None
    assert registry.get(job_id).state == "failed"
    assert "may still be running" in registry.get(job_id).error
    # The gate is open again — Live, having recovered, serves the next call.
    wedged.unwedge()
    assert ctx.run_on_main(lambda: "ok", label="after", timeout=1.0) == "ok"


def test_abandon_bout_refuses_a_job_id_that_is_not_the_one_holding_the_gate():
    registry = JobRegistry()
    ctx = _ctx(_WedgedScheduler(), main_thread_timeout=0.05,
               job_registry=registry)
    with pytest.raises(LiveWorkEscalatedError):
        ctx.run_on_main(lambda: None, label="ableton_device('load')")

    with pytest.raises(ValueError) as caught:
        session_handlers.abandon_bout_handler(ctx, job_id="main_thread-stale")
    assert "does not name the bout" in str(caught.value)
    # And the real bout is undisturbed.
    assert ctx._main_bout_label == "ableton_device('load')"


def test_abandon_bout_refuses_when_nothing_is_occupied():
    ctx = _ctx(_inline, job_registry=JobRegistry())
    with pytest.raises(ValueError) as caught:
        session_handlers.abandon_bout_handler(ctx, job_id="main_thread-x")
    assert "no main-thread bout is occupied" in str(caught.value)


def test_there_is_no_timed_auto_clear_of_a_stuck_bout(monkeypatch):
    """R8's bright line, pinned as behaviour rather than as a comment: an
    escalated bout that nobody abandons is STILL occupied later. A timed
    clear would re-create the very defect this item fixes, on a delay."""
    monkeypatch.setattr(live_dispatch, "_BUSY_ADMIT_WAIT_S", _FAST_ADMIT)
    ctx = _ctx(_WedgedScheduler(), main_thread_timeout=0.02,
               job_registry=JobRegistry())
    with pytest.raises(LiveWorkEscalatedError):
        ctx.run_on_main(lambda: None, label="ableton_device('load')")

    started = ctx._main_bout_started
    time.sleep(0.15)  # many times the ceiling that was overrun
    assert ctx._main_bout_label == "ableton_device('load')"
    assert ctx._main_bout_started == started
    with pytest.raises(LiveBusyError):
        ctx.run_on_main(lambda: None, label="later")


class _FakeSongContext:
    """A minimal ``info``-shaped context that delegates bout reads to a real
    ``LiveLiveContext``. ``info_handler`` wants a Song; the bout block is the
    only thing under test here."""

    def __init__(self, inner: LiveLiveContext) -> None:
        self._inner = inner

    @property
    def song(self) -> Any:
        return _FakeSong()

    @property
    def application(self) -> Any:
        raise AttributeError("no application in this double")

    def main_thread_bout(self) -> Any:
        return self._inner.main_thread_bout()


class _FakeParam:
    value = 0.0


class _FakeMixer:
    volume = _FakeParam()
    panning = _FakeParam()


class _FakeMaster:
    mixer_device = _FakeMixer()


class _FakeSong:
    tempo = 120.0
    signature_numerator = 4
    signature_denominator = 4
    is_playing = False
    current_song_time = 0.0
    loop = False
    loop_start = 0.0
    loop_length = 4.0
    tracks: tuple[Any, ...] = ()
    return_tracks: tuple[Any, ...] = ()
    scenes: tuple[Any, ...] = ()
    master_track = _FakeMaster()


# ---------------------------------------------------------------------------
# I8 — dispatcher translation of LiveBusyError
# ---------------------------------------------------------------------------


_BUSY_TOOL = "ableton_session"
_BUSY_ACTION = "_bout_probe"


def _register_probe(**action_kwargs: Any) -> list[dict[str, Any]]:
    """Register a throwaway action whose handler records what it saw.

    Returns the (mutable) list the handler appends to.
    """
    seen: list[dict[str, Any]] = []

    def _handler(context: Any) -> dict[str, Any]:
        seen.append({"bout_label": context._main_bout_label})
        return {"ran": True}

    register(
        Action(
            tool=_BUSY_TOOL,
            name=_BUSY_ACTION,
            description="test-only probe action",
            handler=_handler,
            example=f"{_BUSY_TOOL}(action='{_BUSY_ACTION}')",
            **action_kwargs,
        )
    )
    return seen


def test_dispatch_translates_livebusyerror_into_a_refusal_not_a_failure(monkeypatch):
    """The wire contract for a refusal.

    ``LiveBusyError`` is caught AHEAD of the broad executor-failure catch,
    so the error text is the raw busy message — not
    ``"tool('action') failed: LiveBusyError: ..."``. That ordering is the
    whole point: nothing is broken, the work was never attempted, and the
    agent must not read it as "this action is broken".
    """
    monkeypatch.setattr(live_dispatch, "_BUSY_ADMIT_WAIT_S", _FAST_ADMIT)
    ctx = _ctx(_inline)

    with isolated_actions():
        seen = _register_probe()
        with _Occupier(ctx, label="ableton_device('load')"):
            response = dispatch(
                Request(tool=_BUSY_TOOL, action=_BUSY_ACTION, params={}),
                context=ctx,
            )

    assert response.ok is False
    assert response.error.startswith("Live's main thread is busy with"), response.error
    assert "failed:" not in response.error, (
        "the broad executor-failure catch reformatted the refusal — the "
        "LiveBusyError branch must stay ahead of it"
    )
    assert "ableton_device('load')" in response.error
    assert response.hint is not None
    assert "Wait for the in-flight operation" in response.hint
    assert "unresponsive Live" in response.hint
    # Refused means never attempted.
    assert seen == []
    # A refusal is not a schema problem — no help menu is attached.
    assert response.valid_actions is None


def test_dispatch_labels_the_bout_with_tool_and_action():
    """The refusal message is only useful if the label identifies the call.
    The dispatcher supplies ``tool('action')``; a refused caller reads that
    label out of the incumbent's bout."""
    ctx = _ctx(_inline)
    with isolated_actions():
        seen = _register_probe()
        response = dispatch(
            Request(tool=_BUSY_TOOL, action=_BUSY_ACTION, params={}),
            context=ctx,
        )
    assert response.ok is True, response.error
    assert seen == [{"bout_label": f"{_BUSY_TOOL}('{_BUSY_ACTION}')"}]


def test_dispatch_passes_the_actions_main_thread_timeout_into_the_bout():
    """``Action.main_thread_timeout`` is the per-action ceiling; the
    dispatcher must hand it to ``run_on_main`` as the per-bout override or
    the wide ceilings (device load, parameter walks) silently do nothing.

    Read off the escalation the overrun produces: ``waited_s`` is the ceiling
    that was actually applied."""
    wedged = _WedgedScheduler()
    ctx = _ctx(wedged, main_thread_timeout=30.0, job_registry=JobRegistry())
    with isolated_actions():
        _register_probe(main_thread_timeout=0.05)
        response = dispatch(
            Request(tool=_BUSY_TOOL, action=_BUSY_ACTION, params={}),
            context=ctx,
        )
    assert response.result["waited_s"] == 0.05, response.result
    assert response.result["elapsed_s"] < 30.0


def test_dispatch_translates_an_overrun_into_a_handle_not_an_error():
    """R4. The bout outran its ceiling and Live is still running it — so the
    reply is ``ok=True`` with the ``work_escalated`` discriminator and a poll
    instruction, NOT the broad executor-failure error. An error here would be
    a lie the agent responds to by retrying, which is what deepens the queue
    behind work Live cannot cancel."""
    registry = JobRegistry()
    ctx = _ctx(_WedgedScheduler(), main_thread_timeout=0.05,
               job_registry=registry)
    with isolated_actions():
        _register_probe(main_thread_timeout=0.05)
        response = dispatch(
            Request(tool=_BUSY_TOOL, action=_BUSY_ACTION, params={}),
            context=ctx,
        )

    assert response.ok is True
    assert response.error is None
    assert response.code == WORK_ESCALATED_CODE
    result = response.result
    assert result["escalated"] is True
    assert result["label"] == f"{_BUSY_TOOL}('{_BUSY_ACTION}')"
    assert registry.get(result["job_id"]) is not None
    assert "bout_status" in result["poll"]
    assert "abandon_bout" in result["poll"]
    assert "cancelled" in result["poll"]
    # The discriminator has to survive serialization on the OK path, or a
    # consumer reads a handle to unfinished work as a completed operation.
    assert response.to_dict()["code"] == WORK_ESCALATED_CODE


def test_livebusyerror_is_importable_from_both_sides():
    """The Live-side module re-exports the dispatcher's ``LiveBusyError`` so
    the two ends raise and catch the SAME class. Two independently-defined
    classes would make the dispatcher's ``except`` branch dead code."""
    assert live_dispatch.LiveBusyError is LiveBusyError
    assert issubclass(LiveBusyError, RuntimeError)


def test_schema_registry_is_unpolluted_by_the_probe_action():
    """Guard for the isolated_actions usage above — a leaked test action
    would corrupt every later schema-shape assertion in the suite."""
    assert schema.get(_BUSY_TOOL, _BUSY_ACTION) is None
