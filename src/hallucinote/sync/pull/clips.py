"""Clip-placement pull: arrangement-clip placements + session-view clip slots
— planners + apply.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from hallucinote.db import mutations as M, queries as Q
from hallucinote.paths import resolve_audio_path

from ._core import (
    PullCall,
    PullPlan,
    ApplyResult,
    _beats_to_position_bar,
    _bool_db,
    _floats_differ,
    _ints_differ,
    _raw_values_match,
)


# ---------------------------------------------------------------------------
# Audio-clip ingest: the path form, and the song anchor it is measured against
# ---------------------------------------------------------------------------


def _song_dir_for_conn(conn: sqlite3.Connection) -> Path | None:
    """The directory holding this song's ``build.py``, DB and ``assets/``.

    ``clips.audio_file`` is anchored to the song directory, but the pull apply
    layer is handed a connection rather than a path — so the anchor is read off
    the connection's own main database file (``songs/<slug>/<slug>.db`` ->
    ``songs/<slug>/``), the same derivation ``tools/song_context.py`` uses.

    Returns ``None`` for an in-memory database: there is then no anchor, and
    every ingested reference is stored absolute rather than guessed at.
    """
    # PRAGMA database_list rows are (seq, name, file); indexed positionally so
    # the read works under either row factory.
    for row in conn.execute("PRAGMA database_list"):
        if row[1] == "main":
            return Path(row[2]).parent if row[2] else None
    return None


def _relative_to_or_none(path: Path, base: Path) -> str | None:
    """``path`` under ``base`` as a POSIX string, or None when it is outside.

    Tried as given and then with both filesystem-normalized, because the song
    dir and Live's reported path can agree only through a symlink (macOS
    resolves ``/tmp`` to ``/private/tmp``); a purely textual containment check
    would miss the relation and store an absolute path for a file that does
    live under the song directory. Same two-attempt shape, and the same
    reason, as ``paths._relative_or_none``.
    """
    for candidate, anchor in ((path, base), (path.resolve(), base.resolve())):
        try:
            return candidate.relative_to(anchor).as_posix()
        except ValueError:
            continue
    return None


def _audio_file_ref(song_dir: Path | None, file_path: str) -> str:
    """Render Live's absolute path into the form ``clips.audio_file`` carries.

    Two forms, and only two: **song-relative POSIX** when the file lives under
    the song directory (the canonical ``assets/...`` reference, which diffs
    identically on every machine), **absolute** for anything else — a sample
    dragged in from the user's own library keeps its absolute path.

    Deliberately NOT :func:`hallucinote.paths.portable_path`. That helper's
    middle form collapses an outside-the-base path to ``~/...``, and the
    resolver this column is read back through — :func:`resolve_audio_path` —
    does not expand ``~`` (only ``resolve_portable_path`` does). A
    ``~``-collapsed reference stored here would resolve as a *relative* path
    under the song directory and fail at the next push.
    """
    p = Path(file_path)
    if song_dir is not None:
        rel = _relative_to_or_none(p, song_dir)
        if rel is not None:
            return rel
    return p.as_posix()


def _same_audio_file(
    song_dir: Path | None, db_ref: Any, live_path: str,
) -> bool:
    """Whether the DB reference and Live's absolute path name the same file.

    Compared as PATHS, never as strings: the DB canonically stores
    ``assets/line.wav`` while Live reports
    ``/.../songs/<slug>/assets/line.wav``, and a textual compare would read
    that as drift and rewrite the portable reference into a machine-absolute
    one on every pull.
    """
    if not db_ref:
        return False
    live = Path(live_path)
    if song_dir is None:
        # No anchor: a relative reference cannot be resolved, so only an
        # absolute one is comparable.
        db_path = Path(str(db_ref))
        if not db_path.is_absolute():
            return False
    else:
        db_path = resolve_audio_path(song_dir, str(db_ref))
    return db_path == live or db_path.resolve() == live.resolve()


def _raw_floats_differ(new: Any, existing: Any) -> bool:
    """:func:`_floats_differ` with a magnitude-relative tolerance (DEV-4P7R).

    For values that carry native magnitude rather than a [0,1] scale — a start
    marker 240 beats into a clip. An absolute epsilon reads Live's
    fourth-significant-digit jitter at that magnitude as drift, and would churn
    the row plus an event on every pull.
    """
    if new is None:
        return False
    if existing is None:
        return True
    return not _raw_values_match(float(new), existing)


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
                "push it via the tracks phase (plan_push_song_tracks) first, "
                "then re-run pull"
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
                "push it via the tracks phase (plan_push_song_tracks) first, "
                "then re-run pull"
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
        # Audio placements are diffed like any other. They were exempted
        # while audio push did not exist — Live never reported them, so the
        # removal pass would have deleted authored state on every pull — but
        # the clips and arrangement phases materialize kind='audio' now, so a
        # DB placement Live does not report is a real removal, not an
        # unknown, and the exemption would instead pin deleted state forever.
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
      - slot populated in Ableton only, MIDI                       -> warn + skip
        (V1 can't auto-create the DB clip from name + length alone;
         note pull would let us fill in content, but distinguishing a
         brand-new session clip from a moved-into-this-slot existing
         clip is the same identity problem as the arrangement case)
      - slot populated in Ableton only, AUDIO                      -> `create_audio_clip`
      - slot populated in both, but the two disagree on kind       -> warn + skip

    **An audio clip in Live becomes source (R1.2).** MIDI cannot be
    auto-created because the wire carries no note content, but an audio clip
    is fully described by what it plays and how it is conformed — file, gain,
    transpose, warp, markers — and every one of those travels on the `list`
    payload. So a line the user dragged into Live by hand is ingested rather
    than warned about: it becomes part of the song's source instead of living
    only in the `.als`. Its file reference is stored in the two forms
    `clips.audio_file` is defined to carry (see :func:`_audio_file_ref`).

    Kind is immutable on a clip row, so a slot where Live and the DB disagree
    on kind is reported, never coerced: converting is delete + create, and
    doing that silently on a pull would drop authored state.

    Note content drift is NOT detected here — that's Chunk D's job
    (note pull via stable-ID read). This planner only diffs the
    container-level fields (`name`, `length`) plus, for audio, the conform
    surface the MCP read action returns.

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

    # Audio rows are in the diff like any other. They were exempted while
    # audio push did not exist — Live's slot state said nothing about them,
    # so an empty slot was not evidence of a deletion — but the clips phase
    # materializes kind='audio' now. An audio row whose Live slot is empty is
    # therefore a real delete, and keeping the exemption would pin a clip the
    # user removed in Live into the song forever.
    db_by_slot: dict[int, sqlite3.Row] = {
        int(c["slot"]): c for c in Q.get_clips_for_track(conn, track_id)
    }
    song_dir = _song_dir_for_conn(conn)
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

        # `is_audio` is the wire's discriminator; an audio entry also carries
        # the conform surface, and a MIDI entry omits those keys entirely
        # rather than null-filling them, so absence never means "audio whose
        # file we could not determine". A payload from a pre-audio server
        # omits the key altogether and reads as MIDI — the same conservative
        # default the handler itself takes.
        is_audio = bool(entry.get("is_audio", False))
        live_kind = "audio" if is_audio else "midi"

        if db_clip is not None and db_clip["kind"] != live_kind:
            # Clip `kind` is immutable (MIDI <-> audio is delete + create), so
            # this is reported rather than coerced. Silently drift-updating
            # across the kinds would write Live's foreign clip over authored
            # state — a MIDI name and length onto an audio row, or an audio
            # file reference the mutator would refuse.
            out.warnings.append(
                f"track {track_row['name']!r}: session slot {slot} holds a "
                f"kind={live_kind!r} clip in Live but a "
                f"kind={db_clip['kind']!r} clip {db_clip['name']!r} in the "
                "DB — clip kind is immutable, so pull does not convert it. "
                "Delete one side (delete+create doctrine) and re-run pull."
            )
            continue

        if is_audio:
            _ingest_session_audio_clip(
                conn, track_row=track_row, slot=slot, entry=entry,
                db_clip=db_clip, song_dir=song_dir, out=out,
                actor=actor, request_id=request_id, reason=reason,
            )
            continue

        if db_clip is None:
            # Ableton has MIDI content the DB doesn't know about. Same V1
            # limitation as the arrangement-clip case: positional
            # matching can't distinguish a brand-new clip from a
            # session-side move, and the MCP wire shape doesn't carry
            # note content for auto-create. (An AUDIO clip IS auto-created —
            # everything that defines it travels on this payload.)
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


def _ingest_session_audio_clip(
    conn: sqlite3.Connection,
    *,
    track_row: sqlite3.Row,
    slot: int,
    entry: dict[str, Any],
    db_clip: sqlite3.Row | None,
    song_dir: Path | None,
    out: ApplyResult,
    actor: str,
    request_id: str | None,
    reason: str | None,
) -> None:
    """Ingest one audio clip Live reports in a session slot (R1.2).

    Creates the `clips` row when the DB has nothing at this slot — **the case
    this exists for**: a line the user dragged into Live by hand becomes part
    of the song's source instead of living only in the `.als`. Otherwise it
    conforms the existing audio row to what Live now holds.

    `reverse` is never written: Live exposes no reverse property on a Clip at
    all, so the wire reports none and pull would be inventing state.

    Live's `length`, `start_marker` and `end_marker` carry a dual unit —
    BEATS when the clip is warped, SECONDS when it is not. They are stored as
    reported, with `warping` on the same row saying which unit it is; writing
    a seconds-valued length into `length_beats` is called out in a warning
    rather than silently normalized, because there is no tempo-independent
    conversion to make.
    """
    name_in = entry.get("name")
    length_in = entry.get("length")
    file_in = entry.get("file_path")
    gain_in = entry.get("gain")
    coarse_in = entry.get("pitch_coarse")
    fine_in = entry.get("pitch_fine")
    warping_in = _bool_db(entry.get("warping"))
    warp_mode_in = entry.get("warp_mode")
    start_in = entry.get("start_marker")
    end_in = entry.get("end_marker")

    def _unwarped_unit_note(what: str) -> None:
        if warping_in == 0:
            out.warnings.append(
                f"track {track_row['name']!r}: session slot {slot} holds an "
                f"UNWARPED audio clip, so Live reports its {what} in SECONDS, "
                "not beats (Live's dual unit). The value is stored as "
                "reported and the row records warping=0 alongside it; warp "
                "the clip in Live if you want musical-time values."
            )

    if db_clip is None:
        # --- the hand-dragged case: Live has it, the song does not ---
        if track_row["kind"] != "audio":
            out.warnings.append(
                f"track {track_row['name']!r}: session slot {slot} holds an "
                f"audio clip {name_in!r} in Live, but the DB models this "
                f"track as kind={track_row['kind']!r} — Live hosts audio "
                "clips only on audio tracks, so the two disagree about what "
                "this track is. Not ingested; fix the track kind (delete + "
                "create) and re-run pull."
            )
            return
        if not file_in:
            out.warnings.append(
                f"track {track_row['name']!r}: session slot {slot} reports an "
                f"audio clip {name_in!r} with no 'file_path' — the row must "
                "answer 'what does this clip play?', so it cannot be "
                "ingested. Re-run pull against a server that reports audio "
                "file paths."
            )
            return
        if length_in is None:
            out.warnings.append(
                f"track {track_row['name']!r}: session slot {slot} reports an "
                f"audio clip {name_in!r} with no 'length' — cannot ingest a "
                "clip with no extent; skipping."
            )
            return
        ref = _audio_file_ref(song_dir, str(file_in))
        _unwarped_unit_note("length and markers")
        cid = M.create_audio_clip(
            conn,
            track_id=track_row["id"],
            slot=slot,
            length_beats=float(length_in),
            audio_file=ref,
            name=name_in,
            gain=None if gain_in is None else float(gain_in),
            pitch_coarse=None if coarse_in is None else int(coarse_in),
            pitch_fine=None if fine_in is None else float(fine_in),
            warping=warping_in,
            warp_mode=None if warp_mode_in is None else int(warp_mode_in),
            start_marker=None if start_in is None else float(start_in),
            end_marker=None if end_in is None else float(end_in),
            actor=actor, request_id=request_id, reason=reason,
        )
        out.mutations += 1
        out.details.append(
            f"track {track_row['name']!r}: session slot {slot} audio clip "
            f"{name_in!r} ingested from Live (clip_id={cid[:8]}, "
            f"audio_file={ref!r})"
        )
        return

    # --- the DB already knows this clip: conform it to Live ---
    changes: dict[str, Any] = {}
    if name_in is not None and name_in != db_clip["name"]:
        changes["name"] = name_in
    # A value Live did not report is silence, never "clear it": each
    # comparison is guarded on the reported value being present, which is
    # also what the `_*_differ` helpers' None asymmetry already encodes.
    if length_in is not None and _floats_differ(length_in, db_clip["length_beats"]):
        changes["length_beats"] = float(length_in)
    if file_in and not _same_audio_file(song_dir, db_clip["audio_file"], str(file_in)):
        # The user pointed the slot at a different sample in Live. Leaving
        # the old reference would make the next push overwrite their choice
        # with the file they replaced.
        changes["audio_file"] = _audio_file_ref(song_dir, str(file_in))
    if gain_in is not None and _floats_differ(gain_in, db_clip["audio_gain"]):
        changes["audio_gain"] = float(gain_in)
    if coarse_in is not None and _ints_differ(coarse_in, db_clip["pitch_coarse"]):
        changes["pitch_coarse"] = int(coarse_in)
    if fine_in is not None and _floats_differ(fine_in, db_clip["pitch_fine"]):
        changes["pitch_fine"] = float(fine_in)
    if warping_in is not None and _ints_differ(warping_in, db_clip["warping"]):
        changes["warping"] = warping_in
    if warp_mode_in is not None and _ints_differ(warp_mode_in, db_clip["warp_mode"]):
        changes["warp_mode"] = int(warp_mode_in)
    if start_in is not None and _raw_floats_differ(start_in, db_clip["start_marker"]):
        changes["start_marker"] = float(start_in)
    if end_in is not None and _raw_floats_differ(end_in, db_clip["end_marker"]):
        changes["end_marker"] = float(end_in)

    if not changes:
        out.no_ops += 1
        return
    if "length_beats" in changes:
        _unwarped_unit_note("length")
    M.update_clip(
        conn, clip_id=db_clip["id"],
        actor=actor, request_id=request_id, reason=reason,
        **changes,
    )
    out.mutations += 1
    out.details.append(
        f"track {track_row['name']!r}: session slot {slot} audio clip "
        f"conformed to Live (clip_id={db_clip['id'][:8]}): {changes!r}"
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
