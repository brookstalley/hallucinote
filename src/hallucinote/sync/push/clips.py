"""Session-clip planners: per-clip + song-wide aggregation."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from hallucinote.db import queries as Q
from hallucinote.paths import resolve_audio_path, same_file_path, song_dir_for_conn

from ._core import PushPlan, ToolCall, _notes_for_mcp


# The authored conform surface: DB column -> the `ableton_clip(set_property)`
# property that writes it. Gain, transpose, warp and markers are what turn a
# raw file into a sample that sits in the song, so they are authorship and
# push materializes them alongside the clip rather than leaving them to a
# later mix pass.
#
# `reverse` is deliberately ABSENT. Live exposes no settable reverse on a
# Clip — the wire carries no such property — so a row that sets it cannot be
# materialized here, and the column's real materialization (a derived asset,
# or Simpler's Reverse parameter) is an open verdict. A row that sets it is
# refused loudly below rather than pushed as a forward-playing clip nobody
# was told about.
AUDIO_CONFORM_PROPERTIES: tuple[tuple[str, str], ...] = (
    ("audio_gain",   "gain"),
    ("pitch_coarse", "pitch_coarse"),
    ("pitch_fine",   "pitch_fine"),
    ("warping",      "warping"),
    ("warp_mode",    "warp_mode"),
    ("start_marker", "start_marker"),
    ("end_marker",   "end_marker"),
)

# `warping` is an INTEGER 0/1 in the DB, a bool on the wire and a bool in
# Live's read-back; send and compare it as a bool so 1 and True are one value.
_BOOL_CONFORM_COLUMNS = frozenset({"warping"})

_INT_CONFORM_COLUMNS = frozenset({"pitch_coarse", "warp_mode"})

# Live reports gain and markers as floats it has already run through its own
# domain, so an exact `==` would re-write an unchanged clip on every push.
_CONFORM_EPS = 1e-6

# Named in every refusal below so a reader can find the one thing that closes
# it: the operator-gated Live session that settles the recreate semantics.
_UNPROBED = (
    "SMP-6V2K chunk 01 — the operator-gated Live session that settles this — "
    "has not run"
)


def _conform_value(column: str, raw: Any) -> Any:
    """The DB value in the domain the wire declares for it."""
    if column in _BOOL_CONFORM_COLUMNS:
        return bool(raw)
    if column in _INT_CONFORM_COLUMNS:
        return int(raw)
    return float(raw)


def _conform_is_current(authored: Any, live: Any) -> bool:
    """Whether Live already holds ``authored``. Unreadable / unrecognizable
    live values answer False — keep the write on doubt, the same posture the
    devices diff takes, because a skipped write is silent and a redundant one
    is merely redundant."""
    if isinstance(authored, bool):
        return bool(live) is authored
    try:
        return abs(float(live) - float(authored)) <= _CONFORM_EPS
    except (TypeError, ValueError):
        return False


# A track whose probe FAILED is absent from the probe map; a track that probed
# successfully is present, with an empty list when it simply holds no clips.
# Those two must never collapse: "unknown" answered as "empty" plans a
# `replace=True` recreate, which deletes a clip the operator really has and
# rebuilds it — losing exactly the un-modelled Live-side state (warp markers, a
# clip envelope) whose survival across a recreate is the unknown the changed-file
# branch refuses to act on. So the reader is tri-state, and this sentinel is the
# third state rather than another `None` for a caller to remember to check.
PROBE_UNKNOWN = object()


def _live_session_entry(
    live_session_clips_by_track: dict[int, list[dict[str, Any]]] | None,
    *,
    track_at: int,
    clip_index: int,
) -> Any:
    """The probed Live session clip occupying ``clip_index`` on ``track_at``.

    Returns the entry when the slot holds one, ``None`` when the track probed
    successfully and that slot is genuinely empty, and :data:`PROBE_UNKNOWN`
    when this track's state is not known — either no probe was taken at all, or
    this track's probe failed and left it out of the map.
    """
    if live_session_clips_by_track is None:
        return PROBE_UNKNOWN
    track_clips = live_session_clips_by_track.get(track_at)
    if track_clips is None:
        return PROBE_UNKNOWN
    for entry in track_clips:
        if entry.get("clip_index") == clip_index:
            return entry
    return None


def _audio_conform_calls(
    clip: sqlite3.Row,
    *,
    clip_id: str,
    track_at: int,
    clip_index: int,
    live_entry: dict[str, Any] | None,
) -> list[ToolCall]:
    """One ``set_property`` call per authored conform field.

    A NULL column means "never authored", never "reset Live" — the same rule
    the mix phase applies to its mixer fields. When ``live_entry`` is a probed
    read of the clip Live actually holds, a field Live already carries is
    skipped, which is what makes a second push of an unchanged song plan
    nothing at all.
    """
    calls: list[ToolCall] = []
    for column, prop in AUDIO_CONFORM_PROPERTIES:
        raw = clip[column]
        if raw is None:
            continue
        value = _conform_value(column, raw)
        if (
            live_entry is not None
            and prop in live_entry
            and _conform_is_current(value, live_entry[prop])
        ):
            continue
        calls.append(ToolCall(
            tool="ableton_clip",
            args={
                "action": "set_property",
                "track_index": track_at,
                "location": "session",
                "clip_index": clip_index,
                "property": prop,
                "value": value,
            },
            # Ack-only (`_ACK_ONLY_KINDS`): the value ORIGINATES in the DB and
            # a conform write records no Live-side index, exactly like the
            # mixer set_property keys.
            key=f"clip_conform:{clip_id}:{prop}",
            purpose=(
                f"conform audio clip {clip['name']!r} in slot {clip['slot']}: "
                f"{prop}={value!r}"
            ),
        ))
    return calls


def _plan_push_audio_clip(
    plan: PushPlan,
    *,
    conn: sqlite3.Connection,
    clip: sqlite3.Row,
    clip_id: str,
    track_at: int,
    clip_at: int | None,
    live_session_clips_by_track: dict[int, list[dict[str, Any]]] | None,
) -> None:
    """Plan the materialization of one ``kind='audio'`` row (R1.1).

    Three outcomes, and which one a row gets is decided here rather than at
    dispatch:

    * **Not linked** → ``create(kind='audio', audio_path=<absolute>)`` plus
      every authored conform property.
    * **Linked and playing the file the row names** → the conform properties
      only, and (with a probe) only the ones Live does not already hold.
    * **Anything that cannot be materialized without guessing** → no calls and
      a :meth:`PushPlan.blocked` reason that says what is unknown.

    The existence check happens BEFORE the create is planned. A clip that
    pushes and then plays silence is a phase reporting OK without having
    determined its state, which is precisely what the sync boundary contract
    forbids.
    """
    ref = clip["audio_file"]
    slot = clip["slot"]
    where = f"clip {clip_id} ({clip['name']!r}, slot {slot})"

    if not ref:
        # The mutator requires audio_file, so this is a row that got here some
        # other way. Determinable and unmaterializable — say so.
        plan.blocked(
            f"{where} is kind='audio' with no audio_file: the row does not say "
            "what it plays, so nothing can be created for it."
        )
        return

    song_dir = song_dir_for_conn(conn)
    if song_dir is None:
        plan.blocked(
            f"{where} is kind='audio' and references {ref!r}, but this "
            "connection has no database file on disk, so there is no song "
            "directory to resolve a song-relative reference against. Open the "
            "song's DB through init_db(<song dir>/<slug>.db) and re-plan."
        )
        return

    resolved = resolve_audio_path(song_dir, ref)
    if not resolved.is_file():
        plan.blocked(
            f"{where} is kind='audio' but its sample is not on disk: "
            f"audio_file={ref!r} resolves to {resolved} against song directory "
            f"{song_dir}. NO create was planned — pushing it would put a clip "
            "in Live that plays silence, which is a phase reporting OK without "
            "having determined its state. Put the file there (canonically "
            "under assets/) or fix the reference, then re-push."
        )
        return

    if clip["reverse"]:
        # Not fatal to the placement — the sample still belongs in the set —
        # but the author asked for reversed playback and it does not happen,
        # and a run that says OK over that is the silent-wrong-audio failure.
        plan.blocked(
            f"{where} sets reverse=1, which push cannot materialize: Live "
            "exposes no settable reverse on a Clip, so the wire carries no "
            "such property. The clip is placed and conformed FORWARD. Reverse "
            "belongs to a derived (pre-reversed) asset or to a sampler's own "
            f"Reverse parameter, and {_UNPROBED} — it is what confirms which."
        )

    if clip_at is None:
        plan.add(ToolCall(
            tool="ableton_clip",
            args={
                "action": "create",
                "location": "session",
                "kind": "audio",
                "track_index": track_at,
                "clip_index": slot,
                # ABSOLUTE by contract — Live resolves nothing, and the wire
                # refuses a relative path.
                "audio_path": str(resolved),
                "name": clip["name"],
                # The slot may hold a scaffold clip; replace makes the create
                # state-independent, the same posture the MIDI create takes.
                "replace": True,
            },
            key=f"clip:{clip_id}",
            purpose=(
                f"create session audio clip in slot {slot} on track "
                f"{track_at} from {resolved.name}"
            ),
        ))
        for call in _audio_conform_calls(
            clip, clip_id=clip_id, track_at=track_at, clip_index=slot,
            live_entry=None,
        ):
            plan.add(call)
        return

    # --- Already linked: reconcile rather than recreate. -------------------
    live_entry = _live_session_entry(
        live_session_clips_by_track, track_at=track_at, clip_index=clip_at,
    )

    if live_entry is PROBE_UNKNOWN:
        # This track's state is UNKNOWN — either no probe at all, or this
        # track's probe failed. Both mean the same thing here and get the same
        # answer. The conform properties are written anyway: they originate in
        # the DB, a set_property is a pure overwrite, and withholding them
        # would drop authored intent on every re-push. What is NOT done is
        # anything destructive — no delete, no recreate — so a re-pointed
        # audio_file goes undetected rather than acted on wrongly.
        if live_session_clips_by_track is None:
            plan.warn(
                f"{where}: no Live session-clip probe was supplied, so the "
                "file Live actually holds was not verified; conform properties "
                "are written in place and nothing is recreated."
            )
        else:
            # BLOCKED, not warn. `warn` writes to `notes`, the diagnostic
            # channel the operator is never shown, so a conform written without
            # verifying which file Live's slot holds would exit 0 saying
            # nothing — the "reported OK without having determined its state"
            # failure this contract forbids. The arrangement phase already
            # rules an identical per-track probe failure this way. The
            # no-probe-at-all arm above stays a warn because that caller
            # deliberately did not probe; this one asked and did not find out.
            plan.blocked(
                f"{where}: the session-clip probe for track {track_at} FAILED, "
                "so this slot's contents are unknown. Conform properties were "
                "written in place and nothing was recreated — an unknown slot "
                "is not an empty one, and answering it with a recreate would "
                "delete a clip that is really there — but which file Live "
                "actually holds was NOT verified. Re-run once Live is "
                "reachable for that track."
            )
        for call in _audio_conform_calls(
            clip, clip_id=clip_id, track_at=track_at, clip_index=clip_at,
            live_entry=None,
        ):
            plan.add(call)
        return

    if live_entry is None:
        # Probed successfully, and the linked slot is genuinely EMPTY. Only a
        # successful probe reaches here — a failed one is PROBE_UNKNOWN and was
        # handled above — and that distinction is the whole point: an empty slot
        # is not a recreate, there is nothing to destroy, so create it.
        plan.warn(
            f"{where}: linked to Live slot {clip_at}, which the probe reports "
            "as empty — recreating it (nothing is destroyed by a create into "
            "an empty slot)."
        )
        plan.add(ToolCall(
            tool="ableton_clip",
            args={
                "action": "create",
                "location": "session",
                "kind": "audio",
                "track_index": track_at,
                "clip_index": clip_at,
                "audio_path": str(resolved),
                "name": clip["name"],
                "replace": True,
            },
            key=f"clip:{clip_id}",
            purpose=(
                f"recreate session audio clip in empty linked slot {clip_at} "
                f"on track {track_at} from {resolved.name}"
            ),
        ))
        for call in _audio_conform_calls(
            clip, clip_id=clip_id, track_at=track_at, clip_index=clip_at,
            live_entry=None,
        ):
            plan.add(call)
        return

    if not live_entry.get("is_audio"):
        plan.blocked(
            f"{where} is linked to Live slot {clip_at} on track {track_at}, "
            "and the probe says that slot holds a clip that is NOT audio. "
            "Making it audio means deleting what is there and creating in its "
            f"place, and whether a recreate preserves the clip's envelopes is "
            f"unknown: {_UNPROBED}. Nothing was planned for this clip. Clear "
            "the slot in Live by hand and re-push, or run chunk 01."
        )
        return

    live_file = live_entry.get("file_path")
    if not live_file:
        plan.blocked(
            f"{where} is linked to Live slot {clip_at}, which the probe "
            "reports as an audio clip with no file_path. Which file it plays "
            "could not be DETERMINED, so no conform write was planned — "
            "writing gain or warp onto an unidentified clip is a push that "
            "reports OK over an unknown."
        )
        return

    if not same_file_path(Path(live_file), resolved):
        plan.blocked(
            f"{where}: the row's audio_file CHANGED. Live's clip in slot "
            f"{clip_at} plays {live_file!r}; the row now authors "
            f"{str(resolved)!r}. Live's Clip.file_path is READ-ONLY, so "
            "re-pointing a clip at a different file is a delete-and-recreate, "
            "and whether a recreate preserves the clip's envelopes is "
            f"unknown: {_UNPROBED}. Nothing was planned for this clip rather "
            "than an invented ordering — a recreate could silently drop an "
            "authored ride, and re-emitting the envelope 'just in case' could "
            "double one that survived. Run chunk 01, or delete the clip in "
            "Live by hand and re-push to recreate it."
        )
        return

    # Same file: update the conform properties in place, and only the ones
    # Live does not already hold. An unchanged row plans nothing.
    for call in _audio_conform_calls(
        clip, clip_id=clip_id, track_at=track_at, clip_index=clip_at,
        live_entry=live_entry,
    ):
        plan.add(call)


def plan_push_clip(
    conn: sqlite3.Connection,
    *,
    clip_id: str,
    session_id: str,
    live_session_clips_by_track: dict[int, list[dict[str, Any]]] | None = None,
) -> PushPlan:
    """Plan the push of a single session clip to Ableton.

    MIDI, two cases (W3-C narrowed from three; track-creation moved to
    :func:`plan_push_song_tracks`):
      1. Clip not yet linked  -> ``ableton_clip(action='create',
         location='session', kind=…, replace=True, notes=…)``  — atomic
         single-call create+populate (Wave M+1-1).
      2. Clip already linked  -> ``ableton_clip(action='replace_notes')``
         (in-place; gap #1's renamed action, unified via Wave M-3).

    Audio (R1.1) routes to :func:`_plan_push_audio_clip`: a create carrying
    the resolved ABSOLUTE sample path, plus the authored conform properties
    (gain, transpose, warp / warp_mode, markers). Two things it refuses rather
    than guesses, each with a :meth:`PushPlan.blocked` reason naming what is
    unknown: a sample that is not on disk, and a linked clip whose file has
    changed underneath the row (``Clip.file_path`` is read-only, so that is a
    delete-and-recreate whose cost to the clip's envelopes is unprobed).

    ``live_session_clips_by_track`` is the per-track Live session-clip
    inventory (``{track_index: [{clip_index, is_audio, file_path, gain, …}]}``
    — the shape ``ableton_clip(action='list', location='session')`` returns,
    empty slots dropped; ``push_cli._probe_live_session_clips_via_mcp``
    produces it). It answers two questions no DB read can: which file a linked
    clip actually plays, and which conform values Live already holds. With it,
    a second push of an unchanged song plans NOTHING. Without it the planner
    still materializes and conforms — it just cannot detect a re-pointed
    ``audio_file``, and it plans nothing destructive; :func:`plan_push_clips`
    raises one alert per song saying so.

    Precondition (W3-C — strict): the clip's track must already be linked in
    this session. Run :func:`plan_push_song_tracks` first to create+link all
    unlinked tracks, ``apply_push_results``, then call this planner. The strict
    raise replaces the prior silent-redundant-emit behavior that produced N
    duplicate ``ableton_track(create)`` calls for N clips on the same unlinked
    track (32 calls for an 8-track / 32-clip song; one per CLIP, not per
    TRACK). It applies to audio rows too, now that they materialize: an audio
    clip needs its track's Live index exactly as a MIDI one does.
    """
    plan = PushPlan()

    clip = Q.get_clip(conn, clip_id)
    if clip is None:
        raise ValueError(f"clip {clip_id} not found")

    track_row = Q.get_track(conn, clip["track_id"])
    if track_row is None:
        raise ValueError(f"track {clip['track_id']} not found for clip {clip_id}")

    track_at = Q.get_ableton_link(
        conn, session_id=session_id, db_kind="track", db_id=track_row["id"]
    )
    clip_at = Q.get_ableton_link(
        conn, session_id=session_id, db_kind="clip", db_id=clip_id
    )

    if track_at is None:
        raise ValueError(
            f"plan_push_clip: track {track_row['id']!r} ('{track_row['name']}') "
            f"is not linked in session {session_id!r}. Call "
            f"plan_push_song_tracks(conn, song_id=..., session_id=...) first "
            f"to create and link any unlinked tracks (one call per unique "
            f"track, not per clip), apply_push_results, then re-run "
            f"plan_push_clip."
        )

    if clip["kind"] == "audio":
        _plan_push_audio_clip(
            plan,
            conn=conn,
            clip=clip,
            clip_id=clip_id,
            track_at=track_at,
            clip_at=clip_at,
            live_session_clips_by_track=live_session_clips_by_track,
        )
        return plan

    notes = Q.get_notes_for_clip(conn, clip_id)

    if clip_at is None:
        # Wave M+1-1: atomic single-call create+populate. `replace=True`
        # makes the handler delete an occupied slot before creating, so the
        # planner doesn't have to know the slot's current state. The handler
        # returns `clip_index`, which `_LINK_KINDS["clip"]` reads to record
        # the binding via the generic apply path.
        plan.add(ToolCall(
            tool="ableton_clip",
            args={
                "action": "create",
                "location": "session",
                "kind": "midi",
                "track_index": track_at,
                "clip_index": clip["slot"],
                "length": clip["length_beats"],
                "name": clip["name"],
                "notes": _notes_for_mcp(notes),
                "replace": True,
            },
            key=f"clip:{clip_id}",
            purpose=f"create+populate session clip slot {clip['slot']} on track {track_at}",
        ))
    else:
        plan.add(ToolCall(
            tool="ableton_clip",
            args={
                "action": "replace_notes",
                "track_index": track_at,
                "location": "session",
                "clip_index": clip_at,
                "notes": _notes_for_mcp(notes),
            },
            key=f"clip:{clip_id}",
            purpose=f"replace notes in existing clip ({len(notes)} notes)",
        ))

    return plan


def plan_push_clips(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    session_id: str,
    live_session_clips_by_track: dict[int, list[dict[str, Any]]] | None = None,
) -> PushPlan:
    """Plan the create/replace of every session clip in a song.

    Aggregates :func:`plan_push_clip` over every ``clips`` row whose
    parent track belongs to this song. Per-clip warnings are prefixed
    with the clip name so the merged plan stays diagnosable; per-clip
    alerts, errors and blocked reasons ride up UNPREFIXED and unmerged —
    they already name their clip, and a blocked reason that did not reach
    this plan would be a push reporting OK over work it did not do.

    ``live_session_clips_by_track`` is threaded down to each per-clip plan;
    see :func:`plan_push_clip` for what it answers. When a song has audio
    clips already linked and NO probe was supplied, one alert says the file
    identity behind those links was not verified — the same shape as the
    arrangement projection's "planned WITHOUT a Live arrangement probe".

    Strict precondition (inherited from :func:`plan_push_clip`): every
    clip's track must already be linked in this session. Run
    :func:`plan_push_song_tracks` first, ``apply_push_results``, then
    this. The strict raise surfaces orchestration order bugs loudly —
    a silent skip would leave Live missing clips with no signal.
    """
    # Resolve `plan_push_clip` through the package facade at call time so
    # callers that monkeypatch the public `push.plan_push_clip` seam (the
    # behavior the original single-module file exposed) still intercept it.
    # Function-local import avoids a load-time cycle (the package __init__
    # imports this module).
    from hallucinote.sync import push

    plan = PushPlan()
    rows = Q.get_clips_for_song(conn, song_id)
    unverified_audio: list[str] = []
    for c in rows:
        sub = push.plan_push_clip(
            conn, clip_id=c["id"], session_id=session_id,
            live_session_clips_by_track=live_session_clips_by_track,
        )
        plan.calls.extend(sub.calls)
        plan.notes.extend(f"[{c['name']}] {n}" for n in sub.notes)
        plan.errors.extend(sub.errors)
        # Re-record through `blocked` so each reason lands on BOTH channels,
        # the way the sub-plan wrote it. `alerts` then carries the sub-plan's
        # own alerts only — a blocked reason copied twice would read as two.
        for reason in sub.blocked_reasons:
            plan.blocked(reason)
        plan.alerts.extend(
            a for a in sub.alerts if a not in sub.blocked_reasons
        )
        if (
            c["kind"] == "audio"
            and live_session_clips_by_track is None
            and Q.get_ableton_link(
                conn, session_id=session_id, db_kind="clip", db_id=c["id"],
            ) is not None
        ):
            unverified_audio.append(c["name"] or c["id"])
    if unverified_audio:
        plan.alert(
            f"{len(unverified_audio)} already-linked audio clip(s) were "
            f"conformed WITHOUT a Live session-clip probe "
            f"({', '.join(sorted(unverified_audio))}): which file each Live "
            "clip actually plays was not verified, so a re-pointed audio_file "
            "would not be detected. Nothing destructive was planned. Pass "
            "live_session_clips_by_track (push_cli._probe_live_session_clips_"
            "via_mcp) to close the check."
        )
    if not rows:
        # Keyed on the ROWS, not on an empty plan: an audio row that refused
        # loudly plans no calls and no notes, and "no clips for this song"
        # over a clip the song does have would be a false clean skip.
        plan.warn("no clips for this song; nothing to push")
    return plan
