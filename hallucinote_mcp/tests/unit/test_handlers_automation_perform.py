"""Tests for ``ableton_automation(action='perform')`` — ENV-7G4K chunk 01.

Fake-Live coverage of the gesture-recording handler:

  - exact begin_gesture → ramp → end_gesture → restore sequence
  - state restore when the ramp raises mid-flight
  - record_mode settle-poll (probe 10: async apply — same-call read-back
    returns the OLD value) including the timeout path
  - breakpoint interpolation (linear / hold / fast / slow, out-of-range
    holds, segment boundaries)
  - param validation (addressing, span, target_kind)
  - wire-path regression through the dispatcher (probe-tool precedent)

The fakes simulate the two async behaviors the mechanism depends on:
``record_mode`` applying N reads late, and ``current_song_time``
advancing while the transport plays. Everything is event-logged so the
ordering assertions read like the probe-4 recipe.
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
    _validate_breakpoints,
    perform_handler,
)
from hallucinote_mcp.testing import isolated_actions
from hallucinote_mcp.wire import Request


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeGestureParam:
    """A Live DeviceParameter that records gesture lifecycle + value sets."""

    def __init__(self, events: list[tuple]):
        self._events = events
        self._value = 0.85
        self.automation_state = 0
        self.raise_on_set_after: int | None = None
        self._set_count = 0

    def begin_gesture(self) -> None:
        self._events.append(("begin_gesture",))

    def end_gesture(self) -> None:
        self._events.append(("end_gesture",))
        # Probe 4: a successful record flips automation_state 0 → 1.
        self.automation_state = 1

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
        return fn()


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


# ---------------------------------------------------------------------------
# Gesture ordering — the probe-4 recipe, exactly
# ---------------------------------------------------------------------------


def test_perform_records_exact_gesture_sequence():
    ctx = FakeCtx()
    result = perform_handler(
        ctx,
        target_kind="mixer_volume",
        master=True,
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

    assert result["automation_state"] == 1
    assert result["span_beats"] == [0.0, 4.0]
    assert result["beats_performed"] == 4.0
    assert result["updates_written"] == len(ramp)
    assert result["target_kind"] == "mixer_volume"
    assert result["master"] is True
    assert "restore_failures" not in result


def test_perform_restores_prior_transport_state():
    ctx = FakeCtx()
    song = ctx.song
    song._record_mode_actual = True  # user had the set armed
    song.session_automation_record = True
    song._song_time = 7.5
    ctx.events.clear()  # drop setup-logged events

    perform_handler(
        ctx,
        target_kind="mixer_volume",
        master=True,
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
    perform_handler(
        ctx,
        target_kind="mixer_volume",
        master=True,
        breakpoints=[_bp(0.0, 0.5), _bp(2.0, 0.9)],
    )
    # The pre-arm stop comes before the arm writes.
    assert ctx.events[0] == ("stop",)
    assert ctx.events[1] == ("session_automation_record", True)


# ---------------------------------------------------------------------------
# State restore on exception
# ---------------------------------------------------------------------------


def test_perform_restores_state_when_ramp_raises():
    ctx = FakeCtx()
    param = ctx.song.master_track.mixer_device.volume
    param.raise_on_set_after = 1  # second value write blows up

    with pytest.raises(RuntimeError, match="simulated Live parameter"):
        perform_handler(
            ctx,
            target_kind="mixer_volume",
            master=True,
            breakpoints=[_bp(0.0, 0.5), _bp(8.0, 0.9)],
        )

    # Gesture closed, transport stopped, set disarmed — despite the raise.
    assert ("end_gesture",) in ctx.events
    assert ("stop",) in ctx.events
    assert ("record_mode", False) in ctx.events
    assert ("session_automation_record", False) in ctx.events
    assert ("re_enable_automation",) in ctx.events
    assert ctx.song.is_playing is False


def test_perform_restore_attempts_every_step_when_one_fails():
    ctx = FakeCtx()

    def _raising_stop() -> None:
        raise RuntimeError("stop failed")

    ctx.song.stop_playing = _raising_stop  # type: ignore[method-assign]
    result = perform_handler(
        ctx,
        target_kind="mixer_volume",
        master=True,
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
    result = perform_handler(
        ctx,
        target_kind="mixer_volume",
        master=True,
        breakpoints=[_bp(0.0, 0.5), _bp(2.0, 0.9)],
    )
    # The gesture began only after record_mode actually applied.
    assert result["automation_state"] == 1
    assert ("begin_gesture",) in ctx.events


def test_perform_times_out_when_record_mode_never_applies_and_restores():
    ctx = FakeCtx()
    # Pending never applies: simulate an unbounded apply delay.
    ctx.song.record_mode_apply_after_reads = 10**9

    with pytest.raises(TimeoutError, match="record_mode"):
        perform_handler(
            ctx,
            target_kind="mixer_volume",
            master=True,
            breakpoints=[_bp(0.0, 0.5), _bp(2.0, 0.9)],
            settle_timeout_ms=20,
        )

    # No gesture ever opened; the set was still disarmed + restored.
    assert ("begin_gesture",) not in ctx.events
    assert ("end_gesture",) not in ctx.events
    assert ("record_mode", False) in ctx.events
    assert ("session_automation_record", False) in ctx.events


# ---------------------------------------------------------------------------
# Breakpoint interpolation
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
# Param validation
# ---------------------------------------------------------------------------


def test_perform_rejects_clip_hosted_target_kinds():
    ctx = FakeCtx()
    with pytest.raises(ValueError, match="write_envelope"):
        perform_handler(
            ctx, target_kind="clip_cc", breakpoints=[_bp(0.0, 0.5)],
        )


def test_perform_requires_exactly_one_parent():
    ctx = FakeCtx()
    with pytest.raises(ValueError, match="exactly one of"):
        perform_handler(
            ctx,
            target_kind="mixer_volume",
            master=True,
            track_index=1,
            breakpoints=[_bp(0.0, 0.5), _bp(2.0, 0.9)],
        )
    with pytest.raises(ValueError, match="exactly one of"):
        perform_handler(
            ctx,
            target_kind="mixer_pan",
            breakpoints=[_bp(0.0, 0.5), _bp(2.0, 0.9)],
        )
    # No transport state was touched by addressing failures.
    assert ctx.events == []


def test_perform_send_level_refuses_master_and_requires_both_indices():
    ctx = FakeCtx()
    with pytest.raises(ValueError, match="no sends"):
        perform_handler(
            ctx,
            target_kind="send_level",
            master=True,
            breakpoints=[_bp(0.0, 0.5), _bp(2.0, 0.9)],
        )
    with pytest.raises(ValueError, match="track_index"):
        perform_handler(
            ctx,
            target_kind="send_level",
            return_index=1,
            breakpoints=[_bp(0.0, 0.5), _bp(2.0, 0.9)],
        )


def test_perform_device_parameter_requires_device_and_name():
    ctx = FakeCtx()
    with pytest.raises(ValueError, match="device_index and parameter_name"):
        perform_handler(
            ctx,
            target_kind="device_parameter",
            master=True,
            breakpoints=[_bp(0.0, 0.5), _bp(2.0, 0.9)],
        )


def test_perform_device_parameter_on_master_chain():
    ctx = FakeCtx()
    cutoff = FakeNamedParam(ctx.events, "Frequency")
    ctx.song.master_track.devices = [FakeDevice([cutoff])]
    result = perform_handler(
        ctx,
        target_kind="device_parameter",
        master=True,
        device_index=1,
        parameter_name="Frequency",
        breakpoints=[_bp(0.0, 0.2), _bp(2.0, 0.9)],
    )
    assert result["automation_state"] == 1
    assert any(e[0] == "set_value" for e in ctx.events)
    assert result["parameter_name"] == "Frequency"


def test_perform_on_return_track_mixer():
    ctx = FakeCtx()
    result = perform_handler(
        ctx,
        target_kind="mixer_volume",
        return_index=1,
        breakpoints=[_bp(0.0, 0.2), _bp(2.0, 0.9)],
    )
    assert result["automation_state"] == 1
    assert result["return_index"] == 1


def test_perform_send_level_on_track():
    ctx = FakeCtx()
    send = FakeGestureParam(ctx.events)
    ctx.song.tracks[0].mixer_device.sends = [send]
    result = perform_handler(
        ctx,
        target_kind="send_level",
        track_index=1,
        return_index=1,
        breakpoints=[_bp(0.0, 0.0), _bp(2.0, 0.7)],
    )
    assert result["automation_state"] == 1
    assert send.automation_state == 1


def test_perform_rejects_empty_span():
    ctx = FakeCtx()
    with pytest.raises(ValueError, match="span is empty"):
        perform_handler(
            ctx,
            target_kind="mixer_volume",
            master=True,
            breakpoints=[_bp(4.0, 0.5)],  # single bp → zero-length default span
        )
    with pytest.raises(ValueError, match="span is empty"):
        perform_handler(
            ctx,
            target_kind="mixer_volume",
            master=True,
            breakpoints=[_bp(0.0, 0.5), _bp(4.0, 0.9)],
            span_start_beats=4.0,
            span_end_beats=2.0,
        )


def test_perform_explicit_span_extends_past_breakpoints():
    ctx = FakeCtx()
    result = perform_handler(
        ctx,
        target_kind="mixer_volume",
        master=True,
        breakpoints=[_bp(1.0, 0.5), _bp(2.0, 0.9)],
        span_start_beats=0.0,
        span_end_beats=4.0,
    )
    assert result["span_beats"] == [0.0, 4.0]
    # First write (at beat 0, before the first breakpoint) holds the
    # first authored value; the tail holds the last.
    sets = [e[1] for e in ctx.events if e[0] == "set_value"]
    assert sets[0] == pytest.approx(0.5)
    assert sets[-1] == pytest.approx(0.9)


def test_perform_rejects_unsorted_breakpoints():
    ctx = FakeCtx()
    with pytest.raises(ValueError, match="sorted"):
        perform_handler(
            ctx,
            target_kind="mixer_volume",
            master=True,
            breakpoints=[_bp(4.0, 0.5), _bp(0.0, 0.9)],
        )


def test_perform_rejects_nonpositive_settle_timeout():
    ctx = FakeCtx()
    with pytest.raises(ValueError, match="settle_timeout_ms"):
        perform_handler(
            ctx,
            target_kind="mixer_volume",
            master=True,
            breakpoints=[_bp(0.0, 0.5), _bp(2.0, 0.9)],
            settle_timeout_ms=0,
        )


# ---------------------------------------------------------------------------
# Wire-path regression (probe-tool precedent: the registered action must
# round-trip through the dispatcher, not just the bare handler)
# ---------------------------------------------------------------------------


@pytest.fixture()
def loaded_actions():
    with isolated_actions():
        yield schema


def test_perform_dispatches_through_wire(loaded_actions):
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_automation",
            action="perform",
            params={
                "target_kind": "mixer_volume",
                "master": True,
                "breakpoints": [
                    {"time_beats": 0.0, "value": 0.5},
                    {"time_beats": 2.0, "value": 0.9, "curve": "slow"},
                ],
            },
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert resp.result["automation_state"] == 1
    assert resp.result["target_kind"] == "mixer_volume"
    assert ("begin_gesture",) in ctx.events


def test_perform_registered_runs_on_worker(loaded_actions):
    action = schema.get("ableton_automation", "perform")
    assert action is not None
    assert action.runs_on_worker is True


def test_perform_wire_validation_rejects_bad_target_kind(loaded_actions):
    resp = dispatch(
        Request(
            tool="ableton_automation",
            action="perform",
            params={
                "target_kind": "clip_cc",
                "breakpoints": [{"time_beats": 0.0, "value": 0.5}],
            },
        ),
        context=FakeCtx(),
    )
    assert resp.ok is False
    assert "target_kind" in resp.error.lower() or "clip_cc" in resp.error
