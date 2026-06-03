"""Scene-provisioning planner (SYN-4P2D).

The ``scenes`` phase runs before ``clips`` and emits one idempotent
``ableton_scene(action='ensure_count')`` call so the Live set has at least as
many scenes as the song's session clips need. Session clip slots ARE scene rows:
a track has exactly as many clip slots as the set has scenes, so creating a clip
in slot N requires the set to have at least N scenes. Without this phase, the
first push of a song with more sections than the default 8-scene set hits a raw
per-clip ``IndexError`` at clip-create — one per affected track.

Deficit math (``needed = N - current``) runs Live-side in the handler — the only
side that can see the current scene count. This planner only computes the
*required* count (``max slot`` over the song's session clips); the handler reads
``len(song.scenes)`` and appends the difference.
"""
from __future__ import annotations

import sqlite3

from hallucinote.db import queries as Q

from ._core import PushPlan, ToolCall


def plan_push_scenes(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    session_id: str,
) -> PushPlan:
    """Plan provisioning of enough Live scenes for the song's session clips.

    Emits a single ``ableton_scene(action='ensure_count', count=max_slot)``
    call where ``max_slot`` is the highest 1-based clip slot over every session
    clip in the song. Deriving from the clip rows (not re-deriving from sections)
    keeps ``scenes`` and ``clips`` reading the same source — they cannot disagree
    about how many scenes the song needs (the clips planner places each clip at
    ``clip["slot"]``).

    Empty path (``max_slot <= 0``): no session clips means nothing to provision.
    Emits NO ``ToolCall`` but DOES ``plan.warn(...)`` — matching the documented
    per-phase warn-not-bare-empty convention (see ``plan_push_song`` and the
    sibling ``plan_push_clips``) so the skill's progress reporting can
    distinguish "ran cleanly with nothing to do" from "phase skipped". A warn
    adds no call, so the executor still reports the phase SKIPPED.

    Key ``scene:ensure`` (ack-only kind ``"scene"``): scenes are a Live-set
    structural property, not a Hallucinote entity, so there's no per-scene DB
    row to link — the kind goes in ``_ACK_ONLY_KINDS``, not ``_LINK_KINDS``.
    """
    plan = PushPlan()
    rows = Q.get_clips_for_song(conn, song_id)
    max_slot = max((r["slot"] for r in rows), default=0)
    if max_slot <= 0:
        plan.warn("no session clips; no scenes to provision")
        return plan
    plan.add(ToolCall(
        tool="ableton_scene",
        args={"action": "ensure_count", "count": max_slot},
        key="scene:ensure",
        purpose=f"ensure >= {max_slot} scenes exist before creating section clips",
    ))
    return plan
