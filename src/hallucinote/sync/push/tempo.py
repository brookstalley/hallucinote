"""Score-half planners: tempo map + time-signature map."""
from __future__ import annotations

import sqlite3

from hallucinote.db import queries as Q

from ._core import PushPlan, ToolCall


def plan_push_tempo_map(
    conn: sqlite3.Connection,
    *,
    song_id: str,
) -> PushPlan:
    """Emit `ableton_session(set_tempo)` for the bar-1 row; warn for the rest.

    Live exposes `Song.tempo` as a single global value (settable via
    `ableton_session(action='set_tempo')`). Per-bar tempo automation is a
    real MCP gap — `ableton_automation` has no `song_tempo` target_kind
    (see hallucinote_mcp/.../guides/gaps.md "Arrangement-level tempo /
    signature automation"). Any tempo_map row at start_bar != 1.0 is
    therefore skipped with a warn.
    """
    plan = PushPlan()
    rows = Q.get_tempo_map(conn, song_id)
    if not rows:
        plan.warn("no tempo_map rows for this song; nothing to push")
        return plan
    bar_1 = next((r for r in rows if float(r["start_bar"]) == 1.0), None)
    if bar_1 is not None:
        plan.add(ToolCall(
            tool="ableton_session",
            args={"action": "set_tempo", "bpm": bar_1["tempo_bpm"]},
            key=f"tempo_point:{bar_1['id']}",
            purpose=f"set global tempo to {bar_1['tempo_bpm']:g} bpm",
        ))
    else:
        plan.warn(
            "tempo_map has no row at start_bar=1.0 — global tempo not set "
            "(Live's set_tempo only addresses the bar-1 value)"
        )
    non_bar_1 = [r for r in rows if float(r["start_bar"]) != 1.0]
    if non_bar_1:
        plan.warn(
            f"per-bar tempo automation is an MCP gap on Live 12.4 — "
            f"ableton_automation has no 'song_tempo' target_kind "
            f"(see hallucinote_mcp/.../guides/gaps.md); "
            f"{len(non_bar_1)} non-bar-1 tempo_map rows skipped"
        )
    return plan


def plan_push_time_signature_map(
    conn: sqlite3.Connection,
    *,
    song_id: str,
) -> PushPlan:
    """Emit `ableton_session(set_signature)` for the bar-1 row; warn the rest.

    Symmetric with `plan_push_tempo_map`. Live's `Song.signature_numerator` /
    `signature_denominator` are the global meter (settable via
    `ableton_session(action='set_signature')`). Per-bar meter automation
    is a real MCP gap — `ableton_automation` has no `song_signature`
    target_kind (see hallucinote_mcp/.../guides/gaps.md).
    """
    plan = PushPlan()
    rows = Q.get_time_signature_map(conn, song_id)
    if not rows:
        plan.warn("no time_signature_map rows for this song; nothing to push")
        return plan
    bar_1 = next((r for r in rows if float(r["start_bar"]) == 1.0), None)
    if bar_1 is not None:
        plan.add(ToolCall(
            tool="ableton_session",
            args={
                "action": "set_signature",
                "numerator": bar_1["numerator"],
                "denominator": bar_1["denominator"],
            },
            key=f"time_signature_point:{bar_1['id']}",
            purpose=(
                f"set global meter to "
                f"{bar_1['numerator']}/{bar_1['denominator']}"
            ),
        ))
    else:
        plan.warn(
            "time_signature_map has no row at start_bar=1.0 — global meter "
            "not set (Live's set_signature only addresses the bar-1 value)"
        )
    non_bar_1 = [r for r in rows if float(r["start_bar"]) != 1.0]
    if non_bar_1:
        plan.warn(
            f"per-bar meter automation is an MCP gap on Live 12.4 — "
            f"ableton_automation has no 'song_signature' target_kind "
            f"(see hallucinote_mcp/.../guides/gaps.md); "
            f"{len(non_bar_1)} non-bar-1 time_signature_map rows skipped"
        )
    return plan
