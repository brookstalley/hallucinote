"""Arrangement-half planners: arrangement clips, cue points, sections."""
from __future__ import annotations

import sqlite3

from hallucinote.db import queries as Q

from ._core import PushPlan, ToolCall, _position_bar_to_beats


def plan_push_arrangement(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    session_id: str,
) -> PushPlan:
    """Plan the arrangement build for a song.

    Strategy: for each ``arrangement_clips`` row, emit one
    ``ableton_clip(action='duplicate_to_arrangement', track_index,
    clip_index, start_beats)`` call. The agent / push-skill is responsible
    for executing them — they're reorder-safe within the planner output
    (each call addresses an independent (track, slot, position) triple)
    and Live's underlying API handles them serially.

    Pre-conditions (W10-G post-Wave-0): unlinked deps skip-and-warn
    instead of raising. The prior strict-raise contract (W3-C/F) was
    correct in intent but unfriendly in practice — Wave 0's full-band-rock
    canary surfaced this as a Python traceback through the CLI when an
    earlier phase failed partway. W10-G normalizes phase-planner partial-
    state behavior: every planner skips-with-note, matching the existing
    ``plan_push_envelopes`` and ``plan_push_devices`` patterns. The agent
    sees actionable notes per skipped row and continues; nothing in Live
    gets half-built because the row simply isn't emitted as a call.

    Idempotency (W10-A): each row whose ``arrangement_clip`` link is
    already recorded in ``ableton_links`` is silently skipped. Without
    this, re-running a successful push would silently duplicate every
    arrangement placement (the canary triage Group C / C-original). The
    skip count surfaces as a tracking warn so the agent / UI can show
    "nothing to do" instead of going dark.

    Position conversion: each row's 1-based fractional ``start_bar`` is
    converted to cumulative beats from song start via
    :func:`_position_bar_to_beats`. The agent doesn't see bars; the MCP
    surface is meter-agnostic (beats throughout).

    Clear pass: not emitted here. When unlinked rows exist (first push,
    or partial-apply recovery), the agent / push-skill should wipe
    existing arrangement clips on the involved tracks before running
    the plan. The planner can't emit a pre-clear: no MCP
    ``arrangement_clip_delete`` action exists and the planner has no DB
    knowledge of Live's current arrangement state. The idempotent-skip
    above means this only matters for genuinely-new placements; see
    W3-I for the long-term direction.

    Returns N decomposed calls (one per row whose track + clip are both
    linked AND whose arrangement_clip link is NOT yet recorded). Each
    call's result must carry ``arrangement_clip_index`` so
    :func:`apply_push_results` can record the binding under the
    ``arrangement_clip:{db_id}`` key.
    """
    plan = PushPlan()
    arr_rows = Q.get_arrangement_for_song(conn, song_id)
    if not arr_rows:
        plan.warn("no arrangement rows for this song")
        return plan

    ts_points = Q.get_time_signature_map(conn, song_id)
    if not ts_points:
        plan.warn(
            "no time_signature_map; assuming 4/4 for arrangement bar→beats conversion"
        )

    already_linked = 0
    for row in arr_rows:
        # W10-A: re-pushes must be idempotent. apply_push_results writes
        # an `arrangement_clip` link after a successful duplicate; if it
        # exists, the placement is already in Live and re-emitting would
        # silently double the clip on every re-run.
        arr_at = Q.get_ableton_link(
            conn, session_id=session_id, db_kind="arrangement_clip",
            db_id=row["id"],
        )
        if arr_at is not None:
            already_linked += 1
            continue
        track_at = Q.get_ableton_link(
            conn, session_id=session_id, db_kind="track", db_id=row["track_id"]
        )
        if track_at is None:
            plan.warn(
                f"arrangement_clip {row['id']!r}: track {row['track_id']!r} "
                f"not linked in session {session_id!r}. Run plan_push_song_tracks "
                f"+ apply_push_results before this phase to surface the link. "
                f"Skipping this placement."
            )
            continue
        clip_at = Q.get_ableton_link(
            conn, session_id=session_id, db_kind="clip", db_id=row["clip_id"]
        )
        if clip_at is None:
            # CLP-AUD1: an audio clip is never linked (its push is
            # CLP-AUD2 scope), so the generic "run the clip-create
            # phase" advice would send the caller in a loop — name the
            # real blocker instead.
            clip_row = Q.get_clip(conn, row["clip_id"])
            if clip_row is not None and clip_row["kind"] == "audio":
                plan.warn(
                    f"arrangement_clip {row['id']!r}: session clip "
                    f"{row['clip_id']!r} is kind='audio' — audio-clip "
                    "push is CLP-AUD2 scope (the row is authored but not "
                    "synced), so this placement can't reach Live yet. "
                    "Skipping this placement."
                )
                continue
            plan.warn(
                f"arrangement_clip {row['id']!r}: session clip {row['clip_id']!r} "
                f"not linked in session {session_id!r}. Run the clip-create "
                f"phase + apply_push_results to surface the link. "
                f"Skipping this placement."
            )
            continue
        plan.add(ToolCall(
            tool="ableton_clip",
            args={
                "action": "duplicate_to_arrangement",
                "track_index": track_at,
                "clip_index": clip_at,
                "start_beats": _position_bar_to_beats(row["start_bar"], ts_points),
            },
            key=f"arrangement_clip:{row['id']}",
            purpose=(
                f"duplicate session slot {clip_at} on track {track_at} → "
                f"arrangement bar {row['start_bar']:g}"
            ),
        ))

    if already_linked:
        # Surface the idempotent skip so the agent/UI can show
        # "nothing to do" instead of going silent.
        plan.warn(
            f"{already_linked} arrangement placement(s) already linked "
            f"in session {session_id!r} — already in the arrangement, "
            "skipping (idempotent re-push)"
        )
    if plan.calls:
        # Post-W10-A this warn fires for the unlinked-placements path
        # only — first push, or a partial-apply recovery where some
        # placements landed in Live but apply_push_results hadn't yet
        # written their bindings. The agent should ensure those slots
        # are empty in Live before running the duplicates (the planner
        # can't emit a pre-clear: no MCP `arrangement_clip_delete`
        # action exists, and the planner has no DB knowledge of Live's
        # current arrangement state regardless).
        plan.warn(
            "agent must clear existing arrangement clips on the involved tracks "
            "before running these duplicates (planner emits no pre-clear ops "
            "because no MCP arrangement-clip-delete action exists and the "
            "planner has no DB knowledge of Live's current arrangement state)"
        )
    return plan


def plan_push_cue_points(
    conn: sqlite3.Connection,
    *,
    song_id: str,
) -> PushPlan:
    """Emit a single batched ``ableton_arrangement(cue_create_batch)`` call.

    Live's MCP exposes per-cue ``ableton_arrangement(action='cue_create',
    position_beats=…, name=…)`` and a batched ``cue_create_batch`` that
    submits multiple cues in one round-trip. The batch is strictly more
    efficient (one TCP exchange instead of N) and matches the underlying
    Live API's per-cue settle cost, so the planner emits the batch form.

    Position conversion: each row's 1-based fractional ``position_bar`` is
    converted to cumulative beats from song start via
    :func:`_position_bar_to_beats`, walking the song's time_signature_map.
    Cues at bar 1.0 → ``position_beats=0.0``; downstream meter changes
    accumulate correctly.

    Sequencing precondition (W3-I): cue creation must run AFTER
    arrangement-clip placement, because Live's ``set_or_delete_cue`` is
    clamped to ``[0, song.last_event_time]``. The agent / push-skill is
    responsible for phase order; a cue past the arrangement's extent
    will surface as a teaching error from the handler at execution time.

    Plan-time visibility (Wave 0 paper-cut, full-band-rock runbook step
    7e): when any cue's ``position_bar`` exceeds ``max(arrangement_clips
    .end_bar)`` — the DB's planned arrangement extent — emit a warn so
    the agent / user sees the prerequisite issue before round-tripping
    to Live. An empty arrangement gets a distinct, more descriptive warn
    naming the missing prereq instead of a generic extent-exceeded
    message.

    Result key: ``cue_batch:{song_id}``. The batch handler returns a list
    of per-cue results; ``apply_push_results`` consumes it via the
    existing batched-result path.
    """
    plan = PushPlan()
    rows = Q.get_cue_points(conn, song_id)
    if not rows:
        plan.warn("no cue_points for this song; nothing to push")
        return plan
    ts_points = Q.get_time_signature_map(conn, song_id)
    if not ts_points:
        plan.warn(
            "no time_signature_map; assuming 4/4 for cue-point beat conversion"
        )

    # Plan-time arrangement-extent check. The DB-side max end_bar is the
    # PLANNED extent — if arrangement is pushed in the same plan_push_song
    # cycle, Live's last_event_time will match this by the time cues run.
    arrangement_rows = Q.get_arrangement_for_song(conn, song_id)
    if not arrangement_rows:
        plan.warn(
            f"{len(rows)} cue point(s) but the DB has no arrangement_clips — "
            "Live's set_or_delete_cue is clamped to [0, last_event_time], so "
            "every cue past bar 1 will fail. Push arrangement first, OR add "
            "arrangement_clips rows covering each cue's position_bar."
        )
    else:
        max_end_bar = max(float(r["end_bar"]) for r in arrangement_rows)
        late_cues = [r for r in rows if float(r["position_bar"]) > max_end_bar]
        if late_cues:
            preview = ", ".join(
                f"{r['name'] or '(unnamed)'}@bar{float(r['position_bar']):.2f}"
                for r in late_cues[:5]
            )
            ellipsis = " ..." if len(late_cues) > 5 else ""
            plan.warn(
                f"{len(late_cues)} of {len(rows)} cue(s) sit past the DB's "
                f"arrangement extent (max end_bar={max_end_bar:.2f}): "
                f"[{preview}{ellipsis}]. Live's set_or_delete_cue is clamped "
                "to [0, last_event_time]; these cues will fail unless "
                "arrangement is extended to cover them first."
            )

    # W19-E: auto-disambiguate repeated cue names. Live's locator strip
    # lists cues by display name; three cues named "chorus" produce three
    # visually-identical entries. The DB intentionally allows the duplicate
    # (the name describes the section, not its ordinal position), so we
    # rewrite at plan time: when a name appears N>1 times, every occurrence
    # gets a "-K" suffix in declaration order ("chorus-1" / "chorus-2" /
    # "chorus-3"). Singletons stay unsuffixed — no churn on songs that
    # already follow the convention. Empty / null names are exempt (Live
    # surfaces those as "Unnamed" already; suffixing would only make them
    # harder to read).
    raw_names = [r["name"] or "" for r in rows]
    name_counts: dict[str, int] = {}
    for name in raw_names:
        if name:
            name_counts[name] = name_counts.get(name, 0) + 1
    name_running_index: dict[str, int] = {}
    display_names: list[str] = []
    for name in raw_names:
        if name and name_counts[name] > 1:
            name_running_index[name] = name_running_index.get(name, 0) + 1
            display_names.append(f"{name}-{name_running_index[name]}")
        else:
            display_names.append(name)

    cues = [
        {
            "position_beats": _position_bar_to_beats(r["position_bar"], ts_points),
            "name": display_names[i],
        }
        for i, r in enumerate(rows)
    ]
    # R-1.1: idempotent re-push. The batch handler's per-cue ``if_exists``
    # defaults to ``"skip"`` so a re-push of the same DB against a Live set
    # that already has the same-named cues is a no-op. We pass it explicitly
    # so the plan's `args` documents the intent (and to defend against the
    # handler default ever flipping).
    plan.add(ToolCall(
        tool="ableton_arrangement",
        args={"action": "cue_create_batch", "cues": cues, "if_exists": "skip"},
        key=f"cue_batch:{song_id}",
        purpose=f"create {len(cues)} cue point(s) in one batched call",
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
