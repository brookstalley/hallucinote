"""WFL-7Q2N: session-ID auto-discovery for the sync CLIs.

Push/pull always operate through an ``ableton_sessions`` row, but its id is
a UUID nobody remembers — daily-loop friction on every invocation. When a
CLI command is run without one, resolve it from the DB the command already
opened (via ``--song``/``--db``):

* exactly one session → use it;
* several (same song) → use the most recently created, and say so on
  stderr with the alternatives listed — the choice is always echoed, never
  silent;
* sessions spanning multiple songs → genuinely ambiguous; refuse with a
  listing (per-song DBs make this rare, but a multi-song DB must not get a
  silent cross-song guess);
* none → actionable error pointing at the bootstrap path.

Echoes go to stderr — stdout stays JSON-clean for the CLIs' tool-result
contracts.
"""
from __future__ import annotations

import sqlite3
import sys

from hallucinote.db import queries as Q


def _describe(row: sqlite3.Row) -> str:
    name = row["name"] or "unnamed"
    return f"{row['id']} ({name!r}, created {row['created_at']})"


def resolve_session_id(
    conn: sqlite3.Connection,
    session_id: str | None,
    *,
    prog: str,
    plan_session_id: str | None = None,
) -> str:
    """Return ``session_id`` as-is when given; otherwise auto-discover.

    ``prog`` prefixes every message (e.g. ``"push_cli execute"``) so the
    echo reads like the CLI's own output.

    ``plan_session_id`` is the session embedded in a plan file the command
    was handed (apply commands). It is the authoritative value when the
    positional id is omitted — the plan was produced against that session,
    and most-recent could silently bind the results to a different one.
    An explicit positional id that *conflicts* with it is refused.
    """
    if session_id is not None:
        if plan_session_id is not None and plan_session_id != session_id:
            raise SystemExit(
                f"{prog}: positional session_id {session_id} conflicts with "
                f"the plan file's session_id {plan_session_id} — results "
                "must be applied to the session the plan was produced "
                "against; drop the positional id or pass the matching one"
            )
        return session_id

    if plan_session_id is not None:
        print(
            f"{prog}: session {plan_session_id} — taken from the plan file",
            file=sys.stderr,
        )
        return plan_session_id

    sessions = Q.list_ableton_sessions(conn)
    if not sessions:
        raise SystemExit(
            f"{prog}: no session_id given and this DB has no sessions — "
            "bootstrap one with `push_cli probe-and-link --probe "
            "--auto-session --song <slug>` (or `push_cli create-session "
            "--song <slug>`)"
        )

    song_ids = {s["song_id"] for s in sessions}
    if len(song_ids) > 1:
        listing = "\n".join(
            f"  {_describe(s)} song={s['song_id']}" for s in sessions
        )
        raise SystemExit(
            f"{prog}: no session_id given and this DB has sessions for "
            f"{len(song_ids)} different songs — pass one explicitly:\n{listing}"
        )

    chosen = sessions[0]
    if len(sessions) == 1:
        print(
            f"{prog}: session {_describe(chosen)} — auto-selected "
            "(only session)",
            file=sys.stderr,
        )
    else:
        print(
            f"{prog}: session {_describe(chosen)} — auto-selected "
            f"(most recent of {len(sessions)})",
            file=sys.stderr,
        )
        for alt in sessions[1:]:
            print(f"{prog}:   alternative: {_describe(alt)}", file=sys.stderr)
    return chosen["id"]


__all__ = ["resolve_session_id"]
