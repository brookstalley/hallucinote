"""All state-changing operations on the hallucinote DB.

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
import re
import sqlite3
import uuid
from typing import Any, Sequence

from hallucinote.db import events as E
from hallucinote.db.connection import transaction

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


TIMING_MODES = frozenset({"native", "grid"})


_SLUG_RE = re.compile(r"[a-z0-9_-]+")


def create_song(
    conn: sqlite3.Connection,
    *,
    name: str,
    title: str | None = None,
    key: str | None = None,
    timing_mode: str = "native",
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> str:
    """Create a song. Tempo and meter live in `tempo_map` / `time_signature_map`;
    add at least one point in each before pushing.

    `name` is the song *slug* — filesystem-safe identifier matching the
    song's directory and DB filename per the project convention
    (`songs/<name>/<name>.db`). Lowercase letters, digits, hyphens, and
    underscores only. `title` is the optional human-facing display name —
    free-form text with spaces, capitals, punctuation.

    `timing_mode='native'` (default) renders bar positions through the maps,
    matching Live's tempo/meter. `'grid'` opts out — generators handle
    resolved positions internally for polytempic experiments.
    """
    if not _SLUG_RE.fullmatch(name):
        raise ValueError(
            f"song name {name!r} must match [a-z0-9_-]+ — slugs only "
            "(no spaces, no uppercase, no special chars). Use `title` for "
            "the human-facing name."
        )
    if timing_mode not in TIMING_MODES:
        raise ValueError(
            f"invalid timing_mode {timing_mode!r}; expected one of {sorted(TIMING_MODES)}"
        )
    sid = _uuid()
    conn.execute(
        "INSERT INTO songs (id, name, title, key, timing_mode) VALUES (?, ?, ?, ?, ?)",
        (sid, name, title, key, timing_mode),
    )
    _emit(
        conn,
        E.SONG_CREATED,
        {"name": name, "title": title, "key": key, "timing_mode": timing_mode},
        song_id=sid,
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    return sid


def set_song_timing_mode(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    timing_mode: str,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> None:
    """Switch a song between 'native' (use tempo/time-signature maps) and 'grid'
    (generators resolve positions themselves). Maps are preserved either way."""
    if timing_mode not in TIMING_MODES:
        raise ValueError(
            f"invalid timing_mode {timing_mode!r}; expected one of {sorted(TIMING_MODES)}"
        )
    conn.execute(
        "UPDATE songs SET timing_mode = ? WHERE id = ?",
        (timing_mode, song_id),
    )
    _touch_song(conn, song_id)
    _emit(
        conn,
        E.SONG_TIMING_MODE_SET,
        {"timing_mode": timing_mode},
        song_id=song_id,
        actor=actor,
        request_id=request_id,
        reason=reason,
    )


# ---------------------------------------------------------------------------
# Tracks
# ---------------------------------------------------------------------------


TRACK_KINDS = frozenset({"midi", "audio", "return", "master", "group"})


def create_track(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    track_index: int,
    name: str,
    instrument_uri: str | None = None,
    kind: str = "midi",
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> str:
    """Create a track. `kind` selects 'midi' (default), 'audio', 'master', or
    'group'; 'return' is reserved (returns live in the `returns` table). Mixer
    state lives on the row but is set separately via `set_track_mixer`."""
    if kind not in TRACK_KINDS:
        raise ValueError(f"invalid kind {kind!r}; expected one of {sorted(TRACK_KINDS)}")
    tid = _uuid()
    conn.execute(
        """INSERT INTO tracks
               (id, song_id, track_index, name, instrument_uri, kind)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (tid, song_id, track_index, name, instrument_uri, kind),
    )
    _emit(
        conn,
        E.TRACK_CREATED,
        {
            "track_id": tid,
            "track_index": track_index,
            "name": name,
            "instrument_uri": instrument_uri,
            "kind": kind,
        },
        song_id=song_id,
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    _touch_song(conn, song_id)
    return tid


_MIXER_FIELDS = {"volume", "pan", "mute", "solo", "arm", "color"}


def set_track_mixer(
    conn: sqlite3.Connection,
    *,
    track_id: str,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
    **changes: Any,
) -> None:
    """Partial mixer update. `changes` keys must be in _MIXER_FIELDS.

    Volume is normalized 0.0–1.0 (Live convention); pan is -1.0..+1.0;
    mute/solo/arm are 0/1; color is RGB int. Schema CHECKs enforce ranges.
    """
    bad = set(changes) - _MIXER_FIELDS
    if bad:
        raise ValueError(f"unsupported fields: {sorted(bad)}")
    if not changes:
        return
    row = conn.execute(
        "SELECT song_id FROM tracks WHERE id = ?", (track_id,)
    ).fetchone()
    if row is None:
        return
    sets = [f"{k} = ?" for k in changes]
    vals = list(changes.values()) + [track_id]
    conn.execute(f"UPDATE tracks SET {', '.join(sets)} WHERE id = ?", vals)
    _emit(
        conn,
        E.TRACK_MIXER_SET,
        {"track_id": track_id, "changes": changes},
        song_id=row["song_id"],
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    _touch_song(conn, row["song_id"])


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
    with transaction(conn):
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
# Score: sections
# ---------------------------------------------------------------------------


def create_section(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    name: str,
    start_bar: float,
    end_bar: float,
    color: int | None = None,
    notes_md: str | None = None,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> str:
    """Mark a named span of bars (verse, chorus, bridge, ...). DB-only metadata
    unless Live exposes section markers; surfaces in event log either way."""
    if end_bar <= start_bar:
        raise ValueError(f"end_bar ({end_bar}) must exceed start_bar ({start_bar})")
    sid = _uuid()
    conn.execute(
        """INSERT INTO sections
               (id, song_id, name, start_bar, end_bar, color, notes_md)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (sid, song_id, name, start_bar, end_bar, color, notes_md),
    )
    _emit(
        conn,
        E.SECTION_CREATED,
        {
            "section_id": sid,
            "name": name,
            "start_bar": start_bar,
            "end_bar": end_bar,
            "color": color,
            "notes_md": notes_md,
        },
        song_id=song_id,
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    _touch_song(conn, song_id)
    return sid


_SECTION_FIELDS = {"name", "start_bar", "end_bar", "color", "notes_md"}


def update_section(
    conn: sqlite3.Connection,
    *,
    section_id: str,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
    **changes: Any,
) -> None:
    """Partial update by id. `changes` keys must be in _SECTION_FIELDS."""
    bad = set(changes) - _SECTION_FIELDS
    if bad:
        raise ValueError(f"unsupported fields: {sorted(bad)}")
    if not changes:
        return
    row = conn.execute(
        "SELECT song_id, start_bar, end_bar FROM sections WHERE id = ?", (section_id,)
    ).fetchone()
    if row is None:
        return
    # Span guard: validate the resulting span, not just the new value, so updating
    # start_bar past the existing end_bar (or vice versa) fails cleanly.
    new_start = float(changes.get("start_bar", row["start_bar"]))
    new_end = float(changes.get("end_bar", row["end_bar"]))
    if new_end <= new_start:
        raise ValueError(f"end_bar ({new_end}) must exceed start_bar ({new_start})")

    sets = [f"{k} = ?" for k in changes]
    vals = list(changes.values()) + [section_id]
    conn.execute(f"UPDATE sections SET {', '.join(sets)} WHERE id = ?", vals)
    _emit(
        conn,
        E.SECTION_UPDATED,
        {"section_id": section_id, "changes": changes},
        song_id=row["song_id"],
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    _touch_song(conn, row["song_id"])


def delete_section(
    conn: sqlite3.Connection,
    *,
    section_id: str,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> None:
    row = conn.execute(
        "SELECT song_id FROM sections WHERE id = ?", (section_id,)
    ).fetchone()
    if row is None:
        return
    conn.execute("DELETE FROM sections WHERE id = ?", (section_id,))
    _emit(
        conn,
        E.SECTION_DELETED,
        {"section_id": section_id},
        song_id=row["song_id"],
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    _touch_song(conn, row["song_id"])


# ---------------------------------------------------------------------------
# Score: tempo map
# ---------------------------------------------------------------------------

TEMPO_RAMP_KINDS = frozenset({"linear", "hold"})


def add_tempo_point(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    start_bar: float,
    tempo_bpm: float,
    ramp: str = "hold",
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> str:
    """Add a tempo point at `start_bar`. `ramp='hold'` keeps tempo constant
    until the next point; `'linear'` ramps to the next point's tempo."""
    if ramp not in TEMPO_RAMP_KINDS:
        raise ValueError(
            f"invalid ramp {ramp!r}; expected one of {sorted(TEMPO_RAMP_KINDS)}"
        )
    if tempo_bpm <= 0:
        raise ValueError(f"tempo_bpm must be positive, got {tempo_bpm}")
    pid = _uuid()
    conn.execute(
        """INSERT INTO tempo_map (id, song_id, start_bar, tempo_bpm, ramp)
           VALUES (?, ?, ?, ?, ?)""",
        (pid, song_id, start_bar, tempo_bpm, ramp),
    )
    _emit(
        conn,
        E.TEMPO_POINT_ADDED,
        {
            "point_id": pid,
            "start_bar": start_bar,
            "tempo_bpm": tempo_bpm,
            "ramp": ramp,
        },
        song_id=song_id,
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    _touch_song(conn, song_id)
    return pid


_TEMPO_POINT_FIELDS = {"tempo_bpm", "ramp"}


def update_tempo_point(
    conn: sqlite3.Connection,
    *,
    point_id: str,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
    **changes: Any,
) -> None:
    """Partial update of a tempo_map row. `changes` keys must be in
    _TEMPO_POINT_FIELDS — `start_bar` is identity here, change it via
    remove+add."""
    bad = set(changes) - _TEMPO_POINT_FIELDS
    if bad:
        raise ValueError(f"unsupported fields: {sorted(bad)}")
    if not changes:
        return
    if "tempo_bpm" in changes and changes["tempo_bpm"] <= 0:
        raise ValueError(f"tempo_bpm must be positive, got {changes['tempo_bpm']}")
    if "ramp" in changes and changes["ramp"] not in TEMPO_RAMP_KINDS:
        raise ValueError(
            f"invalid ramp {changes['ramp']!r}; "
            f"expected one of {sorted(TEMPO_RAMP_KINDS)}"
        )
    row = conn.execute(
        "SELECT song_id FROM tempo_map WHERE id = ?", (point_id,)
    ).fetchone()
    if row is None:
        return
    sets = [f"{k} = ?" for k in changes]
    vals = list(changes.values()) + [point_id]
    conn.execute(f"UPDATE tempo_map SET {', '.join(sets)} WHERE id = ?", vals)
    _emit(
        conn,
        E.TEMPO_POINT_UPDATED,
        {"point_id": point_id, "changes": changes},
        song_id=row["song_id"],
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    _touch_song(conn, row["song_id"])


def remove_tempo_point(
    conn: sqlite3.Connection,
    *,
    point_id: str,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> None:
    row = conn.execute(
        "SELECT song_id FROM tempo_map WHERE id = ?", (point_id,)
    ).fetchone()
    if row is None:
        return
    conn.execute("DELETE FROM tempo_map WHERE id = ?", (point_id,))
    _emit(
        conn,
        E.TEMPO_POINT_REMOVED,
        {"point_id": point_id},
        song_id=row["song_id"],
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    _touch_song(conn, row["song_id"])


# ---------------------------------------------------------------------------
# Score: time-signature map
# ---------------------------------------------------------------------------


def add_time_signature_point(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    start_bar: float,
    numerator: int,
    denominator: int,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> str:
    """Add a meter change at `start_bar` (numerator/denominator)."""
    if numerator <= 0 or denominator <= 0:
        raise ValueError(
            f"numerator/denominator must be positive, got {numerator}/{denominator}"
        )
    pid = _uuid()
    conn.execute(
        """INSERT INTO time_signature_map
               (id, song_id, start_bar, numerator, denominator)
           VALUES (?, ?, ?, ?, ?)""",
        (pid, song_id, start_bar, numerator, denominator),
    )
    _emit(
        conn,
        E.TIME_SIGNATURE_POINT_ADDED,
        {
            "point_id": pid,
            "start_bar": start_bar,
            "numerator": numerator,
            "denominator": denominator,
        },
        song_id=song_id,
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    _touch_song(conn, song_id)
    return pid


_TIME_SIGNATURE_POINT_FIELDS = {"numerator", "denominator"}


def update_time_signature_point(
    conn: sqlite3.Connection,
    *,
    point_id: str,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
    **changes: Any,
) -> None:
    """Partial update of a time_signature_map row. `changes` keys must be in
    _TIME_SIGNATURE_POINT_FIELDS — `start_bar` is identity here, change it
    via remove+add."""
    bad = set(changes) - _TIME_SIGNATURE_POINT_FIELDS
    if bad:
        raise ValueError(f"unsupported fields: {sorted(bad)}")
    if not changes:
        return
    if "numerator" in changes and changes["numerator"] <= 0:
        raise ValueError(f"numerator must be positive, got {changes['numerator']}")
    if "denominator" in changes and changes["denominator"] <= 0:
        raise ValueError(
            f"denominator must be positive, got {changes['denominator']}"
        )
    row = conn.execute(
        "SELECT song_id FROM time_signature_map WHERE id = ?", (point_id,)
    ).fetchone()
    if row is None:
        return
    sets = [f"{k} = ?" for k in changes]
    vals = list(changes.values()) + [point_id]
    conn.execute(
        f"UPDATE time_signature_map SET {', '.join(sets)} WHERE id = ?", vals
    )
    _emit(
        conn,
        E.TIME_SIGNATURE_POINT_UPDATED,
        {"point_id": point_id, "changes": changes},
        song_id=row["song_id"],
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    _touch_song(conn, row["song_id"])


def remove_time_signature_point(
    conn: sqlite3.Connection,
    *,
    point_id: str,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> None:
    row = conn.execute(
        "SELECT song_id FROM time_signature_map WHERE id = ?", (point_id,)
    ).fetchone()
    if row is None:
        return
    conn.execute("DELETE FROM time_signature_map WHERE id = ?", (point_id,))
    _emit(
        conn,
        E.TIME_SIGNATURE_POINT_REMOVED,
        {"point_id": point_id},
        song_id=row["song_id"],
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    _touch_song(conn, row["song_id"])


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
    """Add an arrangement marker at `position_bar`. Maps to Live's cue points."""
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
    return pid


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


# ---------------------------------------------------------------------------
# Mix: returns + sends
# ---------------------------------------------------------------------------


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
    whatever Live applies to a freshly-created return."""
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
    return rid


_RETURN_FIELDS = {"name", "position", "volume", "pan", "mute", "solo", "color"}


def update_return(
    conn: sqlite3.Connection,
    *,
    return_id: str,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
    **changes: Any,
) -> None:
    """Partial update by id. `changes` keys must be in _RETURN_FIELDS."""
    bad = set(changes) - _RETURN_FIELDS
    if bad:
        raise ValueError(f"unsupported fields: {sorted(bad)}")
    if not changes:
        return
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


def remove_send(
    conn: sqlite3.Connection,
    *,
    from_track_id: str,
    to_return_id: str,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> None:
    track_row = conn.execute(
        "SELECT song_id FROM tracks WHERE id = ?", (from_track_id,)
    ).fetchone()
    if track_row is None:
        return
    cur = conn.execute(
        "DELETE FROM sends WHERE from_track_id = ? AND to_return_id = ?",
        (from_track_id, to_return_id),
    )
    if cur.rowcount == 0:
        return
    _emit(
        conn,
        E.SEND_REMOVED,
        {"from_track_id": from_track_id, "to_return_id": to_return_id},
        song_id=track_row["song_id"],
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    _touch_song(conn, track_row["song_id"])


# ---------------------------------------------------------------------------
# Mix: device chains, devices, parameters
# ---------------------------------------------------------------------------
# Parent enforcement: `create_device_chain` accepts exactly one of three
# parent kwargs. The schema CHECK also enforces this, but raising in Python
# yields a clean error before the DB does. Top-level chains (track / return)
# use position=0 by convention; rack chains use their position within the
# parent rack device.


def create_device_chain(
    conn: sqlite3.Connection,
    *,
    parent_track_id: str | None = None,
    parent_return_id: str | None = None,
    parent_rack_device_id: str | None = None,
    position: int = 0,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> str:
    parents = [
        ("parent_track_id", parent_track_id),
        ("parent_return_id", parent_return_id),
        ("parent_rack_device_id", parent_rack_device_id),
    ]
    set_parents = [(k, v) for k, v in parents if v is not None]
    if len(set_parents) != 1:
        raise ValueError(
            f"create_device_chain: exactly one parent kwarg required, "
            f"got {[k for k, _ in set_parents]}"
        )
    chain_id = _uuid()
    conn.execute(
        """INSERT INTO device_chains
               (id, parent_track_id, parent_return_id, parent_rack_device_id, position)
           VALUES (?, ?, ?, ?, ?)""",
        (chain_id, parent_track_id, parent_return_id, parent_rack_device_id, position),
    )
    # Resolve song_id for the event so audit queries find it via song.
    song_id = _resolve_chain_song(
        conn,
        parent_track_id=parent_track_id,
        parent_return_id=parent_return_id,
        parent_rack_device_id=parent_rack_device_id,
    )
    _emit(
        conn,
        E.DEVICE_CHAIN_CREATED,
        {
            "chain_id": chain_id,
            "parent_track_id": parent_track_id,
            "parent_return_id": parent_return_id,
            "parent_rack_device_id": parent_rack_device_id,
            "position": position,
        },
        song_id=song_id,
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    if song_id:
        _touch_song(conn, song_id)
    return chain_id


def _resolve_chain_song(
    conn: sqlite3.Connection,
    *,
    parent_track_id: str | None,
    parent_return_id: str | None,
    parent_rack_device_id: str | None,
) -> str | None:
    """Walk a chain's parent up to its song_id. Nested rack chains recurse
    through their parent device's chain until reaching a track or return."""
    if parent_track_id is not None:
        row = conn.execute(
            "SELECT song_id FROM tracks WHERE id = ?", (parent_track_id,)
        ).fetchone()
        return row["song_id"] if row else None
    if parent_return_id is not None:
        row = conn.execute(
            "SELECT song_id FROM returns WHERE id = ?", (parent_return_id,)
        ).fetchone()
        return row["song_id"] if row else None
    if parent_rack_device_id is not None:
        # Device -> its chain -> recurse on that chain's parent.
        row = conn.execute(
            """SELECT dc.parent_track_id, dc.parent_return_id, dc.parent_rack_device_id
               FROM devices d
               JOIN device_chains dc ON dc.id = d.chain_id
               WHERE d.id = ?""",
            (parent_rack_device_id,),
        ).fetchone()
        if row is None:
            return None
        return _resolve_chain_song(
            conn,
            parent_track_id=row["parent_track_id"],
            parent_return_id=row["parent_return_id"],
            parent_rack_device_id=row["parent_rack_device_id"],
        )
    return None


def delete_device_chain(
    conn: sqlite3.Connection,
    *,
    chain_id: str,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> None:
    row = conn.execute(
        """SELECT parent_track_id, parent_return_id, parent_rack_device_id
           FROM device_chains WHERE id = ?""",
        (chain_id,),
    ).fetchone()
    if row is None:
        return
    song_id = _resolve_chain_song(
        conn,
        parent_track_id=row["parent_track_id"],
        parent_return_id=row["parent_return_id"],
        parent_rack_device_id=row["parent_rack_device_id"],
    )
    conn.execute("DELETE FROM device_chains WHERE id = ?", (chain_id,))
    _emit(
        conn,
        E.DEVICE_CHAIN_DELETED,
        {"chain_id": chain_id},
        song_id=song_id,
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    if song_id:
        _touch_song(conn, song_id)


def create_device(
    conn: sqlite3.Connection,
    *,
    chain_id: str,
    position: int,
    kind: str,
    display_name: str,
    preset_uri: str | None = None,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> str:
    """Create a device in `chain_id` at 1-based `position`. `kind` is Live's
    class name (Compressor2, Eq8, DrumGroupDevice, ...); `display_name` is
    the user-visible name (often == kind, may be a preset name)."""
    if position < 1:
        raise ValueError(f"device position {position} must be >= 1")
    device_id = _uuid()
    conn.execute(
        """INSERT INTO devices (id, chain_id, position, kind, display_name, preset_uri)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (device_id, chain_id, position, kind, display_name, preset_uri),
    )
    song_id = _resolve_device_song(conn, device_id=device_id)
    _emit(
        conn,
        E.DEVICE_CREATED,
        {
            "device_id": device_id,
            "chain_id": chain_id,
            "position": position,
            "kind": kind,
            "display_name": display_name,
            "preset_uri": preset_uri,
        },
        song_id=song_id,
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    if song_id:
        _touch_song(conn, song_id)
    return device_id


def _resolve_device_song(
    conn: sqlite3.Connection,
    *,
    device_id: str,
) -> str | None:
    row = conn.execute(
        """SELECT dc.parent_track_id, dc.parent_return_id, dc.parent_rack_device_id
           FROM devices d
           JOIN device_chains dc ON dc.id = d.chain_id
           WHERE d.id = ?""",
        (device_id,),
    ).fetchone()
    if row is None:
        return None
    return _resolve_chain_song(
        conn,
        parent_track_id=row["parent_track_id"],
        parent_return_id=row["parent_return_id"],
        parent_rack_device_id=row["parent_rack_device_id"],
    )


def delete_device(
    conn: sqlite3.Connection,
    *,
    device_id: str,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> None:
    song_id = _resolve_device_song(conn, device_id=device_id)
    cur = conn.execute("DELETE FROM devices WHERE id = ?", (device_id,))
    if cur.rowcount == 0:
        return
    _emit(
        conn,
        E.DEVICE_DELETED,
        {"device_id": device_id},
        song_id=song_id,
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    if song_id:
        _touch_song(conn, song_id)


def set_device_parameter(
    conn: sqlite3.Connection,
    *,
    device_id: str,
    name: str,
    value_display: str,
    value_normalized: float | None = None,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> str:
    """Upsert a device parameter by (device_id, name). Returns parameter id.

    `value_display` is always set (the human-readable form). `value_normalized`
    is optional — discrete-enum parameters (e.g., Filter Type = "Lowpass")
    have no continuous form.
    """
    if value_normalized is not None and not (0.0 <= value_normalized <= 1.0):
        raise ValueError(
            f"value_normalized {value_normalized} out of range [0.0, 1.0]"
        )
    existing = conn.execute(
        "SELECT id FROM device_parameters WHERE device_id = ? AND name = ?",
        (device_id, name),
    ).fetchone()
    if existing is None:
        param_id = _uuid()
        conn.execute(
            """INSERT INTO device_parameters
                   (id, device_id, name, value_display, value_normalized)
               VALUES (?, ?, ?, ?, ?)""",
            (param_id, device_id, name, value_display, value_normalized),
        )
    else:
        param_id = existing["id"]
        conn.execute(
            """UPDATE device_parameters
                  SET value_display = ?, value_normalized = ?
                WHERE id = ?""",
            (value_display, value_normalized, param_id),
        )
    song_id = _resolve_device_song(conn, device_id=device_id)
    _emit(
        conn,
        E.DEVICE_PARAMETER_SET,
        {
            "parameter_id": param_id,
            "device_id": device_id,
            "name": name,
            "value_display": value_display,
            "value_normalized": value_normalized,
        },
        song_id=song_id,
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    if song_id:
        _touch_song(conn, song_id)
    return param_id


def remove_device_parameter(
    conn: sqlite3.Connection,
    *,
    device_id: str,
    name: str,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> None:
    cur = conn.execute(
        "DELETE FROM device_parameters WHERE device_id = ? AND name = ?",
        (device_id, name),
    )
    if cur.rowcount == 0:
        return
    song_id = _resolve_device_song(conn, device_id=device_id)
    _emit(
        conn,
        E.DEVICE_PARAMETER_REMOVED,
        {"device_id": device_id, "name": name},
        song_id=song_id,
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    if song_id:
        _touch_song(conn, song_id)


# ---------------------------------------------------------------------------
# Mix: automation envelopes + breakpoints
# ---------------------------------------------------------------------------
# Unified shape per target_kind. The mutator validates that the right target
# kwarg is set for the given kind, that parameter_path is present where it's
# required, and resolves song_id from the target (so the event carries song
# provenance even when target_song_id isn't passed explicitly).
#
# Cascade: every target FK has ON DELETE CASCADE, so deleting a clip/note/
# device/track/return collapses any envelopes that pointed at it. No mutator
# discipline needed for cascade — schema handles it.


ENVELOPE_TARGET_KINDS = frozenset({
    "clip_cc",
    "clip_pitch_bend",
    "note_expression",
    "device_parameter",
    "mixer_volume",
    "mixer_pan",
    "send_level",
})

# parameter_path is required for these kinds (CC number / MPE axis / param name)
# and optional/forbidden for the rest.
_PARAMETER_PATH_REQUIRED = frozenset({
    "clip_cc", "note_expression", "device_parameter",
})

# MPE axes accepted in parameter_path for note_expression envelopes.
NOTE_EXPRESSION_AXES = frozenset({"pitch", "pressure", "timbre"})

BREAKPOINT_CURVE_KINDS = frozenset({"linear", "hold", "fast", "slow"})


def create_envelope(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    target_kind: str,
    target_clip_id: str | None = None,
    target_note_id: str | None = None,
    target_device_id: str | None = None,
    target_track_id: str | None = None,
    target_send_return_id: str | None = None,
    parameter_path: str | None = None,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> str:
    """Create an envelope row. Returns the envelope id.

    Caller passes exactly the target kwarg(s) the kind requires:
      clip_cc / clip_pitch_bend  -> target_clip_id
      note_expression            -> target_note_id (parameter_path = MPE axis)
      device_parameter           -> target_device_id (parameter_path = name)
      mixer_volume / mixer_pan   -> target_track_id
      send_level                 -> target_track_id + target_send_return_id

    The schema CHECK is the last-line defense; this mutator raises early with
    a clearer message and validates parameter_path semantics (required for
    clip_cc / note_expression / device_parameter; MPE axis allowlist).
    """
    if target_kind not in ENVELOPE_TARGET_KINDS:
        raise ValueError(
            f"invalid target_kind {target_kind!r}; "
            f"expected one of {sorted(ENVELOPE_TARGET_KINDS)}"
        )

    expected_targets: dict[str, tuple[str, ...]] = {
        "clip_cc":          ("target_clip_id",),
        "clip_pitch_bend":  ("target_clip_id",),
        "note_expression":  ("target_note_id",),
        "device_parameter": ("target_device_id",),
        "mixer_volume":     ("target_track_id",),
        "mixer_pan":        ("target_track_id",),
        "send_level":       ("target_track_id", "target_send_return_id"),
    }
    all_targets = {
        "target_clip_id": target_clip_id,
        "target_note_id": target_note_id,
        "target_device_id": target_device_id,
        "target_track_id": target_track_id,
        "target_send_return_id": target_send_return_id,
    }
    required = expected_targets[target_kind]
    for k in required:
        if all_targets[k] is None:
            raise ValueError(
                f"target_kind={target_kind!r} requires kwarg {k}"
            )
    for k, v in all_targets.items():
        if k not in required and v is not None:
            raise ValueError(
                f"target_kind={target_kind!r} forbids kwarg {k} (got {v!r})"
            )

    if target_kind in _PARAMETER_PATH_REQUIRED:
        if not parameter_path:
            raise ValueError(
                f"target_kind={target_kind!r} requires parameter_path "
                "(CC number / MPE axis / parameter name)"
            )
    else:
        if parameter_path is not None:
            raise ValueError(
                f"target_kind={target_kind!r} does not use parameter_path "
                f"(got {parameter_path!r})"
            )

    if target_kind == "note_expression" and parameter_path not in NOTE_EXPRESSION_AXES:
        raise ValueError(
            f"note_expression parameter_path {parameter_path!r} not in "
            f"{sorted(NOTE_EXPRESSION_AXES)}"
        )

    if target_kind == "clip_cc":
        try:
            cc_number = int(parameter_path)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"clip_cc parameter_path must be an integer CC number "
                f"(got {parameter_path!r})"
            ) from exc
        if not 0 <= cc_number <= 127:
            raise ValueError(
                f"clip_cc CC number {cc_number} out of MIDI range [0, 127]"
            )

    # Provenance: clip envelopes carry their target_clip_id; note_expression
    # envelopes resolve clip via the note's parent so audit-trail queries by
    # clip find them too.
    event_clip_id = target_clip_id
    if target_kind == "note_expression":
        note_row = conn.execute(
            "SELECT clip_id FROM notes WHERE id = ?", (target_note_id,),
        ).fetchone()
        if note_row is not None:
            event_clip_id = note_row["clip_id"]

    env_id = _uuid()
    conn.execute(
        """INSERT INTO envelopes
               (id, song_id, target_kind,
                target_clip_id, target_note_id, target_device_id,
                target_track_id, target_send_return_id, parameter_path)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            env_id, song_id, target_kind,
            target_clip_id, target_note_id, target_device_id,
            target_track_id, target_send_return_id, parameter_path,
        ),
    )
    _emit(
        conn,
        E.ENVELOPE_CREATED,
        {
            "envelope_id": env_id,
            "target_kind": target_kind,
            "target_clip_id": target_clip_id,
            "target_note_id": target_note_id,
            "target_device_id": target_device_id,
            "target_track_id": target_track_id,
            "target_send_return_id": target_send_return_id,
            "parameter_path": parameter_path,
        },
        song_id=song_id,
        clip_id=event_clip_id,
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    _touch_song(conn, song_id)
    return env_id


def delete_envelope(
    conn: sqlite3.Connection,
    *,
    envelope_id: str,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> None:
    row = conn.execute(
        "SELECT song_id, target_clip_id FROM envelopes WHERE id = ?",
        (envelope_id,),
    ).fetchone()
    if row is None:
        return
    conn.execute("DELETE FROM envelopes WHERE id = ?", (envelope_id,))
    _emit(
        conn,
        E.ENVELOPE_DELETED,
        {"envelope_id": envelope_id},
        song_id=row["song_id"],
        clip_id=row["target_clip_id"],
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    _touch_song(conn, row["song_id"])


def _resolve_envelope_song(
    conn: sqlite3.Connection, envelope_id: str,
) -> tuple[str | None, str | None]:
    """Return (song_id, target_clip_id) for an envelope, for event provenance."""
    row = conn.execute(
        "SELECT song_id, target_clip_id FROM envelopes WHERE id = ?",
        (envelope_id,),
    ).fetchone()
    if row is None:
        return None, None
    return row["song_id"], row["target_clip_id"]


def add_breakpoint(
    conn: sqlite3.Connection,
    *,
    envelope_id: str,
    time_beats: float,
    value: float,
    curve_kind: str = "linear",
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> str:
    """Append a single breakpoint to an envelope. Returns the breakpoint id."""
    if curve_kind not in BREAKPOINT_CURVE_KINDS:
        raise ValueError(
            f"invalid curve_kind {curve_kind!r}; "
            f"expected one of {sorted(BREAKPOINT_CURVE_KINDS)}"
        )
    bp_id = _uuid()
    conn.execute(
        """INSERT INTO automation_breakpoints
               (id, envelope_id, time_beats, value, curve_kind)
           VALUES (?, ?, ?, ?, ?)""",
        (bp_id, envelope_id, time_beats, value, curve_kind),
    )
    song_id, clip_id = _resolve_envelope_song(conn, envelope_id)
    _emit(
        conn,
        E.BREAKPOINT_ADDED,
        {
            "breakpoint_id": bp_id,
            "envelope_id": envelope_id,
            "time_beats": time_beats,
            "value": value,
            "curve_kind": curve_kind,
        },
        song_id=song_id,
        clip_id=clip_id,
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    if song_id:
        _touch_song(conn, song_id)
    return bp_id


def remove_breakpoint(
    conn: sqlite3.Connection,
    *,
    breakpoint_id: str,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> None:
    row = conn.execute(
        "SELECT envelope_id FROM automation_breakpoints WHERE id = ?",
        (breakpoint_id,),
    ).fetchone()
    if row is None:
        return
    envelope_id = row["envelope_id"]
    conn.execute(
        "DELETE FROM automation_breakpoints WHERE id = ?", (breakpoint_id,)
    )
    song_id, clip_id = _resolve_envelope_song(conn, envelope_id)
    _emit(
        conn,
        E.BREAKPOINT_REMOVED,
        {"breakpoint_id": breakpoint_id, "envelope_id": envelope_id},
        song_id=song_id,
        clip_id=clip_id,
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    if song_id:
        _touch_song(conn, song_id)


def replace_breakpoints(
    conn: sqlite3.Connection,
    *,
    envelope_id: str,
    breakpoints: Sequence[dict[str, Any]],
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> list[str]:
    """Atomic: delete every breakpoint for `envelope_id`, insert the new set.
    Returns the new breakpoint ids in insertion order. Single event emitted.

    Each breakpoint dict: {time_beats: float, value: float,
    curve_kind: 'linear'|'hold'|'fast'|'slow' (default 'linear')}.
    """
    with transaction(conn):
        prev_count = conn.execute(
            "SELECT COUNT(*) AS c FROM automation_breakpoints WHERE envelope_id = ?",
            (envelope_id,),
        ).fetchone()["c"]
        conn.execute(
            "DELETE FROM automation_breakpoints WHERE envelope_id = ?",
            (envelope_id,),
        )
        new_ids: list[str] = []
        for bp in breakpoints:
            curve = bp.get("curve_kind", "linear")
            if curve not in BREAKPOINT_CURVE_KINDS:
                raise ValueError(
                    f"invalid curve_kind {curve!r}; "
                    f"expected one of {sorted(BREAKPOINT_CURVE_KINDS)}"
                )
            bp_id = _uuid()
            conn.execute(
                """INSERT INTO automation_breakpoints
                       (id, envelope_id, time_beats, value, curve_kind)
                   VALUES (?, ?, ?, ?, ?)""",
                (bp_id, envelope_id, float(bp["time_beats"]),
                 float(bp["value"]), curve),
            )
            new_ids.append(bp_id)
        song_id, clip_id = _resolve_envelope_song(conn, envelope_id)
        _emit(
            conn,
            E.BREAKPOINTS_REPLACED,
            {
                "envelope_id": envelope_id,
                "prev_count": prev_count,
                "new_count": len(new_ids),
                "breakpoint_ids": new_ids,
            },
            song_id=song_id,
            clip_id=clip_id,
            actor=actor,
            request_id=request_id,
            reason=reason,
        )
        if song_id:
            _touch_song(conn, song_id)
    return new_ids


# ---------------------------------------------------------------------------
# Ableton projection: sessions + links
# ---------------------------------------------------------------------------

# db_kind values currently used by the sync layer.
ABLETON_LINK_KINDS = frozenset({
    "track", "clip", "arrangement", "note", "return", "device", "envelope",
})


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
