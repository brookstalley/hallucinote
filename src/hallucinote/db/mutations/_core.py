"""Shared infrastructure for the mutations package.

Holds the pieces every domain submodule needs: id generation, event
emission, the `MutatorResult` return type, the build-session ContextVar +
actor/request resolution, the song/clip touch helpers, and module-level
constants shared across domains.

`_core` must NOT import from any domain submodule — it stays dependency-free
so the package can never form an import cycle through it.
"""
from __future__ import annotations

import contextvars
import functools
import json
import sqlite3
import uuid
from typing import Any, Callable, TypeVar

from hallucinote.db import events as E
from hallucinote.db.connection import transaction

_F = TypeVar("_F", bound=Callable[..., Any])


def _atomic(fn: _F) -> _F:
    """Make a mutator's state-write + event-emit commit together (EVT-6H9R).

    Connections are opened in autocommit (`connection.connect`,
    `isolation_level=None`), so without this wrapper each statement inside a
    mutator commits individually — a crash between the state write and the
    `_emit()` call leaves a state row with no event (or, for multi-statement
    mutators, a half-applied write). Wrapping the whole mutator body in the
    canonical `connection.transaction()` helper closes that window: on ANY
    exception the entire mutation (state + event) rolls back; a killed process
    leaves an uncommitted WAL transaction that SQLite discards on next open.

    Reentrancy: `transaction()` nests via SAVEPOINTs, so a mutator calling
    another mutator (or a caller batching mutators inside its own
    `transaction(conn)`) composes — inner calls join the outermost
    transaction and only the outermost COMMITs.

    Applies to every state-writing mutator in this package. Convention: the
    connection is the first positional argument (see the package docstring).
    """

    @functools.wraps(fn)
    def wrapper(conn: sqlite3.Connection, *args: Any, **kwargs: Any) -> Any:
        with transaction(conn):
            return fn(conn, *args, **kwargs)

    return wrapper  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# W12-A: structured mutator return + build-session injection
# ---------------------------------------------------------------------------
#
# Mutator returns are `MutatorResult` — a `str` subclass so old callsites
# (`tid = M.create_track(...)`) keep working AND new callers can inspect
# `tid.kind` to see whether the row was just created, updated, or unchanged.
#
# When build.py wraps the build in `with M.build_session(...) as bs:`, the
# `_current_build_session` ContextVar gets set. Mutators check it: if the
# caller didn't pass `actor` explicitly (i.e. left the default 'system'),
# the mutator promotes actor to 'build' and tags `request_id` with the
# session's request. Touched-set accumulation happens on the session via
# `bs.record_touch(kind, id)` — mutators call it after their state write.


class MutatorResult(str):
    """The mutator's row id (str-compatible for back-compat) plus `kind`.

    `kind` is one of:
      - 'created'   row was newly inserted
      - 'updated'   row existed; one or more non-identity fields changed
      - 'unchanged' row existed; state already matched the inputs (no-op)

    `MutatorResult` is a `str` subclass so existing callsites that treat the
    return as a bare id (`tid = M.create_track(...)`) keep working unchanged.
    """
    __slots__ = ("kind",)

    def __new__(cls, id_: str, kind: str) -> "MutatorResult":
        if kind not in {"created", "updated", "unchanged"}:
            raise ValueError(f"invalid MutatorResult.kind {kind!r}")
        instance = super().__new__(cls, id_)
        instance.kind = kind  # noqa: PLW0238
        return instance

    def __repr__(self) -> str:  # pragma: no cover (cosmetic)
        return f"MutatorResult({str(self)!r}, kind={self.kind!r})"


# ContextVar for build-session injection. Default None means "not inside a
# build session." Set by `build_session.__enter__`, reset by `__exit__`.
_current_build_session: contextvars.ContextVar["BuildSession | None"] = (
    contextvars.ContextVar("_current_build_session", default=None)
)


def _resolve_actor_and_request(
    actor: str, request_id: str | None,
) -> tuple[str, str | None]:
    """If running inside `build_session`, inject the session's request_id when
    caller didn't pass one, and promote default actor 'system' to 'build'.

    Two independent injections:
      - `actor`: promoted from 'system' (library default) to 'build' inside
        the session. Explicit non-default actors (e.g. 'sync' from
        replay_capture, 'generator' from generators) survive.
      - `request_id`: always injected when None, regardless of actor — so
        every event emitted inside a build_session carries the cycle
        request_id for audit-trail traceability. Explicit request_id values
        survive (rare; mostly test fixtures or nested-cycle scenarios).
    """
    bs = _current_build_session.get()
    if bs is None:
        return actor, request_id
    if actor == "system":
        actor = "build"
    if request_id is None:
        request_id = bs.request_id
    return actor, request_id


def _record_touch_if_session(kind: str, id_: str) -> None:
    """If running inside `build_session`, record (kind, id) to its touched-set."""
    bs = _current_build_session.get()
    if bs is not None:
        bs.record_touch(kind, id_)


# Valid `requests.kind` values. Mirrors the wave-8 design: 'mutate' is the
# back-compat default; 'compose', 'push', 'pull', 'capture', 'analyze' tag
# higher-level cycles for cross-reference queries.
REQUEST_KINDS = frozenset(
    {"compose", "push", "pull", "capture", "analyze", "mutate"}
)

# Valid `requests.outcome` values, set at request close.
REQUEST_OUTCOMES = frozenset({"ok", "partial", "failed"})

NoteDict = dict[str, Any]


# ---------------------------------------------------------------------------
# Internal: id generation + event emission
# ---------------------------------------------------------------------------


def _uuid() -> str:
    """Canonical id format: 32-char hex (no dashes) UUIDv4."""
    return uuid.uuid4().hex


def _emit(
    conn: sqlite3.Connection,
    kind: str,
    payload: dict[str, Any],
    *,
    song_id: str | None = None,
    clip_id: str | None = None,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> str:
    """Append one events row. Returns the new event id.

    `seq` is assigned monotonically from MAX(seq)+1; single-writer assumption
    holds for this single-user authoring tool.
    """
    if actor not in E.ACTORS:
        raise ValueError(f"invalid actor {actor!r}; expected one of {sorted(E.ACTORS)}")
    # EVT-6H9R: kinds are a closed set — every kind must be a constant in
    # hallucinote.db.events (the only sanctioned source). Inline strings used
    # to slip past both the constants convention and the replay smoke test's
    # exhaustive classification; now they fail at the emit site.
    if kind not in E.KINDS:
        raise ValueError(
            f"unknown event kind {kind!r}: add a constant to "
            "hallucinote/db/events.py (the sanctioned source of kinds) and "
            "emit that — inline kind strings are not accepted"
        )
    event_id = _uuid()
    seq = conn.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM events").fetchone()[0]
    conn.execute(
        """INSERT INTO events
               (id, seq, kind, payload_json, song_id, clip_id,
                actor, reason, request_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            event_id,
            seq,
            kind,
            json.dumps(payload, separators=(",", ":")),
            song_id,
            clip_id,
            actor,
            reason,
            request_id,
        ),
    )
    return event_id


def _touch_clip(conn: sqlite3.Connection, clip_id: str) -> None:
    conn.execute(
        "UPDATE clips SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?",
        (clip_id,),
    )


def _touch_song(conn: sqlite3.Connection, song_id: str) -> None:
    conn.execute(
        "UPDATE songs SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?",
        (song_id,),
    )


def _require_bar_floor(field: str, value: float) -> None:
    """Reject a bar position below the 1-based floor with a teaching error.

    Bars are 1-based throughout (bar 1 is the song's first bar); ``start_bar``
    columns on ``sections`` / ``tempo_map`` / ``time_signature_map`` carry a
    ``CHECK (start_bar >= 1.0)`` and ``_position_bar_to_beats`` raises on a
    sub-1.0 position. Validating here, at the only sanctioned write path, fails
    fast at the source with an explanation instead of surfacing a cryptic
    ``IntegrityError`` (CHECK-backed tables) or a far-away ``ValueError`` at
    push/analysis time (``arrangement_clips``, which has no such CHECK)."""
    if value < 1.0:
        raise ValueError(
            f"{field} must be >= 1.0 per the 1-based bar convention "
            f"(bar 1 is the first bar; got {value!r})"
        )


__all__ = [
    "Any",
    "E",
    "MutatorResult",
    "NoteDict",
    "REQUEST_KINDS",
    "REQUEST_OUTCOMES",
    "_atomic",
    "_current_build_session",
    "_emit",
    "_record_touch_if_session",
    "_require_bar_floor",
    "_resolve_actor_and_request",
    "_touch_clip",
    "_touch_song",
    "_uuid",
    "json",
    "sqlite3",
    "transaction",
]
