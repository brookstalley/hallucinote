"""Per-clip note pull: planner + content-diff apply."""
from __future__ import annotations

import sqlite3
from typing import Any

from hallucinote.db import mutations as M, queries as Q

from ._core import (
    PullCall,
    PullPlan,
    ApplyResult,
)


def plan_pull_notes_for_clips(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    session_id: str,
) -> PullPlan:
    """Plan probes to pull notes per linked clip (V1 close-out Chunk D —
    gap #4 partial resolution).

    Emits one ``ableton_note(action='list', track_index=N, location='session',
    clip_index=M)`` per linked session clip. The probe returns the clip's
    notes with Live's stable per-note IDs (via ``clip.get_notes_extended()``);
    the apply layer content-diffs them against DB notes and emits precise
    `update_note` / `insert_notes` / `delete_notes` mutations.

    Identity strategy: Live note IDs are stable WITHIN a session but
    expire on any note-write, so this layer uses them only for
    debug/dedup within one pull pass. The DB-side note UUID is the
    persistent identity. Matching is content-based on
    `(pitch, start_beats, duration_beats)` within `_FLOAT_EPS`:
      - velocity / mute changes preserve the DB note's UUID via
        `update_note`
      - a note whose pitch/start/duration changes surfaces as
        delete + insert (UUID rotates — known V1 limitation)

    Walks every linked clip in the session. Empty clips (no DB notes
    and presumably no Live notes either) still get a probe — the
    cost is one MCP round-trip, and the structural correctness of
    "all linked clips were checked" is worth the cost at V1 scale.
    """
    plan = PullPlan()
    any_emitted = False
    for link in Q.get_ableton_links_for_session(conn, session_id):
        if link["db_kind"] != "clip":
            continue
        clip_id = link["db_id"]
        clip_at = int(link["ableton_index"])
        clip_row = Q.get_clip(conn, clip_id)
        if clip_row is None:
            plan.warn(
                f"clip link {clip_id} has no clips row — stale link, "
                "skipping. Re-push to re-link."
            )
            continue
        if clip_row["kind"] == "audio":
            # CLP-AUD1 defense-in-depth: wave 1 never links audio clips
            # (push refuses them), but CLP-AUD2's placement sync will —
            # and notes live on MIDI clips only, so a note probe against
            # an audio clip is never meaningful.
            plan.warn(
                f"clip {clip_id} ({clip_row['name']!r}) is kind='audio' "
                "— notes live on MIDI clips only; skipping the note "
                "probe."
            )
            continue
        track_at = Q.get_ableton_link(
            conn, session_id=session_id,
            db_kind="track", db_id=clip_row["track_id"],
        )
        if track_at is None:
            plan.warn(
                f"clip {clip_id} is linked but its track "
                f"{clip_row['track_id']} is not — skipping. "
                "Push the track first."
            )
            continue
        any_emitted = True
        plan.add(PullCall(
            tool="ableton_note",
            args={
                "action": "list",
                "track_index": track_at,
                "location": "session",
                "clip_index": clip_at,
            },
            key=f"clip_notes:{clip_id}",
            purpose=(
                f"pull notes for clip {clip_row['name']!r} "
                f"(slot {clip_at} on track {track_at})"
            ),
        ))
    if not any_emitted:
        plan.warn(
            "no clips linked in this session — note pull will be empty"
        )
    return plan


def _apply_notes_for_clip(
    conn: sqlite3.Connection,
    *,
    result: dict[str, Any],
    clip_id: str,
    # song_id is threaded through the dispatcher for parity with sibling
    # apply helpers (which need it for queries like get_time_signature_map);
    # this helper doesn't currently use it. Kept in the signature so the
    # dispatch site doesn't need a special-case branch.
    song_id: str,
    session_id: str,
    out: ApplyResult,
    actor: str,
    request_id: str | None,
    reason: str | None,
) -> None:
    """Diff notes on one clip against the probe payload (V1 close-out
    Chunk D — gap #4 partial resolution).

    Identity is content-based: each note keys by
    ``(pitch, round(start_beats, 3), round(duration_beats, 3))``. This
    preserves the DB note's UUID across velocity / mute edits (the
    common compose-time iteration), at the cost of treating a note's
    pitch / start / duration change as delete + insert (UUID rotates —
    documented V1 limitation; the DB-side composer can edit by UUID
    if preservation is required).

    Diff classes handled:
      - key in both DB and Ableton, fields match -> no-op
      - key in both, velocity or mute drift     -> `update_note`
      - key in DB only                          -> queued for `delete_notes` (batched)
      - key in Ableton only                     -> queued for `insert_notes` (batched)
      - duplicate key on DB side                -> warn + first-row-wins
        (mirrors `_apply_arrangement_clips_for_track`'s duplicate
         handling; rare but valid — chord voicings rarely produce
         exact pitch/start/duration coincidence but it can happen)

    Note IDs from the Ableton side (``note_id`` field) are NOT
    persisted — Live regenerates them on every write, so they're
    useful only for this single pull pass (e.g. for debug logs).
    """
    if Q.get_ableton_link(
        conn, session_id=session_id, db_kind="clip", db_id=clip_id,
    ) is None:
        out.skipped_unlinked += 1
        out.warnings.append(
            f"clip_notes for {clip_id!r}: not linked in session; "
            "skipping (the planner would not have emitted this)"
        )
        return

    clip_row = Q.get_clip(conn, clip_id)
    if clip_row is None:
        out.warnings.append(
            f"clip_notes:{clip_id} — DB clips row missing; skipping"
        )
        return

    if clip_row["kind"] == "audio":
        out.warnings.append(
            f"clip_notes for {clip_id!r}: clip is kind='audio' — notes "
            "live on MIDI clips only; skipping (the planner would not "
            "have emitted this)"
        )
        return

    notes_in = result.get("notes")
    if notes_in is None:
        out.warnings.append(
            f"clip_notes for {clip_id!r}: result missing 'notes' field"
        )
        return

    def _key(pitch: int, start: float, duration: float) -> tuple[int, float, float]:
        # 1/1000-beat precision matches the cue-point + arrangement-clip
        # tolerance elsewhere in this module. Finer than any musically
        # meaningful note placement.
        return (int(pitch), round(float(start), 3), round(float(duration), 3))

    db_by_key: dict[tuple[int, float, float], dict[str, Any]] = {}
    for n in Q.get_notes_for_clip(conn, clip_id):
        k = _key(n["pitch"], n["start_beats"], n["duration_beats"])
        if k in db_by_key:
            kept = db_by_key[k]
            out.warnings.append(
                f"clip {clip_row['name']!r}: duplicate notes at "
                f"pitch={k[0]} start={k[1]:g} duration={k[2]:g} "
                f"(keeping note_id={kept['id'][:8]}; collision with "
                f"note_id={n['id'][:8]} will not round-trip cleanly — "
                f"differentiate the duplicates DB-side or accept the "
                f"velocity/mute reading on the keeper)"
            )
            continue
        db_by_key[k] = n
    seen: set[tuple[int, float, float]] = set()
    to_insert: list[dict[str, Any]] = []

    for entry in notes_in:
        pitch_in = entry.get("pitch")
        sb_in = entry.get("start_time")
        dur_in = entry.get("duration")
        if pitch_in is None or sb_in is None or dur_in is None:
            out.warnings.append(
                f"clip_notes for {clip_id!r}: entry missing pitch / "
                f"start_time / duration: {entry!r}"
            )
            continue
        k = _key(int(pitch_in), float(sb_in), float(dur_in))
        if k in seen:
            # Two Ableton-side notes share the same (pitch, start, duration).
            # Both would match the same DB note (or both would insert as
            # the same key), under-reporting the diff. Warn so the user
            # can fix the upstream duplication; first-Ableton-entry wins
            # the match for this pass.
            out.warnings.append(
                f"clip {clip_row['name']!r}: duplicate Ableton notes at "
                f"pitch={k[0]} start={k[1]:g} duration={k[2]:g} "
                f"(first entry kept for diff; subsequent entry "
                f"note_id={entry.get('note_id')!r} ignored — "
                f"differentiate them by start, duration, or pitch)"
            )
            continue
        seen.add(k)
        db_note = db_by_key.get(k)
        if db_note is None:
            # Ableton has a note the DB doesn't — queue insert.
            to_insert.append({
                "pitch": int(pitch_in),
                "start_beats": float(sb_in),
                "duration_beats": float(dur_in),
                "velocity": int(entry.get("velocity", 100)),
                "mute": 1 if bool(entry.get("mute", False)) else 0,
            })
            continue
        # Match found — check for velocity / mute drift.
        changes: dict[str, Any] = {}
        vel_in = entry.get("velocity")
        if vel_in is not None and int(vel_in) != int(db_note["velocity"]):
            changes["velocity"] = int(vel_in)
        mute_in = entry.get("mute")
        if mute_in is not None:
            mute_db = bool(db_note["mute"])
            if bool(mute_in) != mute_db:
                changes["mute"] = 1 if bool(mute_in) else 0
        if changes:
            M.update_note(
                conn, note_id=db_note["id"],
                actor=actor, request_id=request_id, reason=reason,
                **changes,
            )
            out.mutations += 1
            out.details.append(
                f"clip {clip_row['name']!r}: note "
                f"pitch={k[0]} start={k[1]:g} updated "
                f"(note_id={db_note['id'][:8]}): {changes!r}"
            )
        else:
            out.no_ops += 1

    # DB-only notes (queued for delete) — captured before deletion so we can
    # cross-reference against inserts to detect likely UUID rotation.
    db_only = [db_note for k, db_note in db_by_key.items() if k not in seen]

    # Likely UUID-rotation pairs: a DB note and an Ableton-only note that
    # share pitch + velocity + mute but differ in start/duration. Most often
    # this is the user nudging a note (or changing its length) in Ableton —
    # the diff is correctly modeled as delete + insert (the new note gets
    # a fresh UUID), and we warn so the user can edit DB-side by UUID
    # instead if note identity matters to them.
    #
    # `mute` is part of the bucket key by design: a move-AND-mute-toggle in
    # the same pull won't pair up (and won't warn). Better to miss that
    # rare combined case than to fire when "different pitch + same velocity"
    # is a coincidence — the warning earns its keep only when it points at
    # a genuinely-moved note.
    if db_only and to_insert:
        ins_pool: dict[tuple[int, int, int], list[dict[str, Any]]] = {}
        for ins in to_insert:
            ins_pool.setdefault(
                (ins["pitch"], ins["velocity"], ins["mute"]), []
            ).append(ins)
        pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for db_note in db_only:
            mute_key = 1 if bool(db_note["mute"]) else 0
            bucket = ins_pool.get(
                (int(db_note["pitch"]), int(db_note["velocity"]), mute_key)
            )
            if bucket:
                pairs.append((db_note, bucket.pop(0)))
        if pairs:
            # Name the moved notes so the user can act on the warning —
            # `pitch start_beats -> start_beats (note_id <prefix>)` mirrors
            # the neighboring `update_note` detail-line shape.
            moves = ", ".join(
                f"pitch {db['pitch']} {db['start_beats']:g}"
                f"->{ins['start_beats']:g} (note_id {db['id'][:8]})"
                for db, ins in pairs
            )
            out.warnings.append(
                f"clip {clip_row['name']!r}: {len(pairs)} note(s) "
                f"look moved (same pitch + velocity + mute, different "
                f"start/duration) — the diff applies as delete + insert "
                f"so the UUID rotates; if you want UUID preserved, "
                f"undo in Ableton and edit DB-side by UUID instead. "
                f"Moves: {moves}."
            )

    # Batch insert: one event with all new notes.
    if to_insert:
        new_ids = M.insert_notes(
            conn, clip_id=clip_id, notes=to_insert,
            actor=actor, request_id=request_id, reason=reason,
        )
        out.mutations += 1
        out.details.append(
            f"clip {clip_row['name']!r}: inserted "
            f"{len(new_ids)} note(s) from Ableton-only positions"
        )

    # Batch delete: DB notes whose key Ableton didn't report.
    if db_only:
        M.delete_notes(
            conn, note_ids=[d["id"] for d in db_only],
            actor=actor, request_id=request_id, reason=reason,
        )
        out.mutations += 1
        out.details.append(
            f"clip {clip_row['name']!r}: deleted "
            f"{len(db_only)} DB note(s) absent from Ableton"
        )


__all__ = [
    "plan_pull_notes_for_clips",
    "_apply_notes_for_clip",
]
