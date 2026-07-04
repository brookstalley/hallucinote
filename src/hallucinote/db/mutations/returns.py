"""Mix: return tracks + sends."""
from __future__ import annotations

import sqlite3
from typing import Any

from hallucinote.return_naming import strip_return_slot_prefix

from ._core import (
    E,
    MutatorResult,
    _atomic,
    _emit,
    _record_touch_if_session,
    _resolve_actor_and_request,
    _touch_song,
    _uuid,
)


@_atomic
def create_return(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    name: str,
    position: int,
    volume: float | None = None,
    pan: float | None = None,
    color: int | None = None,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> str:
    """Create a return track. `position` is the return's index in Live (1-based,
    matching captured_session.json). Volume/pan optional; default state is
    whatever Live applies to a freshly-created return.

    Arc 7 / P7: `name` is normalized through `strip_return_slot_prefix`
    so a caller (build.py, snapshot replay) passing Live's `<letter>-`
    prefixed form can't poison the DB. Returns store SUFFIX-only names
    (W4-C convention). Idempotent: already-stripped names pass through.
    """
    name = strip_return_slot_prefix(name)
    actor, request_id = _resolve_actor_and_request(actor, request_id)
    existing = conn.execute(
        """SELECT id, name, volume, pan, color FROM returns
           WHERE song_id = ? AND position = ?""",
        (song_id, position),
    ).fetchone()
    if existing is not None:
        rid = existing["id"]
        if (existing["name"], existing["volume"], existing["pan"],
                existing["color"]) == (name, volume, pan, color):
            _record_touch_if_session("return", rid)
            return MutatorResult(rid, "unchanged")
        conn.execute(
            """UPDATE returns SET name = ?, volume = ?, pan = ?, color = ?
               WHERE id = ?""",
            (name, volume, pan, color, rid),
        )
        _emit(
            conn, E.RETURN_UPDATED,
            {"return_id": rid, "changes": {"name": name, "volume": volume,
                                            "pan": pan, "color": color}},
            song_id=song_id, actor=actor, request_id=request_id, reason=reason,
        )
        _touch_song(conn, song_id)
        _record_touch_if_session("return", rid)
        return MutatorResult(rid, "updated")
    rid = _uuid()
    conn.execute(
        """INSERT INTO returns
               (id, song_id, name, position, volume, pan, color)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (rid, song_id, name, position, volume, pan, color),
    )
    _emit(
        conn,
        E.RETURN_CREATED,
        {
            "return_id": rid,
            "name": name,
            "position": position,
            "volume": volume,
            "pan": pan,
            "color": color,
        },
        song_id=song_id,
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    _touch_song(conn, song_id)
    _record_touch_if_session("return", rid)
    return MutatorResult(rid, "created")


_RETURN_FIELDS = {"name", "position", "volume", "pan", "mute", "solo", "color"}


@_atomic
def update_return(
    conn: sqlite3.Connection,
    *,
    return_id: str,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
    **changes: Any,
) -> None:
    """Partial update by id. `changes` keys must be in _RETURN_FIELDS.

    Arc 7 / P7: when `name` is updated, normalize through
    `strip_return_slot_prefix` so callers can't sneak Live's
    `<letter>-` slot prefix into the DB (mirrors `create_return`).
    """
    bad = set(changes) - _RETURN_FIELDS
    if bad:
        raise ValueError(f"unsupported fields: {sorted(bad)}")
    if not changes:
        return
    if "name" in changes:
        changes["name"] = strip_return_slot_prefix(changes["name"])
    row = conn.execute(
        "SELECT song_id FROM returns WHERE id = ?", (return_id,)
    ).fetchone()
    if row is None:
        return
    sets = [f"{k} = ?" for k in changes]
    vals = list(changes.values()) + [return_id]
    conn.execute(f"UPDATE returns SET {', '.join(sets)} WHERE id = ?", vals)
    _emit(
        conn,
        E.RETURN_UPDATED,
        {"return_id": return_id, "changes": changes},
        song_id=row["song_id"],
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    _touch_song(conn, row["song_id"])


@_atomic
def delete_return(
    conn: sqlite3.Connection,
    *,
    return_id: str,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> None:
    row = conn.execute(
        "SELECT song_id FROM returns WHERE id = ?", (return_id,)
    ).fetchone()
    if row is None:
        return
    conn.execute("DELETE FROM returns WHERE id = ?", (return_id,))
    _emit(
        conn,
        E.RETURN_DELETED,
        {"return_id": return_id},
        song_id=row["song_id"],
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    _touch_song(conn, row["song_id"])


@_atomic
def set_send_level(
    conn: sqlite3.Connection,
    *,
    from_track_id: str,
    to_return_id: str,
    level: float,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> None:
    """Upsert send level for (from_track, to_return). `level` is normalized
    0.0–1.0 to match track volume conventions."""
    if not (0.0 <= level <= 1.0):
        raise ValueError(f"level {level} out of range [0.0, 1.0]")
    actor, request_id = _resolve_actor_and_request(actor, request_id)
    # Resolve song for the emitted event — track and return must share a song.
    track_row = conn.execute(
        "SELECT song_id FROM tracks WHERE id = ?", (from_track_id,)
    ).fetchone()
    ret_row = conn.execute(
        "SELECT song_id FROM returns WHERE id = ?", (to_return_id,)
    ).fetchone()
    if track_row is None or ret_row is None:
        raise ValueError(
            f"send endpoints missing: track={from_track_id!r}, return={to_return_id!r}"
        )
    if track_row["song_id"] != ret_row["song_id"]:
        raise ValueError(
            "cross-song send: track and return belong to different songs"
        )
    # W12-A: idempotent — skip when the existing level matches.
    existing = conn.execute(
        "SELECT level FROM sends WHERE from_track_id = ? AND to_return_id = ?",
        (from_track_id, to_return_id),
    ).fetchone()
    if existing is not None and existing["level"] == level:
        return
    conn.execute(
        """INSERT INTO sends (from_track_id, to_return_id, level)
           VALUES (?, ?, ?)
           ON CONFLICT(from_track_id, to_return_id)
           DO UPDATE SET level = excluded.level""",
        (from_track_id, to_return_id, level),
    )
    _emit(
        conn,
        E.SEND_SET,
        {
            "from_track_id": from_track_id,
            "to_return_id": to_return_id,
            "level": level,
        },
        song_id=track_row["song_id"],
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    _touch_song(conn, track_row["song_id"])


@_atomic
def set_send_intended_rt60(
    conn: sqlite3.Connection,
    *,
    from_track_id: str,
    to_return_id: str,
    intended_rt60_s: float | None,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> None:
    """Set composer-declared RT60 intent on an existing send.

    ``intended_rt60_s=None`` clears the intent (the send remains, with NULL
    intent). Positive when set — the schema CHECK enforces this, but raising
    early gives the caller a clear message rather than a SQLite IntegrityError.

    Requires the send row to exist — there's no useful "intent without a
    level" state (a 0-level send isn't audible anyway, and the audio-analysis
    handler walks the sends table to find candidates). Pair with
    ``set_send_level`` to land both atomically.

    Idempotent: skips emission when the stored value already matches.
    """
    if intended_rt60_s is not None and not (intended_rt60_s > 0.0):
        raise ValueError(
            f"intended_rt60_s {intended_rt60_s} must be > 0.0 (NULL is the "
            f"'no intent declared' state)"
        )
    actor, request_id = _resolve_actor_and_request(actor, request_id)
    row = conn.execute(
        """SELECT t.song_id, s.intended_rt60_s
           FROM sends s JOIN tracks t ON t.id = s.from_track_id
           WHERE s.from_track_id = ? AND s.to_return_id = ?""",
        (from_track_id, to_return_id),
    ).fetchone()
    if row is None:
        raise ValueError(
            f"no send exists for (from_track={from_track_id!r}, "
            f"to_return={to_return_id!r}); call set_send_level first to "
            f"establish the send before declaring RT60 intent"
        )
    if row["intended_rt60_s"] == intended_rt60_s:
        return
    conn.execute(
        """UPDATE sends SET intended_rt60_s = ?
           WHERE from_track_id = ? AND to_return_id = ?""",
        (intended_rt60_s, from_track_id, to_return_id),
    )
    _emit(
        conn,
        E.SEND_INTENT_SET,
        {
            "from_track_id": from_track_id,
            "to_return_id": to_return_id,
            "intended_rt60_s": intended_rt60_s,
        },
        song_id=row["song_id"],
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    _touch_song(conn, row["song_id"])


@_atomic
def remove_send(
    conn: sqlite3.Connection,
    *,
    from_track_id: str,
    to_return_id: str,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> None:
    """Remove a send.

    Decision (audio-analysis follow-on Critic note): an RT60 *intent*
    (``sends.intended_rt60_s``) lives ON the send row, so removing the send
    removes its intent atomically — there is no orphan to clean up and no
    "intent without a send" state to preserve (``set_send_intended_rt60``
    requires the send to exist for exactly this reason). The intent is
    correctly discarded with the send. To keep that discard *auditable*
    rather than silent, a non-null intent is recorded in the SEND_REMOVED
    event payload — the audit log shows that an RT60 intent was dropped, not
    just that a send was.
    """
    row = conn.execute(
        """SELECT t.song_id, s.intended_rt60_s
           FROM sends s JOIN tracks t ON t.id = s.from_track_id
           WHERE s.from_track_id = ? AND s.to_return_id = ?""",
        (from_track_id, to_return_id),
    ).fetchone()
    if row is None:
        # Either the track doesn't exist or there's no such send — nothing to
        # remove. (A no-op delete must not emit an event.)
        return
    conn.execute(
        "DELETE FROM sends WHERE from_track_id = ? AND to_return_id = ?",
        (from_track_id, to_return_id),
    )
    payload: dict[str, object] = {
        "from_track_id": from_track_id,
        "to_return_id": to_return_id,
    }
    if row["intended_rt60_s"] is not None:
        payload["discarded_intended_rt60_s"] = row["intended_rt60_s"]
    _emit(
        conn,
        E.SEND_REMOVED,
        payload,
        song_id=row["song_id"],
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    _touch_song(conn, row["song_id"])


__all__ = [
    "create_return",
    "delete_return",
    "remove_send",
    "set_send_intended_rt60",
    "set_send_level",
    "update_return",
]
