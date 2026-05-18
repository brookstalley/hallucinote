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
from typing import Any, Callable


SongFactory = Callable[[], Any]
ApplicationFactory = Callable[[], Any]
ScheduleOnMain = Callable[[Callable[[], None]], None]


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

    def run_on_main(self, fn: Callable[[], Any]) -> Any:
        """Invoke ``fn`` on Live's main thread; return its result.

        Symmetric to ``concurrent.futures.Future.result``, but we don't pull
        in ``concurrent.futures`` because Live's Python embedding is
        constrained and we want zero runtime deps on the Live side.
        """
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
        if not done.wait(timeout=self._main_thread_timeout):
            raise TimeoutError(
                f"Live API call did not complete within {self._main_thread_timeout}s — "
                f"Live may be stalled or the schedule_on_main hook is misconfigured"
            )
        if "error" in box:
            raise box["error"]
        return box.get("result")


__all__ = ["LiveLiveContext"]
