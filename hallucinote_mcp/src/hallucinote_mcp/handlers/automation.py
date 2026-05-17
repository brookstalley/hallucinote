"""Imperative handlers for ``ableton_automation`` actions.

Seven envelope target families collapse into one ``write_envelope`` action
with a ``target_kind`` discriminator. The handler branches on target_kind
to walk the right Live API path:

  - **clip_cc** — `clip.create_automation_envelope(midi_cc(N))`
  - **clip_pitch_bend** — `clip.create_automation_envelope(midi_pitch_bend)`
  - **note_expression** — `clip.envelope_for_note(pitch, start_beats, axis)`
  - **device_parameter** — `clip.create_automation_envelope(parameter)` where
    parameter is resolved by name on the device's chain
  - **mixer_volume** / **mixer_pan** — track-level automation; clip-less
  - **send_level** — track-level send to a specific return

Each path takes a breakpoints list of `{time_beats, value, curve?}` dicts
and writes via ``envelope.insert_step()`` or ``envelope.add_breakpoint()``.

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
# Shared resolvers (kept tight — write_envelope branches mostly inline)
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


def _apply_envelope(envelope: Any, breakpoints: list[dict[str, Any]]) -> None:
    """Write a sorted breakpoint list to a Live envelope object.

    Live's automation envelope exposes ``clear()`` plus
    ``insert_step(time, duration, value)`` for stepped points and
    ``add_segment(time, duration, start_value, end_value, curve)`` for
    linear/curved segments. We use a uniform pattern: clear then walk
    the breakpoints emitting either insert_step (for 'hold' curve) or
    add_segment (everything else, defaulting to linear).
    """
    envelope.clear()
    for i in range(len(breakpoints) - 1):
        bp = breakpoints[i]
        nxt = breakpoints[i + 1]
        t = bp["time_beats"]
        dur = nxt["time_beats"] - t
        if bp["curve"] == "hold":
            envelope.insert_step(t, dur, bp["value"])
        else:
            # Live's API takes a curve constant; we map our enum to Live's
            # numeric curve hint (defaults to 0.0 = linear).
            envelope.add_segment(
                t, dur, bp["value"], nxt["value"], _curve_to_live(bp["curve"])
            )
    # Final breakpoint: anchor as a zero-duration step so the value holds
    # past the envelope's range without Live extrapolating.
    last = breakpoints[-1]
    envelope.insert_step(last["time_beats"], 0.0, last["value"])


def _curve_to_live(curve: str | None) -> float:
    """Map our curve enum to Live's segment-curve hint (signed 0..1 range)."""
    if curve in (None, "linear", "hold"):
        return 0.0
    if curve == "fast":
        return 1.0   # convex toward the end value
    if curve == "slow":
        return -1.0  # convex toward the start value
    return 0.0


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

    The required identifier set depends on target_kind. The handler validates
    per-kind before walking the Live API.
    """
    if target_kind not in TARGET_KINDS:
        raise ValueError(
            f"target_kind {target_kind!r} not in {list(TARGET_KINDS)}"
        )
    cleaned = _validate_breakpoints(breakpoints)

    if target_kind == "clip_cc":
        if cc_number is None:
            raise ValueError("target_kind='clip_cc' requires cc_number (0-127)")
        if not (0 <= int(cc_number) <= 127):
            raise ValueError(f"cc_number {cc_number} out of MIDI range [0, 127]")
        clip = _require_clip(
            context, track_index=track_index, location=location,
            clip_index=clip_index,
        )
        envelope = clip.create_automation_envelope(
            _midi_cc_envelope_target(clip, int(cc_number))
        )
        _apply_envelope(envelope, cleaned)
    elif target_kind == "clip_pitch_bend":
        clip = _require_clip(
            context, track_index=track_index, location=location,
            clip_index=clip_index,
        )
        envelope = clip.create_automation_envelope(
            _midi_pitch_bend_envelope_target(clip)
        )
        _apply_envelope(envelope, cleaned)
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
        envelope = clip.envelope_for_note(
            int(note_pitch), float(note_start_beats), axis
        )
        _apply_envelope(envelope, cleaned)
    elif target_kind == "device_parameter":
        if device_index is None or parameter_name is None:
            raise ValueError(
                "target_kind='device_parameter' requires device_index and "
                "parameter_name"
            )
        parent = _require_parent(
            context, track_index=track_index, return_index=return_index,
        )
        device = _resolve_device_on(parent, device_index)
        param = _find_parameter(device, parameter_name)
        # Device-parameter envelopes can be clip-local or track-level. M-4
        # supports clip-local: if location+clip_index are set, write to that
        # clip's envelope; otherwise write to the track's arrangement-level
        # automation.
        if location is not None and clip_index is not None:
            clip = _resolve_clip(parent, location, clip_index)
            envelope = clip.create_automation_envelope(param)
        else:
            envelope = parent.automation_envelopes.get(param) \
                if hasattr(parent, "automation_envelopes") else None
            if envelope is None:
                envelope = _create_track_envelope(parent, param)
        _apply_envelope(envelope, cleaned)
    elif target_kind in ("mixer_volume", "mixer_pan"):
        parent = _require_parent(
            context, track_index=track_index, return_index=return_index,
        )
        mixer = parent.mixer_device
        param = mixer.volume if target_kind == "mixer_volume" else mixer.panning
        if location is not None and clip_index is not None:
            clip = _resolve_clip(parent, location, clip_index)
            envelope = clip.create_automation_envelope(param)
        else:
            envelope = _create_track_envelope(parent, param)
        _apply_envelope(envelope, cleaned)
    elif target_kind == "send_level":
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
        send_param = sends[return_index - 1]
        if location is not None and clip_index is not None:
            clip = _resolve_clip(track, location, clip_index)
            envelope = clip.create_automation_envelope(send_param)
        else:
            envelope = _create_track_envelope(track, send_param)
        _apply_envelope(envelope, cleaned)
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
    """Clear one specific envelope. Same identifier set as write_envelope,
    minus breakpoints."""
    if target_kind not in TARGET_KINDS:
        raise ValueError(
            f"target_kind {target_kind!r} not in {list(TARGET_KINDS)}"
        )
    # Strategy: resolve the envelope target the same way write_envelope does,
    # then call envelope.clear() on it. Re-using a single write path with an
    # empty breakpoint list would also work, but keeping clear lightweight
    # avoids the validation cost.
    envelope = _resolve_write_target(
        context, target_kind=target_kind, track_index=track_index,
        return_index=return_index, clip_index=clip_index, location=location,
        device_index=device_index, parameter_name=parameter_name,
        cc_number=cc_number, note_pitch=note_pitch,
        note_start_beats=note_start_beats, axis=axis,
    )
    if envelope is None:
        return {"target_kind": target_kind, "cleared": False, "reason": "no envelope existed"}
    envelope.clear()
    return {"target_kind": target_kind, "cleared": True}


def clear_all_handler(
    context: LiveContext,
    *,
    track_index: int | None = None,
    return_index: int | None = None,
    clip_index: int | None = None,
    location: str | None = None,
) -> dict[str, Any]:
    """Clear ALL envelopes on a clip OR a track/return.

    If clip_index + location are set, clears all of that clip's envelopes.
    Otherwise clears all of the parent (track/return) arrangement-level
    envelopes.
    """
    if location is not None and clip_index is not None:
        if track_index is None:
            raise ValueError("clip-scoped clear_all requires track_index")
        track = _resolve_track(context, track_index)
        clip = _resolve_clip(track, location, clip_index)
        clear_fn = getattr(clip, "clear_all_envelopes", None) \
            or getattr(clip, "remove_automation", None)
        if clear_fn is None:
            raise NotImplementedError(
                "clip does not expose clear_all_envelopes / "
                "remove_automation in this Live version"
            )
        clear_fn()
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
    clear_fn = getattr(parent, "clear_all_envelopes", None) \
        or getattr(parent, "remove_automation", None)
    if clear_fn is None:
        raise NotImplementedError(
            f"{kind} does not expose clear_all_envelopes / "
            "remove_automation in this Live version"
        )
    clear_fn()
    return {"cleared_scope": kind, f"{kind}_index": idx}


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


def _create_track_envelope(parent: Any, param: Any) -> Any:
    """Create or fetch the arrangement-level envelope for a track parameter."""
    creator = getattr(parent, "create_automation_envelope", None)
    if creator is None:
        raise NotImplementedError(
            "track-level (arrangement) automation creation is not exposed "
            "on this parent in this Live version"
        )
    return creator(param)


def _resolve_write_target(
    context: LiveContext,
    *,
    target_kind: str,
    track_index: int | None,
    return_index: int | None,
    clip_index: int | None,
    location: str | None,
    device_index: int | None,
    parameter_name: str | None,
    cc_number: int | None,
    note_pitch: int | None,
    note_start_beats: float | None,
    axis: str | None,
) -> Any:
    """Best-effort resolve of an existing envelope object for a target.

    Used by ``clear``. If no envelope exists, returns None (clear becomes
    a no-op).
    """
    if target_kind in ("clip_cc", "clip_pitch_bend", "note_expression"):
        clip = _require_clip(
            context, track_index=track_index, location=location,
            clip_index=clip_index,
        )
        # The cleanest path is to call envelope_for_target which returns the
        # existing envelope (or None). Fall back to None if absent.
        getter = getattr(clip, "automation_envelope_for", None)
        if getter is None:
            return None
        if target_kind == "clip_cc":
            return getter(_midi_cc_envelope_target(clip, int(cc_number or 0)))
        if target_kind == "clip_pitch_bend":
            return getter(_midi_pitch_bend_envelope_target(clip))
        # note_expression
        getter_note = getattr(clip, "envelope_for_note", None)
        if getter_note is None or note_pitch is None or note_start_beats is None \
                or axis is None:
            return None
        return getter_note(int(note_pitch), float(note_start_beats), axis)
    if target_kind == "device_parameter":
        if device_index is None or parameter_name is None:
            return None
        parent = _require_parent(
            context, track_index=track_index, return_index=return_index,
        )
        device = _resolve_device_on(parent, device_index)
        param = _find_parameter(device, parameter_name)
        if location is not None and clip_index is not None:
            clip = _resolve_clip(parent, location, clip_index)
            getter = getattr(clip, "automation_envelope_for", None)
            return getter(param) if getter else None
        getter = getattr(parent, "automation_envelope_for", None)
        return getter(param) if getter else None
    if target_kind in ("mixer_volume", "mixer_pan"):
        parent = _require_parent(
            context, track_index=track_index, return_index=return_index,
        )
        mixer = parent.mixer_device
        param = mixer.volume if target_kind == "mixer_volume" else mixer.panning
        if location is not None and clip_index is not None:
            clip = _resolve_clip(parent, location, clip_index)
            getter = getattr(clip, "automation_envelope_for", None)
            return getter(param) if getter else None
        getter = getattr(parent, "automation_envelope_for", None)
        return getter(param) if getter else None
    if target_kind == "send_level":
        if track_index is None or return_index is None:
            return None
        track = _resolve_track(context, track_index)
        sends = track.mixer_device.sends
        if return_index < 1 or return_index > len(sends):
            return None
        send_param = sends[return_index - 1]
        if location is not None and clip_index is not None:
            clip = _resolve_clip(track, location, clip_index)
            getter = getattr(clip, "automation_envelope_for", None)
            return getter(send_param) if getter else None
        getter = getattr(track, "automation_envelope_for", None)
        return getter(send_param) if getter else None
    return None


__all__ = [
    "TARGET_KINDS",
    "list_handler",
    "get_envelope_handler",
    "write_envelope_handler",
    "clear_handler",
    "clear_all_handler",
]
