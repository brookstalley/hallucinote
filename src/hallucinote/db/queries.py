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


def get_clips_for_track(conn: sqlite3.Connection, track_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM clips WHERE track_id = ? ORDER BY slot",
        (track_id,),
    ).fetchall()


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
    info — sync-time bindings come from `ableton_links` via `get_ableton_link`."""
    return conn.execute(
        """SELECT a.*, t.name AS track_name, c.name AS clip_name
           FROM arrangement_clips a
           JOIN tracks t ON t.id = a.track_id
           JOIN clips  c ON c.id = a.clip_id
           WHERE a.song_id = ?
           ORDER BY a.track_id, a.start_bar""",
        (song_id,),
    ).fetchall()


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
        """SELECT s.from_track_id, s.to_return_id, s.level,
                  t.track_index AS from_track_index, t.name AS from_track_name,
                  r.position AS return_position, r.name AS return_name
           FROM sends s
           JOIN tracks  t ON t.id = s.from_track_id
           JOIN returns r ON r.id = s.to_return_id
           WHERE t.song_id = ?
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
