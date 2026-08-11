"""Auto-provenance for MCP server-side handlers that write to the Hallucinote DB.

When an annotation write (or any future DB-writing action) lands via MCP, the
dispatcher uses ``auto_request`` to open an ``M.request(kind='mutate', ...)``
against the song's DB before the handler runs. The handler receives the new
request id via the ``_request_id`` kwarg and threads it into its mutator
calls, so every emitted event ties back to the MCP call that produced it —
without forcing every callsite to remember to wrap.

DB connection model: this module opens its own short-lived connection for the
request lifecycle; the handler still opens its own for the writes. SQLite
autocommit + WAL (configured by `hallucinote.db.connection.connect`) lets the
handler's connection see the request row on its first read, and lets the
request-close write commit after the handler's writes — both directions
durable across connections without explicit coordination.

Import discipline: this module lives in `hallucinote_mcp` but reaches into
the main `hallucinote` package, which is NOT vendored into Live's User
Library. The import is guarded so the Remote Script side (where this module
loads but never runs — `runs_server_side` keeps execution on the agent's
process) doesn't ImportError at Control Surface load time.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

logger = logging.getLogger("hallucinote_mcp.provenance")


try:
    from hallucinote.db import mutations as M
    from hallucinote.db import queries as Q
    from hallucinote.db.connection import init_db, resolve_db_path
    _HAS_HALLUCINOTE_DB = True
except ImportError:  # pragma: no cover - exercised in Live's vendored env
    M = None  # type: ignore[assignment]
    Q = None  # type: ignore[assignment]
    init_db = None  # type: ignore[assignment]
    resolve_db_path = None  # type: ignore[assignment]
    _HAS_HALLUCINOTE_DB = False


# Test seam: lets the unit suite point the resolver at a temp path without
# the full songs/<slug>/<slug>-<branch>.db layout.
def _resolve_song_db_path(song_slug: str) -> Path:
    return resolve_db_path(song_slug)


@contextmanager
def auto_request(
    *,
    tool: str,
    action_name: str,
    params: dict[str, Any],
) -> Iterator[str | None]:
    """Open + close an ``M.request(kind='mutate')`` around an MCP handler call.

    Yields the new ``request_id`` for the dispatcher to thread into the
    handler, or ``None`` when provenance can't be established (no
    ``hallucinote.db`` import on this side, no ``song_slug`` in params, the
    song's DB file doesn't exist yet, etc.). In all of those degraded cases
    the handler still runs — the caller falls through to its own teaching
    error path so the LLM gets the same diagnostic shape as before.

    On exception inside the ``with`` block, ``M.request`` closes the
    request with ``outcome='failed'`` and re-raises. On clean exit it
    closes with ``outcome='ok'``.
    """
    if not _HAS_HALLUCINOTE_DB:
        yield None
        return
    slug = params.get("song_slug")
    if not isinstance(slug, str) or not slug:
        yield None
        return
    try:
        db_path = _resolve_song_db_path(slug)
    except Exception:  # prawduct:allow prawduct/broad-except -- resolver failure is degraded provenance, not a user-facing error.
        logger.debug(
            "auto_request: resolve_db_path(%r) failed; skipping provenance", slug,
        )
        yield None
        return
    if not db_path.exists():
        # DB doesn't exist yet — the handler will raise its own teaching
        # error (FileNotFoundError → "no song named X found"). Skip
        # provenance rather than create a request row referencing a song
        # that doesn't exist.
        yield None
        return
    conn = init_db(db_path)
    try:
        song_row = Q.get_song_by_name(conn, slug)
        song_id = song_row["id"] if song_row is not None else None
        metadata = M.provenance_metadata()
        with M.request(
            conn,
            actor="llm",
            intent=f"{tool}({action_name!r})",
            kind="mutate",
            song_id=song_id,
            payload={"params": params},
            metadata=metadata if metadata else None,
        ) as rid:
            yield rid
    finally:
        conn.close()


__all__ = ["auto_request"]
