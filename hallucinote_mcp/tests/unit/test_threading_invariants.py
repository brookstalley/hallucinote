"""Cross-tool threading invariants — W3-F follow-up (2026-05-18).

The Critic caught a cross-thread RLock deadlock in the original W3-F
landing: ``cue_create`` / ``cue_create_batch`` / ``cue_delete`` were
correctly marked ``runs_on_worker=True`` and acquire
``context.live_state_lock`` on the worker thread. But ``seek_handler``
and ``cue_jump_handler`` still ran on the default main-thread-wrapped
path AND ALSO took the same RLock. ``threading.RLock`` is per-thread
reentrant but not cross-thread; a main-thread acquire of a lock held
by the worker thread blocks the main thread, which is exactly the
thread the worker's queued ``run_on_main`` bouts are waiting to run on.
Result: deadlock under concurrent cue + seek traffic.

This module pins two contracts:

1. **Static cross-check** (cheap, runs every suite): every action
   whose handler acquires ``context.live_state_lock`` must be
   registered with ``runs_on_worker=True``. The LOCK_USERS set is the
   audit trail of acknowledged lock takers; tests check the source
   tree for any ``context.live_state_lock`` reference and assert the
   enclosing action carries the flag.

2. **Dynamic deadlock reproduction** (slow, but the real proof): a
   two-OS-thread fake context simulating a separate main thread.
   Issues concurrent ``cue_create`` + ``seek`` from two worker threads
   and asserts both complete within a generous timeout. Pre-fix this
   test deadlocks within seconds; post-fix it completes well under
   one second.
"""
from __future__ import annotations

import ast
import pathlib
import queue
import threading
from typing import Any

import pytest

from hallucinote_mcp import schema
from hallucinote_mcp.dispatcher import dispatch
from hallucinote_mcp.testing import isolated_actions
from hallucinote_mcp.wire import Request


# ---------------------------------------------------------------------------
# Static cross-check: live_state_lock takers must be runs_on_worker=True
# ---------------------------------------------------------------------------


# Hard-coded audit list of (tool, action) pairs whose handler acquires
# context.live_state_lock. The static test below also scans the source
# tree and complains if anything outside this set references the lock —
# the audit list and the source tree must agree.
LOCK_USERS: frozenset[tuple[str, str]] = frozenset({
    ("ableton_arrangement", "cue_create"),
    ("ableton_arrangement", "cue_create_batch"),
    ("ableton_arrangement", "cue_delete"),
    ("ableton_arrangement", "cue_jump"),
    ("ableton_session", "seek"),
    ("ableton_automation", "perform_batch"),
})


def test_every_lock_taker_is_runs_on_worker():
    """Structural contract — every action that acquires
    ``context.live_state_lock`` MUST be ``runs_on_worker=True``. RLocks
    are per-thread reentrant; mixing main-thread and worker-thread
    holders against the same RLock deadlocks under concurrent traffic.
    """
    with isolated_actions():
        for tool, action_name in sorted(LOCK_USERS):
            action = schema.get(tool, action_name)
            assert action is not None, (
                f"{tool}({action_name}) not registered; LOCK_USERS out of sync"
            )
            assert action.runs_on_worker, (
                f"{tool}({action_name}) acquires live_state_lock but is "
                f"NOT registered with runs_on_worker=True. This causes a "
                f"cross-thread RLock deadlock against worker-thread "
                f"holders. Add `runs_on_worker=True` to its register() "
                f"call in actions/."
            )


def _scan_handler_source_for_lock_uses() -> set[str]:
    """Walk every handler module, parse with ast, find functions that
    reference ``context.live_state_lock`` (acquire OR mention). Returns
    the set of function names — caller maps these to (tool, action)
    via the schema."""
    handlers_dir = (
        pathlib.Path(__file__).resolve().parents[2]
        / "src" / "hallucinote_mcp" / "handlers"
    )
    found: set[str] = set()
    for py_file in sorted(handlers_dir.glob("*.py")):
        tree = ast.parse(py_file.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            # Inline check: does the function body reference
            # ``context.live_state_lock`` anywhere?
            for sub in ast.walk(node):
                if (
                    isinstance(sub, ast.Attribute)
                    and sub.attr == "live_state_lock"
                    and isinstance(sub.value, ast.Name)
                    and sub.value.id == "context"
                ):
                    found.add(node.name)
                    break
    return found


def test_no_undeclared_lock_taker_in_handler_source():
    """Audit: every handler function that references
    ``context.live_state_lock`` must correspond to an entry in
    LOCK_USERS. If a new handler grows lock usage and the maintainer
    forgets to update LOCK_USERS, this test fails loudly so the
    runs_on_worker review can't be silently skipped.
    """
    with isolated_actions():
        lock_taker_fn_names = _scan_handler_source_for_lock_uses()
        # Strip the inner helper that's locked-by-contract (the caller
        # acquires before calling): _create_one_cue_locked.
        # It's not directly bound to an action; cue_create / cue_create_batch
        # wrap it.
        lock_taker_fn_names.discard("_create_one_cue_locked")

        # Map registered actions' handler functions → set of fn names
        declared_fn_names: set[str] = set()
        for (tool, action_name) in LOCK_USERS:
            action = schema.get(tool, action_name)
            assert action is not None
            assert action.handler is not None, (
                f"{tool}({action_name}) has no handler — LOCK_USERS entry "
                f"requires a handler-based action"
            )
            declared_fn_names.add(action.handler.__name__)

        missing = lock_taker_fn_names - declared_fn_names
        assert not missing, (
            f"Handler function(s) reference context.live_state_lock but "
            f"the corresponding action is not in LOCK_USERS: {sorted(missing)}. "
            f"Add the (tool, action_name) tuple to LOCK_USERS in this file "
            f"AND register the action with runs_on_worker=True."
        )

        # Reverse direction: every LOCK_USERS handler is actually in the
        # source-tree set. Otherwise LOCK_USERS has a stale entry.
        stale = declared_fn_names - lock_taker_fn_names
        assert not stale, (
            f"LOCK_USERS lists action(s) whose handler does NOT reference "
            f"context.live_state_lock anymore: {sorted(stale)}. Remove "
            f"these stale entries from LOCK_USERS — the runs_on_worker "
            f"flag may also no longer be needed for them."
        )


# ---------------------------------------------------------------------------
# Dynamic deadlock reproduction — two-threaded fake context
# ---------------------------------------------------------------------------


class _SimulatedLiveCtx:
    """Two-thread fake context that mirrors LiveLiveContext's threading
    model. There's a dedicated "main thread" that runs a tight pump
    loop over a queue; worker threads invoke ``run_on_main(fn)`` to
    enqueue work and block on the result.

    This is exactly the threading shape LiveLiveContext implements
    against the real Remote Script's ``schedule_message``. Pre-fix
    code paths that try to acquire ``live_state_lock`` on the main
    thread while a worker holds it will deadlock here too.
    """

    def __init__(self) -> None:
        self._song = _SimulatedSong()
        self._lock = threading.RLock()
        # Main-thread work queue. Each item: (fn, done_event, result_box).
        self._main_q: queue.Queue = queue.Queue()
        self._main_thread = threading.Thread(
            target=self._main_loop, daemon=True, name="sim-live-main",
        )
        self._stop = threading.Event()
        self._main_thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._main_q.put(None)  # sentinel to unblock the pump
        self._main_thread.join(timeout=2.0)

    @property
    def song(self) -> "_SimulatedSong":
        return self._song

    @property
    def live_state_lock(self) -> threading.RLock:
        return self._lock

    def run_on_main(self, fn, **_kwargs):  # type: ignore[no-untyped-def]
        done = threading.Event()
        box: dict[str, Any] = {}
        self._main_q.put((fn, done, box))
        if not done.wait(timeout=5.0):
            raise TimeoutError(
                "run_on_main bout did not complete within 5s — likely "
                "a deadlock against a lock held by another worker thread"
            )
        if "error" in box:
            raise box["error"]
        return box.get("result")

    def _main_loop(self) -> None:
        while not self._stop.is_set():
            item = self._main_q.get()
            if item is None:
                return
            fn, done, box = item
            try:
                box["result"] = fn()
            except BaseException as exc:  # prawduct:ok-broad-except — pump must capture any exception to deliver back to worker
                box["error"] = exc
            finally:
                done.set()


class _SimulatedSong:
    """Minimal Live API surface used by the cue + seek handlers."""

    def __init__(self) -> None:
        self.current_song_time = 0.0
        self.signature_numerator = 4
        self.signature_denominator = 4
        self.last_event_time = 256.0
        self.cue_points: list[_SimulatedCue] = []

    def set_or_delete_cue(self) -> None:
        # Toggle: create cue at current_song_time if absent; delete if present.
        pos = round(self.current_song_time, 6)
        for c in self.cue_points:
            if round(c.time, 6) == pos:
                self.cue_points.remove(c)
                return
        self.cue_points.append(_SimulatedCue(time=pos, name=""))


class _SimulatedCue:
    def __init__(self, time: float, name: str) -> None:
        self.time = time
        self.name = name


@pytest.fixture()
def loaded_actions():
    """Loads the full action registry once per test."""
    with isolated_actions():
        yield schema


def test_concurrent_cue_create_and_seek_do_not_deadlock(loaded_actions):
    """Real-threading regression for the Critic-flagged W3-F deadlock.

    Two worker threads issue concurrent requests against ONE Live
    context with a single shared RLock:

      Worker A: ableton_arrangement(action='cue_create', position_beats=128.0)
      Worker B: ableton_session(action='seek', bar=10, beat=0.0)

    Both handlers acquire ``live_state_lock`` and both run on worker
    threads (post-fix). Without the fix, worker B's seek would have
    been wrapped in ``run_on_main`` (default path), enqueueing
    seek_handler onto the main thread — which would then block trying
    to acquire the lock held by worker A — at which point worker A's
    own main-thread bouts can't run, and the whole thing deadlocks.

    Asserts both requests complete within a generous timeout (the
    actual cost is sub-second; the timeout is 5s to leave headroom).
    """
    ctx = _SimulatedLiveCtx()
    # Seed: a cue at 0 so worker B's seek doesn't trigger any odd
    # interactions; worker A creates a NEW cue at 128.
    ctx.song.cue_points.append(_SimulatedCue(time=0.0, name="intro"))

    results: dict[str, Any] = {}
    errors: dict[str, BaseException] = {}
    barrier = threading.Barrier(2)

    def worker_cue() -> None:
        barrier.wait()  # synchronize start with worker B
        try:
            results["cue"] = dispatch(
                Request(
                    tool="ableton_arrangement", action="cue_create",
                    params={"position_beats": 128.0, "name": "post-fix"},
                ),
                context=ctx,
            )
        except BaseException as exc:  # prawduct:ok-broad-except — test harness must capture any thread-side error to fail the assertion cleanly
            errors["cue"] = exc

    def worker_seek() -> None:
        barrier.wait()  # synchronize start with worker A
        # Issue a few seeks in quick succession to stress the lock window.
        try:
            for bar in (5, 10, 15):
                results[f"seek_{bar}"] = dispatch(
                    Request(
                        tool="ableton_session", action="seek",
                        params={"bar": bar, "beat": 0.0},
                    ),
                    context=ctx,
                )
        except BaseException as exc:  # prawduct:ok-broad-except — test harness; see worker_cue
            errors["seek"] = exc

    t_cue = threading.Thread(target=worker_cue, name="test-worker-cue")
    t_seek = threading.Thread(target=worker_seek, name="test-worker-seek")
    t_cue.start()
    t_seek.start()
    t_cue.join(timeout=10.0)
    t_seek.join(timeout=10.0)

    try:
        assert not t_cue.is_alive(), (
            "cue_create worker thread did not finish within 10s — "
            "DEADLOCK detected. This is the regression the Critic caught "
            "in W3-F's original landing."
        )
        assert not t_seek.is_alive(), (
            "seek worker thread did not finish within 10s — DEADLOCK"
        )
        assert not errors, f"thread errors: {errors!r}"
        assert results["cue"].ok, f"cue_create failed: {results['cue'].error}"
        for bar in (5, 10, 15):
            r = results[f"seek_{bar}"]
            assert r.ok, f"seek bar={bar} failed: {r.error}"
        # Cue was actually created.
        assert any(
            round(c.time, 6) == 128.0 for c in ctx.song.cue_points
        ), f"cue at 128.0 not present after the test; cues: {ctx.song.cue_points}"
    finally:
        ctx.stop()


def test_concurrent_cue_create_and_cue_jump_do_not_deadlock(loaded_actions):
    """Same shape as the seek test but with cue_jump as the second
    handler. cue_jump is also runs_on_worker=True post-fix; pre-fix
    it would have deadlocked against cue_create exactly like seek did."""
    ctx = _SimulatedLiveCtx()
    ctx.song.cue_points.extend([
        _SimulatedCue(time=0.0, name="intro"),
        _SimulatedCue(time=64.0, name="verse"),
    ])
    results: dict[str, Any] = {}
    errors: dict[str, BaseException] = {}
    barrier = threading.Barrier(2)

    def worker_create() -> None:
        barrier.wait()
        try:
            results["create"] = dispatch(
                Request(
                    tool="ableton_arrangement", action="cue_create",
                    params={"position_beats": 32.0},
                ),
                context=ctx,
            )
        except BaseException as exc:  # prawduct:ok-broad-except — test harness
            errors["create"] = exc

    def worker_jump() -> None:
        barrier.wait()
        try:
            results["jump"] = dispatch(
                Request(
                    tool="ableton_arrangement", action="cue_jump",
                    params={"name": "verse"},
                ),
                context=ctx,
            )
        except BaseException as exc:  # prawduct:ok-broad-except — test harness
            errors["jump"] = exc

    # cue_jump uses jump_to_X_cue / target.jump(); our simulated song
    # doesn't have those, so cue_jump exercises the "name path" with
    # ``jumper is None`` falling back to current_song_time write. That's
    # still a live_state_lock acquire on the worker — the deadlock check
    # is what matters.

    t_create = threading.Thread(target=worker_create, name="test-cue-create")
    t_jump = threading.Thread(target=worker_jump, name="test-cue-jump")
    t_create.start()
    t_jump.start()
    t_create.join(timeout=10.0)
    t_jump.join(timeout=10.0)

    try:
        assert not t_create.is_alive(), "cue_create worker deadlocked"
        assert not t_jump.is_alive(), "cue_jump worker deadlocked"
        assert not errors, f"thread errors: {errors!r}"
        assert results["create"].ok, f"cue_create: {results['create'].error}"
        assert results["jump"].ok, f"cue_jump: {results['jump'].error}"
    finally:
        ctx.stop()
