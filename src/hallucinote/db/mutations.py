"""All state-changing operations on the hallucinote DB.

Every function here:
  1. Performs its state change.
  2. Emits an `events` row describing the change in the same transaction.

Callers MUST use these instead of raw SQL. The discipline is the only thing
that makes a future event-store flip cheap rather than a rewrite.

Conventions:
- Functions take `conn` as first positional arg; everything else keyword-only.
- IDs are UUIDv4 hex strings, generated here via `_uuid()`. Mutators return the
  new id (for creates), the list of new ids (for bulk), or None (otherwise).
- Every mutator accepts `actor`, `request_id`, `reason` kwargs. Defaults
  (`'system'`, None, None) keep tests terse; agent code threads explicit
  values to make audit trails readable.
- Notes use canonical field names: pitch, start_beats, duration_beats, velocity,
  mute (0/1), tags (list[str] | None). NOT start_time / duration — convert at
  the porter / generator boundary.
"""
from __future__ import annotations

import contextlib
import contextvars
import json
import re
import sqlite3
import time
import uuid
from typing import Any, Iterator, Sequence

from hallucinote.db import events as E, queries as Q
from hallucinote.db.connection import transaction
from hallucinote.preset_query import normalize as _normalize_preset_query
from hallucinote.return_naming import strip_return_slot_prefix


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
# Provenance metadata capture (Arc 2 / B4)
# ---------------------------------------------------------------------------


def provenance_metadata(
    *,
    model: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Capture the standard provenance signals that ride on `requests.metadata_json`:
    git sha (short), branch, hostname, optional model name, plus any caller-
    provided extras. Best-effort: a failed git/socket probe drops the
    affected key rather than raising — provenance is observational, not
    operational.

    Used by push / pull / capture drivers (Arc 2 / B4) so every audited
    cycle carries the platform context that lets a later session
    reconstruct "where did this come from."
    """
    import socket
    import subprocess

    sha: str | None = None
    branch: str | None = None
    # 2-second cap: every build_session runs this on entry, so a hung git
    # invocation (locked .git, remote-helper stall) would freeze every
    # compose cycle. subprocess.TimeoutExpired falls into the except below.
    _GIT_TIMEOUT_SECONDS = 2.0
    try:
        sha = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=_GIT_TIMEOUT_SECONDS,
        ).strip()
    except (subprocess.SubprocessError, OSError, FileNotFoundError):
        pass
    try:
        branch = subprocess.check_output(
            ["git", "symbolic-ref", "--short", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=_GIT_TIMEOUT_SECONDS,
        ).strip()
    except (subprocess.SubprocessError, OSError, FileNotFoundError):
        pass
    try:
        hostname: str | None = socket.gethostname()
    except OSError:
        hostname = None

    out: dict[str, Any] = {}
    if sha:
        out["git_sha"] = sha
    if branch:
        out["branch"] = branch
    if hostname:
        out["hostname"] = hostname
    if model:
        out["model"] = model
    if extra:
        out.update(extra)
    return out


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


# ---------------------------------------------------------------------------
# Provenance: requests
# ---------------------------------------------------------------------------


def create_request(
    conn: sqlite3.Connection,
    *,
    actor: str,
    intent: str,
    payload: dict[str, Any] | None = None,
    song_id: str | None = None,
    reason: str | None = None,
    kind: str = "mutate",
    prompt_text: str | None = None,
    parent_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Create a request row. Returns the request id.

    Pass the returned id as `request_id=` to subsequent mutators so their
    events thread back to the originating intent. `kind` classifies the
    cycle type — see `REQUEST_KINDS`; defaults to 'mutate' for back-compat
    with pre-W8 callers.

    `prompt_text` is the verbatim seed prompt for compose / push / pull
    cycles (typically the user's natural-language request). `parent_id`
    self-FKs so an MCP auto-`mutate` request can chain to its enclosing
    `compose` parent — degraded but always-present provenance. `metadata`
    is a free-form dict for contextual signals (model, git_sha, branch,
    session_id, hostname, etc.); stored as JSON.
    """
    if actor not in E.ACTORS:
        raise ValueError(f"invalid actor {actor!r}; expected one of {sorted(E.ACTORS)}")
    if kind not in REQUEST_KINDS:
        raise ValueError(
            f"invalid kind {kind!r}; expected one of {sorted(REQUEST_KINDS)}"
        )
    if parent_id is not None:
        parent_row = conn.execute(
            "SELECT id FROM requests WHERE id = ?", (parent_id,)
        ).fetchone()
        if parent_row is None:
            raise ValueError(
                f"invalid parent_id {parent_id!r}; no such request"
            )
    rid = _uuid()
    payload_json = json.dumps(payload, separators=(",", ":")) if payload is not None else None
    metadata_json = (
        json.dumps(metadata, separators=(",", ":")) if metadata is not None else None
    )
    conn.execute(
        """INSERT INTO requests (
               id, actor, intent, payload_json, song_id, kind,
               prompt_text, parent_id, metadata_json
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            rid, actor, intent, payload_json, song_id, kind,
            prompt_text, parent_id, metadata_json,
        ),
    )
    _emit(
        conn,
        E.REQUEST_CREATED,
        {
            "request_id": rid,
            "intent": intent,
            "payload": payload,
            "kind": kind,
            "parent_id": parent_id,
        },
        song_id=song_id,
        actor=actor,
        request_id=rid,
        reason=reason,
    )
    return rid


def close_request(
    conn: sqlite3.Connection,
    *,
    request_id: str,
    outcome: str = "ok",
    duration_ms: int | None = None,
    actor: str = "system",
    reason: str | None = None,
) -> None:
    """Mark a request closed with outcome + duration. Emits REQUEST_CLOSED.

    Idempotency note: calling twice will write the second outcome and emit
    a second event. Callers that need at-most-once should track the open
    set externally; the `request()` context manager below does this for
    the common ergonomic case.
    """
    if outcome not in REQUEST_OUTCOMES:
        raise ValueError(
            f"invalid outcome {outcome!r}; expected one of {sorted(REQUEST_OUTCOMES)}"
        )
    row = conn.execute(
        "SELECT song_id FROM requests WHERE id = ?", (request_id,)
    ).fetchone()
    if row is None:
        raise ValueError(f"request {request_id!r} not found")
    conn.execute(
        "UPDATE requests SET outcome = ?, duration_ms = ? WHERE id = ?",
        (outcome, duration_ms, request_id),
    )
    _emit(
        conn,
        E.REQUEST_CLOSED,
        {"request_id": request_id, "outcome": outcome, "duration_ms": duration_ms},
        song_id=row["song_id"],
        actor=actor,
        request_id=request_id,
        reason=reason,
    )


@contextlib.contextmanager
def request(
    conn: sqlite3.Connection,
    *,
    actor: str,
    intent: str,
    kind: str = "mutate",
    payload: dict[str, Any] | None = None,
    song_id: str | None = None,
    reason: str | None = None,
    prompt_text: str | None = None,
    parent_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> Iterator[str]:
    """Ergonomic open + close lifecycle for kind-tagged request cycles.

    Yields the new request_id; the body threads it to subsequent mutators.
    On normal exit, closes with outcome='ok' + measured duration_ms. On
    exception, closes with outcome='failed' and re-raises.

    `prompt_text`, `parent_id`, and `metadata` thread directly to
    `create_request` — see its docstring.

    Usage:
        with M.request(conn, actor='llm', intent='build verse',
                       kind='compose',
                       prompt_text="make me a moody verse in Dm") as rid:
            M.replace_clip_notes(conn, clip_id=..., request_id=rid, ...)
    """
    rid = create_request(
        conn,
        actor=actor,
        intent=intent,
        payload=payload,
        song_id=song_id,
        reason=reason,
        kind=kind,
        prompt_text=prompt_text,
        parent_id=parent_id,
        metadata=metadata,
    )
    start_ns = time.monotonic_ns()
    outcome = "ok"
    try:
        yield rid
    except BaseException:  # prawduct:ok-broad-except
        # Mark failure for ANY exception including KeyboardInterrupt /
        # CancelledError — the audit trail must record that the cycle
        # didn't complete. Then re-raise so the caller still sees it.
        outcome = "failed"
        raise
    finally:
        duration_ms = (time.monotonic_ns() - start_ns) // 1_000_000
        close_request(
            conn,
            request_id=rid,
            outcome=outcome,
            duration_ms=int(duration_ms),
            actor=actor,
            reason=reason,
        )


# W23-B: structured composer-intent annotations. Distinct from the
# markdown_refs corpus (which holds ADR-shaped decision/annotation files on
# disk) — this surface is for short-form, bar-range-scoped, live-composing
# observations the agent updates as composition progresses.
ANNOTATION_KINDS = frozenset(
    {"intent", "stylistic", "structure", "reference", "todo"}
)


def add_annotation(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    kind: str,
    body: str,
    track_id: str | None = None,
    start_bar: float | None = None,
    end_bar: float | None = None,
    actor: str = "llm",
    request_id: str | None = None,
    reason: str | None = None,
) -> str:
    """Create one annotations row. Returns the new annotation id.

    Scoping levels (enforced by schema CHECK constraints):
      - **Song-scoped**:  ``track_id=None``, ``start_bar=None``, ``end_bar=None``
      - **Time-scoped**:  ``track_id=None``, ``start_bar`` set, ``end_bar``
        optional (None = open-ended forward from start_bar)
      - **Track-scoped**: ``track_id`` set, time optional

    The agent uses this during composition for "live composing notes" —
    distinct from durable decisions, which live as markdown files under
    ``songs/<slug>/decisions/`` and are indexed via ``markdown_refs``.
    """
    if kind not in ANNOTATION_KINDS:
        raise ValueError(
            f"invalid annotation kind {kind!r}; expected one of "
            f"{sorted(ANNOTATION_KINDS)}"
        )
    if end_bar is not None and start_bar is None:
        raise ValueError("end_bar requires start_bar (open-ended-only ranges are not supported)")
    if end_bar is not None and end_bar <= start_bar:
        raise ValueError(f"end_bar ({end_bar}) must be greater than start_bar ({start_bar})")
    aid = _uuid()
    actor, request_id = _resolve_actor_and_request(actor, request_id)
    conn.execute(
        """INSERT INTO annotations
               (id, song_id, track_id, start_bar, end_bar, kind, body)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (aid, song_id, track_id, start_bar, end_bar, kind, body),
    )
    _emit(
        conn,
        E.ANNOTATION_ADDED,
        {
            "annotation_id": aid,
            "song_id": song_id,
            "track_id": track_id,
            "start_bar": start_bar,
            "end_bar": end_bar,
            "kind": kind,
            "body": body,
        },
        song_id=song_id,
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    return aid


def update_annotation(
    conn: sqlite3.Connection,
    *,
    annotation_id: str,
    body: str | None = None,
    kind: str | None = None,
    start_bar: float | None = None,
    end_bar: float | None = None,
    actor: str = "llm",
    request_id: str | None = None,
    reason: str | None = None,
) -> None:
    """Update one annotation. Any of body/kind/start_bar/end_bar may be set;
    None means "leave unchanged." Bumps ``updated_at``.

    Use ``set_*_to_null`` semantics? Not today — clearing a bar range means
    rewriting the row's scope, which is rare enough that delete + recreate
    is simpler. If a callsite ever needs "clear end_bar," add an explicit
    flag rather than overloading None.
    """
    row = conn.execute(
        "SELECT * FROM annotations WHERE id = ?", (annotation_id,)
    ).fetchone()
    if row is None:
        raise ValueError(f"annotation {annotation_id!r} not found")
    if kind is not None and kind not in ANNOTATION_KINDS:
        raise ValueError(
            f"invalid annotation kind {kind!r}; expected one of "
            f"{sorted(ANNOTATION_KINDS)}"
        )
    new_body = body if body is not None else row["body"]
    new_kind = kind if kind is not None else row["kind"]
    new_start = start_bar if start_bar is not None else row["start_bar"]
    new_end = end_bar if end_bar is not None else row["end_bar"]
    if new_end is not None and new_start is None:
        raise ValueError("end_bar requires start_bar")
    if new_end is not None and new_end <= new_start:
        raise ValueError(f"end_bar ({new_end}) must be greater than start_bar ({new_start})")
    actor, request_id = _resolve_actor_and_request(actor, request_id)
    conn.execute(
        """UPDATE annotations
               SET body = ?, kind = ?, start_bar = ?, end_bar = ?,
                   updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
               WHERE id = ?""",
        (new_body, new_kind, new_start, new_end, annotation_id),
    )
    _emit(
        conn,
        E.ANNOTATION_UPDATED,
        {
            "annotation_id": annotation_id,
            "song_id": row["song_id"],
            "body": new_body,
            "kind": new_kind,
            "start_bar": new_start,
            "end_bar": new_end,
        },
        song_id=row["song_id"],
        actor=actor,
        request_id=request_id,
        reason=reason,
    )


def delete_annotation(
    conn: sqlite3.Connection,
    *,
    annotation_id: str,
    actor: str = "llm",
    request_id: str | None = None,
    reason: str | None = None,
) -> None:
    """Remove one annotation. No-ops cleanly if already gone (the agent
    might race two delete prompts; emitting the event twice is worse than
    silent absence)."""
    row = conn.execute(
        "SELECT song_id FROM annotations WHERE id = ?", (annotation_id,)
    ).fetchone()
    if row is None:
        return
    conn.execute("DELETE FROM annotations WHERE id = ?", (annotation_id,))
    actor, request_id = _resolve_actor_and_request(actor, request_id)
    _emit(
        conn,
        E.ANNOTATION_REMOVED,
        {"annotation_id": annotation_id, "song_id": row["song_id"]},
        song_id=row["song_id"],
        actor=actor,
        request_id=request_id,
        reason=reason,
    )


def record_markdown_ref(
    conn: sqlite3.Connection,
    *,
    path: str,
    content_hash: str,
    song_id: str | None = None,
    frontmatter: dict[str, Any] | None = None,
    actor: str = "llm",
    request_id: str | None = None,
    reason: str | None = None,
) -> None:
    """Emit a MARKDOWN_REF_RECORDED audit event.

    Fires when an LLM-driven write produces or updates a decision/annotation
    file under `songs/<name>/`. Does NOT touch `markdown_refs` (that's the
    reindexer's job — the projection rebuilds from disk). Threads
    `request_id` so cross-reference queries can answer "which compose
    session produced this decision."

    Reindex of a pre-existing file DOES NOT emit this event — projection
    rebuild is not a domain mutation.
    """
    _emit(
        conn,
        E.MARKDOWN_REF_RECORDED,
        {"path": path, "content_hash": content_hash, "frontmatter": frontmatter},
        song_id=song_id,
        actor=actor,
        request_id=request_id,
        reason=reason,
    )


# ---------------------------------------------------------------------------
# Songs
# ---------------------------------------------------------------------------


TIMING_MODES = frozenset({"native", "grid"})


_SLUG_RE = re.compile(r"[a-z0-9_-]+")


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


# ---------------------------------------------------------------------------
# Tracks
# ---------------------------------------------------------------------------


TRACK_KINDS = frozenset({"midi", "audio", "master", "group"})


def create_track(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    track_index: int,
    name: str,
    instrument_uri: str | None = None,
    kind: str = "midi",
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> str:
    """Create a track. `kind` selects 'midi' (default), 'audio', 'master', or
    'group'. Real returns live in the `returns` table — the `'return'` kind
    on a `tracks` row was dropped V1 close-out 2026-05-17 (schema CHECK
    rejects). Mixer state lives on the row but is set separately via
    `set_track_mixer`."""
    if kind not in TRACK_KINDS:
        raise ValueError(f"invalid kind {kind!r}; expected one of {sorted(TRACK_KINDS)}")
    actor, request_id = _resolve_actor_and_request(actor, request_id)
    existing = conn.execute(
        """SELECT id, name, instrument_uri, kind FROM tracks
           WHERE song_id = ? AND track_index = ?""",
        (song_id, track_index),
    ).fetchone()
    if existing is not None:
        tid = existing["id"]
        if (existing["name"], existing["instrument_uri"], existing["kind"]) == (
            name, instrument_uri, kind,
        ):
            _record_touch_if_session("track", tid)
            return MutatorResult(tid, "unchanged")
        conn.execute(
            """UPDATE tracks SET name = ?, instrument_uri = ?, kind = ?
               WHERE id = ?""",
            (name, instrument_uri, kind, tid),
        )
        _emit(
            conn,
            E.TRACK_UPDATED,
            {"track_id": tid, "track_index": track_index, "name": name,
             "instrument_uri": instrument_uri, "kind": kind},
            song_id=song_id,
            actor=actor,
            request_id=request_id,
            reason=reason,
        )
        _touch_song(conn, song_id)
        _record_touch_if_session("track", tid)
        return MutatorResult(tid, "updated")
    tid = _uuid()
    conn.execute(
        """INSERT INTO tracks
               (id, song_id, track_index, name, instrument_uri, kind)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (tid, song_id, track_index, name, instrument_uri, kind),
    )
    _emit(
        conn,
        E.TRACK_CREATED,
        {
            "track_id": tid,
            "track_index": track_index,
            "name": name,
            "instrument_uri": instrument_uri,
            "kind": kind,
        },
        song_id=song_id,
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    _touch_song(conn, song_id)
    _record_touch_if_session("track", tid)
    return MutatorResult(tid, "created")


_MIXER_FIELDS = {"volume", "pan", "mute", "solo", "arm", "color"}


def set_track_mixer(
    conn: sqlite3.Connection,
    *,
    track_id: str,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
    **changes: Any,
) -> None:
    """Partial mixer update. `changes` keys must be in _MIXER_FIELDS.

    Volume is normalized 0.0–1.0 (Live convention); pan is -1.0..+1.0;
    mute/solo/arm are 0/1; color is RGB int. Schema CHECKs enforce ranges.
    """
    bad = set(changes) - _MIXER_FIELDS
    if bad:
        raise ValueError(f"unsupported fields: {sorted(bad)}")
    if not changes:
        return
    actor, request_id = _resolve_actor_and_request(actor, request_id)
    # Fetch existing values so we can skip when state already matches.
    cols = ", ".join(["song_id"] + list(changes))
    row = conn.execute(
        f"SELECT {cols} FROM tracks WHERE id = ?", (track_id,)
    ).fetchone()
    if row is None:
        return
    # W12-A: idempotent — diff per-field; skip event when no field changes.
    actual_changes = {k: v for k, v in changes.items() if row[k] != v}
    if not actual_changes:
        return
    sets = [f"{k} = ?" for k in actual_changes]
    vals = list(actual_changes.values()) + [track_id]
    conn.execute(f"UPDATE tracks SET {', '.join(sets)} WHERE id = ?", vals)
    _emit(
        conn,
        E.TRACK_MIXER_SET,
        {"track_id": track_id, "changes": actual_changes},
        song_id=row["song_id"],
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    _touch_song(conn, row["song_id"])


# ---------------------------------------------------------------------------
# Clips
# ---------------------------------------------------------------------------


def create_clip(
    conn: sqlite3.Connection,
    *,
    track_id: str,
    slot: int,
    length_beats: float,
    name: str | None = None,
    section_role: str | None = None,
    generator_call: dict[str, Any] | None = None,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> str:
    gen_json = json.dumps(generator_call, separators=(",", ":")) if generator_call else None
    actor, request_id = _resolve_actor_and_request(actor, request_id)
    song_row = conn.execute(
        "SELECT t.song_id FROM tracks t WHERE t.id = ?", (track_id,)
    ).fetchone()
    existing = conn.execute(
        """SELECT id, length_beats, name, section_role, generator_call_json
           FROM clips WHERE track_id = ? AND slot = ?""",
        (track_id, slot),
    ).fetchone()
    if existing is not None:
        cid = existing["id"]
        if (existing["length_beats"], existing["name"], existing["section_role"],
                existing["generator_call_json"]) == (length_beats, name,
                                                     section_role, gen_json):
            _record_touch_if_session("clip", cid)
            return MutatorResult(cid, "unchanged")
        conn.execute(
            """UPDATE clips SET length_beats = ?, name = ?, section_role = ?,
                                generator_call_json = ?,
                                updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
               WHERE id = ?""",
            (length_beats, name, section_role, gen_json, cid),
        )
        _emit(
            conn,
            E.CLIP_UPDATED,
            {"clip_id": cid, "track_id": track_id, "changes": {
                "length_beats": length_beats, "name": name,
                "section_role": section_role,
                "generator_call": generator_call,
            }},
            song_id=song_row["song_id"] if song_row else None,
            clip_id=cid,
            actor=actor,
            request_id=request_id,
            reason=reason,
        )
        _record_touch_if_session("clip", cid)
        return MutatorResult(cid, "updated")
    cid = _uuid()
    conn.execute(
        """INSERT INTO clips
               (id, track_id, slot, length_beats, name, section_role, generator_call_json)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (cid, track_id, slot, length_beats, name, section_role, gen_json),
    )
    _emit(
        conn,
        E.CLIP_CREATED,
        {
            "clip_id": cid,
            "track_id": track_id,
            "slot": slot,
            "length_beats": length_beats,
            "name": name,
            "section_role": section_role,
            "generator_call": generator_call,
        },
        song_id=song_row["song_id"] if song_row else None,
        clip_id=cid,
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    _record_touch_if_session("clip", cid)
    return MutatorResult(cid, "created")


_CLIP_UPDATE_FIELDS = frozenset({"name", "length_beats", "section_role"})


def update_clip(
    conn: sqlite3.Connection,
    *,
    clip_id: str,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
    **changes: Any,
) -> None:
    """Partial update by id. `changes` keys must be in _CLIP_UPDATE_FIELDS.

    Deliberately excludes `track_id` (moving a clip between tracks is
    delete+create), `slot` (slot relocation is delete+create), and
    `generator_call_json` (provenance — append-only-ish). Notes are
    written via `replace_clip_notes` / `insert_notes`, not here.
    """
    bad = set(changes) - _CLIP_UPDATE_FIELDS
    if bad:
        raise ValueError(f"unsupported fields: {sorted(bad)}")
    if not changes:
        return
    row = conn.execute(
        """SELECT c.track_id, t.song_id FROM clips c
           JOIN tracks t ON t.id = c.track_id WHERE c.id = ?""",
        (clip_id,),
    ).fetchone()
    if row is None:
        return
    sets = [f"{k} = ?" for k in changes]
    vals = list(changes.values()) + [clip_id]
    conn.execute(f"UPDATE clips SET {', '.join(sets)} WHERE id = ?", vals)
    _emit(
        conn,
        E.CLIP_UPDATED,
        {"clip_id": clip_id, "track_id": row["track_id"], "changes": changes},
        song_id=row["song_id"],
        clip_id=clip_id,
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    _touch_song(conn, row["song_id"])


def delete_clip(
    conn: sqlite3.Connection,
    *,
    clip_id: str,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> None:
    row = conn.execute(
        """SELECT c.track_id, t.song_id FROM clips c
           JOIN tracks t ON t.id = c.track_id WHERE c.id = ?""",
        (clip_id,),
    ).fetchone()
    if row is None:
        return
    conn.execute("DELETE FROM clips WHERE id = ?", (clip_id,))
    _emit(
        conn,
        E.CLIP_DELETED,
        {"clip_id": clip_id, "track_id": row["track_id"]},
        song_id=row["song_id"],
        actor=actor,
        request_id=request_id,
        reason=reason,
    )


# ---------------------------------------------------------------------------
# Notes
# ---------------------------------------------------------------------------


def _normalize_note(n: NoteDict) -> tuple:
    """Validate + extract canonical fields. Raises KeyError on missing required.

    Arc 6 / H4: rejects ``start_beats < 0`` at the mutator boundary with a
    teaching error pointing at the most common cause — a ``feel`` shift
    that pushed bar-1's downbeat below zero. ``apply_feel`` math itself
    is correct (within-bar positions can shift below 0.0 conceptually);
    the wire layer can't represent it (Live's MIDI clip has no
    negative-beat region). Catching it here puts the diagnostic next to
    the call site that ships invalid data, not the generator that's
    doing math correctly.
    """
    pitch = int(n["pitch"])
    start = float(n["start_beats"])
    if start < 0:
        raise ValueError(
            f"_normalize_note: start_beats={start!r} is negative — Live's "
            "MIDI clip has no negative-beat region. Common cause: a "
            "`feel` dict shifted bar-1's downbeat below zero "
            "(`feel={0.0: -0.02}` on bar 1's start). Either drop the "
            "bar-1 shift, or author a pickup/anacrusis pattern with a "
            "positive offset. The `apply_feel` math is correct in "
            "isolation; this guard catches notes that can't survive the "
            "wire."
        )
    dur = float(n["duration_beats"])
    vel = int(n["velocity"])
    mute = int(n.get("mute", 0))
    tags = n.get("tags")
    tags_json = json.dumps(tags, separators=(",", ":")) if tags else None
    return (pitch, start, dur, vel, mute, tags_json)


def insert_notes(
    conn: sqlite3.Connection,
    *,
    clip_id: str,
    notes: Sequence[NoteDict],
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> list[str]:
    """Append notes to a clip. Returns new note ids in insertion order."""
    if not notes:
        return []
    new_ids: list[str] = []
    for n in notes:
        pitch, start, dur, vel, mute, tags_json = _normalize_note(n)
        nid = _uuid()
        conn.execute(
            """INSERT INTO notes
                   (id, clip_id, pitch, start_beats, duration_beats, velocity, mute, tags_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (nid, clip_id, pitch, start, dur, vel, mute, tags_json),
        )
        new_ids.append(nid)
    _touch_clip(conn, clip_id)
    _emit(
        conn,
        E.NOTES_INSERTED,
        {"clip_id": clip_id, "count": len(new_ids), "note_ids": new_ids},
        clip_id=clip_id,
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    return new_ids


def replace_clip_notes(
    conn: sqlite3.Connection,
    *,
    clip_id: str,
    notes: Sequence[NoteDict],
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> list[str]:
    """Atomic: delete every note for clip, insert fresh set. Single event emitted.

    W12-A: idempotent — when the existing notes (by content, ignoring ids)
    already match the incoming set, the function is a no-op and emits no
    event. Returns the existing note ids in that case (preserves the
    list[str] return contract — same length, same ordering by start_beats).
    """
    actor, request_id = _resolve_actor_and_request(actor, request_id)
    # Idempotency check: compare normalized incoming set vs existing notes.
    incoming = [_normalize_note(n) for n in notes]
    existing_rows = conn.execute(
        """SELECT id, pitch, start_beats, duration_beats, velocity, mute, tags_json
           FROM notes WHERE clip_id = ?
           ORDER BY start_beats, pitch""",
        (clip_id,),
    ).fetchall()
    existing_sig = [
        (r["pitch"], r["start_beats"], r["duration_beats"], r["velocity"],
         r["mute"], r["tags_json"]) for r in existing_rows
    ]
    incoming_sig = sorted(incoming, key=lambda t: (t[1], t[0]))
    existing_sig_sorted = sorted(existing_sig, key=lambda t: (t[1], t[0]))
    if existing_sig_sorted == incoming_sig:
        return [r["id"] for r in conn.execute(
            "SELECT id FROM notes WHERE clip_id = ? ORDER BY start_beats, pitch",
            (clip_id,),
        ).fetchall()]
    with transaction(conn):
        prev_count = len(existing_rows)
        conn.execute("DELETE FROM notes WHERE clip_id = ?", (clip_id,))
        new_ids: list[str] = []
        for n in notes:
            pitch, start, dur, vel, mute, tags_json = _normalize_note(n)
            nid = _uuid()
            conn.execute(
                """INSERT INTO notes
                       (id, clip_id, pitch, start_beats, duration_beats, velocity, mute, tags_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (nid, clip_id, pitch, start, dur, vel, mute, tags_json),
            )
            new_ids.append(nid)
        _touch_clip(conn, clip_id)
        _emit(
            conn,
            E.CLIP_NOTES_REPLACED,
            {
                "clip_id": clip_id,
                "prev_count": prev_count,
                "new_count": len(new_ids),
                "note_ids": new_ids,
            },
            clip_id=clip_id,
            actor=actor,
            request_id=request_id,
            reason=reason,
        )
    return new_ids


_NOTE_FIELDS = {
    "pitch",
    "start_beats",
    "duration_beats",
    "velocity",
    "mute",
    "tags",
}


def update_note(
    conn: sqlite3.Connection,
    *,
    note_id: str,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
    **changes: Any,
) -> None:
    """Partial update by id. `changes` keys must be in _NOTE_FIELDS."""
    bad = set(changes) - _NOTE_FIELDS
    if bad:
        raise ValueError(f"unsupported fields: {sorted(bad)}")
    if not changes:
        return

    sets: list[str] = []
    vals: list[Any] = []
    for k, v in changes.items():
        if k == "tags":
            sets.append("tags_json = ?")
            vals.append(json.dumps(v, separators=(",", ":")) if v else None)
        else:
            sets.append(f"{k} = ?")
            vals.append(v)
    vals.append(note_id)

    clip_row = conn.execute("SELECT clip_id FROM notes WHERE id = ?", (note_id,)).fetchone()
    if clip_row is None:
        return
    conn.execute(f"UPDATE notes SET {', '.join(sets)} WHERE id = ?", vals)
    _touch_clip(conn, clip_row["clip_id"])
    _emit(
        conn,
        E.NOTE_UPDATED,
        {"note_id": note_id, "changes": changes},
        clip_id=clip_row["clip_id"],
        actor=actor,
        request_id=request_id,
        reason=reason,
    )


def delete_notes(
    conn: sqlite3.Connection,
    *,
    note_ids: Sequence[str],
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> None:
    if not note_ids:
        return
    placeholders = ",".join("?" * len(note_ids))
    rows = conn.execute(
        f"SELECT DISTINCT clip_id FROM notes WHERE id IN ({placeholders})",
        tuple(note_ids),
    ).fetchall()
    affected_clips = [r["clip_id"] for r in rows]
    conn.execute(f"DELETE FROM notes WHERE id IN ({placeholders})", tuple(note_ids))
    for cid in affected_clips:
        _touch_clip(conn, cid)
    _emit(
        conn,
        E.NOTES_DELETED,
        {"note_ids": list(note_ids), "affected_clips": affected_clips},
        actor=actor,
        request_id=request_id,
        reason=reason,
    )


def update_notes_by_tag(
    conn: sqlite3.Connection,
    *,
    clip_id: str,
    tag: str,
    velocity_delta: int | None = None,
    velocity_set: int | None = None,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> int:
    """Bulk-update notes in clip carrying `tag`. Returns count updated.

    Matched in Python (json_each could be used; trivial scale doesn't justify it yet).
    """
    if velocity_delta is None and velocity_set is None:
        raise ValueError("specify velocity_delta or velocity_set")
    if velocity_delta is not None and velocity_set is not None:
        raise ValueError("only one of velocity_delta / velocity_set")

    rows = conn.execute(
        "SELECT id, velocity, tags_json FROM notes WHERE clip_id = ?",
        (clip_id,),
    ).fetchall()

    matched: list[tuple[str, int, int]] = []  # (id, old_vel, new_vel)
    for r in rows:
        if not r["tags_json"]:
            continue
        tags = json.loads(r["tags_json"])
        if tag not in tags:
            continue
        old_vel = r["velocity"]
        if velocity_delta is not None:
            new_vel = max(0, min(127, old_vel + velocity_delta))
        else:
            new_vel = max(0, min(127, velocity_set))  # type: ignore[arg-type]
        matched.append((r["id"], old_vel, new_vel))

    for note_id, _old, new_vel in matched:
        conn.execute("UPDATE notes SET velocity = ? WHERE id = ?", (new_vel, note_id))

    if matched:
        _touch_clip(conn, clip_id)
    _emit(
        conn,
        E.NOTES_BULK_UPDATED,
        {
            "clip_id": clip_id,
            "where_tag": tag,
            "count": len(matched),
            "velocity_delta": velocity_delta,
            "velocity_set": velocity_set,
            "note_ids": [m[0] for m in matched],
        },
        clip_id=clip_id,
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    return len(matched)


# ---------------------------------------------------------------------------
# Arrangement clips
# ---------------------------------------------------------------------------


def add_arrangement_clip(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    track_id: str,
    clip_id: str,
    start_bar: float,
    end_bar: float,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> str:
    actor, request_id = _resolve_actor_and_request(actor, request_id)
    existing = conn.execute(
        """SELECT id, end_bar FROM arrangement_clips
           WHERE song_id = ? AND track_id = ? AND clip_id = ? AND start_bar = ?""",
        (song_id, track_id, clip_id, start_bar),
    ).fetchone()
    if existing is not None:
        aid = existing["id"]
        if existing["end_bar"] == end_bar:
            _record_touch_if_session("arrangement_clip", aid)
            return MutatorResult(aid, "unchanged")
        conn.execute(
            "UPDATE arrangement_clips SET end_bar = ? WHERE id = ?",
            (end_bar, aid),
        )
        _emit(
            conn,
            E.ARRANGEMENT_CLIP_ADDED,
            {"arrangement_clip_id": aid, "track_id": track_id,
             "clip_id": clip_id, "start_bar": start_bar, "end_bar": end_bar,
             "kind": "updated"},
            song_id=song_id, clip_id=clip_id,
            actor=actor, request_id=request_id, reason=reason,
        )
        _record_touch_if_session("arrangement_clip", aid)
        return MutatorResult(aid, "updated")
    aid = _uuid()
    conn.execute(
        """INSERT INTO arrangement_clips (id, song_id, track_id, clip_id, start_bar, end_bar)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (aid, song_id, track_id, clip_id, start_bar, end_bar),
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
        },
        song_id=song_id,
        clip_id=clip_id,
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    _record_touch_if_session("arrangement_clip", aid)
    return MutatorResult(aid, "created")


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
# Score: sections
# ---------------------------------------------------------------------------


def create_section(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    name: str,
    start_bar: float,
    end_bar: float,
    color: int | None = None,
    notes_md: str | None = None,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> str:
    """Mark a named span of bars (verse, chorus, bridge, ...). DB-only metadata
    unless Live exposes section markers; surfaces in event log either way."""
    if end_bar <= start_bar:
        raise ValueError(f"end_bar ({end_bar}) must exceed start_bar ({start_bar})")
    actor, request_id = _resolve_actor_and_request(actor, request_id)
    existing = conn.execute(
        """SELECT id, end_bar, color, notes_md FROM sections
           WHERE song_id = ? AND name = ? AND start_bar = ?""",
        (song_id, name, start_bar),
    ).fetchone()
    if existing is not None:
        sid = existing["id"]
        if (existing["end_bar"], existing["color"], existing["notes_md"]) == (
            end_bar, color, notes_md,
        ):
            _record_touch_if_session("section", sid)
            return MutatorResult(sid, "unchanged")
        conn.execute(
            """UPDATE sections SET end_bar = ?, color = ?, notes_md = ?
               WHERE id = ?""",
            (end_bar, color, notes_md, sid),
        )
        _emit(
            conn, E.SECTION_UPDATED,
            {"section_id": sid, "changes": {"end_bar": end_bar,
             "color": color, "notes_md": notes_md}},
            song_id=song_id, actor=actor, request_id=request_id, reason=reason,
        )
        _touch_song(conn, song_id)
        _record_touch_if_session("section", sid)
        return MutatorResult(sid, "updated")
    sid = _uuid()
    conn.execute(
        """INSERT INTO sections
               (id, song_id, name, start_bar, end_bar, color, notes_md)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (sid, song_id, name, start_bar, end_bar, color, notes_md),
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
        },
        song_id=song_id,
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    _touch_song(conn, song_id)
    _record_touch_if_session("section", sid)
    return MutatorResult(sid, "created")


_SECTION_FIELDS = {"name", "start_bar", "end_bar", "color", "notes_md"}


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
    """Add a meter change at `start_bar` (numerator/denominator)."""
    if numerator <= 0 or denominator <= 0:
        raise ValueError(
            f"numerator/denominator must be positive, got {numerator}/{denominator}"
        )
    actor, request_id = _resolve_actor_and_request(actor, request_id)
    # W10-H: refuse to author meter changes after bar 1. Live 12.4's MCP
    # has no `song_signature` automation target_kind, so within-song meter
    # ratchets can't reach Live. Per user 2026-05-19, ship loud refusal at
    # both DB-mutator and planner layers (dual-layer pattern matching D2);
    # punt the working impl to v1.1 (per-bar-arrangement-clip workaround).
    # Idempotent re-adds at start_bar > 1.0 only fail if no row exists yet —
    # if a row at this position already exists with matching values, the
    # upsert path below returns "unchanged" silently (no new state).
    # Guard fires only for start_bar > 1.0 — the policy is "no within-song
    # ratchet"; bar-1 is the global meter (always allowed) and start_bar < 1.0
    # falls through to the schema CHECK (also rejected, with a different
    # error). The W12-A idempotency contract is preserved: if a row at
    # this position already exists with matching values, we still fall
    # through to the upsert path which returns "unchanged".
    if start_bar > 1.0:
        existing_at_pos = conn.execute(
            """SELECT id, numerator, denominator FROM time_signature_map
               WHERE song_id = ? AND start_bar = ?""",
            (song_id, start_bar),
        ).fetchone()
        if existing_at_pos is None or (
            existing_at_pos["numerator"], existing_at_pos["denominator"]
        ) != (numerator, denominator):
            raise ValueError(
                f"add_time_signature_point: refusing to author meter at "
                f"start_bar={start_bar} — Live 12.4's MCP has no "
                f"`song_signature` automation target_kind, so within-song "
                f"meter ratchets can't reach Live. Use a single global "
                f"meter (one row at start_bar=1.0) for v1; the per-bar-"
                f"arrangement-clip workaround is v1.1 scope (W10-H/v1.1). "
                f"See ableton://guides/gaps for the LOM constraint."
            )
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
        """SELECT song_id, start_bar FROM time_signature_map WHERE id = ?""",
        (point_id,),
    ).fetchone()
    if row is None:
        return
    # W10-H: updates to post-bar-1 rows are refused for the same reason
    # adds are (no MCP path for per-bar meter automation). Updates at
    # bar 1 are fine — that's the global meter. Pre-bar-1 rows shouldn't
    # exist (schema CHECK rejects start_bar < 1.0), but if one does,
    # refuse out of paranoia.
    if row["start_bar"] != 1.0:
        raise ValueError(
            f"update_time_signature_point: refusing to update meter at "
            f"start_bar={row['start_bar']} — Live 12.4's MCP has no "
            f"`song_signature` automation target_kind, so within-song "
            f"meter ratchets can't reach Live. Use a single global meter "
            f"(one row at start_bar=1.0) for v1. See ableton://guides/gaps."
        )
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


# ---------------------------------------------------------------------------
# Score: cue points (arrangement markers)
# ---------------------------------------------------------------------------


def add_cue_point(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    position_bar: float,
    name: str | None = None,
    color: int | None = None,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> str:
    """Add an arrangement marker at `position_bar`. Maps to Live's cue points.

    Idempotent by `(song_id, position_bar)`: a second call at the same
    position with the same name/color is a no-op; with different name/color
    it updates the existing cue. Use `remove_cue_point` + add to move a cue.
    """
    actor, request_id = _resolve_actor_and_request(actor, request_id)
    existing = conn.execute(
        """SELECT id, name, color FROM cue_points
           WHERE song_id = ? AND position_bar = ?""",
        (song_id, position_bar),
    ).fetchone()
    if existing is not None:
        pid = existing["id"]
        if (existing["name"], existing["color"]) == (name, color):
            _record_touch_if_session("cue_point", pid)
            return MutatorResult(pid, "unchanged")
        conn.execute(
            "UPDATE cue_points SET name = ?, color = ? WHERE id = ?",
            (name, color, pid),
        )
        _emit(
            conn, E.CUE_POINT_ADDED,
            {"cue_id": pid, "position_bar": position_bar, "name": name,
             "color": color, "kind": "updated"},
            song_id=song_id, actor=actor, request_id=request_id, reason=reason,
        )
        _touch_song(conn, song_id)
        _record_touch_if_session("cue_point", pid)
        return MutatorResult(pid, "updated")
    pid = _uuid()
    conn.execute(
        """INSERT INTO cue_points (id, song_id, position_bar, name, color)
           VALUES (?, ?, ?, ?, ?)""",
        (pid, song_id, position_bar, name, color),
    )
    _emit(
        conn,
        E.CUE_POINT_ADDED,
        {
            "cue_id": pid,
            "position_bar": position_bar,
            "name": name,
            "color": color,
        },
        song_id=song_id,
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    _touch_song(conn, song_id)
    _record_touch_if_session("cue_point", pid)
    return MutatorResult(pid, "created")


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


# ---------------------------------------------------------------------------
# Mix: returns + sends
# ---------------------------------------------------------------------------


def create_return(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    name: str,
    position: int,
    volume: float | None = None,
    pan: float | None = None,
    color: int | None = None,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> str:
    """Create a return track. `position` is the return's index in Live (1-based,
    matching captured_session.json). Volume/pan optional; default state is
    whatever Live applies to a freshly-created return.

    Arc 7 / P7: `name` is normalized through `strip_return_slot_prefix`
    so a caller (build.py, snapshot replay) passing Live's `<letter>-`
    prefixed form can't poison the DB. Returns store SUFFIX-only names
    (W4-C convention). Idempotent: already-stripped names pass through.
    """
    name = strip_return_slot_prefix(name)
    actor, request_id = _resolve_actor_and_request(actor, request_id)
    existing = conn.execute(
        """SELECT id, name, volume, pan, color FROM returns
           WHERE song_id = ? AND position = ?""",
        (song_id, position),
    ).fetchone()
    if existing is not None:
        rid = existing["id"]
        if (existing["name"], existing["volume"], existing["pan"],
                existing["color"]) == (name, volume, pan, color):
            _record_touch_if_session("return", rid)
            return MutatorResult(rid, "unchanged")
        conn.execute(
            """UPDATE returns SET name = ?, volume = ?, pan = ?, color = ?
               WHERE id = ?""",
            (name, volume, pan, color, rid),
        )
        _emit(
            conn, E.RETURN_UPDATED,
            {"return_id": rid, "changes": {"name": name, "volume": volume,
                                            "pan": pan, "color": color}},
            song_id=song_id, actor=actor, request_id=request_id, reason=reason,
        )
        _touch_song(conn, song_id)
        _record_touch_if_session("return", rid)
        return MutatorResult(rid, "updated")
    rid = _uuid()
    conn.execute(
        """INSERT INTO returns
               (id, song_id, name, position, volume, pan, color)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (rid, song_id, name, position, volume, pan, color),
    )
    _emit(
        conn,
        E.RETURN_CREATED,
        {
            "return_id": rid,
            "name": name,
            "position": position,
            "volume": volume,
            "pan": pan,
            "color": color,
        },
        song_id=song_id,
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    _touch_song(conn, song_id)
    _record_touch_if_session("return", rid)
    return MutatorResult(rid, "created")


_RETURN_FIELDS = {"name", "position", "volume", "pan", "mute", "solo", "color"}


def update_return(
    conn: sqlite3.Connection,
    *,
    return_id: str,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
    **changes: Any,
) -> None:
    """Partial update by id. `changes` keys must be in _RETURN_FIELDS.

    Arc 7 / P7: when `name` is updated, normalize through
    `strip_return_slot_prefix` so callers can't sneak Live's
    `<letter>-` slot prefix into the DB (mirrors `create_return`).
    """
    bad = set(changes) - _RETURN_FIELDS
    if bad:
        raise ValueError(f"unsupported fields: {sorted(bad)}")
    if not changes:
        return
    if "name" in changes:
        changes["name"] = strip_return_slot_prefix(changes["name"])
    row = conn.execute(
        "SELECT song_id FROM returns WHERE id = ?", (return_id,)
    ).fetchone()
    if row is None:
        return
    sets = [f"{k} = ?" for k in changes]
    vals = list(changes.values()) + [return_id]
    conn.execute(f"UPDATE returns SET {', '.join(sets)} WHERE id = ?", vals)
    _emit(
        conn,
        E.RETURN_UPDATED,
        {"return_id": return_id, "changes": changes},
        song_id=row["song_id"],
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    _touch_song(conn, row["song_id"])


def delete_return(
    conn: sqlite3.Connection,
    *,
    return_id: str,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> None:
    row = conn.execute(
        "SELECT song_id FROM returns WHERE id = ?", (return_id,)
    ).fetchone()
    if row is None:
        return
    conn.execute("DELETE FROM returns WHERE id = ?", (return_id,))
    _emit(
        conn,
        E.RETURN_DELETED,
        {"return_id": return_id},
        song_id=row["song_id"],
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    _touch_song(conn, row["song_id"])


def set_send_level(
    conn: sqlite3.Connection,
    *,
    from_track_id: str,
    to_return_id: str,
    level: float,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> None:
    """Upsert send level for (from_track, to_return). `level` is normalized
    0.0–1.0 to match track volume conventions."""
    if not (0.0 <= level <= 1.0):
        raise ValueError(f"level {level} out of range [0.0, 1.0]")
    actor, request_id = _resolve_actor_and_request(actor, request_id)
    # Resolve song for the emitted event — track and return must share a song.
    track_row = conn.execute(
        "SELECT song_id FROM tracks WHERE id = ?", (from_track_id,)
    ).fetchone()
    ret_row = conn.execute(
        "SELECT song_id FROM returns WHERE id = ?", (to_return_id,)
    ).fetchone()
    if track_row is None or ret_row is None:
        raise ValueError(
            f"send endpoints missing: track={from_track_id!r}, return={to_return_id!r}"
        )
    if track_row["song_id"] != ret_row["song_id"]:
        raise ValueError(
            "cross-song send: track and return belong to different songs"
        )
    # W12-A: idempotent — skip when the existing level matches.
    existing = conn.execute(
        "SELECT level FROM sends WHERE from_track_id = ? AND to_return_id = ?",
        (from_track_id, to_return_id),
    ).fetchone()
    if existing is not None and existing["level"] == level:
        return
    conn.execute(
        """INSERT INTO sends (from_track_id, to_return_id, level)
           VALUES (?, ?, ?)
           ON CONFLICT(from_track_id, to_return_id)
           DO UPDATE SET level = excluded.level""",
        (from_track_id, to_return_id, level),
    )
    _emit(
        conn,
        E.SEND_SET,
        {
            "from_track_id": from_track_id,
            "to_return_id": to_return_id,
            "level": level,
        },
        song_id=track_row["song_id"],
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    _touch_song(conn, track_row["song_id"])


def remove_send(
    conn: sqlite3.Connection,
    *,
    from_track_id: str,
    to_return_id: str,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> None:
    track_row = conn.execute(
        "SELECT song_id FROM tracks WHERE id = ?", (from_track_id,)
    ).fetchone()
    if track_row is None:
        return
    cur = conn.execute(
        "DELETE FROM sends WHERE from_track_id = ? AND to_return_id = ?",
        (from_track_id, to_return_id),
    )
    if cur.rowcount == 0:
        return
    _emit(
        conn,
        E.SEND_REMOVED,
        {"from_track_id": from_track_id, "to_return_id": to_return_id},
        song_id=track_row["song_id"],
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    _touch_song(conn, track_row["song_id"])


# ---------------------------------------------------------------------------
# Mix: device chains, devices, parameters
# ---------------------------------------------------------------------------
# Parent enforcement: `create_device_chain` accepts exactly one of three
# parent kwargs. The schema CHECK also enforces this, but raising in Python
# yields a clean error before the DB does. Top-level chains (track / return)
# use position=0 by convention; rack chains use their position within the
# parent rack device.


def create_device_chain(
    conn: sqlite3.Connection,
    *,
    parent_track_id: str | None = None,
    parent_return_id: str | None = None,
    parent_rack_device_id: str | None = None,
    position: int = 0,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> str:
    parents = [
        ("parent_track_id", parent_track_id),
        ("parent_return_id", parent_return_id),
        ("parent_rack_device_id", parent_rack_device_id),
    ]
    set_parents = [(k, v) for k, v in parents if v is not None]
    if len(set_parents) != 1:
        raise ValueError(
            f"create_device_chain: exactly one parent kwarg required, "
            f"got {[k for k, _ in set_parents]}"
        )
    actor, request_id = _resolve_actor_and_request(actor, request_id)
    # Identity by (parent_*_id, position). Each parent column is mutually
    # exclusive by schema CHECK, so the SELECT below matches on the one set.
    existing = conn.execute(
        """SELECT id FROM device_chains
           WHERE parent_track_id IS ? AND parent_return_id IS ?
             AND parent_rack_device_id IS ? AND position = ?""",
        (parent_track_id, parent_return_id, parent_rack_device_id, position),
    ).fetchone()
    if existing is not None:
        # device_chains has no non-identity fields — existing match means
        # unchanged by definition.
        chain_id = existing["id"]
        _record_touch_if_session("device_chain", chain_id)
        return MutatorResult(chain_id, "unchanged")
    chain_id = _uuid()
    conn.execute(
        """INSERT INTO device_chains
               (id, parent_track_id, parent_return_id, parent_rack_device_id, position)
           VALUES (?, ?, ?, ?, ?)""",
        (chain_id, parent_track_id, parent_return_id, parent_rack_device_id, position),
    )
    # Resolve song_id for the event so audit queries find it via song.
    song_id = _resolve_chain_song(
        conn,
        parent_track_id=parent_track_id,
        parent_return_id=parent_return_id,
        parent_rack_device_id=parent_rack_device_id,
    )
    _emit(
        conn,
        E.DEVICE_CHAIN_CREATED,
        {
            "chain_id": chain_id,
            "parent_track_id": parent_track_id,
            "parent_return_id": parent_return_id,
            "parent_rack_device_id": parent_rack_device_id,
            "position": position,
        },
        song_id=song_id,
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    if song_id:
        _touch_song(conn, song_id)
    _record_touch_if_session("device_chain", chain_id)
    return MutatorResult(chain_id, "created")


def _resolve_chain_song(
    conn: sqlite3.Connection,
    *,
    parent_track_id: str | None,
    parent_return_id: str | None,
    parent_rack_device_id: str | None,
) -> str | None:
    """Walk a chain's parent up to its song_id. Nested rack chains recurse
    through their parent device's chain until reaching a track or return."""
    if parent_track_id is not None:
        row = conn.execute(
            "SELECT song_id FROM tracks WHERE id = ?", (parent_track_id,)
        ).fetchone()
        return row["song_id"] if row else None
    if parent_return_id is not None:
        row = conn.execute(
            "SELECT song_id FROM returns WHERE id = ?", (parent_return_id,)
        ).fetchone()
        return row["song_id"] if row else None
    if parent_rack_device_id is not None:
        # Device -> its chain -> recurse on that chain's parent.
        row = conn.execute(
            """SELECT dc.parent_track_id, dc.parent_return_id, dc.parent_rack_device_id
               FROM devices d
               JOIN device_chains dc ON dc.id = d.chain_id
               WHERE d.id = ?""",
            (parent_rack_device_id,),
        ).fetchone()
        if row is None:
            return None
        return _resolve_chain_song(
            conn,
            parent_track_id=row["parent_track_id"],
            parent_return_id=row["parent_return_id"],
            parent_rack_device_id=row["parent_rack_device_id"],
        )
    return None


def delete_device_chain(
    conn: sqlite3.Connection,
    *,
    chain_id: str,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> None:
    row = conn.execute(
        """SELECT parent_track_id, parent_return_id, parent_rack_device_id
           FROM device_chains WHERE id = ?""",
        (chain_id,),
    ).fetchone()
    if row is None:
        return
    song_id = _resolve_chain_song(
        conn,
        parent_track_id=row["parent_track_id"],
        parent_return_id=row["parent_return_id"],
        parent_rack_device_id=row["parent_rack_device_id"],
    )
    conn.execute("DELETE FROM device_chains WHERE id = ?", (chain_id,))
    _emit(
        conn,
        E.DEVICE_CHAIN_DELETED,
        {"chain_id": chain_id},
        song_id=song_id,
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    if song_id:
        _touch_song(conn, song_id)


def create_device(
    conn: sqlite3.Connection,
    *,
    chain_id: str,
    position: int,
    kind: str,
    display_name: str,
    class_name: str | None = None,
    preset_uri: str | None = None,
    preset_query: dict[str, Any] | str | None = None,
    browser_path: list[str] | None = None,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> str:
    """Create a device in `chain_id` at 1-based `position`.

    Arc 4 / D4 convention:
    - ``kind`` is the BROWSER DISPLAY NAME (= Live's
      ``device.class_display_name``): ``"Compressor"`` / ``"Phaser-Flanger"``
      / ``"EQ Eight"`` / ``"Operator"``. The loader's kind-as-given walk
      matches against this directly in Live's browser tree.
    - ``class_name`` (optional) is Live's INTERNAL class identifier:
      ``"Compressor2"`` / ``"PhaserNew"`` / ``"PluginDevice"``.
      Informational + drives plugin classification (compat-check reads
      this to detect third-party plugins). Captured-from-Live writes
      populate it; hand-authored snapshots may omit it.
    - ``display_name`` is the user-visible instance label. Often equals
      ``kind`` for default loads; diverges on preset loads (``"Hall"``
      on a Hybrid Reverb) and user renames (``"Bass Squish"`` on a
      Compressor).

    ``preset_uri`` and ``preset_query`` are mutually exclusive selectors —
    pass one or the other (or neither, for kind-only loading).
    ``preset_query`` is the compose-time portable form (Sweep B): a dict
    ``{root, pattern, mode?, path_prefix?, case_sensitive?}`` stored as
    JSON; the push planner threads it through to
    ``ableton_device(action='load', preset_query=...)`` which resolves on the
    consumer's machine. ``preset_uri`` is the per-machine canonical URI.

    Arc 3 / C2: ``preset_query`` also accepts a path-shape string like
    ``"Drums/Kit-Core 909"`` — normalized to the canonical dict via
    :func:`hallucinote.preset_query.parse_path_shape` before persistence.
    """
    if position < 1:
        raise ValueError(f"device position {position} must be >= 1")
    if preset_uri is not None and preset_query is not None:
        raise ValueError(
            "preset_uri and preset_query are mutually exclusive — pass one "
            "(preset_query for cross-machine portability, preset_uri for "
            "an unambiguous per-machine URI)"
        )
    if browser_path is not None:
        if (
            not isinstance(browser_path, list)
            or len(browser_path) < 1
            or not all(isinstance(s, str) and s for s in browser_path)
        ):
            raise ValueError(
                "browser_path must be a non-empty list of non-empty strings "
                "from the browser root to the loaded item — got "
                f"{browser_path!r}"
            )
    preset_query = _normalize_preset_query(preset_query)
    actor, request_id = _resolve_actor_and_request(actor, request_id)
    preset_query_json = (
        json.dumps(preset_query, sort_keys=True) if preset_query is not None
        else None
    )
    browser_path_json = (
        json.dumps(browser_path) if browser_path is not None else None
    )
    existing = conn.execute(
        """SELECT id, kind, display_name, class_name, preset_uri, preset_query,
                  browser_path_json
           FROM devices WHERE chain_id = ? AND position = ?""",
        (chain_id, position),
    ).fetchone()
    if existing is not None:
        device_id = existing["id"]
        existing_browser_path_json = (
            existing["browser_path_json"]
            if "browser_path_json" in existing.keys() else None
        )
        if (
            existing["kind"], existing["display_name"], existing["class_name"],
            existing["preset_uri"], existing["preset_query"],
            existing_browser_path_json,
        ) == (
            kind, display_name, class_name, preset_uri, preset_query_json,
            browser_path_json,
        ):
            _record_touch_if_session("device", device_id)
            return MutatorResult(device_id, "unchanged")
        conn.execute(
            """UPDATE devices SET kind = ?, display_name = ?, class_name = ?,
                                  preset_uri = ?, preset_query = ?,
                                  browser_path_json = ?
               WHERE id = ?""",
            (kind, display_name, class_name, preset_uri, preset_query_json,
             browser_path_json, device_id),
        )
        song_id = _resolve_device_song(conn, device_id=device_id)
        _emit(
            conn, E.DEVICE_CREATED,
            {"device_id": device_id, "chain_id": chain_id, "position": position,
             "kind": kind, "display_name": display_name,
             "class_name": class_name,
             "preset_uri": preset_uri, "preset_query": preset_query,
             "browser_path": browser_path,
             "result_kind": "updated"},
            song_id=song_id, actor=actor, request_id=request_id, reason=reason,
        )
        if song_id:
            _touch_song(conn, song_id)
        _record_touch_if_session("device", device_id)
        return MutatorResult(device_id, "updated")
    device_id = _uuid()
    conn.execute(
        """INSERT INTO devices (id, chain_id, position, kind, display_name,
                                class_name, preset_uri, preset_query,
                                browser_path_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (device_id, chain_id, position, kind, display_name,
         class_name, preset_uri, preset_query_json, browser_path_json),
    )
    song_id = _resolve_device_song(conn, device_id=device_id)
    _emit(
        conn,
        E.DEVICE_CREATED,
        {
            "device_id": device_id,
            "chain_id": chain_id,
            "position": position,
            "kind": kind,
            "display_name": display_name,
            "class_name": class_name,
            "preset_uri": preset_uri,
            "preset_query": preset_query,
            "browser_path": browser_path,
        },
        song_id=song_id,
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    if song_id:
        _touch_song(conn, song_id)
    _record_touch_if_session("device", device_id)
    return MutatorResult(device_id, "created")


def _resolve_device_song(
    conn: sqlite3.Connection,
    *,
    device_id: str,
) -> str | None:
    row = conn.execute(
        """SELECT dc.parent_track_id, dc.parent_return_id, dc.parent_rack_device_id
           FROM devices d
           JOIN device_chains dc ON dc.id = d.chain_id
           WHERE d.id = ?""",
        (device_id,),
    ).fetchone()
    if row is None:
        return None
    return _resolve_chain_song(
        conn,
        parent_track_id=row["parent_track_id"],
        parent_return_id=row["parent_return_id"],
        parent_rack_device_id=row["parent_rack_device_id"],
    )


def delete_device(
    conn: sqlite3.Connection,
    *,
    device_id: str,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> None:
    song_id = _resolve_device_song(conn, device_id=device_id)
    cur = conn.execute("DELETE FROM devices WHERE id = ?", (device_id,))
    if cur.rowcount == 0:
        return
    _emit(
        conn,
        E.DEVICE_DELETED,
        {"device_id": device_id},
        song_id=song_id,
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    if song_id:
        _touch_song(conn, song_id)


def set_device_parameter(
    conn: sqlite3.Connection,
    *,
    device_id: str,
    name: str,
    value_display: str,
    value_normalized: float | None = None,
    value_items: Sequence[str] | None = None,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> str:
    """Upsert a device parameter by (device_id, name). Returns parameter id.

    `value_display` is always set (the human-readable form). `value_normalized`
    is optional — discrete-enum parameters (e.g., Filter Type = "Lowpass")
    have no continuous form.

    `value_items` is the enum cardinality — Live's `value_items` tuple for
    discrete-enum params, in order (index in the tuple = numeric value
    Live stores). Persisted as JSON; NULL for continuous params. Captured
    at pull time when present; the enum-aware envelope helper reads it
    back to resolve enum-name breakpoints at compose time.
    """
    if value_normalized is not None and not (0.0 <= value_normalized <= 1.0):
        raise ValueError(
            f"value_normalized {value_normalized} out of range [0.0, 1.0]"
        )
    value_items_json: str | None = None
    if value_items is not None:
        items_list = [str(item) for item in value_items]
        if items_list:
            value_items_json = json.dumps(items_list)
    actor, request_id = _resolve_actor_and_request(actor, request_id)
    existing = conn.execute(
        """SELECT id, value_display, value_normalized, value_items_json
             FROM device_parameters
           WHERE device_id = ? AND name = ?""",
        (device_id, name),
    ).fetchone()
    if existing is not None:
        param_id = existing["id"]
        if (
            existing["value_display"],
            existing["value_normalized"],
            existing["value_items_json"],
        ) == (value_display, value_normalized, value_items_json):
            _record_touch_if_session("device_parameter", param_id)
            return MutatorResult(param_id, "unchanged")
        conn.execute(
            """UPDATE device_parameters
                  SET value_display = ?,
                      value_normalized = ?,
                      value_items_json = ?
                WHERE id = ?""",
            (value_display, value_normalized, value_items_json, param_id),
        )
        result_kind = "updated"
    else:
        param_id = _uuid()
        conn.execute(
            """INSERT INTO device_parameters
                   (id, device_id, name, value_display,
                    value_normalized, value_items_json)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (param_id, device_id, name, value_display,
             value_normalized, value_items_json),
        )
        result_kind = "created"
    song_id = _resolve_device_song(conn, device_id=device_id)
    _emit(
        conn,
        E.DEVICE_PARAMETER_SET,
        {
            "parameter_id": param_id,
            "device_id": device_id,
            "name": name,
            "value_display": value_display,
            "value_normalized": value_normalized,
            "value_items_json": value_items_json,
        },
        song_id=song_id,
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    if song_id:
        _touch_song(conn, song_id)
    _record_touch_if_session("device_parameter", param_id)
    return MutatorResult(param_id, result_kind)


def remove_device_parameter(
    conn: sqlite3.Connection,
    *,
    device_id: str,
    name: str,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> None:
    cur = conn.execute(
        "DELETE FROM device_parameters WHERE device_id = ? AND name = ?",
        (device_id, name),
    )
    if cur.rowcount == 0:
        return
    song_id = _resolve_device_song(conn, device_id=device_id)
    _emit(
        conn,
        E.DEVICE_PARAMETER_REMOVED,
        {"device_id": device_id, "name": name},
        song_id=song_id,
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    if song_id:
        _touch_song(conn, song_id)


# ---------------------------------------------------------------------------
# Mix: Drum Rack pad mappings (M1-C)
# ---------------------------------------------------------------------------
# Each row binds one MIDI note on a Drum Rack to the verbatim Live chain
# name at that pad. Canonicalization (chain_name → "kick" / "snare" /
# "hat_closed") happens at READ time in `hallucinote.generators.kit.Kit`,
# not on the way in — preserves Live's name so canonicalization rules can
# evolve without DB rewrites.
#
# Replace-style mutator (mirrors `replace_breakpoints`). A capture probe
# emits a full pad list per Drum Rack device; the mutator atomically
# deletes the old set and inserts the new one in a single transaction
# with a single event.


def replace_drum_pad_mappings(
    conn: sqlite3.Connection,
    *,
    device_id: str,
    mappings: Sequence[dict[str, Any]],
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> list[str]:
    """Atomic: delete every drum_pad_mappings row for ``device_id``, insert
    the new set. Returns the new mapping ids in insertion order. One event.

    Each mapping dict: ``{chain_name: str, midi_note: int}``. The mutator
    rejects mappings with midi_note outside [0, 127] (the schema CHECK
    enforces too, but surfacing it here gives a better error).

    W12-A: idempotent — when the existing rows already match the incoming
    set (by content), the function is a no-op and emits no event.
    """
    actor, request_id = _resolve_actor_and_request(actor, request_id)
    incoming_sig: list[tuple[str, int]] = []
    for m in mappings:
        chain_name = str(m.get("chain_name", ""))
        midi_note = int(m["midi_note"])
        if midi_note < 0 or midi_note > 127:
            raise ValueError(
                f"replace_drum_pad_mappings: midi_note {midi_note} out of "
                "MIDI range [0, 127]"
            )
        if not chain_name:
            raise ValueError(
                "replace_drum_pad_mappings: chain_name must be non-empty "
                f"(got {m!r})"
            )
        incoming_sig.append((chain_name, midi_note))
    existing_rows = conn.execute(
        """SELECT id, chain_name, midi_note FROM drum_pad_mappings
           WHERE device_id = ? ORDER BY midi_note""",
        (device_id,),
    ).fetchall()
    existing_sig = [(r["chain_name"], r["midi_note"]) for r in existing_rows]
    if sorted(existing_sig) == sorted(incoming_sig):
        return [r["id"] for r in existing_rows]
    with transaction(conn):
        prev_count = len(existing_rows)
        conn.execute(
            "DELETE FROM drum_pad_mappings WHERE device_id = ?",
            (device_id,),
        )
        new_ids: list[str] = []
        for chain_name, midi_note in incoming_sig:
            mid = _uuid()
            conn.execute(
                """INSERT INTO drum_pad_mappings
                       (id, device_id, chain_name, midi_note)
                   VALUES (?, ?, ?, ?)""",
                (mid, device_id, chain_name, midi_note),
            )
            new_ids.append(mid)
        song_id = _resolve_device_song(conn, device_id=device_id)
        _emit(
            conn,
            E.DRUM_PAD_MAPPINGS_REPLACED,
            {
                "device_id": device_id,
                "prev_count": prev_count,
                "new_count": len(new_ids),
                "mapping_ids": new_ids,
            },
            song_id=song_id,
            actor=actor,
            request_id=request_id,
            reason=reason,
        )
        if song_id:
            _touch_song(conn, song_id)
    return new_ids


# ---------------------------------------------------------------------------
# Mix: automation envelopes + breakpoints
# ---------------------------------------------------------------------------
# Unified shape per target_kind. The mutator validates that the right target
# kwarg is set for the given kind, that parameter_path is present where it's
# required, and resolves song_id from the target (so the event carries song
# provenance even when target_song_id isn't passed explicitly).
#
# Cascade: every target FK has ON DELETE CASCADE, so deleting a clip/note/
# device/track/return collapses any envelopes that pointed at it. No mutator
# discipline needed for cascade — schema handles it.


ENVELOPE_TARGET_KINDS = frozenset({
    "clip_cc",
    "clip_pitch_bend",
    "note_expression",
    "device_parameter",
    "mixer_volume",
    "mixer_pan",
    "send_level",
})

# parameter_path is required for these kinds (CC number / MPE axis / param name)
# and optional/forbidden for the rest.
_PARAMETER_PATH_REQUIRED = frozenset({
    "clip_cc", "note_expression", "device_parameter",
})

# MPE axes accepted in parameter_path for note_expression envelopes.
NOTE_EXPRESSION_AXES = frozenset({"pitch", "pressure", "timbre"})

# W10-F: target_kinds that the planner routes through a MIDI session clip on
# the target track. Live 12.4's LOM accepts Clip.create_automation_envelope
# for these targets only on session clips, and Hallucinote v1 models clips as
# MIDI-only — so the host track must be kind='midi'. Master/audio/group tracks
# can't host the routing surface, so the mutator refuses early with teaching.
_SESSION_CLIP_ROUTED_KINDS = frozenset({
    "mixer_volume", "mixer_pan", "send_level", "device_parameter",
})

BREAKPOINT_CURVE_KINDS = frozenset({"linear", "hold", "fast", "slow"})


def _track_kind(
    conn: sqlite3.Connection, track_id: str,
) -> str | None:
    # Arc 7 / P7: route through Q.get_track instead of an inline SELECT
    # so this and `sync.push._track_kind_for_envelope` share the same
    # single-row lookup (one query name to maintain when the tracks
    # schema evolves).
    row = Q.get_track(conn, track_id)
    return None if row is None else row["kind"]


def _resolve_envelope_host_track(
    conn: sqlite3.Connection,
    *,
    target_kind: str,
    target_track_id: str | None,
    target_device_id: str | None,
) -> str | None:
    """Return the track_id that hosts a session-clip-routed envelope, or None
    if it can't be resolved yet (e.g. return-side device, which the planner
    handles separately).

    - mixer_volume / mixer_pan / send_level -> target_track_id directly.
    - device_parameter -> the parent_track_id of the device's chain. Returns
      None if the device lives on a return or doesn't exist (the planner
      already warns on those paths).
    """
    if target_kind in ("mixer_volume", "mixer_pan", "send_level"):
        return target_track_id
    if target_kind == "device_parameter":
        if target_device_id is None:
            return None
        row = conn.execute(
            """SELECT dc.parent_track_id
               FROM devices d
               JOIN device_chains dc ON dc.id = d.chain_id
               WHERE d.id = ?""",
            (target_device_id,),
        ).fetchone()
        return None if row is None else row["parent_track_id"]
    return None


def _envelope_track_kind_refusal(target_kind: str, host_kind: str) -> str:
    """Teaching message for D2 (master) / D3 (audio / group) refusals.

    The phrasing names the LOM constraint, the v1 routing path, and the
    supported workaround so callers can act without reading the source.
    """
    if host_kind == "master":
        # D2 — confirmed no LOM path: Clip.create_automation_envelope lives
        # only on Clip; master can't host clips.
        return (
            f"target_kind={target_kind!r} on a master track is not reachable: "
            "Live 12.4's LOM exposes envelope creation only via "
            "Clip.create_automation_envelope, and the master track cannot "
            "host clips. Route the source(s) to a sub-bus group track and "
            "author the envelope on the group's mixer instead. "
            "See ableton://guides/gaps for the LOM constraint."
        )
    if host_kind == "audio":
        # D3 — Hallucinote v1 models clips as MIDI-only; audio tracks can't
        # host MIDI session clips, so the v1 routing path is unreachable.
        return (
            f"target_kind={target_kind!r} on an audio track is not reachable "
            "in v1: Hallucinote routes mixer/send/device_parameter envelopes "
            "through MIDI session clips, which audio tracks cannot host. "
            "Route the source to a sub-bus group track (kind='midi') and "
            "automate the group's mixer instead. Audio-clip envelopes are "
            "v1.1 scope (gated on the audio-clip DB model)."
        )
    if host_kind == "group":
        # Group tracks in Live host no clips of any kind — they're routing-
        # only — so they share D3's "no host clip" failure mode.
        return (
            f"target_kind={target_kind!r} on a group track is not reachable: "
            "group tracks in Live are routing-only and cannot host MIDI "
            "session clips. Author the envelope on a member track or on the "
            "group's parent sub-bus instead."
        )
    # Defensive — TRACK_KINDS allowlist is {midi,audio,master,group}; any new
    # kind that lands here should explicitly choose a teaching path.
    return (
        f"target_kind={target_kind!r} on track kind={host_kind!r} is not "
        "reachable: Hallucinote v1 routes these envelopes through MIDI "
        "session clips; only kind='midi' tracks can host them."
    )


def create_envelope(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    target_kind: str,
    target_clip_id: str | None = None,
    target_note_id: str | None = None,
    target_device_id: str | None = None,
    target_track_id: str | None = None,
    target_send_return_id: str | None = None,
    parameter_path: str | None = None,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> str:
    """Create an envelope row. Returns the envelope id.

    Caller passes exactly the target kwarg(s) the kind requires:
      clip_cc / clip_pitch_bend  -> target_clip_id
      note_expression            -> target_note_id (parameter_path = MPE axis)
      device_parameter           -> target_device_id (parameter_path = name)
      mixer_volume / mixer_pan   -> target_track_id
      send_level                 -> target_track_id + target_send_return_id

    The schema CHECK is the last-line defense; this mutator raises early with
    a clearer message and validates parameter_path semantics (required for
    clip_cc / note_expression / device_parameter; MPE axis allowlist).
    """
    if target_kind not in ENVELOPE_TARGET_KINDS:
        raise ValueError(
            f"invalid target_kind {target_kind!r}; "
            f"expected one of {sorted(ENVELOPE_TARGET_KINDS)}"
        )

    expected_targets: dict[str, tuple[str, ...]] = {
        "clip_cc":          ("target_clip_id",),
        "clip_pitch_bend":  ("target_clip_id",),
        "note_expression":  ("target_note_id",),
        "device_parameter": ("target_device_id",),
        "mixer_volume":     ("target_track_id",),
        "mixer_pan":        ("target_track_id",),
        "send_level":       ("target_track_id", "target_send_return_id"),
    }
    all_targets = {
        "target_clip_id": target_clip_id,
        "target_note_id": target_note_id,
        "target_device_id": target_device_id,
        "target_track_id": target_track_id,
        "target_send_return_id": target_send_return_id,
    }
    required = expected_targets[target_kind]
    for k in required:
        if all_targets[k] is None:
            raise ValueError(
                f"target_kind={target_kind!r} requires kwarg {k}"
            )
    for k, v in all_targets.items():
        if k not in required and v is not None:
            raise ValueError(
                f"target_kind={target_kind!r} forbids kwarg {k} (got {v!r})"
            )

    if target_kind in _PARAMETER_PATH_REQUIRED:
        if not parameter_path:
            raise ValueError(
                f"target_kind={target_kind!r} requires parameter_path "
                "(CC number / MPE axis / parameter name)"
            )
    else:
        if parameter_path is not None:
            raise ValueError(
                f"target_kind={target_kind!r} does not use parameter_path "
                f"(got {parameter_path!r})"
            )

    if target_kind == "note_expression" and parameter_path not in NOTE_EXPRESSION_AXES:
        raise ValueError(
            f"note_expression parameter_path {parameter_path!r} not in "
            f"{sorted(NOTE_EXPRESSION_AXES)}"
        )

    if target_kind == "clip_cc":
        try:
            cc_number = int(parameter_path)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"clip_cc parameter_path must be an integer CC number "
                f"(got {parameter_path!r})"
            ) from exc
        if not 0 <= cc_number <= 127:
            raise ValueError(
                f"clip_cc CC number {cc_number} out of MIDI range [0, 127]"
            )

    # W10-F: enforce track-kind reachability for session-clip-routed envelopes.
    # mixer/pan/send/device_parameter envelopes route through a MIDI session
    # clip on the target track in v1. Master / audio / group tracks cannot host
    # that routing surface, so reject with a teaching message that points at
    # the supported workaround per kind. (See bug-triage-wave2 D2/D3.)
    if target_kind in _SESSION_CLIP_ROUTED_KINDS:
        host_track_id = _resolve_envelope_host_track(
            conn,
            target_kind=target_kind,
            target_track_id=target_track_id,
            target_device_id=target_device_id,
        )
        if host_track_id is not None:
            host_kind = _track_kind(conn, host_track_id)
            if host_kind is not None and host_kind != "midi":
                raise ValueError(
                    _envelope_track_kind_refusal(target_kind, host_kind)
                )

    # Provenance: clip envelopes carry their target_clip_id; note_expression
    # envelopes resolve clip via the note's parent so audit-trail queries by
    # clip find them too.
    event_clip_id = target_clip_id
    if target_kind == "note_expression":
        note_row = conn.execute(
            "SELECT clip_id FROM notes WHERE id = ?", (target_note_id,),
        ).fetchone()
        if note_row is not None:
            event_clip_id = note_row["clip_id"]

    actor, request_id = _resolve_actor_and_request(actor, request_id)

    # Identity by (song_id, target_kind, all target FKs, parameter_path).
    # Use IS for nullable FK comparisons (SQL equality is NULL-vs-NULL = false).
    existing = conn.execute(
        """SELECT id FROM envelopes
           WHERE song_id = ? AND target_kind = ?
             AND target_clip_id IS ? AND target_note_id IS ?
             AND target_device_id IS ? AND target_track_id IS ?
             AND target_send_return_id IS ?
             AND parameter_path IS ?""",
        (song_id, target_kind, target_clip_id, target_note_id,
         target_device_id, target_track_id, target_send_return_id,
         parameter_path),
    ).fetchone()
    if existing is not None:
        # Envelope rows have no non-identity content — breakpoints are
        # separate. Identity match means unchanged by definition.
        env_id = existing["id"]
        _record_touch_if_session("envelope", env_id)
        return MutatorResult(env_id, "unchanged")

    env_id = _uuid()
    conn.execute(
        """INSERT INTO envelopes
               (id, song_id, target_kind,
                target_clip_id, target_note_id, target_device_id,
                target_track_id, target_send_return_id, parameter_path)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            env_id, song_id, target_kind,
            target_clip_id, target_note_id, target_device_id,
            target_track_id, target_send_return_id, parameter_path,
        ),
    )
    _emit(
        conn,
        E.ENVELOPE_CREATED,
        {
            "envelope_id": env_id,
            "target_kind": target_kind,
            "target_clip_id": target_clip_id,
            "target_note_id": target_note_id,
            "target_device_id": target_device_id,
            "target_track_id": target_track_id,
            "target_send_return_id": target_send_return_id,
            "parameter_path": parameter_path,
        },
        song_id=song_id,
        clip_id=event_clip_id,
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    _touch_song(conn, song_id)
    _record_touch_if_session("envelope", env_id)
    return MutatorResult(env_id, "created")


def delete_envelope(
    conn: sqlite3.Connection,
    *,
    envelope_id: str,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> None:
    row = conn.execute(
        "SELECT song_id, target_clip_id FROM envelopes WHERE id = ?",
        (envelope_id,),
    ).fetchone()
    if row is None:
        return
    conn.execute("DELETE FROM envelopes WHERE id = ?", (envelope_id,))
    _emit(
        conn,
        E.ENVELOPE_DELETED,
        {"envelope_id": envelope_id},
        song_id=row["song_id"],
        clip_id=row["target_clip_id"],
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    _touch_song(conn, row["song_id"])


def _resolve_envelope_song(
    conn: sqlite3.Connection, envelope_id: str,
) -> tuple[str | None, str | None]:
    """Return (song_id, target_clip_id) for an envelope, for event provenance."""
    row = conn.execute(
        "SELECT song_id, target_clip_id FROM envelopes WHERE id = ?",
        (envelope_id,),
    ).fetchone()
    if row is None:
        return None, None
    return row["song_id"], row["target_clip_id"]


def add_breakpoint(
    conn: sqlite3.Connection,
    *,
    envelope_id: str,
    time_beats: float,
    value: float,
    curve_kind: str = "linear",
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> str:
    """Append a single breakpoint to an envelope. Returns the breakpoint id."""
    if curve_kind not in BREAKPOINT_CURVE_KINDS:
        raise ValueError(
            f"invalid curve_kind {curve_kind!r}; "
            f"expected one of {sorted(BREAKPOINT_CURVE_KINDS)}"
        )
    bp_id = _uuid()
    conn.execute(
        """INSERT INTO automation_breakpoints
               (id, envelope_id, time_beats, value, curve_kind)
           VALUES (?, ?, ?, ?, ?)""",
        (bp_id, envelope_id, time_beats, value, curve_kind),
    )
    song_id, clip_id = _resolve_envelope_song(conn, envelope_id)
    _emit(
        conn,
        E.BREAKPOINT_ADDED,
        {
            "breakpoint_id": bp_id,
            "envelope_id": envelope_id,
            "time_beats": time_beats,
            "value": value,
            "curve_kind": curve_kind,
        },
        song_id=song_id,
        clip_id=clip_id,
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    if song_id:
        _touch_song(conn, song_id)
    return bp_id


def remove_breakpoint(
    conn: sqlite3.Connection,
    *,
    breakpoint_id: str,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> None:
    row = conn.execute(
        "SELECT envelope_id FROM automation_breakpoints WHERE id = ?",
        (breakpoint_id,),
    ).fetchone()
    if row is None:
        return
    envelope_id = row["envelope_id"]
    conn.execute(
        "DELETE FROM automation_breakpoints WHERE id = ?", (breakpoint_id,)
    )
    song_id, clip_id = _resolve_envelope_song(conn, envelope_id)
    _emit(
        conn,
        E.BREAKPOINT_REMOVED,
        {"breakpoint_id": breakpoint_id, "envelope_id": envelope_id},
        song_id=song_id,
        clip_id=clip_id,
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    if song_id:
        _touch_song(conn, song_id)


def replace_breakpoints(
    conn: sqlite3.Connection,
    *,
    envelope_id: str,
    breakpoints: Sequence[dict[str, Any]],
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> list[str]:
    """Atomic: delete every breakpoint for `envelope_id`, insert the new set.
    Returns the new breakpoint ids in insertion order. Single event emitted.

    Each breakpoint dict: {time_beats: float, value: float,
    curve_kind: 'linear'|'hold'|'fast'|'slow' (default 'linear')}.

    W12-A: idempotent — when the existing breakpoints already match the
    incoming set (by content, ignoring ids), the function is a no-op and
    emits no event. Returns the existing breakpoint ids in that case.
    """
    actor, request_id = _resolve_actor_and_request(actor, request_id)
    # Idempotency check: compare incoming vs existing.
    incoming_sig = [
        (float(bp["time_beats"]), float(bp["value"]),
         bp.get("curve_kind", "linear"))
        for bp in breakpoints
    ]
    existing_rows = conn.execute(
        """SELECT id, time_beats, value, curve_kind
           FROM automation_breakpoints WHERE envelope_id = ?
           ORDER BY time_beats""",
        (envelope_id,),
    ).fetchall()
    existing_sig = [
        (r["time_beats"], r["value"], r["curve_kind"]) for r in existing_rows
    ]
    if sorted(existing_sig) == sorted(incoming_sig):
        return [r["id"] for r in existing_rows]
    with transaction(conn):
        prev_count = len(existing_rows)
        conn.execute(
            "DELETE FROM automation_breakpoints WHERE envelope_id = ?",
            (envelope_id,),
        )
        new_ids: list[str] = []
        for bp in breakpoints:
            curve = bp.get("curve_kind", "linear")
            if curve not in BREAKPOINT_CURVE_KINDS:
                raise ValueError(
                    f"invalid curve_kind {curve!r}; "
                    f"expected one of {sorted(BREAKPOINT_CURVE_KINDS)}"
                )
            bp_id = _uuid()
            conn.execute(
                """INSERT INTO automation_breakpoints
                       (id, envelope_id, time_beats, value, curve_kind)
                   VALUES (?, ?, ?, ?, ?)""",
                (bp_id, envelope_id, float(bp["time_beats"]),
                 float(bp["value"]), curve),
            )
            new_ids.append(bp_id)
        song_id, clip_id = _resolve_envelope_song(conn, envelope_id)
        _emit(
            conn,
            E.BREAKPOINTS_REPLACED,
            {
                "envelope_id": envelope_id,
                "prev_count": prev_count,
                "new_count": len(new_ids),
                "breakpoint_ids": new_ids,
            },
            song_id=song_id,
            clip_id=clip_id,
            actor=actor,
            request_id=request_id,
            reason=reason,
        )
        if song_id:
            _touch_song(conn, song_id)
    return new_ids


def create_enum_envelope(
    conn: sqlite3.Connection,
    *,
    device_id: str,
    parameter_name: str,
    breakpoints: Sequence[dict[str, Any]],
    value_items: Sequence[str] | None = None,
    curve_default: str = "hold",
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> str:
    """Author a device_parameter envelope from enum-name breakpoint values.

    The DB layer stays meter-agnostic and value-numeric — this is a
    compose-time sugar that resolves enum names to the numeric indices
    Live actually stores. Mirrors the MCP handler's ``value_type='enum'``
    surface so build.py authors don't have to look up ``value_items``
    indices by hand to write "Amp Type: Clean→Heavy" automation.

    Resolution order for the enum cardinality:
      1. ``value_items`` kwarg (escape hatch — wins when supplied)
      2. ``device_parameters.value_items_json`` for (device_id, parameter_name)
         — captured at pull time via detail='full'.
      3. Otherwise raises ValueError with a teaching message pointing at
         re-pull (snapshot was captured pre-E1) or value_type='continuous'
         (param isn't enum-shaped).

    Stores numeric breakpoints by calling ``create_envelope`` +
    ``replace_breakpoints`` — no envelope-side schema change. Each
    breakpoint's ``curve`` (or ``curve_kind``) is preserved; ``curve_default``
    fills in when absent (defaults to 'hold' since enum envelopes are
    step-shaped — see Live 12.4's ``Envelope.insert_step`` semantics).

    Returns the envelope id.
    """
    if curve_default not in BREAKPOINT_CURVE_KINDS:
        raise ValueError(
            f"invalid curve_default {curve_default!r}; "
            f"expected one of {sorted(BREAKPOINT_CURVE_KINDS)}"
        )
    if not breakpoints:
        raise ValueError(
            "breakpoints must be a non-empty sequence of "
            "{time_beats, value, curve?} dicts"
        )

    resolved_items = _resolve_enum_value_items(
        conn,
        device_id=device_id,
        parameter_name=parameter_name,
        value_items=value_items,
    )

    numeric_breakpoints: list[dict[str, Any]] = []
    for i, bp in enumerate(breakpoints):
        if not isinstance(bp, dict):
            raise ValueError(
                f"breakpoint {i}: expected dict, got {type(bp).__name__}"
            )
        if "time_beats" not in bp:
            raise ValueError(
                f"breakpoint {i} missing 'time_beats': {bp!r}"
            )
        if "value" not in bp:
            raise ValueError(
                f"breakpoint {i} missing 'value': {bp!r}"
            )
        raw = bp["value"]
        if not isinstance(raw, str):
            raise ValueError(
                f"breakpoint {i}: create_enum_envelope expects string "
                f"values (enum names), got {type(raw).__name__} "
                f"({raw!r}) — use create_envelope + replace_breakpoints "
                f"for numeric authoring"
            )
        if raw not in resolved_items:
            raise ValueError(
                f"breakpoint {i}: enum value {raw!r} not in value_items "
                f"for parameter {parameter_name!r}: {resolved_items}"
            )
        curve_kind = bp.get("curve") or bp.get("curve_kind") or curve_default
        if curve_kind not in BREAKPOINT_CURVE_KINDS:
            raise ValueError(
                f"breakpoint {i}: invalid curve {curve_kind!r}; "
                f"expected one of {sorted(BREAKPOINT_CURVE_KINDS)}"
            )
        numeric_breakpoints.append({
            "time_beats": float(bp["time_beats"]),
            "value": float(resolved_items.index(raw)),
            "curve_kind": curve_kind,
        })

    song_id = _resolve_device_song(conn, device_id=device_id)
    if song_id is None:
        raise ValueError(
            f"device {device_id} not found or has no resolvable song; "
            f"verify the device row exists before authoring envelopes"
        )

    envelope_id = create_envelope(
        conn,
        song_id=song_id,
        target_kind="device_parameter",
        target_device_id=device_id,
        parameter_path=parameter_name,
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    replace_breakpoints(
        conn,
        envelope_id=envelope_id,
        breakpoints=numeric_breakpoints,
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    return envelope_id


def _resolve_enum_value_items(
    conn: sqlite3.Connection,
    *,
    device_id: str,
    parameter_name: str,
    value_items: Sequence[str] | None,
) -> list[str]:
    """Resolve the enum cardinality for (device_id, parameter_name).

    Distinguishes the three "no enum items" states (per the
    `Detection that replaces a user question` learning):
      - no param row for (device, name) → ValueError "not captured"
      - row exists but value_items_json is NULL → ValueError "not enum
        OR pre-E1 capture"
      - row exists with malformed JSON → ValueError "malformed"

    Each surfaces a teaching error pointing at the right remedy.
    """
    if value_items is not None:
        items_list = [str(v) for v in value_items]
        if not items_list:
            raise ValueError(
                "value_items kwarg must be a non-empty sequence"
            )
        return items_list
    param_row = conn.execute(
        """SELECT value_items_json FROM device_parameters
           WHERE device_id = ? AND name = ?""",
        (device_id, parameter_name),
    ).fetchone()
    if param_row is None:
        raise ValueError(
            f"parameter {parameter_name!r} not captured on device "
            f"{device_id} — pull device parameters first (detail='full') "
            f"so value_items is available, or pass value_items=[...] "
            f"explicitly"
        )
    items_json = param_row["value_items_json"]
    if items_json is None:
        raise ValueError(
            f"parameter {parameter_name!r} on device {device_id} has no "
            f"value_items captured — either the param isn't enum-shaped "
            f"(use create_envelope + replace_breakpoints with numeric "
            f"values), or it was captured before value_items_json was "
            f"added (re-pull the song's device parameters). Escape "
            f"hatch: pass value_items=[...] explicitly."
        )
    try:
        loaded = json.loads(items_json)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"value_items_json on device {device_id} parameter "
            f"{parameter_name!r} is malformed: {items_json!r}"
        ) from exc
    if not isinstance(loaded, list) or not loaded:
        raise ValueError(
            f"value_items_json on device {device_id} parameter "
            f"{parameter_name!r} must decode to a non-empty list, "
            f"got {loaded!r}"
        )
    return [str(v) for v in loaded]


# ---------------------------------------------------------------------------
# Soft reset (W18-C)
# ---------------------------------------------------------------------------


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
    conn.commit()
    return counts


# ---------------------------------------------------------------------------
# Ableton projection: sessions + links
# ---------------------------------------------------------------------------

# db_kind values currently used by the sync layer.
ABLETON_LINK_KINDS = frozenset({
    "track", "clip", "arrangement_clip", "note", "return", "device", "envelope",
})


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
        clip_id=db_id if db_kind == "clip" else None,
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    return True


# ---------------------------------------------------------------------------
# W12-A: BuildSession — state-converger context manager
# ---------------------------------------------------------------------------
#
# A song's build.py wraps its mutator calls in `with M.build_session(...)`:
#
#   with M.build_session(conn, song_name='falling-walking', owner='build.py'):
#       song_id = M.create_song(conn, name='falling-walking', ...)
#       M.create_track(conn, song_id=song_id, track_index=1, name='Drums')
#       # ... 80+ more mutator calls
#
# On enter:
#   - Opens a `kind='compose'` request (or 'build' if added later) returning
#     request_id.
#   - Sets the `_current_build_session` ContextVar so subsequent mutator
#     calls (within this context) promote default actor='system' to 'build'
#     and tag the request_id automatically.
#
# On exit (no exception):
#   - For each managed kind owned by build, queries all rows for the song,
#     finds rows NOT in `touched`, and for each candidate row checks the
#     latest event actor. If the latest actor ∈ {'build', 'system'}, deletes
#     the row (cascades children via schema FKs). 'sync'/'llm'/'user'/
#     'generator' actor rows survive.
#   - Closes the request with outcome='ok'.
#
# On exit (exception):
#   - Closes the request with outcome='failed' (or 'partial'); does NOT
#     tombstone (errors leave state alone for inspection).


# Which (kind, song-scope) tables build owns + how to enumerate their ids
# given a song_id. The order here is the deletion order; respecting FK
# dependencies (children before parents) keeps cascade behavior predictable.
# Note: most cascades are handled by ON DELETE CASCADE in the schema; we
# delete the parent and trust the schema, but order from leaves inward
# anyway for visibility in event logs.
_BUILD_OWNED_KINDS: tuple[tuple[str, str, str], ...] = (
    # (kind, table, song_id column expression for SELECT id FROM <table>)
    ("envelope", "envelopes", "song_id"),
    ("arrangement_clip", "arrangement_clips", "song_id"),
    ("cue_point", "cue_points", "song_id"),
    ("tempo_point", "tempo_map", "song_id"),
    ("time_signature_point", "time_signature_map", "song_id"),
    ("section", "sections", "song_id"),
    # Devices live under chains under tracks/returns. Walking through chains
    # via JOIN; managed below via _build_owned_devices.
    ("device_parameter", "device_parameters", ""),  # special — joined via device->chain->track/return
    ("device", "devices", ""),                       # special — joined via chain->track/return
    ("device_chain", "device_chains", ""),           # special — joined via track/return
    ("return", "returns", "song_id"),
    ("clip", "clips", ""),  # special — joined via track
    ("track", "tracks", "song_id"),
)


# events.kind values whose payload's `<kind>_id` or `id` field names the entity
# the event acted on. Used to look up the "latest event actor" per row.
# Map: row-kind -> tuple of (event_kind, payload_field).
_LATEST_ACTOR_EVENTS: dict[str, tuple[tuple[str, str], ...]] = {
    "song":                  (("song_created", "song_id"), ("song_updated", "song_id")),
    "track":                 (("track_created", "track_id"), ("track_updated", "track_id"),
                              ("track_mixer_set", "track_id")),
    "clip":                  (("clip_created", "clip_id"), ("clip_updated", "clip_id")),
    "arrangement_clip":      (("arrangement_clip_added", "arrangement_clip_id"),),
    "section":               (("section_created", "section_id"),
                              ("section_updated", "section_id")),
    "tempo_point":           (("tempo_point_added", "point_id"),
                              ("tempo_point_updated", "point_id")),
    "time_signature_point":  (("time_signature_point_added", "point_id"),
                              ("time_signature_point_updated", "point_id")),
    "cue_point":             (("cue_point_added", "cue_id"),),
    "return":                (("return_created", "return_id"),
                              ("return_updated", "return_id")),
    "device_chain":          (("device_chain_created", "chain_id"),),
    "device":                (("device_created", "device_id"),),
    "device_parameter":      (("device_parameter_set", "parameter_id"),),
    "envelope":              (("envelope_created", "envelope_id"),),
}


def _latest_actor_for(
    conn: sqlite3.Connection, *, row_kind: str, row_id: str,
) -> str | None:
    """Return the actor of the latest event referencing this row (None if
    no event references it). Used by tombstoning to decide whether build is
    allowed to delete the row (actor ∈ {'build','system'}) or must skip it.

    Special-case: row_kind='clip' uses the events.clip_id column directly so
    every clip-touching event (create, update, notes_replaced, notes_inserted,
    note_updated, notes_deleted, notes_bulk_updated) registers as a "touch
    on this clip" — so an LLM revising notes on a build-owned clip flips
    the clip's latest actor to 'llm' and protects it (and the notes that
    cascade with it) from tombstoning.
    """
    if row_kind == "clip":
        # Use the events.clip_id column — catches every clip-touching event
        # without needing per-event-kind payload introspection.
        row = conn.execute(
            "SELECT actor FROM events WHERE clip_id = ? "
            "ORDER BY seq DESC LIMIT 1",
            (row_id,),
        ).fetchone()
        return row["actor"] if row else None
    queries = _LATEST_ACTOR_EVENTS.get(row_kind)
    if not queries:
        return None
    # Build a UNION of per-event-kind queries, ordered by seq DESC, take 1.
    sql_parts = []
    params: list[Any] = []
    for ev_kind, field in queries:
        sql_parts.append(
            f"SELECT actor, seq FROM events "
            f"WHERE kind = ? AND json_extract(payload_json, '$.{field}') = ?"
        )
        params.extend([ev_kind, row_id])
    sql = " UNION ALL ".join(sql_parts) + " ORDER BY seq DESC LIMIT 1"
    row = conn.execute(sql, params).fetchone()
    return row["actor"] if row else None


_DELETE_VERBS: dict[str, str] = {
    # row-kind -> mutator that handles its delete (with proper event emission).
    "envelope":             "delete_envelope",
    "arrangement_clip":     "remove_arrangement_clip",
    "cue_point":            "remove_cue_point",
    "tempo_point":          "remove_tempo_point",
    "time_signature_point": "remove_time_signature_point",
    "section":              "delete_section",
    "device_parameter":     "remove_device_parameter",
    "device":               "delete_device",
    "device_chain":         "delete_device_chain",
    "return":               "delete_return",
    "clip":                 "delete_clip",
    "track":                "_delete_track",  # we add this below
}


def _delete_track(
    conn: sqlite3.Connection, *,
    track_id: str,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> None:
    """Tombstone-time helper: delete a track row. The schema already cascades
    to clips/arrangement_clips/device_chains/etc, but mutations.py didn't
    historically expose a `delete_track` mutator because the only path that
    needed it was `delete_song` (which doesn't exist either). W12-A's
    BuildSession needs it for tombstoning."""
    row = conn.execute(
        "SELECT song_id FROM tracks WHERE id = ?", (track_id,)
    ).fetchone()
    if row is None:
        return
    conn.execute("DELETE FROM tracks WHERE id = ?", (track_id,))
    _emit(
        conn, E.TRACK_DELETED,
        {"track_id": track_id},
        song_id=row["song_id"],
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    _touch_song(conn, row["song_id"])


class BuildSession:
    """State carried by `M.build_session`. Tracks touched (kind, id) pairs."""

    __slots__ = ("conn", "song_name", "song_id", "owner", "request_id",
                 "touched", "_token", "_outcome")

    def __init__(
        self, conn: sqlite3.Connection, *, song_name: str, owner: str,
    ) -> None:
        self.conn = conn
        self.song_name = song_name
        self.owner = owner
        self.song_id: str | None = None
        self.request_id: str | None = None
        self.touched: set[tuple[str, str]] = set()
        self._token: contextvars.Token | None = None
        self._outcome: str = "ok"

    def record_touch(self, kind: str, id_: str) -> None:
        """Called by mutators after their state write. Idempotent — duplicate
        touches in one build are fine (a build that creates then updates a
        row records two touches for the same id; the set dedups)."""
        self.touched.add((kind, id_))

    def touched_count(self, kind: str | None = None) -> int:
        """Diagnostic helper. With kind=None: total touches; with kind: touches of that kind."""
        if kind is None:
            return len(self.touched)
        return sum(1 for k, _ in self.touched if k == kind)


@contextlib.contextmanager
def build_session(
    conn: sqlite3.Connection,
    *,
    song_name: str,
    owner: str = "build.py",
    reason: str | None = None,
    prompt_text: str | None = None,
    parent_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> Iterator[BuildSession]:
    """State-converger context manager for a song's build.py (W12-A).

    Inside the `with` block:
      - Mutators default to actor='build' (unless caller passes otherwise).
      - Every mutator call's (kind, id) is recorded on the session.

    On clean exit:
      - For each managed kind owned by this song, build-owned rows
        (latest event actor ∈ {'build','system'}) NOT in the touched set
        are deleted (cascades naturally via schema FKs).
      - The session's request closes with outcome='ok'.

    On exception:
      - The session's request closes with outcome='failed'; no tombstoning.

    Resolves `song_id` lazily: build.py's first call inside the session is
    typically `M.create_song(name=song_name)`, which the tombstone path
    needs to find rows by song. If a song with `song_name` doesn't exist
    at exit time (e.g., create_song was never called), tombstone is a no-op.

    Arc 2 / B4 provenance: `prompt_text` (user's compose prompt) and
    `parent_id` (parent request, if this build runs inside an outer
    cycle) thread directly to `create_request`. `metadata` augments the
    auto-captured `provenance_metadata()` signals (git_sha, branch,
    hostname) — caller-provided keys override auto-captured ones. If
    nothing is provided, auto-capture still fires so every compose
    cycle gets the standard platform context.
    """
    bs = BuildSession(conn, song_name=song_name, owner=owner)
    # Auto-capture platform metadata so EVERY build session gets the
    # standard signals — callers don't need to remember to opt in. They
    # can still augment via the explicit `metadata=` kwarg; explicit
    # keys override auto-captured ones (the caller knows better).
    auto_meta = provenance_metadata()
    if metadata:
        auto_meta.update(metadata)
    # Open a request to carry the build's actor + provenance for child events.
    bs.request_id = create_request(
        conn,
        actor="build",
        intent=f"build {song_name} (owner={owner})",
        kind="compose",
        reason=reason,
        prompt_text=prompt_text,
        parent_id=parent_id,
        metadata=auto_meta if auto_meta else None,
    )
    bs._token = _current_build_session.set(bs)
    try:
        yield bs
    except BaseException:  # prawduct:ok-broad-except
        # On any failure (including KeyboardInterrupt), close the request as
        # failed and skip tombstoning. The DB stays in whatever partial state
        # the build left it (transaction discipline is the caller's; we do
        # NOT wrap the build in a transaction because builds are large and
        # callers may want partial-progress observability).
        bs._outcome = "failed"
        _current_build_session.reset(bs._token)
        close_request(conn, request_id=bs.request_id, outcome="failed")
        raise
    # Clean exit: resolve song_id (from create_song's touch or by name) and
    # tombstone non-touched build-owned rows.
    _current_build_session.reset(bs._token)
    song_row = conn.execute(
        "SELECT id FROM songs WHERE name = ?", (song_name,),
    ).fetchone()
    if song_row is None:
        # No song was created — nothing to tombstone.
        close_request(conn, request_id=bs.request_id, outcome="ok")
        return
    bs.song_id = song_row["id"]
    _tombstone_untouched(conn, bs)
    close_request(conn, request_id=bs.request_id, outcome="ok")


_NESTED_RACK_CHAINS_CTE = """
WITH RECURSIVE song_chains(id) AS (
    -- Anchor: top-level chains (parented by a track or return in this song).
    SELECT dc.id FROM device_chains dc
    LEFT JOIN tracks t ON t.id = dc.parent_track_id
    LEFT JOIN returns r ON r.id = dc.parent_return_id
    WHERE t.song_id = ? OR r.song_id = ?
    UNION
    -- Recursive: chains parented by a rack device that itself lives in
    -- a song-rooted chain. Walks nested-rack hierarchies of any depth;
    -- terminates naturally when no more chains reference the frontier.
    SELECT dc.id FROM device_chains dc
    JOIN devices d ON d.id = dc.parent_rack_device_id
    JOIN song_chains sc ON sc.id = d.chain_id
)
"""


def _tombstone_untouched(conn: sqlite3.Connection, bs: BuildSession) -> None:
    """Delete build-owned rows for this song not touched in this build.

    Build-owned = latest event actor ∈ {'build', 'system'}. 'sync'-actor
    rows (pulled from Live) survive; 'llm'/'user'/'generator'-actor rows
    survive too — only build's own droppings get cleaned up.

    Walks the kinds in `_BUILD_OWNED_KINDS` in dependency-leaf-first order.
    The schema FKs handle most cascades, but explicit per-kind deletion
    ensures each row's deletion event is emitted by the corresponding
    `M.<delete>` mutator (no silent cascades missing events).
    """
    assert bs.song_id is not None
    song_id = bs.song_id
    touched_by_kind: dict[str, set[str]] = {}
    for k, i in bs.touched:
        touched_by_kind.setdefault(k, set()).add(i)
    for kind, table, song_col in _BUILD_OWNED_KINDS:
        # Build the SELECT query — special-cases for chain/device/device_parameter/clip
        # that don't have direct song_id columns.
        if song_col:
            row_ids = [
                r["id"] for r in conn.execute(
                    f"SELECT id FROM {table} WHERE {song_col} = ?", (song_id,),
                ).fetchall()
            ]
        elif kind == "clip":
            row_ids = [
                r["id"] for r in conn.execute(
                    """SELECT c.id FROM clips c
                       JOIN tracks t ON t.id = c.track_id
                       WHERE t.song_id = ?""",
                    (song_id,),
                ).fetchall()
            ]
        elif kind == "device_chain":
            row_ids = [
                r["id"] for r in conn.execute(
                    _NESTED_RACK_CHAINS_CTE + "SELECT id FROM song_chains",
                    (song_id, song_id),
                ).fetchall()
            ]
        elif kind == "device":
            row_ids = [
                r["id"] for r in conn.execute(
                    _NESTED_RACK_CHAINS_CTE
                    + "SELECT d.id FROM devices d "
                    + "JOIN song_chains sc ON sc.id = d.chain_id",
                    (song_id, song_id),
                ).fetchall()
            ]
        elif kind == "device_parameter":
            row_ids = [
                r["id"] for r in conn.execute(
                    _NESTED_RACK_CHAINS_CTE
                    + "SELECT dp.id FROM device_parameters dp "
                    + "JOIN devices d ON d.id = dp.device_id "
                    + "JOIN song_chains sc ON sc.id = d.chain_id",
                    (song_id, song_id),
                ).fetchall()
            ]
        else:
            row_ids = []
        touched_ids = touched_by_kind.get(kind, set())
        for row_id in row_ids:
            if row_id in touched_ids:
                continue
            actor = _latest_actor_for(conn, row_kind=kind, row_id=row_id)
            # Treat None as 'system' (no event found = legacy/seed data,
            # tombstone-eligible per the design).
            if actor is not None and actor not in ("build", "system"):
                continue
            verb = _DELETE_VERBS.get(kind)
            if verb is None:
                continue
            mutator = globals()[verb]
            # Each kind's delete takes a kwarg whose name varies — map it.
            kwarg = _DELETE_KWARGS[kind]
            mutator(conn, actor="build", request_id=bs.request_id,
                    **{kwarg: row_id})


# Argument names accepted by each delete mutator (since they vary by kind).
_DELETE_KWARGS: dict[str, str] = {
    "envelope":             "envelope_id",
    "arrangement_clip":     "arrangement_clip_id",
    "cue_point":            "cue_id",
    "tempo_point":          "point_id",
    "time_signature_point": "point_id",
    "section":              "section_id",
    "device_chain":         "chain_id",
    "device":               "device_id",
    "return":               "return_id",
    "clip":                 "clip_id",
    "track":                "track_id",
}


# `device_parameter` doesn't fit the kwarg-by-id pattern (it's keyed by
# (device_id, name)). Tombstoning a device_parameter directly is rare — the
# parent device usually carries the tombstone. Skip device_parameter from
# top-level tombstoning by removing it from the _DELETE_VERBS map (its row
# gets caught when the parent device tombstones).
del _DELETE_VERBS["device_parameter"]
