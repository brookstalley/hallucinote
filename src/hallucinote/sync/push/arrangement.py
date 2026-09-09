"""Arrangement-half planners: arrangement clips, cue points, sections."""
from __future__ import annotations

import sqlite3
from typing import Any

from hallucinote.db import queries as Q

from ._core import (
    PushPlan,
    ToolCall,
    _notes_for_mcp,
    _position_bar_to_beats,
    uniform_bar_math_divergences,
)
from .envelopes import envelope_hosting_clip_ids


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
    live_arrangement_clips_by_track: dict[int, list[dict[str, Any]]] | None = None,
) -> PushPlan:
    """Plan the arrangement build as a PROJECTION of the DB (ARR-PROJ).

    Per track with placements: CLEAR its existing arrangement clips (from the
    probed Live state, in descending ``arrangement_clip_index`` so Live's
    post-delete renumbering never invalidates a pending delete) then materialize
    each placement directly. The common note-only case uses ``create``
    (``create_midi_clip`` + ``set_notes``) on a FRESH arrangement clip — no
    ``duplicate_to_arrangement``, so Live's B-24 overlap-split (the 13-month
    stacking bug) cannot occur, and no ``replace_notes``-in-place (the §6b-A
    orphan path). Idempotent by construction: same DB → same arrangement, every
    push, regardless of the timeline's prior state.

    Routing (design §5):

      * **note-only placement** → ``create`` a fresh arrangement clip filled
        from the DB notes (no session source needed).
      * **envelope-bearing placement** — its clip HOSTS a clip-bound envelope
        (:func:`envelope_hosting_clip_ids`, the W4-A snapshot-copy case) →
        ``duplicate_to_arrangement`` onto the cleared region so the clip
        envelope survives (``create``+``set_notes`` writes notes only and would
        silently drop it — the §9 routing risk). Lands on an empty region (clear
        ran first) → no B-24. Needs the clip linked in a session slot.
      * **audio placement** → the whole (audio) track is left untouched
        (CLP-AUD2 scope); see §6a below.

    ``live_arrangement_clips_by_track``: ``{track_index: [{arrangement_clip_index,
    start_beats, ...}]}`` from the execute-path probe
    (:func:`push_cli._probe_live_arrangement_clips_via_mcp`). When ``None`` (a
    caller that did not probe) NO clear is emitted and a loud ``alert`` warns the
    timeline must already be empty — the idempotency guarantee holds only with
    the probe. The execute path always probes; this fallback exists solely for
    non-execute callers / tests / the ``plan``/``phases`` debug subcommands.

    §6a all-or-nothing: the clear is DESTRUCTIVE, so a track is materialized
    atomically — every link it needs is validated BEFORE any of its calls (clear
    or create) join the plan. A track that cannot be fully rebuilt emits nothing
    (no clear) and an alert; sibling tracks are unaffected. The planner therefore
    never PLANS a half-materialization (apply-time failures still fail loud via
    the executor halt + the Chunk-3 integrity assert).

    Skip severity (PSH-ARRPROBE). A track skipped because its state could not be
    DETERMINED — lane absent from the probe, track not linked, envelope-bearing
    source clip not linked, placement referencing a missing clip — is recorded
    via :meth:`PushPlan.blocked`, so the executor reports the phase INCOMPLETE
    with a non-zero exit instead of the "skipped (idempotent)" clean OK that hid
    an empty timeline. A DELIBERATE no-op (audio track, CLP-AUD2) stays a
    :meth:`PushPlan.warn` — nothing was asked for and nothing is owed.

    Each ``create`` / ``duplicate`` call is keyed ``arrangement_clip:{db_id}`` so
    :func:`apply_push_results` records the binding from ``arrangement_clip_index``;
    each ``delete`` is keyed ``arrangement_clip_clear:{track}:{idx}`` (ack-only —
    a delete records no binding).
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

    # The two-ruler check belongs HERE, not in the meter phase: this is where
    # authored bar positions actually become Live beats, and it is the phase
    # `push execute --only arrangement` runs. It reports placements, not the
    # mere presence of a meter change — a song whose every clip sits before
    # the first change diverges nowhere and gets no alert.
    diverging = uniform_bar_math_divergences(
        [float(r["start_bar"]) for r in arr_rows], ts_points,
    )
    if diverging:
        first_bar, mapped, uniform = diverging[0]
        plan.alert(
            f"{len(diverging)} of {len(arr_rows)} arrangement placements sit "
            f"after a meter change, where this codebase's two bar rulers "
            f"disagree: push resolves bar positions through the "
            f"time_signature_map, while hallucinote.arrangement accumulates "
            f"whole bars against one uniform beats_per_bar and never reads "
            f"the map. Bar {first_bar:g} goes to beat {mapped:g} here; "
            f"uniform math would put it at {uniform:g}. If build.py computed "
            f"these positions with a single beats_per_bar, they will land "
            f"somewhere other than where it intended."
        )

    if live_arrangement_clips_by_track is None:
        plan.alert(
            "arrangement planned WITHOUT a Live arrangement probe: no clear was "
            "emitted, so create+fill will STACK onto any existing arrangement "
            "clips on the involved tracks. Run through the execute path (which "
            "probes automatically) or ensure the timeline is already empty."
        )

    host_clip_ids = envelope_hosting_clip_ids(conn, song_id)

    # Group placements by track (rows already ordered by track_id, start_bar, id).
    rows_by_track: dict[str, list[sqlite3.Row]] = {}
    for row in arr_rows:
        rows_by_track.setdefault(row["track_id"], []).append(row)

    created = duplicated = cleared = skipped_tracks = 0

    for track_id, rows in rows_by_track.items():
        track_at = Q.get_ableton_link(
            conn, session_id=session_id, db_kind="track", db_id=track_id,
        )
        if track_at is None:
            plan.blocked(
                f"arrangement: track {track_id!r} not linked in session "
                f"{session_id!r}; skipping all {len(rows)} placement(s) on it. "
                "Run the tracks phase + apply_push_results first."
            )
            skipped_tracks += 1
            continue

        # When a probe was provided but this track's lane is ABSENT from it, the
        # per-track probe FAILED (vs. a present-but-empty lane = genuinely no
        # clips — see _probe_live_arrangement_clips_via_mcp's per-track tolerance).
        # The lane's state is unknown, so create+fill could STACK onto unprobed
        # clips — the exact failure the projection prevents. Skip + alert rather
        # than guess the timeline is clear.
        #
        # ARR-ORPHAN2: skipping is correct, but it used to be SILENT — an alert
        # is drained into the executor's benign "push still OK" channel, so the
        # run exited 0 over a track that kept its stale clips and got none of its
        # placements. The loudness now comes from the post-phase integrity assert:
        # verify_song_arrangement re-probes the same lane and, when that probe
        # fails again, records `lane_probe_failed` — which IS corruption, so the
        # phase HALTS instead of reporting ok. (If the re-probe succeeds, the
        # unbuilt placements read `missing_clip` and the surviving orphan lands in
        # extra_live_clips — both already halting.) Either way the "could not
        # clear this lane, proceeded anyway, reported OK" path is closed.
        if (
            live_arrangement_clips_by_track is not None
            and track_at not in live_arrangement_clips_by_track
        ):
            plan.blocked(
                f"arrangement: no Live arrangement probe for track {track_id!r} "
                f"(Live index {track_at}) — the per-track probe failed, so the "
                "lane state is unknown; skipping to avoid create+fill stacking "
                "onto unprobed clips. Re-run once Live is reachable for it."
            )
            skipped_tracks += 1
            continue

        # --- Validate + build the placement calls; commit only if the WHOLE
        #     track is materializable (§6a — never clear what we can't rebuild).
        placement_calls: list[ToolCall] = []
        skip_reason: str | None = None
        skip_is_known_scope = False  # audio (CLP-AUD2) → warn; real gap → alert
        for row in rows:
            clip_row = Q.get_clip(conn, row["clip_id"])
            if clip_row is None:
                skip_reason = (
                    f"placement {row['id']!r} references missing clip "
                    f"{row['clip_id']!r}"
                )
                break
            if clip_row["kind"] == "audio":
                # A Live track is MIDI or audio, so any audio placement means an
                # audio track: skip the WHOLE track's projection. Clearing it
                # would wipe manually-placed audio clips we cannot rebuild
                # (audio-clip arrangement push is CLP-AUD2 scope).
                skip_reason = (
                    f"placement {row['id']!r} is kind='audio' (CLP-AUD2 scope) — "
                    "audio-track arrangement is not materialized by push; left "
                    "untouched so manual audio clips are preserved"
                )
                skip_is_known_scope = True
                break

            start_beats = _position_bar_to_beats(row["start_bar"], ts_points)
            if row["clip_id"] in host_clip_ids:
                # Envelope-bearing → duplicate-onto-cleared (needs clip linked).
                clip_at = Q.get_ableton_link(
                    conn, session_id=session_id, db_kind="clip",
                    db_id=row["clip_id"],
                )
                if clip_at is None:
                    skip_reason = (
                        f"envelope-bearing placement {row['id']!r}: source clip "
                        f"{row['clip_id']!r} not linked (needed for the duplicate "
                        "route — run the clips phase + apply first)"
                    )
                    break
                placement_calls.append(ToolCall(
                    tool="ableton_clip",
                    args={
                        "action": "duplicate_to_arrangement",
                        "track_index": track_at,
                        "clip_index": clip_at,
                        "start_beats": start_beats,
                    },
                    key=f"arrangement_clip:{row['id']}",
                    purpose=(
                        f"duplicate envelope-bearing clip {row['clip_id']!r} → "
                        f"arrangement bar {row['start_bar']:g} (carries clip "
                        "envelope; cleared region first — no B-24)"
                    ),
                ))
                duplicated += 1
            else:
                # Note-only → create+fill a FRESH arrangement clip from DB notes.
                notes = Q.get_notes_for_clip(conn, row["clip_id"])
                placement_calls.append(ToolCall(
                    tool="ableton_clip",
                    args={
                        "action": "create",
                        "location": "arrangement",
                        "kind": "midi",
                        "track_index": track_at,
                        "start_beats": start_beats,
                        "length": float(clip_row["length_beats"]),
                        "name": clip_row["name"],
                        "notes": _notes_for_mcp(notes),
                    },
                    key=f"arrangement_clip:{row['id']}",
                    purpose=(
                        f"create+fill arrangement clip {row['id']!r} on track "
                        f"{track_at} @ bar {row['start_bar']:g} "
                        f"({len(notes)} notes from DB)"
                    ),
                ))
                created += 1

        if skip_reason is not None:
            msg = (
                f"arrangement: skipping track {track_id!r} entirely (no clear, no "
                f"rebuild) — {skip_reason}. The clear is destructive, so a track "
                "is materialized only when it can be fully rebuilt (§6a)."
            )
            # Known scope (audio / CLP-AUD2) is a DELIBERATE no-op → a
            # diagnostic note. A real gap (missing clip row, unlinked
            # envelope-bearing source) is work the song asked for that this push
            # could not determine how to do → `blocked`, so the run reports
            # INCOMPLETE instead of a clean OK over a silently-unbuilt track.
            (plan.warn if skip_is_known_scope else plan.blocked)(msg)
            skipped_tracks += 1
            continue

        # CLEAR (descending index) — committed only now that the track is fully
        # rebuildable. Emitted BEFORE the placement calls so deletes dispatch
        # first (dispatch preserves add-order).
        #
        # ARR-ORPHAN2: the clear is UNCONDITIONAL over the probed lane — every
        # clip the probe listed is deleted, whether or not it corresponds to a DB
        # placement or carries an ableton_link. There is no "delete only what I
        # can map back" filter, which is why a probed orphan (an unlinked clip, a
        # hand edit, a full-song-length leftover at beat 0) is always removed and
        # can never block the creates that follow. The projection's blind spot is
        # not the clear's selectivity — it is a lane the probe never reported;
        # see the ARR-ORPHAN2 note on the absent-lane skip above.
        track_calls: list[ToolCall] = []
        if live_arrangement_clips_by_track is not None:
            live_clips = live_arrangement_clips_by_track.get(track_at, [])
            for c in sorted(
                live_clips,
                key=lambda c: c["arrangement_clip_index"],
                reverse=True,
            ):
                idx = c["arrangement_clip_index"]
                track_calls.append(ToolCall(
                    tool="ableton_clip",
                    args={
                        "action": "delete",
                        "location": "arrangement",
                        "track_index": track_at,
                        "clip_index": idx,
                    },
                    key=f"arrangement_clip_clear:{track_at}:{idx}",
                    purpose=(
                        f"clear existing arrangement clip {idx} on track "
                        f"{track_at} (projection rebuild)"
                    ),
                ))
                cleared += 1
        track_calls.extend(placement_calls)
        for call in track_calls:
            plan.add(call)

    if cleared or created or duplicated:
        plan.warn(
            f"arrangement projection: cleared {cleared}, created+filled "
            f"{created}, duplicated {duplicated} (envelope-bearing) across "
            f"{len(rows_by_track) - skipped_tracks} track(s)"
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

    # A cue's position resolves through the meter map below, so it diverges from
    # uniform bar math for exactly the same reason an arrangement placement does
    # (see plan_push_arrangement). Cues + placements are the whole surface:
    # clip lengths come from length_beats, and plan_push_sections emits no calls.
    diverging = uniform_bar_math_divergences(
        [float(r["position_bar"]) for r in rows], ts_points,
    )
    if diverging:
        first_bar, mapped, uniform = diverging[0]
        plan.alert(
            f"{len(diverging)} of {len(rows)} cue points sit after a meter "
            f"change, where push's meter-map bar→beat translation and "
            f"hallucinote.arrangement's uniform beats_per_bar disagree. Bar "
            f"{first_bar:g} goes to beat {mapped:g} here; uniform math would "
            f"put it at {uniform:g}."
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
