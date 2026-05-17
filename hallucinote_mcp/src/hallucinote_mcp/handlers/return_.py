"""Imperative handlers for ``ableton_return`` actions.

Mirrors ``handlers/track.py`` but against ``song.return_tracks``. The
module is named ``return_`` (trailing underscore) because ``return`` is a
Python keyword.

Differences from track handlers:
  - No ``arm`` property (returns can't be record-armed).
  - ``create`` uses ``song.create_return_track()`` which Live exposes
    directly (no equivalent for audio/midi-typed creation — returns are
    always audio).
  - ``set_send`` doesn't apply (return tracks don't have sends to other
    returns in this schema; Live does support return-to-return sends but
    the design surface stays minimal in V1).
"""
from __future__ import annotations

from typing import Any

from ..dispatcher import LiveContext


# Returns have the same mixer layout as tracks minus ``arm``.
_RETURN_PROPERTIES: dict[str, tuple[tuple[str, ...], tuple[float, float] | None]] = {
    "volume":  (("mixer_device", "volume", "value"),  (0.0, 1.0)),
    "panning": (("mixer_device", "panning", "value"), (-1.0, 1.0)),
    "mute":    (("mute",),  None),
    "solo":    (("solo",),  None),
    "color":   (("color",), None),
}


def _coerce_value(property: str, value: Any) -> Any:
    if property in ("mute", "solo"):
        return bool(value)
    if property == "color":
        return int(value)
    return float(value)


def _resolve_return(context: LiveContext, return_index: int) -> Any:
    song = context.song
    if return_index < 1 or return_index > len(song.return_tracks):
        raise IndexError(
            f"return_index {return_index} out of range "
            f"[1, {len(song.return_tracks)}]"
        )
    return song.return_tracks[return_index - 1]


def list_handler(context: LiveContext) -> dict[str, Any]:
    """Return a thin index of all return tracks."""
    out: list[dict[str, Any]] = []
    for i, ret in enumerate(context.song.return_tracks, start=1):
        out.append({
            "return_index": i,
            "name": ret.name,
            "color": getattr(ret, "color", None),
        })
    return {"returns": out}


def info_handler(context: LiveContext, *, return_index: int) -> dict[str, Any]:
    ret = _resolve_return(context, return_index)
    mixer = ret.mixer_device
    return {
        "return_index": return_index,
        "name": ret.name,
        "color": getattr(ret, "color", None),
        "volume": float(mixer.volume.value),
        "panning": float(mixer.panning.value),
        "mute": bool(ret.mute),
        "solo": bool(ret.solo),
    }


def create_handler(
    context: LiveContext, *, name: str | None = None
) -> dict[str, Any]:
    """Create a return track. Live appends to the end of ``song.return_tracks``.

    Live 11+ exposes ``Song.create_return_track()`` (no args). Older Live
    builds don't have this; if the attribute is missing we raise a teaching
    error explaining the gap.
    """
    song = context.song
    create_fn = getattr(song, "create_return_track", None)
    if create_fn is None:
        raise NotImplementedError(
            "Live does not expose Song.create_return_track() in this version. "
            "Create the return manually in Ableton, then re-run the push — "
            "the planner will skip the create step once the return is linked."
        )
    new_return = create_fn()
    if name:
        new_return.name = name
    # Find the new return's 1-based index using identity (``is`` not ``==``)
    # — Live Object Model equality semantics are undocumented; we want the
    # object Live just handed us, not "anything that compares equal".
    for i, ret in enumerate(song.return_tracks, start=1):
        if ret is new_return:
            new_index = i
            break
    else:
        raise RuntimeError(
            "create: Live returned a return-track that isn't in song.return_tracks; "
            "this is a Live API bug"
        )
    return {"return_index": new_index, "name": new_return.name}


def delete_handler(
    context: LiveContext, *, return_index: int
) -> dict[str, Any]:
    song = context.song
    ret = _resolve_return(context, return_index)
    delete_fn = getattr(song, "delete_return_track", None)
    if delete_fn is None:
        raise NotImplementedError(
            "Live does not expose Song.delete_return_track() in this version. "
            "Remove the return manually in Ableton."
        )
    delete_fn(ret)
    return {"deleted_return_index": return_index}


def set_property_handler(
    context: LiveContext, *, return_index: int, property: str, value: Any
) -> dict[str, Any]:
    if property not in _RETURN_PROPERTIES:
        raise ValueError(
            f"set_property: property {property!r} is not supported on returns; "
            f"valid values are {sorted(_RETURN_PROPERTIES)} (no 'arm' — "
            "returns can't be record-armed)"
        )
    path, bounds = _RETURN_PROPERTIES[property]
    coerced = _coerce_value(property, value)
    if bounds is not None and not (bounds[0] <= float(coerced) <= bounds[1]):
        raise ValueError(
            f"set_property: value {value} for {property!r} is out of range "
            f"{list(bounds)}"
        )
    ret = _resolve_return(context, return_index)
    obj: Any = ret
    for attr in path[:-1]:
        obj = getattr(obj, attr)
    setattr(obj, path[-1], coerced)
    return {"return_index": return_index, "property": property, "value": coerced}


__all__ = [
    "list_handler",
    "info_handler",
    "create_handler",
    "delete_handler",
    "set_property_handler",
]
