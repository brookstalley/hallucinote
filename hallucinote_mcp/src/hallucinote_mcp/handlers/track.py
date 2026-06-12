"""Imperative handlers for ``ableton_track`` actions.

Mostly thin wrappers over the Live Object Model — but ``set_property`` /
``get_property`` are property-branching dispatch (which the declarative path
doesn't support cleanly), and ``create`` is genuinely multi-step (create the
track + name it + optionally load an instrument).

Convention: every handler accepts a 1-based ``track_index`` and translates
to the Live API's 0-based ``song.tracks[index - 1]`` lookup. Out-of-range
indices raise ``IndexError`` which the dispatcher's broad-except wraps as a
structured "executor failed" wire response.
"""
from __future__ import annotations

from typing import Any

from ..dispatcher import LiveContext
from ._routing import resolve_routing_write, routing_surface_fields
from .display_value import display_number_for, resolve_continuous_write


# Per-property metadata: (path-from-track, value-bounds-or-None, type-coercer)
#
# The path tuple walks attribute-by-attribute from the Track object to the
# final settable attribute. Volume/panning live on the mixer device's
# parameter objects (themselves having a ``.value`` field); mute/solo/arm/color
# live directly on the track. Bounds are checked before write — Live silently
# clamps otherwise, hiding agent errors.
_TRACK_PROPERTIES: dict[str, tuple[tuple[str, ...], tuple[float, float] | None]] = {
    "volume":  (("mixer_device", "volume", "value"),  (0.0, 1.0)),
    "panning": (("mixer_device", "panning", "value"), (-1.0, 1.0)),
    "mute":    (("mute",),    None),
    "solo":    (("solo",),    None),
    "arm":     (("arm",),     None),
    "color":   (("color",),   None),
}


def _coerce_value(property: str, value: Any) -> Any:
    """Coerce the wire value into the type Live's API expects.

    Booleans-as-floats (the agent sometimes ships ``1.0`` for ``mute=True``)
    are normalized here. ``color`` is an int (Live uses palette-index colors).
    Volume and panning stay floats.
    """
    if property in ("mute", "solo", "arm"):
        return bool(value)
    if property == "color":
        return int(value)
    return float(value)


def _resolve_track(context: LiveContext, track_index: int) -> Any:
    song = context.song
    if track_index < 1 or track_index > len(song.tracks):
        raise IndexError(
            f"track_index {track_index} out of range [1, {len(song.tracks)}]"
        )
    return song.tracks[track_index - 1]


def list_handler(context: LiveContext) -> dict[str, Any]:
    """Return a thin index of all session tracks: index, name, kind, color.

    Kept lightweight — per-track mixer / clip / device detail is each
    track's ``info`` action's job.
    """
    song = context.song
    tracks_out: list[dict[str, Any]] = []
    for i, track in enumerate(song.tracks, start=1):
        tracks_out.append({
            "track_index": i,
            "name": track.name,
            "kind": _kind_of(track),
            "color": getattr(track, "color", None),
        })
    return {"tracks": tracks_out}


def _kind_of(track: Any) -> str:
    """Map Live's track typing to our schema's enum: midi / audio / group."""
    if getattr(track, "is_grouped", False) or getattr(track, "is_foldable", False):
        return "group"
    has_midi = getattr(track, "has_midi_input", None)
    if has_midi is True:
        return "midi"
    if has_midi is False:
        return "audio"
    # Older Live builds: fall back to checking ``has_audio_input``.
    if getattr(track, "has_audio_input", False):
        return "audio"
    return "midi"


def info_handler(context: LiveContext, *, track_index: int) -> dict[str, Any]:
    """Read all mixer / identity fields for one track in a single call."""
    track = _resolve_track(context, track_index)
    mixer = track.mixer_device
    return {
        "track_index": track_index,
        "name": track.name,
        "kind": _kind_of(track),
        "color": getattr(track, "color", None),
        "volume": float(mixer.volume.value),
        # dB read off Live's own fader curve (str_for_value), for agents doing
        # gain-staging in dB. None when the fader is fully down (volume 0 reads
        # "-inf dB") — that is independent of the `mute` flag. Pan has no dB
        # sense, so no panning_db.
        "volume_db": display_number_for(mixer.volume),
        "panning": float(mixer.panning.value),
        "mute": bool(track.mute),
        "solo": bool(track.solo),
        "arm": bool(getattr(track, "arm", False)),
    }


def create_handler(
    context: LiveContext,
    *,
    kind: str,
    name: str | None = None,
    index: int | None = None,
    instrument_uri: str | None = None,
) -> dict[str, Any]:
    """Create a track: pick the API by ``kind``, optionally name + load.

    ``index`` is 1-based; if omitted the track is appended to the end. The
    Live API takes 0-based indices; default ``-1`` means "append" in Live's
    convention. We return the new 1-based ``track_index`` plus the name so
    the planner can record the binding immediately.

    ``instrument_uri`` is accepted as a parameter on the action surface but
    NOT loaded here — the device tool (``ableton_device(action='load')``) is
    M-4 territory. The planner should currently leave ``instrument_uri``
    unset and follow up with a separate device-load call.
    """
    song = context.song
    if kind == "midi":
        create_fn = song.create_midi_track
    elif kind == "audio":
        create_fn = song.create_audio_track
    else:
        raise ValueError(
            f"create: kind must be 'midi' or 'audio', got {kind!r} "
            "(group-track creation is not yet supported)"
        )

    insert_at = (index - 1) if index is not None else -1
    new_track = create_fn(insert_at)
    if name:
        new_track.name = name

    # Live's create_midi_track / create_audio_track inserts at the given
    # 0-based position, or appends when -1. The new track's 1-based index
    # is deterministic from that.
    #
    # We deliberately do NOT scan ``song.tracks`` for identity: Live
    # re-wraps API objects on each property access, so ``new_track is
    # song.tracks[i]`` and ``new_track == song.tracks[i]`` can both
    # spuriously return False for wrappers around the same underlying
    # Live track. The previous identity scan tripped this on every real
    # ``create`` call, leaving the new track in Live but the handler
    # response a false-negative "Live API bug" error.
    new_index = len(song.tracks) if insert_at == -1 else insert_at + 1

    result: dict[str, Any] = {
        "track_index": new_index,
        "kind": kind,
        "name": new_track.name,
    }
    if instrument_uri:
        # Schema-stable but not loaded by this action. M-4 fills in the
        # device-load story.
        result["instrument_uri_deferred"] = instrument_uri
    return result


def delete_handler(context: LiveContext, *, track_index: int) -> dict[str, Any]:
    """Delete a track. Live 12.4's ``Song.delete_track`` takes a 0-based int
    (the C++ signature is ``delete_track(TPyHandle<ASong>, int)`` — passing a
    Track wrapper raises ``ArgumentError``). ``_resolve_track`` still runs so
    out-of-range indices surface as a teaching error before we touch Live's
    API, but the C++ side only sees the int.

    W18-E: refuse-and-teach before Live rejects with ``RuntimeError:
    Couldn't delete track``. Live requires the set to contain at least
    one track, so deleting the last surviving track is structurally
    impossible — surface that constraint with a recoverable hint
    (create a new track first, then re-delete) instead of a bare
    runtime error from the LOM.
    """
    song = context.song
    _resolve_track(context, track_index)  # range check + teaching error
    if len(song.tracks) <= 1:
        raise ValueError(
            "delete: Live requires the set to contain at least one track; "
            "refusing to delete the last surviving track. Create a new "
            "track first (ableton_track(action='create')), then retry "
            "the delete."
        )
    song.delete_track(track_index - 1)
    return {"deleted_track_index": track_index}


def set_property_handler(
    context: LiveContext,
    *,
    track_index: int,
    property: str,
    value: Any = None,
    value_display: str | None = None,
) -> dict[str, Any]:
    """Write a single mixer property. Branches on ``property`` to walk to
    the right Live attribute and apply per-property range validation.

    ``volume`` accepts ``value_display`` — a dB target ("-8 dB") inverted to the
    raw value via the same shared ``resolve_continuous_write`` contract the device
    ``set_parameter`` handler uses. ``panning`` is also a ``DeviceParameter`` and
    is routed through the same path, but its display ("50L"/"C"/"50R") isn't a
    signed number, so ``value_display`` is refused for it with a teaching error —
    set pan via ``value``. The non-parameter properties (mute / solo / arm /
    color) take ``value`` only.
    """
    if property not in _TRACK_PROPERTIES:
        raise ValueError(
            f"set_property: property {property!r} is not supported; "
            f"valid values are {sorted(_TRACK_PROPERTIES)}"
        )
    path, bounds = _TRACK_PROPERTIES[property]
    track = _resolve_track(context, track_index)
    obj: Any = track
    for attr in path[:-1]:
        obj = getattr(obj, attr)

    if value_display is not None:
        # value_display addresses a Live DeviceParameter by its display units.
        if not callable(getattr(obj, "str_for_value", None)):
            raise ValueError(
                f"set_property: value_display is only supported for "
                f"parameter-backed properties (volume, panning), not "
                f"{property!r}; set it via `value`"
            )
        coerced = resolve_continuous_write(
            obj, value=value, value_display=value_display, parameter_name=property
        )
    else:
        if value is None:
            raise ValueError(
                f"set_property: {property!r} requires `value` "
                "(or `value_display` for volume / panning)"
            )
        coerced = _coerce_value(property, value)
        if bounds is not None and not (bounds[0] <= float(coerced) <= bounds[1]):
            raise ValueError(
                f"set_property: value {value} for {property!r} is out of range "
                f"{list(bounds)}"
            )

    setattr(obj, path[-1], coerced)
    result: dict[str, Any] = {
        "track_index": track_index,
        "property": property,
        "value": coerced,
    }
    # Echo the achieved display (e.g. "-8.0 dB") for parameter-backed props, so a
    # caller can confirm a value_display target was hit — mirrors device
    # set_parameter's _attach_achieved_display, which reads back the param POST
    # write (robust if Live ever re-quantizes a write).
    str_for_value = getattr(obj, "str_for_value", None)
    if callable(str_for_value):
        result["value_display"] = str_for_value(getattr(obj, path[-1]))
    return result


def get_property_handler(
    context: LiveContext, *, track_index: int, property: str
) -> dict[str, Any]:
    if property not in _TRACK_PROPERTIES:
        raise ValueError(
            f"get_property: property {property!r} is not supported; "
            f"valid values are {sorted(_TRACK_PROPERTIES)}"
        )
    path, _bounds = _TRACK_PROPERTIES[property]
    track = _resolve_track(context, track_index)
    obj: Any = track
    for attr in path:
        obj = getattr(obj, attr)
    if property in ("mute", "solo", "arm"):
        obj = bool(obj)
    return {"track_index": track_index, "property": property, "value": obj}


def set_send_handler(
    context: LiveContext, *, track_index: int, return_index: int, value: float
) -> dict[str, Any]:
    """Set one send level (track i -> return j)."""
    if not (0.0 <= value <= 1.0):
        raise ValueError(
            f"set_send: value {value} out of range [0.0, 1.0]"
        )
    track = _resolve_track(context, track_index)
    sends = track.mixer_device.sends
    if return_index < 1 or return_index > len(sends):
        raise IndexError(
            f"return_index {return_index} out of range [1, {len(sends)}] "
            f"for track {track_index}"
        )
    sends[return_index - 1].value = float(value)
    return {
        "track_index": track_index,
        "return_index": return_index,
        "value": float(value),
    }


def get_sends_handler(
    context: LiveContext, *, track_index: int
) -> dict[str, Any]:
    """Read every send level for a track, paired with the destination return name."""
    track = _resolve_track(context, track_index)
    return_tracks = context.song.return_tracks
    sends_out: list[dict[str, Any]] = []
    for i, send in enumerate(track.mixer_device.sends, start=1):
        return_name = return_tracks[i - 1].name if i - 1 < len(return_tracks) else None
        sends_out.append({
            "return_index": i,
            "return_name": return_name,
            "value": float(send.value),
        })
    return {"track_index": track_index, "sends": sends_out}


# ---------------------------------------------------------------------------
# Output routing
# ---------------------------------------------------------------------------
#
# A track's output routing is the signal path OUT of the track: which mixing
# point it feeds (Main / another audio track acting as a bus / Sends Only /
# Ext. Out) plus the sub-channel (Pre FX / Post FX / Post Mixer / Track In).
# This is the keystone primitive for the "PRE-MAIN submaster" pattern
# (RTE-1K9T): route instrument tracks' output to a plain audio bus track, then
# route the bus to Main. Capability-probe + resolve-by-display_name, mirroring
# the device sidechain-source handlers (`handlers/device.py`); the available
# target set is SOURCE-dependent (a bare MIDI track lacks audio-track targets),
# so the teaching error always lists the source track's own options.


def set_output_routing_handler(
    context: LiveContext,
    *,
    track_index: int,
    type_display_name: str,
    channel_display_name: str | None = None,
) -> dict[str, Any]:
    """Set a track's output routing target by ``display_name``.

    ``type_display_name`` is the destination as it appears in Live's UI:
    ``'Main'`` (the master), another audio track's name (a bus, e.g.
    ``'PRE-MAIN'``), ``'Sends Only'``, or ``'Ext. Out'``. The available set is
    source-dependent, so an unknown name raises a teaching error listing the
    *source track's own* available targets. ``channel_display_name`` optionally
    sets the output sub-channel (``'Pre FX'`` / ``'Post FX'`` / ``'Post Mixer'``
    / ``'Track In'``); omit to leave it unchanged.
    """
    track = _resolve_track(context, track_index)
    available_types = getattr(track, "available_output_routing_types", None)
    if available_types is None:
        raise NotImplementedError(
            f"track {track_index} does not expose output_routing_* — its "
            "output cannot be rerouted via the LOM (a clip-less summing "
            "family such as the master would lack it)."
        )

    # Resolve type AND channel before writing either, so an unknown channel
    # never leaves the type reroute half-applied to Live (atomic set).
    matched_type, matched_channel = resolve_routing_write(
        available_types=available_types,
        type_display_name=type_display_name,
        available_channels=getattr(track, "available_output_routing_channels", None),
        channel_display_name=channel_display_name,
        type_label=f"output routing type (track {track_index})",
        channel_label=f"output routing channel (track {track_index})",
        missing_channel_api_msg=(
            f"track {track_index} exposes output_routing_type but not "
            "output_routing_channel — cannot set channel_display_name"
        ),
    )
    track.output_routing_type = matched_type
    if matched_channel is not None:
        track.output_routing_channel = matched_channel

    # Echo the REQUESTED display_name, not a same-callback readback: Live may
    # return the prior value when a routing type is read back in the same
    # callback that set it (the success signal is the side effect).
    result: dict[str, Any] = {
        "track_index": track_index,
        "output_routing_type": type_display_name,
    }
    if matched_channel is not None:
        result["output_routing_channel"] = channel_display_name
    return result


def get_output_routing_handler(
    context: LiveContext, *, track_index: int
) -> dict[str, Any]:
    """Read a track's output routing surface — current target + channel and the
    available enums for each.

    Returns ``has_output_routing: False`` (no raise) when the track doesn't
    expose the API, symmetric with the device-side capability probe — so an
    agent can discover what's configurable before attempting a write.
    """
    track = _resolve_track(context, track_index)
    available_types = getattr(track, "available_output_routing_types", None)
    has_routing = available_types is not None
    result: dict[str, Any] = {
        "track_index": track_index,
        "has_output_routing": has_routing,
    }
    if has_routing:
        result.update(routing_surface_fields(
            current_type=getattr(track, "output_routing_type", None),
            available_types=available_types,
            current_channel=getattr(track, "output_routing_channel", None),
            available_channels=getattr(track, "available_output_routing_channels", None),
        ))
    return result


# ---------------------------------------------------------------------------
# Input routing
# ---------------------------------------------------------------------------
#
# Symmetric to output routing: the signal path INTO the track — which source
# it listens to. For the PRE-MAIN submaster pattern (RTE-1K9T) the bus's
# output routing carries the summed signal to Main; input routing + monitor
# state govern whether a track PASSES a routed source through. A summing bus
# that receives routed audio wants Monitor = In (see monitoring handlers).


def set_input_routing_handler(
    context: LiveContext,
    *,
    track_index: int,
    type_display_name: str,
    channel_display_name: str | None = None,
) -> dict[str, Any]:
    """Set a track's input routing source by ``display_name``.

    ``type_display_name`` is the source as shown in Live's UI: another track's
    name, an external input ('Ext. In'), or 'No Input'. Source-dependent and
    capability-probed exactly like output routing — an unknown name raises a
    teaching error listing this track's own available sources.
    ``channel_display_name`` optionally sets the input sub-channel; omit to
    leave it unchanged.
    """
    track = _resolve_track(context, track_index)
    available_types = getattr(track, "available_input_routing_types", None)
    if available_types is None:
        raise NotImplementedError(
            f"track {track_index} does not expose input_routing_* — its "
            "input cannot be rerouted via the LOM (a clip-less summing "
            "family such as the master would lack it)."
        )

    # Resolve type AND channel before writing either (atomic set — see
    # set_output_routing_handler).
    matched_type, matched_channel = resolve_routing_write(
        available_types=available_types,
        type_display_name=type_display_name,
        available_channels=getattr(track, "available_input_routing_channels", None),
        channel_display_name=channel_display_name,
        type_label=f"input routing type (track {track_index})",
        channel_label=f"input routing channel (track {track_index})",
        missing_channel_api_msg=(
            f"track {track_index} exposes input_routing_type but not "
            "input_routing_channel — cannot set channel_display_name"
        ),
    )
    track.input_routing_type = matched_type
    if matched_channel is not None:
        track.input_routing_channel = matched_channel

    # Echo the REQUESTED display_name (same-callback readback is unreliable).
    result: dict[str, Any] = {
        "track_index": track_index,
        "input_routing_type": type_display_name,
    }
    if matched_channel is not None:
        result["input_routing_channel"] = channel_display_name
    return result


def get_input_routing_handler(
    context: LiveContext, *, track_index: int
) -> dict[str, Any]:
    """Read a track's input routing surface — current source + channel and the
    available enums for each. Returns ``has_input_routing: False`` (no raise)
    when the track doesn't expose the API."""
    track = _resolve_track(context, track_index)
    available_types = getattr(track, "available_input_routing_types", None)
    has_routing = available_types is not None
    result: dict[str, Any] = {
        "track_index": track_index,
        "has_input_routing": has_routing,
    }
    if has_routing:
        result.update(routing_surface_fields(
            current_type=getattr(track, "input_routing_type", None),
            available_types=available_types,
            current_channel=getattr(track, "input_routing_channel", None),
            available_channels=getattr(track, "available_input_routing_channels", None),
        ))
    return result


# ---------------------------------------------------------------------------
# Monitor state
# ---------------------------------------------------------------------------
#
# Live's ``Track.current_monitoring_state`` is an int enum. The wire contract
# is the string name ('In' / 'Auto' / 'Off'); the int mapping is internal and
# isolated here so a future Live-version change is a one-constant fix. A
# summing bus that receives routed audio needs Monitor = In to PASS that
# audio (the live-probed dependency the build plan calls out). Master / return
# tracks don't expose this attribute — the handlers report that, not crash.
_MONITORING_STATES: dict[str, int] = {"In": 0, "Auto": 1, "Off": 2}
_MONITORING_STATE_NAMES: dict[int, str] = {v: k for k, v in _MONITORING_STATES.items()}


def set_monitoring_state_handler(
    context: LiveContext, *, track_index: int, state: str
) -> dict[str, Any]:
    """Set a track's monitor state to 'In', 'Auto', or 'Off'."""
    # Defense-in-depth: the action schema declares enum=('In','Auto','Off') so
    # the dispatcher rejects out-of-enum values before reaching here; this
    # guard covers direct handler calls (tests / future non-dispatch callers).
    if state not in _MONITORING_STATES:
        raise ValueError(
            f"set_monitoring_state: state must be one of "
            f"{sorted(_MONITORING_STATES)}, got {state!r}"
        )
    track = _resolve_track(context, track_index)
    if not hasattr(track, "current_monitoring_state"):
        raise NotImplementedError(
            f"track {track_index} does not expose current_monitoring_state "
            "(a clip-less family such as the master / a return track has no "
            "monitor switch)."
        )
    track.current_monitoring_state = _MONITORING_STATES[state]
    return {"track_index": track_index, "monitoring_state": state}


def get_monitoring_state_handler(
    context: LiveContext, *, track_index: int
) -> dict[str, Any]:
    """Read a track's monitor state. Returns ``has_monitoring_state: False``
    (no raise) for tracks without the switch (master / returns)."""
    track = _resolve_track(context, track_index)
    raw = getattr(track, "current_monitoring_state", None)
    if raw is None:
        return {"track_index": track_index, "has_monitoring_state": False}
    name = _MONITORING_STATE_NAMES.get(int(raw))
    result: dict[str, Any] = {
        "track_index": track_index,
        "has_monitoring_state": True,
        "monitoring_state": name,
    }
    if name is None:
        # Out-of-vocabulary int (the future-Live-enum-shift the mapping
        # isolates) — surface the raw value so it isn't silently lost and the
        # one-constant fix is diagnosable from the wire response.
        result["monitoring_state_raw"] = int(raw)
    return result


def deletion_status_handler(
    context: LiveContext, *, track_indices: list[int] | None = None
) -> dict[str, Any]:
    """Report which 1-based track indices are addressable in the current
    session.

    Reports ``present`` (the track exists at that index) and the track's
    name when it does. Live does not expose a stable "can this be deleted?"
    predicate on the song API — special-case guards (master, certain group
    layouts) are enforced by Live at delete time, not introspectable
    beforehand. The action's job is therefore to confirm presence; delete
    failures are surfaced as structured errors at delete time.

    If ``track_indices`` is omitted, every track in the song is reported.
    """
    song = context.song
    indices = (
        track_indices
        if track_indices is not None
        else list(range(1, len(song.tracks) + 1))
    )
    results: list[dict[str, Any]] = []
    for idx in indices:
        if idx < 1 or idx > len(song.tracks):
            results.append({
                "track_index": idx,
                "present": False,
            })
            continue
        track = song.tracks[idx - 1]
        results.append({
            "track_index": idx,
            "name": track.name,
            "present": True,
        })
    return {"tracks": results}


__all__ = [
    "list_handler",
    "info_handler",
    "create_handler",
    "delete_handler",
    "set_property_handler",
    "get_property_handler",
    "set_send_handler",
    "get_sends_handler",
    "set_output_routing_handler",
    "get_output_routing_handler",
    "set_input_routing_handler",
    "get_input_routing_handler",
    "set_monitoring_state_handler",
    "get_monitoring_state_handler",
    "deletion_status_handler",
]
