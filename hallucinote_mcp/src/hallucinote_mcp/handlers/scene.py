"""Imperative handlers for ``ableton_scene`` actions.

Scenes are session-view rows that span all tracks; each scene has its own
name, color, optional tempo, optional time signature, and (when fired)
plays all clips in that row simultaneously.

Live's API: ``song.scenes[i]`` (1-based becomes 0-based at access),
``song.create_scene(index)`` (insert at 0-based index; -1 appends),
``song.delete_scene(index)`` (0-based), ``scene.fire()``.

Scene-local tempo / signature: each scene exposes ``tempo`` and
``time_signature_numerator`` / ``time_signature_denominator`` properties.
A value of ``-1`` on tempo means "no scene tempo" (fall through to song
tempo). We treat that as nullable on the wire.

The design doc lists an `insert_at` action separately from `create`; we
collapse them — `create` accepts an optional `position` for insert. The
collapse is documented in the action description so the design doc
diff is visible.
"""
from __future__ import annotations

from typing import Any

from ..dispatcher import LiveContext


def _resolve_scene(context: LiveContext, scene_index: int) -> Any:
    song = context.song
    scenes = song.scenes
    if scene_index < 1 or scene_index > len(scenes):
        raise IndexError(
            f"scene_index {scene_index} out of range [1, {len(scenes)}]"
        )
    return scenes[scene_index - 1]


def _scene_summary(scene: Any, index: int) -> dict[str, Any]:
    tempo = float(getattr(scene, "tempo", -1.0))
    return {
        "scene_index": index,
        "name": str(getattr(scene, "name", "")),
        "color": getattr(scene, "color", None),
        "tempo": tempo if tempo > 0 else None,  # -1 == "no scene tempo"
        "time_signature": {
            "numerator": int(getattr(scene, "time_signature_numerator", 4)),
            "denominator": int(getattr(scene, "time_signature_denominator", 4)),
        },
    }


def list_handler(context: LiveContext) -> dict[str, Any]:
    """Thin index of all session-view scenes."""
    scenes_out: list[dict[str, Any]] = []
    for i, scene in enumerate(context.song.scenes, start=1):
        scenes_out.append(_scene_summary(scene, i))
    return {"scenes": scenes_out}


def info_handler(
    context: LiveContext, *, scene_index: int
) -> dict[str, Any]:
    """Scene identity + per-track clip presence count (how many slots in
    this row have a clip)."""
    scene = _resolve_scene(context, scene_index)
    out = _scene_summary(scene, scene_index)
    # Live exposes scene.clip_slots (one per track). Count non-empty.
    slots = getattr(scene, "clip_slots", ())
    out["clip_count"] = sum(1 for s in slots if getattr(s, "clip", None) is not None)
    return out


def create_handler(
    context: LiveContext,
    *,
    name: str | None = None,
    position: int | None = None,
) -> dict[str, Any]:
    """Create a new scene. position (1-based) inserts before; if omitted,
    Live appends to the end.

    This action absorbs the design doc's separate `insert_at` action —
    they describe the same operation. See the action's description for
    the design doc reconciliation.
    """
    song = context.song
    create_fn = getattr(song, "create_scene", None)
    if create_fn is None:
        raise NotImplementedError(
            "Song.create_scene not exposed in this Live version"
        )
    insert_at = (position - 1) if position is not None else -1
    if position is not None and (position < 1 or position > len(song.scenes) + 1):
        raise IndexError(
            f"position {position} out of range [1, {len(song.scenes) + 1}]"
        )
    new_scene = create_fn(insert_at)
    if name:
        new_scene.name = name
    # ``Song.create_scene(insert_at)`` inserts at the given 0-based position,
    # or appends if -1. The new scene's 1-based index is deterministic from
    # that. We do NOT scan ``song.scenes`` for identity: Live re-wraps API
    # objects on each property access, so ``new_scene is scene`` and
    # equality can both spuriously return False (the same root cause as the
    # arrangement / track / return create handlers; see those for context).
    new_index = len(song.scenes) if insert_at == -1 else insert_at + 1
    return {
        "scene_index": new_index,
        "name": str(getattr(new_scene, "name", "")),
    }


def delete_handler(
    context: LiveContext, *, scene_index: int
) -> dict[str, Any]:
    """W18-E: refuse-and-teach symmetry with ``ableton_track(action='delete')``.
    Live requires the set to contain at least one scene; deleting the last
    surviving scene fails inside Live's API. Refuse before the call with a
    recoverable hint (create a new scene first) instead of surfacing the
    bare LOM error.
    """
    song = context.song
    _ = _resolve_scene(context, scene_index)  # validate
    if len(song.scenes) <= 1:
        raise ValueError(
            "delete: Live requires the set to contain at least one scene; "
            "refusing to delete the last surviving scene. Create a new "
            "scene first (ableton_scene(action='create')), then retry "
            "the delete."
        )
    delete_fn = getattr(song, "delete_scene", None)
    if delete_fn is None:
        raise NotImplementedError(
            "Song.delete_scene not exposed in this Live version"
        )
    delete_fn(scene_index - 1)  # 0-based
    return {"deleted_scene_index": scene_index}


def rename_handler(
    context: LiveContext, *, scene_index: int, name: str
) -> dict[str, Any]:
    scene = _resolve_scene(context, scene_index)
    scene.name = name
    return {"scene_index": scene_index, "name": name}


def fire_handler(
    context: LiveContext, *, scene_index: int
) -> dict[str, Any]:
    """Fire a scene — plays every non-empty clip in that row simultaneously."""
    scene = _resolve_scene(context, scene_index)
    fire_fn = getattr(scene, "fire", None)
    if fire_fn is None:
        raise NotImplementedError(
            f"scene {scene_index} does not expose fire() — older Live build"
        )
    fire_fn()
    return {"scene_index": scene_index, "fired": True}


def set_tempo_handler(
    context: LiveContext, *, scene_index: int, bpm: float
) -> dict[str, Any]:
    """Set the scene's local tempo. Per-scene tempo overrides song tempo
    when the scene is fired.

    Live treats ``scene.tempo = -1`` as "no scene tempo" (fall through to
    song tempo). bpm <= 0 here clears the scene tempo with that semantic.
    """
    scene = _resolve_scene(context, scene_index)
    # Tighter validation than the schema enum bounds allow:
    # Live's per-scene tempo accepts EITHER -1 (the "no override" sentinel)
    # OR a tempo in [20, 999]. Anything in (-1, 0] or (0, 20) or > 999 is
    # rejected with a teaching error rather than passed to Live's silent
    # clamp / undefined behavior.
    if bpm != -1.0 and not (20.0 <= bpm <= 999.0):
        raise ValueError(
            f"bpm {bpm} out of Live's allowed range — pass -1 (clear "
            "override) OR a value in [20, 999]"
        )
    scene.tempo = float(bpm)
    return {
        "scene_index": scene_index,
        "tempo": float(bpm) if bpm > 0 else None,
    }


def set_signature_handler(
    context: LiveContext,
    *,
    scene_index: int,
    numerator: int,
    denominator: int,
) -> dict[str, Any]:
    """Set the scene's local time signature. Live requires denominator to
    be a power of two between 1 and 32."""
    scene = _resolve_scene(context, scene_index)
    if denominator not in (1, 2, 4, 8, 16, 32):
        raise ValueError(
            f"denominator {denominator} must be a power of 2 in [1, 32]"
        )
    if numerator < 1 or numerator > 99:
        raise ValueError(
            f"numerator {numerator} must be in [1, 99]"
        )
    scene.time_signature_numerator = int(numerator)
    scene.time_signature_denominator = int(denominator)
    return {
        "scene_index": scene_index,
        "time_signature": {
            "numerator": int(numerator),
            "denominator": int(denominator),
        },
    }


__all__ = [
    "list_handler",
    "info_handler",
    "create_handler",
    "delete_handler",
    "rename_handler",
    "fire_handler",
    "set_tempo_handler",
    "set_signature_handler",
]
