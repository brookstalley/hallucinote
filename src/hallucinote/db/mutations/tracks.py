"""Tracks: create, mixer state, and the tombstone-time delete helper."""
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
)


TRACK_KINDS = frozenset({"midi", "audio", "master", "group"})


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
    'group'. Real returns live in the `returns` table — the `'return'` kind
    on a `tracks` row was dropped V1 close-out 2026-05-17 (schema CHECK
    rejects). Mixer state lives on the row but is set separately via
    `set_track_mixer`."""
    if kind not in TRACK_KINDS:
        raise ValueError(f"invalid kind {kind!r}; expected one of {sorted(TRACK_KINDS)}")
    actor, request_id = _resolve_actor_and_request(actor, request_id)
    existing = conn.execute(
        """SELECT id, name, instrument_uri, kind FROM tracks
           WHERE song_id = ? AND track_index = ?""",
        (song_id, track_index),
    ).fetchone()
    if existing is not None:
        tid = existing["id"]
        if (existing["name"], existing["instrument_uri"], existing["kind"]) == (
            name, instrument_uri, kind,
        ):
            _record_touch_if_session("track", tid)
            return MutatorResult(tid, "unchanged")
        conn.execute(
            """UPDATE tracks SET name = ?, instrument_uri = ?, kind = ?
               WHERE id = ?""",
            (name, instrument_uri, kind, tid),
        )
        _emit(
            conn,
            E.TRACK_UPDATED,
            {"track_id": tid, "track_index": track_index, "name": name,
             "instrument_uri": instrument_uri, "kind": kind},
            song_id=song_id,
            actor=actor,
            request_id=request_id,
            reason=reason,
        )
        _touch_song(conn, song_id)
        _record_touch_if_session("track", tid)
        return MutatorResult(tid, "updated")
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
    _record_touch_if_session("track", tid)
    return MutatorResult(tid, "created")


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
    actor, request_id = _resolve_actor_and_request(actor, request_id)
    # Fetch existing values so we can skip when state already matches.
    cols = ", ".join(["song_id"] + list(changes))
    row = conn.execute(
        f"SELECT {cols} FROM tracks WHERE id = ?", (track_id,)
    ).fetchone()
    if row is None:
        return
    # W12-A: idempotent — diff per-field; skip event when no field changes.
    actual_changes = {k: v for k, v in changes.items() if row[k] != v}
    if not actual_changes:
        return
    sets = [f"{k} = ?" for k in actual_changes]
    vals = list(actual_changes.values()) + [track_id]
    conn.execute(f"UPDATE tracks SET {', '.join(sets)} WHERE id = ?", vals)
    _emit(
        conn,
        E.TRACK_MIXER_SET,
        {"track_id": track_id, "changes": actual_changes},
        song_id=row["song_id"],
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    _touch_song(conn, row["song_id"])


def _delete_track(
    conn: sqlite3.Connection, *,
    track_id: str,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> None:
    """Tombstone-time helper: delete a track row. The schema already cascades
    to clips/arrangement_clips/device_chains/etc, but mutations.py didn't
    historically expose a `delete_track` mutator because the only path that
    needed it was `delete_song` (which doesn't exist either). W12-A's
    BuildSession needs it for tombstoning."""
    row = conn.execute(
        "SELECT song_id FROM tracks WHERE id = ?", (track_id,)
    ).fetchone()
    if row is None:
        return
    conn.execute("DELETE FROM tracks WHERE id = ?", (track_id,))
    _emit(
        conn, E.TRACK_DELETED,
        {"track_id": track_id},
        song_id=row["song_id"],
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    _touch_song(conn, row["song_id"])


__all__ = [
    "TRACK_KINDS",
    "_delete_track",
    "create_track",
    "set_track_mixer",
]
