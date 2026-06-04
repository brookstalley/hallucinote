"""Clip-placement pull: arrangement-clip placements + session-view clip slots
— planners + apply.
"""
from __future__ import annotations

import sqlite3
from typing import Any

from hallucinote.db import mutations as M, queries as Q

from ._core import (
    PullCall,
    PullPlan,
    ApplyResult,
    _floats_differ,
    _beats_to_position_bar,
)


def plan_pull_arrangement_clips(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    session_id: str,
) -> PullPlan:
    """Plan probes to pull per-track arrangement-clip placements (W3-4 / M+1-3b).

    Emits one ``ableton_clip(action='list', location='arrangement',
    track_index=N)`` per linked authoring track. The probe returns dense
    placements `{arrangement_clip_index, name, start_beats, length}`; the
    apply layer converts beats -> bars via the song's time-signature map and
    diffs positionally against `arrangement_clips` table rows.

    Skips `master` track rows: master has no arrangement of its own.
    Real returns live in the `returns` table and don't appear in the
    `tracks` iteration this planner walks (the legacy
    `tracks.kind='return'` reservation was dropped V1 close-out
    2026-05-17).

    Per `docs/terminology.md`, this is exclusively about arrangement-clip
    *placements* (rows in the `arrangement_clips` table).
    Arrangement-VIEW state (loop region, view zoom) is a separate concern
    with no DB home today (backlog).
    """
    plan = PullPlan()
    any_emitted = False
    for t in Q.get_tracks_for_song(conn, song_id):
        if t["kind"] == "master":
            continue
        track_at = Q.get_ableton_link(
            conn, session_id=session_id, db_kind="track", db_id=t["id"]
        )
        if track_at is None:
            plan.warn(
                f"track {t['name']!r} ({t['id']}) not linked in session — "
                "push it via plan_push_clip first, then re-run pull"
            )
            continue
        any_emitted = True
        plan.add(PullCall(
            tool="ableton_clip",
            args={
                "action": "list",
                "location": "arrangement",
                "track_index": track_at,
            },
            key=f"track_arrangement_clips:{t['id']}",
            purpose=f"pull arrangement-clip placements for track {t['name']!r}",
        ))
    if not any_emitted:
        plan.warn(
            "no linked authoring tracks for this session — "
            "arrangement-clip pull will be empty"
        )
    return plan


def plan_pull_session_clips(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    session_id: str,
) -> PullPlan:
    """Plan probes to pull per-track session-view clip-slot contents
    (V1 close-out Chunk C).

    Emits one ``ableton_clip(action='list', location='session',
    track_index=N)`` per linked authoring track. The probe returns dense
    per-slot entries — populated slots carry
    ``{clip_index, empty: False, name, length}``; empty slots carry
    ``{clip_index, empty: True}``. The apply layer diffs by slot
    (``clips.slot``, which Ableton calls ``clip_index``), the most
    stable identity available for session-view clips.

    Skips `master` track rows: master has no session-view clip grid.
    Real returns live in the `returns` table and don't appear in the
    `tracks` iteration this planner walks.

    Symmetric with `plan_pull_arrangement_clips`. The MCP read side
    shipped in M+1-3a; this planner closes the sync-layer half so
    edits made in Ableton's Session View round-trip back to the DB.
    """
    plan = PullPlan()
    any_emitted = False
    for t in Q.get_tracks_for_song(conn, song_id):
        if t["kind"] == "master":
            continue
        track_at = Q.get_ableton_link(
            conn, session_id=session_id, db_kind="track", db_id=t["id"]
        )
        if track_at is None:
            plan.warn(
                f"track {t['name']!r} ({t['id']}) not linked in session — "
                "push it via plan_push_clip first, then re-run pull"
            )
            continue
        any_emitted = True
        plan.add(PullCall(
            tool="ableton_clip",
            args={
                "action": "list",
                "location": "session",
                "track_index": track_at,
            },
            key=f"track_session_clips:{t['id']}",
            purpose=f"pull session-view clip slots for track {t['name']!r}",
        ))
    if not any_emitted:
        plan.warn(
            "no tracks linked in this session — "
            "session-clip pull will be empty"
        )
    return plan


def _apply_arrangement_clips_for_track(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    session_id: str,
    track_id: str,
    result: dict[str, Any],
    out: ApplyResult,
    actor: str,
    request_id: str | None,
    reason: str | None,
) -> None:
    """Diff arrangement-clip placements on one track against the probe payload
    (W3-4 / M+1-3b).

    Identity is positional: matched by `(start_bar, end_bar)` within bar-
    epsilon tolerance. No `update_arrangement` mutator exists; any field
    change becomes delete + add at the new position — parity with
    `_apply_devices_for_parent` for the same "no stable per-element
    identity" reason. Live's `ableton_link` for arrangement rows binds an
    `arrangement_clip_index` but Live re-numbers those on any delete, so
    the index isn't a stable handle for diff matching either.

    Diff classes handled:
      - `(start, end)` in both DB and Ableton  -> no-op
      - `(start, end)` in DB only              -> `remove_arrangement_clip`
      - `(start, end)` in Ableton only         -> warn + skip
      - duplicate `(start, end)` in DB         -> warn + first-row-wins

    Why warn-and-skip on Ableton-only: positional matching cannot tell
    a *new* placement (user drew/duplicated a clip) from a *moved*
    placement (user dragged an existing one). For a new placement, the
    MCP wire shape carries no DB `clip_id` and V1 can't auto-create a
    `clips` row from name + length + start alone. For a move, the
    underlying `clips` row already exists but the apply layer has no way
    to know which DB row Ableton's placement came from. V1 takes no
    action either way; the user mirrors the change in DB and re-runs
    pull on the next pass. The remove `details` line carries the
    removed row's `clip_id` prefix + `clip_name` so the user can
    correlate the two halves of a move case manually.

    Renames not detected: the `arrangement_clips` table has no `name` column;
    display names live on `clips.name`. Manual renames of an arrangement
    clip in Live are silently lost by this apply. The user can rename via
    the DB-side clip name (clips are shared across placements).

    Defense-in-depth link check parallels `_apply_devices_for_parent`.
    """
    if Q.get_ableton_link(
        conn, session_id=session_id, db_kind="track", db_id=track_id,
    ) is None:
        out.skipped_unlinked += 1
        out.warnings.append(
            f"track_arrangement_clips for {track_id!r}: not linked in session; "
            "skipping (the planner would not have emitted this)"
        )
        return

    track_row = Q.get_track(conn, track_id)
    if track_row is None:
        out.warnings.append(
            f"track_arrangement_clips:{track_id} — DB row missing; skipping"
        )
        return

    clips_in = result.get("clips")
    if clips_in is None:
        out.warnings.append(
            f"track_arrangement_clips for {track_id!r}: result missing "
            "'clips' field"
        )
        return

    ts_points = Q.get_time_signature_map(conn, song_id)

    # 1/1000 of a bar — same precision as `_apply_cue_points_list`. Finer
    # than any musically meaningful placement.
    def _pos_key(b: float) -> float:
        return round(float(b), 3)

    db_rows = Q.get_arrangement_for_track(conn, track_id)
    # Build a positional lookup; warn on any duplicate (start_bar, end_bar)
    # key because the dict would otherwise silently keep only the last row
    # at that position and the diff would under-report. Exact-coincidence
    # on the same track is rare in practice (Live permits overlap but two
    # placements with identical start AND end bars is a user-authoring
    # oddity); first-row-wins preserves the diff's no-op/remove behavior
    # for the common case.
    db_by_pos: dict[tuple[float, float], sqlite3.Row] = {}
    for r in db_rows:
        k = (_pos_key(r["start_bar"]), _pos_key(r["end_bar"]))
        if k in db_by_pos:
            kept = db_by_pos[k]
            out.warnings.append(
                f"track {track_row['name']!r}: duplicate arrangement-clip "
                f"placements at bar {r['start_bar']:g}..{r['end_bar']:g} "
                f"(keeping arrangement_clip_id={kept['id'][:8]} "
                f"{kept['clip_name']!r}; the collision with "
                f"arrangement_clip_id={r['id'][:8]} {r['clip_name']!r} "
                f"will not round-trip cleanly — separate them or remove one)"
            )
            continue
        db_by_pos[k] = r
    seen: set[tuple[float, float]] = set()

    for entry in clips_in:
        sb_in = entry.get("start_beats")
        len_in = entry.get("length")
        if sb_in is None or len_in is None:
            out.warnings.append(
                f"track_arrangement_clips for {track_id!r}: entry missing "
                f"start_beats or length: {entry!r}"
            )
            continue
        start_bar = _beats_to_position_bar(float(sb_in), ts_points)
        end_bar = _beats_to_position_bar(
            float(sb_in) + float(len_in), ts_points
        )
        k = (_pos_key(start_bar), _pos_key(end_bar))
        seen.add(k)
        if k in db_by_pos:
            out.no_ops += 1
            continue
        # Ableton has a placement at a (start, end) the DB doesn't
        # know about. Could be a brand-new clip OR an existing
        # placement the user moved — positional matching can't tell
        # the two apart. V1 takes no action either way: it doesn't
        # auto-create `clips` rows and doesn't infer moves.
        out.warnings.append(
            f"track {track_row['name']!r}: arrangement clip "
            f"{entry.get('name')!r} at bar {start_bar:g}..{end_bar:g} "
            "has no matching DB placement — V1 does not auto-add. "
            "Mirror the change in DB (add a new placement, or re-add "
            "a moved one) and re-run pull."
        )

    # Removals: DB rows Ableton didn't report. The detail line carries
    # the clip_id prefix + clip_name so the user can correlate against
    # the "Ableton-only placement" warnings above when a placement was
    # moved (positional matching can't infer the move, but the breadcrumb
    # lets the user join the two halves manually).
    for k, row in db_by_pos.items():
        if k in seen:
            continue
        M.remove_arrangement_clip(
            conn, arrangement_clip_id=row["id"],
            actor=actor, request_id=request_id, reason=reason,
        )
        out.mutations += 1
        out.details.append(
            f"track {track_row['name']!r}: arrangement placement at "
            f"bar {row['start_bar']:g}..{row['end_bar']:g} removed "
            f"(arrangement_clip_id={row['id'][:8]} {row['clip_name']!r})"
        )


def _apply_session_clips_for_track(
    conn: sqlite3.Connection,
    *,
    result: dict[str, Any],
    track_id: str,
    song_id: str,
    session_id: str,
    out: ApplyResult,
    actor: str,
    request_id: str | None,
    reason: str | None,
) -> None:
    """Diff session-view clip-slot contents on one track against the probe
    payload (V1 close-out Chunk C).

    Identity is slot-positional: matched by `clips.slot` (the 1-based
    clip-slot index Ableton calls `clip_index`). Slots are the stablest
    addressing Live exposes for session clips, so the diff is cleaner
    than arrangement-clip's `(start_bar, end_bar)` matching.

    Diff classes handled:
      - slot populated in both DB and Ableton, name + length match -> no-op
      - slot populated in both, name and/or length drift           -> `update_clip` with the drifted fields
      - slot populated in DB only (Ableton slot empty)             -> `delete_clip`
      - slot populated in Ableton only                             -> warn + skip
        (V1 can't auto-create the DB clip from name + length alone;
         note pull would let us fill in content, but distinguishing a
         brand-new session clip from a moved-into-this-slot existing
         clip is the same identity problem as the arrangement case)

    Note content drift is NOT detected here — that's Chunk D's job
    (note pull via stable-ID read). This planner only diffs the
    container-level fields (`name`, `length`) the MCP read action
    returns.

    Defense-in-depth link check parallels `_apply_arrangement_clips_for_track`.
    """
    if Q.get_ableton_link(
        conn, session_id=session_id, db_kind="track", db_id=track_id,
    ) is None:
        out.skipped_unlinked += 1
        out.warnings.append(
            f"track_session_clips for {track_id!r}: not linked in session; "
            "skipping (the planner would not have emitted this)"
        )
        return

    track_row = Q.get_track(conn, track_id)
    if track_row is None:
        out.warnings.append(
            f"track_session_clips:{track_id} — DB row missing; skipping"
        )
        return

    clips_in = result.get("clips")
    if clips_in is None:
        out.warnings.append(
            f"track_session_clips for {track_id!r}: result missing "
            "'clips' field"
        )
        return

    db_by_slot: dict[int, sqlite3.Row] = {
        int(c["slot"]): c for c in Q.get_clips_for_track(conn, track_id)
    }
    seen: set[int] = set()

    for entry in clips_in:
        slot_in = entry.get("clip_index")
        if slot_in is None:
            out.warnings.append(
                f"track_session_clips for {track_id!r}: entry missing "
                f"'clip_index': {entry!r}"
            )
            continue
        slot = int(slot_in)
        seen.add(slot)
        empty = bool(entry.get("empty", False))
        db_clip = db_by_slot.get(slot)

        if empty:
            # Ableton slot empty; if DB has a clip, delete it.
            if db_clip is not None:
                _delete_session_clip_observing_cascade(
                    conn, track_row=track_row, slot=slot, db_clip=db_clip,
                    out=out, actor=actor, request_id=request_id, reason=reason,
                    cause="cleared in Ableton",
                )
            else:
                out.no_ops += 1
            continue

        # Ableton slot populated. SYN-9K5T parity: the arrangement-clip
        # apply warns when a populated entry is missing the fields it diffs
        # on. The session apply diffs on `name` + `length`; a populated entry
        # carrying neither can't drift-match, so it would silently no-op.
        # Warn explicitly (matching `_apply_arrangement_clips_for_track`'s
        # "entry missing ..." warning) rather than tolerate the asymmetry.
        if entry.get("name") is None and entry.get("length") is None:
            out.warnings.append(
                f"track {track_row['name']!r}: session slot {slot} reported "
                f"populated but missing both 'name' and 'length' — cannot "
                f"diff; skipping (entry={entry!r})"
            )
            continue

        if db_clip is None:
            # Ableton has content the DB doesn't know about. Same V1
            # limitation as the arrangement-clip case: positional
            # matching can't distinguish a brand-new clip from a
            # session-side move, and the MCP wire shape doesn't carry
            # note content for auto-create.
            out.warnings.append(
                f"track {track_row['name']!r}: session slot {slot} has "
                f"clip {entry.get('name')!r} (length {entry.get('length')}) "
                "with no matching DB clip — V1 does not auto-add. "
                "Mirror the change in DB (create the clip + author notes) "
                "and re-run pull."
            )
            continue

        # Both populated -> check for drift.
        changes: dict[str, Any] = {}
        name_in = entry.get("name")
        if name_in is not None and name_in != db_clip["name"]:
            changes["name"] = name_in
        len_in = entry.get("length")
        if _floats_differ(len_in, db_clip["length_beats"]):
            changes["length_beats"] = float(len_in)
        if changes:
            M.update_clip(
                conn, clip_id=db_clip["id"],
                actor=actor, request_id=request_id, reason=reason,
                **changes,
            )
            out.mutations += 1
            out.details.append(
                f"track {track_row['name']!r}: session slot {slot} updated "
                f"(clip_id={db_clip['id'][:8]}): {changes!r}"
            )
        else:
            out.no_ops += 1

    # Slots present in DB but NOT reported by Ableton's dense list:
    # treat as deletion. Ableton's `list` action returns every slot in
    # the track range, so a "missing" slot means we have a DB clip at
    # a slot index past Ableton's known range (the track was shortened
    # in Live, or the DB rows reference indices that no longer exist).
    for slot, db_clip in db_by_slot.items():
        if slot in seen:
            continue
        _delete_session_clip_observing_cascade(
            conn, track_row=track_row, slot=slot, db_clip=db_clip,
            out=out, actor=actor, request_id=request_id, reason=reason,
            cause="out of Ableton range",
        )


def _delete_session_clip_observing_cascade(
    conn: sqlite3.Connection,
    *,
    track_row: sqlite3.Row,
    slot: int,
    db_clip: sqlite3.Row,
    out: ApplyResult,
    actor: str,
    request_id: str | None,
    reason: str | None,
    cause: str,
) -> None:
    """Delete a session-view DB clip and make its arrangement-clip cascade
    observable (SYN-3D7M).

    `delete_clip` removes the `clips` row, which cascades to every
    `arrangement_clips` placement that referenced it
    (``ON DELETE CASCADE``). That cross-domain side effect leaves no
    per-row detail of its own, so per the "never silently drop"
    discipline we count the placements *before* the delete and append a
    `details` line when any were removed by the cascade.
    """
    cascaded = Q.count_arrangement_clips_for_clip(conn, db_clip["id"])
    M.delete_clip(
        conn, clip_id=db_clip["id"],
        actor=actor, request_id=request_id, reason=reason,
    )
    out.mutations += 1
    detail = (
        f"track {track_row['name']!r}: session slot {slot} {cause} -> "
        f"deleted DB clip (clip_id={db_clip['id'][:8]} {db_clip['name']!r})"
    )
    if cascaded:
        plural = "placement" if cascaded == 1 else "placements"
        detail += (
            f"; cascade removed {cascaded} arrangement {plural} "
            f"referencing this clip"
        )
    out.details.append(detail)


__all__ = [
    "plan_pull_arrangement_clips",
    "plan_pull_session_clips",
    "_apply_arrangement_clips_for_track",
    "_apply_session_clips_for_track",
]
