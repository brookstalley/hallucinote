"""hallucinote.authoring — shared song-build plumbing (rulers, not stamps).

The bookkeeping every song's ``build.py`` used to duplicate verbatim: placing a
section's clips on the arrangement, and the open-DB → (optional soft reset) →
``build_session`` → close lifecycle. None of it makes a musical decision — it
removes repetitive wiring so a song's ``build.py`` holds only the composition.
This is the *ruler* side of `generator-altitude-policy.md`: bookkeeping belongs
shared in the library; only the musical decisions stay song-local.
"""
from __future__ import annotations

import sqlite3
from typing import Callable, Mapping

from hallucinote.db import init_db, mutations as M, queries as Q


def arrange_section(
    conn: sqlite3.Connection,
    song_id: str,
    tracks: Mapping[str, str],
    clips: Mapping[str, str],
    *,
    start_bar: float,
    end_bar: float,
) -> None:
    """Place every clip in ``clips`` (track-name → clip-id) on its track between
    ``start_bar`` and ``end_bar``. ``tracks`` is a name→id map (``Q.tracks_by_name``).
    """
    for track_name, clip_id in clips.items():
        M.add_arrangement_clip(
            conn,
            song_id=song_id,
            track_id=tracks[track_name],
            clip_id=clip_id,
            start_bar=start_bar,
            end_bar=end_bar,
        )


def run_build(
    db_path: str,
    song_name: str,
    compose: Callable[[sqlite3.Connection], str],
    *,
    reset: bool = False,
    owner: str = "build.py",
) -> str:
    """The standard song-build harness — the lifecycle every ``build()`` repeats.

    Opens the DB, optionally soft-resets the song's build-owned content, runs
    ``compose(conn)`` inside a ``build_session``, and closes the connection.
    ``compose`` does the song-specific authoring and returns the song_id; that
    value is returned here.

    Soft reset (``reset=True``, W18-C) wipes rebuild-by-build.py content (clips,
    notes, arrangement, sections, tempo/meter maps, cue points, envelopes) but
    preserves the mix layout (tracks, returns, devices, sends) AND the Ableton
    projection (``ableton_sessions`` + ``ableton_links``). For a full clean slate,
    delete the DB file directly. Re-running with no source change is a no-op
    (state-converger; W12-A) — the same idempotency the per-song harness had.
    """
    conn = init_db(db_path)
    try:
        if reset:
            song = Q.get_song_by_name(conn, song_name)
            if song is not None:
                M.reset_song_content(conn, song_id=song["id"])
        with M.build_session(conn, song_name=song_name, owner=owner):
            return compose(conn)
    finally:
        conn.close()
