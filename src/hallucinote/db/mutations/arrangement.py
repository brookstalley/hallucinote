"""Arrangement layout: arrangement clips + cue points (markers)."""
from __future__ import annotations

import sqlite3

from ._core import (
    E,
    MutatorResult,
    _emit,
    _record_touch_if_session,
    _resolve_actor_and_request,
    _touch_song,
    _uuid,
)


# ---------------------------------------------------------------------------
# Arrangement clips
# ---------------------------------------------------------------------------


def add_arrangement_clip(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    track_id: str,
    clip_id: str,
    start_bar: float,
    end_bar: float,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> str:
    actor, request_id = _resolve_actor_and_request(actor, request_id)
    existing = conn.execute(
        """SELECT id, end_bar FROM arrangement_clips
           WHERE song_id = ? AND track_id = ? AND clip_id = ? AND start_bar = ?""",
        (song_id, track_id, clip_id, start_bar),
    ).fetchone()
    if existing is not None:
        aid = existing["id"]
        if existing["end_bar"] == end_bar:
            _record_touch_if_session("arrangement_clip", aid)
            return MutatorResult(aid, "unchanged")
        conn.execute(
            "UPDATE arrangement_clips SET end_bar = ? WHERE id = ?",
            (end_bar, aid),
        )
        _emit(
            conn,
            E.ARRANGEMENT_CLIP_ADDED,
            {"arrangement_clip_id": aid, "track_id": track_id,
             "clip_id": clip_id, "start_bar": start_bar, "end_bar": end_bar,
             "kind": "updated"},
            song_id=song_id, clip_id=clip_id,
            actor=actor, request_id=request_id, reason=reason,
        )
        _record_touch_if_session("arrangement_clip", aid)
        return MutatorResult(aid, "updated")
    aid = _uuid()
    conn.execute(
        """INSERT INTO arrangement_clips (id, song_id, track_id, clip_id, start_bar, end_bar)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (aid, song_id, track_id, clip_id, start_bar, end_bar),
    )
    _emit(
        conn,
        E.ARRANGEMENT_CLIP_ADDED,
        {
            "arrangement_clip_id": aid,
            "track_id": track_id,
            "clip_id": clip_id,
            "start_bar": start_bar,
            "end_bar": end_bar,
        },
        song_id=song_id,
        clip_id=clip_id,
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    _record_touch_if_session("arrangement_clip", aid)
    return MutatorResult(aid, "created")


def remove_arrangement_clip(
    conn: sqlite3.Connection,
    *,
    arrangement_clip_id: str,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> None:
    row = conn.execute(
        "SELECT song_id, clip_id FROM arrangement_clips WHERE id = ?", (arrangement_clip_id,)
    ).fetchone()
    if row is None:
        return
    conn.execute("DELETE FROM arrangement_clips WHERE id = ?", (arrangement_clip_id,))
    _emit(
        conn,
        E.ARRANGEMENT_CLIP_REMOVED,
        {"arrangement_clip_id": arrangement_clip_id},
        song_id=row["song_id"],
        clip_id=row["clip_id"],
        actor=actor,
        request_id=request_id,
        reason=reason,
    )


# ---------------------------------------------------------------------------
# Score: cue points (arrangement markers)
# ---------------------------------------------------------------------------


def add_cue_point(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    position_bar: float,
    name: str | None = None,
    color: int | None = None,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> str:
    """Add an arrangement marker at `position_bar`. Maps to Live's cue points.

    Idempotent by `(song_id, position_bar)`: a second call at the same
    position with the same name/color is a no-op; with different name/color
    it updates the existing cue. Use `remove_cue_point` + add to move a cue.
    """
    actor, request_id = _resolve_actor_and_request(actor, request_id)
    existing = conn.execute(
        """SELECT id, name, color FROM cue_points
           WHERE song_id = ? AND position_bar = ?""",
        (song_id, position_bar),
    ).fetchone()
    if existing is not None:
        pid = existing["id"]
        if (existing["name"], existing["color"]) == (name, color):
            _record_touch_if_session("cue_point", pid)
            return MutatorResult(pid, "unchanged")
        conn.execute(
            "UPDATE cue_points SET name = ?, color = ? WHERE id = ?",
            (name, color, pid),
        )
        _emit(
            conn, E.CUE_POINT_ADDED,
            {"cue_id": pid, "position_bar": position_bar, "name": name,
             "color": color, "kind": "updated"},
            song_id=song_id, actor=actor, request_id=request_id, reason=reason,
        )
        _touch_song(conn, song_id)
        _record_touch_if_session("cue_point", pid)
        return MutatorResult(pid, "updated")
    pid = _uuid()
    conn.execute(
        """INSERT INTO cue_points (id, song_id, position_bar, name, color)
           VALUES (?, ?, ?, ?, ?)""",
        (pid, song_id, position_bar, name, color),
    )
    _emit(
        conn,
        E.CUE_POINT_ADDED,
        {
            "cue_id": pid,
            "position_bar": position_bar,
            "name": name,
            "color": color,
        },
        song_id=song_id,
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    _touch_song(conn, song_id)
    _record_touch_if_session("cue_point", pid)
    return MutatorResult(pid, "created")


def remove_cue_point(
    conn: sqlite3.Connection,
    *,
    cue_id: str,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> None:
    row = conn.execute(
        "SELECT song_id FROM cue_points WHERE id = ?", (cue_id,)
    ).fetchone()
    if row is None:
        return
    conn.execute("DELETE FROM cue_points WHERE id = ?", (cue_id,))
    _emit(
        conn,
        E.CUE_POINT_REMOVED,
        {"cue_id": cue_id},
        song_id=row["song_id"],
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    _touch_song(conn, row["song_id"])


__all__ = [
    "add_arrangement_clip",
    "add_cue_point",
    "remove_arrangement_clip",
    "remove_cue_point",
]
