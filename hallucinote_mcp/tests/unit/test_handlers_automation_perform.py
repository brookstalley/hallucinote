"""Tests for ``ableton_automation(action='perform_batch')`` — ENV-9P4T
single-pass batched recording (supersedes the single-arc ENV-7G4K
``perform``).

Fake-Live coverage of the windowed gesture-recording handler:

  - exact begin_gesture → ramp → end_gesture → restore sequence (N=1 is
    byte-for-byte the proven single-arc path)
  - per-parameter WINDOWING across N arcs in one transport pass: each arc's
    gesture opens at its span entry and closes at its exit, so a short/late
    arc never stamps a flat value across the whole pass
  - state restore when the ramp raises mid-flight (every open gesture closed)
  - record_mode settle-poll (probe 10: async apply) including the timeout
  - breakpoint interpolation (linear / hold / fast / slow, out-of-range
    holds, segment boundaries)
  - param validation (addressing, span, target_kind, empty batch)
  - wire-path regression through the dispatcher

The fakes simulate the two async behaviors the mechanism depends on:
``record_mode`` applying N reads late, and ``current_song_time`` advancing
while the transport plays. Everything is event-logged so the ordering
assertions read like the probe-4 recipe.
"""
from __future__ import annotations

import threading
from typing import Any

import pytest

from hallucinote_mcp import schema
from hallucinote_mcp.dispatcher import dispatch
from hallucinote_mcp.handlers import automation as automation_handlers
from hallucinote_mcp.handlers.automation import (
    _interp_performed_value,
    _require_parent,
    _resolve_send,
    _validate_breakpoints,
    perform_batch_handler,
)
from hallucinote_mcp.testing import isolated_actions
from hallucinote_mcp.wire import Request


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeGestureParam:
    """A Live DeviceParameter that records gesture lifecycle + value sets.

    Events land in the shared ``events`` log (cross-param timeline) AND in
    this param's own ``own`` log (so per-param windowing is observable when
    several params share one pass)."""

    def __init__(self, events: list[tuple]):
        self._events = events
        self.own: list[tuple] = []
        self._value = 0.85
        self.automation_state = 0
        # The state end_gesture flips to (probe 4: a successful record →1).
        # Override to a non-1 value to simulate a write that never verifies.
        self.verify_state = 1
        self.raise_on_set_after: int | None = None
        self._set_count = 0

    def begin_gesture(self) -> None:
        self._events.append(("begin_gesture",))
        self.own.append(("begin",))

    def end_gesture(self) -> None:
        self._events.append(("end_gesture",))
        self.own.append(("end",))
        # Probe 4: a successful record flips automation_state 0 → 1.
        self.automation_state = self.verify_state

    @property
    def value(self) -> float:
        return self._value

    @value.setter
    def value(self, v: float) -> None:
        self._set_count += 1
        if (
            self.raise_on_set_after is not None
            and self._set_count > self.raise_on_set_after
        ):
            raise RuntimeError("simulated Live parameter write failure")
        self._events.append(("set_value", round(float(v), 6)))
        self.own.append(("set", round(float(v), 6)))
        self._value = float(v)


class FakeMixerDevice:
    def __init__(self, events: list[tuple]):
        self.volume = FakeGestureParam(events)
        self.panning = FakeGestureParam(events)
        self.sends: list[FakeGestureParam] = []


class FakeTrack:
    def __init__(self, events: list[tuple]):
        self.mixer_device = FakeMixerDevice(events)
        self.devices: list[Any] = []


class FakeDevice:
    def __init__(self, parameters: list[Any]):
        self.parameters = parameters


class FakeNamedParam(FakeGestureParam):
    def __init__(self, events: list[tuple], name: str):
        super().__init__(events)
        self.name = name


class FakePerformSong:
    """Simulates the two async Song behaviors the mechanism rides:

    - ``record_mode`` applies ``record_mode_apply_after_reads`` reads
      AFTER the set (probe 10's ~300 ms async apply).
    - ``current_song_time`` advances ``beats_per_read`` on every read
      while the transport plays (so the ramp loop terminates).
    """

    def __init__(self, events: list[tuple]):
        self._events = events
        self.tempo = 120.0
        self.is_playing = False
        self.session_automation_record = False
        self.master_track = FakeTrack(events)
        self.tracks: list[Any] = [FakeTrack(events)]
        self.return_tracks: list[Any] = [FakeTrack(events)]

        self.beats_per_read = 1.0
        self.record_mode_apply_after_reads = 0
        # When True, a disarm (record_mode=False) is accepted (event logged)
        # but never applies — Live's async-apply failing silently (probe 10).
        self.disarm_never_applies = False
        # ENV-8K2R #1: the same async-disarm-never-applies simulation for
        # session_automation_record (empirically async too) — set True to prove
        # the restore-path settle-verify catches the silently-armed set.
        self.sar_disarm_never_applies = False
        self._record_mode_actual = False
        self._record_mode_pending: bool | None = None
        self._record_mode_reads_until_apply = 0
        self._song_time = 0.0
        self.re_enable_automation_calls = 0

    # -- record_mode: async apply ------------------------------------
    @property
    def record_mode(self) -> bool:
        if self._record_mode_pending is not None:
            if self._record_mode_reads_until_apply <= 0:
                self._record_mode_actual = self._record_mode_pending
                self._record_mode_pending = None
            else:
                self._record_mode_reads_until_apply -= 1
        return self._record_mode_actual

    @record_mode.setter
    def record_mode(self, v: bool) -> None:
        self._events.append(("record_mode", bool(v)))
        if not bool(v) and self.disarm_never_applies:
            # Accepted but never applied — _record_mode_actual stays armed.
            self._record_mode_pending = None
            return
        self._record_mode_pending = bool(v)
        self._record_mode_reads_until_apply = self.record_mode_apply_after_reads

    # -- session_automation_record (event-logged plain attr) ----------
    @property
    def session_automation_record(self) -> bool:
        return self._sar

    @session_automation_record.setter
    def session_automation_record(self, v: bool) -> None:
        # The initializing assignment in __init__ lands here too — only
        # log once _events exists and init is done.
        if hasattr(self, "_sar"):
            self._events.append(("session_automation_record", bool(v)))
            # ENV-8K2R #1: simulate the async DISARM that's accepted but never
            # applies (Live's silent async-apply failing) — the value is logged
            # but _sar stays armed, so the settle-verify must catch it.
            if not bool(v) and self.sar_disarm_never_applies:
                return
        self._sar = bool(v)

    # -- current_song_time: advances while playing ---------------------
    @property
    def current_song_time(self) -> float:
        t = self._song_time
        if self.is_playing:
            self._song_time += self.beats_per_read
        return t

    @current_song_time.setter
    def current_song_time(self, v: float) -> None:
        self._events.append(("seek", float(v)))
        self._song_time = float(v)

    def start_playing(self) -> None:
        self._events.append(("play",))
        self.is_playing = True

    def stop_playing(self) -> None:
        self._events.append(("stop",))
        self.is_playing = False

    def re_enable_automation(self) -> None:
        self._events.append(("re_enable_automation",))
        self.re_enable_automation_calls += 1


class FakeCtx:
    def __init__(self):
        self.events: list[tuple] = []
        self._song = FakePerformSong(self.events)
        self._lock = threading.RLock()
        self.run_on_main_calls = 0
        # Real run_on_main marshals to Live's main thread and BLOCKS; calling
        # it from within a run_on_main bout (depth > 1) deadlocks. Track the
        # max nesting depth so a regression can assert no bout ever nests.
        self._rom_depth = 0
        self.max_run_on_main_depth = 0

    @property
    def song(self) -> FakePerformSong:
        return self._song

    @property
    def application(self) -> Any:
        return None

    @property
    def live_state_lock(self) -> threading.RLock:
        return self._lock

    def run_on_main(self, fn):
        self.run_on_main_calls += 1
        self._rom_depth += 1
        self.max_run_on_main_depth = max(
            self.max_run_on_main_depth, self._rom_depth
        )
        try:
            return fn()
        finally:
            self._rom_depth -= 1


@pytest.fixture(autouse=True)
def fast_polls(monkeypatch):
    """Collapse worker-thread sleeps so the suite stays fast; the loop
    structure (bout-per-touch, sleep-between-bouts) is unchanged."""
    monkeypatch.setattr(automation_handlers, "_PERFORM_UPDATE_PERIOD_S", 0.0)
    monkeypatch.setattr(automation_handlers, "_PERFORM_SETTLE_POLL_S", 0.0)


def _bp(t: float, v: float, curve: str | None = None) -> dict[str, Any]:
    bp: dict[str, Any] = {"time_beats": t, "value": v}
    if curve is not None:
        bp["curve"] = curve
    return bp


def _one(ctx, *, settle_timeout_ms: int | None = None, **arc_fields):
    """Run perform_batch with a single arc; returns the full batched
    result (the arc is ``result["arcs"][0]``)."""
    kwargs: dict[str, Any] = {}
    if settle_timeout_ms is not None:
        kwargs["settle_timeout_ms"] = settle_timeout_ms
    return perform_batch_handler(ctx, arcs=[arc_fields], **kwargs)


def _arc0(result):
    return result["arcs"][0]


# ---------------------------------------------------------------------------
# Gesture ordering — the probe-4 recipe, exactly (N=1 == the proven path)
# ---------------------------------------------------------------------------


def test_perform_records_exact_gesture_sequence():
    ctx = FakeCtx()
    result = _one(
        ctx, target_kind="mixer_volume", master=True,
        breakpoints=[_bp(0.0, 0.5), _bp(4.0, 0.9)],
    )

    events = ctx.events
    # Arm phase, in order: session record flag, record_mode on, seek.
    assert events[0] == ("session_automation_record", True)
    assert events[1] == ("record_mode", True)
    assert events[2] == ("seek", 0.0)
    assert events[3] == ("begin_gesture",)
    assert events[4] == ("play",)

    # Ramp: value sets strictly between play and end_gesture.
    end_idx = events.index(("end_gesture",))
    ramp = events[5:end_idx]
    assert ramp, "expected at least one value set during the ramp"
    assert all(e[0] == "set_value" for e in ramp)
    # Values follow the authored ascending arc.
    values = [e[1] for e in ramp]
    assert values == sorted(values)
    assert values[0] == pytest.approx(0.5)

    # Restore phase, in order, after end_gesture.
    tail = events[end_idx:]
    assert tail[0] == ("end_gesture",)
    assert tail[1] == ("stop",)
    assert tail[2] == ("record_mode", False)
    assert tail[3] == ("session_automation_record", False)
    assert tail[4] == ("re_enable_automation",)
    assert tail[5] == ("seek", 0.0)  # playhead restored to saved position

    arc = _arc0(result)
    assert arc["automation_state"] == 1
    assert arc["span_beats"] == [0.0, 4.0]
    assert arc["beats_performed"] == 4.0
    assert arc["updates_written"] == len(ramp)
    assert arc["target_kind"] == "mixer_volume"
    assert arc["master"] is True
    assert result["union_span_beats"] == [0.0, 4.0]
    assert result["arc_count"] == 1
    assert "restore_failures" not in result


def test_perform_restores_prior_transport_state():
    ctx = FakeCtx()
    song = ctx.song
    song._record_mode_actual = True  # user had the set armed
    song.session_automation_record = True
    song._song_time = 7.5
    ctx.events.clear()  # drop setup-logged events

    _one(
        ctx, target_kind="mixer_volume", master=True,
        breakpoints=[_bp(0.0, 0.5), _bp(2.0, 0.9)],
    )
    # Restore writes the SAVED values back, not hardcoded False.
    assert ("record_mode", True) in ctx.events[-5:]
    assert ("session_automation_record", True) in ctx.events[-5:]
    assert ctx.events[-1] == ("seek", 7.5)
    # Transport is left stopped (never silently resumes playback).
    assert song.is_playing is False


def test_perform_stops_inflight_playback_before_arming():
    ctx = FakeCtx()
    ctx.song.is_playing = True
    _one(
        ctx, target_kind="mixer_volume", master=True,
        breakpoints=[_bp(0.0, 0.5), _bp(2.0, 0.9)],
    )
    # The pre-arm stop comes before the arm writes.
    assert ctx.events[0] == ("stop",)
    assert ctx.events[1] == ("session_automation_record", True)


# ---------------------------------------------------------------------------
# Per-parameter windowing — the ENV-9P4T keystone
# ---------------------------------------------------------------------------


def test_perform_batch_windows_overlapping_arcs():
    """Two arcs in one pass: A spans [0,8] (master volume), B spans [4,12]
    (return volume). A opens at the union start (before play); B opens only
    when the playhead reaches its span start (mid-pass); each closes at its
    own span end. A short/late arc must NOT stamp a flat value across the
    whole pass — proven by each param's writes staying inside its own
    value band and B opening after A's first post-play write."""
    ctx = FakeCtx()
    ctx.song.beats_per_read = 2.0  # step coarsely through both spans
    a_param = ctx.song.master_track.mixer_device.volume
    b_param = ctx.song.return_tracks[0].mixer_device.volume

    result = perform_batch_handler(ctx, arcs=[
        {"arc_id": "A", "target_kind": "mixer_volume", "master": True,
         "breakpoints": [_bp(0.0, 0.20), _bp(8.0, 0.90)]},
        {"arc_id": "B", "target_kind": "mixer_volume", "return_index": 1,
         "breakpoints": [_bp(4.0, 0.10), _bp(12.0, 0.80)]},
    ])

    # Union span is [0,12]; each arc verified independently.
    assert result["union_span_beats"] == [0.0, 12.0]
    by_id = {a["arc_id"]: a for a in result["arcs"]}
    assert by_id["A"]["automation_state"] == 1
    assert by_id["B"]["automation_state"] == 1
    assert by_id["A"]["span_beats"] == [0.0, 8.0]
    assert by_id["B"]["span_beats"] == [4.0, 12.0]

    # Cross-param timeline: exactly two gestures; A opens before play, B
    # opens AFTER play and after A's first post-play write (windowed open).
    events = ctx.events
    begins = [i for i, e in enumerate(events) if e == ("begin_gesture",)]
    ends = [i for i, e in enumerate(events) if e == ("end_gesture",)]
    play_idx = events.index(("play",))
    assert len(begins) == 2 and len(ends) == 2
    assert begins[0] < play_idx < begins[1]
    first_set_after_play = next(
        i for i, e in enumerate(events) if i > play_idx and e[0] == "set_value"
    )
    assert begins[1] > first_set_after_play
    # Spans close in order: A (ends at 8) before B (ends at 12).
    assert ends[0] < ends[1]

    # Per-param bands: A only ever wrote values in [0.20, 0.90]; B only in
    # [0.10, 0.80]. A short/late arc never wrote the other's value.
    a_sets = [e[1] for e in a_param.own if e[0] == "set"]
    b_sets = [e[1] for e in b_param.own if e[0] == "set"]
    assert a_sets and b_sets
    assert all(0.20 <= v <= 0.90 for v in a_sets), a_sets
    assert all(0.10 <= v <= 0.80 for v in b_sets), b_sets
    # B's first write is at its span start value (~0.10), not the union start
    # — it did not begin recording until the playhead entered its window.
    assert b_sets[0] == pytest.approx(0.10)
    # Each param opened exactly once and closed exactly once.
    assert a_param.own[0] == ("begin",) and a_param.own[-1] == ("end",)
    assert b_param.own[0] == ("begin",) and b_param.own[-1] == ("end",)


def test_perform_batch_degenerate_window_reports_zero_writes():
    """A tiny window the playhead jumps in a single tick opens+closes with
    ZERO value writes — the handler reports updates_written==0 even though
    end_gesture flipped automation_state to 1. The apply layer treats that as
    a stale-lane non-verification (see test_push_perform); here we prove the
    handler actually produces the degenerate datum."""
    ctx = FakeCtx()
    ctx.song.beats_per_read = 60.0  # huge step jumps the tiny window whole
    result = perform_batch_handler(ctx, arcs=[
        {"arc_id": "driver", "target_kind": "mixer_volume", "master": True,
         "breakpoints": [_bp(0.0, 0.2), _bp(100.0, 0.9)]},
        {"arc_id": "tiny", "target_kind": "mixer_volume", "return_index": 1,
         "breakpoints": [_bp(48.0, 0.1), _bp(50.0, 0.8)]},
    ])
    by_id = {a["arc_id"]: a for a in result["arcs"]}
    assert by_id["tiny"]["updates_written"] == 0
    assert by_id["tiny"]["span_beats"] == [48.0, 50.0]
    # end_gesture flipped the (stale) lane to 1 — exactly the trap the apply
    # layer's updates_written gate guards against.
    assert by_id["tiny"]["automation_state"] == 1


def test_perform_batch_rejects_same_target_collision():
    """Two arcs resolving to the SAME parameter would fight for one gesture
    in the shared pass — rejected up front, naming both arc_ids, before any
    transport state is touched."""
    ctx = FakeCtx()
    with pytest.raises(ValueError, match="same parameter"):
        perform_batch_handler(ctx, arcs=[
            {"arc_id": "A", "target_kind": "mixer_volume", "master": True,
             "breakpoints": [_bp(0.0, 0.2), _bp(8.0, 0.9)]},
            {"arc_id": "B", "target_kind": "mixer_volume", "master": True,
             "breakpoints": [_bp(0.0, 0.5), _bp(8.0, 0.7)]},
        ])
    assert ctx.events == []


def test_perform_batch_one_pass_for_all_arcs():
    """All arcs record in a SINGLE transport pass — one arm/seek/play/stop,
    regardless of arc count (the performance win)."""
    ctx = FakeCtx()
    ctx.song.beats_per_read = 4.0
    perform_batch_handler(ctx, arcs=[
        {"arc_id": "A", "target_kind": "mixer_volume", "master": True,
         "breakpoints": [_bp(0.0, 0.2), _bp(8.0, 0.9)]},
        {"arc_id": "B", "target_kind": "mixer_volume", "return_index": 1,
         "breakpoints": [_bp(0.0, 0.1), _bp(8.0, 0.8)]},
    ])
    events = ctx.events
    assert sum(1 for e in events if e == ("play",)) == 1
    assert sum(1 for e in events if e == ("stop",)) == 1
    assert sum(1 for e in events if e[0] == "seek") == 2  # arm seek + restore
    assert sum(1 for e in events if e == ("re_enable_automation",)) == 1


# ---------------------------------------------------------------------------
# State restore on exception
# ---------------------------------------------------------------------------


def test_perform_restores_state_when_ramp_raises():
    ctx = FakeCtx()
    param = ctx.song.master_track.mixer_device.volume
    param.raise_on_set_after = 1  # second value write blows up

    with pytest.raises(RuntimeError, match="simulated Live parameter"):
        _one(
            ctx, target_kind="mixer_volume", master=True,
            breakpoints=[_bp(0.0, 0.5), _bp(8.0, 0.9)],
        )

    # Gesture closed, transport stopped, set disarmed — despite the raise.
    assert ("end_gesture",) in ctx.events
    assert ("stop",) in ctx.events
    assert ("record_mode", False) in ctx.events
    assert ("session_automation_record", False) in ctx.events
    assert ("re_enable_automation",) in ctx.events
    assert ctx.song.is_playing is False


def test_perform_batch_closes_every_open_gesture_when_ramp_raises():
    """A mid-pass failure must close ALL open gestures, not just the one
    whose write raised — a half-open batch would leave Live armed."""
    ctx = FakeCtx()
    ctx.song.beats_per_read = 2.0
    a_param = ctx.song.master_track.mixer_device.volume
    b_param = ctx.song.return_tracks[0].mixer_device.volume
    # Both arcs are active by beat 4; make B's write blow up after both
    # gestures are open.
    b_param.raise_on_set_after = 1

    with pytest.raises(RuntimeError, match="simulated Live parameter"):
        perform_batch_handler(ctx, arcs=[
            {"arc_id": "A", "target_kind": "mixer_volume", "master": True,
             "breakpoints": [_bp(0.0, 0.2), _bp(12.0, 0.9)]},
            {"arc_id": "B", "target_kind": "mixer_volume", "return_index": 1,
             "breakpoints": [_bp(0.0, 0.1), _bp(12.0, 0.8)]},
        ])

    # Both gestures closed (each param's own log ends with a close).
    assert a_param.own[-1] == ("end",)
    assert b_param.own[-1] == ("end",)
    assert ctx.song.is_playing is False
    assert ("record_mode", False) in ctx.events
    assert ("session_automation_record", False) in ctx.events


def test_perform_batch_never_nests_run_on_main():
    """run_on_main marshals to Live's main thread and blocks — calling it from
    WITHIN a run_on_main bout (depth > 1) deadlocks against real async Live.
    The disarm settle-verify calls the worker-only `_wait_for_song_flag_on_worker`
    (which itself polls via run_on_main) DIRECTLY on the worker, not via
    `_attempt`'s run_on_main — for BOTH the record_mode and the
    session_automation_record disarm. This fails if anyone re-wraps it (max
    depth 2)."""
    ctx = FakeCtx()
    _one(
        ctx, target_kind="mixer_volume", master=True,
        breakpoints=[_bp(0.0, 0.5), _bp(2.0, 0.9)],
    )
    assert ctx.max_run_on_main_depth == 1, ctx.max_run_on_main_depth


def test_perform_batch_ramp_deadline_raises_and_restores(monkeypatch):
    """A blocked transport (playhead never advances) trips the ramp wall-clock
    deadline → TimeoutError; the set is still disarmed + restored in finally."""
    monkeypatch.setattr(automation_handlers, "_PERFORM_WALL_CLOCK_FLOOR_S", 0.0)
    monkeypatch.setattr(automation_handlers, "_PERFORM_WALL_CLOCK_FACTOR", 0.0)
    ctx = FakeCtx()
    ctx.song.beats_per_read = 0.0  # playhead frozen → never reaches union end
    with pytest.raises(TimeoutError, match="union span end"):
        _one(
            ctx, target_kind="mixer_volume", master=True,
            breakpoints=[_bp(0.0, 0.5), _bp(8.0, 0.9)], settle_timeout_ms=20,
        )
    assert ("record_mode", False) in ctx.events
    assert ("session_automation_record", False) in ctx.events
    assert ctx.song.is_playing is False


def test_perform_batch_reports_unverified_arc_after_poll_timeout():
    """An arc whose automation_state never reaches 1 within the settle window
    is REPORTED with its non-1 state (poll-timeout branch), not raised — the
    apply layer owns the failed-verification policy."""
    ctx = FakeCtx()
    ctx.song.master_track.mixer_device.volume.verify_state = 0  # never verifies
    result = _one(
        ctx, target_kind="mixer_volume", master=True,
        breakpoints=[_bp(0.0, 0.5), _bp(2.0, 0.9)], settle_timeout_ms=20,
    )
    assert _arc0(result)["automation_state"] == 0


def test_perform_batch_settle_verifies_disarm():
    """record_mode applies asynchronously (probe 10) — the disarm in the
    restore path is settle-verified, so a disarm that's ACCEPTED but never
    applies surfaces in restore_failures (operator-visible) instead of a
    silently armed set."""
    ctx = FakeCtx()
    ctx.song.disarm_never_applies = True
    result = _one(
        ctx, target_kind="mixer_volume", master=True,
        breakpoints=[_bp(0.0, 0.5), _bp(2.0, 0.9)],
        settle_timeout_ms=20,
    )
    assert any("record_mode_settle" in f
               for f in result.get("restore_failures", [])), result


def test_perform_batch_settle_verifies_session_automation_record_disarm():
    """ENV-8K2R #1: session_automation_record ALSO applies asynchronously
    (probe 10, confirmed 2026-06-12) — its restore-path disarm is now
    settle-verified too. A disarm that's ACCEPTED but never applies surfaces in
    restore_failures (operator-visible) instead of leaving the set silently
    armed, where the next playback could record clip envelopes."""
    ctx = FakeCtx()
    ctx.song.sar_disarm_never_applies = True
    result = _one(
        ctx, target_kind="mixer_volume", master=True,
        breakpoints=[_bp(0.0, 0.5), _bp(2.0, 0.9)],
        settle_timeout_ms=20,
    )
    assert any("session_automation_record_settle" in f
               for f in result.get("restore_failures", [])), result


def test_perform_batch_pins_authored_final_value_before_close():
    """ENV-8K2R #2: a normal (ramped) arc records its AUTHORED final breakpoint
    value — the last value SET before end_gesture equals the endpoint, so the
    recorded lane isn't left up to ~0.8 beat short of the authored final."""
    ctx = FakeCtx()
    param = ctx.song.master_track.mixer_device.volume
    final_value = 0.137
    _one(
        ctx, target_kind="mixer_volume", master=True,
        breakpoints=[_bp(0.0, 0.9), _bp(8.0, final_value)],
    )
    # The exact endpoint is pinned immediately before the gesture closes.
    assert param.own[-1] == ("end",)
    assert param.own[-2] == ("set", round(final_value, 6))


def test_perform_batch_exception_path_surfaces_armed_set():
    """When the pass raises AND a restore step ALSO fails (set may be left
    armed), the propagating wire error must carry the armed-set pointer — the
    result dict that surfaces restore_failures on the success path is never
    built on the exception path."""
    ctx = FakeCtx()
    ctx.song.master_track.mixer_device.volume.raise_on_set_after = 1  # ramp raises

    def _raising_stop() -> None:
        raise RuntimeError("stop failed")

    ctx.song.stop_playing = _raising_stop  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="may be left ARMED"):
        _one(
            ctx, target_kind="mixer_volume", master=True,
            breakpoints=[_bp(0.0, 0.5), _bp(8.0, 0.9)],
        )


def test_perform_restore_attempts_every_step_when_one_fails():
    ctx = FakeCtx()

    def _raising_stop() -> None:
        raise RuntimeError("stop failed")

    ctx.song.stop_playing = _raising_stop  # type: ignore[method-assign]
    result = _one(
        ctx, target_kind="mixer_volume", master=True,
        breakpoints=[_bp(0.0, 0.5), _bp(2.0, 0.9)],
    )
    # stop failed, but the disarm writes still happened…
    assert ("record_mode", False) in ctx.events
    assert ("session_automation_record", False) in ctx.events
    # …and the failure is surfaced, not swallowed.
    assert any("stop_playing" in f for f in result["restore_failures"])


# ---------------------------------------------------------------------------
# record_mode settle-poll (probe 10)
# ---------------------------------------------------------------------------


def test_perform_waits_for_async_record_mode_apply():
    ctx = FakeCtx()
    ctx.song.record_mode_apply_after_reads = 3  # OLD value for 3 reads
    result = _one(
        ctx, target_kind="mixer_volume", master=True,
        breakpoints=[_bp(0.0, 0.5), _bp(2.0, 0.9)],
    )
    # The gesture began only after record_mode actually applied.
    assert _arc0(result)["automation_state"] == 1
    assert ("begin_gesture",) in ctx.events


def test_perform_times_out_when_record_mode_never_applies_and_restores():
    ctx = FakeCtx()
    # Pending never applies: simulate an unbounded apply delay.
    ctx.song.record_mode_apply_after_reads = 10**9

    with pytest.raises(TimeoutError, match="record_mode"):
        _one(
            ctx, target_kind="mixer_volume", master=True,
            breakpoints=[_bp(0.0, 0.5), _bp(2.0, 0.9)],
            settle_timeout_ms=20,
        )

    # No gesture ever opened; the set was still disarmed + restored.
    assert ("begin_gesture",) not in ctx.events
    assert ("end_gesture",) not in ctx.events
    assert ("record_mode", False) in ctx.events
    assert ("session_automation_record", False) in ctx.events


# ---------------------------------------------------------------------------
# Breakpoint interpolation (unchanged — _interp_performed_value is reused)
# ---------------------------------------------------------------------------


def _cleaned(*bps: dict[str, Any]) -> list[dict[str, Any]]:
    return _validate_breakpoints(list(bps))


def test_interp_linear_default():
    bps = _cleaned(_bp(0.0, 0.0), _bp(4.0, 1.0))
    assert _interp_performed_value(bps, 1.0) == pytest.approx(0.25)
    assert _interp_performed_value(bps, 2.0) == pytest.approx(0.5)
    assert _interp_performed_value(bps, 3.0) == pytest.approx(0.75)


def test_interp_holds_outside_range():
    bps = _cleaned(_bp(2.0, 0.3), _bp(4.0, 0.8))
    assert _interp_performed_value(bps, 0.0) == pytest.approx(0.3)
    assert _interp_performed_value(bps, 99.0) == pytest.approx(0.8)


def test_interp_hold_curve_keeps_previous_value():
    bps = _cleaned(_bp(0.0, 0.2, "hold"), _bp(4.0, 1.0))
    assert _interp_performed_value(bps, 3.999) == pytest.approx(0.2)
    assert _interp_performed_value(bps, 4.0) == pytest.approx(1.0)


def test_interp_fast_curve_front_loads_change():
    bps = _cleaned(_bp(0.0, 0.0, "fast"), _bp(4.0, 1.0))
    midpoint = _interp_performed_value(bps, 2.0)
    assert midpoint > 0.5  # 1-(1-t)^2 at t=0.5 → 0.75
    assert midpoint == pytest.approx(0.75)


def test_interp_slow_curve_back_loads_change():
    bps = _cleaned(_bp(0.0, 0.0, "slow"), _bp(4.0, 1.0))
    midpoint = _interp_performed_value(bps, 2.0)
    assert midpoint < 0.5  # t^2 at t=0.5 → 0.25
    assert midpoint == pytest.approx(0.25)


def test_interp_multi_segment_uses_departure_curve_per_segment():
    bps = _cleaned(
        _bp(0.0, 0.0), _bp(2.0, 1.0, "hold"), _bp(4.0, 0.0),
    )
    assert _interp_performed_value(bps, 1.0) == pytest.approx(0.5)  # linear
    assert _interp_performed_value(bps, 3.0) == pytest.approx(1.0)  # hold
    assert _interp_performed_value(bps, 4.0) == pytest.approx(0.0)


def test_interp_exact_breakpoint_times():
    bps = _cleaned(_bp(0.0, 0.1), _bp(2.0, 0.5), _bp(4.0, 0.9))
    assert _interp_performed_value(bps, 0.0) == pytest.approx(0.1)
    assert _interp_performed_value(bps, 2.0) == pytest.approx(0.5)
    assert _interp_performed_value(bps, 4.0) == pytest.approx(0.9)


# ---------------------------------------------------------------------------
# Param / batch validation
# ---------------------------------------------------------------------------


def test_perform_rejects_empty_batch():
    ctx = FakeCtx()
    with pytest.raises(ValueError, match="non-empty 'arcs'"):
        perform_batch_handler(ctx, arcs=[])
    # No transport state was touched.
    assert ctx.events == []


def test_perform_rejects_clip_hosted_target_kinds():
    ctx = FakeCtx()
    with pytest.raises(ValueError, match="write_envelope"):
        _one(ctx, target_kind="clip_cc", breakpoints=[_bp(0.0, 0.5)])


def test_perform_requires_exactly_one_parent():
    ctx = FakeCtx()
    with pytest.raises(ValueError, match="exactly one of"):
        _one(
            ctx, target_kind="mixer_volume", master=True, track_index=1,
            breakpoints=[_bp(0.0, 0.5), _bp(2.0, 0.9)],
        )
    with pytest.raises(ValueError, match="exactly one of"):
        _one(
            ctx, target_kind="mixer_pan",
            breakpoints=[_bp(0.0, 0.5), _bp(2.0, 0.9)],
        )
    # No transport state was touched by addressing failures.
    assert ctx.events == []


def test_perform_send_level_refuses_master_and_requires_both_indices():
    ctx = FakeCtx()
    with pytest.raises(ValueError, match="no sends"):
        _one(
            ctx, target_kind="send_level", master=True,
            breakpoints=[_bp(0.0, 0.5), _bp(2.0, 0.9)],
        )
    with pytest.raises(ValueError, match="track_index"):
        _one(
            ctx, target_kind="send_level", return_index=1,
            breakpoints=[_bp(0.0, 0.5), _bp(2.0, 0.9)],
        )


def test_perform_device_parameter_requires_device_and_name():
    ctx = FakeCtx()
    with pytest.raises(ValueError, match="device_index and parameter_name"):
        _one(
            ctx, target_kind="device_parameter", master=True,
            breakpoints=[_bp(0.0, 0.5), _bp(2.0, 0.9)],
        )


def test_perform_device_parameter_on_master_chain():
    ctx = FakeCtx()
    cutoff = FakeNamedParam(ctx.events, "Frequency")
    ctx.song.master_track.devices = [FakeDevice([cutoff])]
    result = _one(
        ctx, target_kind="device_parameter", master=True,
        device_index=1, parameter_name="Frequency",
        breakpoints=[_bp(0.0, 0.2), _bp(2.0, 0.9)],
    )
    arc = _arc0(result)
    assert arc["automation_state"] == 1
    assert any(e[0] == "set_value" for e in ctx.events)
    assert arc["parameter_name"] == "Frequency"


def test_perform_on_return_track_mixer():
    ctx = FakeCtx()
    result = _one(
        ctx, target_kind="mixer_volume", return_index=1,
        breakpoints=[_bp(0.0, 0.2), _bp(2.0, 0.9)],
    )
    arc = _arc0(result)
    assert arc["automation_state"] == 1
    assert arc["return_index"] == 1


def test_perform_send_level_on_track():
    ctx = FakeCtx()
    send = FakeGestureParam(ctx.events)
    ctx.song.tracks[0].mixer_device.sends = [send]
    result = _one(
        ctx, target_kind="send_level", track_index=1, return_index=1,
        breakpoints=[_bp(0.0, 0.0), _bp(2.0, 0.7)],
    )
    assert _arc0(result)["automation_state"] == 1
    assert send.automation_state == 1


def test_perform_echoes_arc_id_for_caller_correlation():
    ctx = FakeCtx()
    result = _one(
        ctx, arc_id="env-42", target_kind="mixer_volume", master=True,
        breakpoints=[_bp(0.0, 0.5), _bp(2.0, 0.9)],
    )
    assert _arc0(result)["arc_id"] == "env-42"


def test_perform_rejects_empty_span():
    ctx = FakeCtx()
    with pytest.raises(ValueError, match="span is empty"):
        _one(
            ctx, target_kind="mixer_volume", master=True,
            breakpoints=[_bp(4.0, 0.5)],  # single bp → zero-length span
        )


def test_perform_rejects_unsorted_breakpoints():
    ctx = FakeCtx()
    with pytest.raises(ValueError, match="sorted"):
        _one(
            ctx, target_kind="mixer_volume", master=True,
            breakpoints=[_bp(4.0, 0.5), _bp(0.0, 0.9)],
        )


def test_perform_rejects_nonpositive_settle_timeout():
    ctx = FakeCtx()
    with pytest.raises(ValueError, match="settle_timeout_ms"):
        _one(
            ctx, target_kind="mixer_volume", master=True,
            breakpoints=[_bp(0.0, 0.5), _bp(2.0, 0.9)],
            settle_timeout_ms=0,
        )


# ---------------------------------------------------------------------------
# Wire-path regression (the registered action must round-trip through the
# dispatcher, not just the bare handler)
# ---------------------------------------------------------------------------


@pytest.fixture()
def loaded_actions():
    with isolated_actions():
        yield schema


def test_perform_batch_dispatches_through_wire(loaded_actions):
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_automation",
            action="perform_batch",
            params={
                "arcs": [
                    {
                        "arc_id": "e1",
                        "target_kind": "mixer_volume",
                        "master": True,
                        "breakpoints": [
                            {"time_beats": 0.0, "value": 0.5},
                            {"time_beats": 2.0, "value": 0.9, "curve": "slow"},
                        ],
                    },
                ],
            },
        ),
        context=ctx,
    )
    assert resp.ok is True
    arc = resp.result["arcs"][0]
    assert arc["automation_state"] == 1
    assert arc["target_kind"] == "mixer_volume"
    assert arc["arc_id"] == "e1"
    assert ("begin_gesture",) in ctx.events


def test_perform_batch_registered_runs_on_worker(loaded_actions):
    action = schema.get("ableton_automation", "perform_batch")
    assert action is not None
    assert action.runs_on_worker is True


def test_perform_batch_wire_validation_rejects_bad_target_kind(loaded_actions):
    resp = dispatch(
        Request(
            tool="ableton_automation",
            action="perform_batch",
            params={
                "arcs": [
                    {
                        "target_kind": "clip_cc",
                        "breakpoints": [{"time_beats": 0.0, "value": 0.5}],
                    },
                ],
            },
        ),
        context=FakeCtx(),
    )
    assert resp.ok is False
    assert "target_kind" in resp.error.lower() or "clip_cc" in resp.error


# ---------------------------------------------------------------------------
# ENV-8K2R #7 — addressing dedup. ``_require_parent`` gained an opt-in master
# branch (so ``_resolve_perform_target`` delegates its parent resolution there
# instead of duplicating the return-bounds block), and ``_resolve_send`` is the
# single home for the send_level bounds check shared by all four envelope paths.
# ---------------------------------------------------------------------------


def test_require_parent_master_returns_master_track():
    ctx = FakeCtx()
    assert (
        _require_parent(ctx, master=True, track_index=None, return_index=None)
        is ctx.song.master_track
    )


def test_require_parent_rejects_master_combined_with_track_or_return():
    ctx = FakeCtx()
    with pytest.raises(ValueError, match="exactly one"):
        _require_parent(ctx, master=True, track_index=1, return_index=None)
    with pytest.raises(ValueError, match="exactly one"):
        _require_parent(ctx, master=True, track_index=None, return_index=1)


def test_require_parent_non_master_paths_unchanged():
    ctx = FakeCtx()
    assert (
        _require_parent(ctx, track_index=1, return_index=None)
        is ctx.song.tracks[0]
    )
    assert (
        _require_parent(ctx, track_index=None, return_index=1)
        is ctx.song.return_tracks[0]
    )
    with pytest.raises(ValueError, match="not both"):
        _require_parent(ctx, track_index=1, return_index=1)


def test_resolve_send_resolves_and_bounds_check():
    events: list[tuple] = []
    track = FakeTrack(events)
    send = FakeGestureParam(events)
    track.mixer_device.sends = [send]
    assert _resolve_send(track, track_index=2, return_index=1) is send
    # 1-based: index 0 and index past the end both out of range, same message.
    with pytest.raises(IndexError, match="out of range"):
        _resolve_send(track, track_index=2, return_index=2)
    with pytest.raises(IndexError, match="out of range"):
        _resolve_send(track, track_index=2, return_index=0)
