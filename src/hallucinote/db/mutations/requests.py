"""Provenance: requests + markdown-ref audit events."""
from __future__ import annotations

import contextlib
import sqlite3
import time
from typing import Any, Iterator

from ._core import (
    E,
    REQUEST_KINDS,
    REQUEST_OUTCOMES,
    _emit,
    _uuid,
    json,
)


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


__all__ = [
    "close_request",
    "create_request",
    "provenance_metadata",
    "record_markdown_ref",
    "request",
]
