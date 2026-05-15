"""All state-changing operations on the songwright DB.

Every function here:
  1. Performs its state change.
  2. Emits an `events` row describing the change in the same transaction.

Callers MUST use these instead of raw SQL. The discipline is the only thing
that makes a future event-store flip cheap rather than a rewrite.

Conventions:
- Functions take `conn` as first positional arg; everything else keyword-only.
- IDs are UUIDv4 hex strings, generated here via `_uuid()`. Mutators return the
  new id (for creates), the list of new ids (for bulk), or None (otherwise).
- Every mutator accepts `actor`, `request_id`, `reason` kwargs. Defaults
  (`'system'`, None, None) keep tests terse; agent code threads explicit
  values to make audit trails readable.
- Notes use canonical field names: pitch, start_beats, duration_beats, velocity,
  mute (0/1), tags (list[str] | None). NOT start_time / duration — convert at
  the porter / generator boundary.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any, Sequence

from songwright.db import events as E

NoteDict = dict[str, Any]


# ---------------------------------------------------------------------------
# Internal: id generation + event emission
# ---------------------------------------------------------------------------


def _uuid() -> str:
    """Canonical id format: 32-char hex (no dashes) UUIDv4."""
    return uuid.uuid4().hex


def _emit(
    conn: sqlite3.Connection,
    kind: str,
    payload: dict[str, Any],
    *,
    song_id: str | None = None,
    clip_id: str | None = None,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> str:
    """Append one events row. Returns the new event id.

    `seq` is assigned monotonically from MAX(seq)+1; single-writer assumption
    holds for this single-user authoring tool.
    """
    if actor not in E.ACTORS:
        raise ValueError(f"invalid actor {actor!r}; expected one of {sorted(E.ACTORS)}")
    event_id = _uuid()
    seq = conn.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM events").fetchone()[0]
    conn.execute(
        """INSERT INTO events
               (id, seq, kind, payload_json, song_id, clip_id,
                actor, reason, request_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            event_id,
            seq,
            kind,
            json.dumps(payload, separators=(",", ":")),
            song_id,
            clip_id,
            actor,
            reason,
            request_id,
        ),
    )
    return event_id


def _touch_clip(conn: sqlite3.Connection, clip_id: str) -> None:
    conn.execute(
        "UPDATE clips SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?",
        (clip_id,),
    )


def _touch_song(conn: sqlite3.Connection, song_id: str) -> None:
    conn.execute(
        "UPDATE songs SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?",
        (song_id,),
    )


# ---------------------------------------------------------------------------
# Provenance: requests
# ---------------------------------------------------------------------------


def create_request(
    conn: sqlite3.Connection,
    *,
    actor: str,
    intent: str,
    payload: dict[str, Any] | None = None,
    song_id: str | None = None,
    reason: str | None = None,
) -> str:
    """Create a request row. Returns the request id.

    Pass the returned id as `request_id=` to subsequent mutators so their
    events thread back to the originating intent.
    """
    if actor not in E.ACTORS:
        raise ValueError(f"invalid actor {actor!r}; expected one of {sorted(E.ACTORS)}")
    rid = _uuid()
    payload_json = json.dumps(payload, separators=(",", ":")) if payload is not None else None
    conn.execute(
        """INSERT INTO requests (id, actor, intent, payload_json, song_id)
           VALUES (?, ?, ?, ?, ?)""",
        (rid, actor, intent, payload_json, song_id),
    )
    _emit(
        conn,
        E.REQUEST_CREATED,
        {"request_id": rid, "intent": intent, "payload": payload},
        song_id=song_id,
        actor=actor,
        request_id=rid,
        reason=reason,
    )
    return rid


# ---------------------------------------------------------------------------
# Songs
# ---------------------------------------------------------------------------


def create_song(
    conn: sqlite3.Connection,
    *,
    name: str,
    key: str | None = None,
    tempo: float | None = None,
    time_signature: str | None = None,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> str:
    sid = _uuid()
    conn.execute(
        "INSERT INTO songs (id, name, key, tempo, time_signature) VALUES (?, ?, ?, ?, ?)",
        (sid, name, key, tempo, time_signature),
    )
    _emit(
        conn,
        E.SONG_CREATED,
        {"name": name, "key": key, "tempo": tempo, "time_signature": time_signature},
        song_id=sid,
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    return sid


# ---------------------------------------------------------------------------
# Tracks
# ---------------------------------------------------------------------------


def create_track(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    track_index: int,
    name: str,
    instrument_uri: str | None = None,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> str:
    tid = _uuid()
    conn.execute(
        """INSERT INTO tracks (id, song_id, track_index, name, instrument_uri)
           VALUES (?, ?, ?, ?, ?)""",
        (tid, song_id, track_index, name, instrument_uri),
    )
    _emit(
        conn,
        E.TRACK_CREATED,
        {
            "track_id": tid,
            "track_index": track_index,
            "name": name,
            "instrument_uri": instrument_uri,
        },
        song_id=song_id,
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    _touch_song(conn, song_id)
    return tid


# ---------------------------------------------------------------------------
# Clips
# ---------------------------------------------------------------------------


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
    cid = _uuid()
    conn.execute(
        """INSERT INTO clips
               (id, track_id, slot, length_beats, name, section_role, generator_call_json)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (cid, track_id, slot, length_beats, name, section_role, gen_json),
    )
    song_row = conn.execute(
        "SELECT t.song_id FROM tracks t WHERE t.id = ?", (track_id,)
    ).fetchone()
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
    return cid


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


# ---------------------------------------------------------------------------
# Notes
# ---------------------------------------------------------------------------


def _normalize_note(n: NoteDict) -> tuple:
    """Validate + extract canonical fields. Raises KeyError on missing required."""
    pitch = int(n["pitch"])
    start = float(n["start_beats"])
    dur = float(n["duration_beats"])
    vel = int(n["velocity"])
    mute = int(n.get("mute", 0))
    tags = n.get("tags")
    tags_json = json.dumps(tags, separators=(",", ":")) if tags else None
    return (pitch, start, dur, vel, mute, tags_json)


def insert_notes(
    conn: sqlite3.Connection,
    *,
    clip_id: str,
    notes: Sequence[NoteDict],
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> list[str]:
    """Append notes to a clip. Returns new note ids in insertion order."""
    if not notes:
        return []
    new_ids: list[str] = []
    for n in notes:
        pitch, start, dur, vel, mute, tags_json = _normalize_note(n)
        nid = _uuid()
        conn.execute(
            """INSERT INTO notes
                   (id, clip_id, pitch, start_beats, duration_beats, velocity, mute, tags_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (nid, clip_id, pitch, start, dur, vel, mute, tags_json),
        )
        new_ids.append(nid)
    _touch_clip(conn, clip_id)
    _emit(
        conn,
        E.NOTES_INSERTED,
        {"clip_id": clip_id, "count": len(new_ids), "note_ids": new_ids},
        clip_id=clip_id,
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    return new_ids


def replace_clip_notes(
    conn: sqlite3.Connection,
    *,
    clip_id: str,
    notes: Sequence[NoteDict],
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> list[str]:
    """Atomic: delete every note for clip, insert fresh set. Single event emitted."""
    with conn:  # transaction
        prev_count = conn.execute(
            "SELECT COUNT(*) AS c FROM notes WHERE clip_id = ?", (clip_id,)
        ).fetchone()["c"]
        conn.execute("DELETE FROM notes WHERE clip_id = ?", (clip_id,))
        new_ids: list[str] = []
        for n in notes:
            pitch, start, dur, vel, mute, tags_json = _normalize_note(n)
            nid = _uuid()
            conn.execute(
                """INSERT INTO notes
                       (id, clip_id, pitch, start_beats, duration_beats, velocity, mute, tags_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (nid, clip_id, pitch, start, dur, vel, mute, tags_json),
            )
            new_ids.append(nid)
        _touch_clip(conn, clip_id)
        _emit(
            conn,
            E.CLIP_NOTES_REPLACED,
            {
                "clip_id": clip_id,
                "prev_count": prev_count,
                "new_count": len(new_ids),
                "note_ids": new_ids,
            },
            clip_id=clip_id,
            actor=actor,
            request_id=request_id,
            reason=reason,
        )
    return new_ids


_NOTE_FIELDS = {
    "pitch",
    "start_beats",
    "duration_beats",
    "velocity",
    "mute",
    "tags",
}


def update_note(
    conn: sqlite3.Connection,
    *,
    note_id: str,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
    **changes: Any,
) -> None:
    """Partial update by id. `changes` keys must be in _NOTE_FIELDS."""
    bad = set(changes) - _NOTE_FIELDS
    if bad:
        raise ValueError(f"unsupported fields: {sorted(bad)}")
    if not changes:
        return

    sets: list[str] = []
    vals: list[Any] = []
    for k, v in changes.items():
        if k == "tags":
            sets.append("tags_json = ?")
            vals.append(json.dumps(v, separators=(",", ":")) if v else None)
        else:
            sets.append(f"{k} = ?")
            vals.append(v)
    vals.append(note_id)

    clip_row = conn.execute("SELECT clip_id FROM notes WHERE id = ?", (note_id,)).fetchone()
    if clip_row is None:
        return
    conn.execute(f"UPDATE notes SET {', '.join(sets)} WHERE id = ?", vals)
    _touch_clip(conn, clip_row["clip_id"])
    _emit(
        conn,
        E.NOTE_UPDATED,
        {"note_id": note_id, "changes": changes},
        clip_id=clip_row["clip_id"],
        actor=actor,
        request_id=request_id,
        reason=reason,
    )


def delete_notes(
    conn: sqlite3.Connection,
    *,
    note_ids: Sequence[str],
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> None:
    if not note_ids:
        return
    placeholders = ",".join("?" * len(note_ids))
    rows = conn.execute(
        f"SELECT DISTINCT clip_id FROM notes WHERE id IN ({placeholders})",
        tuple(note_ids),
    ).fetchall()
    affected_clips = [r["clip_id"] for r in rows]
    conn.execute(f"DELETE FROM notes WHERE id IN ({placeholders})", tuple(note_ids))
    for cid in affected_clips:
        _touch_clip(conn, cid)
    _emit(
        conn,
        E.NOTES_DELETED,
        {"note_ids": list(note_ids), "affected_clips": affected_clips},
        actor=actor,
        request_id=request_id,
        reason=reason,
    )


def update_notes_by_tag(
    conn: sqlite3.Connection,
    *,
    clip_id: str,
    tag: str,
    velocity_delta: int | None = None,
    velocity_set: int | None = None,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> int:
    """Bulk-update notes in clip carrying `tag`. Returns count updated.

    Matched in Python (json_each could be used; trivial scale doesn't justify it yet).
    """
    if velocity_delta is None and velocity_set is None:
        raise ValueError("specify velocity_delta or velocity_set")
    if velocity_delta is not None and velocity_set is not None:
        raise ValueError("only one of velocity_delta / velocity_set")

    rows = conn.execute(
        "SELECT id, velocity, tags_json FROM notes WHERE clip_id = ?",
        (clip_id,),
    ).fetchall()

    matched: list[tuple[str, int, int]] = []  # (id, old_vel, new_vel)
    for r in rows:
        if not r["tags_json"]:
            continue
        tags = json.loads(r["tags_json"])
        if tag not in tags:
            continue
        old_vel = r["velocity"]
        if velocity_delta is not None:
            new_vel = max(0, min(127, old_vel + velocity_delta))
        else:
            new_vel = max(0, min(127, velocity_set))  # type: ignore[arg-type]
        matched.append((r["id"], old_vel, new_vel))

    for note_id, _old, new_vel in matched:
        conn.execute("UPDATE notes SET velocity = ? WHERE id = ?", (new_vel, note_id))

    if matched:
        _touch_clip(conn, clip_id)
    _emit(
        conn,
        E.NOTES_BULK_UPDATED,
        {
            "clip_id": clip_id,
            "where_tag": tag,
            "count": len(matched),
            "velocity_delta": velocity_delta,
            "velocity_set": velocity_set,
            "note_ids": [m[0] for m in matched],
        },
        clip_id=clip_id,
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    return len(matched)


# ---------------------------------------------------------------------------
# Arrangement
# ---------------------------------------------------------------------------


def add_arrangement(
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
    aid = _uuid()
    conn.execute(
        """INSERT INTO arrangement (id, song_id, track_id, clip_id, start_bar, end_bar)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (aid, song_id, track_id, clip_id, start_bar, end_bar),
    )
    _emit(
        conn,
        E.ARRANGEMENT_ADDED,
        {
            "arrangement_id": aid,
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
    return aid


def remove_arrangement(
    conn: sqlite3.Connection,
    *,
    arrangement_id: str,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> None:
    row = conn.execute(
        "SELECT song_id, clip_id FROM arrangement WHERE id = ?", (arrangement_id,)
    ).fetchone()
    if row is None:
        return
    conn.execute("DELETE FROM arrangement WHERE id = ?", (arrangement_id,))
    _emit(
        conn,
        E.ARRANGEMENT_REMOVED,
        {"arrangement_id": arrangement_id},
        song_id=row["song_id"],
        clip_id=row["clip_id"],
        actor=actor,
        request_id=request_id,
        reason=reason,
    )


# ---------------------------------------------------------------------------
# Ableton projection: sessions + links
# ---------------------------------------------------------------------------

# db_kind values currently used by the sync layer.
ABLETON_LINK_KINDS = frozenset({"track", "clip", "arrangement", "note"})


def create_ableton_session(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    name: str | None = None,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> str:
    """Open a new Ableton session for `song_id`. Returns the session id.

    Bind this id once at sync setup; pass it through plan/apply calls so a
    song can have multiple live bindings (e.g., draft set + render set) at
    the same time without aliasing.
    """
    sid = _uuid()
    conn.execute(
        "INSERT INTO ableton_sessions (id, song_id, name) VALUES (?, ?, ?)",
        (sid, song_id, name),
    )
    _emit(
        conn,
        E.ABLETON_SESSION_CREATED,
        {"session_id": sid, "name": name},
        song_id=song_id,
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    return sid


def link_db_to_ableton(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    db_kind: str,
    db_id: str,
    ableton_index: int,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> None:
    """Upsert a (db_kind, db_id) -> ableton_index binding for one session.

    Replaces the per-domain link_track / link_clip / link_arrangement mutators.
    """
    if db_kind not in ABLETON_LINK_KINDS:
        raise ValueError(
            f"invalid db_kind {db_kind!r}; expected one of {sorted(ABLETON_LINK_KINDS)}"
        )
    existing = conn.execute(
        """SELECT id FROM ableton_links
           WHERE session_id = ? AND db_kind = ? AND db_id = ?""",
        (session_id, db_kind, db_id),
    ).fetchone()
    if existing is None:
        link_id = _uuid()
        conn.execute(
            """INSERT INTO ableton_links
                   (id, session_id, db_kind, db_id, ableton_index)
               VALUES (?, ?, ?, ?, ?)""",
            (link_id, session_id, db_kind, db_id, ableton_index),
        )
    else:
        link_id = existing["id"]
        conn.execute(
            "UPDATE ableton_links SET ableton_index = ? WHERE id = ?",
            (ableton_index, link_id),
        )
    song_row = conn.execute(
        "SELECT song_id FROM ableton_sessions WHERE id = ?", (session_id,)
    ).fetchone()
    _emit(
        conn,
        E.ABLETON_LINK_SET,
        {
            "link_id": link_id,
            "session_id": session_id,
            "db_kind": db_kind,
            "db_id": db_id,
            "ableton_index": ableton_index,
        },
        song_id=song_row["song_id"] if song_row else None,
        clip_id=db_id if db_kind == "clip" else None,
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
