"""Live-side LiveContext — bridges the dispatcher's ``LiveContext`` Protocol
to the concrete Live API.

The dispatcher wraps each action execution in ``context.run_on_main(fn)``,
which is responsible for:

  1. Scheduling ``fn`` onto Live's main thread (the only thread allowed to
     touch ``Live.Song.*``).
  2. Blocking the calling worker thread until the main-thread call returns.
  3. Returning the result, or re-raising any exception ``fn`` raised.

``LiveLiveContext.run_on_main`` does that via the ``_Framework`` primitive
``schedule_message``. ``LiveLiveContext.song`` returns the current Song
object and is meant to be read from inside the marshaled callback.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable


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
# dispatcher can translate it without importing this Live-only module.
from ..dispatcher import LiveBusyError  # noqa: E402  (re-exported for callers)


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
        thread to complete an operation before raising ``TimeoutError``.
        Live's main-thread queue should drain in milliseconds; 15s is a
        generous ceiling that surfaces a stalled engine without hanging
        the MCP forever.
    """

    def __init__(
        self,
        song_factory: SongFactory,
        application_factory: ApplicationFactory,
        schedule_on_main: ScheduleOnMain,
        main_thread_timeout: float = 15.0,
    ):
        self._song_factory = song_factory
        self._application_factory = application_factory
        self._schedule_on_main = schedule_on_main
        self._main_thread_timeout = main_thread_timeout
        # Re-entrant so batch handlers (e.g. cue_create_batch) can acquire
        # it once and call into per-item helpers that also acquire.
        self._live_state_lock = threading.RLock()
        # Admission control for Live's main thread.
        #
        # A timeout on `run_on_main` does NOT cancel the work — Python cannot
        # interrupt a running Live API call. So when a bout overruns, the caller
        # is told "failed" while the main thread is still committed, and its
        # natural next move (retry, or simply the next call) schedules MORE work
        # behind the running op. The TCP server spawns a thread per connection
        # with no admission control, so nothing throttles that pile-up: one slow
        # operation becomes an unresponsive Live.
        #
        # Re-entrant so a worker-thread handler already inside a bout can nest;
        # a DIFFERENT thread arriving while a bout is in flight is refused fast
        # with `LiveBusyError` instead of silently queueing behind it.
        self._main_bout_lock = threading.RLock()
        self._main_bout_label: str | None = None
        self._main_bout_started: float | None = None

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

        ``label`` names the operation in the busy/timeout messages, so a caller
        that is refused learns WHAT Live is doing rather than just that it is
        unavailable.

        Raises :class:`LiveBusyError` if another thread's bout is already in
        flight, rather than queueing behind it (see ``_main_bout_lock``).
        """
        wait = self._main_thread_timeout if timeout is None else timeout
        # Bounded wait, then refuse. A short wait absorbs the ordinary case of
        # two quick calls overlapping; refusing after it is what stops an
        # unbounded queue forming behind a genuinely long operation.
        if not self._main_bout_lock.acquire(timeout=_BUSY_ADMIT_WAIT_S):
            busy_label = self._main_bout_label or "an unnamed operation"
            started = self._main_bout_started
            elapsed = f"{time.monotonic() - started:.1f}s" if started else "unknown"
            raise LiveBusyError(
                f"Live's main thread is busy with {busy_label} "
                f"(running {elapsed}); this request was refused rather than "
                f"queued behind it. The running operation cannot be cancelled — "
                f"wait for it to finish rather than retrying immediately."
            )
        outer = self._main_bout_label is not None  # nested re-entry on this thread
        if not outer:
            self._main_bout_label = label or "a Live API call"
            self._main_bout_started = time.monotonic()
        try:
            done = threading.Event()
            box: dict[str, Any] = {}

            def runner() -> None:
                try:
                    box["result"] = fn()
                except BaseException as exc:  # prawduct:ok-broad-except — capture any exception and re-raise on the worker thread; otherwise it goes uncaught in Live's main loop
                    box["error"] = exc
                finally:
                    done.set()

            self._schedule_on_main(runner)
            if not done.wait(timeout=wait):
                raise TimeoutError(
                    f"Live API call ({label or 'unnamed'}) did not complete "
                    f"within {wait}s. IT IS STILL RUNNING on Live's main thread "
                    f"— Python cannot interrupt a Live API call, so this is a "
                    f"report that we stopped waiting, NOT that the work stopped. "
                    f"Do not retry immediately: another call now queues behind "
                    f"the one still executing."
                )
            if "error" in box:
                raise box["error"]
            return box.get("result")
        finally:
            if not outer:
                self._main_bout_label = None
                self._main_bout_started = None
            self._main_bout_lock.release()


__all__ = ["LiveLiveContext"]
