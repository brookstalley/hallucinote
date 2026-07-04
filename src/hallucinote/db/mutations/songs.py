"""Songs: create + timing-mode mutators."""
from __future__ import annotations

import re
import sqlite3

from ._core import (
    E,
    MutatorResult,
    _atomic,
    _emit,
    _record_touch_if_session,
    _resolve_actor_and_request,
    _touch_song,
    _uuid,
)


TIMING_MODES = frozenset({"native", "grid"})


_SLUG_RE = re.compile(r"[a-z0-9_-]+")


@_atomic
def create_song(
    conn: sqlite3.Connection,
    *,
    name: str,
    title: str | None = None,
    key: str | None = None,
    timing_mode: str = "native",
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> str:
    """Create a song. Tempo and meter live in `tempo_map` / `time_signature_map`;
    add at least one point in each before pushing.

    `name` is the song *slug* — filesystem-safe identifier matching the
    song's directory and DB filename per the project convention
    (`songs/<name>/<name>.db`). Lowercase letters, digits, hyphens, and
    underscores only. `title` is the optional human-facing display name —
    free-form text with spaces, capitals, punctuation.

    `timing_mode='native'` (default) renders bar positions through the maps,
    matching Live's tempo/meter. `'grid'` opts out — generators handle
    resolved positions internally for polytempic experiments.
    """
    if not _SLUG_RE.fullmatch(name):
        raise ValueError(
            f"song name {name!r} must match [a-z0-9_-]+ — slugs only "
            "(no spaces, no uppercase, no special chars). Use `title` for "
            "the human-facing name."
        )
    if timing_mode not in TIMING_MODES:
        raise ValueError(
            f"invalid timing_mode {timing_mode!r}; expected one of {sorted(TIMING_MODES)}"
        )
    actor, request_id = _resolve_actor_and_request(actor, request_id)
    existing = conn.execute(
        "SELECT id, title, key, timing_mode FROM songs WHERE name = ?",
        (name,),
    ).fetchone()
    if existing is not None:
        sid = existing["id"]
        if (existing["title"], existing["key"], existing["timing_mode"]) == (
            title, key, timing_mode,
        ):
            _record_touch_if_session("song", sid)
            return MutatorResult(sid, "unchanged")
        conn.execute(
            "UPDATE songs SET title = ?, key = ?, timing_mode = ? WHERE id = ?",
            (title, key, timing_mode, sid),
        )
        _touch_song(conn, sid)
        _emit(
            conn,
            E.SONG_UPDATED,
            {"name": name, "title": title, "key": key, "timing_mode": timing_mode},
            song_id=sid,
            actor=actor,
            request_id=request_id,
            reason=reason,
        )
        _record_touch_if_session("song", sid)
        return MutatorResult(sid, "updated")
    sid = _uuid()
    conn.execute(
        "INSERT INTO songs (id, name, title, key, timing_mode) VALUES (?, ?, ?, ?, ?)",
        (sid, name, title, key, timing_mode),
    )
    _emit(
        conn,
        E.SONG_CREATED,
        {"name": name, "title": title, "key": key, "timing_mode": timing_mode},
        song_id=sid,
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    _record_touch_if_session("song", sid)
    return MutatorResult(sid, "created")


@_atomic
def set_song_timing_mode(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    timing_mode: str,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> None:
    """Switch a song between 'native' (use tempo/time-signature maps) and 'grid'
    (generators resolve positions themselves). Maps are preserved either way."""
    if timing_mode not in TIMING_MODES:
        raise ValueError(
            f"invalid timing_mode {timing_mode!r}; expected one of {sorted(TIMING_MODES)}"
        )
    actor, request_id = _resolve_actor_and_request(actor, request_id)
    # W12-A: idempotent — no-op + skip event when state matches.
    row = conn.execute(
        "SELECT timing_mode FROM songs WHERE id = ?", (song_id,)
    ).fetchone()
    if row is not None and row["timing_mode"] == timing_mode:
        return
    conn.execute(
        "UPDATE songs SET timing_mode = ? WHERE id = ?",
        (timing_mode, song_id),
    )
    _touch_song(conn, song_id)
    _emit(
        conn,
        E.SONG_TIMING_MODE_SET,
        {"timing_mode": timing_mode},
        song_id=song_id,
        actor=actor,
        request_id=request_id,
        reason=reason,
    )


@_atomic
def set_song_tuning(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    tuning_ref: str | None,
    tuning_data: str | None,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> None:
    """Bind a song to a pulled alternate tuning (MICROTUNE / TUN-4Q7W).

    `tuning_ref` is the song-relative path to the cached `.ascl`; `tuning_data` is
    the derived JSON blob the mapper / writer / drift-verify read. Both are opaque
    strings here — this mutator stays tuning-agnostic (the `hallucinote.tuning`
    package owns serialization), preserving the isolation invariant that the core
    DB layer imports nothing from `tuning`. Pass both `None` to clear a song back
    to 12-TET.

    Idempotent: a no-op (no event) when both columns already match the inputs,
    mirroring `set_song_timing_mode`.
    """
    actor, request_id = _resolve_actor_and_request(actor, request_id)
    row = conn.execute(
        "SELECT tuning_ref, tuning_data FROM songs WHERE id = ?", (song_id,)
    ).fetchone()
    if row is not None and (row["tuning_ref"], row["tuning_data"]) == (
        tuning_ref, tuning_data,
    ):
        return
    conn.execute(
        "UPDATE songs SET tuning_ref = ?, tuning_data = ? WHERE id = ?",
        (tuning_ref, tuning_data, song_id),
    )
    _touch_song(conn, song_id)
    _emit(
        conn,
        E.SONG_TUNING_SET,
        {"tuning_ref": tuning_ref, "tuning_data": tuning_data},
        song_id=song_id,
        actor=actor,
        request_id=request_id,
        reason=reason,
    )


__all__ = [
    "TIMING_MODES",
    "create_song",
    "set_song_timing_mode",
    "set_song_tuning",
]
