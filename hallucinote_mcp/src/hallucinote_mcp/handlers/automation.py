"""Imperative handlers for ``ableton_automation`` actions.

Seven envelope target families collapse into one ``write_envelope`` action
with a ``target_kind`` discriminator. The handler branches on target_kind
to walk the right Live API path:

  - **clip_cc** — `clip.create_automation_envelope(midi_cc(N))`
  - **clip_pitch_bend** — `clip.create_automation_envelope(midi_pitch_bend)`
  - **note_expression** — `clip.envelope_for_note(pitch, start_beats, axis)`
  - **device_parameter** — `clip.create_automation_envelope(parameter)` where
    parameter is resolved by name on the device's chain
  - **mixer_volume** / **mixer_pan** / **send_level** — likewise routed
    through a containing arrangement (or session) clip's
    ``create_automation_envelope``.

All seven target kinds require a containing ``Clip`` (session or
arrangement). Live 12.4's LOM does NOT expose track-level / parameter-level
envelope creation: ``Track.create_automation_envelope`` and
``Parameter.automation_*`` are not in the public surface (verified against
Live 12 Suite's bundled ``LomTypes`` plus the first-party Push code in
``pushbase/automation_component.py``). The handler surfaces a
``NotImplementedError`` with a teaching message when callers omit
``clip_index + location`` for the mixer/send/device-parameter kinds.

Each path takes a breakpoints list of ``{time_beats, value, curve?}`` dicts
and writes via ``Envelope.insert_step(time, duration, value)``. Live 12.4's
``Envelope`` exposes neither ``clear()`` nor ``add_segment(...)``; pre-clear
goes through the parent clip's ``clear_envelope(target)`` and all
breakpoints are written as stepped regions. The wire's ``curve`` field is
accepted for forward compatibility but recorded as a note when non-step
hints appear (Live 12.4 has no way to apply them).

The handler is push-direction. ``clear`` / ``clear_all`` destroy
envelopes; ``get_envelope`` / ``list`` are gap-blocked stubs (the MCP
read surface for envelopes hasn't landed yet — Hallucinote's pull skill
documents this as a blocked domain).

Time is in **beats** on the wire. The Hallucinote planner converts from
bar-based song positions via its time-signature map before emit. MCP
stays meter-agnostic — same principle as ``ableton_clip``.
"""
from __future__ import annotations

from typing import Any

from ..dispatcher import LiveContext


TARGET_KINDS: tuple[str, ...] = (
    "clip_cc",
    "clip_pitch_bend",
    "note_expression",
    "device_parameter",
    "mixer_volume",
    "mixer_pan",
    "send_level",
)

# Kinds that REQUIRE a containing clip on Live 12.4 (used for the teaching
# error when callers omit clip_index + location).
_CLIP_REQUIRED_KINDS: frozenset[str] = frozenset({
    "device_parameter", "mixer_volume", "mixer_pan", "send_level",
})


_TRACK_LEVEL_GAP_HINT = (
    "target_kind={target_kind!r} requires clip_index + location on Live "
    "12.4: the LOM does not expose track-level (clip-less) envelope "
    "creation for mixer / send / device-parameter automation. Provide "
    "location='arrangement' (or 'session') and clip_index pointing at "
    "the containing clip. Live's UI shows free track lanes, but the "
    "Python API only addresses envelopes through Clip."
)


# ---------------------------------------------------------------------------
# Read-side gap stubs
# ---------------------------------------------------------------------------


_ENVELOPE_READ_GAP_HINT = (
    "ableton_automation read operations (list, get_envelope) are blocked "
    "by the MCP envelope read surface gap — Live's API does not yet "
    "expose a stable iterator over a clip's / track's existing envelopes "
    "through the Remote Script. Schema is registered for surface "
    "stability; implementation lands once the underlying read surface is "
    "in place. To write a fresh envelope, use "
    "ableton_automation(action='write_envelope', target_kind=...). To "
    "destroy envelopes, use action='clear' or action='clear_all'."
)


def list_handler(
    context: LiveContext,
    *,
    track_index: int | None = None,
    return_index: int | None = None,
    clip_index: int | None = None,
    location: str | None = None,
) -> dict[str, Any]:
    raise NotImplementedError(_ENVELOPE_READ_GAP_HINT)


def get_envelope_handler(
    context: LiveContext,
    *,
    target_kind: str,
    track_index: int | None = None,
    return_index: int | None = None,
    clip_index: int | None = None,
    location: str | None = None,
    device_index: int | None = None,
    parameter_name: str | None = None,
    cc_number: int | None = None,
    note_pitch: int | None = None,
    note_start_beats: float | None = None,
    axis: str | None = None,
) -> dict[str, Any]:
    raise NotImplementedError(_ENVELOPE_READ_GAP_HINT)


# ---------------------------------------------------------------------------
# Shared resolvers
# ---------------------------------------------------------------------------


def _resolve_track(context: LiveContext, track_index: int) -> Any:
    song = context.song
    if track_index < 1 or track_index > len(song.tracks):
        raise IndexError(
            f"track_index {track_index} out of range [1, {len(song.tracks)}]"
        )
    return song.tracks[track_index - 1]


def _resolve_clip(track: Any, location: str, clip_index: int) -> Any:
    if location == "session":
        slots = track.clip_slots
        if clip_index < 1 or clip_index > len(slots):
            raise IndexError(
                f"clip_index {clip_index} out of range [1, {len(slots)}] "
                "(session view)"
            )
        clip = slots[clip_index - 1].clip
        if clip is None:
            raise IndexError(
                f"session slot {clip_index} is empty; create a clip first"
            )
        return clip
    if location == "arrangement":
        arr_clips = track.arrangement_clips
        if clip_index < 1 or clip_index > len(arr_clips):
            raise IndexError(
                f"clip_index {clip_index} out of range "
                f"[1, {len(arr_clips)}] (arrangement view)"
            )
        return arr_clips[clip_index - 1]
    raise ValueError(
        f"location must be 'session' or 'arrangement', got {location!r}"
    )


def _resolve_device_on(parent: Any, device_index: int) -> Any:
    devices = parent.devices
    if device_index < 1 or device_index > len(devices):
        raise IndexError(
            f"device_index {device_index} out of range [1, {len(devices)}]"
        )
    return devices[device_index - 1]


def _find_parameter(device: Any, parameter_name: str) -> Any:
    for p in getattr(device, "parameters", ()):
        if p.name == parameter_name:
            return p
    available = [p.name for p in getattr(device, "parameters", ())]
    raise ValueError(
        f"parameter {parameter_name!r} not found; available: {available}"
    )


_CURVE_KINDS = ("linear", "hold", "fast", "slow")


def _validate_breakpoints(breakpoints: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Validate the wire breakpoint shape; return a cleaned list.

    Each breakpoint: {time_beats: float >= 0, value: float, curve?: enum}.
    Time MUST be monotonically non-decreasing (Live's envelope API requires
    sorted breakpoints; we catch bad orderings upfront with a teaching
    error rather than letting Live reject the whole envelope).
    """
    if not isinstance(breakpoints, list) or not breakpoints:
        raise ValueError(
            "breakpoints must be a non-empty list of "
            "{time_beats, value, curve?} dicts"
        )
    cleaned: list[dict[str, Any]] = []
    prev_time: float | None = None
    for i, bp in enumerate(breakpoints):
        if "time_beats" not in bp:
            raise ValueError(
                f"breakpoint {i} missing required 'time_beats': {bp!r}"
            )
        if "value" not in bp:
            raise ValueError(
                f"breakpoint {i} missing required 'value': {bp!r}"
            )
        t = float(bp["time_beats"])
        v = float(bp["value"])
        if t < 0:
            raise ValueError(
                f"breakpoint {i}: time_beats {t} must be >= 0"
            )
        if prev_time is not None and t < prev_time:
            raise ValueError(
                f"breakpoint {i}: time_beats {t} < previous {prev_time}; "
                "envelope breakpoints must be sorted by time"
            )
        prev_time = t
        curve = bp.get("curve")
        if curve is not None and curve not in _CURVE_KINDS:
            raise ValueError(
                f"breakpoint {i}: curve {curve!r} not in {list(_CURVE_KINDS)}"
            )
        cleaned.append({"time_beats": t, "value": v, "curve": curve})
    return cleaned


def _write_breakpoints_as_steps(
    envelope: Any, breakpoints: list[dict[str, Any]]
) -> bool:
    """Walk breakpoints emitting ``insert_step`` calls.

    Live 12.4's ``Envelope`` only exposes ``insert_step(time, duration,
    value)`` — there is no ``add_segment`` for linear/curved transitions.
    Each segment between consecutive breakpoints becomes one stepped region;
    a final zero-duration step anchors the last value so it holds without
    extrapolation past the envelope's range.

    Returns True if any non-'hold' curve hint was present — the caller can
    surface a note explaining the curve was recorded but not applied.
    """
    non_step_seen = False
    for i in range(len(breakpoints) - 1):
        bp = breakpoints[i]
        nxt = breakpoints[i + 1]
        t = bp["time_beats"]
        dur = nxt["time_beats"] - t
        envelope.insert_step(t, dur, bp["value"])
        if bp.get("curve") not in (None, "hold"):
            non_step_seen = True
    last = breakpoints[-1]
    envelope.insert_step(last["time_beats"], 0.0, last["value"])
    return non_step_seen


def _stepped_envelope_note() -> str:
    return (
        "Live 12.4 LOM exposes only stepped envelopes "
        "(Envelope.insert_step); 'linear'/'fast'/'slow' curve hints were "
        "recorded in the request but applied as step transitions."
    )


# ---------------------------------------------------------------------------
# write_envelope dispatcher (target_kind branching)
# ---------------------------------------------------------------------------


def write_envelope_handler(
    context: LiveContext,
    *,
    target_kind: str,
    breakpoints: list[dict[str, Any]],
    track_index: int | None = None,
    return_index: int | None = None,
    clip_index: int | None = None,
    location: str | None = None,
    device_index: int | None = None,
    parameter_name: str | None = None,
    cc_number: int | None = None,
    note_pitch: int | None = None,
    note_start_beats: float | None = None,
    axis: str | None = None,
) -> dict[str, Any]:
    """Write a single automation envelope.

    The required identifier set depends on target_kind. The handler
    validates per-kind before walking the Live API. All seven target kinds
    require a containing clip (session or arrangement) on Live 12.4 —
    callers that omit ``clip_index + location`` for the mixer / send /
    device-parameter kinds get a ``NotImplementedError`` citing the LOM
    gap.
    """
    if target_kind not in TARGET_KINDS:
        raise ValueError(
            f"target_kind {target_kind!r} not in {list(TARGET_KINDS)}"
        )
    cleaned = _validate_breakpoints(breakpoints)

    non_step_seen = False
    if target_kind == "clip_cc":
        if cc_number is None:
            raise ValueError("target_kind='clip_cc' requires cc_number (0-127)")
        if not (0 <= int(cc_number) <= 127):
            raise ValueError(f"cc_number {cc_number} out of MIDI range [0, 127]")
        clip = _require_clip(
            context, track_index=track_index, location=location,
            clip_index=clip_index,
        )
        target = _midi_cc_envelope_target(clip, int(cc_number))
        clip.clear_envelope(target)
        envelope = clip.create_automation_envelope(target)
        non_step_seen = _write_breakpoints_as_steps(envelope, cleaned)
    elif target_kind == "clip_pitch_bend":
        clip = _require_clip(
            context, track_index=track_index, location=location,
            clip_index=clip_index,
        )
        target = _midi_pitch_bend_envelope_target(clip)
        clip.clear_envelope(target)
        envelope = clip.create_automation_envelope(target)
        non_step_seen = _write_breakpoints_as_steps(envelope, cleaned)
    elif target_kind == "note_expression":
        if note_pitch is None or note_start_beats is None or axis is None:
            raise ValueError(
                "target_kind='note_expression' requires note_pitch, "
                "note_start_beats, and axis (one of 'pitch'|'pressure'|'timbre')"
            )
        if axis not in ("pitch", "pressure", "timbre"):
            raise ValueError(
                f"axis {axis!r} not in ['pitch', 'pressure', 'timbre']"
            )
        clip = _require_clip(
            context, track_index=track_index, location=location,
            clip_index=clip_index,
        )
        # Note-expression envelopes have their own factory (envelope_for_note)
        # rather than the create_automation_envelope path; Live exposes no
        # equivalent clear-by-target for them, so insert_step's overwrite
        # semantics handle replacement within the breakpoint range.
        envelope = clip.envelope_for_note(
            int(note_pitch), float(note_start_beats), axis
        )
        non_step_seen = _write_breakpoints_as_steps(envelope, cleaned)
    elif target_kind in _CLIP_REQUIRED_KINDS:
        if clip_index is None or location is None:
            raise NotImplementedError(
                _TRACK_LEVEL_GAP_HINT.format(target_kind=target_kind)
            )
        if target_kind == "device_parameter":
            if device_index is None or parameter_name is None:
                raise ValueError(
                    "target_kind='device_parameter' requires device_index "
                    "and parameter_name"
                )
            parent = _require_parent(
                context, track_index=track_index, return_index=return_index,
            )
            device = _resolve_device_on(parent, device_index)
            target = _find_parameter(device, parameter_name)
            clip = _resolve_clip(parent, location, clip_index)
        elif target_kind in ("mixer_volume", "mixer_pan"):
            parent = _require_parent(
                context, track_index=track_index, return_index=return_index,
            )
            mixer = parent.mixer_device
            target = mixer.volume if target_kind == "mixer_volume" else mixer.panning
            clip = _resolve_clip(parent, location, clip_index)
        else:  # send_level
            if return_index is None:
                raise ValueError(
                    "target_kind='send_level' requires return_index "
                    "(the destination return for the send)"
                )
            if track_index is None:
                raise ValueError(
                    "target_kind='send_level' requires track_index "
                    "(the source track of the send)"
                )
            track = _resolve_track(context, track_index)
            sends = track.mixer_device.sends
            if return_index < 1 or return_index > len(sends):
                raise IndexError(
                    f"return_index {return_index} out of range "
                    f"[1, {len(sends)}] for track {track_index}"
                )
            target = sends[return_index - 1]
            clip = _resolve_clip(track, location, clip_index)
        clip.clear_envelope(target)
        envelope = clip.create_automation_envelope(target)
        non_step_seen = _write_breakpoints_as_steps(envelope, cleaned)
    else:
        # Defensive — enum validation above should have caught this.
        raise ValueError(f"unhandled target_kind {target_kind!r}")

    result: dict[str, Any] = {
        "target_kind": target_kind,
        "breakpoints_written": len(cleaned),
    }
    if track_index is not None:
        result["track_index"] = track_index
    if return_index is not None:
        result["return_index"] = return_index
    if clip_index is not None:
        result["clip_index"] = clip_index
    if location is not None:
        result["location"] = location
    if device_index is not None:
        result["device_index"] = device_index
    if parameter_name is not None:
        result["parameter_name"] = parameter_name
    if non_step_seen:
        result["notes"] = [_stepped_envelope_note()]
    return result


# ---------------------------------------------------------------------------
# clear / clear_all
# ---------------------------------------------------------------------------


def clear_handler(
    context: LiveContext,
    *,
    target_kind: str,
    track_index: int | None = None,
    return_index: int | None = None,
    clip_index: int | None = None,
    location: str | None = None,
    device_index: int | None = None,
    parameter_name: str | None = None,
    cc_number: int | None = None,
    note_pitch: int | None = None,
    note_start_beats: float | None = None,
    axis: str | None = None,
) -> dict[str, Any]:
    """Clear one specific envelope.

    Same identifier set as write_envelope, minus breakpoints. Clip-scoped
    on Live 12.4 — same gap rationale as ``write_envelope`` for the
    mixer / send / device-parameter kinds.

    Returns ``cleared: True`` after invoking ``clip.clear_envelope(target)``.
    Live's API is idempotent (no-op when no envelope existed) but does not
    expose a way to inspect existence first, so we always report True.
    Callers needing the "was-it-present" signal should pair this with
    ``get_envelope`` once the read-surface gap closes.
    """
    if target_kind not in TARGET_KINDS:
        raise ValueError(
            f"target_kind {target_kind!r} not in {list(TARGET_KINDS)}"
        )
    if target_kind == "clip_cc":
        if cc_number is None:
            raise ValueError(
                "clear with target_kind='clip_cc' requires cc_number — "
                "matches write_envelope's requirement for the same kind"
            )
        clip = _require_clip(
            context, track_index=track_index, location=location,
            clip_index=clip_index,
        )
        target = _midi_cc_envelope_target(clip, int(cc_number))
        clip.clear_envelope(target)
        return {"target_kind": target_kind, "cleared": True}
    if target_kind == "clip_pitch_bend":
        clip = _require_clip(
            context, track_index=track_index, location=location,
            clip_index=clip_index,
        )
        target = _midi_pitch_bend_envelope_target(clip)
        clip.clear_envelope(target)
        return {"target_kind": target_kind, "cleared": True}
    if target_kind == "note_expression":
        # Live 12.4 has no documented per-axis clear for note-expression
        # envelopes through Clip.clear_envelope (which expects a Parameter-
        # shaped target, not the note-expression envelope target). Direct
        # callers should fall back to action='clear_all' on the clip.
        raise NotImplementedError(
            "clear with target_kind='note_expression' is not exposed by "
            "Live 12.4's LOM (clear_envelope expects a Parameter target; "
            "envelope_for_note returns the envelope but no symmetric "
            "clear factory exists). Use action='clear_all' to clear all "
            "envelopes on the containing clip."
        )

    # device_parameter / mixer_volume / mixer_pan / send_level
    if clip_index is None or location is None:
        raise NotImplementedError(
            _TRACK_LEVEL_GAP_HINT.format(target_kind=target_kind)
        )
    if target_kind == "device_parameter":
        if device_index is None or parameter_name is None:
            raise ValueError(
                "clear with target_kind='device_parameter' requires "
                "device_index and parameter_name (matches write_envelope)"
            )
        parent = _require_parent(
            context, track_index=track_index, return_index=return_index,
        )
        device = _resolve_device_on(parent, device_index)
        target = _find_parameter(device, parameter_name)
        clip = _resolve_clip(parent, location, clip_index)
    elif target_kind in ("mixer_volume", "mixer_pan"):
        parent = _require_parent(
            context, track_index=track_index, return_index=return_index,
        )
        mixer = parent.mixer_device
        target = mixer.volume if target_kind == "mixer_volume" else mixer.panning
        clip = _resolve_clip(parent, location, clip_index)
    else:  # send_level
        if return_index is None or track_index is None:
            raise ValueError(
                "clear with target_kind='send_level' requires track_index "
                "AND return_index"
            )
        track = _resolve_track(context, track_index)
        sends = track.mixer_device.sends
        if return_index < 1 or return_index > len(sends):
            raise IndexError(
                f"return_index {return_index} out of range "
                f"[1, {len(sends)}] for track {track_index}"
            )
        target = sends[return_index - 1]
        clip = _resolve_clip(track, location, clip_index)
    clip.clear_envelope(target)
    return {"target_kind": target_kind, "cleared": True}


def clear_all_handler(
    context: LiveContext,
    *,
    track_index: int | None = None,
    return_index: int | None = None,
    clip_index: int | None = None,
    location: str | None = None,
) -> dict[str, Any]:
    """Clear ALL envelopes on a clip OR on every clip of a track/return.

    Clip-scoped (``track_index + location + clip_index``): one direct call
    to ``clip.clear_all_envelopes()``.

    Parent-scoped (``track_index`` or ``return_index`` only): Live 12.4
    does NOT expose an atomic track-level clear. We iterate the parent's
    arrangement clips and session-view clips (skipping empty slots) and
    invoke ``clear_all_envelopes()`` on each. The response carries the
    count so callers know whether the operation touched anything.
    """
    if location is not None and clip_index is not None:
        if track_index is None:
            raise ValueError("clip-scoped clear_all requires track_index")
        track = _resolve_track(context, track_index)
        clip = _resolve_clip(track, location, clip_index)
        clip.clear_all_envelopes()
        return {
            "cleared_scope": "clip",
            "track_index": track_index,
            "location": location,
            "clip_index": clip_index,
        }
    parent: Any
    if track_index is not None:
        parent = _resolve_track(context, track_index)
        kind = "track"
        idx = track_index
    elif return_index is not None:
        song = context.song
        if return_index < 1 or return_index > len(song.return_tracks):
            raise IndexError(
                f"return_index {return_index} out of range "
                f"[1, {len(song.return_tracks)}]"
            )
        parent = song.return_tracks[return_index - 1]
        kind = "return"
        idx = return_index
    else:
        raise ValueError(
            "clear_all requires track_index or return_index (clip-scoped "
            "clear additionally needs location + clip_index)"
        )
    cleared_count = _clear_all_on_parent_clips(parent)
    return {
        "cleared_scope": kind,
        f"{kind}_index": idx,
        "clips_cleared": cleared_count,
    }


def _clear_all_on_parent_clips(parent: Any) -> int:
    """Iterate every clip on the parent (arrangement + occupied session
    slots) and clear envelopes on each. Returns the count for caller
    response payloads.

    Live 12.4's LOM has no atomic ``Track.clear_all_envelopes`` —
    automation lives on the contained Clip objects, so a track-wide clear
    is an explicit fan-out. ``clear_all_envelopes`` is exposed on
    ``Live.Clip.Clip`` (verified via pushbase / _Framework usage).
    """
    count = 0
    for clip in getattr(parent, "arrangement_clips", ()):
        clip.clear_all_envelopes()
        count += 1
    for slot in getattr(parent, "clip_slots", ()):
        clip = getattr(slot, "clip", None)
        if clip is None:
            continue
        clip.clear_all_envelopes()
        count += 1
    return count


# ---------------------------------------------------------------------------
# Internal resolvers
# ---------------------------------------------------------------------------


def _require_clip(
    context: LiveContext,
    *,
    track_index: int | None,
    location: str | None,
    clip_index: int | None,
) -> Any:
    if track_index is None or location is None or clip_index is None:
        raise ValueError(
            "this target_kind requires track_index + location + clip_index"
        )
    track = _resolve_track(context, track_index)
    return _resolve_clip(track, location, clip_index)


def _require_parent(
    context: LiveContext,
    *,
    track_index: int | None,
    return_index: int | None,
) -> Any:
    if track_index is not None and return_index is not None:
        raise ValueError(
            "specify exactly one of track_index / return_index, not both"
        )
    if track_index is not None:
        return _resolve_track(context, track_index)
    if return_index is not None:
        song = context.song
        if return_index < 1 or return_index > len(song.return_tracks):
            raise IndexError(
                f"return_index {return_index} out of range "
                f"[1, {len(song.return_tracks)}]"
            )
        return song.return_tracks[return_index - 1]
    raise ValueError("must specify track_index or return_index")


def _midi_cc_envelope_target(clip: Any, cc_number: int) -> Any:
    """Build the Live envelope target for a clip-CC envelope."""
    factory = getattr(clip, "envelope_target_for_cc", None)
    if factory is not None:
        return factory(int(cc_number))
    # Fallback for older / mock APIs: return a structural sentinel that the
    # test fakes recognize.
    return ("cc", int(cc_number))


def _midi_pitch_bend_envelope_target(clip: Any) -> Any:
    factory = getattr(clip, "envelope_target_for_pitch_bend", None)
    if factory is not None:
        return factory()
    return ("pitch_bend",)


__all__ = [
    "TARGET_KINDS",
    "list_handler",
    "get_envelope_handler",
    "write_envelope_handler",
    "clear_handler",
    "clear_all_handler",
]
