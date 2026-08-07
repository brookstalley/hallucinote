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
      set on entry and cleared on exit, on every path.
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
  I7  A bout timeout reports "still running, do not retry" — it is a
      report that we stopped waiting, not that the work stopped.
  I8  ``dispatcher.dispatch`` translates ``LiveBusyError`` into a refusal
      response whose error text is the raw busy message (NOT reformatted
      by the broad executor-failure catch), and labels each bout
      ``tool('action')`` with the action's ``main_thread_timeout``.

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
from hallucinote_mcp.dispatcher import LiveBusyError, dispatch
from hallucinote_mcp.remote_script import dispatch as live_dispatch
from hallucinote_mcp.remote_script.dispatch import LiveLiveContext
from hallucinote_mcp.schema import Action, register
from hallucinote_mcp.testing import isolated_actions
from hallucinote_mcp.wire import Request


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
) -> LiveLiveContext:
    return LiveLiveContext(
        song_factory=lambda: _SONG,
        application_factory=lambda: _APPLICATION,
        schedule_on_main=schedule,
        main_thread_timeout=main_thread_timeout,
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
        except BaseException as exc:  # prawduct:ok-broad-except — test harness must carry any thread-side error back to the assertion
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
# I6 / I7 — bout timeout: the per-bout override, and what a timeout means
# ---------------------------------------------------------------------------


def test_per_bout_timeout_override_is_honoured():
    """Some Live operations legitimately exceed a general-purpose ceiling
    (a Max for Live instantiation, a full parameter walk). The override is
    how those actions buy a wider window without widening it for everyone.
    """
    wedged = _WedgedScheduler()
    ctx = _ctx(wedged, main_thread_timeout=30.0)

    with pytest.raises(TimeoutError) as caught:
        ctx.run_on_main(lambda: None, timeout=0.05, label="ableton_device('load')")

    message = str(caught.value)
    assert "within 0.05s" in message, message
    assert "30" not in message, "the context default must not win over the override"
    assert len(wedged.pending) == 1, "the work was scheduled, just never run"


def test_bout_without_an_override_uses_the_context_default_timeout():
    wedged = _WedgedScheduler()
    ctx = _ctx(wedged, main_thread_timeout=0.05)

    with pytest.raises(TimeoutError) as caught:
        ctx.run_on_main(lambda: None, label="ableton_track('info')")

    assert "within 0.05s" in str(caught.value)


def test_timeout_says_the_work_is_still_running_and_not_to_retry():
    """The single most important thing this message does: a Live API call
    cannot be interrupted, so a timeout means 'we stopped waiting', NOT
    'the work stopped'. A caller that reads it as failure and retries
    queues more work behind an uncancellable operation."""
    ctx = _ctx(_WedgedScheduler(), main_thread_timeout=0.05)

    with pytest.raises(TimeoutError) as caught:
        ctx.run_on_main(lambda: None, label="ableton_device('load')")

    message = str(caught.value)
    assert "ableton_device('load')" in message
    assert "STILL RUNNING" in message
    assert "Do not retry immediately" in message


def test_timeout_names_the_bout_as_unnamed_when_no_label_was_given():
    ctx = _ctx(_WedgedScheduler(), main_thread_timeout=0.05)
    with pytest.raises(TimeoutError) as caught:
        ctx.run_on_main(lambda: None)
    assert "(unnamed)" in str(caught.value)


def test_a_timed_out_bout_releases_admission_although_the_work_is_still_pending():
    """KNOWN GAP, pinned deliberately so a future fix is a conscious change.

    ``run_on_main`` releases the bout lock in its ``finally`` — including on
    the timeout path. So the admission control refuses callers that arrive
    WHILE we are waiting, but not callers that arrive AFTER we gave up,
    even though Live's main thread is still committed to the uncancellable
    work. The retry the timeout message warns against is therefore not
    actually blocked by the machine; only the message discourages it.

    Closing the gap needs a bout that stays "occupied" until the runner
    signals completion (a Condition-based state machine — an RLock cannot
    be released by a thread that does not own it), which is a design change
    beyond the state machine as it stands.
    """
    wedged = _WedgedScheduler()
    ctx = _ctx(wedged, main_thread_timeout=0.05)

    with pytest.raises(TimeoutError):
        ctx.run_on_main(lambda: None, label="ableton_device('load')")

    # Bookkeeping cleared and admission free again, while the first bout's
    # callback is still sitting unrun in Live's queue.
    assert ctx._main_bout_label is None
    assert ctx._main_bout_started is None
    assert len(wedged.pending) == 1, "the abandoned work is still pending"

    # Live "unblocks" enough to run new work — the abandoned callback is
    # still ahead of it in reality, but nothing here refuses the retry.
    wedged.unwedge()
    assert ctx.run_on_main(lambda: "admitted anyway", label="retry") == "admitted anyway"


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
    the wide ceilings (device load, parameter walks) silently do nothing."""
    wedged = _WedgedScheduler()
    ctx = _ctx(wedged, main_thread_timeout=30.0)
    with isolated_actions():
        _register_probe(main_thread_timeout=0.05)
        response = dispatch(
            Request(tool=_BUSY_TOOL, action=_BUSY_ACTION, params={}),
            context=ctx,
        )
    assert response.ok is False
    assert "within 0.05s" in response.error, response.error
    assert "TimeoutError" in response.error


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
