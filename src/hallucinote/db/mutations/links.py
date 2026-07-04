"""Ableton projection (sessions + links) and the W18-C soft reset."""
from __future__ import annotations

import sqlite3

from ._core import (
    E,
    _atomic,
    _emit,
    _uuid,
)


# ---------------------------------------------------------------------------
# Soft reset (W18-C)
# ---------------------------------------------------------------------------


@_atomic
def reset_song_content(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    actor: str = "build",
    request_id: str | None = None,
    reason: str | None = None,
) -> dict[str, int]:
    """Soft-reset a song: wipe rebuild-by-build.py content while preserving
    the mix layout (tracks, returns, sends, devices) AND the Ableton
    projection (ableton_sessions, ableton_links).

    W18-C: closes the punk-fate state-drift bug where ``build.py --reset``
    wiped ``ableton_sessions`` + ``ableton_links``, invalidating session_ids
    presented as durable handles. Soft reset keeps those bindings so the
    natural compose-iterate loop (edit build.py → re-run --reset → push
    again) doesn't surface "no ableton_sessions row" errors mid-flow.

    Track / return / device UUIDs survive because the mix-layout mutators
    (``create_track``, ``create_return``, ``create_device``, etc.) are
    upsert-shaped by ``(song_id, track_index)`` / ``(song_id, position)``
    keys (W12-A). ``replay_capture`` re-runs after reset return the same
    UUIDs, and ``ableton_links`` stay pointed at valid targets.

    Wiped tables (scoped to this song):

    * ``sections``, ``tempo_map``, ``time_signature_map``, ``cue_points``
      (score-half)
    * ``arrangement_clips``, ``clips``, ``notes`` (clip content)
    * ``envelopes``, ``automation_breakpoints`` (automation)

    Preserved (scoped to this song):

    * ``songs`` (the song row itself)
    * ``tracks``, ``returns``, ``sends``
    * ``device_chains``, ``devices``, ``device_parameters``
    * ``ableton_sessions``, ``ableton_links``
    * ``markdown_refs`` (decisions / annotations are author-managed)
    * ``events``, ``requests`` (audit log — append-only by invariant)

    Cross-song preserves: ``kits``, ``preset_chains``.

    For a full clean slate (drop bindings too), unlink the DB file
    directly — that's the explicit "I really want to start over" path.

    Returns a counts dict mapping table name -> deleted row count, and
    emits one ``song_content_reset`` event with those counts in the
    payload.
    """
    counts: dict[str, int] = {}

    # Leaf-first, even though FK CASCADEs would handle dependents — we want
    # accurate row counts per table for the emitted event payload.

    cur = conn.execute(
        "DELETE FROM automation_breakpoints WHERE envelope_id IN "
        "(SELECT id FROM envelopes WHERE song_id = ?)",
        (song_id,),
    )
    counts["automation_breakpoints"] = cur.rowcount

    cur = conn.execute("DELETE FROM envelopes WHERE song_id = ?", (song_id,))
    counts["envelopes"] = cur.rowcount

    cur = conn.execute(
        "DELETE FROM arrangement_clips WHERE song_id = ?", (song_id,),
    )
    counts["arrangement_clips"] = cur.rowcount

    cur = conn.execute(
        "DELETE FROM notes WHERE clip_id IN "
        "(SELECT c.id FROM clips c JOIN tracks t ON t.id = c.track_id "
        " WHERE t.song_id = ?)",
        (song_id,),
    )
    counts["notes"] = cur.rowcount

    cur = conn.execute(
        "DELETE FROM clips WHERE track_id IN "
        "(SELECT id FROM tracks WHERE song_id = ?)",
        (song_id,),
    )
    counts["clips"] = cur.rowcount

    cur = conn.execute("DELETE FROM cue_points WHERE song_id = ?", (song_id,))
    counts["cue_points"] = cur.rowcount

    cur = conn.execute(
        "DELETE FROM time_signature_map WHERE song_id = ?", (song_id,),
    )
    counts["time_signature_map"] = cur.rowcount

    cur = conn.execute("DELETE FROM tempo_map WHERE song_id = ?", (song_id,))
    counts["tempo_map"] = cur.rowcount

    cur = conn.execute("DELETE FROM sections WHERE song_id = ?", (song_id,))
    counts["sections"] = cur.rowcount

    _emit(
        conn,
        "song_content_reset",
        {"counts": counts},
        song_id=song_id,
        actor=actor,
        request_id=request_id,
        reason=reason or "reset_song_content (W18-C soft reset)",
    )
    # No explicit commit: @_atomic owns the transaction (EVT-6H9R) — the
    # autocommit-era `conn.commit()` here would commit early and break the
    # wrapper's COMMIT.
    return counts


# ---------------------------------------------------------------------------
# Ableton projection: sessions + links
# ---------------------------------------------------------------------------

# db_kind values currently used by the sync layer.
ABLETON_LINK_KINDS = frozenset({
    "track", "clip", "arrangement_clip", "note", "return", "device", "envelope",
})


@_atomic
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


@_atomic
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


@_atomic
def unlink_db_from_ableton(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    db_kind: str,
    db_id: str,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> bool:
    """Remove the (session, db_kind, db_id) link row. Returns True if a row
    was deleted, False if no link existed.

    Used by W18-B's strict reconciliation in
    :func:`hallucinote.sync.push.probe_and_link`: when the freshly-probed Live
    snapshot no longer contains an entity at the link's ``ableton_index``
    (typical repro: user deleted the linked Live track), the link is stale and
    must be removed before the next push so phases don't dispatch against a
    dead index.
    """
    if db_kind not in ABLETON_LINK_KINDS:
        raise ValueError(
            f"invalid db_kind {db_kind!r}; expected one of {sorted(ABLETON_LINK_KINDS)}"
        )
    row = conn.execute(
        """SELECT id, ableton_index FROM ableton_links
           WHERE session_id = ? AND db_kind = ? AND db_id = ?""",
        (session_id, db_kind, db_id),
    ).fetchone()
    if row is None:
        return False
    link_id = row["id"]
    ableton_index = row["ableton_index"]
    conn.execute("DELETE FROM ableton_links WHERE id = ?", (link_id,))
    song_row = conn.execute(
        "SELECT song_id FROM ableton_sessions WHERE id = ?", (session_id,)
    ).fetchone()
    # FK-GUARD: a clip link is reconciled away precisely when its clip row is GONE
    # from the DB — a `build.py --reset` rebuild or a Live-set swap that reuses the
    # session (the SYN-3C8K cascade in probe_and_link drops clip links whose clip
    # row no longer exists). Stamping the event's `clip_id` with that now-dangling
    # id violates `events.clip_id`'s FK to `clips(id)` on INSERT
    # (sqlite3.IntegrityError, which crashed probe-and-link mid-reconcile). Only
    # stamp `clip_id` when the clip row still exists; the unlinked id is preserved
    # in the event payload's `db_id` regardless, so no audit information is lost.
    clip_id_for_event: str | None = None
    if db_kind == "clip":
        clip_exists = conn.execute(
            "SELECT 1 FROM clips WHERE id = ?", (db_id,)
        ).fetchone() is not None
        if clip_exists:
            clip_id_for_event = db_id
    _emit(
        conn,
        E.ABLETON_LINK_REMOVED,
        {
            "link_id": link_id,
            "session_id": session_id,
            "db_kind": db_kind,
            "db_id": db_id,
            "ableton_index": ableton_index,
        },
        song_id=song_row["song_id"] if song_row else None,
        clip_id=clip_id_for_event,
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    return True


__all__ = [
    "ABLETON_LINK_KINDS",
    "create_ableton_session",
    "link_db_to_ableton",
    "reset_song_content",
    "unlink_db_from_ableton",
]
