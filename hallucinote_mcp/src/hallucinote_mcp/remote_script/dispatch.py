"""Live-side LiveContext — bridges the dispatcher's ``LiveContext`` Protocol
to the concrete Live API.

The dispatcher wraps each action execution in ``context.run_on_main(fn)``,
which is responsible for:

  1. Scheduling ``fn`` onto Live's main thread (the only thread allowed to
     touch ``Live.Song.*``).
  2. Blocking the calling worker thread until the main-thread call returns.
  3. Returning the result, or re-raising any exception ``fn`` raised.
  4. Fencing Live's main thread while that work is outstanding — including
     after the caller has stopped waiting for it.

``LiveLiveContext.run_on_main`` does that via the ``_Framework`` primitive
``schedule_message``. ``LiveLiveContext.song`` returns the current Song
object and is meant to be read from inside the marshaled callback.

**Why the occupancy record outlives the waiter.** A timeout on ``run_on_main``
is not a cancellation: Python cannot interrupt a running Live API call. The
scheduled callback is still sitting on Live's main thread when we give up on
it. If the admission gate were released at that moment, it would refuse
callers who arrive *while* we wait and admit callers who arrive *after* we
stop — open exactly when a retry would stack more work behind an operation
Live cannot abandon. So the bout is held by the RUNNER, not by the waiter:
only the callback's own completion clears it. That is why the state machine
is a ``threading.Condition`` over an explicit ``_Bout`` record rather than a
held lock — an ``RLock`` cannot be released by a thread that does not own it,
and the only party that knows the work finished is the runner on Live's main
thread.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable

from ..handlers.jobs import Job, JobRegistry, default_registry


SongFactory = Callable[[], Any]
ApplicationFactory = Callable[[], Any]
ScheduleOnMain = Callable[[Callable[[], None]], None]

_BUSY_ADMIT_WAIT_S = 2.0
"""How long a new caller waits for an in-flight main-thread bout before being
refused.

Long enough that two ordinary quick calls overlapping just works (Live's queue
drains in milliseconds), short enough that a caller blocked behind a genuinely
long operation learns so promptly instead of burning its own socket timeout."""


# Raised by `run_on_main`; defined beside the LiveContext Protocol so the
# dispatcher can translate them without importing this Live-only module.
from ..dispatcher import (  # noqa: E402  (re-exported for callers)
    LiveBusyError,
    LiveWorkEscalatedError,
)


class _Bout:
    """One occupancy of Live's main thread.

    Installed by the outermost ``run_on_main`` on a thread and cleared by the
    LAST runner scheduled inside it — not by the waiter. ``outstanding``
    counts runners that have been scheduled and have not yet signalled, so a
    nested bout whose inner callback never lands keeps the fence closed even
    after the outer callback returns.

    ``owner_ident`` is the thread that may re-enter without installing a new
    bout (R2 — batch handlers nest). It is set to ``None`` the moment the bout
    is abandoned, which both states the fact ("no live waiter owns this") and
    closes a hazard: thread idents are recycled after a thread exits, so a
    later connection thread could otherwise inherit an abandoned bout's
    ownership and be admitted straight through the fence.
    """

    __slots__ = (
        "label", "started", "owner_ident", "outstanding",
        "job_id", "abandoned", "settle",
    )

    def __init__(self, label: str, started: float, owner_ident: int) -> None:
        self.label = label
        self.started = started
        self.owner_ident: int | None = owner_ident
        self.outstanding = 0
        self.job_id: str | None = None
        self.abandoned = False
        # Set when the bout is escalated: reads the escalating call's result
        # box at release time so the job settles with what the work actually
        # returned, not with whatever the last nested step produced.
        self.settle: Callable[[], None] | None = None

    def elapsed(self) -> float:
        return time.monotonic() - self.started


class LiveLiveContext:
    """LiveContext implementation backed by the real Live API.

    Parameters:
      song_factory: zero-arg callable returning the current Live Song object
        (Ableton's ``ControlSurface.song()`` is the canonical source).
      application_factory: zero-arg callable returning Live's Application
        object. Real ``ControlSurface`` exposes ``self.application`` which
        is exactly this shape. The Live ``Song`` does NOT expose
        ``get_application``, so we flow Application access through the
        context Protocol instead of having handlers ``import Live`` directly.
      schedule_on_main: callable that takes a zero-arg function and arranges
        for Live to invoke it on the main thread. The conventional shape in
        ``_Framework`` is ``lambda fn: control_surface.schedule_message(0, fn)``.
      main_thread_timeout: how long worker threads will wait for the main
        thread to complete an operation before ESCALATING (see
        ``run_on_main``). Live's main-thread queue should drain in
        milliseconds; 15s is a generous ceiling that surfaces a stalled engine
        without hanging the MCP forever.
      job_registry: where an escalated bout is registered so the caller can
        poll it. Defaults to the per-process singleton — the same registry
        ``ableton_session(action='bout_status')`` reads, because both run in
        the Remote Script process.
    """

    def __init__(
        self,
        song_factory: SongFactory,
        application_factory: ApplicationFactory,
        schedule_on_main: ScheduleOnMain,
        main_thread_timeout: float = 15.0,
        job_registry: JobRegistry | None = None,
    ):
        self._song_factory = song_factory
        self._application_factory = application_factory
        self._schedule_on_main = schedule_on_main
        self._main_thread_timeout = main_thread_timeout
        self._job_registry = job_registry
        # Re-entrant so batch handlers (e.g. cue_create_batch) can acquire
        # it once and call into per-item helpers that also acquire.
        self._live_state_lock = threading.RLock()
        # Admission control for Live's main thread.
        #
        # A timeout on `run_on_main` does NOT cancel the work — Python cannot
        # interrupt a running Live API call. So when a bout overruns, the main
        # thread is still committed, and a caller's natural next move (retry,
        # or simply the next call) would schedule MORE work behind the running
        # op. The TCP server spawns a thread per connection with no admission
        # control, so nothing else throttles that pile-up: one slow operation
        # becomes an unresponsive Live.
        #
        # A DIFFERENT thread arriving while a bout is in flight waits a bounded
        # moment and is then refused with `LiveBusyError` instead of silently
        # queueing behind it; the SAME thread re-enters without installing a
        # new bout, so batch handlers still nest.
        self._bout_cv = threading.Condition()
        self._bout: _Bout | None = None

    # -- bout bookkeeping ---------------------------------------------------
    #
    # ``_main_bout_label`` / ``_main_bout_started`` are the names the busy and
    # escalation messages read, and they are derived from the record rather
    # than tracked alongside it so the two can never disagree.
    #
    # INVARIANT: bout bookkeeping is set on entry and cleared on exit — with
    # ONE stated exception. On the escalation path it deliberately SURVIVES
    # the caller's exit, because the work survives it too. The bout is cleared
    # by the runner when Live finally gets to it, or by an operator's
    # ``ableton_session(action='abandon_bout')``, and by nothing else. There
    # is no timed auto-clear: a clear on a timer would re-create exactly the
    # defect this machine exists to prevent, only on a delay.

    @property
    def _main_bout_label(self) -> str | None:
        bout = self._bout
        return bout.label if bout is not None else None

    @property
    def _main_bout_started(self) -> float | None:
        bout = self._bout
        return bout.started if bout is not None else None

    @property
    def song(self) -> Any:
        """The current Live Song object.

        Intended to be called from inside ``run_on_main`` callbacks. We don't
        enforce that — calling it outside the main thread is safe as long as
        the song object is only *read*; mutations require main-thread access,
        which the dispatcher arranges.
        """
        return self._song_factory()

    @property
    def application(self) -> Any:
        """Live's Application object.

        Used for view-state reads/writes and browser access. Same main-thread
        discipline as ``song`` — call from inside ``run_on_main`` callbacks.
        """
        return self._application_factory()

    @property
    def live_state_lock(self) -> threading.RLock:
        """Mutex serializing handlers that write ``Song.current_song_time``.

        Acquired by ``cue_create`` / ``cue_create_batch`` / ``cue_delete``
        / ``cue_jump`` / ``seek``. The ~400ms seek+settle+toggle+settle
        window in cue ops would otherwise let parallel callers' playhead
        writes overwrite each other before the audio thread picks them
        up; empirically observed as "each handler reads the previous
        handler's target" (B-21 in bug-triage). The lock is also a
        forward guard for any future handler that writes transport
        state.
        """
        return self._live_state_lock

    # -- occupancy introspection / escape hatch -----------------------------

    def main_thread_bout(self) -> dict[str, Any] | None:
        """What Live's main thread is occupied with, or ``None`` if idle.

        The visibility half of "no automatic recovery": a runner that never
        signals leaves a bout standing forever, so it must be *readable*
        rather than quietly forgiven. Surfaced on
        ``ableton_session(action='info')`` and as its own ``bout_status``
        action.
        """
        with self._bout_cv:
            bout = self._bout
            if bout is None:
                return None
            return {
                "label": bout.label,
                "elapsed_s": round(bout.elapsed(), 3),
                "job_id": bout.job_id,
                "escalated": bout.abandoned,
            }

    def abandon_main_thread_bout(self, job_id: str) -> dict[str, Any]:
        """Force-release the admission gate held by an escalated bout.

        The explicit operator escape from a never-signalling runner — the
        alternative to a timed auto-clear, which would put us back where we
        started. Clearing occupancy does NOT stop the work: Live may still be
        executing it, and anything admitted afterwards queues behind it. The
        returned warning says so, and the job is marked ``failed`` because
        nothing will ever settle it now.

        Raises ``ValueError`` (translated by the dispatcher into a teaching
        error) when no bout is occupied or ``job_id`` names a different one —
        releasing the fence for a bout you are not looking at is how you
        release the wrong one.
        """
        with self._bout_cv:
            bout = self._bout
            if bout is None:
                raise ValueError(
                    f"abandon_bout: no main-thread bout is occupied, so there "
                    f"is nothing to abandon (job_id={job_id!r}). Live's main "
                    f"thread is free."
                )
            if bout.job_id != job_id:
                raise ValueError(
                    f"abandon_bout: job_id {job_id!r} does not name the bout "
                    f"currently occupying Live's main thread "
                    f"({bout.label!r}, job_id={bout.job_id!r}). Read "
                    f"ableton_session(action='bout_status') first — "
                    f"abandoning by a stale id would release the fence for an "
                    f"operation you are not looking at."
                )
            label = bout.label
            elapsed = bout.elapsed()
            bout.owner_ident = None
            bout.abandoned = True
            bout.settle = None
            self._bout = None
            self._bout_cv.notify_all()
        self._registry().mark_failed(
            job_id,
            f"abandoned by operator after {elapsed:.1f}s; Live may still be "
            f"running {label}",
        )
        return {
            "abandoned": True,
            "job_id": job_id,
            "label": label,
            "elapsed_s": round(elapsed, 3),
            "warning": (
                f"The admission gate is released, but {label} MAY STILL BE "
                f"RUNNING on Live's main thread — a Live API call cannot be "
                f"cancelled. Anything you send now queues behind it. Abandon "
                f"is for a runner you believe will never signal (Live "
                f"restarted, engine wedged); if Live is merely slow, waiting "
                f"is strictly better."
            ),
        }

    # -- the bout itself ----------------------------------------------------

    def run_on_main(
        self,
        fn: Callable[[], Any],
        *,
        timeout: float | None = None,
        label: str | None = None,
    ) -> Any:
        """Invoke ``fn`` on Live's main thread; return its result.

        Symmetric to ``concurrent.futures.Future.result``, but we don't pull
        in ``concurrent.futures`` because Live's Python embedding is
        constrained and we want zero runtime deps on the Live side.

        ``timeout`` overrides the context-wide default for THIS bout. Some Live
        operations legitimately exceed a general-purpose ceiling — instantiating
        a Max for Live device, enumerating every parameter of a large sampled
        rack — and a timeout shorter than the real operation is not a safety
        net, it is a false report of failure. The per-action values live on the
        Action schema and MUST stay in step with the client-side read-timeout
        table (``hallucinote_mcp.client._READ_TIMEOUTS``): if the two ends
        disagree, whichever gives up first turns a working call into a lie.

        ``label`` names the operation in the busy/escalation messages, so a
        caller that is refused learns WHAT Live is doing rather than just that
        it is unavailable.

        Raises :class:`LiveBusyError` if another thread's bout is already in
        flight, rather than queueing behind it.

        Raises :class:`LiveWorkEscalatedError` when the ceiling passes with the
        callback still unrun or unfinished. That is NOT a failure report: the
        work is registered as a ``main_thread`` job, the bout stays occupied,
        and the caller polls the job instead of retrying.
        """
        wait = self._main_thread_timeout if timeout is None else timeout
        me = threading.get_ident()
        done = threading.Event()
        box: dict[str, Any] = {}

        # Bounded wait, then refuse. A short wait absorbs the ordinary case of
        # two quick calls overlapping; refusing after it is what stops an
        # unbounded queue forming behind a genuinely long operation.
        deadline = time.monotonic() + _BUSY_ADMIT_WAIT_S
        with self._bout_cv:
            while self._bout is not None and self._bout.owner_ident != me:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise LiveBusyError(self._busy_message(self._bout))
                self._bout_cv.wait(remaining)
            outer = self._bout is None
            if outer:
                bout = _Bout(
                    label=label or "a Live API call",
                    started=time.monotonic(),
                    owner_ident=me,
                )
                self._bout = bout
            else:
                # Nested re-entry on the owning thread: the OUTER bout keeps
                # its label and start time — it is the thing a refused caller
                # needs named, and the elapsed time that matters is the whole
                # operation's, not the innermost step's.
                bout = self._bout  # type: ignore[assignment]
            bout.outstanding += 1

        def runner() -> None:
            try:
                box["result"] = fn()
            except BaseException as exc:  # prawduct:allow prawduct/broad-except -- capture any exception and re-raise on the worker thread; otherwise it goes uncaught in Live's main loop.
                box["error"] = exc
            finally:
                done.set()
                self._runner_finished(bout)

        try:
            self._schedule_on_main(runner)
        except BaseException:  # prawduct:allow prawduct/broad-except -- if the schedule never happened, the runner will never signal; release the fence and re-raise rather than leaving the bout occupied forever.
            # The runner is what clears the bout, so a callback that was never
            # scheduled would fence Live's main thread permanently — the exact
            # inverse of the defect this machine fixes, and the one failure
            # mode with no operator-visible cause. Release, then re-raise.
            self._runner_finished(bout)
            raise
        if not done.wait(timeout=wait):
            escalation = self._escalate(bout, box, done, label, wait)
            if escalation is not None:
                raise escalation
            # The callback landed inside the escalation's own race window —
            # nothing was escalated, so report the real outcome below.
        if "error" in box:
            raise box["error"]
        return box.get("result")

    # -- internals ----------------------------------------------------------

    def _registry(self) -> JobRegistry:
        return (
            self._job_registry
            if self._job_registry is not None
            else default_registry()
        )

    @staticmethod
    def _busy_message(bout: _Bout) -> str:
        elapsed = f"{bout.elapsed():.1f}s"
        tail = (
            f" It already outran its ceiling and is observable as job "
            f"{bout.job_id}."
            if bout.job_id is not None
            else ""
        )
        return (
            f"Live's main thread is busy with {bout.label} "
            f"(running {elapsed}); this request was refused rather than "
            f"queued behind it. The running operation cannot be cancelled — "
            f"wait for it to finish rather than retrying immediately.{tail}"
        )

    def _runner_finished(self, bout: _Bout) -> None:
        """Called on Live's main thread as each scheduled callback returns.

        The LAST outstanding runner clears the bout — not the waiter. A nested
        bout whose inner callback never lands therefore keeps the fence closed
        even after the outer callback has returned, which is the honest state:
        Live is still committed to work nobody can cancel.
        """
        settle: Callable[[], None] | None = None
        with self._bout_cv:
            bout.outstanding -= 1
            if bout.outstanding > 0:
                return
            settle = bout.settle
            bout.settle = None
            if self._bout is bout:
                self._bout = None
                self._bout_cv.notify_all()
        if settle is not None:
            settle()

    def _escalate(
        self,
        bout: _Bout,
        box: dict[str, Any],
        done: threading.Event,
        label: str | None,
        waited: float,
    ) -> LiveWorkEscalatedError | None:
        """Register the still-running bout as a job and build the escalation.

        Returns ``None`` when the callback landed in the window between the
        wait expiring and this acquiring the condition — then nothing is
        escalated and the caller reports the real result.
        """
        with self._bout_cv:
            if done.is_set():
                return None
            if bout.job_id is None:
                job = self._registry().create(
                    kind="main_thread",
                    detail={
                        "label": bout.label,
                        "elapsed_s": round(bout.elapsed(), 3),
                    },
                )
                bout.job_id = job.job_id
                bout.settle = lambda: self._settle_escalated_job(job, box)
            bout.abandoned = True
            # No live waiter owns this any more. Beyond stating the fact, this
            # closes the recycled-ident hazard: the escalating thread is about
            # to return to the connection pool, and a later thread reusing its
            # ident must NOT inherit re-entry rights into abandoned work.
            bout.owner_ident = None
            return LiveWorkEscalatedError(
                job_id=bout.job_id,
                label=label or bout.label,
                elapsed_s=bout.elapsed(),
                waited_s=waited,
            )

    def _settle_escalated_job(self, job: Job, box: dict[str, Any]) -> None:
        """Land the terminal state of an escalated bout once Live returns.

        Reads the escalating call's own result box, so the caller polling the
        job gets the result it would have got had the call landed inside its
        ceiling.
        """
        registry = self._registry()
        if "error" in box:
            exc = box["error"]
            registry.mark_failed(
                job.job_id, f"{exc.__class__.__name__}: {exc}",
            )
        else:
            registry.mark_done(job.job_id, {"result": box.get("result")})


__all__ = ["LiveLiveContext"]
