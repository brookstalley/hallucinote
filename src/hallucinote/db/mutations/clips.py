"""Clips: session-clip create / update / delete."""
from __future__ import annotations

import sqlite3
from typing import Any

from ._core import (
    E,
    MutatorResult,
    _emit,
    _record_touch_if_session,
    _resolve_actor_and_request,
    _touch_song,
    _uuid,
    json,
)


def create_clip(
    conn: sqlite3.Connection,
    *,
    track_id: str,
    slot: int,
    length_beats: float,
    name: str | None = None,
    section_role: str | None = None,
    generator_call: dict[str, Any] | None = None,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> str:
    gen_json = json.dumps(generator_call, separators=(",", ":")) if generator_call else None
    actor, request_id = _resolve_actor_and_request(actor, request_id)
    song_row = conn.execute(
        "SELECT t.song_id FROM tracks t WHERE t.id = ?", (track_id,)
    ).fetchone()
    existing = conn.execute(
        """SELECT id, length_beats, name, section_role, generator_call_json
           FROM clips WHERE track_id = ? AND slot = ?""",
        (track_id, slot),
    ).fetchone()
    if existing is not None:
        cid = existing["id"]
        if (existing["length_beats"], existing["name"], existing["section_role"],
                existing["generator_call_json"]) == (length_beats, name,
                                                     section_role, gen_json):
            _record_touch_if_session("clip", cid)
            return MutatorResult(cid, "unchanged")
        conn.execute(
            """UPDATE clips SET length_beats = ?, name = ?, section_role = ?,
                                generator_call_json = ?,
                                updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
               WHERE id = ?""",
            (length_beats, name, section_role, gen_json, cid),
        )
        _emit(
            conn,
            E.CLIP_UPDATED,
            {"clip_id": cid, "track_id": track_id, "changes": {
                "length_beats": length_beats, "name": name,
                "section_role": section_role,
                "generator_call": generator_call,
            }},
            song_id=song_row["song_id"] if song_row else None,
            clip_id=cid,
            actor=actor,
            request_id=request_id,
            reason=reason,
        )
        _record_touch_if_session("clip", cid)
        return MutatorResult(cid, "updated")
    cid = _uuid()
    conn.execute(
        """INSERT INTO clips
               (id, track_id, slot, length_beats, name, section_role, generator_call_json)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (cid, track_id, slot, length_beats, name, section_role, gen_json),
    )
    _emit(
        conn,
        E.CLIP_CREATED,
        {
            "clip_id": cid,
            "track_id": track_id,
            "slot": slot,
            "length_beats": length_beats,
            "name": name,
            "section_role": section_role,
            "generator_call": generator_call,
        },
        song_id=song_row["song_id"] if song_row else None,
        clip_id=cid,
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    _record_touch_if_session("clip", cid)
    return MutatorResult(cid, "created")


_CLIP_UPDATE_FIELDS = frozenset({"name", "length_beats", "section_role"})


def update_clip(
    conn: sqlite3.Connection,
    *,
    clip_id: str,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
    **changes: Any,
) -> None:
    """Partial update by id. `changes` keys must be in _CLIP_UPDATE_FIELDS.

    Deliberately excludes `track_id` (moving a clip between tracks is
    delete+create), `slot` (slot relocation is delete+create), and
    `generator_call_json` (provenance — append-only-ish). Notes are
    written via `replace_clip_notes` / `insert_notes`, not here.
    """
    bad = set(changes) - _CLIP_UPDATE_FIELDS
    if bad:
        raise ValueError(f"unsupported fields: {sorted(bad)}")
    if not changes:
        return
    row = conn.execute(
        """SELECT c.track_id, t.song_id FROM clips c
           JOIN tracks t ON t.id = c.track_id WHERE c.id = ?""",
        (clip_id,),
    ).fetchone()
    if row is None:
        return
    sets = [f"{k} = ?" for k in changes]
    vals = list(changes.values()) + [clip_id]
    conn.execute(f"UPDATE clips SET {', '.join(sets)} WHERE id = ?", vals)
    _emit(
        conn,
        E.CLIP_UPDATED,
        {"clip_id": clip_id, "track_id": row["track_id"], "changes": changes},
        song_id=row["song_id"],
        clip_id=clip_id,
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    _touch_song(conn, row["song_id"])


def delete_clip(
    conn: sqlite3.Connection,
    *,
    clip_id: str,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> None:
    row = conn.execute(
        """SELECT c.track_id, t.song_id FROM clips c
           JOIN tracks t ON t.id = c.track_id WHERE c.id = ?""",
        (clip_id,),
    ).fetchone()
    if row is None:
        return
    conn.execute("DELETE FROM clips WHERE id = ?", (clip_id,))
    _emit(
        conn,
        E.CLIP_DELETED,
        {"clip_id": clip_id, "track_id": row["track_id"]},
        song_id=row["song_id"],
        actor=actor,
        request_id=request_id,
        reason=reason,
    )


__all__ = [
    "create_clip",
    "delete_clip",
    "update_clip",
]
