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
    through a containing **session** clip's ``create_automation_envelope``;
    then ``ableton_clip(action='duplicate_to_arrangement')`` snapshot-copies
    the envelope into the arrangement.

All seven target kinds require a containing ``Clip``. Live 12.4's LOM does
NOT expose track-level / parameter-level envelope creation:
``Track.create_automation_envelope`` and ``Parameter.automation_*`` are not
in the public surface (verified against Live 12 Suite's bundled ``LomTypes``
plus the first-party Push code in ``pushbase/automation_component.py``).
For mixer/pan/send/device_parameter targets the clip MUST be a session
clip — Live raises ``RuntimeError("Not a session clip or parameter belongs
to another track.")`` when called on an arrangement clip (W2-10 finding).
The handler surfaces a ``NotImplementedError`` with a teaching message when
callers omit ``clip_index + location`` for the mixer/send/device-parameter
kinds, and a second ``NotImplementedError`` when ``location='arrangement'``
is passed for those kinds.

Each path takes a breakpoints list of ``{time_beats, value, curve?}`` dicts
and writes via ``Envelope.insert_step(time, duration, value)``. Live 12.4's
``Envelope`` exposes neither ``clear()`` nor ``add_segment(...)``; pre-clear
goes through the parent clip's ``clear_envelope(target)`` and all
breakpoints are written as stepped regions. The wire's ``curve`` field is
accepted for forward compatibility but recorded as a note when non-step
hints appear (Live 12.4 has no way to apply them).

The module covers both directions. ``write_envelope`` is the write
keystone; ``clear`` / ``clear_all`` destroy envelopes; ``read_envelope``
/ ``get_envelope`` (alias) read via sampling-based reconstruction
(W6-G/H 2026-05-19) — Live exposes only ``envelope.value_at_time(t)``,
not breakpoint enumeration, so the handler samples and reconstructs
step transitions. Covers 5 of 7 target_kinds; clip_cc / clip_pitch_bend
remain LOM-blocked on the read side same as the write side. ``list``
(target-less enumeration) stays blocked: enumerating
``Clip.automation_envelopes`` yields envelope objects but the
canonical-id mapping back to a *target_kind + addressing args*
shape would need to invert every target-resolution branch. The
targeted read path is the supported route.

Time is in **beats** on the wire. The Hallucinote planner converts from
bar-based song positions via its time-signature map before emit. MCP
stays meter-agnostic — same principle as ``ableton_clip``.
"""
from __future__ import annotations

import logging
import math as _math
import time
from dataclasses import dataclass
from typing import Any, Callable

from ..dispatcher import LiveContext


logger = logging.getLogger(__name__)


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
    "location='session' and clip_index pointing at a session clip on the "
    "target track; then ableton_clip(action='duplicate_to_arrangement') "
    "carries the envelope into the arrangement. Live 12.4 rejects these "
    "target kinds on arrangement clips outright. Live's UI shows free "
    "track lanes, but the Python API only addresses envelopes through Clip."
)


# ---------------------------------------------------------------------------
# Read-side gap stubs
# ---------------------------------------------------------------------------


# W6-G/W6-H: envelope read surface.
#
# Live 12's AutomationEnvelope exposes only two public methods:
# insert_step(time, duration, value) and value_at_time(time). There is
# NO breakpoint enumeration API. To read an envelope's shape we must
# sample value_at_time() across the clip's range and reconstruct step
# transitions from the sample sequence. The reconstruction is lossy at
# the sample resolution but musically faithful at 1/96 beat resolution
# (~3ms at 120BPM, well below human perception).
#
# `list_handler` and `get_envelope_handler` are retained as the
# original action names; `read_envelope_handler` is the new keystone
# that reads a specific target_kind. list_handler remains gap-blocked
# for a different reason than originally documented: `envelope.parameter`
# IS accessible (W7-0 smoke 2026-05-19 confirmed it empirically and the
# fix relies on it), so iteration is possible — but mapping a Live
# parameter back to a *target_kind + addressing args* response shape
# requires inverting every target-resolution branch, which the
# targeted read path already handles. Until a consumer needs
# bulk-enumeration, the targeted path is the supported route.


_ENVELOPE_LIST_GAP_HINT = (
    "ableton_automation(action='list') — bulk enumeration without a "
    "target_kind isn't currently supported. The list would need to "
    "invert every target-resolution branch to map each "
    "Clip.automation_envelopes entry back to a (target_kind, "
    "addressing-args) tuple. Use "
    "ableton_automation(action='read_envelope', target_kind=..., ...) "
    "with a specific target instead — the same addressing args as "
    "write_envelope / clear."
)


def list_handler(
    context: LiveContext,
    *,
    track_index: int | None = None,
    return_index: int | None = None,
    clip_index: int | None = None,
    location: str | None = None,
) -> dict[str, Any]:
    raise NotImplementedError(_ENVELOPE_LIST_GAP_HINT)


# Sampling resolution for value_at_time reconstruction. 1/96 beat
# ≈ 3.1ms at 120BPM, finer than Live's MIDI tick resolution. Tuneable
# per-call via the `resolution_beats` param.
_DEFAULT_ENVELOPE_READ_RESOLUTION = 1.0 / 96.0


def _sample_envelope_to_breakpoints(
    envelope: Any,
    *,
    start_beats: float,
    end_beats: float,
    resolution_beats: float,
) -> list[dict[str, float]]:
    """Sample envelope.value_at_time across [start_beats, end_beats] at
    resolution_beats, emit a breakpoint at every detected step
    transition.

    Reconstruction quality scales with resolution. Same-value runs collapse
    to a single breakpoint (Live's stepped envelope is already idempotent
    on repeated identical values — same audible behavior). Step
    transitions are localized to within resolution_beats of their actual
    position; for finer fidelity, callers can pass a smaller resolution.

    Always emits a breakpoint at start_beats (the envelope's anchor) so
    callers can round-trip an envelope that begins with the same value
    as its initial state without losing the anchor.
    """
    if end_beats <= start_beats:
        return []
    if resolution_beats <= 0:
        raise ValueError(f"resolution_beats must be > 0, got {resolution_beats}")
    n_steps = int(_math.ceil((end_beats - start_beats) / resolution_beats))
    breakpoints: list[dict[str, float]] = []
    prev: float | None = None
    for i in range(n_steps + 1):
        t = min(start_beats + i * resolution_beats, end_beats)
        v = float(envelope.value_at_time(t))
        if prev is None or abs(v - prev) > 1e-9:
            breakpoints.append({"time_beats": float(t), "value": v})
            prev = v
    return breakpoints


def _params_equal(p1: Any, p2: Any) -> bool:
    """Compare two Live ``DeviceParameter`` objects for identity.

    Live re-wraps API objects across calls so ``is`` is unreliable
    (learnings.md: ``Never use `is` for Live API object identity``).
    ``==`` typically delegates to the underlying C++ object identity and
    works correctly, but we guard against odd plugin objects raising on
    equality by falling back to a name + canonical_parent comparison.
    """
    try:
        if p1 == p2:
            return True
    except Exception:  # prawduct:ok-broad-except — Live wrappers can raise arbitrary types on __eq__
        pass
    n1 = getattr(p1, "name", None)
    n2 = getattr(p2, "name", None)
    if n1 is None or n1 != n2:
        return False
    cp1 = getattr(p1, "canonical_parent", None)
    cp2 = getattr(p2, "canonical_parent", None)
    if cp1 is None or cp2 is None:
        return False
    try:
        return cp1 == cp2
    except Exception:  # prawduct:ok-broad-except — same wrapper-equality risk
        return False


def _find_existing_envelope(clip: Any, target: Any) -> Any | None:
    """Find or create an envelope on ``clip`` for the given ``target``.

    Real Live 12.4's ``Clip.create_automation_envelope(target)`` is **not**
    idempotent when an envelope already exists for the target — it returns
    ``None`` (or raises) rather than returning the bound envelope. W7-0
    smoke (2026-05-19) caught this against real Live: the old assumed-
    idempotent path returned ``exists=False`` on freshly-written envelopes.

    Strategy: iterate ``clip.automation_envelopes`` and match by
    parameter identity (the smoke spec's anticipated remediation). The
    ``Envelope.parameter`` attribute IS accessible on Live 12.4 even
    though the codebase comment around ``list_handler`` previously
    suggested otherwise — the prior gap was about *enumeration without
    a known target*, not about reading ``.parameter`` once you have an
    envelope reference.

    Falls back to ``create_automation_envelope`` for the fresh-target
    case (no existing envelope) — there the call IS reliable.

    Returns the envelope object, or ``None`` when neither existing nor
    creatable (invalid target, arrangement-vs-session mismatch, etc.).
    """
    envelopes = getattr(clip, "automation_envelopes", None)
    if envelopes is not None:
        for env in envelopes:
            env_param = getattr(env, "parameter", None)
            if env_param is None:
                continue
            if _params_equal(env_param, target):
                return env
    creator = getattr(clip, "create_automation_envelope", None)
    if creator is None:
        return None
    try:
        env = creator(target)
    except (TypeError, RuntimeError):
        # Live raises these for invalid targets / arrangement-vs-session
        # mismatches. Mirror write_envelope's handling.
        return None
    return env


def _resolve_read_envelope_target_and_clip(
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
) -> tuple[Any, Any]:
    """Resolve (clip, target) for a read_envelope call. Mirrors the
    target-resolution branches of write_envelope_handler — clip-scoped
    kinds need `clip_index + location`; track/return-scoped kinds route
    through the parent track's session clip too (Live 12.4 limitation
    documented in write_envelope)."""
    if target_kind == "clip_cc":
        if cc_number is None:
            raise ValueError(
                "read_envelope target_kind='clip_cc' requires cc_number"
            )
        clip = _require_clip(
            context, track_index=track_index, location=location,
            clip_index=clip_index,
        )
        target = _midi_cc_envelope_target(clip, int(cc_number))
        return clip, target
    if target_kind == "clip_pitch_bend":
        clip = _require_clip(
            context, track_index=track_index, location=location,
            clip_index=clip_index,
        )
        target = _midi_pitch_bend_envelope_target(clip)
        return clip, target
    if target_kind == "note_expression":
        _require_note_expression_args(
            note_pitch=note_pitch,
            note_start_beats=note_start_beats,
            axis=axis,
        )
        clip = _require_clip(
            context, track_index=track_index, location=location,
            clip_index=clip_index,
        )
        envelope = clip.envelope_for_note(
            int(note_pitch), float(note_start_beats), axis  # type: ignore[arg-type]
        )
        # For note_expression, envelope IS the target — clip.envelope_for_note
        # returns the envelope directly. Return (clip, envelope) and let
        # the caller skip the _find_existing_envelope step.
        return clip, envelope
    # device_parameter / mixer_volume / mixer_pan / send_level — clip-scoped
    # on Live 12.4.
    if clip_index is None or location is None:
        raise NotImplementedError(
            _TRACK_LEVEL_GAP_HINT.format(target_kind=target_kind)
        )
    if location == "arrangement":
        raise NotImplementedError(
            f"read_envelope target_kind={target_kind!r} on an arrangement "
            "clip is not supported by Live 12.4's LOM (same constraint as "
            "write_envelope). Read the envelope on the source session clip "
            "instead — duplicate_to_arrangement copies envelope state to "
            "the arrangement clip."
        )
    if target_kind == "device_parameter":
        if device_index is None or parameter_name is None:
            raise ValueError(
                "read_envelope target_kind='device_parameter' requires "
                "device_index and parameter_name"
            )
        parent = _require_parent(
            context, track_index=track_index, return_index=return_index,
        )
        device = _resolve_device_on(parent, device_index)
        target = _find_parameter(device, parameter_name)
        clip = _resolve_clip(parent, location, clip_index)
        return clip, target
    if target_kind in ("mixer_volume", "mixer_pan"):
        parent = _require_parent(
            context, track_index=track_index, return_index=return_index,
        )
        mixer = parent.mixer_device
        target = mixer.volume if target_kind == "mixer_volume" else mixer.panning
        clip = _resolve_clip(parent, location, clip_index)
        return clip, target
    # send_level
    if return_index is None:
        raise ValueError(
            "read_envelope target_kind='send_level' requires return_index"
        )
    if track_index is None:
        raise ValueError(
            "read_envelope target_kind='send_level' requires track_index"
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
    return clip, target


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
    resolution_beats: float | None = None,
) -> dict[str, Any]:
    """Alias for read_envelope (legacy action name). Same shape."""
    return read_envelope_handler(
        context,
        target_kind=target_kind,
        track_index=track_index,
        return_index=return_index,
        clip_index=clip_index,
        location=location,
        device_index=device_index,
        parameter_name=parameter_name,
        cc_number=cc_number,
        note_pitch=note_pitch,
        note_start_beats=note_start_beats,
        axis=axis,
        resolution_beats=resolution_beats,
    )


def read_envelope_handler(
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
    resolution_beats: float | None = None,
) -> dict[str, Any]:
    """Read an envelope by target_kind + addressing args, return
    reconstructed breakpoints.

    Sampling-based: Live exposes only ``envelope.value_at_time(t)`` —
    breakpoint enumeration isn't reachable. The handler samples at
    ``resolution_beats`` (default 1/96 beat ≈ 3ms at 120BPM) across the
    clip's [0, length_beats] range and emits a breakpoint at each
    detected step transition. Step changes are localized to within
    resolution_beats; for finer fidelity pass a smaller resolution.

    Returns:
      {
        target_kind: str,
        exists: bool,                # whether any non-default samples found
        time_range_beats: [start, end],
        resolution_beats: float,
        breakpoints: [{time_beats, value}, ...],
        ...echo of addressing args
      }

    Mirrors write_envelope's target-resolution branches and gap-blocked
    target kinds. clip_cc / clip_pitch_bend on Live 12.4 raise the same
    gap error as the write side (Clip.create_automation_envelope rejects
    those targets at the C++ boundary)."""
    if target_kind not in TARGET_KINDS:
        raise ValueError(
            f"target_kind {target_kind!r} not in {list(TARGET_KINDS)}"
        )
    if target_kind == "clip_cc":
        # Same Live 12.4 LOM gap as the write side — surface the same
        # teaching error so agents understand the constraint.
        raise NotImplementedError(
            "Live 12.4 LOM doesn't expose envelope creation/read for "
            "MIDI CC targets — Clip.envelope_target_for_cc returns "
            "sentinels rejected by Clip.create_automation_envelope at "
            "the C++ boundary. CC envelopes can be encoded as MIDI "
            "control-change notes via ableton_clip(action='replace_notes'); "
            "read them back via ableton_clip's note read path."
        )
    if target_kind == "clip_pitch_bend":
        raise NotImplementedError(
            "Live 12.4 LOM doesn't expose envelope creation/read for "
            "clip pitch-bend targets — same constraint as clip_cc. Author "
            "pitch-bend manually in Live's clip envelope editor, or use "
            "target_kind='note_expression' with axis='pitch'."
        )

    res = resolution_beats if resolution_beats is not None else _DEFAULT_ENVELOPE_READ_RESOLUTION
    if res <= 0:
        raise ValueError(f"resolution_beats must be > 0, got {res}")

    clip, target = _resolve_read_envelope_target_and_clip(
        context,
        target_kind=target_kind,
        track_index=track_index,
        return_index=return_index,
        clip_index=clip_index,
        location=location,
        device_index=device_index,
        parameter_name=parameter_name,
        cc_number=cc_number,
        note_pitch=note_pitch,
        note_start_beats=note_start_beats,
        axis=axis,
    )

    # note_expression's resolver returns the envelope directly; for all
    # other target_kinds we resolve via create-or-return on the clip.
    if target_kind == "note_expression":
        envelope = target  # the resolver returned the envelope as `target`
    else:
        envelope = _find_existing_envelope(clip, target)
    if envelope is None:
        # Target is valid but Live couldn't bind an envelope to it.
        # Surface as exists=False rather than raising — read-shouldn't-raise
        # parallels capabilities / get_input_routing on the device side.
        return _read_envelope_empty_result(
            target_kind=target_kind,
            resolution_beats=res,
            track_index=track_index, return_index=return_index,
            clip_index=clip_index, location=location,
            device_index=device_index, parameter_name=parameter_name,
            cc_number=cc_number, note_pitch=note_pitch,
            note_start_beats=note_start_beats, axis=axis,
        )

    clip_length = float(getattr(clip, "length", 0.0))
    breakpoints = _sample_envelope_to_breakpoints(
        envelope, start_beats=0.0, end_beats=clip_length,
        resolution_beats=res,
    )
    # Heuristic: an envelope with exactly one breakpoint at t=0 carrying
    # the parameter's current value is "empty in the musical sense" —
    # Live returns this default when no insert_step has ever fired.
    exists = len(breakpoints) > 1
    result: dict[str, Any] = {
        "target_kind": target_kind,
        "exists": exists,
        "time_range_beats": [0.0, clip_length],
        "resolution_beats": res,
        "breakpoints": breakpoints,
    }
    _echo_addressing_args(
        result,
        track_index=track_index, return_index=return_index,
        clip_index=clip_index, location=location,
        device_index=device_index, parameter_name=parameter_name,
        cc_number=cc_number, note_pitch=note_pitch,
        note_start_beats=note_start_beats, axis=axis,
    )
    return result


def _read_envelope_empty_result(
    *,
    target_kind: str,
    resolution_beats: float,
    **addressing: Any,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "target_kind": target_kind,
        "exists": False,
        "time_range_beats": [0.0, 0.0],
        "resolution_beats": resolution_beats,
        "breakpoints": [],
    }
    _echo_addressing_args(result, **addressing)
    return result


def _echo_addressing_args(result: dict[str, Any], **addressing: Any) -> None:
    """Copy non-None addressing args into result. Mirrors write_envelope's
    "echo what the caller passed in" convention so read/write responses
    have symmetric shape."""
    for k, v in addressing.items():
        if v is not None:
            result[k] = v


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


_NOTE_EXPRESSION_AXES = ("pitch", "pressure", "timbre")


def _require_note_expression_args(
    *,
    note_pitch: int | None,
    note_start_beats: float | None,
    axis: str | None,
) -> None:
    """Validate the trio of args every ``note_expression`` path requires.

    Called by ``write_envelope`` (where the gap is closed and the args
    drive the actual ``envelope_for_note`` call) AND by ``clear`` (where
    the gap is open today but the args ARE part of the target's address
    — validating them up front matches ``clear``'s ``clip_cc`` precedent
    which validates ``cc_number`` before raising the Live-API failure).

    Raises ``ValueError`` on missing or invalid args; raises nothing on
    a valid trio.
    """
    if note_pitch is None or note_start_beats is None or axis is None:
        raise ValueError(
            "target_kind='note_expression' requires note_pitch, "
            "note_start_beats, and axis (one of 'pitch'|'pressure'|'timbre')"
        )
    if axis not in _NOTE_EXPRESSION_AXES:
        raise ValueError(
            f"axis {axis!r} not in {list(_NOTE_EXPRESSION_AXES)}"
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
    envelope: Any,
    breakpoints: list[dict[str, Any]],
    *,
    tail_end: float | None = None,
) -> bool:
    """Walk breakpoints emitting ``insert_step`` calls.

    Live 12.4's ``Envelope`` only exposes ``insert_step(time, duration,
    value)`` — there is no ``add_segment`` for linear/curved transitions.
    Each ``insert_step`` is a *punch box*: inside ``[t, t+duration]`` the
    value holds at ``value``; outside, the envelope reverts to the
    parameter's default. Consecutive breakpoints chain cleanly because
    each next step covers the previous step's tail-reversion. The last
    breakpoint has no successor, so without ``tail_end`` the held value
    is followed by a revert-to-default artifact (visible in Live's UI as
    an unintended 0dB / 0-pan point between ``last_t`` and clip end —
    W7-0 smoke, 2026-05-19).

    ``tail_end`` (in beats) extends the last step to cover [last_t,
    tail_end] so the held value survives to the envelope's intended end.
    Pass ``clip.length`` for clip-scoped envelopes (mixer / pan / send /
    device_parameter). Pass the note's end time for note_expression.
    Pass ``None`` to fall back to a zero-duration anchor (legacy behavior
    — leaves a revert artifact; only useful where the caller genuinely
    wants a point marker without a hold tail).

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
    last_t = last["time_beats"]
    if tail_end is not None and tail_end > last_t:
        tail_dur = tail_end - last_t
    else:
        tail_dur = 0.0
    envelope.insert_step(last_t, tail_dur, last["value"])
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


_VALUE_TYPES: tuple[str, ...] = ("continuous", "enum")


def _resolve_enum_breakpoint_values(
    context: LiveContext,
    *,
    target_kind: str,
    track_index: int | None,
    return_index: int | None,
    device_index: int | None,
    parameter_name: str | None,
    breakpoints: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Resolve enum-name breakpoint values to numeric via the target
    parameter's ``value_items``. Returns (numeric_breakpoints, value_items).

    Mirrors ``set_parameter_handler``'s enum path (handlers/device.py:
    ``_VALUE_TYPES`` / ``set_parameter_handler``) so the capability surface
    is identical: ``is_quantized`` gates value_items access (Wave-2 W2-9:
    Live raises on continuous-parameter value_items reads), the items
    tuple defines cardinality, and ``items.index(name)`` is the
    enum-name → numeric resolution. Teaching error on non-enum targets.

    Only ``device_parameter`` envelopes have enum semantics — mixer /
    pan / send / clip_cc / clip_pitch_bend / note_expression target
    continuous Live parameters by definition.
    """
    if target_kind != "device_parameter":
        raise ValueError(
            f"value_type='enum' is only valid for target_kind="
            f"'device_parameter', got {target_kind!r} (mixer / send / "
            f"pan / clip_cc / clip_pitch_bend / note_expression all "
            f"target continuous Live parameters)"
        )
    if device_index is None or parameter_name is None:
        raise ValueError(
            "value_type='enum' with target_kind='device_parameter' "
            "requires device_index and parameter_name"
        )
    # Pre-validate breakpoint shape (time_beats + value present) BEFORE
    # walking into the Live API — cheaper failure path, and the existing
    # _validate_breakpoints will run again on the resolved list to catch
    # ordering / range issues.
    for i, bp in enumerate(breakpoints):
        if not isinstance(bp, dict):
            raise ValueError(
                f"breakpoint {i}: expected dict, got {type(bp).__name__}"
            )
        if "time_beats" not in bp:
            raise ValueError(
                f"breakpoint {i} missing required 'time_beats': {bp!r}"
            )
        if "value" not in bp:
            raise ValueError(
                f"breakpoint {i} missing required 'value': {bp!r}"
            )
    parent = _require_parent(
        context, track_index=track_index, return_index=return_index,
    )
    device = _resolve_device_on(parent, device_index)
    target_param = _find_parameter(device, parameter_name)
    if not bool(getattr(target_param, "is_quantized", False)):
        raise ValueError(
            f"parameter {parameter_name!r} is not an enum parameter "
            f"(is_quantized=False); use value_type='continuous'"
        )
    items = tuple(getattr(target_param, "value_items", ()) or ())
    if not items:
        raise ValueError(
            f"parameter {parameter_name!r} is not an enum parameter "
            f"(no value_items); use value_type='continuous'"
        )
    items_list = [str(item) for item in items]
    resolved: list[dict[str, Any]] = []
    for i, bp in enumerate(breakpoints):
        # Shape pre-validated above; only the enum-specific value check
        # remains here.
        raw = bp["value"]
        if not isinstance(raw, str):
            raise ValueError(
                f"breakpoint {i}: value_type='enum' requires value as a "
                f"string, got {type(raw).__name__} ({raw!r})"
            )
        if raw not in items_list:
            raise ValueError(
                f"breakpoint {i}: enum value {raw!r} not in value_items "
                f"for parameter {parameter_name!r}: {items_list}"
            )
        translated = dict(bp)
        translated["value"] = float(items_list.index(raw))
        resolved.append(translated)
    return resolved, items_list


def write_envelope_handler(
    context: LiveContext,
    *,
    target_kind: str,
    breakpoints: list[dict[str, Any]],
    value_type: str = "continuous",
    track_index: int | None = None,
    return_index: int | None = None,
    clip_index: int | None = None,
    location: str | None = None,
    device_index: int | None = None,
    parameter_name: str | None = None,
    cc_number: int | None = None,
    note_pitch: int | None = None,
    note_start_beats: float | None = None,
    note_duration: float | None = None,
    axis: str | None = None,
) -> dict[str, Any]:
    """Write a single automation envelope.

    The required identifier set depends on target_kind. The handler
    validates per-kind before walking the Live API. All seven target kinds
    require a containing clip (session or arrangement) on Live 12.4 —
    callers that omit ``clip_index + location`` for the mixer / send /
    device-parameter kinds get a ``NotImplementedError`` citing the LOM
    gap.

    ``value_type='continuous'`` (default): each breakpoint's ``value`` is
    a float. ``value_type='enum'``: each breakpoint's ``value`` is a
    string from the target parameter's ``value_items``; the handler
    resolves via ``value_items.index(name)`` and submits the numeric
    value to Live. Capability-probed via ``is_quantized``: handler refuses
    with a teaching error if the target param has ``is_quantized=False``
    (mirrors ``set_parameter``'s enum path). Enum mode is only valid for
    ``target_kind='device_parameter'`` — mixer / pan / send / clip_cc /
    clip_pitch_bend / note_expression target continuous parameters by
    definition.
    """
    if target_kind not in TARGET_KINDS:
        raise ValueError(
            f"target_kind {target_kind!r} not in {list(TARGET_KINDS)}"
        )
    if value_type not in _VALUE_TYPES:
        raise ValueError(
            f"value_type must be one of {list(_VALUE_TYPES)}, "
            f"got {value_type!r}"
        )
    if value_type == "enum":
        breakpoints, _items = _resolve_enum_breakpoint_values(
            context,
            target_kind=target_kind,
            track_index=track_index,
            return_index=return_index,
            device_index=device_index,
            parameter_name=parameter_name,
            breakpoints=breakpoints,
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
        try:
            clip.clear_envelope(target)
            envelope = clip.create_automation_envelope(target)
        except TypeError as exc:
            # Boost.Python's ArgumentError subclasses TypeError; the
            # tuple sentinel triggers it.
            raise _translate_envelope_target_error("clip_cc", exc) from exc
        non_step_seen = _write_breakpoints_as_steps(
            envelope, cleaned, tail_end=float(getattr(clip, "length", 0.0)),
        )
    elif target_kind == "clip_pitch_bend":
        clip = _require_clip(
            context, track_index=track_index, location=location,
            clip_index=clip_index,
        )
        target = _midi_pitch_bend_envelope_target(clip)
        try:
            clip.clear_envelope(target)
            envelope = clip.create_automation_envelope(target)
        except TypeError as exc:
            raise _translate_envelope_target_error("clip_pitch_bend", exc) from exc
        non_step_seen = _write_breakpoints_as_steps(
            envelope, cleaned, tail_end=float(getattr(clip, "length", 0.0)),
        )
    elif target_kind == "note_expression":
        _require_note_expression_args(
            note_pitch=note_pitch,
            note_start_beats=note_start_beats,
            axis=axis,
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
        # W7-0 anchor (note_expression branch): when the caller supplies
        # the note's duration, extend the last step to cover the note's
        # full duration so the held value survives to note end instead
        # of reverting to default after the last breakpoint. Per-note
        # envelopes use note-LOCAL coordinates (Live's envelope_for_note
        # returns an envelope addressed [0, note_duration_beats]), so the
        # tail anchor is note_duration — not note_start_beats + duration.
        # Mirrors the clip-scoped tail_end=clip.length paths above, but
        # in the note's own coordinate system.
        ne_tail_end: float | None = (
            float(note_duration) if note_duration is not None else None
        )
        non_step_seen = _write_breakpoints_as_steps(
            envelope, cleaned, tail_end=ne_tail_end,
        )
    elif target_kind in _CLIP_REQUIRED_KINDS:
        if clip_index is None or location is None:
            raise NotImplementedError(
                _TRACK_LEVEL_GAP_HINT.format(target_kind=target_kind)
            )
        # Wave-2 W2-10: empirical Live 12.4 — mixer / pan / send / device_parameter
        # envelopes are addressable on SESSION clips only. Arrangement clips
        # reject these targets with RuntimeError("Not a session clip or
        # parameter belongs to another track."). Surface the gap with a
        # teaching error pointing at the session-clip path rather than
        # letting Live's raw error reach the caller.
        if location == "arrangement":
            raise NotImplementedError(
                f"target_kind={target_kind!r} on an arrangement clip is "
                "not supported by Live 12.4's LOM — Clip.create_automation_"
                "envelope() rejects mixer / pan / send / device_parameter "
                "targets unless the clip is a session clip. Author the "
                "envelope on a session clip first (location='session'), "
                "then ableton_clip(action='duplicate_to_arrangement') to "
                "place a copy in the arrangement. The arrangement clip "
                "inherits the envelope.\n"
                "Track-level arrangement automation creation isn't exposed "
                "on Live 12.4 either — see ableton://guides/gaps for the "
                "broader LOM gap."
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
        non_step_seen = _write_breakpoints_as_steps(
            envelope, cleaned, tail_end=float(getattr(clip, "length", 0.0)),
        )
    else:
        # Defensive — enum validation above should have caught this.
        raise ValueError(f"unhandled target_kind {target_kind!r}")

    result: dict[str, Any] = {
        "target_kind": target_kind,
        "breakpoints_written": len(cleaned),
        "value_type": value_type,
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
        try:
            clip.clear_envelope(target)
        except TypeError as exc:
            raise _translate_envelope_target_error("clip_cc", exc) from exc
        return {"target_kind": target_kind, "cleared": True}
    if target_kind == "clip_pitch_bend":
        clip = _require_clip(
            context, track_index=track_index, location=location,
            clip_index=clip_index,
        )
        target = _midi_pitch_bend_envelope_target(clip)
        try:
            clip.clear_envelope(target)
        except TypeError as exc:
            raise _translate_envelope_target_error("clip_pitch_bend", exc) from exc
        return {"target_kind": target_kind, "cleared": True}
    if target_kind == "note_expression":
        # Validate required addressing args FIRST — matches the clip_cc
        # branch above (which validates cc_number before invoking Live)
        # and matches write_envelope's note_expression branch. Without
        # this, the gap raise below would mask "missing axis" errors
        # behind "not supported," giving the agent two things to debug.
        _require_note_expression_args(
            note_pitch=note_pitch,
            note_start_beats=note_start_beats,
            axis=axis,
        )
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
    # Wave-2 W2-10: Live 12.4 also rejects clear_envelope for these targets
    # on arrangement clips (same root cause as write — Clip's create / clear
    # path only accepts session-clip-owned mixer / pan / send / parameter
    # envelopes). Mirror write_envelope's arrangement guard so the
    # symmetric clear path surfaces the same teaching error.
    if location == "arrangement":
        raise NotImplementedError(
            f"clear with target_kind={target_kind!r} on an arrangement clip "
            "is not supported by Live 12.4's LOM — symmetric with "
            "write_envelope's gap. Author the envelope on a session clip "
            "first; clear it via location='session' if you need to remove "
            "it. To remove ALL envelopes from an arrangement clip, use "
            "action='clear_all' on the clip-owning track."
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
    """Build the Live envelope target for a clip-CC envelope.

    Live 12.4 may not expose ``Clip.envelope_target_for_cc`` — the
    canonical factory name is uncertain (Ableton's Remote Script LOM is
    undocumented for this surface). The fallback returns a tuple
    sentinel that the test fakes recognize; real Live will reject it
    at the typed boundary (``clip.clear_envelope`` /
    ``clip.create_automation_envelope``) and the caller surfaces the
    teaching error via ``_translate_envelope_target_error``.
    """
    factory = getattr(clip, "envelope_target_for_cc", None)
    if factory is not None:
        return factory(int(cc_number))
    return ("cc", int(cc_number))


def _midi_pitch_bend_envelope_target(clip: Any) -> Any:
    factory = getattr(clip, "envelope_target_for_pitch_bend", None)
    if factory is not None:
        return factory()
    return ("pitch_bend",)


def _translate_envelope_target_error(target_kind: str, exc: Exception) -> Exception:
    """Convert Live's raw ArgumentError on envelope-target writes to a
    teaching NotImplementedError.

    Live 12.4 raises ``ArgumentError: Python argument types ... did not
    match C++ signature: clear_envelope(TPyHandle<AClip>,
    TPyHandle<ATimeableValue>)`` when the handler passes a tuple sentinel
    (our fallback when the factory method isn't exposed). Wave-2 W2-10
    captured this empirically for ``clip_pitch_bend``; the same applies
    to ``clip_cc``. Surface a teaching error pointing at the LOM gap.
    """
    msg = str(exc)
    if "ATimeableValue" in msg or "TimeableValue" in msg:
        return NotImplementedError(
            f"target_kind={target_kind!r}: Live 12.4's LOM doesn't expose "
            f"a public factory for this clip envelope target — the handler "
            f"passes a structural sentinel that Live's typed boundary "
            f"rejects with ArgumentError. Workaround for clip_cc: encode "
            f"the CC as a MIDI control-change event via "
            f"ableton_clip(action='replace_notes'). For clip_pitch_bend: "
            f"author it manually in Live's clip envelope editor. Original "
            f"error: {exc}"
        )
    return exc


# ---------------------------------------------------------------------------
# perform_batch — gesture-recorded arrangement automation, one transport
# pass for N windowed arcs (ENV-9P4T; supersedes the single-arc ENV-7G4K
# perform)
# ---------------------------------------------------------------------------
#
# Master / group / return mixer and device-parameter automation has NO
# session-clip host (master and returns can't hold session clips; Live
# rejects group-track clip slots) and arrangement automation lanes have
# no LOM write surface. The verified write path (lom-probe-results.md
# probes 4 / 4b / 10, Live 12.4.1) is realtime automation recording:
#
#   save transport/record state
#   song.session_automation_record = True
#   song.record_mode = True        # ASYNC — applies ~300 ms later
#                                  # (probe 10): settle-poll, NEVER
#                                  # trust same-call read-back
#   seek to span start
#   param.begin_gesture()
#   song.start_playing()
#   loop (~10 Hz): read song.current_song_time (beats) on the main
#                  thread, set param.value = interp(breakpoints, beat)
#   param.end_gesture()
#   song.stop_playing(); restore saved state
#
# Properties of the mechanism class: *write-only* (no LOM read of
# arrangement automation — verification is param.automation_state +
# playback observation), *realtime* (a perform costs wall-clock
# proportional to span / tempo), *async transport state*.
#
# Threading: registered runs_on_worker=True. Every Live touch is its own
# ``context.run_on_main`` bout; wall-clock sleeps happen on the worker
# thread between bouts so Live's main thread stays free to pump the
# audio-thread → mirror propagation (the W3-F lesson — a main-thread
# sleep starves the very event pump the settle-poll is waiting on).
# Transport mutation is serialized under ``context.live_state_lock``
# (same contract as seek / cue_create).


PERFORM_TARGET_KINDS: tuple[str, ...] = (
    "mixer_volume",
    "mixer_pan",
    "send_level",
    "device_parameter",
)

# Value-update PERIOD for the scripted ramp — the loop sleeps 100 ms per
# step, but main-thread scheduling + the Live touch dominate, so the
# ACHIEVED rate is ~2.5-3 Hz (S-7 .als dump: ~3 breakpoints/second per
# arc). That rate still read as faithful across all 5 S-7 arc families —
# Live interpolates between recorded points. Tune here if a future arc
# surfaces audible stepping; the floor is scheduling, not this constant.
_PERFORM_UPDATE_PERIOD_S = 0.1

# Settle-poll cadence for async Song state (record_mode — probe 10).
_PERFORM_SETTLE_POLL_S = 0.05

_DEFAULT_PERFORM_SETTLE_TIMEOUT_MS = 2000

# The ramp loop's wall-clock budget is the expected playback duration
# times this factor, plus a fixed floor — generous because tempo maps
# can slow playback well below the tempo read at span start.
_PERFORM_WALL_CLOCK_FACTOR = 3.0
_PERFORM_WALL_CLOCK_FLOOR_S = 10.0


@dataclass
class _PreparedArc:
    """One arc inside a perform_batch pass. ``state`` is the single source of
    truth for the gesture lifecycle — ``pending`` (gesture not yet opened) →
    ``open`` (begin_gesture done, ramping values) → ``closed`` (end_gesture
    done) — so there is no multi-boolean combination to keep consistent as the
    windowing loop mutates it. ``opened`` derives from state (anything past
    ``pending``); only opened arcs are verified post-pass."""

    arc_id: Any
    target_kind: str
    master: bool
    track_index: int | None
    return_index: int | None
    device_index: int | None
    parameter_name: str | None
    cleaned: list[dict[str, Any]]
    span_start: float
    span_end: float
    param: Any = None
    state: str = "pending"  # pending -> open -> closed
    updates_written: int = 0
    automation_state: int | None = None

    @property
    def opened(self) -> bool:
        return self.state != "pending"

    def addressing_key(self) -> tuple:
        """Identity of the Live parameter this arc rides — two arcs with the
        same key resolve to the SAME param and would fight for one gesture in
        a single pass (a same-target collision)."""
        return (
            self.target_kind, self.master, self.track_index,
            self.return_index, self.device_index, self.parameter_name,
        )


def _interp_performed_value(
    breakpoints: list[dict[str, Any]], beat: float
) -> float:
    """Interpolate the authored arc's value at ``beat``.

    ``breakpoints`` is the cleaned output of ``_validate_breakpoints``
    (sorted, ``{time_beats, value, curve}``). Before the first breakpoint
    the first value holds; after the last, the last value holds. Within a
    segment, ``breakpoints[i]['curve']`` describes the transition TO the
    next breakpoint (same convention as ``_write_breakpoints_as_steps``):

      - ``linear`` (default) — straight lerp
      - ``hold`` — previous value until the next breakpoint
      - ``fast`` — most of the change happens early (1 - (1-t)^2)
      - ``slow`` — most of the change happens late (t^2)

    Recorded automation has no LOM curve-object surface; curve shapes are
    approximated by sampling the shaped interpolation during the ramp
    (design.md, ENV-7G4K).
    """
    if beat <= breakpoints[0]["time_beats"]:
        return float(breakpoints[0]["value"])
    if beat >= breakpoints[-1]["time_beats"]:
        return float(breakpoints[-1]["value"])
    # Walk segments — breakpoint lists are authored-arc sized (tens of
    # entries), linear scan at 10 Hz is well below any cost threshold.
    for i in range(len(breakpoints) - 1):
        t0 = breakpoints[i]["time_beats"]
        t1 = breakpoints[i + 1]["time_beats"]
        if not (t0 <= beat < t1):
            continue
        v0 = float(breakpoints[i]["value"])
        v1 = float(breakpoints[i + 1]["value"])
        curve = breakpoints[i].get("curve") or "linear"
        if curve == "hold":
            return v0
        if t1 <= t0:  # zero-length segment (duplicate times) — step to v0
            return v0
        t = (beat - t0) / (t1 - t0)
        if curve == "fast":
            shaped = 1.0 - (1.0 - t) ** 2
        elif curve == "slow":
            shaped = t**2
        else:  # linear
            shaped = t
        return v0 + (v1 - v0) * shaped
    # Unreachable given the boundary checks above; defensive hold.
    return float(breakpoints[-1]["value"])


def _resolve_perform_target(
    context: LiveContext,
    *,
    target_kind: str,
    master: bool,
    track_index: int | None,
    return_index: int | None,
    device_index: int | None,
    parameter_name: str | None,
) -> Any:
    """Resolve the Live ``DeviceParameter`` the gesture will ride.

    Parent addressing: exactly one of ``master=True`` / ``track_index`` /
    ``return_index`` — perform targets are clip-less, so unlike
    ``write_envelope`` there is no containing-clip resolution, and the
    master track is addressable (the canonical use). ``send_level`` is
    track-parented (regular or group track) with ``return_index`` naming
    the destination return, mirroring ``write_envelope``; master has no
    sends and return-host sends are out of wave-1 scope.

    Must run on Live's main thread (callers wrap in ``run_on_main``).
    """
    if target_kind == "send_level":
        if master:
            raise ValueError(
                "perform target_kind='send_level' cannot target the master "
                "track — the master strip has no sends"
            )
        if track_index is None or return_index is None:
            raise ValueError(
                "perform target_kind='send_level' requires track_index "
                "(source track — regular or group) AND return_index "
                "(destination return), mirroring write_envelope. "
                "Return-host sends are not in the wave-1 perform surface."
            )
        track = _resolve_track(context, track_index)
        sends = track.mixer_device.sends
        if return_index < 1 or return_index > len(sends):
            raise IndexError(
                f"return_index {return_index} out of range "
                f"[1, {len(sends)}] for track {track_index}"
            )
        return sends[return_index - 1]

    # mixer_volume / mixer_pan / device_parameter — parent is exactly one
    # of master / track / return.
    selected = [
        name
        for name, present in (
            ("master", master),
            ("track_index", track_index is not None),
            ("return_index", return_index is not None),
        )
        if present
    ]
    if len(selected) != 1:
        raise ValueError(
            f"perform target_kind={target_kind!r} requires exactly one of "
            f"master=True / track_index / return_index, got {selected or 'none'}"
        )
    if master:
        parent = context.song.master_track
    elif track_index is not None:
        parent = _resolve_track(context, track_index)
    else:
        song = context.song
        if return_index < 1 or return_index > len(song.return_tracks):  # type: ignore[operator]
            raise IndexError(
                f"return_index {return_index} out of range "
                f"[1, {len(song.return_tracks)}]"
            )
        parent = song.return_tracks[return_index - 1]  # type: ignore[index]

    if target_kind == "device_parameter":
        if device_index is None or parameter_name is None:
            raise ValueError(
                "perform target_kind='device_parameter' requires "
                "device_index and parameter_name"
            )
        device = _resolve_device_on(parent, device_index)
        return _find_parameter(device, parameter_name)
    mixer = parent.mixer_device
    return mixer.volume if target_kind == "mixer_volume" else mixer.panning


def _wait_for_record_mode_on_worker(
    context: LiveContext,
    expected: bool,
    *,
    timeout_s: float,
    poll_interval_s: float = _PERFORM_SETTLE_POLL_S,
) -> None:
    """Settle-poll ``song.record_mode`` until it reads ``expected``.

    Probe 10 (Live 12.4.1): ``record_mode`` applies ASYNC — an immediate
    read-back after the set returns the OLD value; it reads true ~300 ms
    later. Runs on the worker thread; each read is its own main-thread
    bout, with ``time.sleep`` between bouts on the worker so Live's main
    thread can pump the state propagation we're waiting on.
    """
    deadline = time.monotonic() + timeout_s
    while True:
        observed = context.run_on_main(
            lambda: bool(context.song.record_mode)
        )
        if observed == expected:
            return
        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"song.record_mode did not settle to {expected} within "
                f"{timeout_s:.1f}s (record_mode applies asynchronously — "
                f"probe 10). Live may be busy or showing a modal dialog; "
                f"retry, or pass a larger settle_timeout_ms."
            )
        time.sleep(poll_interval_s)


def perform_batch_handler(
    context: LiveContext,
    *,
    arcs: list[dict[str, Any]],
    settle_timeout_ms: int = _DEFAULT_PERFORM_SETTLE_TIMEOUT_MS,
) -> dict[str, Any]:
    """Record N authored automation arcs into Live's ARRANGEMENT automation
    in a SINGLE transport pass (ENV-9P4T) — gesture recording with
    per-parameter windowing.

    Each arc in ``arcs`` is ``{arc_id?, target_kind, <addressing>,
    breakpoints}`` where ``<addressing>`` is the same master / track_index /
    return_index / device_index / parameter_name surface as the (former)
    single-arc path, and the arc's span is ``[first, last]`` breakpoint
    time. The transport plays ONCE over the UNION span
    ``[min(start), max(end)]``; each arc's ``begin_gesture`` /
    ``end_gesture`` opens at its span entry and closes at its span exit
    inside that shared pass, so a short arc never stamps a flat value
    across the whole song. Arcs active at the union start open BEFORE
    ``start_playing`` (matching the proven single-arc order); later arcs
    open mid-ramp.

    ``arc_id`` is an opaque caller correlation id echoed back per arc so
    the push apply layer can gate each arc's performed-state independently
    on ITS ``automation_state`` (one unverified arc never blocks the
    others). The write path is for surfaces session clips can't reach:
    master / group / return mixer moves and device parameters.

    Returns ``{"arcs": [{arc_id?, target_kind, automation_state,
    span_beats, beats_performed, updates_written, breakpoint_count,
    <addressing echo>}, ...], "union_span_beats", "wall_clock_s",
    "arc_count"}``. A non-1 ``automation_state`` is reported per arc, not
    raised — the caller owns the failed-verification policy.

    A failed pass must not leave the set armed or any gesture open: every
    still-open gesture is closed and the transport / record state restored
    in a ``finally`` with per-step isolation. ``re_enable_automation`` is
    set-wide by design (design.md) — the correct post-record state for a
    scripted writer.
    """
    if not isinstance(arcs, list) or not arcs:
        raise ValueError(
            "perform_batch requires a non-empty 'arcs' list — each arc is "
            "{arc_id?, target_kind, <addressing>, breakpoints}"
        )
    if settle_timeout_ms <= 0:
        raise ValueError(
            f"settle_timeout_ms must be > 0, got {settle_timeout_ms}"
        )
    settle_timeout_s = settle_timeout_ms / 1000.0

    # Validate + normalize every arc up front (no Live touch yet) so a
    # malformed arc raises before any transport state is armed.
    prepared: list[_PreparedArc] = []
    for i, arc in enumerate(arcs):
        target_kind = arc.get("target_kind")
        if target_kind not in PERFORM_TARGET_KINDS:
            raise ValueError(
                f"perform_batch arcs[{i}] target_kind {target_kind!r} not in "
                f"{list(PERFORM_TARGET_KINDS)} — clip-hosted kinds (clip_cc, "
                f"clip_pitch_bend, note_expression) are written via "
                f"write_envelope, not performed"
            )
        cleaned = _validate_breakpoints(arc.get("breakpoints"))
        span_start = cleaned[0]["time_beats"]
        span_end = cleaned[-1]["time_beats"]
        if span_end <= span_start:
            raise ValueError(
                f"perform_batch arcs[{i}] ({target_kind}) span is empty "
                f"({span_start}..{span_end}) — a single-point arc is a static "
                "value, not an automation ride; dial the parameter instead"
            )
        prepared.append(_PreparedArc(
            arc_id=arc.get("arc_id"),
            target_kind=target_kind,
            master=bool(arc.get("master", False)),
            track_index=arc.get("track_index"),
            return_index=arc.get("return_index"),
            device_index=arc.get("device_index"),
            parameter_name=arc.get("parameter_name"),
            cleaned=cleaned,
            span_start=span_start,
            span_end=span_end,
        ))

    # Same-target collision guard: two arcs resolving to ONE Live parameter
    # would fight for a single gesture in the shared pass (interleaved
    # begin/end on the same param → undefined recording). Reject up front,
    # naming both colliding ids. (Two arcs on one param was unreachable when
    # each arc had its own transport pass; batching makes it reachable.)
    seen_targets: dict[tuple, Any] = {}
    for a in prepared:
        key = a.addressing_key()
        if key in seen_targets:
            raise ValueError(
                f"perform_batch: two arcs target the same parameter "
                f"({a.target_kind} {key[1:]!r}) — arc_id {seen_targets[key]!r} "
                f"and {a.arc_id!r}. One parameter carries one performed arc per "
                "pass; merge them into a single arc."
            )
        seen_targets[key] = a.arc_id

    union_start = min(a.span_start for a in prepared)
    union_end = max(a.span_end for a in prepared)

    with context.live_state_lock:
        # Bout 1 — resolve every arc's param. Addressing errors land here,
        # before any transport state is touched (nothing has mutated yet).
        def _resolve_all() -> None:
            for a in prepared:
                a.param = _resolve_perform_target(
                    context,
                    target_kind=a.target_kind,
                    master=a.master,
                    track_index=a.track_index,
                    return_index=a.return_index,
                    device_index=a.device_index,
                    parameter_name=a.parameter_name,
                )

        context.run_on_main(_resolve_all)

        # Bout 2 — read-only state snapshot. Captured BEFORE any mutation so
        # the finally-restore below has the prior state even when the arm
        # bout itself fails partway.
        def _save_state() -> tuple[dict[str, Any], float]:
            song = context.song
            saved = {
                "record_mode": bool(song.record_mode),
                "session_automation_record": bool(
                    song.session_automation_record
                ),
                "current_song_time": float(song.current_song_time),
            }
            return saved, float(song.tempo)

        saved, tempo = context.run_on_main(_save_state)

        restore_failures: list[str] = []
        wall_start = time.monotonic()

        # Windowing primitives — both run inside a single main-thread bout
        # (with the playhead beat just read), so an open/close/write can't
        # lag a stale beat. State transitions: pending → open → closed.
        def _open_entering(beat: float) -> None:
            for a in prepared:
                if a.state == "pending" and beat >= a.span_start:
                    a.param.begin_gesture()
                    a.state = "open"

        def _write_or_close(beat: float) -> None:
            for a in prepared:
                if a.state != "open":
                    continue
                if beat >= a.span_end:
                    a.param.end_gesture()
                    a.state = "closed"
                else:
                    a.param.value = _interp_performed_value(a.cleaned, beat)
                    a.updates_written += 1

        try:
            # Bout 3 — arm + seek to the union span start (first mutation;
            # inside the try so a partial arm still restores).
            def _arm_and_seek() -> None:
                song = context.song
                if bool(song.is_playing):
                    song.stop_playing()
                song.session_automation_record = True
                song.record_mode = True
                song.current_song_time = float(union_start)

            context.run_on_main(_arm_and_seek)

            _wait_for_record_mode_on_worker(
                context, True, timeout_s=settle_timeout_s
            )

            # Open the gestures for arcs already active at the union start
            # (begin_gesture BEFORE start_playing, as the single-arc path
            # did), THEN play. Values are written by the ramp loop while the
            # transport is actually moving.
            def _begin_initial_and_play() -> None:
                _open_entering(float(context.song.current_song_time))
                context.song.start_playing()

            context.run_on_main(_begin_initial_and_play)

            # Ramp loop over the union span. Beat-space interpolation makes
            # tempo maps free: the playhead position IS the authored
            # coordinate, so each arc's window is compared in beats.
            expected_s = (union_end - union_start) / (max(tempo, 1.0) / 60.0)
            deadline = wall_start + max(
                expected_s * _PERFORM_WALL_CLOCK_FACTOR,
                _PERFORM_WALL_CLOCK_FLOOR_S,
            ) + settle_timeout_s

            def _ramp_step() -> bool:
                song = context.song
                beat = float(song.current_song_time)
                _open_entering(beat)
                _write_or_close(beat)
                return beat >= union_end

            while True:
                done = context.run_on_main(_ramp_step)
                if done:
                    break
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        f"perform_batch ramp did not reach union span end "
                        f"{union_end} beats within its wall-clock budget "
                        f"({deadline - wall_start:.1f}s). Transport may be "
                        f"blocked (modal dialog, count-in) — the handler's "
                        f"cleanup disarms the set and restores transport state "
                        f"(check record_mode in Live if a restore step also "
                        f"failed; those are logged)."
                    )
                time.sleep(_PERFORM_UPDATE_PERIOD_S)
        finally:
            # Disarm + restore — every step attempts even when an earlier
            # one fails; a failed pass must not leave the set armed or ANY
            # gesture open.
            def _attempt(label: str, fn: Callable[[], Any]) -> None:
                try:
                    context.run_on_main(fn)
                except Exception as exc:  # prawduct:allow prawduct/broad-except -- Live wrappers raise arbitrary types; every restore step must still attempt
                    restore_failures.append(f"{label}: {exc}")
                    logger.warning(
                        "perform_batch restore step %s failed: %s", label, exc
                    )

            for a in prepared:
                if a.state == "open":
                    _attempt(
                        f"end_gesture[{a.arc_id}]",
                        lambda p=a.param: p.end_gesture(),
                    )
                    a.state = "closed"
            _attempt("stop_playing", lambda: context.song.stop_playing())
            _attempt(
                "record_mode",
                lambda: setattr(
                    context.song, "record_mode", saved["record_mode"]
                ),
            )
            # record_mode applies ASYNCHRONOUSLY (probe 10) — a bare setattr
            # that's accepted but never applies would leave the set armed with
            # no signal. Settle-verify the disarm; a timeout lands in
            # restore_failures (surfaced as an operator warning), the one
            # armed-set failure mode that otherwise had no detection.
            _attempt(
                "record_mode_settle",
                lambda: _wait_for_record_mode_on_worker(
                    context, saved["record_mode"], timeout_s=settle_timeout_s
                ),
            )
            _attempt(
                "session_automation_record",
                lambda: setattr(
                    context.song,
                    "session_automation_record",
                    saved["session_automation_record"],
                ),
            )
            _attempt(
                "re_enable_automation",
                lambda: context.song.re_enable_automation(),
            )
            _attempt(
                "current_song_time",
                lambda: setattr(
                    context.song,
                    "current_song_time",
                    saved["current_song_time"],
                ),
            )

        # Post-perform verification — per arc, the same automation_state
        # poll the single-arc path used (probe 4: 0 → 1 after a successful
        # record), but only for arcs that actually opened a gesture. A non-1
        # read is reported per arc, not raised.
        state_deadline = time.monotonic() + settle_timeout_s
        to_verify = [a for a in prepared if a.opened]
        while True:
            for a in list(to_verify):
                a.automation_state = context.run_on_main(
                    lambda p=a.param: (
                        int(p.automation_state)
                        if getattr(p, "automation_state", None) is not None
                        else None
                    )
                )
                if a.automation_state == 1:
                    to_verify.remove(a)
            if not to_verify or time.monotonic() >= state_deadline:
                break
            time.sleep(_PERFORM_SETTLE_POLL_S)

    arcs_result: list[dict[str, Any]] = []
    for a in prepared:
        entry: dict[str, Any] = {
            "target_kind": a.target_kind,
            "automation_state": a.automation_state,
            "span_beats": [a.span_start, a.span_end],
            "beats_performed": a.span_end - a.span_start,
            "updates_written": a.updates_written,
            "breakpoint_count": len(a.cleaned),
        }
        if a.arc_id is not None:
            entry["arc_id"] = a.arc_id
        _echo_addressing_args(
            entry,
            master=a.master or None,
            track_index=a.track_index,
            return_index=a.return_index,
            device_index=a.device_index,
            parameter_name=a.parameter_name,
        )
        arcs_result.append(entry)

    result: dict[str, Any] = {
        "arcs": arcs_result,
        "union_span_beats": [union_start, union_end],
        "wall_clock_s": round(time.monotonic() - wall_start, 3),
        "arc_count": len(prepared),
    }
    if restore_failures:
        result["restore_failures"] = restore_failures
    return result


__all__ = [
    "TARGET_KINDS",
    "PERFORM_TARGET_KINDS",
    "list_handler",
    "get_envelope_handler",
    "read_envelope_handler",
    "write_envelope_handler",
    "clear_handler",
    "clear_all_handler",
    "perform_batch_handler",
]
