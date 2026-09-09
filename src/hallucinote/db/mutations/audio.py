"""Audio-capture audit trail (AUD-5M8H).

A capture pass writes WAVs + a manifest to disk; nothing in the DB recorded
that it happened, so "when was this take captured" could only be answered by
listing directories. This module appends the one audit event that puts capture
timestamps into the event log, queryable through
``queries.get_events_for_song`` alongside every other thing that happened to
the song.

Deliberately audit-only: the captures dir is a regenerable build artifact, not
domain state, so nothing here writes a projection table.
"""
from __future__ import annotations

import sqlite3

from ._core import (
    E,
    _atomic,
    _emit,
)


@_atomic
def record_audio_capture(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    captures_dir: str,
    manifest_seq: int | None = None,
    track_count: int | None = None,
    actor: str = "sync",
    request_id: str | None = None,
    reason: str | None = None,
) -> str | None:
    """Append an ``AUDIO_CAPTURED`` event for a completed capture pass.

    Returns the new event id, or ``None`` when this ``captures_dir`` is already
    recorded for this song.

    **Idempotent by captures_dir**, because the caller is a poll: the agent
    polls ``ableton_render(action='status')`` until it reads ``done``, and every
    poll after that reads ``done`` again. Emitting per poll would write one
    event per poll for a single take. The dedupe lives here, inside the same
    transaction as the append, so two concurrent callers cannot both pass the
    check — and it keys on the dir rather than an in-memory flag so it survives
    a server restart mid-poll.
    """
    existing = conn.execute(
        "SELECT id FROM events WHERE song_id = ? AND kind = ? "
        "AND json_extract(payload_json, '$.captures_dir') = ? LIMIT 1",
        (song_id, E.AUDIO_CAPTURED, captures_dir),
    ).fetchone()
    if existing is not None:
        return None
    return _emit(
        conn,
        E.AUDIO_CAPTURED,
        {
            "captures_dir": captures_dir,
            "manifest_seq": manifest_seq,
            "track_count": track_count,
        },
        song_id=song_id,
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
