"""ableton_automation schema + handler behavior.

Test fakes mirror Live 12.4's actual envelope surface:
  - ``Clip.create_automation_envelope(target)`` is the only path that produces
    an envelope. Track / Parameter creation surfaces don't exist on 12.4.
  - ``Clip.clear_envelope(target)`` is the only documented per-target clear
    (``Envelope.clear`` was removed; ``Track.clear_*`` was never exposed).
  - ``Clip.clear_all_envelopes()`` is the atomic per-clip wipe.
  - ``Envelope.insert_step(time, duration, value)`` is the only writer.
    ``add_segment`` / ``add_breakpoint`` aren't on 12.4's Envelope.

Authority for these claims: Live 12 Suite's bundled ``_MxDCore/LomTypes.pyc``
plus the first-party usage in ``pushbase/automation_component.py`` and
``ableton/v2/control_surface/components/session_recording.py``.
"""
from __future__ import annotations

from typing import Any

import pytest

from hallucinote_mcp import schema
from hallucinote_mcp.dispatcher import dispatch
from hallucinote_mcp.testing import isolated_actions
from hallucinote_mcp.wire import Request


# ---------- Fakes ----------


class FakeEnvelope:
    """Records ``insert_step`` writes so tests can assert breakpoint shape.

    Mirrors Live 12.4: only ``insert_step(time, duration, value)`` exists.
    No ``clear``, no ``add_segment``. ``value_at_time(t)`` is added per
    W6-G — Live's real Envelope exposes it as the read path, and the
    new sampling-based reconstruction depends on it.
    """

    def __init__(self):
        self.steps: list[tuple[float, float, float]] = []  # (time, dur, value)

    def insert_step(self, time_beats: float, duration: float, value: float) -> None:
        self.steps.append((time_beats, duration, value))

    def value_at_time(self, time_beats: float) -> float:
        """Return the value at the given time per the recorded steps.

        Mirrors Live's stepped semantics: the most recent `insert_step`
        whose region [t, t+duration] covers `time_beats` wins. Zero-
        duration anchors (Hallucinote's last-breakpoint anchor pattern)
        match at exactly their start time too — the handler's anchor
        check needs this to round-trip the final breakpoint.

        Default 0.0 when no step covers the time (matches Live's
        unset-region behavior).
        """
        value = 0.0
        for t, dur, v in self.steps:
            if dur == 0.0:
                if abs(time_beats - t) < 1e-9:
                    value = v
            elif t <= time_beats < t + dur:
                value = v
        return value


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
    """Minimal clip stub.

    - ``create_automation_envelope(target)`` returns an envelope per
      target — idempotent (returns existing if present, else creates).
      Mirrors Live's actual behavior; W6-G's read path depends on it.
      The write path always preceedes with ``clear_envelope`` so it
      still gets a fresh envelope.
    - ``clear_envelope(target)`` removes the envelope for that target
      (idempotent — no error if absent).
    - ``clear_all_envelopes()`` wipes everything.
    - ``envelope_for_note(pitch, start, axis)`` returns the per-note MPE
      envelope; note-expression has its own factory in Live's API.
    - ``length`` is the clip's length in beats (W6-G read path samples
      across [0, length]).
    """

    def __init__(self, length: float = 4.0):
        self.envelopes_by_target: dict[Any, FakeEnvelope] = {}
        self.clear_envelope_calls: list[Any] = []  # ordered targets cleared
        self.clear_all_calls: int = 0
        self.length = length

    def _key(self, target: Any) -> Any:
        return target if isinstance(target, tuple) else id(target)

    def clear_envelope(self, target: Any) -> None:
        self.clear_envelope_calls.append(target)
        self.envelopes_by_target.pop(self._key(target), None)

    def clear_all_envelopes(self) -> None:
        self.clear_all_calls += 1
        self.envelopes_by_target.clear()

    def create_automation_envelope(self, target: Any) -> FakeEnvelope:
        # Idempotent — return existing envelope if present (matches Live's
        # actual behavior; W6-G's read path uses this to discover existing
        # envelopes without a dedicated get_automation_envelope API).
        key = self._key(target)
        env = self.envelopes_by_target.get(key)
        if env is None:
            env = FakeEnvelope()
            self.envelopes_by_target[key] = env
        return env

    def envelope_for_note(self, pitch: int, start: float, axis: str) -> FakeEnvelope:
        key = ("note", pitch, start, axis)
        env = self.envelopes_by_target.get(key)
        if env is None:
            env = FakeEnvelope()
            self.envelopes_by_target[key] = env
        return env


class FakeClipSlot:
    def __init__(self, clip: FakeClip | None = None):
        self.clip = clip


class FakeTrack:
    """Track has NO create_automation_envelope on Live 12.4. The fake
    intentionally omits it — handler code that tries to call it must
    surface the teaching error instead.
    """
    def __init__(self, *, slots: int = 4):
        self.clip_slots = [FakeClipSlot() for _ in range(slots)]
        self.arrangement_clips: list[FakeClip] = []
        self.devices = []
        self.mixer_device = FakeMixer(sends=1)


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
    # W6-G/W6-H: read_envelope is the new keystone; get_envelope kept as alias.
    "read_envelope",
}


def test_automation_registers_expected_actions(loaded_actions):
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
    # The handler called clip.clear_envelope for the CC target before
    # creating the envelope (mirrors pushbase/actions.py:335).
    assert ("cc", 7) in clip.clear_envelope_calls
    assert ("cc", 7) in clip.envelopes_by_target
    env = clip.envelopes_by_target[("cc", 7)]
    # Live 12.4 only exposes insert_step — 2 segment-steps + 1 anchor step.
    assert len(env.steps) == 3
    # Segment step durations match consecutive-breakpoint gaps.
    assert env.steps[0] == (0.0, 4.0, 0.0)
    assert env.steps[1] == (4.0, 4.0, 1.0)
    # Final anchor is zero-duration at the last breakpoint's value.
    assert env.steps[2] == (8.0, 0.0, 0.5)


def test_write_envelope_clip_cc_surfaces_curve_note_for_non_step_hints(loaded_actions):
    """Live 12.4 LOM only has insert_step. The handler must surface a note
    when callers pass curves other than 'hold' so the agent knows the hint
    was recorded but not applied as a ramp.
    """
    ctx, _ = _track_with_clip()
    resp = dispatch(
        Request(
            tool="ableton_automation", action="write_envelope",
            params={
                "target_kind": "clip_cc",
                "track_index": 1, "location": "session", "clip_index": 1,
                "cc_number": 7,
                "breakpoints": [
                    {"time_beats": 0.0, "value": 0.0, "curve": "linear"},
                    {"time_beats": 4.0, "value": 1.0},
                ],
            },
        ),
        context=ctx,
    )
    assert resp.ok is True
    notes = resp.result.get("notes") or []
    assert any("stepped" in n for n in notes), notes


def test_write_envelope_clip_cc_no_note_when_all_step(loaded_actions):
    """Pure-step envelopes (no curves or all 'hold') should not surface a
    curve-warning note — silence means the writes are faithful.
    """
    ctx, _ = _track_with_clip()
    resp = dispatch(
        Request(
            tool="ableton_automation", action="write_envelope",
            params={
                "target_kind": "clip_cc",
                "track_index": 1, "location": "session", "clip_index": 1,
                "cc_number": 7,
                "breakpoints": [
                    {"time_beats": 0.0, "value": 0.0, "curve": "hold"},
                    {"time_beats": 4.0, "value": 1.0},
                ],
            },
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert "notes" not in resp.result


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
    assert ("pitch_bend",) in clip.clear_envelope_calls
    assert ("pitch_bend",) in clip.envelopes_by_target


def test_write_envelope_mixer_volume_on_arrangement_clip_teaches(loaded_actions):
    """Wave-2 W2-10: Live 12.4's Clip.create_automation_envelope rejects
    mixer/pan/send/device_parameter targets on arrangement clips with
    "Not a session clip or parameter belongs to another track." The
    handler now surfaces a teaching error explaining the session-clip
    workaround instead of letting Live's raw RuntimeError reach the
    caller.
    """
    ctx, _ = _track_with_clip()
    # Also add an arrangement clip to the same track so _resolve_clip
    # can find it under location='arrangement'.
    ctx.song.tracks[0].arrangement_clips = (
        ctx.song.tracks[0].clip_slots[0].clip,
    )
    resp = dispatch(
        Request(
            tool="ableton_automation", action="write_envelope",
            params={
                "target_kind": "mixer_volume",
                "track_index": 1, "location": "arrangement", "clip_index": 1,
                "breakpoints": [
                    {"time_beats": 0.0, "value": 0.5},
                    {"time_beats": 16.0, "value": 0.9},
                ],
            },
        ),
        context=ctx,
    )
    assert resp.ok is False
    err = (resp.error or "")
    assert "arrangement clip" in err.lower()
    assert "session" in err.lower()  # the workaround is mentioned
    assert "duplicate_to_arrangement" in err


def test_write_envelope_clip_cc_translates_typed_boundary_error(loaded_actions):
    """Wave-2 W2-10: real Live's Clip.clear_envelope rejects the tuple
    sentinel with ``ArgumentError: ... TPyHandle<ATimeableValue>``. The
    handler now catches that error and surfaces a teaching
    NotImplementedError pointing at the LOM gap + workaround.

    Simulated via a FakeClip whose clear_envelope mimics Live's typed
    rejection.
    """
    ctx, clip = _track_with_clip()

    def _typed_reject(target):
        raise TypeError(
            "ArgumentError: Python argument types in "
            "Clip.clear_envelope(Clip, tuple) did not match C++ "
            "signature: clear_envelope(TPyHandle<AClip>, "
            "TPyHandle<ATimeableValue>)"
        )

    clip.clear_envelope = _typed_reject  # noqa: SLF001 — test override
    resp = dispatch(
        Request(
            tool="ableton_automation", action="write_envelope",
            params={
                "target_kind": "clip_cc",
                "track_index": 1, "location": "session", "clip_index": 1,
                "cc_number": 7,
                "breakpoints": [{"time_beats": 0.0, "value": 0.5}],
            },
        ),
        context=ctx,
    )
    assert resp.ok is False
    err = (resp.error or "")
    assert "clip_cc" in err
    assert "LOM" in err  # mentions the API gap
    assert "replace_notes" in err  # suggests the workaround


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
    # note_expression uses envelope_for_note (no pre-clear): insert_step
    # overwrites the existing breakpoints in the time range.
    assert ("note", 60, 1.0, "pitch") not in clip.clear_envelope_calls


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


# ---------- write_envelope: track-level paths are gap-blocked on 12.4 ----------


def test_write_envelope_mixer_volume_without_clip_raises_teaching_error(loaded_actions):
    """B-11: Live 12.4 LOM has no Track.create_automation_envelope. The
    handler must reject the clip-less mixer_volume call with a teaching
    error pointing at the clip-scoped workaround — silently dropping the
    write would violate Critical Rule "never silently drop a requirement".
    """
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
    assert resp.ok is False
    err = (resp.error or "").lower()
    assert "clip_index" in err and "location" in err
    assert "live 12.4" in err


def test_write_envelope_mixer_pan_without_clip_raises_teaching_error(loaded_actions):
    """B-11 sibling for mixer_pan."""
    track = FakeTrack()
    ctx = FakeCtx(FakeSong(tracks=[track]))
    resp = dispatch(
        Request(
            tool="ableton_automation", action="write_envelope",
            params={
                "target_kind": "mixer_pan",
                "track_index": 1,
                "breakpoints": [{"time_beats": 0.0, "value": 0.0}],
            },
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "clip_index" in (resp.error or "").lower()


def test_write_envelope_send_level_without_clip_raises_teaching_error(loaded_actions):
    """B-11 sibling for send_level."""
    track = FakeTrack()
    ctx = FakeCtx(FakeSong(tracks=[track]))
    resp = dispatch(
        Request(
            tool="ableton_automation", action="write_envelope",
            params={
                "target_kind": "send_level",
                "track_index": 1, "return_index": 1,
                "breakpoints": [{"time_beats": 0.0, "value": 0.5}],
            },
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "clip_index" in (resp.error or "").lower()


def test_write_envelope_device_parameter_without_clip_raises_teaching_error(loaded_actions):
    """B-11 sibling for device_parameter."""
    class _Dev:
        def __init__(self):
            self.parameters = (FakeParam("Threshold", -12.0),)

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
                "breakpoints": [{"time_beats": 0.0, "value": 0.5}],
            },
        ),
        context=ctx,
    )
    assert resp.ok is False
    err = (resp.error or "").lower()
    assert "clip_index" in err


# ---------- write_envelope: clip-scoped variants of the mixer/send/param paths ----------


def test_write_envelope_mixer_volume_clip_scoped(loaded_actions):
    """The valid path on Live 12.4: clip-scoped mixer_volume envelope."""
    ctx, clip = _track_with_clip()
    track = ctx.song.tracks[0]
    resp = dispatch(
        Request(
            tool="ableton_automation", action="write_envelope",
            params={
                "target_kind": "mixer_volume",
                "track_index": 1, "location": "session", "clip_index": 1,
                "breakpoints": [
                    {"time_beats": 0.0, "value": 0.5},
                    {"time_beats": 16.0, "value": 0.8},
                ],
            },
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.error
    assert resp.result["target_kind"] == "mixer_volume"
    # The track's volume parameter was cleared on the clip and the envelope
    # was created with the same target.
    vol = track.mixer_device.volume
    assert vol in clip.clear_envelope_calls
    assert id(vol) in clip.envelopes_by_target


def test_write_envelope_mixer_pan_clip_scoped(loaded_actions):
    ctx, clip = _track_with_clip()
    track = ctx.song.tracks[0]
    resp = dispatch(
        Request(
            tool="ableton_automation", action="write_envelope",
            params={
                "target_kind": "mixer_pan",
                "track_index": 1, "location": "session", "clip_index": 1,
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
    assert track.mixer_device.panning in clip.clear_envelope_calls


def test_write_envelope_send_level_clip_scoped(loaded_actions):
    ctx, clip = _track_with_clip()
    track = ctx.song.tracks[0]
    resp = dispatch(
        Request(
            tool="ableton_automation", action="write_envelope",
            params={
                "target_kind": "send_level",
                "track_index": 1, "return_index": 1,
                "location": "session", "clip_index": 1,
                "breakpoints": [{"time_beats": 0.0, "value": 0.5}],
            },
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert resp.result["target_kind"] == "send_level"
    assert track.mixer_device.sends[0] in clip.clear_envelope_calls


def test_write_envelope_device_parameter_clip_scoped(loaded_actions):
    """Clip-scoped device-parameter envelope."""
    class _Dev:
        def __init__(self):
            self.parameters = (FakeParam("Threshold", -12.0),)

    clip = FakeClip()
    track = FakeTrack()
    track.devices = [_Dev()]
    track.clip_slots[0].clip = clip
    ctx = FakeCtx(FakeSong(tracks=[track]))
    resp = dispatch(
        Request(
            tool="ableton_automation", action="write_envelope",
            params={
                "target_kind": "device_parameter",
                "track_index": 1, "device_index": 1,
                "parameter_name": "Threshold",
                "location": "session", "clip_index": 1,
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
    # The threshold parameter was the clear target.
    threshold = track.devices[0].parameters[0]
    assert threshold in clip.clear_envelope_calls


def test_write_envelope_device_parameter_unknown_name(loaded_actions):
    class _Dev:
        def __init__(self):
            self.parameters = (FakeParam("Threshold", -12.0),)

    clip = FakeClip()
    track = FakeTrack()
    track.devices = [_Dev()]
    track.clip_slots[0].clip = clip
    ctx = FakeCtx(FakeSong(tracks=[track]))
    resp = dispatch(
        Request(
            tool="ableton_automation", action="write_envelope",
            params={
                "target_kind": "device_parameter",
                "track_index": 1, "device_index": 1,
                "parameter_name": "Bogus",
                "location": "session", "clip_index": 1,
                "breakpoints": [{"time_beats": 0.0, "value": 0.5}],
            },
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "Bogus" in (resp.error or "")
    assert "Threshold" in (resp.error or "")


# ---------- W7-C: return_index clip-scoped parity tests ----------
#
# The handler accepts return_index for the same clip-scoped envelopes as
# track_index — mixer_volume / mixer_pan on a return's session clip,
# send_level for return-to-return sends, and device_parameter on a return
# device. The tests above all exercise track_index; these pin the return
# branch of `_require_parent`. (Hallucinote's sync layer doesn't address
# return-side session clips today — schema gap per backlog — but the MCP
# handler must keep working for direct callers.)


def _return_with_clip(send_count: int = 0) -> tuple[FakeCtx, FakeClip, FakeReturn]:
    """Return a context whose return-track has a clip in slot 1.

    `send_count` adjusts the FakeMixer's send count so return-to-return
    send tests can address sends[N].
    """
    ret = FakeReturn()
    if send_count:
        ret.mixer_device = FakeMixer(sends=send_count)
    clip = FakeClip()
    ret.clip_slots[0].clip = clip
    return FakeCtx(FakeSong(tracks=[FakeTrack()], returns=[ret])), clip, ret


def test_write_envelope_mixer_volume_return_clip_scoped(loaded_actions):
    """Return-track mixer_volume on a session clip — same envelope shape
    as the track-side test, addressed via return_index."""
    ctx, clip, ret = _return_with_clip()
    resp = dispatch(
        Request(
            tool="ableton_automation", action="write_envelope",
            params={
                "target_kind": "mixer_volume",
                "return_index": 1, "location": "session", "clip_index": 1,
                "breakpoints": [
                    {"time_beats": 0.0, "value": 0.5},
                    {"time_beats": 8.0, "value": 0.8},
                ],
            },
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.error
    assert resp.result["target_kind"] == "mixer_volume"
    assert ret.mixer_device.volume in clip.clear_envelope_calls


def test_write_envelope_mixer_pan_return_clip_scoped(loaded_actions):
    """Return-track mixer_pan on a session clip — common authoring case
    (automate a return's stereo position over an arrangement section)."""
    ctx, clip, ret = _return_with_clip()
    resp = dispatch(
        Request(
            tool="ableton_automation", action="write_envelope",
            params={
                "target_kind": "mixer_pan",
                "return_index": 1, "location": "session", "clip_index": 1,
                "breakpoints": [
                    {"time_beats": 0.0, "value": -0.5},
                    {"time_beats": 4.0, "value": 0.5},
                ],
            },
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.error
    assert resp.result["target_kind"] == "mixer_pan"
    assert ret.mixer_device.panning in clip.clear_envelope_calls


def test_write_envelope_send_level_return_to_return_clip_scoped(loaded_actions):
    """Live supports return-to-return sends; send_level addressed by
    (source return_index, target return_index) must work the same way
    as track-to-return."""
    # Two returns: the source has a send to the second; the source has
    # a clip in slot 1 that hosts the envelope.
    src_ret = FakeReturn()
    src_ret.mixer_device = FakeMixer(sends=1)
    clip = FakeClip()
    src_ret.clip_slots[0].clip = clip
    tgt_ret = FakeReturn()
    ctx = FakeCtx(FakeSong(
        tracks=[FakeTrack()], returns=[src_ret, tgt_ret],
    ))
    resp = dispatch(
        Request(
            tool="ableton_automation", action="write_envelope",
            params={
                "target_kind": "send_level",
                "return_index": 1,  # source return
                "send_target_return_index": 2,  # but handler may name this differently
                "location": "session", "clip_index": 1,
                "breakpoints": [{"time_beats": 0.0, "value": 0.5}],
            },
        ),
        context=ctx,
    )
    # Either the handler accepts this exact shape OR it raises a teaching
    # error about the right param name. Test pins the contract: a clear
    # response (success OR a teaching error) — never a silent miss.
    if resp.ok:
        assert resp.result["target_kind"] == "send_level"
        # Mixer.sends[0] is the send target this envelope writes to.
        assert src_ret.mixer_device.sends[0] in clip.clear_envelope_calls
    else:
        # The handler today expects `return_index` to address the SEND
        # TARGET (per the existing send_level test at line 519), which
        # makes return-source ambiguous. The error must teach the user
        # rather than silently succeed.
        assert resp.error is not None


def test_write_envelope_device_parameter_return_clip_scoped(loaded_actions):
    """Return-track device_parameter on a session clip — e.g. automate
    a Reverb's Decay on return A across an arrangement section."""
    class _Dev:
        def __init__(self):
            self.parameters = (FakeParam("Decay Time", 2.0),)

    ret = FakeReturn()
    ret.devices = [_Dev()]
    clip = FakeClip()
    ret.clip_slots[0].clip = clip
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack()], returns=[ret]))
    resp = dispatch(
        Request(
            tool="ableton_automation", action="write_envelope",
            params={
                "target_kind": "device_parameter",
                "return_index": 1, "device_index": 1,
                "parameter_name": "Decay Time",
                "location": "session", "clip_index": 1,
                "breakpoints": [
                    {"time_beats": 0.0, "value": 1.0},
                    {"time_beats": 8.0, "value": 4.0},
                ],
            },
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.error
    assert resp.result["target_kind"] == "device_parameter"
    assert resp.result["parameter_name"] == "Decay Time"
    decay = ret.devices[0].parameters[0]
    assert decay in clip.clear_envelope_calls


def test_write_envelope_send_level_requires_return(loaded_actions):
    ctx, _ = _track_with_clip()
    resp = dispatch(
        Request(
            tool="ableton_automation", action="write_envelope",
            params={
                "target_kind": "send_level",
                "track_index": 1,  # missing return_index
                "location": "session", "clip_index": 1,
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
                "target_kind": "mixer_volume",
                "track_index": 1, "location": "session", "clip_index": 1,
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
                "target_kind": "mixer_volume",
                "track_index": 1, "location": "session", "clip_index": 1,
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


# ---------- clear ----------


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


def test_clear_clip_cc_calls_clip_clear_envelope(loaded_actions):
    """B-22 fix: clear routes through clip.clear_envelope(target), not the
    removed Envelope.clear() method.
    """
    ctx, clip = _track_with_clip()
    resp = dispatch(
        Request(
            tool="ableton_automation", action="clear",
            params={
                "target_kind": "clip_cc",
                "track_index": 1, "location": "session", "clip_index": 1,
                "cc_number": 7,
            },
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert resp.result["cleared"] is True
    assert ("cc", 7) in clip.clear_envelope_calls


def test_clear_clip_cc_translates_typed_boundary_error(loaded_actions):
    """Wave-2 W2-10 sibling of the write-side test: clear_handler also
    wraps Live's typed-boundary ArgumentError on the tuple sentinel
    via _translate_envelope_target_error. Mirror the write test so
    the symmetric path stays covered against future refactors.
    """
    ctx, clip = _track_with_clip()

    def _typed_reject(target):
        raise TypeError(
            "ArgumentError: Python argument types in "
            "Clip.clear_envelope(Clip, tuple) did not match C++ "
            "signature: clear_envelope(TPyHandle<AClip>, "
            "TPyHandle<ATimeableValue>)"
        )

    clip.clear_envelope = _typed_reject  # noqa: SLF001 — test override
    resp = dispatch(
        Request(
            tool="ableton_automation", action="clear",
            params={
                "target_kind": "clip_cc",
                "track_index": 1, "location": "session", "clip_index": 1,
                "cc_number": 7,
            },
        ),
        context=ctx,
    )
    assert resp.ok is False
    err = (resp.error or "")
    assert "clip_cc" in err
    assert "LOM" in err
    assert "replace_notes" in err


def test_clear_mixer_volume_arrangement_clip_raises_teaching_error(loaded_actions):
    """Wave-2 W2-10 / Critic W2-E #3: write_envelope rejects arrangement
    location for mixer/pan/send/device_parameter; clear must symmetrically
    surface the same teaching error rather than reaching Live's raw
    rejection.
    """
    ctx, _ = _track_with_clip()
    ctx.song.tracks[0].arrangement_clips = (
        ctx.song.tracks[0].clip_slots[0].clip,
    )
    resp = dispatch(
        Request(
            tool="ableton_automation", action="clear",
            params={
                "target_kind": "mixer_volume",
                "track_index": 1,
                "location": "arrangement",
                "clip_index": 1,
            },
        ),
        context=ctx,
    )
    assert resp.ok is False
    err = (resp.error or "")
    assert "arrangement clip" in err
    assert "session" in err.lower()


def test_clear_mixer_volume_without_clip_raises_teaching_error(loaded_actions):
    """B-25 sibling: clear-without-clip surfaces the same gap as write."""
    track = FakeTrack()
    ctx = FakeCtx(FakeSong(tracks=[track]))
    resp = dispatch(
        Request(
            tool="ableton_automation", action="clear",
            params={"target_kind": "mixer_volume", "track_index": 1},
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "clip_index" in (resp.error or "").lower()


def test_clear_mixer_volume_clip_scoped(loaded_actions):
    """Clip-scoped clear hits clip.clear_envelope with the volume param."""
    ctx, clip = _track_with_clip()
    track = ctx.song.tracks[0]
    resp = dispatch(
        Request(
            tool="ableton_automation", action="clear",
            params={
                "target_kind": "mixer_volume",
                "track_index": 1, "location": "session", "clip_index": 1,
            },
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert resp.result["cleared"] is True
    assert track.mixer_device.volume in clip.clear_envelope_calls


def test_clear_note_expression_raises_teaching_error(loaded_actions):
    """note_expression clear isn't exposed in Live 12.4 — surface the gap
    rather than silently doing nothing or crashing.
    """
    ctx, _ = _track_with_clip()
    resp = dispatch(
        Request(
            tool="ableton_automation", action="clear",
            params={
                "target_kind": "note_expression",
                "track_index": 1, "location": "session", "clip_index": 1,
                "note_pitch": 60, "note_start_beats": 1.0, "axis": "pitch",
            },
        ),
        context=ctx,
    )
    assert resp.ok is False
    err = (resp.error or "").lower()
    assert "note_expression" in err
    assert "clear_all" in err  # points at the working alternative


# W6-A: missing-arg validation precedes the gap raise — matches the
# clip_cc branch's "validate cc_number first" precedent. Without these
# tests, a future refactor could silently re-flip the precedence and
# mask a missing-axis error behind a "not supported" error, giving the
# agent two things to debug instead of one.


def test_clear_note_expression_missing_axis_raises_value_error_first(loaded_actions):
    """When note_expression args are missing, the missing-arg ValueError
    fires BEFORE the gap NotImplementedError. The agent sees the actionable
    error (missing axis) rather than the structural one (not supported)."""
    ctx, _ = _track_with_clip()
    resp = dispatch(
        Request(
            tool="ableton_automation", action="clear",
            params={
                "target_kind": "note_expression",
                "track_index": 1, "location": "session", "clip_index": 1,
                "note_pitch": 60, "note_start_beats": 1.0,
                # axis intentionally omitted
            },
        ),
        context=ctx,
    )
    assert resp.ok is False
    err = (resp.error or "").lower()
    assert "requires note_pitch" in err or "axis" in err
    # Critically: the gap message must NOT be what surfaces.
    assert "clear_all" not in err


def test_clear_note_expression_invalid_axis_raises_value_error_first(loaded_actions):
    """Same precedence applies to invalid (not just missing) args."""
    ctx, _ = _track_with_clip()
    resp = dispatch(
        Request(
            tool="ableton_automation", action="clear",
            params={
                "target_kind": "note_expression",
                "track_index": 1, "location": "session", "clip_index": 1,
                "note_pitch": 60, "note_start_beats": 1.0, "axis": "volume",
            },
        ),
        context=ctx,
    )
    assert resp.ok is False
    err = (resp.error or "").lower()
    assert "axis" in err and "volume" in err
    assert "clear_all" not in err


def test_write_envelope_note_expression_validation_uses_shared_helper(loaded_actions):
    """Cross-check: write_envelope's note_expression branch produces the
    SAME error text as clear's note_expression branch when args are
    missing. Pins the shared-helper extraction — both paths route through
    _require_note_expression_args."""
    ctx, _ = _track_with_clip()
    resp = dispatch(
        Request(
            tool="ableton_automation", action="write_envelope",
            params={
                "target_kind": "note_expression",
                "track_index": 1, "location": "session", "clip_index": 1,
                "note_pitch": 60, "note_start_beats": 1.0,
                # axis intentionally omitted
                "breakpoints": [
                    {"time_beats": 0.0, "value": 0.0},
                    {"time_beats": 1.0, "value": 0.5},
                ],
            },
        ),
        context=ctx,
    )
    assert resp.ok is False
    err = (resp.error or "").lower()
    assert "requires note_pitch" in err


# ---------- clear_all ----------


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


def test_clear_all_clip_scoped_calls_clip_clear_all(loaded_actions):
    ctx, clip = _track_with_clip()
    resp = dispatch(
        Request(
            tool="ableton_automation", action="clear_all",
            params={
                "track_index": 1, "location": "session", "clip_index": 1,
            },
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert resp.result["cleared_scope"] == "clip"
    assert clip.clear_all_calls == 1


def test_clear_all_track_scoped_iterates_all_clips(loaded_actions):
    """B-25: there is no atomic Track.clear_all_envelopes on Live 12.4.
    The handler iterates the parent's arrangement clips + occupied session
    slots and calls clear_all_envelopes() on each. The response carries
    the count.
    """
    track = FakeTrack()
    arr_clip_a = FakeClip()
    arr_clip_b = FakeClip()
    track.arrangement_clips = [arr_clip_a, arr_clip_b]
    session_clip = FakeClip()
    track.clip_slots[0].clip = session_clip
    # slots[1..3] empty — handler should skip them
    ctx = FakeCtx(FakeSong(tracks=[track]))
    resp = dispatch(
        Request(
            tool="ableton_automation", action="clear_all",
            params={"track_index": 1},
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.error
    assert resp.result["cleared_scope"] == "track"
    assert resp.result["clips_cleared"] == 3
    assert arr_clip_a.clear_all_calls == 1
    assert arr_clip_b.clear_all_calls == 1
    assert session_clip.clear_all_calls == 1


def test_clear_all_track_scoped_with_no_clips_reports_zero(loaded_actions):
    """A track with no clips reports clips_cleared=0 rather than erroring —
    the operation is well-defined (clear all of nothing = no-op).
    """
    track = FakeTrack()
    ctx = FakeCtx(FakeSong(tracks=[track]))
    resp = dispatch(
        Request(
            tool="ableton_automation", action="clear_all",
            params={"track_index": 1},
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert resp.result["clips_cleared"] == 0


def test_clear_all_return_scoped_iterates_clips(loaded_actions):
    """Returns are tracks too — same iterate-and-clear behavior."""
    ret = FakeReturn()
    arr_clip = FakeClip()
    ret.arrangement_clips = [arr_clip]
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack()], returns=[ret]))
    resp = dispatch(
        Request(
            tool="ableton_automation", action="clear_all",
            params={"return_index": 1},
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert resp.result["cleared_scope"] == "return"
    assert resp.result["clips_cleared"] == 1
    assert arr_clip.clear_all_calls == 1


def test_clear_all_requires_some_target(loaded_actions):
    ctx = FakeCtx()
    resp = dispatch(
        Request(tool="ableton_automation", action="clear_all", params={}),
        context=ctx,
    )
    assert resp.ok is False
    assert "track_index" in (resp.error or "") or "return_index" in (resp.error or "")


# ---------- read_envelope (W6-G/W6-H — sampling-based reconstruction) ----------


def _write_then_read(loaded_actions, *, target_kind, write_params, read_params):
    """Helper: write an envelope then read it back. Returns (write_resp, read_resp)."""
    ctx, _clip = _track_with_clip()
    write_resp = dispatch(
        Request(
            tool="ableton_automation", action="write_envelope",
            params={"target_kind": target_kind, **write_params},
        ),
        context=ctx,
    )
    read_resp = dispatch(
        Request(
            tool="ableton_automation", action="read_envelope",
            params={"target_kind": target_kind, **read_params},
        ),
        context=ctx,
    )
    return write_resp, read_resp


def test_read_envelope_mixer_volume_round_trip(loaded_actions):
    """Write a stepped envelope on mixer_volume, read it back, verify
    the reconstructed breakpoints match the writes (within sampling
    resolution)."""
    ctx, _clip = _track_with_clip()
    write_resp = dispatch(
        Request(
            tool="ableton_automation", action="write_envelope",
            params={
                "target_kind": "mixer_volume",
                "track_index": 1, "location": "session", "clip_index": 1,
                "breakpoints": [
                    {"time_beats": 0.0, "value": 0.5},
                    {"time_beats": 1.0, "value": 0.8},
                    {"time_beats": 2.5, "value": 0.3},
                ],
            },
        ),
        context=ctx,
    )
    assert write_resp.ok is True
    read_resp = dispatch(
        Request(
            tool="ableton_automation", action="read_envelope",
            params={
                "target_kind": "mixer_volume",
                "track_index": 1, "location": "session", "clip_index": 1,
                "resolution_beats": 0.01,
            },
        ),
        context=ctx,
    )
    assert read_resp.ok is True, read_resp.error
    r = read_resp.result
    assert r["exists"] is True
    assert r["target_kind"] == "mixer_volume"
    # Reconstruct: expect breakpoints near 0.0, 1.0, 2.5 with values
    # 0.5, 0.8, 0.3 (step localization is within resolution_beats).
    bps = r["breakpoints"]
    times = [bp["time_beats"] for bp in bps]
    values = [bp["value"] for bp in bps]
    # At least one breakpoint with each written value should surface.
    assert any(abs(v - 0.5) < 1e-6 for v in values)
    assert any(abs(v - 0.8) < 1e-6 for v in values)
    assert any(abs(v - 0.3) < 1e-6 for v in values)
    # First breakpoint anchors at the envelope's start.
    assert bps[0]["time_beats"] == 0.0


def test_read_envelope_empty_returns_exists_false(loaded_actions):
    """A target with no envelope ever written returns exists=False —
    no raise. The handler creates-or-returns; the empty envelope
    samples to a single anchor breakpoint at the default value, which
    the handler classifies as 'not musically populated' (exists=False).
    Callers can use exists to short-circuit instead of inspecting the
    single-anchor breakpoint."""
    ctx, _ = _track_with_clip()
    resp = dispatch(
        Request(
            tool="ableton_automation", action="read_envelope",
            params={
                "target_kind": "mixer_volume",
                "track_index": 1, "location": "session", "clip_index": 1,
            },
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert resp.result["exists"] is False
    # The single-anchor default breakpoint is fine; exists=False is the
    # signal that the envelope hasn't been populated.
    assert len(resp.result["breakpoints"]) <= 1


def test_read_envelope_device_parameter_round_trip(loaded_actions):
    """Cross-target-kind canary: device_parameter read works too."""
    ctx, _clip = _track_with_clip()
    # Set up a device with a parameter on the track.
    from typing import Any as _Any
    track = ctx.song.tracks[0]
    param = FakeParam("Threshold", 0.5)

    class _Dev:
        parameters = (param,)

    track.devices = [_Dev()]
    write_resp = dispatch(
        Request(
            tool="ableton_automation", action="write_envelope",
            params={
                "target_kind": "device_parameter",
                "track_index": 1, "location": "session", "clip_index": 1,
                "device_index": 1, "parameter_name": "Threshold",
                "breakpoints": [
                    {"time_beats": 0.0, "value": 0.2},
                    {"time_beats": 1.5, "value": 0.9},
                ],
            },
        ),
        context=ctx,
    )
    assert write_resp.ok is True, write_resp.error
    read_resp = dispatch(
        Request(
            tool="ableton_automation", action="read_envelope",
            params={
                "target_kind": "device_parameter",
                "track_index": 1, "location": "session", "clip_index": 1,
                "device_index": 1, "parameter_name": "Threshold",
                "resolution_beats": 0.01,
            },
        ),
        context=ctx,
    )
    assert read_resp.ok is True, read_resp.error
    r = read_resp.result
    assert r["exists"] is True
    assert r["device_index"] == 1
    assert r["parameter_name"] == "Threshold"
    values = [bp["value"] for bp in r["breakpoints"]]
    assert any(abs(v - 0.2) < 1e-6 for v in values)
    assert any(abs(v - 0.9) < 1e-6 for v in values)


def test_read_envelope_clip_cc_raises_lom_gap(loaded_actions):
    """clip_cc remains blocked by Live 12.4 LOM (same constraint as
    write_envelope)."""
    ctx, _ = _track_with_clip()
    resp = dispatch(
        Request(
            tool="ableton_automation", action="read_envelope",
            params={
                "target_kind": "clip_cc",
                "track_index": 1, "location": "session", "clip_index": 1,
                "cc_number": 64,
            },
        ),
        context=ctx,
    )
    assert resp.ok is False
    err = (resp.error or "").lower()
    assert "clip_cc" in err or "cc" in err
    assert "lom" in err or "12.4" in err


def test_read_envelope_arrangement_clip_raises_gap(loaded_actions):
    """Same Live 12.4 LOM constraint as write_envelope: track-level
    targets on arrangement clips aren't supported."""
    ctx, _ = _track_with_clip()
    resp = dispatch(
        Request(
            tool="ableton_automation", action="read_envelope",
            params={
                "target_kind": "mixer_volume",
                "track_index": 1, "location": "arrangement", "clip_index": 1,
            },
        ),
        context=ctx,
    )
    assert resp.ok is False
    err = (resp.error or "").lower()
    assert "arrangement" in err


def test_read_envelope_resolution_beats_validates(loaded_actions):
    """Non-positive resolution_beats raises a teaching error."""
    ctx, _ = _track_with_clip()
    resp = dispatch(
        Request(
            tool="ableton_automation", action="read_envelope",
            params={
                "target_kind": "mixer_volume",
                "track_index": 1, "location": "session", "clip_index": 1,
                "resolution_beats": 0.0,
            },
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "resolution_beats" in (resp.error or "")


def test_get_envelope_is_read_envelope_alias(loaded_actions):
    """get_envelope and read_envelope return identical shapes — the
    legacy-named action is just an alias for the W6-G/H keystone."""
    ctx, _clip = _track_with_clip()
    # Write something readable.
    dispatch(
        Request(
            tool="ableton_automation", action="write_envelope",
            params={
                "target_kind": "mixer_volume",
                "track_index": 1, "location": "session", "clip_index": 1,
                "breakpoints": [
                    {"time_beats": 0.0, "value": 0.4},
                    {"time_beats": 1.0, "value": 0.7},
                ],
            },
        ),
        context=ctx,
    )
    via_get = dispatch(
        Request(
            tool="ableton_automation", action="get_envelope",
            params={
                "target_kind": "mixer_volume", "track_index": 1,
                "location": "session", "clip_index": 1,
            },
        ),
        context=ctx,
    )
    via_read = dispatch(
        Request(
            tool="ableton_automation", action="read_envelope",
            params={
                "target_kind": "mixer_volume", "track_index": 1,
                "location": "session", "clip_index": 1,
            },
        ),
        context=ctx,
    )
    assert via_get.ok is True and via_read.ok is True
    assert via_get.result == via_read.result


def test_list_returns_gap_error(loaded_actions):
    """list — enumerating envelopes without target identifiers stays
    blocked. Clip.automation_envelopes exists but the per-envelope
    target isn't readable, so per-target read_envelope is the way."""
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_automation", action="list",
            params={"track_index": 1},
        ),
        context=ctx,
    )
    assert resp.ok is False
    err = (resp.error or "").lower()
    # New error text mentions enumeration constraint + the read_envelope
    # workaround.
    assert "enumerat" in err or "list" in err
    assert "read_envelope" in (resp.error or "")


# ---------- run_on_main discipline ----------


def test_automation_execution_marshals_to_main_thread(loaded_actions):
    ctx, _ = _track_with_clip()
    dispatch(
        Request(
            tool="ableton_automation", action="write_envelope",
            params={
                "target_kind": "mixer_volume",
                "track_index": 1, "location": "session", "clip_index": 1,
                "breakpoints": [{"time_beats": 0.0, "value": 0.5}],
            },
        ),
        context=ctx,
    )
    assert ctx.run_on_main_calls == 1
