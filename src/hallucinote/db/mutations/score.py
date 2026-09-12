"""Score: sections, tempo map, time-signature map."""
from __future__ import annotations

import sqlite3
import warnings
from typing import Any

from hallucinote.meter import MeterMap, MeterPoint

from ._core import (
    E,
    MutatorResult,
    _atomic,
    _emit,
    _record_touch_if_session,
    _require_bar_floor,
    _resolve_actor_and_request,
    _touch_song,
    _touches,
    _uuid,
)
from .arrangement import DEFAULT_BAR_RULER, _validate_bar_ruler


# ---------------------------------------------------------------------------
# Score: sections
# ---------------------------------------------------------------------------


@_atomic
def create_section(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    name: str,
    start_bar: float,
    end_bar: float,
    color: int | None = None,
    notes_md: str | None = None,
    energy: float | None = None,
    bar_ruler: str = DEFAULT_BAR_RULER,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> str:
    """Mark a named span of bars (verse, chorus, bridge, ...). DB-only metadata
    unless Live exposes section markers; surfaces in event log either way.

    ``energy`` is the authored per-section intensity intent (0..1 ordinal,
    ARR-7M3D) — NULL when undeclared. It is excluded from the energy-realization
    correlation when NULL, never coerced to a value.

    ``bar_ruler`` records which ruler produced ``start_bar`` / ``end_bar``:
    ``'map'`` when they were resolved through the song's ``time_signature_map``
    — which every writer in the tree does since #566, and which is the default,
    so a new writer is correct without knowing the rule exists — and
    ``'uniform'`` when they were accumulated against a single ``beats_per_bar``,
    which nothing authors any more and only rows written before #566 carry.
    Re-stamped on the update branch too, so re-running a ``build.py`` corrects a
    stale ``'uniform'`` rather than leaving the row asserting a ruler it no
    longer used.
    """
    _require_bar_floor("start_bar", start_bar)
    if end_bar <= start_bar:
        raise ValueError(f"end_bar ({end_bar}) must exceed start_bar ({start_bar})")
    _validate_bar_ruler(bar_ruler)
    actor, request_id = _resolve_actor_and_request(actor, request_id)
    existing = conn.execute(
        """SELECT id, end_bar, color, notes_md, energy, bar_ruler FROM sections
           WHERE song_id = ? AND name = ? AND start_bar = ?""",
        (song_id, name, start_bar),
    ).fetchone()
    if existing is not None:
        sid = existing["id"]
        if (
            existing["end_bar"], existing["color"], existing["notes_md"],
            existing["energy"], existing["bar_ruler"],
        ) == (
            end_bar, color, notes_md, energy, bar_ruler,
        ):
            _record_touch_if_session("section", sid)
            return MutatorResult(sid, "unchanged")
        conn.execute(
            """UPDATE sections SET end_bar = ?, color = ?, notes_md = ?,
                   energy = ?, bar_ruler = ?
               WHERE id = ?""",
            (end_bar, color, notes_md, energy, bar_ruler, sid),
        )
        _emit(
            conn, E.SECTION_UPDATED,
            {"section_id": sid, "changes": {"end_bar": end_bar,
             "color": color, "notes_md": notes_md, "energy": energy,
             "bar_ruler": bar_ruler}},
            song_id=song_id, actor=actor, request_id=request_id, reason=reason,
        )
        _touch_song(conn, song_id)
        _record_touch_if_session("section", sid)
        return MutatorResult(sid, "updated")
    sid = _uuid()
    conn.execute(
        """INSERT INTO sections
               (id, song_id, name, start_bar, end_bar, color, notes_md, energy,
                bar_ruler)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (sid, song_id, name, start_bar, end_bar, color, notes_md, energy,
         bar_ruler),
    )
    _emit(
        conn,
        E.SECTION_CREATED,
        {
            "section_id": sid,
            "name": name,
            "start_bar": start_bar,
            "end_bar": end_bar,
            "color": color,
            "notes_md": notes_md,
            "energy": energy,
            "bar_ruler": bar_ruler,
        },
        song_id=song_id,
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    _touch_song(conn, song_id)
    _record_touch_if_session("section", sid)
    return MutatorResult(sid, "created")


_SECTION_FIELDS = {"name", "start_bar", "end_bar", "color", "notes_md", "energy"}


@_touches("section", "section_id")
@_atomic
def update_section(
    conn: sqlite3.Connection,
    *,
    section_id: str,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
    **changes: Any,
) -> None:
    """Partial update by id. `changes` keys must be in _SECTION_FIELDS."""
    bad = set(changes) - _SECTION_FIELDS
    if bad:
        raise ValueError(f"unsupported fields: {sorted(bad)}")
    if not changes:
        return
    row = conn.execute(
        "SELECT song_id, start_bar, end_bar FROM sections WHERE id = ?", (section_id,)
    ).fetchone()
    if row is None:
        return
    # Span guard: validate the resulting span, not just the new value, so updating
    # start_bar past the existing end_bar (or vice versa) fails cleanly.
    new_start = float(changes.get("start_bar", row["start_bar"]))
    new_end = float(changes.get("end_bar", row["end_bar"]))
    if new_end <= new_start:
        raise ValueError(f"end_bar ({new_end}) must exceed start_bar ({new_start})")

    sets = [f"{k} = ?" for k in changes]
    vals = list(changes.values()) + [section_id]
    conn.execute(f"UPDATE sections SET {', '.join(sets)} WHERE id = ?", vals)
    _emit(
        conn,
        E.SECTION_UPDATED,
        {"section_id": section_id, "changes": changes},
        song_id=row["song_id"],
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    _touch_song(conn, row["song_id"])


@_atomic
def delete_section(
    conn: sqlite3.Connection,
    *,
    section_id: str,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> None:
    row = conn.execute(
        "SELECT song_id FROM sections WHERE id = ?", (section_id,)
    ).fetchone()
    if row is None:
        return
    conn.execute("DELETE FROM sections WHERE id = ?", (section_id,))
    _emit(
        conn,
        E.SECTION_DELETED,
        {"section_id": section_id},
        song_id=row["song_id"],
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    _touch_song(conn, row["song_id"])


# ---------------------------------------------------------------------------
# Score: tempo map
# ---------------------------------------------------------------------------

TEMPO_RAMP_KINDS = frozenset({"linear", "hold"})


@_atomic
def add_tempo_point(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    start_bar: float,
    tempo_bpm: float,
    ramp: str = "hold",
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> str:
    """Add a tempo point at `start_bar`. `ramp='hold'` keeps tempo constant
    until the next point; `'linear'` ramps to the next point's tempo."""
    if ramp not in TEMPO_RAMP_KINDS:
        raise ValueError(
            f"invalid ramp {ramp!r}; expected one of {sorted(TEMPO_RAMP_KINDS)}"
        )
    if tempo_bpm <= 0:
        raise ValueError(f"tempo_bpm must be positive, got {tempo_bpm}")
    _require_bar_floor("start_bar", start_bar)
    actor, request_id = _resolve_actor_and_request(actor, request_id)
    existing = conn.execute(
        """SELECT id, tempo_bpm, ramp FROM tempo_map
           WHERE song_id = ? AND start_bar = ?""",
        (song_id, start_bar),
    ).fetchone()
    if existing is not None:
        pid = existing["id"]
        if (existing["tempo_bpm"], existing["ramp"]) == (tempo_bpm, ramp):
            _record_touch_if_session("tempo_point", pid)
            return MutatorResult(pid, "unchanged")
        conn.execute(
            "UPDATE tempo_map SET tempo_bpm = ?, ramp = ? WHERE id = ?",
            (tempo_bpm, ramp, pid),
        )
        _emit(
            conn, E.TEMPO_POINT_UPDATED,
            {"point_id": pid, "changes": {"tempo_bpm": tempo_bpm, "ramp": ramp}},
            song_id=song_id, actor=actor, request_id=request_id, reason=reason,
        )
        _touch_song(conn, song_id)
        _record_touch_if_session("tempo_point", pid)
        return MutatorResult(pid, "updated")
    pid = _uuid()
    conn.execute(
        """INSERT INTO tempo_map (id, song_id, start_bar, tempo_bpm, ramp)
           VALUES (?, ?, ?, ?, ?)""",
        (pid, song_id, start_bar, tempo_bpm, ramp),
    )
    _emit(
        conn,
        E.TEMPO_POINT_ADDED,
        {
            "point_id": pid,
            "start_bar": start_bar,
            "tempo_bpm": tempo_bpm,
            "ramp": ramp,
        },
        song_id=song_id,
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    _touch_song(conn, song_id)
    _record_touch_if_session("tempo_point", pid)
    return MutatorResult(pid, "created")


_TEMPO_POINT_FIELDS = {"tempo_bpm", "ramp"}


@_touches("tempo_point", "point_id")
@_atomic
def update_tempo_point(
    conn: sqlite3.Connection,
    *,
    point_id: str,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
    **changes: Any,
) -> None:
    """Partial update of a tempo_map row. `changes` keys must be in
    _TEMPO_POINT_FIELDS — `start_bar` is identity here, change it via
    remove+add."""
    bad = set(changes) - _TEMPO_POINT_FIELDS
    if bad:
        raise ValueError(f"unsupported fields: {sorted(bad)}")
    if not changes:
        return
    if "tempo_bpm" in changes and changes["tempo_bpm"] <= 0:
        raise ValueError(f"tempo_bpm must be positive, got {changes['tempo_bpm']}")
    if "ramp" in changes and changes["ramp"] not in TEMPO_RAMP_KINDS:
        raise ValueError(
            f"invalid ramp {changes['ramp']!r}; "
            f"expected one of {sorted(TEMPO_RAMP_KINDS)}"
        )
    row = conn.execute(
        "SELECT song_id FROM tempo_map WHERE id = ?", (point_id,)
    ).fetchone()
    if row is None:
        return
    sets = [f"{k} = ?" for k in changes]
    vals = list(changes.values()) + [point_id]
    conn.execute(f"UPDATE tempo_map SET {', '.join(sets)} WHERE id = ?", vals)
    _emit(
        conn,
        E.TEMPO_POINT_UPDATED,
        {"point_id": point_id, "changes": changes},
        song_id=row["song_id"],
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    _touch_song(conn, row["song_id"])


@_atomic
def remove_tempo_point(
    conn: sqlite3.Connection,
    *,
    point_id: str,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> None:
    row = conn.execute(
        "SELECT song_id FROM tempo_map WHERE id = ?", (point_id,)
    ).fetchone()
    if row is None:
        return
    conn.execute("DELETE FROM tempo_map WHERE id = ?", (point_id,))
    _emit(
        conn,
        E.TEMPO_POINT_REMOVED,
        {"point_id": point_id},
        song_id=row["song_id"],
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    _touch_song(conn, row["song_id"])


# ---------------------------------------------------------------------------
# Score: time-signature map
# ---------------------------------------------------------------------------


def _warn_if_positions_would_be_retimed(
    conn: sqlite3.Connection,
    song_id: str,
    start_bar: float,
    numerator: int,
    denominator: int,
) -> None:
    """Warn when a meter write moves positions the song already holds.

    Every bar position in this song resolves to beats through the meter map, so
    changing the map moves the positions after the change — sections, cue points
    and arrangement placements alike — while the rows themselves keep the bar
    numbers they were written with. Nothing looks wrong afterwards.

    What fires is the order that silently corrupts: meter written AFTER
    positions exist. `Arrangement.materialize` checks map agreement, but it
    checks at the moment it runs, so a later write is invisible to it; and the
    rows it wrote carry `bar_ruler="map"`, which tells the push planner they
    were resolved through the map and stops its divergence detector reading
    them. This is the only place that ordering is visible.

    **It asks whether beats actually move, not whether the map was touched.**
    A bar-1 row written after a placement is ordinary — several songs' builds
    do it — and declaring 4/4 where 4/4 was already in force moves nothing. A
    warning that fired on those would fire on almost every build, and a warning
    every build prints is one nobody reads.
    """
    rows = conn.execute(
        """SELECT start_bar, numerator, denominator FROM time_signature_map
           WHERE song_id = ?""",
        (song_id,),
    ).fetchall()
    before = MeterMap.from_rows(rows)
    after = MeterMap(
        [p for p in before.points if abs(p.start_bar - start_bar) >= 1e-9]
        + [MeterPoint(start_bar, numerator, denominator)]
    )

    positions = conn.execute(
        """SELECT end_bar AS bar FROM sections         WHERE song_id = ?
           UNION SELECT position_bar          FROM cue_points       WHERE song_id = ?
           UNION SELECT end_bar               FROM arrangement_clips WHERE song_id = ?""",
        (song_id, song_id, song_id),
    ).fetchall()
    moved = [
        float(row["bar"])
        for row in positions
        if abs(after.beats_at(float(row["bar"])) - before.beats_at(float(row["bar"])))
        > 1e-9
    ]
    if not moved:
        return
    shown = ", ".join(f"{b:g}" for b in sorted(moved)[:8])
    if len(moved) > 8:
        shown += f", and {len(moved) - 8} more"
    warnings.warn(
        f"meter {numerator}/{denominator} written at bar {start_bar:g} AFTER "
        f"positions exist past it: {len(moved)} authored bar position(s) now "
        f"resolve to different beats than the map they were authored against "
        f"gave them (bars {shown}). Their bar numbers are unchanged, so nothing "
        f"looks wrong, and the push planner reads them as map-resolved. Author "
        f"the song's meter BEFORE materializing its arrangement — re-running "
        f"the song's build.py does exactly that and settles it.",
        stacklevel=3,
    )


@_atomic
def add_time_signature_point(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    start_bar: float,
    numerator: int,
    denominator: int,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> str:
    """Add a meter change at `start_bar` (numerator/denominator).

    Within-song meter changes ARE recordable. The song's meter is a property
    of the authored work; Live's ability to render it is a materialization
    detail, so the limit belongs to the projection, not to the source of
    truth. Live 12.4 exposes only a single global signature (no
    `song_signature` automation target_kind), so `plan_push_time_signature_map`
    pushes the bar-1 row and warns loudly about the rest — that warn is the
    one place the reach limit is stated.
    """
    if numerator <= 0 or denominator <= 0:
        raise ValueError(
            f"numerator/denominator must be positive, got {numerator}/{denominator}"
        )
    _require_bar_floor("start_bar", start_bar)
    actor, request_id = _resolve_actor_and_request(actor, request_id)
    existing = conn.execute(
        """SELECT id, numerator, denominator FROM time_signature_map
           WHERE song_id = ? AND start_bar = ?""",
        (song_id, start_bar),
    ).fetchone()
    if existing is not None:
        pid = existing["id"]
        if (existing["numerator"], existing["denominator"]) == (numerator, denominator):
            _record_touch_if_session("time_signature_point", pid)
            return MutatorResult(pid, "unchanged")
        _warn_if_positions_would_be_retimed(
            conn, song_id, start_bar, numerator, denominator,
        )
        conn.execute(
            "UPDATE time_signature_map SET numerator = ?, denominator = ? WHERE id = ?",
            (numerator, denominator, pid),
        )
        _emit(
            conn, E.TIME_SIGNATURE_POINT_UPDATED,
            {"point_id": pid, "changes": {"numerator": numerator,
                                           "denominator": denominator}},
            song_id=song_id, actor=actor, request_id=request_id, reason=reason,
        )
        _touch_song(conn, song_id)
        _record_touch_if_session("time_signature_point", pid)
        return MutatorResult(pid, "updated")
    _warn_if_positions_would_be_retimed(
        conn, song_id, start_bar, numerator, denominator,
    )
    pid = _uuid()
    conn.execute(
        """INSERT INTO time_signature_map
               (id, song_id, start_bar, numerator, denominator)
           VALUES (?, ?, ?, ?, ?)""",
        (pid, song_id, start_bar, numerator, denominator),
    )
    _emit(
        conn,
        E.TIME_SIGNATURE_POINT_ADDED,
        {
            "point_id": pid,
            "start_bar": start_bar,
            "numerator": numerator,
            "denominator": denominator,
        },
        song_id=song_id,
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    _touch_song(conn, song_id)
    _record_touch_if_session("time_signature_point", pid)
    return MutatorResult(pid, "created")


_TIME_SIGNATURE_POINT_FIELDS = {"numerator", "denominator"}


@_touches("time_signature_point", "point_id")
@_atomic
def update_time_signature_point(
    conn: sqlite3.Connection,
    *,
    point_id: str,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
    **changes: Any,
) -> None:
    """Partial update of a time_signature_map row. `changes` keys must be in
    _TIME_SIGNATURE_POINT_FIELDS — `start_bar` is identity here, change it
    via remove+add."""
    bad = set(changes) - _TIME_SIGNATURE_POINT_FIELDS
    if bad:
        raise ValueError(f"unsupported fields: {sorted(bad)}")
    if not changes:
        return
    if "numerator" in changes and changes["numerator"] <= 0:
        raise ValueError(f"numerator must be positive, got {changes['numerator']}")
    if "denominator" in changes and changes["denominator"] <= 0:
        raise ValueError(
            f"denominator must be positive, got {changes['denominator']}"
        )
    row = conn.execute(
        """SELECT song_id FROM time_signature_map WHERE id = ?""",
        (point_id,),
    ).fetchone()
    if row is None:
        return
    sets = [f"{k} = ?" for k in changes]
    vals = list(changes.values()) + [point_id]
    conn.execute(
        f"UPDATE time_signature_map SET {', '.join(sets)} WHERE id = ?", vals
    )
    _emit(
        conn,
        E.TIME_SIGNATURE_POINT_UPDATED,
        {"point_id": point_id, "changes": changes},
        song_id=row["song_id"],
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    _touch_song(conn, row["song_id"])


@_atomic
def remove_time_signature_point(
    conn: sqlite3.Connection,
    *,
    point_id: str,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> None:
    row = conn.execute(
        "SELECT song_id FROM time_signature_map WHERE id = ?", (point_id,)
    ).fetchone()
    if row is None:
        return
    conn.execute("DELETE FROM time_signature_map WHERE id = ?", (point_id,))
    _emit(
        conn,
        E.TIME_SIGNATURE_POINT_REMOVED,
        {"point_id": point_id},
        song_id=row["song_id"],
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    _touch_song(conn, row["song_id"])


__all__ = [
    "TEMPO_RAMP_KINDS",
    "add_tempo_point",
    "add_time_signature_point",
    "create_section",
    "delete_section",
    "remove_tempo_point",
    "remove_time_signature_point",
    "update_section",
    "update_tempo_point",
    "update_time_signature_point",
]
