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


# Live's Clip.warp_mode enum ints (LOM value domain, stored directly so the
# column never drifts from Live). 'rex' is Live's legacy REX-file mode —
# readable on old clips, not a sensible authoring target.
WARP_MODES = {
    "beats": 0,
    "tones": 1,
    "texture": 2,
    "repitch": 3,
    "complex": 4,
    "rex": 5,
    "complex_pro": 6,
}


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
        "SELECT t.song_id, t.kind FROM tracks t WHERE t.id = ?", (track_id,)
    ).fetchone()
    if song_row is not None and song_row["kind"] == "audio":
        raise ValueError(
            f"MIDI clip on a track of kind='audio' is not valid: Live "
            "hosts MIDI clips only on MIDI tracks. Use create_audio_clip "
            f"for audio material on track {track_id}, or create a "
            "kind='midi' host track."
        )
    existing = conn.execute(
        """SELECT id, kind, length_beats, name, section_role, generator_call_json
           FROM clips WHERE track_id = ? AND slot = ?""",
        (track_id, slot),
    ).fetchone()
    if existing is not None:
        # `kind` is immutable — the idempotent-rebuild path must never
        # silently "update" an audio row as MIDI (mirror of
        # create_audio_clip's MIDI-slot refusal).
        if existing["kind"] != "midi":
            raise ValueError(
                f"slot {slot} on track {track_id} already holds a "
                f"kind={existing['kind']!r} clip: clip kind is immutable. "
                "Delete the existing clip first (delete+create), or pick "
                "another slot."
            )
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
               (id, track_id, slot, length_beats, name, section_role,
                generator_call_json, kind)
           VALUES (?, ?, ?, ?, ?, ?, ?, 'midi')""",
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
            "kind": "midi",
        },
        song_id=song_row["song_id"] if song_row else None,
        clip_id=cid,
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    _record_touch_if_session("clip", cid)
    return MutatorResult(cid, "created")


def create_audio_clip(
    conn: sqlite3.Connection,
    *,
    track_id: str,
    slot: int,
    length_beats: float,
    audio_file: str,
    name: str | None = None,
    gain: float | None = None,
    pitch_coarse: int | None = None,
    pitch_fine: float | None = None,
    warping: int | None = None,
    warp_mode: int | None = None,
    start_marker: float | None = None,
    end_marker: float | None = None,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> str:
    """Create a session audio clip (kind='audio') — CLP-AUD1 wave 1.

    `audio_file` is stored exactly as authored: a song-relative POSIX path
    (canonically under `assets/`) or an absolute path; resolution happens at
    push/analysis time, not here. `start_marker`/`end_marker` carry Live's
    dual unit — beats when `warping` is on, seconds when off. `length_beats`
    is the authored placement length (slot extent), never derived audio
    duration. The host track must be kind='audio'.
    """
    if not audio_file:
        raise ValueError(
            "audio_file is required for an audio clip: the row must answer "
            "'what does this clip play?'. Pass a song-relative POSIX path "
            "(canonically under assets/) or an absolute path."
        )
    actor, request_id = _resolve_actor_and_request(actor, request_id)
    track_row = conn.execute(
        "SELECT t.song_id, t.kind FROM tracks t WHERE t.id = ?", (track_id,)
    ).fetchone()
    if track_row is not None and track_row["kind"] != "audio":
        raise ValueError(
            f"audio clip on a track of kind={track_row['kind']!r} is not "
            "valid: Live hosts audio clips only on audio tracks. Create the "
            "host track with kind='audio', or use create_clip for MIDI "
            "material."
        )
    existing = conn.execute(
        """SELECT id, kind, length_beats, name, audio_file, audio_gain,
                  pitch_coarse, pitch_fine, warping, warp_mode,
                  start_marker, end_marker
           FROM clips WHERE track_id = ? AND slot = ?""",
        (track_id, slot),
    ).fetchone()
    fields = {
        "length_beats": length_beats,
        "name": name,
        "audio_file": audio_file,
        "audio_gain": gain,
        "pitch_coarse": pitch_coarse,
        "pitch_fine": pitch_fine,
        "warping": warping,
        "warp_mode": warp_mode,
        "start_marker": start_marker,
        "end_marker": end_marker,
    }
    if existing is not None:
        # `kind` is immutable — converting a MIDI slot to audio is
        # delete+create, same doctrine as track_id/slot relocation.
        if existing["kind"] != "audio":
            raise ValueError(
                f"slot {slot} on track {track_id} already holds a "
                f"kind={existing['kind']!r} clip: clip kind is immutable. "
                "Delete the existing clip first (delete+create), or pick "
                "another slot."
            )
        cid = existing["id"]
        if all(existing[k] == v for k, v in fields.items()):
            _record_touch_if_session("clip", cid)
            return MutatorResult(cid, "unchanged")
        sets = ", ".join(f"{k} = ?" for k in fields)
        conn.execute(
            f"""UPDATE clips SET {sets},
                                 updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                WHERE id = ?""",
            (*fields.values(), cid),
        )
        _emit(
            conn,
            E.CLIP_UPDATED,
            {"clip_id": cid, "track_id": track_id, "changes": fields},
            song_id=track_row["song_id"] if track_row else None,
            clip_id=cid,
            actor=actor,
            request_id=request_id,
            reason=reason,
        )
        _record_touch_if_session("clip", cid)
        return MutatorResult(cid, "updated")
    cid = _uuid()
    cols = ", ".join(fields)
    placeholders = ", ".join("?" for _ in fields)
    conn.execute(
        f"""INSERT INTO clips (id, track_id, slot, kind, {cols})
            VALUES (?, ?, ?, 'audio', {placeholders})""",
        (cid, track_id, slot, *fields.values()),
    )
    _emit(
        conn,
        E.CLIP_CREATED,
        {
            "clip_id": cid,
            "track_id": track_id,
            "slot": slot,
            "kind": "audio",
            **fields,
        },
        song_id=track_row["song_id"] if track_row else None,
        clip_id=cid,
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    _record_touch_if_session("clip", cid)
    return MutatorResult(cid, "created")


_CLIP_UPDATE_FIELDS = frozenset({"name", "length_beats", "section_role"})

# Audio-only columns (CLP-AUD1 wave 1) — updatable on kind='audio' rows
# only; a MIDI clip carrying any of these is a kind-guard violation.
_AUDIO_CLIP_UPDATE_FIELDS = frozenset({
    "audio_file",
    "audio_gain",
    "pitch_coarse",
    "pitch_fine",
    "warping",
    "warp_mode",
    "start_marker",
    "end_marker",
})


def update_clip(
    conn: sqlite3.Connection,
    *,
    clip_id: str,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
    **changes: Any,
) -> None:
    """Partial update by id. `changes` keys must be in _CLIP_UPDATE_FIELDS
    (both kinds) or _AUDIO_CLIP_UPDATE_FIELDS (kind='audio' rows only).

    Deliberately excludes `track_id` (moving a clip between tracks is
    delete+create), `slot` (slot relocation is delete+create), `kind`
    (MIDI<->audio conversion is delete+create — same doctrine), and
    `generator_call_json` (provenance — append-only-ish). Notes are
    written via `replace_clip_notes` / `insert_notes`, not here.
    """
    if "kind" in changes:
        raise ValueError(
            "clip `kind` is immutable: converting between MIDI and audio "
            "is delete+create, same doctrine as track_id/slot relocation."
        )
    bad = set(changes) - _CLIP_UPDATE_FIELDS - _AUDIO_CLIP_UPDATE_FIELDS
    if bad:
        raise ValueError(f"unsupported fields: {sorted(bad)}")
    if not changes:
        return
    row = conn.execute(
        """SELECT c.track_id, c.kind, t.song_id FROM clips c
           JOIN tracks t ON t.id = c.track_id WHERE c.id = ?""",
        (clip_id,),
    ).fetchone()
    if row is None:
        return
    audio_changes = set(changes) & _AUDIO_CLIP_UPDATE_FIELDS
    if audio_changes and row["kind"] != "audio":
        raise ValueError(
            f"audio fields {sorted(audio_changes)} on a "
            f"kind={row['kind']!r} clip are not valid: audio columns live "
            "on kind='audio' clips only (MIDI clips ignore audio fields "
            "by contract). Author audio material via create_audio_clip "
            "on an audio track."
        )
    if row["kind"] == "audio" and "audio_file" in changes and not changes["audio_file"]:
        raise ValueError(
            "audio_file cannot be cleared on an audio clip: the row must "
            "always answer 'what does this clip play?'. To retire the "
            "clip, delete it (delete+create doctrine)."
        )
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
    "WARP_MODES",
    "create_audio_clip",
    "create_clip",
    "delete_clip",
    "update_clip",
]
