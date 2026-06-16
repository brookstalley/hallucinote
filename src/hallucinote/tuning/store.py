"""The DB bridge for tuning state — cache + persist on write, deserialize on read.

This is the only place ``hallucinote.tuning`` touches the core DB, and the
direction is one-way: ``tuning`` imports the core mutator/query surface, **never
the reverse** (the isolation invariant — the core path imports nothing from
``tuning``). The mutator/query themselves stay tuning-agnostic: they move opaque
strings (the song-relative ``.ascl`` ref + the JSON blob). Serialization to/from
:class:`TuningData` lives here, on the bolt-on side.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from hallucinote.db import mutations as M
from hallucinote.db import queries as Q

from .cache import cache_ascl
from .model import TuningData


def persist_tuning(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    song_dir: str | Path,
    tuning: TuningData,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> str:
    """Cache ``tuning``'s ``.ascl`` under ``song_dir`` and record it on the song.

    Writes ``songs/<slug>/tunings/<name>.ascl`` (via :func:`cache_ascl`) and sets
    both ``songs.tuning_ref`` (the cached path) and ``songs.tuning_data`` (the
    derived blob) through the standard mutator, so the event falls out. Returns
    the song-relative ref.
    """
    ref = cache_ascl(song_dir, tuning)
    M.set_song_tuning(
        conn,
        song_id=song_id,
        tuning_ref=ref,
        tuning_data=tuning.to_blob(),
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    return ref


def load_song_tuning(conn: sqlite3.Connection, song_id: str) -> TuningData | None:
    """Read a song's persisted tuning blob back as :class:`TuningData`.

    Returns :data:`None` for a 12-TET song (no ``tuning_data``) or an unknown
    song — the mapper / authoring layer treats both the same.
    """
    row = Q.get_song_tuning(conn, song_id)
    if row is None or row["tuning_data"] is None:
        return None
    return TuningData.from_blob(row["tuning_data"])


__all__ = ["persist_tuning", "load_song_tuning"]
