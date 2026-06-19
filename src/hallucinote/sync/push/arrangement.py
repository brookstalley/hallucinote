"""Arrangement-half planners: arrangement clips, cue points, sections."""
from __future__ import annotations

import sqlite3

from hallucinote.db import queries as Q

from ._core import PushPlan, ToolCall, _notes_for_mcp, _position_bar_to_beats


def _arrangement_note_refresh_call(
    conn: sqlite3.Connection,
    *,
    row: sqlite3.Row,
    session_id: str,
) -> ToolCall | None:
    """Build a ``replace_notes(location='arrangement')`` call that re-syncs one
    already-materialized arrangement clip's notes from its source session clip.

    PSH-6W2J: an arrangement clip is a distinct Live copy made once by
    ``duplicate_to_arrangement``; a later note edit to the session clip never
    reaches the copy. Refreshing the copy's notes in place (the MCP
    ``replace_notes`` handler accepts ``location='arrangement'`` with
    ``clip_index = arrangement_clip_index``) keeps the two in sync WITHOUT
    re-duplicating the placement.

    Returns ``None`` when the refresh can't apply: the placement's track or
    arrangement_clip link isn't recorded yet (it'll be created by the duplicate
    path, not refreshed), or the source clip is audio (no notes; CLP-AUD2 scope).

    ``row`` must carry ``clip_kind`` (both feeding queries —
    :func:`Q.get_arrangement_for_song` and :func:`Q.get_arrangement_for_clip` —
    join it), so the audio check costs no extra query.
    """
    if row["clip_kind"] == "audio":
        return None
    track_at = Q.get_ableton_link(
        conn, session_id=session_id, db_kind="track", db_id=row["track_id"]
    )
    arr_at = Q.get_ableton_link(
        conn, session_id=session_id, db_kind="arrangement_clip", db_id=row["id"]
    )
    if track_at is None or arr_at is None:
        return None
    notes = Q.get_notes_for_clip(conn, row["clip_id"])
    return ToolCall(
        tool="ableton_clip",
        args={
            "action": "replace_notes",
            "location": "arrangement",
            "track_index": track_at,
            "clip_index": arr_at,
            "notes": _notes_for_mcp(notes),
        },
        # Distinct key kind from `arrangement_clip:` (the duplicate/link op):
        # this refreshes content on an already-linked placement and records no
        # binding — declared ack-only in apply_push_results._ACK_ONLY_KINDS.
        key=f"arrangement_clip_notes:{row['id']}",
        purpose=(
            f"refresh notes in already-placed arrangement clip {row['id']!r} "
            f"({len(notes)} notes) from session clip {row['clip_id']!r}"
        ),
    )


def plan_push_arrangement_clip_notes(
    conn: sqlite3.Connection,
    *,
    clip_id: str,
    session_id: str,
) -> PushPlan:
    """Plan note refreshes for every arrangement copy of one session clip.

    PSH-6W2J: the scoped note-push path (:func:`push_notes`) replaces notes on a
    session clip but not on its arrangement copies. This planner emits one
    ``replace_notes(location='arrangement')`` per *linked* placement of the clip
    so the compose loop's scoped push propagates to the arrangement too. Unlinked
    placements (not yet materialized) and audio sources are skipped — see
    :func:`_arrangement_note_refresh_call`.
    """
    plan = PushPlan()
    for row in Q.get_arrangement_for_clip(conn, clip_id):
        call = _arrangement_note_refresh_call(conn, row=row, session_id=session_id)
        if call is not None:
            plan.add(call)
    return plan


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
    refreshed = 0
    new_placements = 0
    for row in arr_rows:
        # W10-A / PSH-6W2J: re-pushes must NOT re-duplicate an already-placed
        # clip (that silently doubled the placement on every re-run). But the
        # original "skip entirely" was too aggressive — it also suppressed note
        # propagation, so a later note edit never reached the arrangement copy
        # (silent stale render/playback). Now an already-linked placement emits
        # a `replace_notes(location='arrangement')` REFRESH instead: idempotent
        # on placement (no doubling), notes kept in sync.
        arr_at = Q.get_ableton_link(
            conn, session_id=session_id, db_kind="arrangement_clip",
            db_id=row["id"],
        )
        if arr_at is not None:
            already_linked += 1
            refresh_call = _arrangement_note_refresh_call(
                conn, row=row, session_id=session_id
            )
            if refresh_call is not None:
                plan.add(refresh_call)
                refreshed += 1
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
        new_placements += 1

    if already_linked:
        # Surface the idempotent re-push so the agent/UI sees what happened.
        # PSH-6W2J: already-linked placements aren't silently skipped anymore —
        # their notes are refreshed from the session clip (no re-duplication).
        note = (
            f"{already_linked} arrangement placement(s) already linked "
            f"in session {session_id!r} — refreshed notes from their session "
            "clips, no re-duplication (idempotent re-push)"
        )
        if refreshed != already_linked:
            # Some linked placements couldn't be refreshed (unresolved track
            # link, or audio source — no notes to push). Name the gap so a
            # stale arrangement copy can't hide behind the "refreshed" claim.
            note += (
                f"; {already_linked - refreshed} of them not refreshed "
                "(track link unresolved or audio source)"
            )
        plan.warn(note)
    if new_placements:
        # Fires for genuine NEW duplicates only (first push, or partial-apply
        # recovery) — NOT for note refreshes of already-placed clips, which add
        # nothing to clear. The agent should ensure those slots are empty in
        # Live before running the duplicates (the planner emits no pre-clear:
        # no MCP `arrangement_clip_delete` action exists, and the planner has no
        # DB knowledge of Live's current arrangement state regardless).
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
    responsible for phase order.

    Extent partition (SYN-6B4Q): a cue's fate is decided against the DB's
    composed song length (``max(arrangement_clips.end_bar)``):

      * past the composed length (and an arrangement IS authored) → a hard
        authoring error via :meth:`PushPlan.error` (no calls emitted); the
        executor halts the phase with that DB-grounded message rather than
        the opaque runtime ``past last_event_time``.
      * no arrangement authored yet (skeleton push) → all cues are deferred:
        a warn explains they'll land once the arrangement is composed.
      * otherwise → emitted with ``on_out_of_range='skip'`` so a cue ahead of
        Live's CURRENT extent (skeleton, or arrangement-not-yet-built) defers
        at the handler instead of failing the batch.

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

    # SYN-6B4Q: partition cues against the DB's composed song length.
    #
    # The composed extent is max(arrangement_clips.end_bar) — the length the
    # song is authored to. Two distinct questions decide a cue's fate:
    #
    #   * "Will this cue EVER be placeable?" — a DB question, answered here. A
    #     cue past the composed extent references content that can't exist;
    #     that's a hard authoring error (plan.error → the executor halts the
    #     phase with THIS clear message, not the opaque runtime
    #     `past last_event_time=…`). Only meaningful once an arrangement is
    #     authored: with none, the song simply isn't composed yet.
    #   * "Is this cue placeable RIGHT NOW in Live?" — a runtime question only
    #     Live's last_event_time answers. A cue within the composed song can
    #     still be ahead of Live's CURRENT extent (a skeleton push, or an
    #     arrangement that hasn't built yet). We emit those with
    #     on_out_of_range='skip' so Live's handler DEFERS them (reports them
    #     back) instead of failing the whole batch; they land on the next push.
    arrangement_rows = Q.get_arrangement_for_song(conn, song_id)
    composed_max_end_bar = (
        max(float(r["end_bar"]) for r in arrangement_rows)
        if arrangement_rows else None
    )
    if composed_max_end_bar is not None:
        overrun = [
            r for r in rows
            if float(r["position_bar"]) > composed_max_end_bar + 1e-9
        ]
        if overrun:
            preview = ", ".join(
                f"{r['name'] or '(unnamed)'}@bar{float(r['position_bar']):.2f}"
                for r in overrun[:5]
            )
            ellipsis = " ..." if len(overrun) > 5 else ""
            plan.error(
                f"{len(overrun)} of {len(rows)} cue(s) sit past the composed "
                f"song length (arrangement extent max end_bar="
                f"{composed_max_end_bar:.2f}): [{preview}{ellipsis}]. A cue "
                "past the end of the composed arrangement can never be placed "
                "(Live clamps set_or_delete_cue to [0, last_event_time]) — "
                "extend the arrangement to cover these positions, or "
                "move/remove the cue(s), then re-push. No cues written."
            )
            return plan
    else:
        plan.warn(
            f"{len(rows)} cue point(s) but the DB has no arrangement_clips "
            "yet — cues are deferred until the arrangement is composed (Live "
            "clamps set_or_delete_cue to [0, last_event_time]). They land on "
            "the next push once arrangement content covers them."
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
        args={
            "action": "cue_create_batch", "cues": cues,
            "if_exists": "skip",
            # SYN-6B4Q: cues ahead of Live's current extent defer (the handler
            # reports them in skipped_out_of_range) rather than failing the
            # batch. The planner has already refused cues past the composed
            # song length above, so anything deferred here WILL become
            # placeable on a later push.
            "on_out_of_range": "skip",
        },
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
