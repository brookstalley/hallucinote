"""Stub handlers for ``ableton_note`` actions.

Every operation here is blocked by MCP gap #4 (Hallucinote-side: no stable
note IDs surfaced by the underlying ``clip.get_notes_extended()`` API). The
schema is registered for surface stability — agents reading
``ableton_note(action='help')`` see the planned action menu and can reason
about what's coming. The handlers raise ``NotImplementedError`` with a clear
gap-#4 message that the dispatcher's exception path wraps in a structured
teaching error.

When gap #4 is resolved (the underlying MCP capability lands), each handler
gets its real implementation; the action signatures stay stable.
"""
from __future__ import annotations

from typing import Any

from ..dispatcher import LiveContext


_GAP_4_HINT = (
    "ableton_note operations are blocked by MCP gap #4 — Live's note API "
    "does not yet expose stable per-note IDs (clip.get_notes_extended() "
    "returns notes without IDs in the current Remote Script). The schema is "
    "registered for surface stability; implementation lands once the "
    "underlying capability is in place. To replace ALL notes on a clip, use "
    "ableton_clip(action='replace_notes') — that's the working path today."
)


def list_handler(
    context: LiveContext,
    *,
    track_index: int,
    location: str,
    clip_index: int,
) -> dict[str, Any]:
    raise NotImplementedError(_GAP_4_HINT)


def add_handler(
    context: LiveContext,
    *,
    track_index: int,
    location: str,
    clip_index: int,
    notes: list[dict[str, Any]],
) -> dict[str, Any]:
    raise NotImplementedError(_GAP_4_HINT)


def update_handler(
    context: LiveContext,
    *,
    track_index: int,
    location: str,
    clip_index: int,
    note_ids: list[int],
    changes: dict[str, Any],
) -> dict[str, Any]:
    raise NotImplementedError(_GAP_4_HINT)


def delete_handler(
    context: LiveContext,
    *,
    track_index: int,
    location: str,
    clip_index: int,
    note_ids: list[int],
) -> dict[str, Any]:
    raise NotImplementedError(_GAP_4_HINT)


__all__ = [
    "list_handler",
    "add_handler",
    "update_handler",
    "delete_handler",
]
