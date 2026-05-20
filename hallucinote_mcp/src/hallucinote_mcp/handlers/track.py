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
    context: LiveContext, *, track_index: int, property: str, value: Any
) -> dict[str, Any]:
    """Write a single mixer property. Branches on ``property`` to walk to
    the right Live attribute and apply per-property range validation.
    """
    if property not in _TRACK_PROPERTIES:
        raise ValueError(
            f"set_property: property {property!r} is not supported; "
            f"valid values are {sorted(_TRACK_PROPERTIES)}"
        )
    path, bounds = _TRACK_PROPERTIES[property]
    coerced = _coerce_value(property, value)
    if bounds is not None and not (bounds[0] <= float(coerced) <= bounds[1]):
        raise ValueError(
            f"set_property: value {value} for {property!r} is out of range "
            f"{list(bounds)}"
        )
    track = _resolve_track(context, track_index)
    obj: Any = track
    for attr in path[:-1]:
        obj = getattr(obj, attr)
    setattr(obj, path[-1], coerced)
    return {"track_index": track_index, "property": property, "value": coerced}


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
    "deletion_status_handler",
]
