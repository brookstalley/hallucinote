"""Arrangement layout: arrangement clips + cue points (markers)."""
from __future__ import annotations

import sqlite3

from ._core import (
    E,
    MutatorResult,
    _atomic,
    _emit,
    _record_touch_if_session,
    _require_bar_floor,
    _resolve_actor_and_request,
    _touch_song,
    _uuid,
)


# Which bar ruler a position was authored against (#496).
#
# `uniform` — the position came from accumulating whole bars against ONE
# `beats_per_bar`, which is what `hallucinote.arrangement` does; it never reads
# the song's `time_signature_map`. `map` — the position was authored directly
# against the map, which is how push resolves every bar position.
#
# The two agree on every bar before the first meter change and part after it.
# Recording which one wrote a row is the whole point: without it, a deliberate
# 7/4 song and a `build.py` that did uniform bar math past a meter change are
# indistinguishable at push time, so the divergence alert had to fire on both.
#
# `map` is the DEFAULT so a writer that has never heard of this column is
# correct by construction; the one component doing uniform math opts out.
BAR_RULERS: frozenset[str] = frozenset({"uniform", "map"})
DEFAULT_BAR_RULER = "map"


def _validate_bar_ruler(bar_ruler: str) -> str:
    """Reject an unknown ruler at the mutator rather than at the CHECK.

    The schema CHECK would also refuse it, but with SQLite's message, naming
    neither the argument nor the two legal values.
    """
    if bar_ruler not in BAR_RULERS:
        raise ValueError(
            f"bar_ruler must be one of {sorted(BAR_RULERS)}, got {bar_ruler!r}. "
            "'uniform' means the position was accumulated against a single "
            "beats_per_bar; 'map' means it was authored against the song's "
            "time_signature_map."
        )
    return bar_ruler


# ---------------------------------------------------------------------------
# Arrangement clips
# ---------------------------------------------------------------------------


@_atomic
def add_arrangement_clip(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    track_id: str,
    clip_id: str,
    start_bar: float,
    end_bar: float,
    bar_ruler: str = DEFAULT_BAR_RULER,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> str:
    # arrangement_clips is the one bar-position table without a schema CHECK,
    # so these are its only floor/ordering guards; both feed the push layer's
    # _position_bar_to_beats, which raises on a sub-1.0 bar.
    _require_bar_floor("start_bar", start_bar)
    if end_bar <= start_bar:
        raise ValueError(f"end_bar ({end_bar}) must exceed start_bar ({start_bar})")
    _validate_bar_ruler(bar_ruler)
    actor, request_id = _resolve_actor_and_request(actor, request_id)
    existing = conn.execute(
        """SELECT id, end_bar, bar_ruler FROM arrangement_clips
           WHERE song_id = ? AND track_id = ? AND clip_id = ? AND start_bar = ?""",
        (song_id, track_id, clip_id, start_bar),
    ).fetchone()
    if existing is not None:
        aid = existing["id"]
        # bar_ruler joins the comparison so a re-run of a REWRITTEN build.py
        # re-stamps the row instead of leaving the old provenance standing —
        # a stale `uniform` on a position now authored against the map would
        # keep raising an alert the song already fixed.
        if (existing["end_bar"], existing["bar_ruler"]) == (end_bar, bar_ruler):
            _record_touch_if_session("arrangement_clip", aid)
            return MutatorResult(aid, "unchanged")
        conn.execute(
            "UPDATE arrangement_clips SET end_bar = ?, bar_ruler = ? WHERE id = ?",
            (end_bar, bar_ruler, aid),
        )
        _emit(
            conn,
            E.ARRANGEMENT_CLIP_ADDED,
            {"arrangement_clip_id": aid, "track_id": track_id,
             "clip_id": clip_id, "start_bar": start_bar, "end_bar": end_bar,
             "bar_ruler": bar_ruler, "kind": "updated"},
            song_id=song_id, clip_id=clip_id,
            actor=actor, request_id=request_id, reason=reason,
        )
        _record_touch_if_session("arrangement_clip", aid)
        return MutatorResult(aid, "updated")
    aid = _uuid()
    conn.execute(
        """INSERT INTO arrangement_clips
               (id, song_id, track_id, clip_id, start_bar, end_bar, bar_ruler)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (aid, song_id, track_id, clip_id, start_bar, end_bar, bar_ruler),
    )
    _emit(
        conn,
        E.ARRANGEMENT_CLIP_ADDED,
        {
            "arrangement_clip_id": aid,
            "track_id": track_id,
            "clip_id": clip_id,
            "start_bar": start_bar,
            "end_bar": end_bar,
            "bar_ruler": bar_ruler,
        },
        song_id=song_id,
        clip_id=clip_id,
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    _record_touch_if_session("arrangement_clip", aid)
    return MutatorResult(aid, "created")


@_atomic
def remove_arrangement_clip(
    conn: sqlite3.Connection,
    *,
    arrangement_clip_id: str,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> None:
    row = conn.execute(
        "SELECT song_id, clip_id FROM arrangement_clips WHERE id = ?", (arrangement_clip_id,)
    ).fetchone()
    if row is None:
        return
    conn.execute("DELETE FROM arrangement_clips WHERE id = ?", (arrangement_clip_id,))
    _emit(
        conn,
        E.ARRANGEMENT_CLIP_REMOVED,
        {"arrangement_clip_id": arrangement_clip_id},
        song_id=row["song_id"],
        clip_id=row["clip_id"],
        actor=actor,
        request_id=request_id,
        reason=reason,
    )


# ---------------------------------------------------------------------------
# Score: cue points (arrangement markers)
# ---------------------------------------------------------------------------


@_atomic
def add_cue_point(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    position_bar: float,
    name: str | None = None,
    color: int | None = None,
    bar_ruler: str = DEFAULT_BAR_RULER,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> str:
    """Add an arrangement marker at `position_bar`. Maps to Live's cue points.

    Idempotent by `(song_id, position_bar)`: a second call at the same
    position with the same name/color is a no-op; with different name/color
    it updates the existing cue. Use `remove_cue_point` + add to move a cue.
    """
    _require_bar_floor("position_bar", position_bar)
    _validate_bar_ruler(bar_ruler)
    actor, request_id = _resolve_actor_and_request(actor, request_id)
    existing = conn.execute(
        """SELECT id, name, color, bar_ruler FROM cue_points
           WHERE song_id = ? AND position_bar = ?""",
        (song_id, position_bar),
    ).fetchone()
    if existing is not None:
        pid = existing["id"]
        # Same re-stamp rule as add_arrangement_clip: a rewritten build.py must
        # be able to correct a row's recorded provenance by re-running.
        if (existing["name"], existing["color"], existing["bar_ruler"]) == (
            name, color, bar_ruler,
        ):
            _record_touch_if_session("cue_point", pid)
            return MutatorResult(pid, "unchanged")
        conn.execute(
            "UPDATE cue_points SET name = ?, color = ?, bar_ruler = ? WHERE id = ?",
            (name, color, bar_ruler, pid),
        )
        _emit(
            conn, E.CUE_POINT_ADDED,
            {"cue_id": pid, "position_bar": position_bar, "name": name,
             "color": color, "bar_ruler": bar_ruler, "kind": "updated"},
            song_id=song_id, actor=actor, request_id=request_id, reason=reason,
        )
        _touch_song(conn, song_id)
        _record_touch_if_session("cue_point", pid)
        return MutatorResult(pid, "updated")
    pid = _uuid()
    conn.execute(
        """INSERT INTO cue_points (id, song_id, position_bar, name, color, bar_ruler)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (pid, song_id, position_bar, name, color, bar_ruler),
    )
    _emit(
        conn,
        E.CUE_POINT_ADDED,
        {
            "cue_id": pid,
            "position_bar": position_bar,
            "name": name,
            "color": color,
            "bar_ruler": bar_ruler,
        },
        song_id=song_id,
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    _touch_song(conn, song_id)
    _record_touch_if_session("cue_point", pid)
    return MutatorResult(pid, "created")


@_atomic
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


__all__ = [
    "BAR_RULERS",
    "DEFAULT_BAR_RULER",
    "add_arrangement_clip",
    "add_cue_point",
    "remove_arrangement_clip",
    "remove_cue_point",
]
