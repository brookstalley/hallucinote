"""Read-side helpers. Pure SQL, no event emission, never mutate.

Anything that needs to write goes through `mutations`.

Ableton bindings live in `ableton_sessions` + `ableton_links` (a session-
scoped projection), not on core rows. Read them via `get_ableton_link` /
`get_ableton_links_for_session`; the sync layer joins them in.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any


def get_song_by_name(conn: sqlite3.Connection, name: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM songs WHERE name = ?", (name,)).fetchone()


def get_song(conn: sqlite3.Connection, song_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM songs WHERE id = ?", (song_id,)).fetchone()


def get_tracks_for_song(conn: sqlite3.Connection, song_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM tracks WHERE song_id = ? ORDER BY track_index",
        (song_id,),
    ).fetchall()


def get_track(conn: sqlite3.Connection, track_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM tracks WHERE id = ?", (track_id,)).fetchone()


def tracks_by_name(conn: sqlite3.Connection, song_id: str) -> dict[str, str]:
    """Map track name -> id for the song (master included; returns are not).

    The bookkeeping every song's build.py used to re-declare locally — a pure
    name->id lookup over ``get_tracks_for_song``, no musical decision (a ruler;
    see ``generator-altitude-policy.md``)."""
    return {row["name"]: row["id"] for row in get_tracks_for_song(conn, song_id)}


def returns_by_name(conn: sqlite3.Connection, song_id: str) -> dict[str, str]:
    """Map return-track name -> id for the song (the return-bus analog of
    ``tracks_by_name``)."""
    return {row["name"]: row["id"] for row in get_returns_for_song(conn, song_id)}


def get_clips_for_track(conn: sqlite3.Connection, track_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM clips WHERE track_id = ? ORDER BY slot",
        (track_id,),
    ).fetchall()


def get_clips_for_song(conn: sqlite3.Connection, song_id: str) -> list[sqlite3.Row]:
    """All clips on any track of `song_id`. Used by the push planner to
    enumerate the song's clip surface in one go (replaces a raw IN-subquery
    that lived in `plan_push_clips` pre-W20-E).

    Order: clip name then id (stable for the same DB read twice).
    """
    return conn.execute(
        """SELECT c.* FROM clips c
           JOIN tracks t ON t.id = c.track_id
           WHERE t.song_id = ?
           ORDER BY c.name, c.id""",
        (song_id,),
    ).fetchall()


def get_device_parent_chain(
    conn: sqlite3.Connection, device_id: str,
) -> sqlite3.Row | None:
    """Return the `device_chains` row owning `device_id`. Joins through
    `devices` so the caller gets ``parent_track_id`` / ``parent_return_id``
    / ``parent_rack_device_id`` in one query. None when the device is gone.

    Used by the envelope planner to walk a device-parameter envelope's
    routing surface (track vs return vs nested rack) without a raw SQL
    JOIN inside the planner.
    """
    return conn.execute(
        """SELECT dc.parent_track_id, dc.parent_return_id,
                  dc.parent_rack_device_id
           FROM devices d
           JOIN device_chains dc ON dc.id = d.chain_id
           WHERE d.id = ?""",
        (device_id,),
    ).fetchone()


def get_note(conn: sqlite3.Connection, note_id: str) -> sqlite3.Row | None:
    """Look up one notes row by id. None when the note has been deleted."""
    return conn.execute(
        "SELECT * FROM notes WHERE id = ?", (note_id,)
    ).fetchone()


def get_clip(conn: sqlite3.Connection, clip_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM clips WHERE id = ?", (clip_id,)).fetchone()


def get_notes_for_clip(conn: sqlite3.Connection, clip_id: str) -> list[dict[str, Any]]:
    """Return notes as dicts with tags deserialized. Sorted by start_beats."""
    rows = conn.execute(
        """SELECT id, pitch, start_beats, duration_beats, velocity, mute, tags_json
           FROM notes WHERE clip_id = ? ORDER BY start_beats, pitch""",
        (clip_id,),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "id": r["id"],
                "pitch": r["pitch"],
                "start_beats": r["start_beats"],
                "duration_beats": r["duration_beats"],
                "velocity": r["velocity"],
                "mute": r["mute"],
                "tags": json.loads(r["tags_json"]) if r["tags_json"] else [],
            }
        )
    return out


def get_arrangement_for_song(conn: sqlite3.Connection, song_id: str) -> list[sqlite3.Row]:
    """Return arrangement_clips rows joined with track + clip names. No Ableton
    info — sync-time bindings come from `ableton_links` via `get_ableton_link`.

    Ordering: `(track_id, start_bar, id)` — the trailing `id` tiebreaker
    makes the result deterministic when two placements share a position
    (which is rare but valid; see `get_arrangement_for_track`)."""
    return conn.execute(
        """SELECT a.*, t.name AS track_name, c.name AS clip_name
           FROM arrangement_clips a
           JOIN tracks t ON t.id = a.track_id
           JOIN clips  c ON c.id = a.clip_id
           WHERE a.song_id = ?
           ORDER BY a.track_id, a.start_bar, a.id""",
        (song_id,),
    ).fetchall()


def get_arrangement_for_track(conn: sqlite3.Connection, track_id: str) -> list[sqlite3.Row]:
    """Return arrangement_clips rows for one track, joined with clip name.

    Shape differs from `get_arrangement_for_song` in one way: no
    `track_name` column — callers that need this query already have the
    track row in hand, so the join would be redundant.

    Ordering: `(start_bar, id)`. The `id` tiebreaker makes the pull-side
    duplicate-position detection deterministic per-DB (it doesn't matter
    *which* row of a colliding pair the apply layer treats as the
    keeper, but the choice must be stable across runs to keep tests +
    debugging tractable)."""
    return conn.execute(
        """SELECT a.*, c.name AS clip_name
           FROM arrangement_clips a
           JOIN clips c ON c.id = a.clip_id
           WHERE a.track_id = ?
           ORDER BY a.start_bar, a.id""",
        (track_id,),
    ).fetchall()


def get_arrangement_placements_with_clip_length(
    conn: sqlite3.Connection, track_id: str
) -> list[sqlite3.Row]:
    """Arrangement placements on one track, joined with the source clip's
    ``length_beats`` for envelope-coverage resolution.

    The sync layer resolves envelope addressing against the SOURCE session
    clip's natural length (not the placement's trimmed ``end_bar``), so it
    needs ``clips.length_beats`` alongside each placement. Columns:
    ``(id, clip_id, start_bar, end_bar, length_beats)``, ordered
    ``(start_bar, id)`` for deterministic earliest-placement matching.
    Factors the inline ``arrangement_clips JOIN clips`` read out of the
    sync caller, consistent with the read-helper discipline.
    """
    return conn.execute(
        """SELECT a.id, a.clip_id, a.start_bar, a.end_bar, c.length_beats
           FROM arrangement_clips a
           JOIN clips c ON c.id = a.clip_id
           WHERE a.track_id = ?
           ORDER BY a.start_bar, a.id""",
        (track_id,),
    ).fetchall()


def count_arrangement_clips_for_clip(
    conn: sqlite3.Connection, clip_id: str
) -> int:
    """Count arrangement placements that reference one `clips` row.

    A `clips` row can back multiple arrangement-clip placements; deleting
    the clip cascades (`arrangement_clips.clip_id REFERENCES clips ON DELETE
    CASCADE`) and removes every placement. Callers that need the cascade to
    be observable (the session-clip pull deletes clips and must not silently
    drop arrangement placements) read this count *before* the delete so they
    can report what the cascade removed.
    """
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM arrangement_clips WHERE clip_id = ?",
        (clip_id,),
    ).fetchone()
    return int(row["n"])


def get_events_for_song(
    conn: sqlite3.Connection,
    song_id: str,
    *,
    limit: int = 200,
) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM events WHERE song_id = ? ORDER BY seq DESC LIMIT ?",
        (song_id, limit),
    ).fetchall()


def get_events_for_clip(
    conn: sqlite3.Connection,
    clip_id: str,
    *,
    limit: int = 200,
) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM events WHERE clip_id = ? ORDER BY seq DESC LIMIT ?",
        (clip_id, limit),
    ).fetchall()


# ---------------------------------------------------------------------------
# Score: sections, tempo map, time-signature map, cue points
# ---------------------------------------------------------------------------


def get_sections_for_song(conn: sqlite3.Connection, song_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM sections WHERE song_id = ? ORDER BY start_bar, end_bar",
        (song_id,),
    ).fetchall()


def get_tempo_map(conn: sqlite3.Connection, song_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM tempo_map WHERE song_id = ? ORDER BY start_bar",
        (song_id,),
    ).fetchall()


def get_time_signature_map(
    conn: sqlite3.Connection,
    song_id: str,
) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM time_signature_map WHERE song_id = ? ORDER BY start_bar",
        (song_id,),
    ).fetchall()


def get_cue_points(conn: sqlite3.Connection, song_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM cue_points WHERE song_id = ? ORDER BY position_bar",
        (song_id,),
    ).fetchall()


# ---------------------------------------------------------------------------
# Mix: returns + sends
# ---------------------------------------------------------------------------


def get_returns_for_song(conn: sqlite3.Connection, song_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM returns WHERE song_id = ? ORDER BY position",
        (song_id,),
    ).fetchall()


def get_return(conn: sqlite3.Connection, return_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM returns WHERE id = ?", (return_id,)
    ).fetchone()


def get_return_by_name(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    name: str,
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM returns WHERE song_id = ? AND name = ?",
        (song_id, name),
    ).fetchone()


def get_sends_for_track(
    conn: sqlite3.Connection,
    from_track_id: str,
) -> list[sqlite3.Row]:
    """Return all sends from a track. Joined with the return's position+name so
    callers can sort/display without a second query."""
    return conn.execute(
        """SELECT s.*, r.name AS return_name, r.position AS return_position
           FROM sends s
           JOIN returns r ON r.id = s.to_return_id
           WHERE s.from_track_id = ?
           ORDER BY r.position""",
        (from_track_id,),
    ).fetchall()


def get_sends_for_song(conn: sqlite3.Connection, song_id: str) -> list[sqlite3.Row]:
    """Return every send in the song. Joined with track + return identity so the
    caller has the full (from, to, level) matrix without N+1 lookups."""
    return conn.execute(
        """SELECT s.from_track_id, s.to_return_id, s.level, s.intended_rt60_s,
                  t.track_index AS from_track_index, t.name AS from_track_name,
                  r.position AS return_position, r.name AS return_name
           FROM sends s
           JOIN tracks  t ON t.id = s.from_track_id
           JOIN returns r ON r.id = s.to_return_id
           WHERE t.song_id = ?
           ORDER BY t.track_index, r.position""",
        (song_id,),
    ).fetchall()


def get_reverb_send_intents_for_song(
    conn: sqlite3.Connection, song_id: str
) -> list[sqlite3.Row]:
    """Return sends carrying a non-NULL ``intended_rt60_s`` declaration.

    Used by the audio-analysis handler to assemble ``DeclaredReverbSend``
    records from DB intent without forcing the MCP caller to enumerate
    them. NULL-intent sends are filtered server-side — callers get an
    already-pruned list.

    The projection includes ``track_index`` + ``return_position`` because
    the analysis handler translates DB UUIDs into capture-side surface
    IDs (``track:N`` / ``return:N`` — see
    ``analyzer.setup.track_id_for_surface``) before passing
    ``DeclaredReverbSend`` records to ``analyze_mix``.
    """
    return conn.execute(
        """SELECT s.from_track_id, s.to_return_id, s.intended_rt60_s,
                  t.track_index AS from_track_index, t.name AS from_track_name,
                  r.position AS return_position, r.name AS return_name
           FROM sends s
           JOIN tracks  t ON t.id = s.from_track_id
           JOIN returns r ON r.id = s.to_return_id
           WHERE t.song_id = ? AND s.intended_rt60_s IS NOT NULL
           ORDER BY t.track_index, r.position""",
        (song_id,),
    ).fetchall()


# ---------------------------------------------------------------------------
# Mix: device chains, devices, parameters
# ---------------------------------------------------------------------------


def get_device_chains_for_track(
    conn: sqlite3.Connection,
    track_id: str,
) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT * FROM device_chains
           WHERE parent_track_id = ? ORDER BY position""",
        (track_id,),
    ).fetchall()


def get_device_chains_for_return(
    conn: sqlite3.Connection,
    return_id: str,
) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT * FROM device_chains
           WHERE parent_return_id = ? ORDER BY position""",
        (return_id,),
    ).fetchall()


def get_device_chain(
    conn: sqlite3.Connection,
    chain_id: str,
) -> sqlite3.Row | None:
    """One device chain by id. Carries the polymorphic parent (parent_track_id
    / parent_return_id / parent_rack_device_id) — used to resolve a device back
    to the surface (track or return) it sits on, e.g. for the audio analyzer's
    device-parameter automation verification."""
    return conn.execute(
        "SELECT * FROM device_chains WHERE id = ?", (chain_id,)
    ).fetchone()


def get_device_chains_for_rack_device(
    conn: sqlite3.Connection,
    device_id: str,
) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT * FROM device_chains
           WHERE parent_rack_device_id = ? ORDER BY position""",
        (device_id,),
    ).fetchall()


def get_devices_for_chain(
    conn: sqlite3.Connection,
    chain_id: str,
) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT * FROM devices
           WHERE chain_id = ? ORDER BY position""",
        (chain_id,),
    ).fetchall()


def get_devices_for_track(
    conn: sqlite3.Connection,
    track_id: str,
) -> list[sqlite3.Row]:
    """Convenience join across (top-level) chain → devices for a track. Does
    NOT recurse into nested rack chains — those need a separate walk via
    `get_device_chains_for_rack_device`.
    """
    return conn.execute(
        """SELECT d.*, dc.position AS chain_position
           FROM devices d
           JOIN device_chains dc ON dc.id = d.chain_id
           WHERE dc.parent_track_id = ?
           ORDER BY dc.position, d.position""",
        (track_id,),
    ).fetchall()


def get_devices_for_return(
    conn: sqlite3.Connection,
    return_id: str,
) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT d.*, dc.position AS chain_position
           FROM devices d
           JOIN device_chains dc ON dc.id = d.chain_id
           WHERE dc.parent_return_id = ?
           ORDER BY dc.position, d.position""",
        (return_id,),
    ).fetchall()


def get_device(conn: sqlite3.Connection, device_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM devices WHERE id = ?", (device_id,)
    ).fetchone()


def get_device_parameters(
    conn: sqlite3.Connection,
    device_id: str,
) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT * FROM device_parameters
           WHERE device_id = ? ORDER BY name""",
        (device_id,),
    ).fetchall()


def get_drum_pad_mappings(
    conn: sqlite3.Connection,
    device_id: str,
) -> list[sqlite3.Row]:
    """Return Drum Rack pad mappings for a device, ordered by midi_note ASC.

    Each row: ``{id, device_id, chain_name, midi_note}``. Empty list when
    no mappings have been captured for this device yet (caller should
    fall through to `Kit.gm_default()` per `hallucinote.generators.kit`).
    """
    return conn.execute(
        """SELECT * FROM drum_pad_mappings
           WHERE device_id = ? ORDER BY midi_note""",
        (device_id,),
    ).fetchall()


def get_linked_drum_racks_for_session(
    conn: sqlite3.Connection,
    session_id: str,
) -> list[sqlite3.Row]:
    """Return every Drum Rack device in this session's song that has
    a live binding (track + device link rows), with the addressing the
    MCP needs to probe it.

    Arc 4 / D4: filters on ``d.kind = 'Drum Rack'`` (browser display
    name), which is what pull writes from ``device.class_display_name``.
    Pre-D4 the column held the internal class ``'DrumGroupDevice'``.

    Each row: ``{device_id, display_name, parent_kind, parent_ableton_index,
    device_ableton_index, device_position}``.

    Used by ``push_execute``'s post-devices-phase pad-probe walker — for
    every linked Drum Rack the walker dispatches
    ``ableton_device(action='pad_info', track_index=parent_ableton_index,
    device_index=device_ableton_index)`` then persists the result via
    ``M.replace_drum_pad_mappings``. The single SQL keeps the chain
    traversal cohesive: a device is "fully linked" only when both its
    parent (track or return) AND the device itself have ``ableton_links``
    rows for this session.

    Returns an empty list when nothing matches (no Drum Racks in the song,
    or no device links written yet — first-time push state before phase 7
    completes).
    """
    return conn.execute(
        """
        SELECT
            d.id           AS device_id,
            d.display_name AS display_name,
            d.position     AS device_position,
            CASE
                WHEN dc.parent_track_id  IS NOT NULL THEN 'track'
                WHEN dc.parent_return_id IS NOT NULL THEN 'return'
            END AS parent_kind,
            COALESCE(
                (SELECT al.ableton_index FROM ableton_links al
                  WHERE al.session_id = :session_id
                    AND al.db_kind = 'track'
                    AND al.db_id  = dc.parent_track_id),
                (SELECT al.ableton_index FROM ableton_links al
                  WHERE al.session_id = :session_id
                    AND al.db_kind = 'return'
                    AND al.db_id  = dc.parent_return_id)
            ) AS parent_ableton_index,
            (SELECT al.ableton_index FROM ableton_links al
              WHERE al.session_id = :session_id
                AND al.db_kind = 'device'
                AND al.db_id  = d.id) AS device_ableton_index
        FROM devices d
        JOIN device_chains dc ON dc.id = d.chain_id
        WHERE d.kind = 'Drum Rack'
          AND (dc.parent_track_id IS NOT NULL OR dc.parent_return_id IS NOT NULL)
        ORDER BY d.position
        """,
        {"session_id": session_id},
    ).fetchall()


# ---------------------------------------------------------------------------
# Mix: automation envelopes + breakpoints
# ---------------------------------------------------------------------------


def get_envelope(conn: sqlite3.Connection, envelope_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM envelopes WHERE id = ?", (envelope_id,)
    ).fetchone()


def get_envelopes_for_song(
    conn: sqlite3.Connection, song_id: str,
) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT * FROM envelopes WHERE song_id = ?
           ORDER BY target_kind, id""",
        (song_id,),
    ).fetchall()


def get_envelopes_for_clip(
    conn: sqlite3.Connection, clip_id: str,
) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT * FROM envelopes WHERE target_clip_id = ?
           ORDER BY target_kind, parameter_path""",
        (clip_id,),
    ).fetchall()


def get_envelopes_for_note(
    conn: sqlite3.Connection, note_id: str,
) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT * FROM envelopes WHERE target_note_id = ?
           ORDER BY parameter_path""",
        (note_id,),
    ).fetchall()


def get_envelopes_for_device(
    conn: sqlite3.Connection, device_id: str,
) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT * FROM envelopes WHERE target_device_id = ?
           ORDER BY parameter_path""",
        (device_id,),
    ).fetchall()


def get_envelopes_for_track(
    conn: sqlite3.Connection, track_id: str,
) -> list[sqlite3.Row]:
    """Mixer + send envelopes anchored on this track (mixer_volume, mixer_pan,
    send_level). Device-parameter envelopes for this track's devices are NOT
    included — query via `get_envelopes_for_device` per device."""
    return conn.execute(
        """SELECT * FROM envelopes WHERE target_track_id = ?
           ORDER BY target_kind, target_send_return_id""",
        (track_id,),
    ).fetchall()


def get_breakpoints(
    conn: sqlite3.Connection, envelope_id: str,
) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT * FROM automation_breakpoints
           WHERE envelope_id = ? ORDER BY time_beats, id""",
        (envelope_id,),
    ).fetchall()


# ---------------------------------------------------------------------------
# Ableton projection
# ---------------------------------------------------------------------------


def get_ableton_session(
    conn: sqlite3.Connection,
    session_id: str,
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM ableton_sessions WHERE id = ?", (session_id,)
    ).fetchone()


def list_ableton_sessions(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Sessions newest-first (created_at, rowid tiebreak). WFL-7Q2N: the
    auto-discovery resolver leans on this ordering — index 0 is "most
    recent"."""
    return conn.execute(
        "SELECT * FROM ableton_sessions ORDER BY created_at DESC, rowid DESC"
    ).fetchall()


def get_ableton_link(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    db_kind: str,
    db_id: str,
) -> int | None:
    """Return the ableton_index for (session, db_kind, db_id), or None."""
    row = conn.execute(
        """SELECT ableton_index FROM ableton_links
           WHERE session_id = ? AND db_kind = ? AND db_id = ?""",
        (session_id, db_kind, db_id),
    ).fetchone()
    return row["ableton_index"] if row else None


def get_ableton_links_for_session(
    conn: sqlite3.Connection,
    session_id: str,
) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM ableton_links WHERE session_id = ?",
        (session_id,),
    ).fetchall()


# ---------------------------------------------------------------------------
# Markdown corpus projection (song-context retrieval surface)
# ---------------------------------------------------------------------------


def get_markdown_ref(
    conn: sqlite3.Connection, path: str
) -> sqlite3.Row | None:
    """Look up one markdown_refs row by path. Returns None if not indexed."""
    return conn.execute(
        "SELECT * FROM markdown_refs WHERE path = ?", (path,)
    ).fetchone()


def get_request(
    conn: sqlite3.Connection, request_id: str
) -> sqlite3.Row | None:
    """Look up one requests row by id. Returns None if not found."""
    return conn.execute(
        "SELECT * FROM requests WHERE id = ?", (request_id,)
    ).fetchone()


# ---------------------------------------------------------------------------
# W23-A: provenance read surface
# ---------------------------------------------------------------------------
#
# These queries let the agent answer "what did I do last time on this song?"
# without scanning the events table by hand. All four are read-only over
# the existing requests + events tables — no schema change. The intent
# vocabulary matches REQUEST_KINDS in mutations.py: 'compose', 'push',
# 'pull', 'capture', 'analyze', 'mutate'.


def list_requests_for_song(
    conn: sqlite3.Connection,
    song_id: str,
    *,
    kind: str | None = None,
    limit: int = 50,
) -> list[sqlite3.Row]:
    """List recent requests on `song_id`, most-recent first.

    `kind` filters to one cycle type (e.g. ``'push'`` to see only push
    cycles); leave None to see every cycle. `limit` defaults to 50 — the
    last ~5 days of activity for a heavily-worked song. The list shape
    (request id, actor, intent, kind, outcome, duration_ms, ts) is what
    the agent needs to summarise "what's been happening here lately."
    """
    # `ts` is millisecond-precision; two rapid calls can tie. Secondary
    # order by `rowid DESC` is SQLite's stable insertion-order tiebreaker
    # so "latest" stays deterministic within a tie.
    if kind is not None:
        return conn.execute(
            """SELECT * FROM requests
               WHERE song_id = ? AND kind = ?
               ORDER BY ts DESC, rowid DESC LIMIT ?""",
            (song_id, kind, limit),
        ).fetchall()
    return conn.execute(
        """SELECT * FROM requests WHERE song_id = ?
           ORDER BY ts DESC, rowid DESC LIMIT ?""",
        (song_id, limit),
    ).fetchall()


def get_latest_request_for_song(
    conn: sqlite3.Connection,
    song_id: str,
    *,
    kind: str | None = None,
) -> sqlite3.Row | None:
    """The single most-recent request on `song_id`, optionally filtered by
    kind. Returns None if no matching request exists.

    Common use: "what was the last push for this song?" answers via
    ``get_latest_request_for_song(conn, song_id, kind='push')``.
    """
    rows = list_requests_for_song(conn, song_id, kind=kind, limit=1)
    return rows[0] if rows else None


def get_events_for_request(
    conn: sqlite3.Connection,
    request_id: str,
    *,
    limit: int = 500,
) -> list[sqlite3.Row]:
    """Every event threaded back to one request, in seq order (oldest first).

    Use to drill into "what did this push actually do?": the agent reads
    the request from :func:`get_request`, then pulls its events here.
    Default limit of 500 covers a heavy compose round (W12-A's converger
    can emit hundreds of touched-rows events); raise the limit for an
    audit dump.
    """
    return conn.execute(
        """SELECT * FROM events WHERE request_id = ?
           ORDER BY seq ASC LIMIT ?""",
        (request_id, limit),
    ).fetchall()


def get_request_event_summary(
    conn: sqlite3.Connection,
    request_id: str,
) -> dict[str, int]:
    """``{event_kind: count}`` for one request's event stream.

    The agent uses this as a one-look "what did this request touch?"
    summary — e.g. ``{'track_created': 8, 'clip_created': 24,
    'arrangement_clip_added': 24, 'request_created': 1, 'request_closed': 1}``
    tells you a full push of an 8-track song. Cheaper than reading every
    event for the common "how big was this cycle" question.
    """
    rows = conn.execute(
        """SELECT kind, COUNT(*) AS n FROM events
           WHERE request_id = ? GROUP BY kind""",
        (request_id,),
    ).fetchall()
    return {r["kind"]: r["n"] for r in rows}


def find_related_decisions(
    conn: sqlite3.Connection,
    song_id: str,
    *,
    keywords: list[str],
    limit: int = 20,
) -> list[sqlite3.Row]:
    """Search a song's compose-time audit log for prior decisions matching
    one or more keywords.

    Two request fields are scanned, song-scoped:
      - ``requests.prompt_text`` — verbatim seed prompt for compose / push /
        pull / mutate cycles.
      - ``requests.metadata_json`` — bag carrying the convention key
        ``decision_rationale`` (the LLM's reasoning at compose time).

    Multi-keyword semantics: AND across keywords — every keyword must appear
    (case-insensitive LIKE) in the row's searchable text. Single-keyword
    callers pass a one-element list. Empty ``keywords`` returns ``[]`` (no
    broad-dump path; ``list_requests_for_song`` is the broad-listing surface).

    Each row carries a synthetic ``sort_ts`` column (aliasing ``requests.ts``)
    so callers rely on most-recent-first ordering without coupling to the
    underlying column name.

    Durable composer intent + decision rationale live as git-tracked markdown
    (``songs/<slug>/decisions/`` + ``annotations/``), surfaced through the
    ``markdown_refs`` corpus and ``/song-context``; this query is the
    audit-log half — what the LLM was *asked* to do, and the reasoning it
    recorded at the time.

    Out of scope: cross-song search; multi-user attribution; semantic /
    embedding search; track / bar scope filters.
    """
    if not keywords:
        return []
    patterns = [f"%{k}%" for k in keywords]
    # AND-of-keywords: every keyword must appear in the row's searchable text.
    match_sql = " AND ".join(
        "(prompt_text LIKE ? OR metadata_json LIKE ?)" for _ in patterns
    )
    params: list[Any] = [song_id]
    for pat in patterns:
        params.extend((pat, pat))
    sql = f"""
        SELECT id,
               ts AS sort_ts,
               actor,
               kind,
               intent,
               prompt_text,
               metadata_json
          FROM requests
         WHERE song_id = ? AND {match_sql}
        ORDER BY sort_ts DESC
        LIMIT ?
    """
    params.append(limit)
    return conn.execute(sql, params).fetchall()


def find_markdown_refs_for_request(
    conn: sqlite3.Connection, request_id: str
) -> list[sqlite3.Row]:
    """Cross-reference query: markdown refs recorded during a specific request.

    Joins `events` (kind=MARKDOWN_REF_RECORDED, threaded by request_id) to
    `markdown_refs` on path. Returns the markdown_refs row plus the event's
    `ts` so callers see when each ref was recorded relative to the cycle.
    Tombstoned refs are included — the historical query stays valid even
    after a file is removed.
    """
    return conn.execute(
        """SELECT m.*, e.ts AS recorded_at
           FROM events e
           JOIN markdown_refs m
             ON m.path = json_extract(e.payload_json, '$.path')
           WHERE e.request_id = ?
             AND e.kind = 'markdown_ref_recorded'
           ORDER BY e.seq""",
        (request_id,),
    ).fetchall()


def find_markdown_refs(
    conn: sqlite3.Connection,
    *,
    song_id: str | None = None,
    kind: str | None = None,
    scope: str | None = None,
    track_id: str | None = None,
    tags: list[str] | None = None,
    fulltext: str | None = None,
    bars: tuple[float, float] | None = None,
    include_tombstoned: bool = False,
    limit: int = 50,
) -> list[sqlite3.Row]:
    """Query the markdown corpus projection.

    All filter args are AND-composed; `tags` is a contains-any match. When
    `fulltext` is set, results join to `markdown_refs_fts` and rank by
    FTS5 relevance (returns include a `snippet` column with `<<...>>`
    highlights). Without `fulltext`, results are ordered by frontmatter_date
    DESC (most recent decisions first), tiebreaking on path.

    `bars=(q_start, q_end)` returns rows whose `bars_json` overlaps the
    given range — point rows `[a]` match iff `q_start <= a <= q_end`;
    range rows `[a, b]` match iff `max(a, q_start) < min(b, q_end)`.

    Tombstoned rows (file no longer on disk) are excluded by default.
    """
    where: list[str] = []
    args: list[Any] = []

    if not include_tombstoned:
        where.append("m.tombstoned_at IS NULL")
    if song_id:
        where.append("m.song_id = ?")
        args.append(song_id)
    if kind:
        where.append("m.kind = ?")
        args.append(kind)
    if scope:
        where.append("m.scope = ?")
        args.append(scope)
    if track_id:
        where.append("m.track_id = ?")
        args.append(track_id)
    if tags:
        placeholders = ",".join("?" for _ in tags)
        where.append(
            f"EXISTS (SELECT 1 FROM json_each(m.tags_json) "
            f"WHERE value IN ({placeholders}))"
        )
        args.extend(tags)
    if bars is not None:
        q_start, q_end = bars
        where.append(
            "m.bars_json IS NOT NULL AND ("
            "(json_array_length(m.bars_json) = 1 "
            " AND json_extract(m.bars_json, '$[0]') >= ? "
            " AND json_extract(m.bars_json, '$[0]') <= ?) "
            "OR "
            "(json_array_length(m.bars_json) = 2 "
            " AND json_extract(m.bars_json, '$[0]') < ? "
            " AND json_extract(m.bars_json, '$[1]') > ?))"
        )
        args.extend([q_start, q_end, q_end, q_start])

    where_sql = (" WHERE " + " AND ".join(where)) if where else ""

    if fulltext:
        sql = (
            "SELECT m.*, "
            "snippet(markdown_refs_fts, 0, '<<', '>>', '...', 32) AS snippet "
            "FROM markdown_refs_fts f "
            "JOIN markdown_refs m ON m.path = f.path "
            "WHERE markdown_refs_fts MATCH ?"
            + ("" if not where else " AND " + " AND ".join(where))
            + " ORDER BY rank LIMIT ?"
        )
        return conn.execute(sql, [fulltext, *args, limit]).fetchall()

    sql = (
        "SELECT m.* FROM markdown_refs m"
        f"{where_sql} "
        "ORDER BY COALESCE(m.frontmatter_date, '0000-01-01') DESC, m.path "
        "LIMIT ?"
    )
    return conn.execute(sql, [*args, limit]).fetchall()


# ---------------------------------------------------------------------------
# Ableton projection (continued)
# ---------------------------------------------------------------------------


def get_db_id_by_ableton_index(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    db_kind: str,
    ableton_index: int,
) -> str | None:
    """Reverse of `get_ableton_link`: given Ableton coordinates, return the db_id.

    Used by pull-side sync to map an `(track_index, ...)` from an MCP probe back
    onto the DB row whose mixer state we'll diff against. Returns None for
    unlinked Ableton rows — pull treats those as "not ours, skip with warn."
    """
    row = conn.execute(
        """SELECT db_id FROM ableton_links
           WHERE session_id = ? AND db_kind = ? AND ableton_index = ?""",
        (session_id, db_kind, ableton_index),
    ).fetchone()
    return row["db_id"] if row else None
