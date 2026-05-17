"""Imperative handlers for ``ableton_arrangement`` actions.

Arrangement state lives at ``song.cue_points`` (the cue list),
``song.loop`` / ``song.loop_start`` / ``song.loop_length`` (the loop
region), ``song.last_event_time`` (the arrangement total length), and
``song.get_application().view`` (arranger view controls).

Cue point time positions are in **beats** on the wire (Wave M-3/M-4
principle: wire stays meter-agnostic; Hallucinote planner converts from
bar-based song positions via the time-signature map before emit). The
handler does no bar/beat translation.

Cue point name gap (Hallucinote gap #13) — Live's API exposes
``cue.name`` as readable AND writable, but the legacy fork's
``get_cue_points`` returned only numeric IDs, not names. With our
greenfield Remote Script we read names directly; the gap is resolved
for the new MCP server's lifetime.
"""
from __future__ import annotations

from typing import Any

from ..dispatcher import LiveContext


# ---------------------------------------------------------------------------
# info
# ---------------------------------------------------------------------------


def info_handler(context: LiveContext) -> dict[str, Any]:
    """Arrangement-level state snapshot.

    Returns global tempo + signature (the song-level values at the start
    of the arrangement; per-bar automation is captured by separate
    envelope reads when gap-blocked), arrangement total length in beats,
    loop region, and cue count.
    """
    song = context.song
    sig_num = int(getattr(song, "signature_numerator", 4))
    sig_den = int(getattr(song, "signature_denominator", 4))
    return {
        "tempo": float(getattr(song, "tempo", 120.0)),
        "signature": {"numerator": sig_num, "denominator": sig_den},
        "total_length_beats": float(getattr(song, "last_event_time", 0.0)),
        "loop_enabled": bool(getattr(song, "loop", False)),
        "loop_start_beats": float(getattr(song, "loop_start", 0.0)),
        "loop_length_beats": float(getattr(song, "loop_length", 0.0)),
        "cue_count": len(getattr(song, "cue_points", ())),
    }


# ---------------------------------------------------------------------------
# set_loop
# ---------------------------------------------------------------------------


def set_loop_handler(
    context: LiveContext,
    *,
    enabled: bool,
    start_beats: float | None = None,
    end_beats: float | None = None,
) -> dict[str, Any]:
    """Toggle the arrangement loop + optionally set its region in beats.

    Both start_beats and end_beats must be passed together (or neither).
    Live stores the loop as (loop_start, loop_length); we compute length
    from (end_beats - start_beats).

    Wave M-3 principle: wire is meter-agnostic — beats not bars. The
    Hallucinote planner converts bar-based song positions before emit.
    """
    if (start_beats is None) != (end_beats is None):
        raise ValueError(
            "set_loop: pass start_beats AND end_beats together, or neither"
        )
    song = context.song
    if start_beats is not None and end_beats is not None:
        if start_beats < 0:
            raise ValueError(f"start_beats {start_beats} must be >= 0")
        if end_beats <= start_beats:
            raise ValueError(
                f"end_beats {end_beats} must be > start_beats {start_beats}"
            )
        song.loop_start = float(start_beats)
        song.loop_length = float(end_beats) - float(start_beats)
    song.loop = bool(enabled)
    return {
        "enabled": bool(enabled),
        "loop_start_beats": float(getattr(song, "loop_start", 0.0)),
        "loop_length_beats": float(getattr(song, "loop_length", 0.0)),
    }


# ---------------------------------------------------------------------------
# control_view
# ---------------------------------------------------------------------------


_VIEW_ACTIONS = (
    "zoom_in", "zoom_out", "scroll_left", "scroll_right",
    "follow_on", "follow_off", "collapse_track", "expand_track",
)


def control_view_handler(
    context: LiveContext,
    *,
    action_kind: str,
    track_index: int | None = None,
) -> dict[str, Any]:
    """Step the arranger view. Each action_kind maps to a Live API call:

      - zoom_in / zoom_out — application.view.zoom_view
      - scroll_left / scroll_right — application.view.scroll_view
      - follow_on / follow_off — song.view.follow_song property
      - collapse_track / expand_track — per-track property on the arranger
    """
    if action_kind not in _VIEW_ACTIONS:
        raise ValueError(
            f"action_kind {action_kind!r} not in {list(_VIEW_ACTIONS)}"
        )
    song = context.song
    application_view = song.get_application().view if hasattr(song, "get_application") else None

    if action_kind in ("follow_on", "follow_off"):
        target = song.view
        target.follow_song = (action_kind == "follow_on")
        return {"action_kind": action_kind, "follow_song": target.follow_song}

    if action_kind in ("zoom_in", "zoom_out"):
        if application_view is None:
            raise NotImplementedError(
                "application.view not exposed in this Live version"
            )
        # Live's zoom_view takes (direction, view_name, optional bool)
        # direction: 0=in, 1=out, 2=left, 3=right (per Remote Script SDK)
        direction = 0 if action_kind == "zoom_in" else 1
        application_view.zoom_view(direction, "Arranger", False)
        return {"action_kind": action_kind}

    if action_kind in ("scroll_left", "scroll_right"):
        if application_view is None:
            raise NotImplementedError(
                "application.view not exposed in this Live version"
            )
        direction = 2 if action_kind == "scroll_left" else 3
        application_view.scroll_view(direction, "Arranger", False)
        return {"action_kind": action_kind}

    # collapse_track / expand_track — per-track
    if track_index is None:
        raise ValueError(
            f"action_kind={action_kind!r} requires track_index"
        )
    if track_index < 1 or track_index > len(song.tracks):
        raise IndexError(
            f"track_index {track_index} out of range [1, {len(song.tracks)}]"
        )
    track = song.tracks[track_index - 1]
    is_collapsed = (action_kind == "collapse_track")
    # Per Live's API, the property is `is_showing_chains` (rack) or
    # `arrangement_track_height` (display height). We expose a uniform
    # collapsed/expanded affordance via the `fold_state` attribute when
    # present; otherwise fall through to setting display height.
    if hasattr(track, "fold_state"):
        track.fold_state = 1 if is_collapsed else 0
    elif hasattr(track, "is_folded"):
        track.is_folded = is_collapsed
    else:
        raise NotImplementedError(
            f"track {track_index} does not support collapse/expand in this "
            "Live version"
        )
    return {"action_kind": action_kind, "track_index": track_index}


# ---------------------------------------------------------------------------
# Cue points
# ---------------------------------------------------------------------------


def cue_list_handler(context: LiveContext) -> dict[str, Any]:
    """Return all arrangement cue points.

    Each entry: {cue_index (1-based), position_beats, name}.
    Names round-trip cleanly via Live's API in our greenfield server —
    the legacy fork's gap #13 (numeric-only names) doesn't apply here.
    """
    song = context.song
    cues = getattr(song, "cue_points", ())
    out: list[dict[str, Any]] = []
    for i, cue in enumerate(cues, start=1):
        out.append({
            "cue_index": i,
            "position_beats": float(getattr(cue, "time", 0.0)),
            "name": str(getattr(cue, "name", "")),
        })
    return {"cue_points": out}


def cue_create_handler(
    context: LiveContext,
    *,
    position_beats: float,
    name: str | None = None,
) -> dict[str, Any]:
    """Create a cue point at position_beats. Live's API takes the play
    position via set_or_delete_cue_point (which adds at the current play
    head). We temporarily seek to position_beats, add the cue, then
    optionally rename + restore.

    **Toggle-collision guard.** Live's ``set_or_delete_cue`` is a TOGGLE —
    calling it at a position that already has a cue DELETES that cue
    instead of creating a new one. cue_create's contract is to create;
    we pre-check for an existing cue at the position and raise a teaching
    error instead of silently destroying it.
    """
    if position_beats < 0:
        raise ValueError(f"position_beats {position_beats} must be >= 0")
    song = context.song
    # Pre-check: refuse to "create" when the position is already occupied.
    # Float tolerance matches the apply-side `pos_key` precision.
    for existing in getattr(song, "cue_points", ()):
        if abs(float(getattr(existing, "time", -1.0)) - float(position_beats)) < 1e-6:
            raise ValueError(
                f"cue_create: a cue already exists at position_beats="
                f"{position_beats} (name={getattr(existing, 'name', '')!r}); "
                "use cue_delete first if you want to replace it"
            )
    create_fn = getattr(song, "set_or_delete_cue", None)
    if create_fn is not None:
        # Newer Live exposes set_or_delete_cue(time) directly.
        create_fn(float(position_beats))
    else:
        # Fallback: seek then use the toggle on the current play position.
        prior = float(getattr(song, "current_song_time", 0.0))
        song.current_song_time = float(position_beats)
        toggle = getattr(song, "set_or_delete_cue_point", None)
        if toggle is None:
            raise NotImplementedError(
                "Live does not expose a cue-point creation API in this version"
            )
        toggle()
        song.current_song_time = prior
    # Find the new cue (by position match) and rename if requested.
    new_cue_index: int | None = None
    new_cue = None
    for i, cue in enumerate(getattr(song, "cue_points", ()), start=1):
        if abs(float(getattr(cue, "time", -1.0)) - float(position_beats)) < 1e-6:
            new_cue_index = i
            new_cue = cue
            break
    if new_cue is None:
        raise RuntimeError(
            f"cue_create: could not locate the new cue at "
            f"position_beats={position_beats}"
        )
    if name is not None:
        new_cue.name = name
    return {
        "cue_index": new_cue_index,
        "position_beats": float(position_beats),
        "name": str(getattr(new_cue, "name", "")),
    }


def cue_delete_handler(
    context: LiveContext,
    *,
    cue_index: int,
) -> dict[str, Any]:
    """Delete a cue by 1-based index."""
    song = context.song
    cues = list(getattr(song, "cue_points", ()))
    if cue_index < 1 or cue_index > len(cues):
        raise IndexError(
            f"cue_index {cue_index} out of range [1, {len(cues)}]"
        )
    target = cues[cue_index - 1]
    # Live exposes deletion via the cue's own method or via
    # song.set_or_delete_cue(time). Prefer the per-cue method when present.
    delete_fn = getattr(target, "delete", None) or getattr(target, "remove", None)
    if delete_fn is not None:
        delete_fn()
    else:
        toggle = getattr(song, "set_or_delete_cue", None)
        if toggle is None:
            raise NotImplementedError(
                "Live does not expose cue deletion in this version"
            )
        toggle(float(getattr(target, "time", 0.0)))
    return {"deleted_cue_index": cue_index}


_JUMP_DIRECTIONS = ("next", "previous")


def cue_jump_handler(
    context: LiveContext,
    *,
    direction: str | None = None,
    name: str | None = None,
) -> dict[str, Any]:
    """Jump the playhead to a cue. Either ``direction`` ('next'|'previous')
    relative to current position, or ``name`` to jump to a specific cue.
    Exactly one of the two must be provided.
    """
    if (direction is None) == (name is None):
        raise ValueError(
            "cue_jump: provide exactly one of direction (next|previous) OR name"
        )
    song = context.song
    if direction is not None:
        if direction not in _JUMP_DIRECTIONS:
            raise ValueError(
                f"direction {direction!r} not in {list(_JUMP_DIRECTIONS)}"
            )
        fn = getattr(
            song, "jump_to_next_cue" if direction == "next" else "jump_to_prev_cue",
            None,
        )
        if fn is None:
            raise NotImplementedError(
                f"Live does not expose jump_to_{direction}_cue in this version"
            )
        fn()
        return {
            "direction": direction,
            "position_beats": float(getattr(song, "current_song_time", 0.0)),
        }
    # name path
    target = None
    for cue in getattr(song, "cue_points", ()):
        if getattr(cue, "name", "") == name:
            target = cue
            break
    if target is None:
        available = [
            getattr(c, "name", "") for c in getattr(song, "cue_points", ())
        ]
        raise ValueError(
            f"cue_jump: no cue named {name!r}; available: {available}"
        )
    jumper = getattr(target, "jump", None)
    if jumper is not None:
        jumper()
    else:
        song.current_song_time = float(getattr(target, "time", 0.0))
    return {
        "name": name,
        "position_beats": float(getattr(song, "current_song_time", 0.0)),
    }


__all__ = [
    "info_handler",
    "set_loop_handler",
    "control_view_handler",
    "cue_list_handler",
    "cue_create_handler",
    "cue_delete_handler",
    "cue_jump_handler",
]
