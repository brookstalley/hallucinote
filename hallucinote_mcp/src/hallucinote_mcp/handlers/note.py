"""Handlers for ``ableton_note`` actions.

V1 close-out Chunk D ships the READ side of gap #4:
``ableton_note(action='list')`` is now functional, returning notes with
Live's stable per-note IDs via ``clip.get_notes_extended()``. The
add / update / delete handlers remain stubs — Live's surgical
note-write surface (``apply_note_modifications`` / ``add_new_notes`` /
``remove_notes_by_id``) hasn't been wired through yet. For now the
hallucinote sync layer reads notes via ``list`` for diff attribution
and writes whole clips via ``ableton_clip(action='replace_notes')``.

The read+whole-clip-write strategy preserves all V1 capability
(humanization, "raise verse ghosts by 5", surgical fixes — the math
happens DB-side, then the clip is rewritten in one MCP call). The
residual live-playback-continuity case (Live retriggers a clip on
``set_notes`` during playback) is acceptable because
``scope.never`` excludes live-performance use.
"""
from __future__ import annotations

from typing import Any

from ..dispatcher import LiveContext
from .clip import _resolve_clip


_GAP_4_WRITE_HINT = (
    "ableton_note write operations (add / update / delete) are still "
    "blocked by gap #4 — Live's surgical note-write surface hasn't been "
    "wired through. For now, write notes via ableton_clip("
    "action='replace_notes', notes=[...]) — whole-clip writes preserve "
    "all V1 capability (the math is done DB-side; one MCP call rewrites "
    "the clip). Use ableton_note(action='list') to read notes with stable "
    "IDs for diff attribution before deciding what to write."
)


def list_handler(
    context: LiveContext,
    *,
    track_index: int,
    location: str,
    clip_index: int,
) -> dict[str, Any]:
    """Read every note in a clip with Live's stable per-note IDs.

    Calls ``clip.get_notes_extended(0, 128, 0.0, clip.length)`` — the
    full pitch range and full clip duration. Live note IDs are stable
    within a session but expire on any note-write operation, so the
    hallucinote sync layer uses them only for diff attribution within
    a single pull pass and never stores them in `ableton_links`.
    """
    clip = _resolve_clip(
        context, track_index=track_index, location=location, clip_index=clip_index,
    )
    raw = clip.get_notes_extended(0, 128, 0.0, float(clip.length))
    notes: list[dict[str, Any]] = []
    for n in raw:
        notes.append({
            "note_id": int(n.note_id),
            "pitch": int(n.pitch),
            "start_time": float(n.start_time),
            "duration": float(n.duration),
            "velocity": int(n.velocity),
            "mute": bool(n.mute),
        })
    return {
        "track_index": track_index,
        "location": location,
        "clip_index": clip_index,
        "notes": notes,
    }


def add_handler(
    context: LiveContext,
    *,
    track_index: int,
    location: str,
    clip_index: int,
    notes: list[dict[str, Any]],
) -> dict[str, Any]:
    raise NotImplementedError(_GAP_4_WRITE_HINT)


def update_handler(
    context: LiveContext,
    *,
    track_index: int,
    location: str,
    clip_index: int,
    note_ids: list[int],
    changes: dict[str, Any],
) -> dict[str, Any]:
    raise NotImplementedError(_GAP_4_WRITE_HINT)


def delete_handler(
    context: LiveContext,
    *,
    track_index: int,
    location: str,
    clip_index: int,
    note_ids: list[int],
) -> dict[str, Any]:
    raise NotImplementedError(_GAP_4_WRITE_HINT)


__all__ = [
    "list_handler",
    "add_handler",
    "update_handler",
    "delete_handler",
]
