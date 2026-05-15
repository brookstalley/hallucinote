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

# Live's default meter when a song has no `time_signature_map` rows.
_DEFAULT_NUMERATOR = 4
_DEFAULT_DENOMINATOR = 4


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


def _beats_per_bar(numerator: int, denominator: int) -> float:
    """Live counts a beat as a quarter note regardless of meter, so the beat
    count per bar is `numerator * (4 / denominator)` (e.g., 6/8 -> 3 beats,
    7/4 -> 7 beats, 4/4 -> 4 beats)."""
    return numerator * (4.0 / denominator)


def _meter_at_bar(
    bar: float,
    ts_points: list[sqlite3.Row],
) -> tuple[int, int]:
    """Return (numerator, denominator) effective at a 1-based bar position.

    Empty ts_points fall back to 4/4. Bars before the first map point use the
    first point's meter — matches Live's behavior for unmarked regions.
    """
    if not ts_points:
        return (_DEFAULT_NUMERATOR, _DEFAULT_DENOMINATOR)
    chosen = ts_points[0]
    for p in ts_points:
        if p["start_bar"] <= bar:
            chosen = p
        else:
            break
    return (chosen["numerator"], chosen["denominator"])


def _split_bar(
    bar_pos: float,
    ts_points: list[sqlite3.Row],
) -> tuple[int, float]:
    """Split a 1-based fractional bar position into (bar_int, beat_within_bar).

    Matches the `(bar: int 1-based, beat: float 0-based-within-bar)` shape that
    Live's MCP tools use throughout. `bar_pos=4.5` in 4/4 -> (4, 2.0).
    """
    bar_int = int(bar_pos)
    frac = bar_pos - bar_int
    num, den = _meter_at_bar(bar_pos, ts_points)
    return bar_int, frac * _beats_per_bar(num, den)


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
# Score-half planners: tempo / meter / cue points / sections
# ---------------------------------------------------------------------------


def plan_push_tempo_map(
    conn: sqlite3.Connection,
    *,
    song_id: str,
) -> PushPlan:
    """Emit canonical `write_tempo_point` calls — one per row in `tempo_map`.

    Positions are emitted as `(bar, beat)` matching the rest of the MCP surface
    (see mcp-requirements.md). The (bar, beat) pair is computed via the song's
    time_signature_map (defaulting to 4/4 if empty, with a warning).
    """
    plan = PushPlan()
    rows = Q.get_tempo_map(conn, song_id)
    if not rows:
        plan.warn("no tempo_map rows for this song; nothing to push")
        return plan
    ts_points = Q.get_time_signature_map(conn, song_id)
    if not ts_points:
        plan.warn(
            "no time_signature_map; assuming 4/4 for tempo-map bar/beat split"
        )
    for r in rows:
        bar, beat = _split_bar(r["start_bar"], ts_points)
        plan.add(ToolCall(
            tool="write_tempo_point",
            args={
                "bar": bar,
                "beat": beat,
                "bpm": r["tempo_bpm"],
                "ramp": r["ramp"],
            },
            key=f"tempo_point:{r['id']}",
            purpose=f"set tempo to {r['tempo_bpm']:g} bpm at bar {r['start_bar']:g} "
                    f"(ramp={r['ramp']})",
        ))
    if len(rows) > 1 or any(r["ramp"] == "linear" for r in rows):
        plan.warn(
            "multi-point or ramped tempo maps require full tempo-automation MCP "
            "support (see docs/mcp-requirements.md, P2)"
        )
    return plan


def plan_push_time_signature_map(
    conn: sqlite3.Connection,
    *,
    song_id: str,
) -> PushPlan:
    """Emit canonical `write_time_signature_point` calls — one per meter change.

    Live exposes no MCP tool for arrangement-level meter changes today; the
    planner produces canonical (bar, beat, numerator, denominator) calls and
    warns about the MCP gap so apply can no-op until support lands.
    """
    plan = PushPlan()
    rows = Q.get_time_signature_map(conn, song_id)
    if not rows:
        plan.warn("no time_signature_map rows for this song; nothing to push")
        return plan
    for r in rows:
        # A time-signature point's own position is in its own meter context —
        # use `rows` (the map itself) as the time-sig reference.
        bar, beat = _split_bar(r["start_bar"], rows)
        plan.add(ToolCall(
            tool="write_time_signature_point",
            args={
                "bar": bar,
                "beat": beat,
                "numerator": r["numerator"],
                "denominator": r["denominator"],
            },
            key=f"time_signature_point:{r['id']}",
            purpose=f"set meter to {r['numerator']}/{r['denominator']} "
                    f"at bar {r['start_bar']:g}",
        ))
    plan.warn(
        "time-signature change writes are an MCP gap "
        "(see docs/mcp-requirements.md, P2)"
    )
    return plan


def plan_push_cue_points(
    conn: sqlite3.Connection,
    *,
    song_id: str,
) -> PushPlan:
    """Emit `create_cue_point` calls for every row in `cue_points`.

    Live's MCP `create_cue_point(bar, beat, name)` is callable today, with
    `bar` 1-based int and `beat` 0-based float within that bar. The planner
    splits each row's fractional `position_bar` accordingly using the song's
    time_signature_map.
    """
    plan = PushPlan()
    rows = Q.get_cue_points(conn, song_id)
    if not rows:
        plan.warn("no cue_points for this song; nothing to push")
        return plan
    ts_points = Q.get_time_signature_map(conn, song_id)
    if not ts_points:
        plan.warn(
            "no time_signature_map; assuming 4/4 for cue-point bar/beat split"
        )
    for r in rows:
        bar, beat = _split_bar(r["position_bar"], ts_points)
        plan.add(ToolCall(
            tool="create_cue_point",
            args={"bar": bar, "beat": beat, "name": r["name"] or ""},
            key=f"cue_point:{r['id']}",
            purpose=f"create cue point '{r['name'] or ''}' at bar {r['position_bar']:g}",
        ))
    return plan


def plan_push_sections(
    conn: sqlite3.Connection,
    *,
    song_id: str,
) -> PushPlan:
    """Sections are DB-only metadata today — Live has no section-marker concept
    distinct from cue points. The planner emits no calls; it surfaces the
    section count as a warn so callers can decide whether to mirror sections
    as cue points themselves."""
    plan = PushPlan()
    rows = Q.get_sections_for_song(conn, song_id)
    if rows:
        plan.warn(
            f"{len(rows)} section(s) are DB-only; Live exposes no section-marker "
            "tool. Consider creating matching cue_points for visibility."
        )
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
