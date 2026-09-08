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
from hallucinote_mcp.handlers._transport import PlayheadPositionError
from hallucinote_mcp.handlers.automation import (
    _describe_perform_stall,
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


class _FakeRackChain:
    def __init__(self, name: str, devices: list[Any]):
        self.name = name
        self.devices = devices


class _FakeRackDevice:
    """A rack device — has `chains` so `_resolve_device_path` can descend
    (DEEP-RACK-ADDR). Carries no parameters of its own."""

    def __init__(self, chains: list[_FakeRackChain]):
        self.parameters: list[Any] = []
        self.chains = chains


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

    def __init__(self, events: list[tuple], clock: Any = None):
        self._events = events
        self._clock = clock
        self._tempo = 120.0
        # PSH-3H8M: loop / punch transport flags the pre-perform reset clears and
        # the finally restores. Event-logged (like tempo) so a test can observe
        # the clear-then-restore round-trip.
        self._loop = False
        self._punch_in = False
        self._punch_out = False
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
        # PSH-4L6C: `current_song_time = x` is an async LOCATE — the set is
        # accepted but the playhead only ARRIVES `locate_apply_after_reads`
        # reads later (the same async-apply shape record_mode already has).
        # `locate_never_applies` simulates a locate Live silently drops;
        # `locate_offset` simulates Live parking the playhead a fraction of a
        # beat off the requested position.
        self.locate_apply_after_reads = 0
        self.locate_never_applies = False
        self.locate_offset = 0.0
        self._locate_pending: float | None = None
        self._locate_reads_until_apply = 0
        # Transport state the timeout diagnostics read (Live LOM surface).
        self.count_in_duration = 0
        # The playhead position observed at the moment start_playing() fired —
        # the ramp must never begin sampling before the span start.
        self.song_time_at_play: float | None = None

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

    # -- current_song_time: async locate, advances while playing --------
    @property
    def current_song_time(self) -> float:
        if self._locate_pending is not None:
            if self._locate_reads_until_apply <= 0:
                self._song_time = self._locate_pending + self.locate_offset
                self._locate_pending = None
            else:
                self._locate_reads_until_apply -= 1
        t = self._song_time
        if self.is_playing:
            self._song_time += self.beats_per_read
            if self._clock is not None and self.beats_per_read:
                # Virtual realtime: playhead travel costs wall-clock at the
                # current tempo, so a wall-clock budget maps onto beats.
                self._clock.advance(
                    self.beats_per_read / (self._tempo / 60.0)
                )
        return t

    @current_song_time.setter
    def current_song_time(self, v: float) -> None:
        self._events.append(("seek", float(v)))
        if self.locate_never_applies:
            self._locate_pending = None
            return
        if self.locate_apply_after_reads <= 0:
            self._song_time = float(v) + self.locate_offset
            self._locate_pending = None
            return
        self._locate_pending = float(v)
        self._locate_reads_until_apply = self.locate_apply_after_reads

    # -- tempo: event-logged so ENV-2T9K's slow-down + restore is observable --
    @property
    def tempo(self) -> float:
        return self._tempo

    @tempo.setter
    def tempo(self, v: float) -> None:
        self._events.append(("tempo", round(float(v), 3)))
        self._tempo = float(v)

    # -- loop / punch: event-logged so PSH-3H8M clear+restore is observable --
    @property
    def loop(self) -> bool:
        return self._loop

    @loop.setter
    def loop(self, v: bool) -> None:
        self._events.append(("loop", bool(v)))
        self._loop = bool(v)

    @property
    def punch_in(self) -> bool:
        return self._punch_in

    @punch_in.setter
    def punch_in(self, v: bool) -> None:
        self._events.append(("punch_in", bool(v)))
        self._punch_in = bool(v)

    @property
    def punch_out(self) -> bool:
        return self._punch_out

    @punch_out.setter
    def punch_out(self, v: bool) -> None:
        self._events.append(("punch_out", bool(v)))
        self._punch_out = bool(v)

    def start_playing(self) -> None:
        self._events.append(("play",))
        # PSH-4L6C: an in-flight locate is LOST once the transport starts —
        # playback proceeds from wherever the playhead actually is. This is the
        # modelled shape of the live failure (transport rolled, start sounded
        # "weird", the span end was never reached in a budget 3.5x the span);
        # whether Live drops the locate or the setter is ignored while arming
        # is in flight, the observable is the same. See
        # .prawduct/operator-verification.md — the mechanism is inferred from
        # the symptom, not confirmed against a live instance.
        self._locate_pending = None
        self.song_time_at_play = self._song_time
        self.is_playing = True

    def stop_playing(self) -> None:
        self._events.append(("stop",))
        self.is_playing = False

    def re_enable_automation(self) -> None:
        self._events.append(("re_enable_automation",))
        self.re_enable_automation_calls += 1


class _VirtualClock:
    """A stand-in for the ``time`` module inside the handler (monkeypatched as
    ``automation_handlers.time``) whose ``monotonic`` only advances when the
    SIMULATED transport travels — see ``FakePerformSong.current_song_time``.

    That makes the ramp's wall-clock budget a deterministic function of beats
    travelled, so "did this pass fit in its budget?" is testable without real
    sleeping."""

    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += float(seconds)

    def advance(self, seconds: float) -> None:
        self.now += float(seconds)


class FakeCtx:
    def __init__(self, clock: Any = None):
        self.events: list[tuple] = []
        self._song = FakePerformSong(self.events, clock=clock)
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

    def run_on_main(self, fn, **_kwargs):
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


def _one(ctx, *, settle_timeout_ms: int | None = None,
         slowdown_factor: float | None = None, **arc_fields):
    """Run perform_batch with a single arc; returns the full batched
    result (the arc is ``result["arcs"][0]``)."""
    kwargs: dict[str, Any] = {}
    if settle_timeout_ms is not None:
        kwargs["settle_timeout_ms"] = settle_timeout_ms
    if slowdown_factor is not None:
        kwargs["slowdown_factor"] = slowdown_factor
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


# ---------------------------------------------------------------------------
# PSH-4L6C — the async LOCATE race (settle the seek before playing)
# ---------------------------------------------------------------------------


def _far_arc() -> dict[str, Any]:
    """The motivating failure's arc: 8 beats at 96..104, parked far from a
    playhead sitting at 0."""
    return {
        "target_kind": "mixer_volume", "master": True,
        "breakpoints": [_bp(96.0, 0.2), _bp(104.0, 0.9)],
    }


def test_perform_batch_waits_for_late_locate_before_starting_transport():
    """PSH-4L6C: ``current_song_time = x`` is an ASYNC locate. The transport
    must not start — and so the ramp must not begin sampling — until the
    playhead has ACTUALLY arrived at the span start. Otherwise the pass rolls
    from the old position (audibly wrong at the start) and the ramp measures
    from the wrong beat."""
    ctx = FakeCtx()
    song = ctx.song
    song._song_time = 0.0            # playhead parked far from the span
    song.locate_apply_after_reads = 4  # the locate lands 4 reads late

    result = perform_batch_handler(ctx, arcs=[_far_arc()])

    # The transport started only once the playhead had arrived at the span
    # start — never from the stale position.
    assert song.song_time_at_play == pytest.approx(96.0)
    # And the initial gesture opened BEFORE play, which is only possible when
    # the observed beat already reads >= the span start.
    assert ctx.events.index(("begin_gesture",)) < ctx.events.index(("play",))
    assert _arc0(result)["automation_state"] == 1


def test_perform_batch_late_locate_does_not_spuriously_time_out(monkeypatch):
    """The motivating live failure: an 8-beat arc at 96..104 (3.4 s of travel)
    timing out against a budget ~3.5x that. Rolling from an un-located playhead
    turns an 8-beat journey into a 104-beat one, which no span-proportional
    budget can cover. Waiting for the locate keeps the pass inside its budget.

    The clock is virtual and advances ONLY with playhead travel, so this asserts
    beats-travelled, not real seconds."""
    clock = _VirtualClock()
    monkeypatch.setattr(automation_handlers, "time", clock)
    ctx = FakeCtx(clock=clock)
    ctx.song._song_time = 0.0
    ctx.song.locate_apply_after_reads = 4

    result = perform_batch_handler(ctx, arcs=[_far_arc()])

    assert _arc0(result)["automation_state"] == 1
    # 8 beats @120 BPM = 4 virtual seconds of transport travel. The budget is
    # max(4 * 3.0, 10.0) + 2.0 settle = 14 s; rolling from beat 0 would have
    # cost 52 s. Anything near the 8-beat cost proves the locate was honoured.
    assert clock.now < 14.0


def test_perform_batch_unsettled_locate_fails_clean_without_playing():
    """A locate Live never applies aborts AT THE SETTLE BOUNDARY, naming the
    playhead — instead of starting the transport from the wrong position and
    burning the whole ramp budget on a journey nobody budgeted for. The
    transport is never started, and the set is still disarmed + restored."""
    ctx = FakeCtx()
    ctx.song._song_time = 0.0
    ctx.song.locate_never_applies = True

    with pytest.raises(TimeoutError, match="could not locate the playhead"):
        perform_batch_handler(
            ctx, arcs=[_far_arc()], settle_timeout_ms=20
        )

    assert ("play",) not in ctx.events
    assert ctx.song.is_playing is False
    assert ("record_mode", False) in ctx.events
    assert ("session_automation_record", False) in ctx.events


def test_perform_batch_unsettled_locate_names_target_and_observed():
    """The abort teaches: it names where the playhead was ASKED to go and where
    it actually reads, so the operator is not left guessing."""
    ctx = FakeCtx()
    ctx.song._song_time = 12.0
    ctx.song.locate_never_applies = True

    with pytest.raises(TimeoutError) as exc:
        perform_batch_handler(ctx, arcs=[_far_arc()], settle_timeout_ms=20)

    msg = str(exc.value)
    assert "beat 96" in msg
    assert "12.000" in msg
    assert "asynchronously" in msg


def test_perform_batch_tolerates_sub_beat_locate_residual():
    """Live need not park the playhead on the exact requested float. A SUB-BEAT
    residual is harmless — the ramp is beat-space interpolated off the ACTUAL
    playhead — so the settle gate must not reject it. The gate exists for a
    locate that has not landed at all, not for grid snapping."""
    ctx = FakeCtx()
    ctx.song.locate_offset = 0.25  # Live parks a quarter-beat off

    result = _one(
        ctx, target_kind="mixer_volume", master=True,
        breakpoints=[_bp(0.0, 0.5), _bp(8.0, 0.9)],
    )

    assert _arc0(result)["automation_state"] == 1
    assert ctx.song.song_time_at_play == pytest.approx(0.25)


# ---------------------------------------------------------------------------
# PSH-4L6C — the ramp timeout reports what it OBSERVED
# ---------------------------------------------------------------------------


def test_ramp_timeout_reports_observed_transport_state(monkeypatch):
    """The old message asserted "modal dialog, count-in" as the likely causes.
    In the failure that motivated PSH-4L6C both were provably absent
    (loop False, count_in_duration 0), so it sent the operator looking at the
    wrong things. The message must now report what it actually READ."""
    monkeypatch.setattr(automation_handlers, "_PERFORM_WALL_CLOCK_FLOOR_S", 0.0)
    monkeypatch.setattr(automation_handlers, "_PERFORM_WALL_CLOCK_FACTOR", 0.0)
    ctx = FakeCtx()
    ctx.song.beats_per_read = 0.0  # rolling but never advancing

    with pytest.raises(TimeoutError) as exc:
        _one(
            ctx, target_kind="mixer_volume", master=True,
            breakpoints=[_bp(0.0, 0.5), _bp(8.0, 0.9)], settle_timeout_ms=20,
        )

    msg = str(exc.value)
    assert "observed at give-up" in msg
    assert "playhead beat" in msg
    assert "transport rolling=True" in msg
    assert "loop=False" in msg
    assert "count_in_duration=0" in msg
    # No longer asserts causes it did not observe.
    assert "blocked (modal dialog, count-in)" not in msg


def test_ramp_timeout_diagnostics_survive_an_unreadable_song(monkeypatch):
    """A diagnostic read that blows up must never mask the timeout it was
    called to describe."""
    monkeypatch.setattr(automation_handlers, "_PERFORM_WALL_CLOCK_FLOOR_S", 0.0)
    monkeypatch.setattr(automation_handlers, "_PERFORM_WALL_CLOCK_FACTOR", 0.0)
    ctx = FakeCtx()
    ctx.song.beats_per_read = 0.0
    calls = {"n": 0}
    real_run = ctx.run_on_main

    def _explode_on_diagnostics(fn, **kw):
        # The diagnostics bout is the one taken after the deadline trips.
        if getattr(fn, "__name__", "") == "_read":
            calls["n"] += 1
            raise RuntimeError("Live went away")
        return real_run(fn, **kw)

    monkeypatch.setattr(ctx, "run_on_main", _explode_on_diagnostics)

    with pytest.raises(TimeoutError, match="union span end"):
        _one(
            ctx, target_kind="mixer_volume", master=True,
            breakpoints=[_bp(0.0, 0.5), _bp(8.0, 0.9)], settle_timeout_ms=20,
        )
    assert calls["n"] == 1


@pytest.mark.parametrize("diag,expected", [
    (
        {"beat": 3.0, "is_playing": True, "loop": False,
         "count_in_duration": 0, "tempo": 140.0},
        "BEHIND the span start",
    ),
    (
        {"beat": 99.0, "is_playing": False, "loop": False,
         "count_in_duration": 0, "tempo": 140.0},
        "NOT rolling",
    ),
    (
        {"beat": 99.0, "is_playing": True, "loop": True,
         "count_in_duration": 0, "tempo": 140.0},
        "ACTIVE loop",
    ),
    (
        {"beat": 99.0, "is_playing": True, "loop": False,
         "count_in_duration": 2, "tempo": 140.0},
        "count-in",
    ),
    (
        {"beat": 99.0, "is_playing": True, "loop": False,
         "count_in_duration": 0, "tempo": 140.0},
        "just too",
    ),
    (
        {"beat": None, "is_playing": True, "loop": None,
         "count_in_duration": None, "tempo": None},
        "could not be read",
    ),
])
def test_describe_perform_stall_reads_the_evidence(diag, expected):
    """Each observed transport state yields the ONE reading that follows from
    it — never a list of causes the evidence rules out."""
    text = _describe_perform_stall(diag, union_start=96.0, union_end=104.0)
    assert expected in text
    # Always carries the raw observation alongside the interpretation.
    assert "observed at give-up" in text


# ---------------------------------------------------------------------------
# PSH-3H8M — fast non-advancement watchdog + loop/punch pre-perform reset
# ---------------------------------------------------------------------------


def test_perform_batch_stall_watchdog_aborts_fast(monkeypatch):
    """A frozen playhead trips the fast non-advancement watchdog — aborting with
    the stuck beat named, WITHOUT waiting out the span-proportional wall-clock
    ceiling. Keeping the ceiling far away proves the WATCHDOG is what fires."""
    monkeypatch.setattr(automation_handlers, "_PERFORM_STALL_TIMEOUT_S", 0.0)
    monkeypatch.setattr(
        automation_handlers, "_PERFORM_WALL_CLOCK_FLOOR_S", 600.0
    )
    ctx = FakeCtx()
    ctx.song.beats_per_read = 0.0  # playhead frozen → never advances
    with pytest.raises(TimeoutError, match="stopped advancing at beat"):
        _one(
            ctx, target_kind="mixer_volume", master=True,
            breakpoints=[_bp(0.0, 0.5), _bp(4.0, 0.9)],
        )
    # The finally still ran: disarmed + transport stopped.
    assert ("record_mode", False) in ctx.events
    assert ctx.song.is_playing is False


def test_perform_batch_stall_watchdog_no_false_positive_while_advancing(
    monkeypatch,
):
    """An advancing playhead never trips the watchdog — even at a 0 s threshold,
    every read resets the stall clock, so only a truly frozen transport aborts."""
    monkeypatch.setattr(automation_handlers, "_PERFORM_STALL_TIMEOUT_S", 0.0)
    ctx = FakeCtx()
    ctx.song.beats_per_read = 1.0  # advances every read → completes normally
    result = _one(
        ctx, target_kind="mixer_volume", master=True,
        breakpoints=[_bp(0.0, 0.5), _bp(4.0, 0.9)],
    )
    assert _arc0(result)["automation_state"] == 1  # finished, no TimeoutError


def test_perform_batch_clears_and_restores_loop_punch():
    """A user-left loop / punch region is cleared BEFORE the perform (so it can't
    trap the playhead in a sub-span) and restored to its prior state AFTER."""
    ctx = FakeCtx()
    ctx.song.loop = True
    ctx.song.punch_in = True
    ctx.song.punch_out = True
    ctx.events.clear()  # drop the setup writes

    _one(
        ctx, target_kind="mixer_volume", master=True,
        breakpoints=[_bp(0.0, 0.5), _bp(4.0, 0.9)],
    )

    # Cleared during the pre-perform reset (before play), restored in finally.
    play_idx = ctx.events.index(("play",))
    assert ctx.events.index(("loop", False)) < play_idx
    assert ctx.events.index(("punch_in", False)) < play_idx
    assert ctx.events.index(("punch_out", False)) < play_idx
    assert ctx.events.index(("loop", True)) > play_idx
    # Final live state restored to the user's prior loop/punch.
    assert ctx.song.loop is True
    assert ctx.song.punch_in is True
    assert ctx.song.punch_out is True


def test_perform_batch_leaves_clean_transport_untouched():
    """A set with loop / punch already OFF logs no loop/punch churn — the reset
    only writes a flag it actually has to clear."""
    ctx = FakeCtx()  # loop / punch default False
    _one(
        ctx, target_kind="mixer_volume", master=True,
        breakpoints=[_bp(0.0, 0.5), _bp(4.0, 0.9)],
    )
    assert not any(
        e[0] in ("loop", "punch_in", "punch_out") for e in ctx.events
    )


def test_perform_batch_restores_loop_punch_on_abort(monkeypatch):
    """The loop / punch restore rides the finally — even when the perform aborts
    (watchdog), the user's transport flags are put back."""
    monkeypatch.setattr(automation_handlers, "_PERFORM_STALL_TIMEOUT_S", 0.0)
    ctx = FakeCtx()
    ctx.song.loop = True
    ctx.song.beats_per_read = 0.0  # frozen → watchdog aborts
    with pytest.raises(TimeoutError, match="stopped advancing"):
        _one(
            ctx, target_kind="mixer_volume", master=True,
            breakpoints=[_bp(0.0, 0.5), _bp(4.0, 0.9)],
        )
    assert ctx.song.loop is True  # restored despite the abort


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


def test_perform_batch_slows_tempo_during_record_and_restores():
    """ENV-2T9K: slowdown_factor lowers the transport tempo for the record pass
    (the lever for more breakpoints per beat at the fixed tick rate) and restores
    the original after — the slowdown is a recording-time trick, gone from the
    final set. (The density GAIN itself is a Live-only outcome; here we pin the
    mechanism: the tempo is set low, then restored.)"""
    ctx = FakeCtx()
    result = _one(
        ctx, target_kind="mixer_volume", master=True,
        breakpoints=[_bp(0.0, 0.5), _bp(4.0, 0.9)],
        slowdown_factor=4.0,
    )
    assert result["slowdown_factor"] == 4.0
    assert result["record_tempo"] == 30.0  # 120 / 4
    # Reduced tempo set during arm, original restored after the pass.
    tempo_sets = [e[1] for e in ctx.events if e[0] == "tempo"]
    assert tempo_sets == [30.0, 120.0]
    assert ctx.song.tempo == 120.0
    # The tempo drop happens BEFORE arming so the whole pass runs slowed.
    assert ctx.events.index(("tempo", 30.0)) < ctx.events.index(
        ("session_automation_record", True)
    )


def test_perform_batch_floors_reduced_tempo_at_live_minimum():
    """A large factor can't drive the transport below Live's minimum tempo."""
    ctx = FakeCtx()  # default 120 BPM
    result = _one(
        ctx, target_kind="mixer_volume", master=True,
        breakpoints=[_bp(0.0, 0.5), _bp(4.0, 0.9)],
        slowdown_factor=100.0,  # 120/100 = 1.2 BPM → floored
    )
    assert result["record_tempo"] == 20.0  # _PERFORM_MIN_RECORD_TEMPO_BPM


def test_perform_batch_default_factor_does_not_touch_tempo():
    """slowdown_factor defaults to off — no tempo event, no record-tempo change."""
    ctx = FakeCtx()
    result = _one(
        ctx, target_kind="mixer_volume", master=True,
        breakpoints=[_bp(0.0, 0.5), _bp(4.0, 0.9)],
    )
    assert result["slowdown_factor"] == 1.0
    assert result["record_tempo"] == 120.0
    assert not any(name == "tempo" for (name, *_rest) in ctx.events)


def test_perform_batch_rejects_factor_below_one():
    ctx = FakeCtx()
    with pytest.raises(ValueError, match="slowdown_factor"):
        _one(
            ctx, target_kind="mixer_volume", master=True,
            breakpoints=[_bp(0.0, 0.5), _bp(4.0, 0.9)],
            slowdown_factor=0.5,
        )


def test_perform_batch_restores_tempo_even_when_pass_raises():
    """ENV-2T9K: the tempo restore lives in the finally, so a ramp that raises
    mid-pass still leaves the original tempo (no slowed set left behind)."""
    ctx = FakeCtx()
    ctx.song.master_track.mixer_device.volume.raise_on_set_after = 1  # ramp raises

    def _raising_stop() -> None:
        raise RuntimeError("stop failed")

    ctx.song.stop_playing = _raising_stop  # type: ignore[method-assign]
    with pytest.raises(RuntimeError):
        _one(
            ctx, target_kind="mixer_volume", master=True,
            breakpoints=[_bp(0.0, 0.5), _bp(8.0, 0.9)],
            slowdown_factor=4.0,
        )
    # Despite the raise, the tempo was restored to the original.
    assert ctx.song.tempo == 120.0
    assert ("tempo", 120.0) in ctx.events


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


def test_perform_device_parameter_requires_parameter_name():
    # NODE-ADDR: device_index is now structural inside `node` (its absence is
    # caught by validate_node_addr — see test_node_addr.py), so this pins the
    # remaining parameter_name requirement via the downstream combined check.
    ctx = FakeCtx()
    with pytest.raises(ValueError, match="device_index and parameter_name"):
        _one(
            ctx, target_kind="device_parameter",
            node={"parent": {"kind": "master"}, "device_index": 1},
            breakpoints=[_bp(0.0, 0.5), _bp(2.0, 0.9)],
        )


def test_perform_device_parameter_on_master_chain():
    ctx = FakeCtx()
    cutoff = FakeNamedParam(ctx.events, "Frequency")
    ctx.song.master_track.devices = [FakeDevice([cutoff])]
    result = _one(
        ctx, target_kind="device_parameter",
        node={"parent": {"kind": "master"}, "device_index": 1},
        parameter_name="Frequency",
        breakpoints=[_bp(0.0, 0.2), _bp(2.0, 0.9)],
    )
    arc = _arc0(result)
    assert arc["automation_state"] == 1
    assert any(e[0] == "set_value" for e in ctx.events)
    assert arc["parameter_name"] == "Frequency"


def test_perform_device_parameter_nested_via_device_path():
    """DEEP-RACK-ADDR: perform_batch rides a param on a device NESTED inside a
    rack, addressed by device_index + device_path. The gesture surface reaches
    nested params directly (unlike the session-clip route, which Live gates)."""
    ctx = FakeCtx()
    nested_param = FakeNamedParam(ctx.events, "Volume")
    rack = _FakeRackDevice([_FakeRackChain("Inner", [FakeDevice([nested_param])])])
    ctx.song.master_track.devices = [rack]
    result = _one(
        ctx, target_kind="device_parameter",
        node={
            "parent": {"kind": "master"},
            "device_index": 1,
            "path": [{"chain_index": 1, "device_position": 1}],
        },
        parameter_name="Volume",
        breakpoints=[_bp(0.0, 0.2), _bp(2.0, 0.9)],
    )
    arc = _arc0(result)
    assert arc["automation_state"] == 1
    assert arc["parameter_name"] == "Volume"
    assert arc["device_path"] == [{"chain_index": 1, "device_position": 1}]
    # The gesture rode the NESTED param (begin/set/end recorded on it).
    assert nested_param.own and nested_param.own[0] == ("begin",)


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


# ---------------------------------------------------------------------------
# #471 — the START PLAYING POSITION is not the playhead
# ---------------------------------------------------------------------------


class _JumpableCue:
    """A Live CuePoint. ``jump()`` is the only surface that moves the start
    playing position, which is the whole reason a locate is a cue jump."""

    def __init__(self, song: "FakeStartPositionSong", time_: float):
        self._song = song
        self.time = float(time_)
        self.name = ""

    def jump(self) -> None:
        self._song.cue_events.append(("cue_jump", round(self.time, 6)))
        self._song._start_position = self.time
        self._song._song_time = self.time


class FakeStartPositionSong(FakePerformSong):
    """``FakePerformSong`` with Live's ACTUAL transport shape: the playhead and
    the start playing position are separate fields, and ``start_playing()``
    rolls from the second.

    The base fake models a single position, which was the belief that let #471
    hide — a seek that reads back correctly and playback that begins somewhere
    else are indistinguishable when there is only one field. Cue bookkeeping
    lands in ``cue_events`` rather than the shared ``events`` timeline, which
    stays the gesture/arm ordering log the rest of this module asserts against.
    """

    def __init__(self, events, clock=None, *, start_position: float = 0.0,
                 has_cue_api: bool = True):
        super().__init__(events, clock=clock)
        self._start_position = float(start_position)
        self.cue_events: list[tuple] = []
        self.last_event_time = 4096.0
        self.cue_points: list[Any] = []
        if not has_cue_api:
            # A Live with no cue-toggle surface. The handler probes by
            # ``getattr(..., None)``, so shadowing the method is exactly what
            # absence looks like from where it stands.
            self.set_or_delete_cue = None  # type: ignore[assignment]

    def set_or_delete_cue(self) -> None:
        at = self._song_time
        self.cue_events.append(("toggle", round(at, 6)))
        for i, cue in enumerate(self.cue_points):
            if abs(cue.time - at) < 1e-6:
                del self.cue_points[i]
                return
        self.cue_points.append(_JumpableCue(self, at))
        self.cue_points.sort(key=lambda c: c.time)

    def start_playing(self) -> None:
        self._events.append(("play",))
        self._locate_pending = None
        self._song_time = self._start_position
        self.song_time_at_play = self._song_time
        self.is_playing = True


class StartPositionCtx(FakeCtx):
    def __init__(self, clock=None, **song_kwargs):
        super().__init__(clock=clock)
        self._song = FakeStartPositionSong(self.events, clock=clock,
                                           **song_kwargs)


def test_a_stale_start_position_no_longer_silently_records_nothing():
    """#471, end to end. The set has been listened to, so Live's start playing
    position sits at 351 while the arc lives at 96..104. Before the fix the
    seek read back as 96.0 — honestly — the transport rolled from 351, the ramp
    loop's first tick was already past the span end, and the pass returned a
    clean result having written nothing."""
    ctx = StartPositionCtx(start_position=351.3)

    result = perform_batch_handler(ctx, arcs=[_far_arc()])

    arc = _arc0(result)
    assert arc["updates_written"] > 0
    assert arc["outcome"] == "recorded"
    assert ctx.song.song_time_at_play == pytest.approx(96.0)


def test_the_locate_gives_back_the_cue_it_borrowed():
    ctx = StartPositionCtx(start_position=351.3)

    perform_batch_handler(ctx, arcs=[_far_arc()])

    assert [c.time for c in ctx.song.cue_points] == []
    # Created, jumped, removed — in that order, at the span start.
    assert ctx.song.cue_events == [
        ("toggle", 96.0), ("cue_jump", 96.0), ("toggle", 96.0),
    ]


def test_an_operators_own_cue_at_the_span_start_is_used_not_toggled():
    ctx = StartPositionCtx(start_position=351.3)
    ctx.song.cue_points = [_JumpableCue(ctx.song, 96.0)]

    perform_batch_handler(ctx, arcs=[_far_arc()])

    assert [c.time for c in ctx.song.cue_points] == [96.0]
    assert ctx.song.cue_events == [("cue_jump", 96.0)]


def test_a_transport_rolling_past_the_span_aborts_instead_of_reporting_ok():
    """The mechanism-independent guard. With no cue API the locate can only
    move the playhead, so the transport still rolls from the stale start
    position — and the pass must say so rather than close its gestures on a
    beat past the span and return a clean result."""
    ctx = StartPositionCtx(start_position=351.3, has_cue_api=False)

    with pytest.raises(PlayheadPositionError) as exc:
        perform_batch_handler(ctx, arcs=[_far_arc()])

    err = exc.value
    assert err.observed_beats == pytest.approx(351.3)
    assert err.target_beats == 96.0
    assert "START PLAYING POSITION" in str(err)
    # The set is left disarmed and restored, as on every other failure path.
    assert ctx.song.is_playing is False
    assert ("record_mode", False) in ctx.events
    assert ("session_automation_record", False) in ctx.events


def test_the_abort_names_the_degraded_locate_that_led_to_it():
    ctx = StartPositionCtx(start_position=351.3, has_cue_api=False)

    with pytest.raises(PlayheadPositionError) as exc:
        perform_batch_handler(ctx, arcs=[_far_arc()])

    assert "playhead_only" in str(exc.value)
    assert "set_or_delete_cue" in str(exc.value)


# ---------------------------------------------------------------------------
# Per-arc outcomes — automation_state alone cannot carry this
# ---------------------------------------------------------------------------


def test_a_ramped_arc_reports_recorded_with_no_reason_to_explain():
    ctx = FakeCtx()
    arc = _arc0(_one(
        ctx, target_kind="mixer_volume", master=True,
        breakpoints=[_bp(0.0, 0.5), _bp(4.0, 0.9)],
    ))

    assert arc["outcome"] == "recorded"
    assert "outcome_reason" not in arc


def test_a_zero_write_arc_is_unverified_however_confident_live_sounds():
    """The damaging case: a parameter that already carries a lane from an
    earlier session reports ``automation_state == 1`` unconditionally, so a
    pass that wrote nothing is indistinguishable from one that wrote correctly
    — unless the count this pass is actually entitled to claim is consulted.

    The second arc's window is narrower than the gap between two ramp ticks, so
    the playhead crosses it whole: the gesture opens and closes having written
    nothing, while the parameter's earlier lane keeps answering 1."""
    ctx = FakeCtx()
    ctx.song.beats_per_read = 2.0

    result = perform_batch_handler(ctx, arcs=[
        {"target_kind": "mixer_volume", "master": True,
         "breakpoints": [_bp(0.0, 0.2), _bp(8.0, 0.9)]},
        {"target_kind": "mixer_pan", "master": True,
         "breakpoints": [_bp(1.0, 0.1), _bp(1.2, 0.4)]},
    ])

    ramped, skipped = result["arcs"]
    assert ramped["outcome"] == "recorded"
    assert skipped["updates_written"] == 0
    assert skipped["automation_state"] == 1
    assert skipped["outcome"] == "unverified"
    assert "reflects a lane from an earlier pass" in skipped["outcome_reason"]


def test_an_unconfirmed_lane_is_unverified_and_says_which_check_failed():
    ctx = FakeCtx()
    ctx.song.master_track.mixer_device.volume.verify_state = 0

    arc = _arc0(_one(
        ctx, target_kind="mixer_volume", master=True,
        breakpoints=[_bp(0.0, 0.5), _bp(4.0, 0.9)],
        settle_timeout_ms=20,
    ))

    assert arc["updates_written"] > 0
    assert arc["outcome"] == "unverified"
    assert "automation_state=0" in arc["outcome_reason"]
