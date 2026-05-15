"""DB -> Ableton planner.

Produces a list of `ToolCall` objects describing what the agent should run.
After the agent executes the plan, it calls `apply_push_results` to write
Ableton-side IDs back into the DB.

Why a plan rather than direct calls: MCP tools are invoked by the agent, not
by Python. Returning a plan keeps this layer pure, testable, and reorder-safe.

Sessions: every plan/apply takes a `session_id` (an `ableton_sessions` row).
Bindings live in `ableton_links`, not on core rows — so a song can be bound
to multiple Live sets at the same time without aliasing. Open one with
`mutations.create_ableton_session`.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field, asdict
from typing import Any

from songwright.db import mutations as M, queries as Q


@dataclass
class ToolCall:
    """One MCP tool invocation. `key` lets results be matched back to ops.

    Names are *canonical* (post-Wave-1). Agent uses `mcp_names.resolve` to
    map onto today's surface.
    """
    tool: str
    args: dict[str, Any]
    key: str  # caller-chosen identifier; used in apply_push_results
    purpose: str = ""  # human-readable hint for the agent


@dataclass
class PushPlan:
    calls: list[ToolCall] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)  # human notes / warnings

    def add(self, call: ToolCall) -> None:
        self.calls.append(call)

    def warn(self, msg: str) -> None:
        self.notes.append(msg)

    def to_dict(self) -> dict[str, Any]:
        return {
            "calls": [asdict(c) for c in self.calls],
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# Note conversion: DB -> MCP
# ---------------------------------------------------------------------------


def _notes_for_mcp(notes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """DB notes carry tags + extra fields; MCP wants the bare quartet."""
    return [
        {
            "pitch": n["pitch"],
            "start_time": n["start_beats"],
            "duration": n["duration_beats"],
            "velocity": n["velocity"],
            "mute": bool(n["mute"]),
        }
        for n in notes
    ]


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------


def plan_push_clip(
    conn: sqlite3.Connection,
    *,
    clip_id: str,
    session_id: str,
) -> PushPlan:
    """Plan the push of a single session clip (track + notes) to Ableton.

    Three cases:
      1. Track not yet linked in this session -> create_midi_track_with, then ...
      2. Clip not yet linked in this session  -> replace_session_clip (atomic)
      3. Clip already linked                  -> set_clip_notes (in-place)
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
        plan.add(ToolCall(
            tool="create_midi_track_with",
            args={
                "name": track_row["name"],
                "instrument_uri": track_row["instrument_uri"],
                "index": -1,
            },
            key=f"track:{track_row['id']}",
            purpose=f"create track '{track_row['name']}' (db track_id={track_row['id']})",
        ))
        plan.warn(
            f"track {track_row['id']} has no ableton link in session {session_id} yet — "
            f"after create_midi_track_with returns, call apply_push_results to record it."
        )
        # Subsequent calls in this plan can't run until we know the new track index.
        # The agent should execute the track-creation, capture the result, call
        # apply_push_results, then re-plan to pick up the now-linked track.
        return plan

    if clip_at is None:
        plan.add(ToolCall(
            tool="replace_session_clip",
            args={
                "track_index": track_at,
                "clip_index": clip["slot"],
                "length": clip["length_beats"],
                "name": clip["name"],
                "notes": _notes_for_mcp(notes),
            },
            key=f"clip:{clip_id}",
            purpose=f"create+populate session clip slot {clip['slot']} on track {track_at}",
        ))
    else:
        plan.add(ToolCall(
            tool="set_clip_notes",
            args={
                "track_index": track_at,
                "clip_index": clip_at,
                "notes": _notes_for_mcp(notes),
            },
            key=f"clip:{clip_id}",
            purpose=f"replace notes in existing clip ({len(notes)} notes)",
        ))

    return plan


def plan_push_arrangement(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    session_id: str,
) -> PushPlan:
    """Plan rebuilding the arrangement for a song.

    Strategy: clear all existing arrangement clips for the involved tracks,
    then duplicate session clips into the arrangement at their target bars.
    Single batch_arrangement_layout call.

    Pre-conditions (planner asserts and warns; doesn't fix):
      - All tracks involved have a `track` link in this session
      - All clips involved have a `clip` link in this session
    """
    plan = PushPlan()
    arr_rows = Q.get_arrangement_for_song(conn, song_id)
    if not arr_rows:
        plan.warn("no arrangement rows for this song")
        return plan

    operations: list[dict[str, Any]] = []
    track_indices_seen: set[int] = set()

    for row in arr_rows:
        track_at = Q.get_ableton_link(
            conn, session_id=session_id, db_kind="track", db_id=row["track_id"]
        )
        if track_at is None:
            plan.warn(f"arrangement {row['id']}: track not linked in this session — skipping")
            continue
        clip_at = Q.get_ableton_link(
            conn, session_id=session_id, db_kind="clip", db_id=row["clip_id"]
        )
        if clip_at is None:
            plan.warn(
                f"arrangement {row['id']}: clip {row['clip_id']} not linked in this session — skipping"
            )
            continue
        track_indices_seen.add(track_at)
        operations.append({
            "op": "duplicate",
            "track_index": track_at,
            "clip_index": clip_at,
            "destination_bar": row["start_bar"],
            "key": f"arrangement:{row['id']}",
        })

    # Clear pass: caller-controlled. Conservative default — assume agent wipes
    # arrangement clips on listed tracks before this batch runs. We could add
    # explicit delete ops here once the planner knows what's currently in the
    # arrangement (requires a get_arrangement_info pre-call).
    if operations:
        plan.add(ToolCall(
            tool="batch_arrangement_layout",
            args={"operations": operations},
            key=f"arrangement_batch:{song_id}",
            purpose=f"rebuild arrangement: {len(operations)} duplicates "
                    f"across {len(track_indices_seen)} tracks",
        ))
    plan.warn("planner does not yet emit pre-clear ops — agent must clear target tracks first")
    return plan


# ---------------------------------------------------------------------------
# Result application
# ---------------------------------------------------------------------------


def apply_push_results(
    conn: sqlite3.Connection,
    results: list[dict[str, Any]],
    *,
    session_id: str,
    actor: str = "sync",
    request_id: str | None = None,
    reason: str | None = None,
) -> None:
    """After the agent runs the plan, feed structured results back here so the
    DB knows what's now in Ableton. Bindings are recorded in `ableton_links`
    for `session_id`, not on core rows.

    Each result dict shape:
        {
          "key": "<the ToolCall.key from the plan>",
          "ok": bool,
          "tool": "<canonical tool name>",
          "result": { ... tool-specific shape ... },
          "error": "...optional..."
        }

    Recognized result shapes:
      - track:<uuid> from create_midi_track_with
            result = {"track_index": int}
      - clip:<uuid> from replace_session_clip / set_clip_notes
            result = {"clip_index": int}  # only relevant for replace; ignored otherwise
      - arrangement:<uuid> from a duplicate op inside batch_arrangement_layout
            result = {"arrangement_clip_index": int}
    """
    with conn:
        for r in results:
            if not r.get("ok"):
                continue
            key = r.get("key", "")
            kind, _, db_id = key.partition(":")
            if not db_id:
                continue

            res = r.get("result") or {}
            if kind == "track" and "track_index" in res:
                M.link_db_to_ableton(
                    conn,
                    session_id=session_id,
                    db_kind="track",
                    db_id=db_id,
                    ableton_index=res["track_index"],
                    actor=actor,
                    request_id=request_id,
                    reason=reason,
                )
            elif kind == "clip" and "clip_index" in res:
                M.link_db_to_ableton(
                    conn,
                    session_id=session_id,
                    db_kind="clip",
                    db_id=db_id,
                    ableton_index=res["clip_index"],
                    actor=actor,
                    request_id=request_id,
                    reason=reason,
                )
            elif kind == "arrangement" and "arrangement_clip_index" in res:
                M.link_db_to_ableton(
                    conn,
                    session_id=session_id,
                    db_kind="arrangement",
                    db_id=db_id,
                    ableton_index=res["arrangement_clip_index"],
                    actor=actor,
                    request_id=request_id,
                    reason=reason,
                )
