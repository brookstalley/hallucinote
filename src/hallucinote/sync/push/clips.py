"""Session-clip planners: per-clip + song-wide aggregation."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from hallucinote.db import queries as Q
from hallucinote.paths import resolve_audio_path, same_file_path, song_dir_for_conn

from ._core import PushPlan, ToolCall, _notes_for_mcp
from .envelopes import plan_push_envelopes_for_clip


# The authored conform surface: DB column -> the `ableton_clip(set_property)`
# property that writes it. Gain, transpose, warp and markers are what turn a
# raw file into a sample that sits in the song, so they are authorship and
# push materializes them alongside the clip rather than leaving them to a
# later mix pass.
#
# `reverse` is deliberately ABSENT. Live exposes no settable reverse on a
# Clip — probe-confirmed on a real audio clip: 49 properties, 142 methods, none
# of them a reverse — so the wire carries no such property. Simpler has none
# either; its `reverse()` is a destructive method that writes a derived file.
# Reverse is materialized one step earlier instead, as a pre-reversed DERIVED
# ASSET the clip is pointed at (:func:`resolve_reversed_sample`): the flag
# changes which FILE the clip plays, never a property on the wire.
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
# rebuilds it — losing the un-modelled Live-side state a recreate does not
# carry (warp markers; and a recreate drops the clip's envelopes, which is why
# the changed-file branch re-emits them). So the reader is tri-state, and this
# sentinel is the third state rather than another `None` for a caller to
# remember to check.
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


def resolve_authored_sample(
    conn: sqlite3.Connection,
    clip: sqlite3.Row,
    *,
    where: str,
) -> tuple[Path | None, str | None]:
    """Resolve a ``kind='audio'`` row's ``audio_file`` to the ABSOLUTE path a
    Live call takes, or say why it cannot be.

    Returns ``(path, None)`` or ``(None, reason)``. The one home for the rule
    both push phases share — **the file's existence is checked before any
    call is planned** — so a later tightening (readability, a format check)
    lands once. Three refusals, each determinable and unmaterializable:

    * no ``audio_file`` at all (the mutator requires one, so the row got here
      some other way);
    * a connection with no database file on disk, so a song-relative
      reference has no directory to resolve against;
    * a sample that is not on disk. A clip that pushes and then plays
      silence is a phase reporting OK without having determined its state,
      which is precisely what the sync boundary contract forbids.

    ``where`` names the row for the reason text; callers append their own
    consequence.
    """
    ref = clip["audio_file"]
    if not ref:
        return None, (
            f"{where} is kind='audio' with no audio_file: the row does not say "
            "what it plays, so nothing can be created for it."
        )
    song_dir = song_dir_for_conn(conn)
    if song_dir is None:
        return None, (
            f"{where} is kind='audio' and references {ref!r}, but this "
            "connection has no database file on disk, so there is no song "
            "directory to resolve a song-relative reference against. Open the "
            "song's DB through init_db(<song dir>/<slug>.db) and re-plan."
        )
    resolved = resolve_audio_path(song_dir, ref)
    if not resolved.is_file():
        return None, (
            f"{where} is kind='audio' but its sample is not on disk: "
            f"audio_file={ref!r} resolves to {resolved} against song directory "
            f"{song_dir}."
        )
    return resolved, None


def resolve_reversed_sample(
    conn: sqlite3.Connection,
    resolved: Path,
    *,
    where: str,
) -> tuple[Path | None, str | None]:
    """Resolve the file a ``reverse=1`` row actually plays: the pre-reversed
    derived asset for ``resolved``, or say why there is none.

    Returns ``(path, None)`` or ``(None, reason)``, the same shape
    :func:`resolve_authored_sample` answers in, because a caller treats the two
    identically — a row it cannot determine the file for is a row it refuses.

    Neither Live nor Simpler carries a reverse the wire could set, so the flag
    is materialized one step earlier: the sample is run through the ``reverse``
    transform and filed in the song's content-addressed derived cache, and the
    clip is created from THAT file. The address is a hash over the source's
    checksum and the chain, so the flag and the file cannot disagree — flip the
    flag and the path changes, which the ordinary re-pointed-``audio_file``
    reconcile below then acts on. A source the manifest does not record is
    still derivable: it is wrapped as an unmanifested source whose checksum is
    computed here, so a sample referenced straight out of ``assets/`` addresses
    exactly as an ingested one does.

    The render happens at PLAN time so the create carries a path that already
    exists — the same discipline the authored-sample resolve enforces — and the
    cache makes every push after the first a lookup. Nothing is sent to Live
    from here; the derived cache is local, regenerable and checked in.
    """
    song_dir = song_dir_for_conn(conn)
    if song_dir is None:
        return None, (
            f"{where} sets reverse=1, but this connection has no database file "
            "on disk, so there is no song directory to hold the derived cache "
            "the reversed file lives in. Open the song's DB through "
            "init_db(<song dir>/<slug>.db) and re-plan."
        )
    # Imported here rather than at module scope: reverse is the only thing in
    # this phase that needs the DSP stack, and a MIDI-only push should not pay
    # to import soundfile and numpy to plan notes.
    import soundfile as sf

    from hallucinote.assets import derived as derived_cache
    from hallucinote.assets import store, transforms
    from hallucinote.assets.types import Source

    try:
        source: Source | None = None
        for candidate in store.sources(song_dir):
            if same_file_path(candidate.path, resolved):
                source = candidate
                break
        if source is None:
            info = sf.info(str(resolved))
            source = Source(
                name=resolved.stem,
                path=resolved,
                checksum=store.file_checksum(resolved),
                sample_rate=int(info.samplerate),
                channels=int(info.channels),
                duration_s=float(info.duration),
            )
        # The transforms are frozen dataclasses, so their `kind` is read-only
        # while the `Transform` protocol declares it settable; mypy therefore
        # rejects any concrete transform where the protocol is expected. The
        # runtime check `derive` itself makes is structural and passes.
        derived = derived_cache.derive(
            source, (transforms.reverse(),), song_dir=song_dir,  # type: ignore[arg-type]
        )
    except (OSError, ValueError, sf.SoundFileError) as exc:
        return None, (
            f"{where} sets reverse=1, and the reversed file could not be "
            f"derived from {resolved}: {exc}"
        )
    return derived.path, None


def _audio_create_call(
    *,
    clip: sqlite3.Row,
    clip_id: str,
    track_at: int,
    clip_index: int,
    resolved: Path,
    replace: bool,
    purpose: str,
) -> ToolCall:
    """The session ``create(kind='audio')`` call, built one way for every
    branch that plans one.

    ``replace`` is the caller's decision about the slot: ``True`` where the
    slot's state is unknown or a scaffold clip may sit there (the MIDI
    create's posture), ``False`` where an explicit delete already emptied it
    and a slot found occupied is a delete that did not take — Live should say
    so rather than silently delete twice.
    """
    args: dict[str, Any] = {
        "action": "create",
        "location": "session",
        "kind": "audio",
        "track_index": track_at,
        "clip_index": clip_index,
        # ABSOLUTE by contract — Live resolves nothing, and the wire refuses
        # a relative path.
        "audio_path": str(resolved),
        "name": clip["name"],
    }
    if replace:
        args["replace"] = True
    return ToolCall(tool="ableton_clip", args=args, key=f"clip:{clip_id}", purpose=purpose)


def _recreate_audio_clip(
    plan: PushPlan,
    *,
    conn: sqlite3.Connection,
    clip: sqlite3.Row,
    clip_id: str,
    song_id: str,
    session_id: str,
    track_at: int,
    clip_at: int,
    resolved: Path,
    why: str,
) -> None:
    """Plan the destructive reconcile of a linked audio slot, as one sequence:
    ``delete`` → ``create`` → conform → re-emit every envelope the row hosts.

    ``Clip.file_path`` is read-only and ``create_audio_clip`` into an occupied
    slot is a hard error (``This clip slot already has a clip``), so a slot
    that must play a different file — or must become audio at all — is emptied
    first. The delete is its own planned call rather than a ``replace=True``
    on the create, so the destruction is visible in the plan and ordered
    before the create rather than hidden inside a handler.

    A recreate drops every envelope the old clip hosted (probe-confirmed:
    ``automation_envelope`` reads ``None`` after delete + create of the same
    file), so the ride the author wrote is written again, through the
    envelopes phase's own planner, onto the new clip — same slot, same link,
    so the address is known at plan time and nothing positional is guessed.
    The conform runs with no probe entry: the new clip is at Live's defaults
    whatever the old one held.

    Said on the operator channel as an alert, not buried in ``notes``: a clip
    the operator had in Live was deleted and rebuilt, and that is theirs to
    know even when it is exactly what the song asked for.
    """
    plan.alert(
        f"{why} Live's clip in slot {clip_at} on track {track_at} is DELETED "
        f"and recreated from {resolved.name}, then conformed and its "
        "envelopes re-emitted (a recreate drops every envelope the old clip "
        "hosted). Un-modelled Live-side state on the old clip — hand-placed "
        "warp markers — does not survive."
    )
    plan.add(ToolCall(
        tool="ableton_clip",
        args={
            "action": "delete",
            "location": "session",
            "track_index": track_at,
            "clip_index": clip_at,
        },
        # Ack-only (`_ACK_ONLY_KINDS`): the delete records no binding; the
        # create that follows re-records the clip's link under `clip:`.
        key=f"clip_delete:{clip_id}",
        purpose=(
            f"delete the clip in slot {clip_at} on track {track_at} so it can "
            f"be recreated from {resolved.name} (Clip.file_path is read-only)"
        ),
    ))
    # No `replace`: the delete above is the one destructive step.
    plan.add(_audio_create_call(
        clip=clip, clip_id=clip_id, track_at=track_at, clip_index=clip_at,
        resolved=resolved, replace=False,
        purpose=(
            f"recreate session audio clip in slot {clip_at} on track "
            f"{track_at} from {resolved.name}"
        ),
    ))
    for call in _audio_conform_calls(
        clip, clip_id=clip_id, track_at=track_at, clip_index=clip_at,
        live_entry=None,
    ):
        plan.add(call)
    envelopes = plan_push_envelopes_for_clip(
        conn, song_id=song_id, session_id=session_id, clip_id=clip_id,
    )
    plan.absorb(envelopes)
    if envelopes.calls:
        plan.warn(
            f"clip {clip_id}: re-emitted {len(envelopes.calls)} envelope(s) "
            f"onto the recreated clip in slot {clip_at}"
        )


def _plan_push_audio_clip(
    plan: PushPlan,
    *,
    conn: sqlite3.Connection,
    clip: sqlite3.Row,
    clip_id: str,
    song_id: str,
    session_id: str,
    track_at: int,
    clip_at: int | None,
    live_session_clips_by_track: dict[int, list[dict[str, Any]]] | None,
) -> None:
    """Plan the materialization of one ``kind='audio'`` row (R1.1).

    Four outcomes, and which one a row gets is decided here rather than at
    dispatch:

    * **Not linked** → ``create(kind='audio', audio_path=<absolute>)`` plus
      every authored conform property.
    * **Linked and playing the file the row names** → the conform properties
      only, and (with a probe) only the ones Live does not already hold.
    * **Linked, but Live's slot plays a different file or holds a MIDI clip**
      → the destructive reconcile of :func:`_recreate_audio_clip`: delete,
      create, conform, re-emit the envelopes the row hosts. Only a
      successful probe reaches this — it is the one branch that destroys.
    * **Anything that cannot be materialized without guessing** → no calls and
      a :meth:`PushPlan.blocked` reason that says what is unknown.

    The existence check happens BEFORE the create is planned. A clip that
    pushes and then plays silence is a phase reporting OK without having
    determined its state, which is precisely what the sync boundary contract
    forbids.

    A ``reverse=1`` row is resolved to its pre-reversed derived file first
    (:func:`resolve_reversed_sample`), so every outcome above is decided
    against the file the clip really plays.
    """
    slot = clip["slot"]
    where = f"clip {clip_id} ({clip['name']!r}, slot {slot})"

    resolved, refusal = resolve_authored_sample(conn, clip, where=where)
    if resolved is None:
        plan.blocked(
            f"{refusal} NO create was planned — pushing it would put a clip in "
            "Live that plays silence, which is a phase reporting OK without "
            "having determined its state. Put the file there (canonically "
            "under assets/) or fix the reference, then re-push."
        )
        return

    if clip["reverse"]:
        # From here on `resolved` is the reversed file, so every branch below
        # — create, conform, the changed-file recreate — works on the file the
        # clip really plays. A row whose reversed file cannot be derived is
        # refused rather than placed forward: a clip that pushes clean and then
        # plays the line the wrong way round is the silent-wrong-audio failure.
        resolved, refusal = resolve_reversed_sample(conn, resolved, where=where)
        if resolved is None:
            plan.blocked(
                f"{refusal} NO create was planned — placing it FORWARD would "
                "report OK over audio the author did not write. Fix the source "
                "(a manifest checksum that no longer matches its file is the "
                "usual cause), then re-push."
            )
            return

    if clip_at is None:
        # The slot may hold a scaffold clip; replace makes the create
        # state-independent, the same posture the MIDI create takes. Pull now
        # writes the link for every clip it ingests, so an unlinked row whose
        # slot is nevertheless occupied means one of two things: the clip in
        # Live was placed by hand and never pulled, or the link that once
        # bound them is gone. Either way the row wins and the slot is rebuilt
        # from it, losing hand-set warp markers — the DB models warp mode, not
        # markers. That cost is said on the operator channel whenever the
        # probe shows the slot occupied, because `replace=True` hides the
        # delete inside the handler and nothing else in the run would name it.
        occupant = _live_session_entry(
            live_session_clips_by_track, track_at=track_at, clip_index=slot,
        )
        if occupant is not None and occupant is not PROBE_UNKNOWN:
            held = occupant.get("name") or "an unnamed clip"
            held_file = occupant.get("file_path")
            playing = f" playing {Path(held_file).name}" if held_file else ""
            plan.alert(
                f"clip {clip_id} ('{clip['name']}', slot {slot}): the row has "
                f"no link, but Live's slot {slot} on track {track_at} already "
                f"holds '{held}'{playing} — a clip placed by hand and never "
                "pulled (pull links what it ingests), or a link that has gone "
                "stale. That clip is DELETED and rebuilt from "
                f"{resolved.name} (the create replaces the slot), then "
                "conformed from the row. Un-modelled Live-side state on the "
                "old clip — hand-placed warp markers — does not survive. Pull "
                "the set first if that clip is the one you meant to keep."
            )
        plan.add(_audio_create_call(
            clip=clip, clip_id=clip_id, track_at=track_at, clip_index=slot,
            resolved=resolved, replace=True,
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
        plan.add(_audio_create_call(
            clip=clip, clip_id=clip_id, track_at=track_at, clip_index=clip_at,
            resolved=resolved, replace=True,
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
        # The DB says audio; Live's slot holds a MIDI clip. The DB is the
        # projection's author, exactly as the MIDI path's `replace=True`
        # already treats an occupied slot — so the slot becomes what the row
        # says, by the one route Live allows.
        _recreate_audio_clip(
            plan, conn=conn, clip=clip, clip_id=clip_id, song_id=song_id,
            session_id=session_id, track_at=track_at, clip_at=clip_at,
            resolved=resolved,
            why=(
                f"{where} is linked to Live slot {clip_at} on track "
                f"{track_at}, and the probe says that slot holds a clip that "
                "is NOT audio."
            ),
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
        _recreate_audio_clip(
            plan, conn=conn, clip=clip, clip_id=clip_id, song_id=song_id,
            session_id=session_id, track_at=track_at, clip_at=clip_at,
            resolved=resolved,
            why=(
                f"{where}: the row's audio_file CHANGED — Live's clip plays "
                f"{live_file!r}, the row now authors {str(resolved)!r}, and "
                "Live's Clip.file_path is read-only."
            ),
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
    (gain, transpose, warp / warp_mode, markers). A linked clip whose file
    has changed underneath the row is a delete-and-recreate that re-emits
    the envelopes the row hosts (``Clip.file_path`` is read-only, and a
    recreate drops them — :func:`_recreate_audio_clip`). Two things it
    refuses rather than guesses, each with a :meth:`PushPlan.blocked` reason:
    a sample that is not on disk, and a ``reverse=1`` row whose reversed file
    cannot be derived.

    ``live_session_clips_by_track`` is the per-track Live session-clip
    inventory (``{track_index: [{clip_index, is_audio, file_path, gain, …}]}``
    — the shape ``ableton_clip(action='list', location='session')`` returns,
    empty slots dropped; ``push_cli._probe_live_session_clips_via_mcp``
    produces it). It answers two questions no DB read can: which file a linked
    clip actually plays, and which conform values Live already holds. With it,
    a second push of an unchanged song plans NOTHING, and a re-pointed
    ``audio_file`` is detected and recreated. Without it the planner still
    materializes and conforms — it just cannot detect a re-pointed
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
            song_id=track_row["song_id"],
            session_id=session_id,
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
        plan.absorb(sub, note_prefix=f"[{c['name']}]")
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
