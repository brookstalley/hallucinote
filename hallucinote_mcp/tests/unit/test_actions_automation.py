"""ableton_automation schema + handler behavior."""
from __future__ import annotations

from typing import Any

import pytest

from hallucinote_mcp import schema
from hallucinote_mcp.dispatcher import dispatch
from hallucinote_mcp.testing import isolated_actions
from hallucinote_mcp.wire import Request


# ---------- Fakes ----------


class FakeEnvelope:
    """Records envelope writes so tests can assert the breakpoint shape."""

    def __init__(self):
        self.cleared = 0
        self.steps: list[tuple[float, float, float]] = []  # (time, dur, value)
        self.segments: list[tuple[float, float, float, float, float]] = []
        # (time, dur, start, end, curve)

    def clear(self) -> None:
        self.cleared += 1
        self.steps.clear()
        self.segments.clear()

    def insert_step(self, time_beats: float, duration: float, value: float) -> None:
        self.steps.append((time_beats, duration, value))

    def add_segment(self, time, dur, start, end, curve) -> None:
        self.segments.append((time, dur, start, end, curve))


class FakeParam:
    def __init__(self, name: str, value: float = 0.0):
        self.name = name
        self.value = value
        self.min = 0.0
        self.max = 1.0
        self.value_items = None


class FakeMixer:
    def __init__(self, sends: int = 0):
        self.volume = FakeParam("Volume", 0.85)
        self.panning = FakeParam("Panning", 0.0)
        self.sends = [FakeParam(f"Send{i}", 0.0) for i in range(sends)]


class FakeClip:
    """Minimal clip stub that records envelope creation by-target."""

    def __init__(self):
        self.envelopes_by_target: dict[Any, FakeEnvelope] = {}

    # The dispatcher walks `_midi_cc_envelope_target` which calls
    # `clip.envelope_target_for_cc` if present. Our fake skips that and
    # accepts the tuple sentinel returned by the fallback.
    def create_automation_envelope(self, target: Any) -> FakeEnvelope:
        env = FakeEnvelope()
        # Use repr of target as key — both Live param objects and our tuple
        # sentinels hash differently per target.
        key = target if isinstance(target, tuple) else id(target)
        self.envelopes_by_target[key] = env
        return env

    def envelope_for_note(self, pitch: int, start: float, axis: str) -> FakeEnvelope:
        env = FakeEnvelope()
        self.envelopes_by_target[("note", pitch, start, axis)] = env
        return env

    def automation_envelope_for(self, target) -> Any:
        """Used by clear's _resolve_write_target. Returns the existing envelope
        for a target if previously created; None otherwise.
        """
        key = target if isinstance(target, tuple) else id(target)
        return self.envelopes_by_target.get(key)


class FakeClipSlot:
    def __init__(self, clip: FakeClip | None = None):
        self.clip = clip


class FakeTrack:
    def __init__(self, *, slots: int = 4):
        self.clip_slots = [FakeClipSlot() for _ in range(slots)]
        self.arrangement_clips = []
        self.devices = []
        self.mixer_device = FakeMixer(sends=1)

    def create_automation_envelope(self, param: Any) -> FakeEnvelope:
        """Arrangement-level (track) envelope."""
        env = FakeEnvelope()
        if not hasattr(self, "_track_envelopes"):
            self._track_envelopes: dict[Any, FakeEnvelope] = {}
        self._track_envelopes[id(param)] = env
        return env


class FakeReturn(FakeTrack):
    pass


class FakeSong:
    def __init__(
        self,
        tracks: list[FakeTrack] | None = None,
        returns: list[FakeReturn] | None = None,
    ):
        self.tracks = tracks or [FakeTrack(), FakeTrack()]
        self.return_tracks = returns or [FakeReturn()]


class FakeCtx:
    def __init__(self, song: FakeSong | None = None):
        self._song = song or FakeSong()
        self.run_on_main_calls = 0

    @property
    def song(self) -> FakeSong:
        return self._song

    def run_on_main(self, fn):
        self.run_on_main_calls += 1
        return fn()


@pytest.fixture()
def loaded_actions():
    with isolated_actions():
        yield schema


# ---------- Schema sanity ----------


_EXPECTED_AUTOMATION_ACTIONS = {
    "help", "list", "clear", "clear_all", "write_envelope", "get_envelope",
}


def test_automation_registers_six_actions(loaded_actions):
    names = {a.name for a in schema.actions_for("ableton_automation")}
    assert names == _EXPECTED_AUTOMATION_ACTIONS


def test_automation_help_lists_planned_surface(loaded_actions):
    resp = dispatch(Request(tool="ableton_automation", action="help"))
    assert resp.ok is True
    names = {a["name"] for a in resp.result["actions"]}
    assert names == _EXPECTED_AUTOMATION_ACTIONS - {"help"}


# ---------- write_envelope: target_kind branching ----------


def _track_with_clip() -> tuple[FakeCtx, FakeClip]:
    clip = FakeClip()
    track = FakeTrack()
    track.clip_slots[0].clip = clip
    return FakeCtx(FakeSong(tracks=[track])), clip


def test_write_envelope_clip_cc(loaded_actions):
    ctx, clip = _track_with_clip()
    resp = dispatch(
        Request(
            tool="ableton_automation", action="write_envelope",
            params={
                "target_kind": "clip_cc",
                "track_index": 1, "location": "session", "clip_index": 1,
                "cc_number": 7,
                "breakpoints": [
                    {"time_beats": 0.0, "value": 0.0},
                    {"time_beats": 4.0, "value": 1.0},
                    {"time_beats": 8.0, "value": 0.5, "curve": "linear"},
                ],
            },
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.error
    assert resp.result["target_kind"] == "clip_cc"
    assert resp.result["breakpoints_written"] == 3
    # The fake created exactly one envelope for the CC target.
    assert ("cc", 7) in clip.envelopes_by_target
    env = clip.envelopes_by_target[("cc", 7)]
    assert env.cleared == 1
    # 2 segments + 1 anchor step
    assert len(env.segments) == 2
    assert len(env.steps) == 1


def test_write_envelope_clip_cc_requires_cc_number(loaded_actions):
    ctx, _ = _track_with_clip()
    resp = dispatch(
        Request(
            tool="ableton_automation", action="write_envelope",
            params={
                "target_kind": "clip_cc",
                "track_index": 1, "location": "session", "clip_index": 1,
                "breakpoints": [{"time_beats": 0.0, "value": 0.0}],
            },
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "cc_number" in (resp.error or "")


def test_write_envelope_clip_pitch_bend(loaded_actions):
    ctx, clip = _track_with_clip()
    resp = dispatch(
        Request(
            tool="ableton_automation", action="write_envelope",
            params={
                "target_kind": "clip_pitch_bend",
                "track_index": 1, "location": "session", "clip_index": 1,
                "breakpoints": [
                    {"time_beats": 0.0, "value": 0.0},
                    {"time_beats": 2.0, "value": 0.5},
                ],
            },
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert ("pitch_bend",) in clip.envelopes_by_target


def test_write_envelope_note_expression(loaded_actions):
    ctx, clip = _track_with_clip()
    resp = dispatch(
        Request(
            tool="ableton_automation", action="write_envelope",
            params={
                "target_kind": "note_expression",
                "track_index": 1, "location": "session", "clip_index": 1,
                "note_pitch": 60, "note_start_beats": 1.0, "axis": "pitch",
                "breakpoints": [
                    {"time_beats": 0.0, "value": 0.0},
                    {"time_beats": 0.5, "value": 0.5},
                ],
            },
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert ("note", 60, 1.0, "pitch") in clip.envelopes_by_target


def test_write_envelope_note_expression_invalid_axis(loaded_actions):
    ctx, _ = _track_with_clip()
    resp = dispatch(
        Request(
            tool="ableton_automation", action="write_envelope",
            params={
                "target_kind": "note_expression",
                "track_index": 1, "location": "session", "clip_index": 1,
                "note_pitch": 60, "note_start_beats": 1.0, "axis": "wrong",
                "breakpoints": [{"time_beats": 0.0, "value": 0.0}],
            },
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "not in enum" in (resp.error or "")


def test_write_envelope_mixer_volume_track_level(loaded_actions):
    track = FakeTrack()
    ctx = FakeCtx(FakeSong(tracks=[track]))
    resp = dispatch(
        Request(
            tool="ableton_automation", action="write_envelope",
            params={
                "target_kind": "mixer_volume",
                "track_index": 1,
                "breakpoints": [
                    {"time_beats": 0.0, "value": 0.5},
                    {"time_beats": 16.0, "value": 0.8},
                ],
            },
        ),
        context=ctx,
    )
    assert resp.ok is True


def test_write_envelope_device_parameter_track_level(loaded_actions):
    """Track-level device-parameter envelope (no clip context)."""
    from test_actions_automation import FakeParam as _Param

    class _Dev:
        def __init__(self):
            self.parameters = (_Param("Threshold", -12.0),)

    track = FakeTrack()
    track.devices = [_Dev()]
    ctx = FakeCtx(FakeSong(tracks=[track]))
    resp = dispatch(
        Request(
            tool="ableton_automation", action="write_envelope",
            params={
                "target_kind": "device_parameter",
                "track_index": 1, "device_index": 1,
                "parameter_name": "Threshold",
                "breakpoints": [
                    {"time_beats": 0.0, "value": 0.5},
                    {"time_beats": 8.0, "value": 0.3},
                ],
            },
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.error
    assert resp.result["target_kind"] == "device_parameter"
    assert resp.result["parameter_name"] == "Threshold"


def test_write_envelope_device_parameter_unknown_name(loaded_actions):
    from test_actions_automation import FakeParam as _Param

    class _Dev:
        def __init__(self):
            self.parameters = (_Param("Threshold", -12.0),)

    track = FakeTrack()
    track.devices = [_Dev()]
    ctx = FakeCtx(FakeSong(tracks=[track]))
    resp = dispatch(
        Request(
            tool="ableton_automation", action="write_envelope",
            params={
                "target_kind": "device_parameter",
                "track_index": 1, "device_index": 1,
                "parameter_name": "Bogus",
                "breakpoints": [{"time_beats": 0.0, "value": 0.5}],
            },
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "Bogus" in (resp.error or "")
    assert "Threshold" in (resp.error or "")


def test_write_envelope_mixer_pan_track_level(loaded_actions):
    track = FakeTrack()
    ctx = FakeCtx(FakeSong(tracks=[track]))
    resp = dispatch(
        Request(
            tool="ableton_automation", action="write_envelope",
            params={
                "target_kind": "mixer_pan",
                "track_index": 1,
                "breakpoints": [
                    {"time_beats": 0.0, "value": -0.5},
                    {"time_beats": 8.0, "value": 0.5},
                ],
            },
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert resp.result["target_kind"] == "mixer_pan"


def test_write_envelope_send_level_requires_both(loaded_actions):
    track = FakeTrack()
    ctx = FakeCtx(FakeSong(tracks=[track]))
    resp = dispatch(
        Request(
            tool="ableton_automation", action="write_envelope",
            params={
                "target_kind": "send_level",
                "track_index": 1,  # missing return_index
                "breakpoints": [{"time_beats": 0.0, "value": 0.5}],
            },
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "return_index" in (resp.error or "")


def test_write_envelope_rejects_unsorted_breakpoints(loaded_actions):
    ctx, _ = _track_with_clip()
    resp = dispatch(
        Request(
            tool="ableton_automation", action="write_envelope",
            params={
                "target_kind": "mixer_volume", "track_index": 1,
                "breakpoints": [
                    {"time_beats": 4.0, "value": 0.5},
                    {"time_beats": 1.0, "value": 0.8},  # out of order
                ],
            },
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "sorted" in (resp.error or "")


def test_write_envelope_rejects_negative_time(loaded_actions):
    ctx, _ = _track_with_clip()
    resp = dispatch(
        Request(
            tool="ableton_automation", action="write_envelope",
            params={
                "target_kind": "mixer_volume", "track_index": 1,
                "breakpoints": [{"time_beats": -0.5, "value": 0.5}],
            },
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert ">= 0" in (resp.error or "")


def test_write_envelope_rejects_invalid_target_kind(loaded_actions):
    ctx, _ = _track_with_clip()
    resp = dispatch(
        Request(
            tool="ableton_automation", action="write_envelope",
            params={
                "target_kind": "wrong", "track_index": 1,
                "breakpoints": [{"time_beats": 0.0, "value": 0.5}],
            },
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "not in enum" in (resp.error or "")


# ---------- clear / clear_all ----------


def test_clear_clip_cc_requires_cc_number_symmetric_with_write(loaded_actions):
    """clear with target_kind='clip_cc' must require cc_number the same way
    write_envelope does — a silent default to CC 0 would be a contract-asymmetry
    trap (clear on the wrong CC silently).
    """
    ctx, _ = _track_with_clip()
    resp = dispatch(
        Request(
            tool="ableton_automation", action="clear",
            params={
                "target_kind": "clip_cc",
                "track_index": 1, "location": "session", "clip_index": 1,
                # NO cc_number — must error, not silently target CC 0
            },
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "cc_number" in (resp.error or "")


def test_clear_returns_no_op_when_no_envelope_exists(loaded_actions):
    """clear on a target with no existing envelope returns cleared=False
    rather than erroring — the apply layer can call clear unconditionally."""
    track = FakeTrack()
    ctx = FakeCtx(FakeSong(tracks=[track]))
    resp = dispatch(
        Request(
            tool="ableton_automation", action="clear",
            params={"target_kind": "mixer_volume", "track_index": 1},
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert resp.result["cleared"] is False
    assert "no envelope" in resp.result["reason"]


def test_clear_all_clip_scoped_requires_track_index(loaded_actions):
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack()]))
    resp = dispatch(
        Request(
            tool="ableton_automation", action="clear_all",
            params={"location": "session", "clip_index": 1},
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "track_index" in (resp.error or "")


def test_clear_all_parent_scoped_track(loaded_actions):
    class _TrackWithClear(FakeTrack):
        def __init__(self):
            super().__init__()
            self.clear_all_calls = 0
        def clear_all_envelopes(self):
            self.clear_all_calls += 1

    track = _TrackWithClear()
    ctx = FakeCtx(FakeSong(tracks=[track]))
    resp = dispatch(
        Request(
            tool="ableton_automation", action="clear_all",
            params={"track_index": 1},
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert resp.result["cleared_scope"] == "track"
    assert track.clear_all_calls == 1


def test_clear_all_requires_some_target(loaded_actions):
    ctx = FakeCtx()
    resp = dispatch(
        Request(tool="ableton_automation", action="clear_all", params={}),
        context=ctx,
    )
    assert resp.ok is False
    assert "track_index" in (resp.error or "") or "return_index" in (resp.error or "")


# ---------- get_envelope / list — gap stubs ----------


def test_get_envelope_returns_gap_error(loaded_actions):
    ctx, _ = _track_with_clip()
    resp = dispatch(
        Request(
            tool="ableton_automation", action="get_envelope",
            params={
                "target_kind": "mixer_volume", "track_index": 1,
            },
        ),
        context=ctx,
    )
    assert resp.ok is False
    err = (resp.error or "").lower()
    assert "gap" in err
    assert "write_envelope" in err  # points at the working alternative


def test_list_returns_gap_error(loaded_actions):
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_automation", action="list",
            params={"track_index": 1},
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "gap" in (resp.error or "").lower()


def test_blocked_actions_carry_BLOCKED_tag_in_description(loaded_actions):
    for name in ("list", "get_envelope"):
        action = schema.get("ableton_automation", name)
        assert action is not None
        assert "BLOCKED" in action.description


# ---------- run_on_main discipline ----------


def test_automation_execution_marshals_to_main_thread(loaded_actions):
    ctx, _ = _track_with_clip()
    dispatch(
        Request(
            tool="ableton_automation", action="write_envelope",
            params={
                "target_kind": "mixer_volume", "track_index": 1,
                "breakpoints": [{"time_beats": 0.0, "value": 0.5}],
            },
        ),
        context=ctx,
    )
    assert ctx.run_on_main_calls == 1
