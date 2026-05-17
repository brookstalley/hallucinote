"""Imperative handlers for ``ableton_device`` actions.

Devices live on either a track or a return track. The Live Object Model
exposes both via the same per-chain ``devices`` collection — the only
difference is the navigation root. Handlers address devices via exactly
one of ``track_index`` / ``return_index`` (validated by
``_resolve_parent``) so the agent's mental model stays close to Live's UI
(devices belong to tracks or returns) without forcing a separate
``parent_kind`` param.

set_parameter handles both continuous and enum values via ``value_type``.
Live's DeviceParameter has ``value`` (always a float — for enum params it
is an index into ``value_items``) plus ``value_items`` (tuple of strings)
plus ``str_to_value`` (parses a display string). For the enum path the
handler maps wire ``value`` (string) to an index via ``value_items`` and
writes that. For continuous the handler validates 0.0–1.0 range and
writes via ``value``.

Nested rack chains are deliberately out of scope for M-4 — the parent_chain
walk stops at the top-level chain. Recursing into instrument-rack or
drum-rack chains is tracked in the backlog (capture-side device chain
extension).
"""
from __future__ import annotations

from typing import Any

from ..dispatcher import LiveContext


_PARENT_KINDS = ("track", "return")


def _resolve_parent(
    context: LiveContext,
    *,
    track_index: int | None,
    return_index: int | None,
) -> tuple[Any, str, int]:
    """Return (parent_object, kind, 1-based-index). Raises if neither or both."""
    if track_index is None and return_index is None:
        raise ValueError(
            "must specify exactly one of track_index or return_index "
            "(devices live on a track or a return)"
        )
    if track_index is not None and return_index is not None:
        raise ValueError(
            "specify exactly one of track_index or return_index, not both"
        )
    song = context.song
    if track_index is not None:
        if track_index < 1 or track_index > len(song.tracks):
            raise IndexError(
                f"track_index {track_index} out of range "
                f"[1, {len(song.tracks)}]"
            )
        return song.tracks[track_index - 1], "track", track_index
    assert return_index is not None
    if return_index < 1 or return_index > len(song.return_tracks):
        raise IndexError(
            f"return_index {return_index} out of range "
            f"[1, {len(song.return_tracks)}]"
        )
    return song.return_tracks[return_index - 1], "return", return_index


def _resolve_device(parent: Any, device_index: int) -> Any:
    devices = parent.devices
    if device_index < 1 or device_index > len(devices):
        raise IndexError(
            f"device_index {device_index} out of range [1, {len(devices)}]"
        )
    return devices[device_index - 1]


def _parent_address(kind: str, index: int) -> dict[str, Any]:
    """Build the (kind-specific) key for return values."""
    return {f"{kind}_index": index}


# ---------------------------------------------------------------------------
# list / info / get_parameters
# ---------------------------------------------------------------------------


def list_handler(
    context: LiveContext,
    *,
    track_index: int | None = None,
    return_index: int | None = None,
) -> dict[str, Any]:
    """Return the top-level device chain on a track or return.

    Identity only (name, class_name, position). Per-device detail (parameters,
    routing, etc.) is each device's ``info`` action's job.
    """
    parent, kind, idx = _resolve_parent(
        context, track_index=track_index, return_index=return_index
    )
    devices_out: list[dict[str, Any]] = []
    for i, dev in enumerate(parent.devices, start=1):
        devices_out.append({
            "device_index": i,
            "name": getattr(dev, "name", ""),
            "class_name": getattr(dev, "class_name", ""),
            "is_active": bool(getattr(dev, "is_active", True)),
        })
    result: dict[str, Any] = {"parent_kind": kind, "devices": devices_out}
    result.update(_parent_address(kind, idx))
    return result


def info_handler(
    context: LiveContext,
    *,
    device_index: int,
    track_index: int | None = None,
    return_index: int | None = None,
) -> dict[str, Any]:
    """Identity + activation + parameter count for one device."""
    parent, kind, idx = _resolve_parent(
        context, track_index=track_index, return_index=return_index
    )
    dev = _resolve_device(parent, device_index)
    params = getattr(dev, "parameters", ())
    result: dict[str, Any] = {
        "device_index": device_index,
        "name": getattr(dev, "name", ""),
        "class_name": getattr(dev, "class_name", ""),
        "is_active": bool(getattr(dev, "is_active", True)),
        "parameter_count": len(params),
        "can_have_chains": bool(getattr(dev, "can_have_chains", False)),
        "parent_kind": kind,
    }
    result.update(_parent_address(kind, idx))
    return result


def get_parameters_handler(
    context: LiveContext,
    *,
    device_index: int,
    track_index: int | None = None,
    return_index: int | None = None,
    detail: str = "summary",
) -> dict[str, Any]:
    """Return device parameters with current values.

    ``detail='summary'`` returns name + value + value_display (cheap).
    ``detail='full'`` adds min/max + is_enum + value_items (more expensive
    on devices with many enum params).
    """
    if detail not in ("summary", "full"):
        raise ValueError(
            f"detail must be 'summary' or 'full', got {detail!r}"
        )
    parent, kind, idx = _resolve_parent(
        context, track_index=track_index, return_index=return_index
    )
    dev = _resolve_device(parent, device_index)
    params_out: list[dict[str, Any]] = []
    for p in getattr(dev, "parameters", ()):
        entry: dict[str, Any] = {
            "name": p.name,
            "value": float(p.value),
            "value_display": str(getattr(p, "str_for_value", lambda v: "")(p.value))
                if hasattr(p, "str_for_value") else "",
        }
        if detail == "full":
            entry["min"] = float(getattr(p, "min", 0.0))
            entry["max"] = float(getattr(p, "max", 1.0))
            items = tuple(getattr(p, "value_items", ()) or ())
            entry["is_enum"] = bool(items)
            if items:
                entry["value_items"] = list(items)
        params_out.append(entry)
    result: dict[str, Any] = {
        "device_index": device_index,
        "parent_kind": kind,
        "parameters": params_out,
    }
    result.update(_parent_address(kind, idx))
    return result


# ---------------------------------------------------------------------------
# load / delete
# ---------------------------------------------------------------------------


def load_handler(
    context: LiveContext,
    *,
    kind: str,
    preset_uri: str | None = None,
    track_index: int | None = None,
    return_index: int | None = None,
    position: int | None = None,
) -> dict[str, Any]:
    """Load a device onto a track or return chain.

    ``kind`` is the Live device class name (e.g. ``'Compressor2'``,
    ``'Operator'``). ``preset_uri`` is an optional Live browser URI for
    a specific preset/.adv file; if omitted, Live's default for that kind
    is loaded.

    ``position`` is the 1-based slot in the chain where the new device
    should sit. Live's API loads via browser-URI and the device appears
    at the chain's tail by default; if ``position`` is set, the handler
    moves the new device into place. Returns the new ``device_index``.
    """
    parent, parent_kind, parent_idx = _resolve_parent(
        context, track_index=track_index, return_index=return_index
    )
    if not isinstance(kind, str) or not kind:
        raise ValueError("kind must be a non-empty Live device class name")
    chain_before = list(parent.devices)
    # Live's modern API exposes load via the song's view; the legacy fork
    # used `track.load_device(browser_uri)`. We prefer the modern path,
    # falling back to the legacy method if available.
    loader = getattr(parent, "load_device", None)
    if loader is None:
        raise NotImplementedError(
            f"{parent_kind} does not expose load_device — older Live build "
            "or unsupported track type (master / group)"
        )
    loader(kind=kind, preset_uri=preset_uri) if _loader_accepts_kwargs(loader) \
        else loader(preset_uri or kind)
    chain_after = list(parent.devices)
    if len(chain_after) <= len(chain_before):
        raise RuntimeError(
            f"load: Live did not append a device on {parent_kind} "
            f"{parent_idx} after load_device({kind!r}); this may be a "
            "browser-URI miss or an unsupported device kind"
        )
    new_device = chain_after[-1]
    new_index = len(chain_after)
    # Optional re-position. Live's API exposes
    # `track.devices` as immutable in some versions; movement is via
    # `move_device` if present, else a documented limitation.
    if position is not None:
        if position < 1 or position > new_index:
            raise IndexError(
                f"position {position} out of range [1, {new_index}]"
            )
        if position != new_index:
            mover = getattr(parent, "move_device", None)
            if mover is None:
                raise NotImplementedError(
                    f"{parent_kind} does not expose move_device — the device "
                    f"was loaded at position {new_index}; manual reordering "
                    "via Live is required"
                )
            mover(new_device, position - 1)
            new_index = position
    result: dict[str, Any] = {
        "device_index": new_index,
        "kind": kind,
        "name": getattr(new_device, "name", ""),
        "parent_kind": parent_kind,
    }
    result.update(_parent_address(parent_kind, parent_idx))
    if preset_uri is not None:
        result["preset_uri"] = preset_uri
    return result


def _loader_accepts_kwargs(loader: Any) -> bool:
    """Heuristic: does ``loader`` accept keyword args (modern API) or only
    positional (legacy)? We can't introspect Live's C-implemented methods
    reliably; this falls back to positional on uncertainty.
    """
    try:
        import inspect
        sig = inspect.signature(loader)
        return any(
            p.kind in (p.KEYWORD_ONLY, p.POSITIONAL_OR_KEYWORD)
            for p in sig.parameters.values()
        )
    except (TypeError, ValueError):
        return False


def delete_handler(
    context: LiveContext,
    *,
    device_index: int,
    track_index: int | None = None,
    return_index: int | None = None,
) -> dict[str, Any]:
    """Remove a device from a track or return chain."""
    parent, kind, idx = _resolve_parent(
        context, track_index=track_index, return_index=return_index
    )
    _ = _resolve_device(parent, device_index)  # validates range
    delete_fn = getattr(parent, "delete_device", None)
    if delete_fn is None:
        raise NotImplementedError(
            f"{kind} does not expose delete_device — older Live build "
            "or unsupported track type"
        )
    delete_fn(device_index - 1)  # Live's API is 0-based
    result: dict[str, Any] = {
        "deleted_device_index": device_index,
        "parent_kind": kind,
    }
    result.update(_parent_address(kind, idx))
    return result


# ---------------------------------------------------------------------------
# enable / disable / set_parameter
# ---------------------------------------------------------------------------


def _set_active(
    context: LiveContext,
    *,
    device_index: int,
    track_index: int | None,
    return_index: int | None,
    is_active: bool,
) -> dict[str, Any]:
    parent, kind, idx = _resolve_parent(
        context, track_index=track_index, return_index=return_index
    )
    dev = _resolve_device(parent, device_index)
    dev.is_active = is_active
    result: dict[str, Any] = {
        "device_index": device_index,
        "is_active": is_active,
        "parent_kind": kind,
    }
    result.update(_parent_address(kind, idx))
    return result


def enable_handler(
    context: LiveContext,
    *,
    device_index: int,
    track_index: int | None = None,
    return_index: int | None = None,
) -> dict[str, Any]:
    return _set_active(
        context,
        device_index=device_index,
        track_index=track_index,
        return_index=return_index,
        is_active=True,
    )


def disable_handler(
    context: LiveContext,
    *,
    device_index: int,
    track_index: int | None = None,
    return_index: int | None = None,
) -> dict[str, Any]:
    return _set_active(
        context,
        device_index=device_index,
        track_index=track_index,
        return_index=return_index,
        is_active=False,
    )


_VALUE_TYPES = ("continuous", "enum")


def set_parameter_handler(
    context: LiveContext,
    *,
    device_index: int,
    parameter_name: str,
    value: Any,
    value_type: str = "continuous",
    track_index: int | None = None,
    return_index: int | None = None,
) -> dict[str, Any]:
    """Write one device parameter.

    ``value_type='continuous'`` (default): ``value`` must be a float in
    [param.min, param.max]. The handler writes via Live's ``parameter.value``.

    ``value_type='enum'``: ``value`` must be a string in
    ``parameter.value_items``. The handler resolves it to the index of that
    item in ``value_items`` and writes the index via ``parameter.value``
    (which is how Live represents enum state internally).

    Resolves the legacy fork's gap #17b workaround — the new path doesn't
    depend on the broken ``set_device_parameter`` fork tool.
    """
    if value_type not in _VALUE_TYPES:
        raise ValueError(
            f"value_type must be one of {list(_VALUE_TYPES)}, got {value_type!r}"
        )
    parent, kind, idx = _resolve_parent(
        context, track_index=track_index, return_index=return_index
    )
    dev = _resolve_device(parent, device_index)
    target_param = None
    for p in getattr(dev, "parameters", ()):
        if p.name == parameter_name:
            target_param = p
            break
    if target_param is None:
        available = [p.name for p in getattr(dev, "parameters", ())]
        raise ValueError(
            f"parameter {parameter_name!r} not found on device "
            f"{device_index}; available: {available}"
        )

    if value_type == "enum":
        items = tuple(getattr(target_param, "value_items", ()) or ())
        if not items:
            raise ValueError(
                f"parameter {parameter_name!r} is not an enum parameter "
                f"(no value_items); use value_type='continuous'"
            )
        if not isinstance(value, str):
            raise ValueError(
                f"value_type='enum' requires value as a string, got "
                f"{type(value).__name__}"
            )
        if value not in items:
            raise ValueError(
                f"enum value {value!r} not in value_items for parameter "
                f"{parameter_name!r}: {list(items)}"
            )
        new_value: float = float(items.index(value))
        target_param.value = new_value
    else:
        try:
            coerced = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"value_type='continuous' requires a numeric value, got "
                f"{value!r}"
            ) from exc
        p_min = float(getattr(target_param, "min", 0.0))
        p_max = float(getattr(target_param, "max", 1.0))
        if not (p_min <= coerced <= p_max):
            raise ValueError(
                f"value {coerced} out of range [{p_min}, {p_max}] for "
                f"parameter {parameter_name!r}"
            )
        target_param.value = coerced

    result: dict[str, Any] = {
        "device_index": device_index,
        "parameter_name": parameter_name,
        "value": float(target_param.value),
        "value_type": value_type,
        "parent_kind": kind,
    }
    result.update(_parent_address(kind, idx))
    return result


# ---------------------------------------------------------------------------
# Sidechain / routing / preset / pad_info
# ---------------------------------------------------------------------------


def set_sidechain_handler(
    context: LiveContext,
    *,
    device_index: int,
    enabled: bool,
    track_index: int | None = None,
    return_index: int | None = None,
    source_track_index: int | None = None,
    gain_db: float | None = None,
) -> dict[str, Any]:
    """Configure a Compressor's sidechain routing.

    Live exposes the Compressor's sidechain via four routing properties:
    ``input_routing_type``, ``input_routing_channel``, plus an
    ``input_meter_left/right`` for monitoring. The Compressor2 device
    additionally has ``sidechain_active`` and a ``sidechain_gain`` parameter.

    This handler is intentionally device-class-aware: it expects a Compressor
    or Compressor2; on other devices it raises a teaching error. Wider
    sidechain support (Glue Compressor, gates) is a backlog candidate.
    """
    parent, kind, idx = _resolve_parent(
        context, track_index=track_index, return_index=return_index
    )
    dev = _resolve_device(parent, device_index)
    class_name = getattr(dev, "class_name", "")
    if "Compressor" not in class_name:
        raise NotImplementedError(
            f"sidechain configuration is only supported on Compressor "
            f"devices in M-4; got class_name={class_name!r}"
        )

    if not enabled:
        # Simplest disable: set sidechain_active off.
        active = getattr(dev, "sidechain_active", None)
        if active is None:
            raise NotImplementedError(
                f"device {class_name} does not expose sidechain_active"
            )
        dev.sidechain_active = False
        result: dict[str, Any] = {
            "device_index": device_index,
            "enabled": False,
            "parent_kind": kind,
        }
        result.update(_parent_address(kind, idx))
        return result

    if source_track_index is None:
        raise ValueError(
            "set_sidechain: enabled=True requires source_track_index "
            "(1-based)"
        )
    song = context.song
    if source_track_index < 1 or source_track_index > len(song.tracks):
        raise IndexError(
            f"source_track_index {source_track_index} out of range "
            f"[1, {len(song.tracks)}]"
        )
    source_track = song.tracks[source_track_index - 1]

    # Walk Live's Compressor sidechain routing properties.
    if hasattr(dev, "sidechain_active"):
        dev.sidechain_active = True
    routings = getattr(dev, "available_input_routing_types", None)
    if routings is not None:
        # Find the matching routing object for source_track.
        matched = None
        for r in routings:
            if getattr(r, "display_name", "") == source_track.name:
                matched = r
                break
        if matched is None:
            raise ValueError(
                f"source track {source_track.name!r} not in available "
                f"sidechain routings for {class_name}"
            )
        dev.input_routing_type = matched
    if gain_db is not None:
        gain_param = None
        for p in getattr(dev, "parameters", ()):
            if p.name in ("SC Gain", "Sidechain Gain"):
                gain_param = p
                break
        if gain_param is not None:
            gain_param.value = float(gain_db)
    result = {
        "device_index": device_index,
        "enabled": True,
        "source_track_index": source_track_index,
        "parent_kind": kind,
    }
    if gain_db is not None:
        result["gain_db"] = float(gain_db)
    result.update(_parent_address(kind, idx))
    return result


def get_routing_handler(
    context: LiveContext,
    *,
    device_index: int,
    track_index: int | None = None,
    return_index: int | None = None,
) -> dict[str, Any]:
    """Read a device's input routing summary (sidechain source, etc.)."""
    parent, kind, idx = _resolve_parent(
        context, track_index=track_index, return_index=return_index
    )
    dev = _resolve_device(parent, device_index)
    rt = getattr(dev, "input_routing_type", None)
    routing_name = getattr(rt, "display_name", None) if rt is not None else None
    result: dict[str, Any] = {
        "device_index": device_index,
        "input_routing": routing_name,
        "sidechain_active": bool(getattr(dev, "sidechain_active", False)),
        "parent_kind": kind,
    }
    result.update(_parent_address(kind, idx))
    return result


_PRESET_DIRECTIONS = ("next", "previous", "current")


def navigate_preset_handler(
    context: LiveContext,
    *,
    device_index: int,
    direction: str,
    track_index: int | None = None,
    return_index: int | None = None,
) -> dict[str, Any]:
    """Step a device's preset within its browser folder.

    Live exposes ``device.selected_preset_index`` plus methods like
    ``next_preset`` / ``previous_preset`` on some device classes. This
    handler is best-effort: ``current`` just reads the index, ``next`` /
    ``previous`` step it.
    """
    if direction not in _PRESET_DIRECTIONS:
        raise ValueError(
            f"direction must be one of {list(_PRESET_DIRECTIONS)}, got "
            f"{direction!r}"
        )
    parent, kind, idx = _resolve_parent(
        context, track_index=track_index, return_index=return_index
    )
    dev = _resolve_device(parent, device_index)
    if direction == "current":
        index_now = getattr(dev, "selected_preset_index", None)
        name_now = getattr(dev, "selected_preset_name", None)
        result: dict[str, Any] = {
            "device_index": device_index,
            "direction": direction,
            "preset_index": index_now,
            "preset_name": name_now,
            "parent_kind": kind,
        }
        result.update(_parent_address(kind, idx))
        return result
    step_fn = getattr(
        dev, "next_preset" if direction == "next" else "previous_preset", None
    )
    if step_fn is None:
        raise NotImplementedError(
            f"device {device_index} does not support preset navigation "
            f"({direction!r})"
        )
    step_fn()
    result = {
        "device_index": device_index,
        "direction": direction,
        "preset_index": getattr(dev, "selected_preset_index", None),
        "preset_name": getattr(dev, "selected_preset_name", None),
        "parent_kind": kind,
    }
    result.update(_parent_address(kind, idx))
    return result


def pad_info_handler(
    context: LiveContext,
    *,
    device_index: int,
    track_index: int | None = None,
    return_index: int | None = None,
) -> dict[str, Any]:
    """Read drum-rack pad layout: pitch → chain identity.

    Drum racks (Live's DrumGroupDevice) expose 128 ``drum_pads`` keyed by
    MIDI note number. Each pad has a chain (possibly empty). This handler
    returns the non-empty pads as a list of {note, name, chain_name}.

    On a non-drum-rack device this raises a teaching error.
    """
    parent, kind, idx = _resolve_parent(
        context, track_index=track_index, return_index=return_index
    )
    dev = _resolve_device(parent, device_index)
    pads = getattr(dev, "drum_pads", None)
    if pads is None:
        raise NotImplementedError(
            f"device {device_index} ({getattr(dev, 'class_name', '?')}) is "
            "not a drum rack; pad_info only applies to DrumGroupDevice"
        )
    pads_out: list[dict[str, Any]] = []
    for pad in pads:
        # Live's pad iteration is sometimes by-attribute; treat the
        # collection as an iterable and read fields defensively.
        note = getattr(pad, "note", None)
        chain_name = None
        chains = getattr(pad, "chains", ())
        if chains:
            chain_name = getattr(chains[0], "name", None)
        if chain_name is None and not chains:
            continue  # empty pad
        pads_out.append({
            "note": note,
            "name": getattr(pad, "name", ""),
            "chain_name": chain_name,
        })
    result: dict[str, Any] = {
        "device_index": device_index,
        "pads": pads_out,
        "parent_kind": kind,
    }
    result.update(_parent_address(kind, idx))
    return result


__all__ = [
    "list_handler",
    "info_handler",
    "get_parameters_handler",
    "load_handler",
    "delete_handler",
    "enable_handler",
    "disable_handler",
    "set_parameter_handler",
    "set_sidechain_handler",
    "get_routing_handler",
    "navigate_preset_handler",
    "pad_info_handler",
]
