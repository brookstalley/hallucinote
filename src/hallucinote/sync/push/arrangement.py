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
from .clips import AUDIO_CONFORM_PROPERTIES, resolve_authored_sample, resolve_reversed_sample
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
    path, not refreshed), or the source clip is audio — an audio clip hosts no
    note array at all, so there is nothing for a note refresh to carry.

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


# What Live lets a push write on an ALREADY-PLACED arrangement clip to bound
# what it PLAYS. `end_marker` bounds a clip that runs once; a LOOPING clip
# repeats its loop brace instead, so `loop_end` has to move with it or the copy
# keeps sounding past the authored region. Both are settable on a placed clip,
# on the direct-create route and the duplicate route alike.
#
# The span a clip OCCUPIES on the timeline is `Clip.end_time`, and Live exposes
# it with NO SETTER — it is fixed when the clip is placed and no write moves it.
# That is why this list bounds playback and never the block.
_REGION_PROPERTIES: tuple[str, ...] = ("end_marker", "loop_end")


def _region_is_writable(clip_row: sqlite3.Row) -> bool:
    """Whether the authored region can be written to this clip's copy in the
    BEATS domain the arrangement is authored in.

    Live's markers carry a dual unit — beats when the clip is warped, seconds
    when it is not (`clips.warping`, and the wire says the same). A row that
    authors `warping = 0` is saying the copy reads its markers in seconds, so a
    beats-domain region would trim it to the wrong place; the write is skipped
    and said rather than made wrong. An unauthored `warping` leaves Live's own
    default in force and the beats domain is the one to write.
    """
    return clip_row["warping"] != 0


def _block_note(
    where: str, *, end_bar: float, region_travels: bool, route: str,
) -> str:
    """One placement's line in the phase's block-extent alert.

    Terse by design: it NAMES the placement and what its block is, and leaves
    the two-part explanation — the region travels, the block cannot — to the
    single phase-level alert that carries these. Saying it per placement would
    repeat a permanent Live limit once per stem.
    """
    region = (
        "region set to the authored span" if region_travels
        else "region NOT set (unwarped clip — markers are in seconds)"
    )
    return (
        f"{where}: {region}; block stays {route} "
        f"(placement end_bar {end_bar:g})"
    )


def _audio_placement_call(
    conn: sqlite3.Connection,
    *,
    row: sqlite3.Row,
    clip_row: sqlite3.Row,
    track_at: int,
    start_beats: float,
) -> tuple[ToolCall | None, str | None, tuple[str, str | None] | None]:
    """Materialize one ENVELOPE-FREE ``kind='audio'`` placement by direct
    create, or say why it can't be (R1.1).

    Returns ``(call, refusal, (block_note, conform_gap))``. A ``refusal`` is a reason the
    whole track must be skipped (§6a: the clear is destructive, so a track is
    materialized only when every placement on it can be rebuilt). A
    ``conform_gap`` is a placement that WAS planned but whose authored conform
    could not travel with it — recorded when the track commits.

    The route is ``Track.create_audio_clip(path, start_beats)`` — the call the
    LOM probe confirmed for arrangement placement, reached through
    ``ableton_clip(action='create', location='arrangement', kind='audio')``.
    It needs no session counterpart, which is why an envelope-free audio
    placement does not require its source clip to be linked. A placement
    whose source clip HOSTS an envelope never reaches this function: the
    projection loop routes it through ``duplicate_to_arrangement`` like an
    envelope-bearing MIDI one, because the duplicate carries a ride off an
    audio session clip exactly as off a MIDI one (probe-confirmed against an
    envelope-free control) and the direct create here carries no envelope at
    all.

    One thing it refuses rather than guesses: **a sample that is not on
    disk.** Checked before the call is planned; a clip that pushes and then
    plays silence is a phase reporting OK without having determined its state.

    And one thing it plans while saying what did NOT land: the direct create
    loads a FRESH clip at Live's defaults, so the row's authored gain /
    transpose / warp / markers stay on the session clip and do not reach the
    arrangement copy. Nothing in the same plan can conform it — a
    `set_property` addresses an arrangement clip by index, and that index
    exists only in the create's RESULT, after apply; predicting it is exactly
    the positional guess ARR-PROJ diagnosed as a root cause. The copy's
    PLAYABLE REGION does reach it, in the pass that runs after apply against
    the recorded link (:func:`plan_push_arrangement_audio_regions`); the rest
    of the conform is still reported as a gap, never guessed at.
    """
    row_id = row["id"]
    where = (
        f"placement {row_id!r} (clip {clip_row['name']!r} @ bar "
        f"{row['start_bar']:g})"
    )

    resolved, refusal = resolve_authored_sample(conn, clip_row, where=where)
    if resolved is None:
        return None, (
            f"{refusal} Placing it would put a clip in the arrangement that "
            "plays silence"
        ), None
    if clip_row["reverse"]:
        # The same derived file the session clip plays: an arrangement copy
        # that ran the line forward while the session clip ran it backwards
        # would be two truths about one row.
        resolved, refusal = resolve_reversed_sample(conn, resolved, where=where)
        if resolved is None:
            return None, (
                f"{refusal} Placing it would put a clip in the arrangement "
                "playing the line forward"
            ), None

    call = ToolCall(
        tool="ableton_clip",
        args={
            "action": "create",
            "location": "arrangement",
            "kind": "audio",
            "track_index": track_at,
            "start_beats": start_beats,
            # ABSOLUTE by contract — Live resolves nothing.
            "audio_path": str(resolved),
            "name": clip_row["name"],
        },
        key=f"arrangement_clip:{row_id}",
        purpose=(
            f"create arrangement audio clip {row_id!r} on track {track_at} @ "
            f"bar {row['start_bar']:g} from {resolved.name}"
        ),
    )

    authored = [
        prop for column, prop in AUDIO_CONFORM_PROPERTIES
        if clip_row[column] is not None
    ]
    # TWO facts, two severities, because they are two different facts.
    #
    # BLOCK EXTENT is universal and PERMANENT: Track.create_audio_clip takes a
    # path and a position and no length, so the copy's block is the file's
    # length — and Live exposes `Clip.end_time` with no setter, so nothing this
    # push can write moves it afterwards either. That is true of every audio
    # placement ever planned, so it is an ALERT — operator-visible and
    # non-fatal; routing it as blocked would make every song with a stem exit
    # non-zero forever, which is the invariant `test_audio_track_is_not_blocked`
    # protects. It is said for EVERY audio placement, not only rows with an
    # authored conform column. The per-placement line only NAMES the placement;
    # the two-part explanation (region travels, block does not) is said once for
    # the phase in `plan_push_arrangement`'s summary alert.
    #
    # AUTHORED CONFORM is per-song: the song asked for a gain or a warp mode and
    # did not get it on this copy. That is a run that must not read clean.
    block_note = _block_note(
        where,
        end_bar=float(row["end_bar"]),
        region_travels=_region_is_writable(clip_row),
        route="the file's length",
    )
    conform_gap = None
    if authored:
        conform_gap = (
            f"{where} was placed, but its authored conform ({', '.join(authored)}) "
            "did NOT travel with it. Live's Track.create_audio_clip loads a "
            "FRESH clip at Live's defaults, and the region pass that follows the "
            "create writes only the copy's PLAYABLE REGION — not its gain, "
            "transpose, warp or markers. The session clip IS conformed; the "
            "arrangement copy plays at Live's defaults until the conform reaches "
            "it. Conform the copy in Live by hand for now; a placement whose clip "
            "hosts an envelope does not have this gap, because it travels by "
            "duplicate of the conformed session clip"
        )
    return call, None, (block_note, conform_gap)


def _divergence_bars(diverging: list[tuple[float, float, float]]) -> str:
    """Name the diverging bars, not just the first.

    An operator told only a count and one bar number knows a repair is needed
    but not where, and this alert is the only channel carrying it — there is no
    logger on this path. Long runs are capped so one badly-authored song cannot
    push the rest of the report out of view; the cap is stated in the text so
    the reader knows the list was cut rather than complete.
    """
    # Deduped and sorted, because the input is per-PLACEMENT and a bar carries
    # as many placements as it has tracks. A section boundary at bar 10 on eight
    # tracks would otherwise fill the whole cap with `10, 10, 10, ...` and hide
    # every other diverging bar behind repeats of one — worse on the ordinary
    # song than on the pathological one. The opening clause still reports the
    # per-placement count, so nothing is lost by collapsing them here.
    bars = sorted({b for b, _, _ in diverging})
    shown = [f"{b:g}" for b in bars[:8]]
    if len(bars) <= 8:
        return ", ".join(shown)
    return ", ".join(shown) + f", and {len(bars) - 8} more"


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
      * **envelope-bearing placement, MIDI or AUDIO** — its clip HOSTS a
        clip-bound envelope (:func:`envelope_hosting_clip_ids`, the W4-A
        snapshot-copy case) → ``duplicate_to_arrangement`` onto the cleared
        region so the clip envelope survives (a fresh create — notes for MIDI,
        a file for audio — carries no envelope and would silently drop it,
        the §9 routing risk). ``duplicate_clip_to_arrangement`` carries a ride
        off an audio session clip exactly as off a MIDI one (probe-confirmed,
        with an envelope-free control duplicate so the automation_state flip
        could be trusted). Lands on an empty region (clear ran first) → no
        B-24. Needs the clip linked in a session slot. For audio this route
        also carries the session clip's CONFORM, since the duplicate copies
        the conformed clip — so the conform gap below does not apply to it.
      * **envelope-free audio placement** → ``create`` a fresh arrangement
        audio clip directly from the row's resolved sample path
        (``Track.create_audio_clip(path, beats)``), which needs no session
        counterpart. Refused — and, per §6a, taking the whole track with it —
        when the sample is not on disk. See :func:`_audio_placement_call`.
        Only the envelope-hosting rows duplicate: the duplicate carries the
        session clip's length rather than the placement's, and the positional
        renumbering ARR-PROJ fixed was born in that path, so widening it to
        every audio placement is a decision the extent gap has to earn on its
        own, not one this routing takes by default.

    An audio track the DB has NO placements for never enters the loop, so its
    hand-placed clips are untouched by construction; the summary names those
    tracks so "untouched" and "forgotten" don't read the same in the report.

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
    an empty timeline. An audio placement this planner cannot materialize
    without guessing is in that class, not a deliberate no-op: the song asked
    for the clip and did not get it.

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
            f"the map. Affected bars: {_divergence_bars(diverging)}. "
            f"Bar {first_bar:g} goes to beat {mapped:g} here; "
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

    created = duplicated = cleared = skipped_tracks = placed_audio = 0
    # Per-placement block-extent lines, collected across tracks and said ONCE
    # per phase below — on the operator channel, because `notes` is the channel
    # the executor discards and a fact the operator may have to act on
    # (shorten the block in Live) must reach them; one alert per placement
    # would bury the rest of the report under a stem-heavy song. Each carries
    # whether that placement's REGION travels, so the phase-level sentence can
    # say what actually happened rather than what usually does.
    extent_notes: list[tuple[str, bool]] = []

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
        pending_gaps: list[str] = []
        pending_extent_notes: list[tuple[str, bool]] = []
        skip_reason: str | None = None
        for row in rows:
            clip_row = Q.get_clip(conn, row["clip_id"])
            if clip_row is None:
                skip_reason = (
                    f"placement {row['id']!r} references missing clip "
                    f"{row['clip_id']!r}"
                )
                break

            start_beats = _position_bar_to_beats(row["start_bar"], ts_points)
            is_audio = clip_row["kind"] == "audio"
            hosts_envelope = row["clip_id"] in host_clip_ids
            if is_audio and not hosts_envelope:
                # A Live track is MIDI or audio, so any audio placement means
                # an audio track — and an audio track the DB HAS placements for
                # is projectable like any other. (A track the DB has NO
                # placements for never enters `rows_by_track` at all, so
                # hand-placed audio on it is untouched by construction; the
                # summary below names those tracks.) An envelope-hosting audio
                # placement falls through to the duplicate route below, with
                # the MIDI ones, so its ride travels with it.
                audio_call, refusal, gaps = _audio_placement_call(
                    conn, row=row, clip_row=clip_row, track_at=track_at,
                    start_beats=start_beats,
                )
                if refusal is not None or audio_call is None:
                    skip_reason = refusal or (
                        f"placement {row['id']!r} is kind='audio' and could not "
                        "be materialized"
                    )
                    break
                placement_calls.append(audio_call)
                # A planned placement always carries the extent note; the
                # authored-conform half is present only when the row authored
                # one. The guard keeps the pair's optionality honest rather than
                # assuming the shape a successful return happens to have.
                if gaps is not None:
                    block_note, authored_gap = gaps
                    pending_extent_notes.append(
                        (block_note, _region_is_writable(clip_row))
                    )
                    if authored_gap is not None:
                        pending_gaps.append(authored_gap)
                placed_audio += 1
                continue

            if hosts_envelope:
                # Envelope-bearing, MIDI or audio → duplicate-onto-cleared
                # (needs clip linked). The kind does not change the route: the
                # duplicate carries the ride either way.
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
                        f"duplicate envelope-bearing {clip_row['kind']} clip "
                        f"{row['clip_id']!r} → arrangement bar "
                        f"{row['start_bar']:g} (carries clip envelope"
                        + ("; audio: carries the session clip's conform too"
                           if is_audio else "")
                        + "; cleared region first — no B-24)"
                    ),
                ))
                duplicated += 1
                if is_audio:
                    placed_audio += 1
                    # The block is the session clip's length on this route, and
                    # is just as unmovable as on the direct create — but the
                    # copy's playable region is written by the same post-apply
                    # pass, so this line reads like the direct create's.
                    dup_region_travels = _region_is_writable(clip_row)
                    pending_extent_notes.append((_block_note(
                        f"placement {row['id']!r} (clip {clip_row['name']!r} "
                        f"@ bar {row['start_bar']:g}, duplicate route)",
                        end_bar=float(row["end_bar"]),
                        region_travels=dup_region_travels,
                        route="the session clip's length",
                    ), dup_region_travels))
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
            # Every reason a track is skipped is a real gap — a missing clip
            # row, an unlinked envelope-bearing source, an audio placement
            # whose sample is not on disk. That is
            # work the song asked for and this push could not determine how to
            # do, so it is `blocked`: the run reports INCOMPLETE rather than a
            # clean OK over a silently-unbuilt track. (A DELIBERATE no-op would
            # be a `warn` instead; there is no longer one here — an audio track
            # stopped being a known-scope skip when audio started materializing.)
            plan.blocked(msg)
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
        # Drained only now: a gap on a track that ended up skipped would name
        # work nobody attempted. These are placements that DID land minus part
        # of what the song authored for them, so the run must not read clean.
        for gap in pending_gaps:
            plan.blocked(f"arrangement: {gap}.")
        extent_notes.extend(pending_extent_notes)

    if extent_notes:
        shown = [line for line, _ in extent_notes[:8]]
        more = len(extent_notes) - len(shown)
        # The whole two-part truth, said ONCE for the phase. Half of it is now
        # work this push does (the region), half of it is a Live limit nobody
        # can lift (the block) — and an operator who is told only the second
        # half goes hand-trimming clips that already play the right thing.
        # The first half is claimed only for the placements it is true of; the
        # per-placement lines say which those are.
        any_region = any(travels for _, travels in extent_notes)
        region_clause = (
            "Their PLAYABLE REGION is written to the authored span right after "
            "the placements apply (Live takes end_marker and loop_end on a "
            "placed clip), so each copy SOUNDS the placement's span. "
            if any_region else
            "None of them could take a PLAYABLE REGION write, for the reason "
            "each line gives. "
        )
        plan.alert(
            f"arrangement: {len(extent_notes)} audio placement(s) landed. "
            + region_clause
            + "The BLOCK each copy occupies on the timeline is a different "
            "thing and stays the clip's own length: Live's Clip.end_time has no "
            "setter, so no push can move it — a copy can therefore sit in a "
            "block that runs past its end_bar, silent after the region ends and "
            "overlapping whatever the DB places behind it. Shorten those blocks "
            "in Live when the visual span matters or a later placement collides. "
            "Placements: "
            + " | ".join(shown)
            + (f" | and {more} more" if more > 0 else "")
        )

    if cleared or created or duplicated or placed_audio:
        plan.warn(
            f"arrangement projection: cleared {cleared}, created+filled "
            f"{created}, duplicated {duplicated} (envelope-bearing, MIDI and "
            f"audio), placed {placed_audio} audio (direct create and "
            f"duplicate together) across "
            f"{len(rows_by_track) - skipped_tracks} track(s)"
        )

    # Say which audio tracks were projected and which were left alone. A track
    # the DB has no placements for never enters the loop above, so its
    # hand-placed clips are safe by construction — but "safe by construction"
    # reads identically to "forgotten" in a report that doesn't mention it.
    untouched_audio = [
        t["name"] for t in Q.get_tracks_for_song(conn, song_id)
        if t["kind"] == "audio" and t["id"] not in rows_by_track
    ]
    if untouched_audio:
        # Operator channel, not `notes`: "untouched" and "forgotten" read the
        # same in a report that does not mention it, and the executor shows
        # the operator alerts only.
        plan.alert(
            f"arrangement: {len(untouched_audio)} audio track(s) have no DB "
            f"placements and were left UNTOUCHED (no clear, no rebuild) so "
            f"anything placed in them by hand survives: "
            f"{', '.join(sorted(untouched_audio))}"
        )
    return plan


def plan_push_arrangement_audio_regions(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    session_id: str,
) -> PushPlan:
    """Set each placed audio copy's PLAYABLE REGION to the span the placement
    authored — the pass that runs AFTER the arrangement placements apply.

    Why it is a separate pass and not part of :func:`plan_push_arrangement`: a
    `set_property` addresses an arrangement clip by index, and that index does
    not exist until the create's result comes back. This planner never predicts
    one. It reads the `arrangement_clip` binding `apply_push_results` recorded
    from `arrangement_clip_index`, so every copy it touches is one Live already
    told us the index of — the positional guess ARR-PROJ diagnosed as a root
    cause is not made here either.

    What it writes, and what it cannot:

    * `end_marker` and `loop_end` (:data:`_REGION_PROPERTIES`) go to the end of
      the authored span. A clip that runs once is bounded by the marker; a
      LOOPING one repeats its brace instead, so both move together and the copy
      sounds the authored span in either state.
    * The BLOCK the copy occupies on the timeline is `Clip.end_time`, which Live
      exposes with no setter. It is fixed when the clip is placed. Nothing here
      changes it and nothing can — the copy plays the right span inside a block
      that may still run to the file's length.

    A placement is skipped, with a reason on the operator channel, when its copy
    is not addressable (no track or `arrangement_clip` link recorded — the
    placement did not materialize, and the arrangement phase already said so) or
    when the row authors `warping = 0`, which puts the copy's markers in seconds
    while the arrangement is authored in bars (see :func:`_region_is_writable`).
    """
    plan = PushPlan()
    rows = [
        r for r in Q.get_arrangement_for_song(conn, song_id)
        if r["clip_kind"] == "audio"
    ]
    if not rows:
        plan.warn("no audio placements; no arrangement region to set")
        return plan

    ts_points = Q.get_time_signature_map(conn, song_id)
    host_clip_ids = envelope_hosting_clip_ids(conn, song_id)
    unwarped: list[str] = []
    unlinked: list[str] = []
    written = 0

    for row in rows:
        row_id = row["id"]
        where = (
            f"placement {row_id!r} (clip {row['clip_name']!r} @ bar "
            f"{row['start_bar']:g})"
        )
        track_at = Q.get_ableton_link(
            conn, session_id=session_id, db_kind="track", db_id=row["track_id"],
        )
        arr_at = Q.get_ableton_link(
            conn, session_id=session_id, db_kind="arrangement_clip", db_id=row_id,
        )
        if track_at is None or arr_at is None:
            unlinked.append(where)
            continue
        clip_row = Q.get_clip(conn, row["clip_id"])
        if clip_row is None:
            unlinked.append(where)
            continue
        if not _region_is_writable(clip_row):
            unwarped.append(where)
            continue

        region_beats = (
            _position_bar_to_beats(row["end_bar"], ts_points)
            - _position_bar_to_beats(row["start_bar"], ts_points)
        )
        # The region starts where the copy's playable region already starts, so
        # the write moves the END and nothing else. On the duplicate route the
        # session clip's conformed `start_marker` travelled with the copy; on
        # the direct create it did not (that is the conform gap the arrangement
        # phase reports), so the copy sits at Live's own 0.0.
        start_marker = 0.0
        if row["clip_id"] in host_clip_ids and clip_row["start_marker"] is not None:
            start_marker = float(clip_row["start_marker"])
        region_end = start_marker + region_beats

        for prop in _REGION_PROPERTIES:
            plan.add(ToolCall(
                tool="ableton_clip",
                args={
                    "action": "set_property",
                    "location": "arrangement",
                    "track_index": track_at,
                    "clip_index": arr_at,
                    "property": prop,
                    "value": region_end,
                },
                # Its own key kind: this writes playback bounds on an
                # already-linked copy and records no binding — declared
                # ack-only in plan._ACK_ONLY_KINDS.
                key=f"arrangement_clip_region:{row_id}:{prop}",
                purpose=(
                    f"bound arrangement copy of placement {row_id!r} to its "
                    f"authored {region_beats:g}-beat region ({prop}={region_end:g})"
                ),
            ))
        written += 1

    if written:
        plan.warn(
            f"arrangement regions: bounded {written} audio copy/copies to the "
            "authored span"
        )
    if unwarped:
        plan.alert(
            f"arrangement: {len(unwarped)} audio placement(s) kept their copy's "
            "FULL playable region — the row authors warping=0, so Live reads the "
            "copy's markers in seconds while the placement is authored in bars, "
            "and a beats-domain write would trim to the wrong point. Warp the "
            "clip, or trim the copy in Live. Placements: "
            + " | ".join(unwarped[:8])
            + (f" | and {len(unwarped) - 8} more" if len(unwarped) > 8 else "")
        )
    if unlinked:
        # Not `blocked`: the arrangement phase already reported whatever kept
        # these placements from materializing, and raising it a second time
        # would double-count one failure. Said, so a copy that is playing its
        # whole file is never a silent surprise.
        plan.alert(
            f"arrangement: {len(unlinked)} audio placement(s) have no recorded "
            "arrangement clip to bound, so their region was not set — the "
            "placement did not materialize (see the arrangement phase's own "
            "reasons). Placements: "
            + " | ".join(unlinked[:8])
            + (f" | and {len(unlinked) - 8} more" if len(unlinked) > 8 else "")
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
            f"hallucinote.arrangement's uniform beats_per_bar disagree. "
            f"Affected bars: {_divergence_bars(diverging)}. Bar "
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
