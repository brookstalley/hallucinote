"""Imperative handlers for ``ableton_clip`` actions.

Clip operations branch on ``location`` (``session`` vs ``arrangement``) because
the Live Object Model exposes the two contexts through different navigation
paths:

  - Session clips live at ``song.tracks[t].clip_slots[s].clip``. The slot
    always exists; ``.clip`` is ``None`` for empty slots. Lifecycle methods
    live on the clip_slot (``create_clip(length)`` for MIDI,
    ``create_audio_clip(path)`` for audio, ``delete_clip()``).
  - Arrangement clips live in ``song.tracks[t].arrangement_clips`` — a list of
    just the populated clips on the timeline. Lifecycle goes through the
    track itself (``create_midi_clip(start, length)`` /
    ``create_audio_clip(path, start)`` / ``delete_clip``).

Indices are 1-based on the wire and translated to 0-based when accessing the
Live API.

Note operations: ``replace_notes`` does a true total-replace — a full-extent
``remove_notes_extended(0, 128, 0, length)`` clear *then* ``clip.set_notes``,
because Live's ``set_notes`` alone does NOT reliably clear pre-existing notes
on arrangement clips (ARR-ORPHAN). It reads the resulting set back and returns
``notes_present`` so a caller can detect orphan-survival. The action name is
renamed (from ``add_notes_to_clip`` on the legacy fork) to make the semantic
visible. Per-note addressing (true append, in-place mutation) waits on MCP
gap #4 — see ``handlers/note.py`` for those stubs.
"""
from __future__ import annotations

import os
from collections import Counter
from typing import Any, Iterable

from ..dispatcher import LiveContext
from ._arrangement_latch import (
    CLICK_BACK_TO_ARRANGEMENT,
    OVERRIDE_DESCRIPTION,
    is_overridden,
)


_LOCATION_ENUM = ("session", "arrangement")


def _check_location(location: str) -> None:
    if location not in _LOCATION_ENUM:
        raise ValueError(
            f"location must be one of {list(_LOCATION_ENUM)}, got {location!r}"
        )


def _resolve_track(context: LiveContext, track_index: int) -> Any:
    song = context.song
    if track_index < 1 or track_index > len(song.tracks):
        raise IndexError(
            f"track_index {track_index} out of range [1, {len(song.tracks)}]"
        )
    return song.tracks[track_index - 1]


# ---------------------------------------------------------------------------
# Audio-clip read surface
# ---------------------------------------------------------------------------


def _is_audio_clip(clip: Any) -> bool:
    """True when this clip plays a sample rather than notes.

    ``is_audio_clip`` is the direct discriminator and the mirror of the
    ``is_midi_clip`` guard the note reader already uses. It is read first;
    a wrapper that exposes only the MIDI half still answers correctly
    through the fallback, and a clip exposing neither reads as MIDI (the
    conservative answer — the audio fields are then simply absent rather
    than half-populated with defaults).
    """
    is_audio = getattr(clip, "is_audio_clip", None)
    if is_audio is not None:
        return bool(is_audio)
    return not bool(getattr(clip, "is_midi_clip", True))


def _opt_float(value: Any) -> float | None:
    return None if value is None else float(value)


def _opt_int(value: Any) -> int | None:
    return None if value is None else int(value)


def _audio_clip_fields(clip: Any) -> dict[str, Any]:
    """The conform surface of an audio clip: what plays, and how.

    These eight keys are the read half of what ``set_property`` writes, so
    a clip a human dragged into Live can be ingested and pushed back
    unchanged. They are emitted ONLY for audio clips — a MIDI clip omits
    every one of them rather than reporting them null, so an absent
    ``file_path`` always means "not an audio clip" and never "an audio clip
    whose file we could not determine".

    ``start_marker`` / ``end_marker`` carry Live's dual unit: BEATS when
    ``warping`` is true, SECONDS when it is false. ``warping`` travels in
    the same dict precisely so a reader can tell which it is holding.

    There is no reverse field: Live exposes no reverse on a Clip at all
    (`lom-audio-clip-surface.md` §4), so reporting one would invent state.
    """
    return {
        "file_path": (
            None if getattr(clip, "file_path", None) is None
            else str(clip.file_path)
        ),
        "gain": _opt_float(getattr(clip, "gain", None)),
        "pitch_coarse": _opt_int(getattr(clip, "pitch_coarse", None)),
        "pitch_fine": _opt_float(getattr(clip, "pitch_fine", None)),
        "warping": (
            None if getattr(clip, "warping", None) is None
            else bool(clip.warping)
        ),
        "warp_mode": _opt_int(getattr(clip, "warp_mode", None)),
        "start_marker": _opt_float(getattr(clip, "start_marker", None)),
        "end_marker": _opt_float(getattr(clip, "end_marker", None)),
    }


def list_handler(
    context: LiveContext,
    *,
    track_index: int,
    location: str,
) -> dict[str, Any]:
    """Per-track clip inventory.

    Session: returns every slot (populated AND empty); the slot's 1-based
    position doubles as ``clip_index`` for writes. Empty slots carry
    ``{clip_index, empty: True}``; populated slots add ``name``, ``length``
    and ``is_audio``.

    Arrangement: returns every placed clip with ``arrangement_clip_index``
    (1-based, ordered by ``track.arrangement_clips`` — Live's ordering),
    plus ``name``, ``start_beats``, ``length``, ``muted``, ``note_count``
    and ``is_audio``.
    ``note_count`` distinguishes an empty placement from a full one (a long clip
    spanning the song looks identical to an empty one on name/length alone — the
    "track shows no events" debugging question); it is ``None`` for audio clips
    (notes are MIDI-only). There are no "empty" arrangement positions —
    ``arrangement_clips`` is dense.

    **Audio clips report what they play.** In either location, a clip whose
    ``is_audio`` is true also carries the conform surface
    :func:`_audio_clip_fields` returns — ``file_path``, ``gain``,
    ``pitch_coarse``, ``pitch_fine``, ``warping``, ``warp_mode``,
    ``start_marker``, ``end_marker``. A MIDI clip omits those keys
    entirely; that asymmetry is the contract, because a null-filled MIDI
    entry would read as an audio clip whose file could not be determined.
    This is the surface a pull ingests a hand-dragged clip through.

    Index naming follows ``docs/terminology.md``: session uses
    ``clip_index`` (slot), arrangement uses the fully-qualified
    ``arrangement_clip_index`` to keep the two senses unconfused at the
    response shape.

    Beats are returned raw; the Hallucinote sync layer converts to
    bar-based song positions using the song's time-signature map.
    """
    _check_location(location)
    track = _resolve_track(context, track_index)
    clips_out: list[dict[str, Any]] = []
    if location == "session":
        for i, slot in enumerate(track.clip_slots, start=1):
            clip = slot.clip
            if clip is None:
                clips_out.append({"clip_index": i, "empty": True})
            else:
                is_audio = _is_audio_clip(clip)
                entry: dict[str, Any] = {
                    "clip_index": i,
                    "empty": False,
                    "name": clip.name,
                    "length": float(clip.length),
                    "is_audio": is_audio,
                }
                if is_audio:
                    entry.update(_audio_clip_fields(clip))
                clips_out.append(entry)
    else:
        for i, clip in enumerate(track.arrangement_clips, start=1):
            # note_count answers the "no events" debugging question that a
            # bare name/length can't (an empty long clip looks like a full one).
            # MIDI-only — get_notes_extended raises on audio clips, so guard on
            # is_midi_clip and report None for audio (mirrors note.py's reader).
            note_count = (
                len(clip.get_notes_extended(0, 128, 0.0, float(clip.length)))
                if clip.is_midi_clip
                else None
            )
            is_audio = _is_audio_clip(clip)
            entry = {
                "arrangement_clip_index": i,
                "name": clip.name,
                "start_beats": float(clip.start_time),
                "length": float(clip.length),
                "muted": bool(clip.muted),
                "note_count": note_count,
                "is_audio": is_audio,
            }
            if is_audio:
                entry.update(_audio_clip_fields(clip))
            clips_out.append(entry)
    return {
        "track_index": track_index,
        "location": location,
        "clips": clips_out,
    }


def _resolve_clip(context: LiveContext, *, track_index: int, location: str, clip_index: int) -> Any:
    """Return the Live Clip object addressed by (track_index, location, clip_index).

    Raises ``IndexError`` with a teaching message if the address points at an
    empty slot (session) or out of range (arrangement).
    """
    _check_location(location)
    track = _resolve_track(context, track_index)
    if location == "session":
        slots = track.clip_slots
        if clip_index < 1 or clip_index > len(slots):
            raise IndexError(
                f"clip_index {clip_index} out of range [1, {len(slots)}] "
                f"for session view of track {track_index}"
            )
        clip = slots[clip_index - 1].clip
        if clip is None:
            raise IndexError(
                f"session slot {clip_index} on track {track_index} is empty; "
                f"create a clip first with ableton_clip(action='create', "
                f"location='session', track_index={track_index}, "
                f"clip_index={clip_index}, length=...)"
            )
        return clip
    # arrangement
    arr_clips = track.arrangement_clips
    if clip_index < 1 or clip_index > len(arr_clips):
        raise IndexError(
            f"clip_index {clip_index} out of range [1, {len(arr_clips)}] "
            f"for arrangement view of track {track_index}"
        )
    return arr_clips[clip_index - 1]


# ---------------------------------------------------------------------------
# Note marshaling — MCP wire shape <-> Live's (pitch, time, duration, velocity, mute)
# ---------------------------------------------------------------------------


# Live's clip.set_notes() takes a tuple of 5-tuples:
#   (pitch: int 0-127, start_beats: float, duration_beats: float,
#    velocity: int 1-127, mute: bool)
# Our wire shape accepts both 'start_time' / 'duration' (Hallucinote naming)
# and 'start' / 'length' (some older docs) — we coerce here to be agent-tolerant
# while keeping the Live call site canonical.
_NOTE_START_KEYS = ("start_time", "start")
_NOTE_DURATION_KEYS = ("duration", "length")


def _coerce_note(note: dict[str, Any]) -> tuple[int, float, float, int, bool]:
    if "pitch" not in note:
        raise ValueError(f"note missing required field 'pitch': {note!r}")
    pitch = int(note["pitch"])
    if pitch < 0 or pitch > 127:
        raise ValueError(f"note pitch {pitch} out of MIDI range [0, 127]")
    start: float | None = None
    for k in _NOTE_START_KEYS:
        if k in note:
            start = float(note[k])
            break
    if start is None:
        raise ValueError(
            f"note missing required field 'start_time' (or 'start'): {note!r}"
        )
    duration: float | None = None
    for k in _NOTE_DURATION_KEYS:
        if k in note:
            duration = float(note[k])
            break
    if duration is None:
        raise ValueError(
            f"note missing required field 'duration' (or 'length'): {note!r}"
        )
    if duration <= 0:
        raise ValueError(f"note duration {duration} must be > 0")
    velocity = int(note.get("velocity", 100))
    if velocity < 1 or velocity > 127:
        raise ValueError(f"note velocity {velocity} out of range [1, 127]")
    mute = bool(note.get("mute", False))
    return pitch, start, duration, velocity, mute


def _coerce_notes(notes: Iterable[dict[str, Any]]) -> tuple[tuple[int, float, float, int, bool], ...]:
    return tuple(_coerce_note(n) for n in notes)


# ---------------------------------------------------------------------------
# Inline-notes soft cap (build-plan B4)
# ---------------------------------------------------------------------------
#
# The per-call ``notes=[…]`` channel (``create`` + ``replace_notes``) is the
# right tool for trivial interactive edits. Above this many notes it costs
# agent context the DB path avoids and bypasses the Hallucinote DB (the next
# full push overwrites a clip authored only inline). The guardrail WARNS, never
# blocks — small edits stay frictionless; large writes get pointed at the
# author-as-code loop (build.py + ``push_cli push-notes``), where the array
# never enters the agent's tool-use channel.
#
# Both note-accepting handlers route through ``_inline_notes_warning`` so they
# emit the identical guidance at the identical threshold — parity locked in
# ``tests/unit/test_actions_clip.py``. The agent-facing mirror is
# ``ableton://guides/conventions`` ("Inline note arrays: soft cap"); there is
# no domain-side mirror because no domain entry point inlines an agent-supplied
# note array — domain writes read notes from build.py code through the mutators,
# which is exactly the path this warning points TO, not a parallel one.
INLINE_NOTES_SOFT_CAP = 32


def _inline_notes_warning(note_count: int) -> str | None:
    """Teaching warning when an inline note write exceeds the soft cap, else ``None``.

    Non-blocking: the clip is still written. Shared by ``create_handler`` and
    ``replace_notes_handler`` so the two inline-note actions stay in parity.
    """
    if note_count <= INLINE_NOTES_SOFT_CAP:
        return None
    return (
        f"{note_count} notes written inline (soft cap {INLINE_NOTES_SOFT_CAP}). "
        "Inline note arrays cost agent context and bypass the Hallucinote DB — "
        "the next full push overwrites notes authored only this way. For a part "
        "this size, author the notes as code in the song's build.py "
        "(hallucinote.generators) and materialize with "
        "`push_cli push-notes --changed`, where the array never enters the "
        "agent's context. See the /compose-part skill and "
        'docs/song-authoring-conventions.md "Authoring API".'
    )


# ---------------------------------------------------------------------------
# Audio-clip creation
# ---------------------------------------------------------------------------
#
# Live 12.2 added ``ClipSlot.create_audio_clip(path)`` and
# ``Track.create_audio_clip(path, start_beats)``; 12.4 fixed a crash in the
# arrangement one, which makes 12.4 the floor. Both were executed against a
# running Live 12.4.1 and their refusals recorded verbatim
# (``docs/research/audio-first-class/lom-probe-results.md`` rows 1a-1c), which
# is where the two message fragments below come from.
#
# Note the argument ORDER: the audio calls take (path, position) while
# ``create_midi_clip`` takes (position, length). An audio clip's length is
# the file's, not the caller's.

# Fragments of Live's own refusals, matched case-insensitively so a wording
# tweak in a future Live build degrades to the raw error rather than to a
# wrong diagnosis.
_LIVE_WRONG_TRACK_KIND = "can only be created on audio tracks"
_LIVE_BAD_AUDIO_PATH = "valid audio file"
# Live checks absoluteness BEFORE existence, with its own string (probe row 17:
# `ValueError: Please provide an absolute path`). The handler refuses a
# relative path itself before the call, so this arrives only when Live's idea
# of "absolute" is stricter than `os.path.isabs` — a cross-platform path form,
# a future Live build — and then it must teach the same fix, not surface as a
# bare ValueError that reads like a corrupt file.
_LIVE_RELATIVE_AUDIO_PATH = "provide an absolute path"


def _create_audio_clip(
    create_fn: Any,
    args: tuple[Any, ...],
    *,
    track_index: int,
    audio_path: str,
) -> Any:
    """Call Live's ``create_audio_clip`` and teach its three refusals.

    Live raises a bare ``RuntimeError`` for the wrong track kind and a bare
    ``ValueError`` for a path it will not load — and a different
    ``ValueError`` for a path it does not consider absolute, checked before
    the file is looked at. None of them says what to do next. Anything else
    propagates untouched — a message we do not recognize must not be
    re-labelled as one we do.
    """
    try:
        return create_fn(*args)
    except RuntimeError as exc:
        if _LIVE_WRONG_TRACK_KIND in str(exc).lower():
            raise ValueError(
                f"create: track {track_index} is not an audio track, and "
                f"Live creates audio clips only on audio tracks. Make the "
                f"host track with ableton_track(action='create', "
                f"kind='audio'), or address an existing audio track. "
                f"(Live said: {exc})"
            ) from exc
        raise
    except ValueError as exc:
        if _LIVE_RELATIVE_AUDIO_PATH in str(exc).lower():
            raise ValueError(
                f"create: Live does not accept {audio_path!r} as an absolute "
                f"path. Live resolves nothing — resolve a song-relative "
                f"reference with hallucinote.paths.resolve_audio_path("
                f"song_dir, ref) and pass the result. (Live said: {exc})"
            ) from exc
        if _LIVE_BAD_AUDIO_PATH in str(exc).lower():
            raise ValueError(
                f"create: Live will not load {audio_path!r}. It reports a "
                f"file that is missing and a file it cannot decode with the "
                f"same refusal, so check both: the absolute path exists, and "
                f"the format is one Live reads (wav / aiff / flac / mp3 / "
                f"ogg). (Live said: {exc})"
            ) from exc
        raise


def _definite_track_kind(track: Any) -> str | None:
    """Return ``"midi"`` / ``"audio"`` only when Live states the kind, else None.

    Live types a track by its input side: a MIDI track reports
    ``has_midi_input`` true and ``has_audio_input`` false, an audio track the
    reverse (lom-probe-results row "describe Track"). This is deliberately
    NOT ``handlers/track.py``'s ``_kind_of``, which must always produce a
    label for the wire and so falls back to ``"midi"`` when it can read
    nothing. A fallback is exactly wrong here: the caller of this function
    refuses a create on the strength of the answer, and guessing "midi" for a
    track whose kind is unreadable would refuse an audio create that would
    have succeeded. Unknown must stay unknown.

    A group track (``is_foldable``) is reported unknown too: its input flags
    describe the tracks folded into it, not a slot that could hold a clip.
    """
    if getattr(track, "is_foldable", False):
        return None
    has_midi = getattr(track, "has_midi_input", None)
    if has_midi is True:
        return "midi"
    if has_midi is False:
        return "audio"
    if getattr(track, "has_audio_input", None) is True:
        return "audio"
    return None


def _check_replace_track_kind(
    track: Any, *, track_index: int, kind: str, clip_index: int
) -> None:
    """Refuse a wrong-kind session replace BEFORE anything is deleted.

    A slot holds at most one clip, so ``replace=True`` has to delete before it
    creates — and Live refuses a wrong-kind create only after that point, when
    the previous clip is already gone and unrecoverable through this bridge.
    Live's own track typing is readable in advance, so the one case that is
    certain to fail is caught while the clip is still there.

    Silent when the track's kind cannot be read: a refusal on a guess would
    block a create that would have worked. Everything this cannot foresee — a
    path Live will not load, a build that refuses for its own reasons — still
    falls through to the post-delete disclosure.
    """
    actual = _definite_track_kind(track)
    if actual is None or actual == kind:
        return
    if kind == "audio":
        host, rule = "a MIDI track", "audio clips only on audio tracks"
    else:
        host, rule = "an audio track", "MIDI clips only on MIDI tracks"
    raise ValueError(
        f"create: track {track_index} is {host}, and Live creates {rule}. "
        f"Nothing was deleted — the clip in session slot {clip_index} is "
        f"still there. Make the host track with ableton_track("
        f"action='create', kind={kind!r}), or address a track that already "
        f"is one."
    )


def _locate_created_arrangement_clip(
    track: Any, *, start_beats: float, before_starts: Counter[float]
) -> tuple[Any, int]:
    """Return ``(clip, 1-based index)`` for the clip just created at ``start_beats``.

    Live gives the create call no usable handle back through the Remote
    Script (and re-wraps its API objects on every property access, so
    identity comparison silently fails — B-1). Position is the handle:
    ``arrangement_clips`` is ordered by ``start_time``, so we look for a
    clip there.

    ``before_starts`` is a multiset of the start times present BEFORE the
    call, which is what makes this correct when the new clip lands on top
    of one that was already there: skip as many clips at this position as
    were there before, and the next one is ours. Matching on length instead
    would work for MIDI and fail for audio, whose length comes from the
    file and is not known until after the call.
    """
    key = round(float(start_beats), 6)
    to_skip = before_starts.get(key, 0)
    for i, c in enumerate(track.arrangement_clips, start=1):
        if abs(float(c.start_time) - float(start_beats)) < 1e-6:
            if to_skip:
                to_skip -= 1
                continue
            return c, i
    raise RuntimeError(
        f"create: no new arrangement clip appeared at beat {start_beats} — "
        f"Live accepted the call but the clip is not in arrangement_clips. "
        f"The post-create ordering or the create call itself may have "
        f"changed in this Live build."
    )


# ---------------------------------------------------------------------------
# create / delete / rename
# ---------------------------------------------------------------------------


def create_handler(
    context: LiveContext,
    *,
    track_index: int,
    location: str,
    kind: str,
    length: float | None = None,
    clip_index: int | None = None,
    start_beats: float | None = None,
    name: str | None = None,
    notes: list[dict[str, Any]] | None = None,
    audio_path: str | None = None,
    replace: bool = False,
) -> dict[str, Any]:
    """Create a clip in session or arrangement view.

    Branches on ``location``:

    - **session**: ``clip_index`` (1-based slot) is required. Calls
      ``clip_slot.create_clip(length)`` for MIDI and
      ``clip_slot.create_audio_clip(audio_path)`` for audio. By default
      errors if the slot already holds a clip; pass ``replace=True`` to
      delete-then-create atomically (the most common Hallucinote iteration
      shape — gap #2's resolution path). A replace onto the wrong track
      kind is refused BEFORE the delete, so the existing clip survives a
      create Live was always going to reject.
    - **arrangement**: ``start_beats`` is required (Live counts arrangement
      time in beats). The Hallucinote planner converts bar-based song
      positions to beats using its time-signature map before emit; the MCP
      layer stays meter-agnostic. Calls
      ``track.create_midi_clip(start_beats, length)`` or
      ``track.create_audio_clip(audio_path, start_beats)``.

    The two kinds take different inputs, and the difference is Live's, not
    ours:

    - **MIDI** needs ``length`` (beats), and takes optional ``notes``,
      written via ``clip.set_notes(...)`` after the clip exists — a single
      round-trip for the common "create-and-populate" iteration pattern.
    - **audio** needs ``audio_path``, an ABSOLUTE path to a file Live can
      read. Live resolves nothing itself; a song-relative reference is
      resolved engine-side through ``paths.resolve_audio_path`` before the
      call reaches this handler. The clip's length comes from the file
      (warped to the song tempo), so a ``length`` passed alongside is
      ignored and said so in the result; trim with ``set_property``
      ``start_marker`` / ``end_marker``. ``notes`` are refused — an audio
      clip has no note array.

    An audio create returns the created clip's ``file_path`` read back off
    Live, which is the evidence that a file actually loaded.
    """
    _check_location(location)
    if kind not in ("midi", "audio"):
        raise ValueError(f"kind must be 'midi' or 'audio', got {kind!r}")
    if length is not None and length <= 0:
        raise ValueError(f"length {length} must be > 0")
    # Each kind's own required input, bound once where it is known present:
    # the MIDI path never reads the path, and the audio path never reads the
    # length (Live's create_audio_clip takes no length at all).
    midi_length = 0.0
    abs_audio_path = ""
    if kind == "midi":
        if length is None:
            raise ValueError(
                "create: kind='midi' requires length (clip length in beats, "
                "> 0). Only an audio clip takes its length from a file."
            )
        midi_length = float(length)
        if audio_path is not None:
            raise ValueError(
                f"create: audio_path was given for kind='midi'. A MIDI clip "
                f"plays notes, not a file — pass kind='audio' to load "
                f"{audio_path!r}."
            )
    else:
        if audio_path is None:
            raise ValueError(
                "create: kind='audio' requires audio_path — an ABSOLUTE path "
                "to an audio file Live can read. Live has no way to create "
                "an empty audio clip; the file is what the clip is."
            )
        if not os.path.isabs(audio_path):
            raise ValueError(
                f"create: audio_path {audio_path!r} is not absolute. Live "
                f"resolves nothing — resolve a song-relative reference with "
                f"hallucinote.paths.resolve_audio_path(song_dir, ref) before "
                f"the call."
            )
        if notes is not None:
            raise ValueError(
                "create: notes were given for kind='audio'. An audio clip "
                "has no note array — conform it with set_property (gain, "
                "pitch, pitch_fine, warp, warp_mode, start_marker, "
                "end_marker) instead."
            )
        abs_audio_path = audio_path

    if location == "session":
        if clip_index is None:
            raise ValueError(
                "create: location='session' requires clip_index "
                "(the 1-based slot number)"
            )
        track = _resolve_track(context, track_index)
        slots = track.clip_slots
        if clip_index < 1 or clip_index > len(slots):
            raise IndexError(
                f"clip_index {clip_index} out of range [1, {len(slots)}] "
                f"for session view of track {track_index}"
            )
        slot = slots[clip_index - 1]
        replaced_existing = False
        if slot.clip is not None:
            if not replace:
                raise ValueError(
                    f"session slot {clip_index} on track {track_index} is "
                    f"already occupied; pass replace=True to delete and "
                    f"recreate atomically"
                )
            _check_replace_track_kind(
                track,
                track_index=track_index,
                kind=kind,
                clip_index=clip_index,
            )
            slot.delete_clip()
            replaced_existing = True
        # The pre-check above rules out the one refusal Live's own track typing
        # can foresee. The rest it cannot: a slot holds at most one clip, so
        # replace=True must delete BEFORE it creates, and a path Live will not
        # load is refused only after that point, when the old clip is already
        # gone. Nothing here can give it back, so the one thing owed is that
        # the caller LEARNS it — a bare "does not point to a valid audio file"
        # reads like a rejected call that changed nothing, which is the
        # reported-OK-without-determining-state failure wearing an error's
        # clothes.
        try:
            if kind == "audio":
                create_fn = getattr(slot, "create_audio_clip", None)
                if create_fn is None:
                    raise NotImplementedError(
                        f"the clip slot at (track={track_index}, session, "
                        f"{clip_index}) does not expose create_audio_clip. That "
                        f"call landed in Live 12.2 and Live 12.4 is this "
                        f"project's floor — upgrade Live, or drag the file into "
                        f"the slot from Live's browser by hand."
                    )
                _create_audio_clip(
                    create_fn,
                    (abs_audio_path,),
                    track_index=track_index,
                    audio_path=abs_audio_path,
                )
            else:
                slot.create_clip(midi_length)
        except Exception as exc:
            if not replaced_existing:
                raise
            message = (
                f"{exc} — NOTE: replace=True had already deleted the clip that "
                f"was in session slot {clip_index} on track {track_index}, so "
                f"that slot is now EMPTY. The previous clip is not recoverable "
                f"through this bridge; undo in Live restores it."
            )
            # Preserve the original type where it can carry a plain message, so
            # a caller catching ValueError still catches one. Not every
            # exception's __init__ takes a single string, though, and this is
            # the ONE path where a raise-inside-the-handler would be worst: the
            # user's clip is already deleted, and a TypeError here would lose
            # both the original error and the disclosure. So the fallback is
            # unconditional rather than a type whitelist.
            try:
                raise type(exc)(message) from exc
            except TypeError:
                raise RuntimeError(message) from exc
        clip = slot.clip
        if clip is None:
            raise RuntimeError(
                f"create: the slot at (track={track_index}, session, "
                f"{clip_index}) is still empty after Live accepted the "
                f"create call"
            )
    else:
        # arrangement
        if start_beats is None:
            raise ValueError(
                "create: location='arrangement' requires start_beats "
                "(float, >= 0). The Hallucinote planner converts bar-based "
                "song positions to beats via the song's time-signature map "
                "before emit; MCP stays meter-agnostic."
            )
        if start_beats < 0:
            raise ValueError(f"start_beats {start_beats} must be >= 0")
        track = _resolve_track(context, track_index)
        sb = float(start_beats)
        # Snapshot positions before the call so the new clip can be told
        # apart from one that was already sitting at this beat.
        before_starts: Counter[float] = Counter(
            round(float(c.start_time), 6) for c in track.arrangement_clips
        )
        if kind == "midi":
            create_fn = getattr(track, "create_midi_clip", None)
            if create_fn is None:
                raise NotImplementedError(
                    f"track {track_index} does not expose create_midi_clip "
                    f"(not a MIDI track, or older Live build)"
                )
            create_fn(sb, midi_length)
        else:
            create_fn = getattr(track, "create_audio_clip", None)
            if create_fn is None:
                raise NotImplementedError(
                    f"track {track_index} does not expose create_audio_clip. "
                    f"That call landed in Live 12.2 (12.4 fixed the "
                    f"arrangement case and is this project's floor) and "
                    f"exists only on audio tracks."
                )
            # (path, position) — the mirror image of create_midi_clip's
            # (position, length), because the file supplies the length.
            _create_audio_clip(
                create_fn,
                (abs_audio_path, sb),
                track_index=track_index,
                audio_path=abs_audio_path,
            )
        clip, arrangement_clip_index = _locate_created_arrangement_clip(
            track, start_beats=sb, before_starts=before_starts
        )

    if name:
        clip.name = name
    if notes is not None:
        clip.set_notes(_coerce_notes(notes))

    # Result shape: report the resolved 1-based clip_index where applicable,
    # plus the clip's name and (for arrangement) its start_beats.
    result: dict[str, Any] = {
        "track_index": track_index,
        "location": location,
        "kind": kind,
        "name": clip.name,
        "length": float(clip.length),
    }
    if location == "session":
        result["clip_index"] = clip_index
    else:
        # The result field is `arrangement_clip_index` (not `clip_index`) so
        # the Hallucinote apply layer's `_LINK_KINDS["arrangement_clip"]`
        # can read it to record the `ableton_links` binding. It comes from
        # the same positional resolution that found the clip — Live re-wraps
        # its API objects on every property access, so an identity scan
        # (``c is clip``) silently finds nothing and the field goes missing.
        result["arrangement_clip_index"] = arrangement_clip_index
        result["start_beats"] = float(start_beats) if start_beats is not None else None
    if kind == "audio":
        # Read back what Live actually loaded — the evidence that the file
        # is in the clip, not merely that the call returned.
        loaded = getattr(clip, "file_path", None)
        result["file_path"] = str(loaded) if loaded is not None else None
        if length is not None:
            result["warning"] = (
                f"length={length} was ignored: an audio clip's length comes "
                f"from its file (warped to the song tempo), and Live's "
                f"create_audio_clip takes no length. The clip is "
                f"{float(clip.length)} beats. Trim it with "
                f"ableton_clip(action='set_property', "
                f"property='start_marker'|'end_marker', ...)."
            )
    if notes is not None:
        result["notes_written"] = len(notes)
        warning = _inline_notes_warning(len(notes))
        if warning:
            result["warning"] = warning
    return result


def delete_handler(
    context: LiveContext,
    *,
    track_index: int,
    location: str,
    clip_index: int,
) -> dict[str, Any]:
    """Delete a clip.

    Session: ``clip_slot.delete_clip()`` clears the slot but keeps the slot.
    Arrangement: the track's ``delete_clip(clip)`` method removes the clip
    object; subsequent arrangement_clips indices shift.
    """
    _check_location(location)
    if location == "session":
        track = _resolve_track(context, track_index)
        slots = track.clip_slots
        if clip_index < 1 or clip_index > len(slots):
            raise IndexError(
                f"clip_index {clip_index} out of range [1, {len(slots)}] "
                f"for session view of track {track_index}"
            )
        slot = slots[clip_index - 1]
        if slot.clip is None:
            raise IndexError(
                f"session slot {clip_index} on track {track_index} is "
                f"already empty"
            )
        slot.delete_clip()
        return {
            "track_index": track_index,
            "location": location,
            "clip_index": clip_index,
            "deleted": True,
        }
    # arrangement
    track = _resolve_track(context, track_index)
    clip = _resolve_clip(
        context, track_index=track_index, location=location, clip_index=clip_index
    )
    delete_fn = getattr(track, "delete_clip", None)
    if delete_fn is None:
        raise NotImplementedError(
            f"track {track_index} does not expose delete_clip — older Live "
            f"build, or arrangement-clip deletion is not available via the API"
        )
    delete_fn(clip)
    return {
        "track_index": track_index,
        "location": location,
        "clip_index": clip_index,
        "deleted": True,
    }


def rename_handler(
    context: LiveContext,
    *,
    track_index: int,
    location: str,
    clip_index: int,
    name: str,
) -> dict[str, Any]:
    """Set a clip's display name. Works for session and arrangement."""
    clip = _resolve_clip(
        context, track_index=track_index, location=location, clip_index=clip_index
    )
    clip.name = name
    return {
        "track_index": track_index,
        "location": location,
        "clip_index": clip_index,
        "name": name,
    }


# ---------------------------------------------------------------------------
# fire / stop — session only
# ---------------------------------------------------------------------------


def fire_handler(
    context: LiveContext, *, track_index: int, clip_index: int
) -> dict[str, Any]:
    """Fire a session-view clip. Arrangement clips aren't fired — use
    ableton_session(action='play') for arrangement playback.
    """
    track = _resolve_track(context, track_index)
    slots = track.clip_slots
    if clip_index < 1 or clip_index > len(slots):
        raise IndexError(
            f"clip_index {clip_index} out of range [1, {len(slots)}] "
            f"for session view of track {track_index}"
        )
    slot = slots[clip_index - 1]
    if slot.clip is None:
        raise IndexError(
            f"session slot {clip_index} on track {track_index} is empty; "
            f"nothing to fire"
        )
    slot.fire()
    return {"track_index": track_index, "clip_index": clip_index, "fired": True}


def stop_handler(
    context: LiveContext, *, track_index: int, clip_index: int
) -> dict[str, Any]:
    """Stop a session-view clip. The track stops; the slot's clip is
    unchanged."""
    track = _resolve_track(context, track_index)
    slots = track.clip_slots
    if clip_index < 1 or clip_index > len(slots):
        raise IndexError(
            f"clip_index {clip_index} out of range [1, {len(slots)}] "
            f"for session view of track {track_index}"
        )
    # Live's API stops a clip via the track's stop_all_clips() (track-wide)
    # OR by setting clip_slot.is_playing = False. We use the per-slot path
    # so we don't accidentally stop other slots on the same track.
    slot = slots[clip_index - 1]
    if slot.clip is None:
        raise IndexError(
            f"session slot {clip_index} on track {track_index} is empty; "
            f"nothing to stop"
        )
    # Live exposes ``clip_slot.stop()`` on recent versions; fall back to
    # the track-wide stop if not present.
    stop_fn = getattr(slot, "stop", None)
    if stop_fn is not None:
        stop_fn()
    else:
        track.stop_all_clips()
    result: dict[str, Any] = {
        "track_index": track_index,
        "clip_index": clip_index,
        "stopped": True,
    }
    # Stopping the Session clip does NOT auto-resume the Arrangement on a track
    # whose lane was overridden — the global latch survives the stop, so the
    # track stays silent (greyed Arrangement lane). Surface that instead of a
    # bare ``stopped: True`` that reads as "fixed" (MCP-7P3R direction 4).
    if is_overridden(context.song):
        result["still_overridden"] = True
        result["note"] = (
            f"Stopping the Session clip did not re-engage the Arrangement. "
            f"{OVERRIDE_DESCRIPTION} {CLICK_BACK_TO_ARRANGEMENT} "
            f"ableton_session(action='back_to_arrangement') attempts the API clear."
        )
    return result


# ---------------------------------------------------------------------------
# set_property — the conform surface plus loop / muted / color
# ---------------------------------------------------------------------------


# Property metadata: (live-attribute-name-on-clip, value-coercer, bounds-or-None)
def _coerce_bool(v: Any) -> bool: return bool(v)
def _coerce_float(v: Any) -> float: return float(v)
def _coerce_int(v: Any) -> int: return int(v)


_CLIP_PROPERTIES: dict[str, tuple[str, Any, tuple[float, float] | None]] = {
    # Audio-clip-only properties raise a teaching error if the underlying
    # clip doesn't expose them. We keep them in the enum so the schema
    # surface stays uniform; the handler discovers per-clip.
    #
    # ``pitch``/``pitch_coarse`` and ``warp``/``warping`` are each ONE Live
    # property under two names: the shipped wire name, and the name
    # ``action='list'`` reports it under (which is also the DB column's).
    # Both spellings write the same attribute, so a value read back can be
    # written back verbatim — a round trip that had to rename its own fields
    # in flight is not one.
    #
    # ``warp_mode`` is Live's warp-algorithm enum. The int is passed through
    # and only its range is checked: which algorithm each int names is a
    # per-build fact, and a clip's own ``available_warp_modes`` is the
    # authority. Live refuses a value it does not know.
    #
    # ``start_marker`` / ``end_marker`` are NOT audio-only — a MIDI clip has
    # them too — and they carry Live's dual unit: beats when the clip is
    # warped, seconds when it is not. Unbounded here for the same reason
    # loop points are: the ceiling is the clip's own extent.
    #
    # No ``reverse``: Live exposes no settable reverse on a Clip.
    "gain":         ("gain",         _coerce_float, (0.0, 1.0)),
    "pitch":        ("pitch_coarse", _coerce_int,   (-48, 48)),
    "pitch_coarse": ("pitch_coarse", _coerce_int,   (-48, 48)),
    "pitch_fine":   ("pitch_fine",   _coerce_float, (-50.0, 50.0)),
    "warp":         ("warping",      _coerce_bool,  None),
    "warping":      ("warping",      _coerce_bool,  None),
    "warp_mode":    ("warp_mode",    _coerce_int,   (0, 6)),
    "start_marker": ("start_marker", _coerce_float, None),
    "end_marker":   ("end_marker",   _coerce_float, None),
    "loop_start":   ("loop_start",   _coerce_float, None),
    "loop_end":     ("loop_end",     _coerce_float, None),
    "muted":        ("muted",        _coerce_bool,  None),
    "color":        ("color",        _coerce_int,   None),
}


_AUDIO_ONLY_CLIP_PROPERTIES: frozenset[str] = frozenset({
    "gain", "pitch", "pitch_coarse", "pitch_fine", "warp", "warping",
    "warp_mode",
})


def set_property_handler(
    context: LiveContext,
    *,
    track_index: int,
    location: str,
    clip_index: int,
    property: str,
    value: Any,
) -> dict[str, Any]:
    """Write one clip property.

    Audio-only properties — gain, pitch / pitch_coarse, pitch_fine, warp,
    warp_mode — raise a teaching error on MIDI clips. Together with the
    markers they are the conform surface: what turns a raw file into a
    sample that sits in the song. Loop properties are in beats; markers
    follow the clip's own unit (beats when warped, seconds when not);
    ``muted`` is a clip-level mute (orthogonal to track-level mute).
    """
    if property not in _CLIP_PROPERTIES:
        raise ValueError(
            f"set_property: property {property!r} is not supported; "
            f"valid values are {sorted(_CLIP_PROPERTIES)}"
        )
    attr, coercer, bounds = _CLIP_PROPERTIES[property]
    coerced = coercer(value)
    clip = _resolve_clip(
        context, track_index=track_index, location=location, clip_index=clip_index
    )
    # Pre-check: an audio-only property on a MIDI clip bubbles Live's raw
    # "X is only available for Audio Clips" RuntimeError.
    # Surface a teaching error instead (Wave-1 B-26). Done BEFORE the
    # bounds check so users with a bad value on the wrong clip kind get
    # the kind-mismatch message (more actionable) instead of "out of range".
    if property in _AUDIO_ONLY_CLIP_PROPERTIES and bool(
        getattr(clip, "is_midi_clip", False)
    ):
        raise ValueError(
            f"set_property: property {property!r} is audio-only "
            f"({sorted(_AUDIO_ONLY_CLIP_PROPERTIES)}); the clip at "
            f"(track={track_index}, {location}, {clip_index}) is a MIDI "
            f"clip. These properties only apply to audio clips."
        )
    if bounds is not None and not (bounds[0] <= float(coerced) <= bounds[1]):
        raise ValueError(
            f"set_property: value {value} for {property!r} is out of range "
            f"{list(bounds)}"
        )
    if not hasattr(clip, attr):
        raise NotImplementedError(
            f"clip at (track={track_index}, {location}, {clip_index}) does not "
            f"expose attribute {attr!r}; property {property!r} likely doesn't "
            f"apply to this clip's kind (audio-only properties: "
            f"{sorted(_AUDIO_ONLY_CLIP_PROPERTIES)})"
        )
    setattr(clip, attr, coerced)
    return {
        "track_index": track_index,
        "location": location,
        "clip_index": clip_index,
        "property": property,
        "value": coerced,
    }


# ---------------------------------------------------------------------------
# duplicate_to_arrangement
# ---------------------------------------------------------------------------


def _clip_identity(clip: Any) -> tuple[float, float, str]:
    """A clip's (start, length, name), rounded — enough to tell two clips at
    the same start apart when one of them is about to be deleted."""
    return (
        round(float(clip.start_time), 6),
        round(float(clip.length), 6),
        str(getattr(clip, "name", "")),
    )


def duplicate_to_arrangement_handler(
    context: LiveContext,
    *,
    track_index: int,
    clip_index: int,
    start_beats: float,
) -> dict[str, Any]:
    """Copy a session clip into the arrangement at ``start_beats``.

    Live's ``track.duplicate_clip_to_arrangement(clip, destination_time)``
    takes beats. The Hallucinote planner converts from bar-based song
    positions using its time-signature map before emit; the MCP layer
    stays meter-agnostic. Returns the new arrangement clip's 1-based
    index.

    Wave-2 W2-H / B-24: when the destination region overlaps an existing
    arrangement clip, Live's duplicate semantics SPLIT the overlapped
    clip at the destination position and emit a SECOND copy of the
    overlapped clip starting at ``dest_beats + source_length`` (the
    right-half-of-the-split, but as a NEW arrangement clip). Example:
    Scaffold 0..32 + duplicate(source_length=4) at beat 16 produces
    [Scaffold 0..32, DupSource 16..20, Scaffold 20..52] — the third
    clip is the side effect. The handler now detects this case and
    deletes the spurious clip post-call. Cleanup is best-effort: if
    Live doesn't expose a per-clip deleter on this track, we report
    the spurious clip in the result so the agent can act on it.
    """
    if start_beats < 0:
        raise ValueError(f"start_beats {start_beats} must be >= 0")
    track = _resolve_track(context, track_index)
    slots = track.clip_slots
    if clip_index < 1 or clip_index > len(slots):
        raise IndexError(
            f"clip_index {clip_index} out of range [1, {len(slots)}] "
            f"for session view of track {track_index}"
        )
    slot = slots[clip_index - 1]
    if slot.clip is None:
        raise IndexError(
            f"session slot {clip_index} on track {track_index} is empty; "
            f"nothing to duplicate"
        )
    source_clip = slot.clip
    dest_beats = float(start_beats)

    duplicate_fn = getattr(track, "duplicate_clip_to_arrangement", None)
    if duplicate_fn is None:
        raise NotImplementedError(
            f"track {track_index} does not expose "
            f"duplicate_clip_to_arrangement — older Live build, or the API "
            f"has moved"
        )

    # Snapshot start_times before the duplicate so we can identify the
    # spurious overlap-split side effect afterward.
    #
    # A MULTISET, not a set: a set answers "was anything here before?", which
    # is the wrong question when Live adds a SECOND clip at a position that
    # already had one. If a pre-existing clip happens to sit at exactly
    # `dest_beats + source_length` — precisely where the B-24 split emits its
    # copy — a set-based check sees the start_time already present and waves
    # the spurious clip through. Counting occurrences instead asks "is there
    # one MORE clip here than before?", which is the question that catches it.
    # Identity (`id(c)`) would also answer it, but Live recreates its clip
    # wrappers (B-1), so identities don't survive the call.
    before_starts: Counter[float] = Counter(
        round(float(c.start_time), 6) for c in track.arrangement_clips
    )
    # The IDENTITY multiset, alongside the position one. Counting starts says
    # how MANY clips are surplus at a position; it cannot say WHICH of the
    # clips now sitting there is the surplus one — and the loser of that
    # question gets deleted. Keying on (start, length, name) lets a contested
    # position be settled by matching each survivor against what was there
    # before, rather than by the order Live happens to enumerate in.
    before_identities: Counter[tuple[float, float, str]] = Counter(
        _clip_identity(c) for c in track.arrangement_clips
    )
    duplicate_fn(source_clip, dest_beats)

    # The new arrangement clip is whichever one starts at dest_beats.
    new_index: int | None = None
    expected_start_key = round(dest_beats, 6)
    for i, c in enumerate(track.arrangement_clips, start=1):
        if abs(float(c.start_time) - dest_beats) < 1e-6:
            new_index = i
            break
    if new_index is None:
        raise RuntimeError(
            "duplicate_to_arrangement: could not locate the new arrangement "
            "clip after Live's duplicate call"
        )

    # Identify any arrangement clip that is SURPLUS to what was here before,
    # once our intended destination clip is accounted for — that's Live's B-24
    # split-and-shift side effect.
    #
    # Walk the after-state drawing down the before-counts: each clip that can
    # be paired with one that existed before is accounted for, the first
    # unaccounted clip at the destination is the one we asked Live to make,
    # and anything still unaccounted after that is spurious. Pairing by count
    # rather than by "start_time seen before" is what makes a collision at
    # `dest_beats + source_length` detectable.
    # Resolved a POSITION AT A TIME, never clip-by-clip in enumeration order.
    # Counting answers how many clips are surplus at a start; identity answers
    # which one. Answering the second by iteration order means that when Live
    # enumerates the split copy before the operator's pre-existing clip, this
    # handler deletes the operator's authored clip, keeps the artifact, and
    # reports it as a successful cleanup. Live's ordering for two clips
    # sharing a start is not something this code controls, so it is not
    # something this code may bet a deletion on. A start that will not resolve
    # deletes NOTHING and goes out through `spurious_clips_remaining`.
    after_by_start: dict[float, list[Any]] = {}
    for c in track.arrangement_clips:
        after_by_start.setdefault(round(float(c.start_time), 6), []).append(c)

    spurious_clips: list[Any] = []
    ambiguous_clips: list[Any] = []
    for start_key, group in after_by_start.items():
        surplus = len(group) - before_starts.get(start_key, 0)
        if start_key == expected_start_key:
            # One surplus clip at the destination is the one we asked for.
            surplus -= 1
        if surplus <= 0:
            continue
        if len(group) == surplus:
            # Nothing survives here from before, so there is no contest and
            # nothing to identify.
            spurious_clips.extend(group)
            continue
        # Contested. Two clips here look alike enough that only one of them
        # should go, so the first question is whether identity can tell them
        # apart at all. Where the SAME identity occurs twice in the group,
        # it cannot: drawing one of the pair down against the before-state
        # and calling the other the newcomer just re-runs the enumeration-order
        # coin-flip one level down, and in real Live the split copy carries the
        # OVERLAPPED clip's content — so the two are not interchangeable and
        # deleting the wrong one is still a destroyed authored clip.
        group_identities = Counter(_clip_identity(c) for c in group)
        tied = [c for c in group if group_identities[_clip_identity(c)] > 1]
        if tied:
            ambiguous_clips.extend(tied)
            continue
        # Every clip here is distinguishable. Draw each survivor down against
        # the identities present before the call; whatever is left over is
        # what the duplicate added.
        unmatched = Counter(before_identities)
        newcomers: list[Any] = []
        for c in group:
            identity = _clip_identity(c)
            if unmatched.get(identity, 0) > 0:
                unmatched[identity] -= 1
            else:
                newcomers.append(c)
        if len(newcomers) == surplus:
            spurious_clips.extend(newcomers)
        else:
            # Distinguishable from each other, but the group does not reconcile
            # with what was here before — so which one the duplicate added is
            # not established, and a wrong guess destroys authored work.
            ambiguous_clips.extend(group)

    spurious_removed: list[dict[str, Any]] = []
    spurious_remaining: list[dict[str, Any]] = [
        {
            "start_beats": float(c.start_time),
            "length": float(c.length),
            "name": str(getattr(c, "name", "")),
            "reason": (
                "more clips at this start than before, but the survivors "
                "cannot be told apart from what was already here — delete "
                "the surplus one by hand"
            ),
        }
        for c in ambiguous_clips
    ]
    for c in spurious_clips:
        info = {
            "start_beats": float(c.start_time),
            "length": float(c.length),
            "name": str(getattr(c, "name", "")),
        }
        # Prefer Track.delete_clip(clip) — Live 12.4's per-clip deleter.
        # Fall back to clip.delete() / clip.remove() if exposed.
        deleter = getattr(track, "delete_clip", None)
        deleted = False
        if deleter is not None:
            try:
                deleter(c)
                deleted = True
            except (TypeError, RuntimeError):
                pass
        if not deleted:
            per_clip = getattr(c, "delete", None) or getattr(c, "remove", None)
            if per_clip is not None:
                try:
                    per_clip()
                    deleted = True
                except (TypeError, RuntimeError):
                    pass
        if deleted:
            spurious_removed.append(info)
        else:
            spurious_remaining.append(info)

    # Recompute new_index since the spurious-clip removal may have
    # shifted positions in arrangement_clips (Live's collection is
    # dense and sorted by start_time).
    if spurious_removed:
        for i, c in enumerate(track.arrangement_clips, start=1):
            if abs(float(c.start_time) - dest_beats) < 1e-6:
                new_index = i
                break

    result: dict[str, Any] = {
        "track_index": track_index,
        "source_clip_index": clip_index,
        "arrangement_clip_index": new_index,
        "start_beats": dest_beats,
    }
    if spurious_removed:
        result["spurious_clips_removed"] = spurious_removed
    if spurious_remaining:
        # Don't fail the call — the requested duplicate IS in place. But
        # the agent should know the cleanup couldn't complete so it can
        # decide whether to delete via a follow-up call.
        result["spurious_clips_remaining"] = spurious_remaining
    return result


# ---------------------------------------------------------------------------
# replace_notes — gap #1's renamed action
# ---------------------------------------------------------------------------


def replace_notes_handler(
    context: LiveContext,
    *,
    track_index: int,
    location: str,
    clip_index: int,
    notes: list[dict[str, Any]],
) -> dict[str, Any]:
    """Replace ALL notes in a clip.

    The legacy fork's ``add_notes_to_clip`` had this same destructive
    semantic but the name lied (Hallucinote gap #1). The renamed action
    makes the contract honest: agents read ``replace_notes`` and know they
    must pull-mutate-push to preserve manual edits.

    Note the return shape **deliberately omits** ``clip_index``. The
    Hallucinote apply layer's ``_LINK_KINDS`` table maps `clip:` keys to
    ``clip_index`` for ableton-link binding; in-place replace doesn't
    re-bind anything, and emitting an ``ABLETON_LINK_SET`` event for every
    note edit would noise up the audit-log seed (the future event-store
    flip cares). Omitting the field causes apply to skip the relink path
    cleanly (see ``apply_push_results``'s ``if result_field not in res``
    branch). ``track_index`` is still returned for diagnostics; only
    ``clip_index`` is suppressed because it's the link key.
    """
    clip = _resolve_clip(
        context, track_index=track_index, location=location, clip_index=clip_index
    )
    coerced = _coerce_notes(notes)
    # True total-replace. Live's ``set_notes()`` does NOT reliably clear
    # pre-existing notes on ARRANGEMENT clips — it left 5 older-generation
    # notes (distinct (pitch, start), inside the clip extent) untouched on a
    # 243-note write, reporting success (ARR-ORPHAN). Explicitly clear the
    # full clip extent first so the write is a genuine total-replace on both
    # views. The session path already total-replaces; the clear is harmless
    # (and defensive) there.
    clip.remove_notes_extended(0, 128, 0.0, float(clip.length))
    clip.set_notes(coerced)
    # Read the resulting set back so the caller can detect a leak instead of
    # trusting the intended count. Live collapses same-(pitch, start) notes,
    # so a faithful write can legitimately hold FEWER than ``len(coerced)``
    # (e.g. stacked add_wildness notes); collapse only ever REDUCES, so an
    # EXCESS is impossible after a true clear and is the one unambiguous
    # orphan-survival signal. (MIDI-only — get_notes_extended raises on audio;
    # mirrors the list-handler guard at the top of this module.)
    notes_present = (
        len(clip.get_notes_extended(0, 128, 0.0, float(clip.length)))
        if clip.is_midi_clip
        else len(coerced)
    )
    result: dict[str, Any] = {
        "track_index": track_index,
        "location": location,
        "notes_written": len(coerced),
        "notes_present": notes_present,
    }
    warnings: list[str] = []
    inline_warning = _inline_notes_warning(len(coerced))
    if inline_warning:
        warnings.append(inline_warning)
    if notes_present > len(coerced):
        warnings.append(
            f"replace_notes left {notes_present - len(coerced)} unexpected "
            f"note(s): wrote {len(coerced)} but the clip holds {notes_present} "
            "after a full-extent clear (orphan-survival — ARR-ORPHAN). The "
            "clip is NOT faithful to the written set; re-read with "
            "ableton_note(action='list') and clear the stragglers."
        )
    if warnings:
        result["warning"] = warnings[0] if len(warnings) == 1 else " | ".join(warnings)
    return result


# ---------------------------------------------------------------------------
# Quantize / swing / groove are deliberately NOT MCP actions.
# ---------------------------------------------------------------------------
#
# Note-timing transforms (quantize, swing, groove templates) are pure-math
# operations on a note array. The Hallucinote DB is the source of truth for
# notes; doing the math in Python/SQL space and pushing the already-grooved
# array via ``ableton_clip(action='replace_notes', ...)`` is uniformly
# better than Live's per-clip ``quantize()`` / ``Groove Pool`` round-trip:
#
#   - **Testability.** A pure function ``quantize(notes, grid, amount, swing)``
#     can be unit-tested against fixtures. Live's ``clip.quantize()`` is a
#     black box.
#   - **Cross-DAW portability.** The same DB row drives Live, a future Logic
#     exporter, an OSC engine, or a humanized print. Live-side compute would
#     have to be re-implemented per target.
#   - **Groove templates as DB rows.** A `grooves` table is portable across
#     songs, version-controlled with the rest of the project, and immune to
#     Live's per-set Groove Pool isolation.
#
# The Hallucinote-side quantize/groove module has no LIVE tracker item: GEN-2T8M
# (issue #272) was dropped, not deferred. The rationale above is therefore the
# whole record, which is why it is written out here rather than left to a link.


__all__ = [
    "list_handler",
    "create_handler",
    "delete_handler",
    "rename_handler",
    "fire_handler",
    "stop_handler",
    "set_property_handler",
    "duplicate_to_arrangement_handler",
    "replace_notes_handler",
]
