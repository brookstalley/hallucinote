"""Notes: per-clip note insert / replace / update / delete + bulk-by-tag."""
from __future__ import annotations

import sqlite3
from typing import Any, Sequence

from ._core import (
    E,
    NoteDict,
    _atomic,
    _emit,
    _resolve_actor_and_request,
    _touch_clip,
    _uuid,
    json,
    transaction,
)


def _normalize_note(n: NoteDict) -> tuple:
    """Validate + extract canonical fields. Raises KeyError on missing required.

    Arc 6 / H4: rejects ``start_beats < 0`` at the mutator boundary with a
    teaching error pointing at the most common cause — a ``feel`` shift
    that pushed bar-1's downbeat below zero. ``apply_feel`` math itself
    is correct (within-bar positions can shift below 0.0 conceptually);
    the wire layer can't represent it (Live's MIDI clip has no
    negative-beat region). Catching it here puts the diagnostic next to
    the call site that ships invalid data, not the generator that's
    doing math correctly.
    """
    pitch = int(n["pitch"])
    start = float(n["start_beats"])
    if start < 0:
        raise ValueError(
            f"_normalize_note: start_beats={start!r} is negative — Live's "
            "MIDI clip has no negative-beat region. Common cause: a "
            "`feel` dict shifted bar-1's downbeat below zero "
            "(`feel={0.0: -0.02}` on bar 1's start). Either drop the "
            "bar-1 shift, or author a pickup/anacrusis pattern with a "
            "positive offset. The `apply_feel` math is correct in "
            "isolation; this guard catches notes that can't survive the "
            "wire."
        )
    dur = float(n["duration_beats"])
    vel = int(n["velocity"])
    mute = int(n.get("mute", 0))
    tags = n.get("tags")
    tags_json = json.dumps(tags, separators=(",", ":")) if tags else None
    return (pitch, start, dur, vel, mute, tags_json)


def _require_midi_clip(conn: sqlite3.Connection, clip_id: str, op: str) -> None:
    """Refuse note writes against non-MIDI clips (CLP-AUD1 kind-guard).

    Notes live on MIDI clips only; an audio clip's content is its
    ``audio_file``. Unknown clip ids pass through unchanged — the
    ``notes.clip_id`` FK owns that failure, same as before this guard.
    """
    row = conn.execute(
        "SELECT kind FROM clips WHERE id = ?", (clip_id,)
    ).fetchone()
    if row is not None and row["kind"] != "midi":
        raise ValueError(
            f"{op}: clip {clip_id} has kind={row['kind']!r} — notes live "
            "on MIDI clips only; an audio clip's content is its "
            "audio_file. Conform audio via update_clip's audio fields "
            "(gain / pitch / warp / markers) instead."
        )


@_atomic
def insert_notes(
    conn: sqlite3.Connection,
    *,
    clip_id: str,
    notes: Sequence[NoteDict],
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> list[str]:
    """Append notes to a clip. Returns new note ids in insertion order.

    Refuses kind='audio' targets (notes live on MIDI clips only)."""
    if not notes:
        return []
    _require_midi_clip(conn, clip_id, "insert_notes")
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


@_atomic
def replace_clip_notes(
    conn: sqlite3.Connection,
    *,
    clip_id: str,
    notes: Sequence[NoteDict],
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> list[str]:
    """Atomic: delete every note for clip, insert fresh set. Single event emitted.

    W12-A: idempotent — when the existing notes (by content, ignoring ids)
    already match the incoming set, the function is a no-op and emits no
    event. Returns the existing note ids in that case (preserves the
    list[str] return contract — same length, same ordering by start_beats).

    Refuses kind='audio' targets (notes live on MIDI clips only).
    """
    _require_midi_clip(conn, clip_id, "replace_clip_notes")
    actor, request_id = _resolve_actor_and_request(actor, request_id)
    # Idempotency check: compare normalized incoming set vs existing notes.
    incoming = [_normalize_note(n) for n in notes]
    existing_rows = conn.execute(
        """SELECT id, pitch, start_beats, duration_beats, velocity, mute, tags_json
           FROM notes WHERE clip_id = ?
           ORDER BY start_beats, pitch""",
        (clip_id,),
    ).fetchall()
    existing_sig = [
        (r["pitch"], r["start_beats"], r["duration_beats"], r["velocity"],
         r["mute"], r["tags_json"]) for r in existing_rows
    ]
    incoming_sig = sorted(incoming, key=lambda t: (t[1], t[0]))
    existing_sig_sorted = sorted(existing_sig, key=lambda t: (t[1], t[0]))
    if existing_sig_sorted == incoming_sig:
        return [r["id"] for r in conn.execute(
            "SELECT id FROM notes WHERE clip_id = ? ORDER BY start_beats, pitch",
            (clip_id,),
        ).fetchall()]
    with transaction(conn):
        prev_count = len(existing_rows)
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


@_atomic
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


@_atomic
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
        f"SELECT id, clip_id FROM notes WHERE id IN ({placeholders})",
        tuple(note_ids),
    ).fetchall()
    by_clip: dict[str, list[str]] = {}
    for r in rows:
        by_clip.setdefault(r["clip_id"], []).append(r["id"])
    affected_clips = list(by_clip.keys())
    conn.execute(f"DELETE FROM notes WHERE id IN ({placeholders})", tuple(note_ids))
    for cid in affected_clips:
        _touch_clip(conn, cid)
    # Emit one NOTES_DELETED event per affected clip so events.clip_id is set
    # — symmetric with NOTE_UPDATED + insert_notes, and the events.clip_id
    # column drives `_latest_actor_for(row_kind='clip')`'s tombstone-actor
    # lookup. Single-event-with-affected_clips payload missed that lookup,
    # leaving a build-owned clip whose only LLM-touch was `delete_notes`
    # falsely tombstone-eligible.
    for cid, cid_note_ids in by_clip.items():
        _emit(
            conn,
            E.NOTES_DELETED,
            {"note_ids": cid_note_ids, "affected_clips": [cid]},
            clip_id=cid,
            actor=actor,
            request_id=request_id,
            reason=reason,
        )


@_atomic
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


__all__ = [
    "_normalize_note",
    "delete_notes",
    "insert_notes",
    "replace_clip_notes",
    "update_note",
    "update_notes_by_tag",
]
