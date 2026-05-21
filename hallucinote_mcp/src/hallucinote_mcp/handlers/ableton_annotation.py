"""Handlers for ``ableton_annotation`` — agent-facing annotation surface
wrapping the W8-C mutators/queries.

Annotations capture composer-intent ("verse is sad," "don't sidechain the
bass on the bridge — let it bloom") with three scoping levels: song,
time-range, and track. W8-C shipped the DB layer (table + mutators +
queries + events); this module exposes it through MCP so compose-time
agents can read AND write annotations during a session, instead of the
table being storage without affordance.

DB resolution: each call accepts a ``song_slug`` and resolves the
per-song SQLite file via ``hallucinote.db.connection.resolve_db_path``.
Inside that DB, the song row is looked up by ``name = slug`` (mirrors
the convention used by ``build_session`` and ``replay_capture``). If
either the file or the row is missing, the handler returns a teaching
error rather than silently writing to the wrong place.

Track resolution: ``track_index`` arrives 1-based per MCP convention and
is resolved to ``track_id`` via the ``tracks.track_index`` column. Bar
positions arrive as floats per the DB schema (start_bar / end_bar).

The handler takes a ``LiveContext`` parameter to match the dispatcher's
universal handler shape but does NOT use it — annotations are pure DB,
no Live API touches. The dispatcher will marshal these calls onto Live's
main thread (the default ``runs_on_worker=False`` path), which adds a
trivial overhead (sub-ms) and keeps the threading model consistent with
the other ten tools. Live-blocking time is bounded by the SQLite call,
which is microseconds for these operations.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from hallucinote.db import mutations as M
from hallucinote.db import queries as Q
from hallucinote.db.connection import init_db, resolve_db_path

from ..dispatcher import LiveContext


# Public for tests: lets the unit suite inject a temp DB path without
# spinning up the full songs/<slug>/ layout. Default behavior delegates
# to resolve_db_path with the runtime git-branch probe.
def _resolve_song_db(song_slug: str) -> Path:
    return resolve_db_path(song_slug)


def _open_song_conn(song_slug: str) -> sqlite3.Connection:
    """Open the per-song SQLite file. Raises FileNotFoundError if it
    doesn't exist — the handler translates that into a teaching error.

    Uses ``init_db`` (not raw ``sqlite3.connect``) so the
    ``_ensure_added_columns`` idempotent migration fires on every open.
    Without it, an annotations call against a stale DB (missing W8-C's
    annotations table or Arc-2 columns) would raise inside the mutator
    with a sqlite error instead of getting upgraded silently.
    """
    path = _resolve_song_db(song_slug)
    if not path.exists():
        raise FileNotFoundError(str(path))
    return init_db(path)


def _resolve_song_id(conn: sqlite3.Connection, song_slug: str) -> str | None:
    row = Q.get_song_by_name(conn, song_slug)
    return row["id"] if row is not None else None


def _resolve_track_id(
    conn: sqlite3.Connection, song_id: str, track_index: int
) -> str | None:
    """1-based track_index → track_id; None if no track at that position."""
    for row in Q.get_tracks_for_song(conn, song_id):
        if int(row["track_index"]) == int(track_index):
            return row["id"]
    return None


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "song_id": row["song_id"],
        "track_id": row["track_id"],
        "start_bar": row["start_bar"],
        "end_bar": row["end_bar"],
        "kind": row["kind"],
        "body": row["body"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _teach_song_not_found(song_slug: str) -> dict[str, Any]:
    return {
        "error": (
            f"no song named {song_slug!r} found — looked for "
            f"songs/{song_slug}/{song_slug}-<branch>.db and within that DB "
            f"for a row in `songs` where name={song_slug!r}. Has the song "
            f"been built yet? `python3 songs/{song_slug}/build.py --reset` "
            f"creates the DB and song row."
        ),
    }


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------


def add_handler(
    _context: LiveContext,
    *,
    song_slug: str,
    kind: str,
    body: str,
    start_bar: float | None = None,
    end_bar: float | None = None,
    track_index: int | None = None,
) -> dict[str, Any]:
    """Wrap ``M.add_annotation``. Returns the new annotation as a dict.

    ``track_index`` is 1-based; resolved to ``track_id`` here so MCP
    callers don't need to know the internal UUID. If both ``track_index``
    and ``start_bar`` are set, the annotation is track+time-scoped
    (overlap-active when in the bar range AND on the named track).
    """
    try:
        conn = _open_song_conn(song_slug)
    except FileNotFoundError:
        return _teach_song_not_found(song_slug)
    try:
        song_id = _resolve_song_id(conn, song_slug)
        if song_id is None:
            return _teach_song_not_found(song_slug)
        track_id: str | None = None
        if track_index is not None:
            track_id = _resolve_track_id(conn, song_id, track_index)
            if track_id is None:
                return {
                    "error": (
                        f"no track at index {track_index} in song "
                        f"{song_slug!r}; use ableton_track(action='list') to "
                        f"see current tracks."
                    )
                }
        annotation_id = M.add_annotation(
            conn,
            song_id=song_id,
            kind=kind,
            body=body,
            track_id=track_id,
            start_bar=start_bar,
            end_bar=end_bar,
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM annotations WHERE id = ?", (annotation_id,)
        ).fetchone()
        return _row_to_dict(row)
    finally:
        conn.close()


def list_handler(
    _context: LiveContext,
    *,
    song_slug: str,
    kind: str | None = None,
) -> dict[str, Any]:
    """List all annotations on a song, optionally filtered by ``kind``.

    Returns ``{"annotations": [...]}``. Ordered per Q.get_annotations_for_song
    (song-scoped first, then time-scoped by start_bar, then created_at).
    """
    try:
        conn = _open_song_conn(song_slug)
    except FileNotFoundError:
        return _teach_song_not_found(song_slug)
    try:
        song_id = _resolve_song_id(conn, song_slug)
        if song_id is None:
            return _teach_song_not_found(song_slug)
        rows = Q.get_annotations_for_song(conn, song_id, kind=kind)
        return {"annotations": [_row_to_dict(r) for r in rows]}
    finally:
        conn.close()


def get_at_bar_handler(
    _context: LiveContext,
    *,
    song_slug: str,
    bar: float,
) -> dict[str, Any]:
    """All annotations active at a given bar (song-scoped always active,
    time-scoped scoped to [start_bar, end_bar) or [start_bar, ∞) if open).
    """
    try:
        conn = _open_song_conn(song_slug)
    except FileNotFoundError:
        return _teach_song_not_found(song_slug)
    try:
        song_id = _resolve_song_id(conn, song_slug)
        if song_id is None:
            return _teach_song_not_found(song_slug)
        rows = Q.get_annotations_at_bar(conn, song_id, bar)
        return {"annotations": [_row_to_dict(r) for r in rows]}
    finally:
        conn.close()


def update_handler(
    _context: LiveContext,
    *,
    song_slug: str,
    annotation_id: str,
    body: str | None = None,
    kind: str | None = None,
    start_bar: float | None = None,
    end_bar: float | None = None,
) -> dict[str, Any]:
    """Update one annotation in-place. Only the fields passed are touched."""
    try:
        conn = _open_song_conn(song_slug)
    except FileNotFoundError:
        return _teach_song_not_found(song_slug)
    try:
        row = conn.execute(
            "SELECT * FROM annotations WHERE id = ?", (annotation_id,)
        ).fetchone()
        if row is None:
            return {
                "error": (
                    f"no annotation with id {annotation_id!r} in song "
                    f"{song_slug!r}; use action='list' to see ids."
                )
            }
        kwargs: dict[str, Any] = {}
        if body is not None:
            kwargs["body"] = body
        if kind is not None:
            kwargs["kind"] = kind
        if start_bar is not None:
            kwargs["start_bar"] = start_bar
        if end_bar is not None:
            kwargs["end_bar"] = end_bar
        if not kwargs:
            return {
                "error": (
                    "update requires at least one of body / kind / start_bar / "
                    "end_bar to be set."
                )
            }
        M.update_annotation(conn, annotation_id=annotation_id, **kwargs)
        conn.commit()
        updated = conn.execute(
            "SELECT * FROM annotations WHERE id = ?", (annotation_id,)
        ).fetchone()
        return _row_to_dict(updated)
    finally:
        conn.close()


def delete_handler(
    _context: LiveContext,
    *,
    song_slug: str,
    annotation_id: str,
) -> dict[str, Any]:
    """Delete one annotation. Idempotent: deleting a missing id is a no-op."""
    try:
        conn = _open_song_conn(song_slug)
    except FileNotFoundError:
        return _teach_song_not_found(song_slug)
    try:
        M.delete_annotation(conn, annotation_id=annotation_id)
        conn.commit()
        return {"annotation_id": annotation_id, "deleted": True}
    finally:
        conn.close()
