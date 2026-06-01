"""Session-clip planners: per-clip + song-wide aggregation."""
from __future__ import annotations

import sqlite3

from hallucinote.db import queries as Q

from ._core import PushPlan, ToolCall, _notes_for_mcp


def plan_push_clip(
    conn: sqlite3.Connection,
    *,
    clip_id: str,
    session_id: str,
) -> PushPlan:
    """Plan the push of a single session clip to Ableton.

    Two cases (W3-C narrowed from three; track-creation moved to
    :func:`plan_push_song_tracks`):
      1. Clip not yet linked  -> ``ableton_clip(action='create',
         location='session', kind=…, replace=True, notes=…)``  — atomic
         single-call create+populate (Wave M+1-1).
      2. Clip already linked  -> ``ableton_clip(action='replace_notes')``
         (in-place; gap #1's renamed action, unified via Wave M-3).

    Precondition (W3-C — strict): the clip's track must already be
    linked in this session. Run :func:`plan_push_song_tracks` first to
    create+link all unlinked tracks, ``apply_push_results``, then call
    this planner. The strict raise replaces the prior silent-redundant-
    emit behavior that produced N duplicate ``ableton_track(create)``
    calls for N clips on the same unlinked track (32 calls for an
    8-track / 32-clip song; one per CLIP, not one per TRACK).
    """
    plan = PushPlan()

    clip = Q.get_clip(conn, clip_id)
    if clip is None:
        raise ValueError(f"clip {clip_id} not found")

    track_row = Q.get_track(conn, clip["track_id"])
    if track_row is None:
        raise ValueError(f"track {clip['track_id']} not found for clip {clip_id}")
    notes = Q.get_notes_for_clip(conn, clip_id)

    track_at = Q.get_ableton_link(
        conn, session_id=session_id, db_kind="track", db_id=track_row["id"]
    )
    clip_at = Q.get_ableton_link(
        conn, session_id=session_id, db_kind="clip", db_id=clip_id
    )

    if track_at is None:
        raise ValueError(
            f"plan_push_clip: track {track_row['id']!r} ('{track_row['name']}') "
            f"is not linked in session {session_id!r}. Call "
            f"plan_push_song_tracks(conn, song_id=..., session_id=...) first "
            f"to create and link any unlinked tracks (one call per unique "
            f"track, not per clip), apply_push_results, then re-run "
            f"plan_push_clip."
        )

    if clip_at is None:
        # Wave M+1-1: atomic single-call create+populate. `replace=True`
        # makes the handler delete an occupied slot before creating, so the
        # planner doesn't have to know the slot's current state. The handler
        # returns `clip_index`, which `_LINK_KINDS["clip"]` reads to record
        # the binding via the generic apply path.
        plan.add(ToolCall(
            tool="ableton_clip",
            args={
                "action": "create",
                "location": "session",
                "kind": "midi",
                "track_index": track_at,
                "clip_index": clip["slot"],
                "length": clip["length_beats"],
                "name": clip["name"],
                "notes": _notes_for_mcp(notes),
                "replace": True,
            },
            key=f"clip:{clip_id}",
            purpose=f"create+populate session clip slot {clip['slot']} on track {track_at}",
        ))
    else:
        plan.add(ToolCall(
            tool="ableton_clip",
            args={
                "action": "replace_notes",
                "track_index": track_at,
                "location": "session",
                "clip_index": clip_at,
                "notes": _notes_for_mcp(notes),
            },
            key=f"clip:{clip_id}",
            purpose=f"replace notes in existing clip ({len(notes)} notes)",
        ))

    return plan


def plan_push_clips(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    session_id: str,
) -> PushPlan:
    """Plan the create/replace of every session clip in a song.

    Aggregates :func:`plan_push_clip` over every ``clips`` row whose
    parent track belongs to this song. Per-clip warnings are prefixed
    with the clip name so the merged plan stays diagnosable.

    Strict precondition (inherited from :func:`plan_push_clip`): every
    clip's track must already be linked in this session. Run
    :func:`plan_push_song_tracks` first, ``apply_push_results``, then
    this. The strict raise surfaces orchestration order bugs loudly —
    a silent skip would leave Live missing clips with no signal.
    """
    # Resolve `plan_push_clip` through the package facade at call time so
    # callers that monkeypatch the public `push.plan_push_clip` seam (the
    # behavior the original single-module file exposed) still intercept it.
    # Function-local import avoids a load-time cycle (the package __init__
    # imports this module).
    from hallucinote.sync import push

    plan = PushPlan()
    rows = Q.get_clips_for_song(conn, song_id)
    for c in rows:
        sub = push.plan_push_clip(conn, clip_id=c["id"], session_id=session_id)
        plan.calls.extend(sub.calls)
        plan.notes.extend(f"[{c['name']}] {n}" for n in sub.notes)
    if not plan.calls and not plan.notes:
        plan.warn("no clips for this song; nothing to push")
    return plan
