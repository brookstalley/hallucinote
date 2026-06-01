"""Pre-pass planners: create unlinked tracks + return tracks."""
from __future__ import annotations

import sqlite3
from typing import Any

from hallucinote.db import queries as Q

from ._core import PushPlan, ToolCall


def plan_push_song_tracks(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    session_id: str,
) -> PushPlan:
    """Pre-pass: emit one ``ableton_track(action='create')`` call per
    unique unlinked non-master track for this song.

    W3-C — replaces the per-clip track-create emit that
    :func:`plan_push_clip` used to do. A song with 8 tracks and 32 clips
    used to produce 32 ``ableton_track(create)`` calls (with identical
    ``key=track:{track_id}`` values for each track), all of which had to
    be deduplicated by the agent. This planner emits exactly N calls for
    N unique unlinked tracks — dedupe is structural, not behavioral.

    Caller flow:
        1. ``plan = plan_push_song_tracks(conn, song_id, session_id)``
        2. Agent executes ``plan.calls`` (parallelizable — each is
           independent), captures results.
        3. ``apply_push_results(conn, results, session_id=session_id)``
           records each new ``track_index`` via ``ableton_links``.
        4. Now :func:`plan_push_clip`, :func:`plan_push_arrangement`,
           and :func:`plan_push_mix` can run — every track they touch
           is linked.

    Master tracks are skipped: master has no Live-side "create" — it
    exists implicitly in every Live set and is reached via
    ``ableton_session(set_master_property)``.

    Returns an empty plan when every non-master track is already linked
    (idempotent — safe to re-run after partial pushes).
    """
    plan = PushPlan()
    tracks = Q.get_tracks_for_song(conn, song_id)
    for t in tracks:
        if t["kind"] == "master":
            continue
        existing = Q.get_ableton_link(
            conn, session_id=session_id, db_kind="track", db_id=t["id"],
        )
        if existing is not None:
            continue
        create_args: dict[str, Any] = {
            "action": "create",
            "kind": t["kind"],
            "name": t["name"],
        }
        if t["instrument_uri"]:
            # Round-trips in the result as `instrument_uri_deferred`; agent
            # follows up with ableton_device(action='load') separately.
            create_args["instrument_uri"] = t["instrument_uri"]
        plan.add(ToolCall(
            tool="ableton_track",
            args=create_args,
            key=f"track:{t['id']}",
            purpose=(
                f"create unlinked track '{t['name']}' "
                f"(kind={t['kind']}, db_id={t['id']})"
            ),
        ))
    return plan


def plan_push_song_returns(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    session_id: str,
) -> PushPlan:
    """Pre-pass: emit one ``ableton_return(action='create')`` call per
    unique unlinked return for this song.

    Mirror of :func:`plan_push_song_tracks` for return tracks. The same
    dedupe-at-the-planner-level rationale applies: returns are
    referenced by sends and by send_level envelopes — without a
    song-level pre-pass, every per-element planner would re-emit the
    create. Idempotent across re-runs.
    """
    plan = PushPlan()
    returns = Q.get_returns_for_song(conn, song_id)
    for r in returns:
        existing = Q.get_ableton_link(
            conn, session_id=session_id, db_kind="return", db_id=r["id"],
        )
        if existing is not None:
            continue
        plan.add(ToolCall(
            tool="ableton_return",
            args={"action": "create", "name": r["name"]},
            key=f"return:{r['id']}",
            purpose=f"create unlinked return '{r['name']}' (db_id={r['id']})",
        ))
    return plan
