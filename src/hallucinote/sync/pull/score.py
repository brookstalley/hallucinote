"""Cue-point pull: arrangement cue-list planner + apply.

(Global tempo/signature score fields ride the session_info probe and live in
`mix.py` alongside the master-mixer apply that shares the same probe.)
"""
from __future__ import annotations

import sqlite3
from typing import Any

from hallucinote.db import mutations as M, queries as Q

from ._core import (
    PullCall,
    PullPlan,
    ApplyResult,
    _join_bar_beat,
    _is_numeric_id_name,
    _beats_to_position_bar,
)


def plan_pull_cue_points(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    session_id: str,
) -> PullPlan:
    """Plan a single `ableton_arrangement(action='cue_list')` probe.

    Wave M-5: retargeted from the legacy fork's `get_cue_points` to the
    unified arrangement tool. Cue identity is `(position_beats)` with
    float-tolerance — matching by position is the only stable handle.
    Names round-trip cleanly in the greenfield server (gap #13 doesn't
    apply); apply layer still treats name diffs as informational since
    DB-side cue names are user-authoritative.
    """
    plan = PullPlan()
    plan.add(PullCall(
        tool="ableton_arrangement",
        args={"action": "cue_list"},
        key="cue_points_list",
        purpose="pull arrangement cue points (position_beats + names)",
    ))
    return plan


def _apply_cue_points_list(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    result: list[dict[str, Any]],
    out: ApplyResult,
    actor: str,
    request_id: str | None,
    reason: str | None,
) -> None:
    """Ingest Ableton's cue points by position.

    Matching: `(position_bar)` with float tolerance. Three diff classes:
      - position present in Ableton, absent in DB -> add_cue_point (the
        Ableton-side name IS stored on add, since Wave M-5's
        ableton_arrangement(action='cue_list') returns real names rather
        than the legacy fork's numeric IDs)
      - position present in both -> no-op (with a name-mismatch warning
        if the pulled name differs from DB; DB names are user-authoritative
        so pulls do not overwrite them)
      - position present in DB, absent in Ableton -> remove_cue_point

    The numeric-ID-name detector stays as a defense against agent-layer
    reformatting that might re-introduce the legacy fork's numeric shape.
    """
    ts_points = Q.get_time_signature_map(conn, song_id)
    db_cues = list(Q.get_cue_points(conn, song_id))
    # Round to fixed precision for tolerant matching (1/1000 of a bar — way
    # finer than any musically meaningful cue placement).
    pos_key = lambda pb: round(float(pb), 3)
    db_by_pos: dict[float, sqlite3.Row] = {pos_key(c["position_bar"]): c for c in db_cues}
    seen: set[float] = set()

    for entry in result:
        # Accept three shapes (Wave M-5 adds position_beats):
        #   {position_beats: float}            (greenfield arrangement.cue_list)
        #   {position_bar: float}              (legacy / pre-normalized)
        #   {bar: int, beat: float}            (legacy fork shape)
        if "position_beats" in entry:
            position_bar = _beats_to_position_bar(
                float(entry["position_beats"]), ts_points
            )
        elif "position_bar" in entry:
            position_bar = float(entry["position_bar"])
        elif "bar" in entry:
            # Legacy fork shape — dormant since the legacy fork was retired
            # in W3 / Wave M. Guard `bar < 1` because the new
            # `cue_points.position_bar >= 1.0` CHECK (added J-6) would
            # `IntegrityError` on `_join_bar_beat(0, ...)` → 0.0. Warn and
            # skip rather than crashing the whole pull on bad upstream data.
            bar_in = int(entry["bar"])
            if bar_in < 1:
                out.warnings.append(
                    f"cue_points_list entry has legacy bar={bar_in!r} "
                    "(< 1) — schema requires position_bar >= 1.0; skipping"
                )
                continue
            position_bar = _join_bar_beat(
                bar_in, float(entry.get("beat", 0.0)), ts_points
            )
        else:
            out.warnings.append(
                f"cue_points_list entry missing position: {entry!r}"
            )
            continue
        k = pos_key(position_bar)
        seen.add(k)
        existing = db_by_pos.get(k)
        name_in = entry.get("name")
        if existing is None:
            # New from Ableton — add. Drop numeric-ID names (gap #13).
            stored_name = None if _is_numeric_id_name(name_in) else name_in
            M.add_cue_point(
                conn, song_id=song_id, position_bar=position_bar,
                name=stored_name,
                actor=actor, request_id=request_id, reason=reason,
            )
            out.mutations += 1
            out.details.append(
                f"cue: added at bar {position_bar:g}"
                + (f" (name={stored_name!r})" if stored_name else "")
            )
            continue
        # Position matches. Flag name diffs but don't mutate (gap #13).
        if (name_in
            and not _is_numeric_id_name(name_in)
            and name_in != existing["name"]):
            out.warnings.append(
                f"cue at bar {position_bar:g}: name mismatch "
                f"(DB={existing['name']!r}, Ableton={name_in!r}); "
                "names not pulled (MCP gap #13)"
            )
        out.no_ops += 1

    # Removals: DB cues not seen in Ableton.
    for c in db_cues:
        if pos_key(c["position_bar"]) in seen:
            continue
        M.remove_cue_point(
            conn, cue_id=c["id"],
            actor=actor, request_id=request_id, reason=reason,
        )
        out.mutations += 1
        out.details.append(
            f"cue: removed at bar {c['position_bar']:g}"
            + (f" (was {c['name']!r})" if c["name"] else "")
        )


__all__ = [
    "plan_pull_cue_points",
    "_apply_cue_points_list",
]
