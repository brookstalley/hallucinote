"""Shared helpers for resolving Live routing vectors by display name.

Live exposes routing on two object families that share the same vector shape:

- **Devices** carry input routing (the sidechain *source*) —
  ``handlers/device.py``.
- **Tracks** carry output + input routing (the signal *path*) —
  ``handlers/track.py``.

Both resolve a target out of a ``RoutingTypeVector`` / ``RoutingChannelVector``
by its ``display_name`` and enumerate the available names for teaching errors.
These two helpers therefore live here, imported by both handler modules, rather
than copy-pasted (the MIX-6D2N duplication smell the build plan calls out).

Match by ``display_name``, never object identity: Live re-wraps API objects on
every property access, so ``entry is target`` can spuriously fail for two
wrappers around the same underlying routing object.
"""
from __future__ import annotations

from typing import Any


def find_routing_by_display_name(available: Any, display_name: str) -> Any | None:
    """Find the first entry in a routing vector whose ``display_name`` matches.

    ``available`` is a Live ``RoutingTypeVector`` / ``RoutingChannelVector``
    (or ``None`` when the object doesn't expose that routing surface). Returns
    the matching entry, or ``None`` when not found — the caller composes a
    teaching error listing the available names via ``enumerate_available``.
    """
    if available is None:
        return None
    for entry in available:
        if getattr(entry, "display_name", "") == display_name:
            return entry
    return None


def enumerate_available(available: Any) -> list[str]:
    """Collect the ``display_name`` of every entry in a routing vector.

    Used to build teaching errors ("not in available types [...]") and to
    surface the configurable enum on ``get_*_routing`` reads. Returns an empty
    list when ``available`` is ``None``.
    """
    if available is None:
        return []
    out: list[str] = []
    for entry in available:
        dn = getattr(entry, "display_name", None)
        if dn is not None:
            out.append(dn)
    return out


def resolve_routing_write(
    *,
    available_types: Any,
    type_display_name: str,
    available_channels: Any,
    channel_display_name: str | None,
    type_label: str,
    channel_label: str,
    missing_channel_api_msg: str,
) -> tuple[Any, Any | None]:
    """Resolve a routing type and optional channel WITHOUT writing anything.

    Returns ``(matched_type, matched_channel)`` — ``matched_channel`` is
    ``None`` when no channel was requested. Raises ``ValueError`` (unknown
    name, with the available list) or ``NotImplementedError`` (channel
    requested but the object has no channel API) BEFORE the caller touches
    Live, so a bad channel never leaves the type half-applied: the caller
    performs both writes only after both resolve (the atomicity the routing
    set handlers need). ``available_types`` is assumed already non-``None``
    (the caller probes the API presence and raises its own teaching error).
    """
    matched_type = find_routing_by_display_name(available_types, type_display_name)
    if matched_type is None:
        raise ValueError(
            f"{type_label} {type_display_name!r} not in available "
            f"{enumerate_available(available_types)!r}"
        )
    matched_channel = None
    if channel_display_name is not None:
        if available_channels is None:
            raise NotImplementedError(missing_channel_api_msg)
        matched_channel = find_routing_by_display_name(
            available_channels, channel_display_name
        )
        if matched_channel is None:
            raise ValueError(
                f"{channel_label} {channel_display_name!r} not in available "
                f"channels {enumerate_available(available_channels)!r}"
            )
    return matched_type, matched_channel


def routing_surface_fields(
    *,
    current_type: Any,
    available_types: Any,
    current_channel: Any,
    available_channels: Any,
) -> dict[str, Any]:
    """The shared current/available shape of a routing-surface read.

    The caller owns the address fields (``track_index`` / ``device_index`` +
    parent) and the ``has_*_routing`` flag key name; this returns only the
    four object-family-agnostic keys so the read-side stays symmetric across
    the device and track handlers (and matches what the action descriptions
    promise).
    """
    return {
        "current_type": (
            getattr(current_type, "display_name", None)
            if current_type is not None else None
        ),
        "available_types": enumerate_available(available_types),
        "current_channel": (
            getattr(current_channel, "display_name", None)
            if current_channel is not None else None
        ),
        "available_channels": enumerate_available(available_channels),
    }


__all__ = [
    "find_routing_by_display_name",
    "enumerate_available",
    "resolve_routing_write",
    "routing_surface_fields",
]
