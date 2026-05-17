"""Imperative handlers for ``ableton_clip`` actions.

Clip operations branch on ``location`` (``session`` vs ``arrangement``) because
the Live Object Model exposes the two contexts through different navigation
paths:

  - Session clips live at ``song.tracks[t].clip_slots[s].clip``. The slot
    always exists; ``.clip`` is ``None`` for empty slots. Lifecycle methods
    live on the clip_slot (``create_clip(length)``, ``delete_clip()``).
  - Arrangement clips live in ``song.tracks[t].arrangement_clips`` — a list of
    just the populated clips on the timeline. Lifecycle goes through the
    track itself (``create_midi_clip`` / ``create_audio_clip`` / ``delete_clip``).

Indices are 1-based on the wire and translated to 0-based when accessing the
Live API.

Note operations: ``replace_notes`` calls ``clip.set_notes(tuple(...))`` which
**replaces** the clip's entire note array. The action name is renamed (from
``add_notes_to_clip`` on the legacy fork) to make the semantic visible. Per-
note addressing (true append, in-place mutation) waits on MCP gap #4 — see
``handlers/note.py`` for those stubs.
"""
from __future__ import annotations

from typing import Any, Iterable

from ..dispatcher import LiveContext


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


def list_handler(
    context: LiveContext,
    *,
    track_index: int,
    location: str,
) -> dict[str, Any]:
    """Per-track clip inventory.

    Session: returns every slot (populated AND empty); the slot's 1-based
    position doubles as ``clip_index`` for writes. Empty slots carry
    ``{clip_index, empty: True}``; populated slots add ``name`` + ``length``.

    Arrangement: returns every placed clip with ``arrangement_clip_index``
    (1-based, ordered by ``track.arrangement_clips`` — Live's ordering),
    plus ``name``, ``start_beats``, and ``length``. There are no "empty"
    arrangement positions — ``arrangement_clips`` is dense.

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
                clips_out.append({
                    "clip_index": i,
                    "empty": False,
                    "name": clip.name,
                    "length": float(clip.length),
                })
    else:
        for i, clip in enumerate(track.arrangement_clips, start=1):
            clips_out.append({
                "arrangement_clip_index": i,
                "name": clip.name,
                "start_beats": float(clip.start_time),
                "length": float(clip.length),
            })
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
# create / delete / rename
# ---------------------------------------------------------------------------


def create_handler(
    context: LiveContext,
    *,
    track_index: int,
    location: str,
    kind: str,
    length: float,
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
      ``track.clip_slots[clip_index-1].create_clip(length)``. By default
      errors if the slot already holds a clip; pass ``replace=True`` to
      delete-then-create atomically (the most common Hallucinote iteration
      shape — gap #2's resolution path).
    - **arrangement**: ``start_beats`` is required (Live counts arrangement
      time in beats). The Hallucinote planner converts bar-based song
      positions to beats using its time-signature map before emit; the MCP
      layer stays meter-agnostic. Calls
      ``track.create_midi_clip(start_beats, length)`` or
      ``create_audio_clip``.

    ``audio_path`` is reserved for the future audio-clip ingest story;
    today it's recorded in the result as ``audio_path_deferred`` if
    provided, but no file is loaded.

    ``notes``, when present, is written via ``clip.set_notes(...)`` after
    the clip exists — a single round-trip for the common
    "create-and-populate" iteration pattern.
    """
    _check_location(location)
    if kind not in ("midi", "audio"):
        raise ValueError(f"kind must be 'midi' or 'audio', got {kind!r}")
    if length <= 0:
        raise ValueError(f"length {length} must be > 0")

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
        if slot.clip is not None:
            if not replace:
                raise ValueError(
                    f"session slot {clip_index} on track {track_index} is "
                    f"already occupied; pass replace=True to delete and "
                    f"recreate atomically"
                )
            slot.delete_clip()
        if kind == "audio":
            # Live's clip_slot doesn't expose create_audio_clip; audio clips
            # are dragged from the browser. Until we have a fuller audio
            # ingest story (M-4+), surface this as a teaching error.
            raise NotImplementedError(
                "session-view audio clip creation is not supported in V1 "
                "(Live's API doesn't expose clip_slot.create_audio_clip). "
                "Drag the audio from Live's browser, or place audio in the "
                "arrangement instead (location='arrangement')."
            )
        slot.create_clip(float(length))
        clip = slot.clip
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
        if kind == "midi":
            create_fn = getattr(track, "create_midi_clip", None)
            if create_fn is None:
                raise NotImplementedError(
                    f"track {track_index} does not expose create_midi_clip "
                    f"(not a MIDI track, or older Live build)"
                )
            create_fn(sb, float(length))
        else:
            create_fn = getattr(track, "create_audio_clip", None)
            if create_fn is None:
                raise NotImplementedError(
                    f"track {track_index} does not expose create_audio_clip "
                    f"(not an audio track, or older Live build)"
                )
            create_fn(sb, float(length))
        # Find the new clip — Live appends, so it should be the last one,
        # but we scan defensively for the one matching our (start_beats,
        # length) since arrangement_clips ordering is implementation detail.
        # Break on first hit so a (highly unlikely) duplicate match doesn't
        # silently pick the wrong one.
        new_clip = None
        for c in track.arrangement_clips:
            if (
                abs(float(c.start_time) - sb) < 1e-6
                and abs(float(c.length) - float(length)) < 1e-6
            ):
                new_clip = c
                break
        if new_clip is None:
            raise RuntimeError(
                "create: could not locate the newly-created arrangement clip; "
                "Live API may have changed the post-create ordering"
            )
        clip = new_clip

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
        # Compute the 1-based arrangement index after the create.
        track = _resolve_track(context, track_index)
        for i, c in enumerate(track.arrangement_clips, start=1):
            if c is clip:
                result["clip_index"] = i
                break
        result["start_beats"] = float(start_beats) if start_beats is not None else None
    if audio_path is not None:
        # Reserved for future audio ingest; round-trips so the planner can
        # see we received it.
        result["audio_path_deferred"] = audio_path
    if notes is not None:
        result["notes_written"] = len(notes)
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
    return {"track_index": track_index, "clip_index": clip_index, "stopped": True}


# ---------------------------------------------------------------------------
# set_property — gain / pitch / warp / loop_start / loop_end / muted / color
# ---------------------------------------------------------------------------


# Property metadata: (live-attribute-name-on-clip, value-coercer, bounds-or-None)
def _coerce_bool(v: Any) -> bool: return bool(v)
def _coerce_float(v: Any) -> float: return float(v)
def _coerce_int(v: Any) -> int: return int(v)


_CLIP_PROPERTIES: dict[str, tuple[str, Any, tuple[float, float] | None]] = {
    # Audio-clip-only properties (gain, pitch, warp) raise a teaching error
    # if the underlying clip doesn't expose them. We keep them in the enum so
    # the schema surface stays uniform; the handler discovers per-clip.
    "gain":       ("gain",       _coerce_float, (-1.0, 1.0)),
    "pitch":      ("pitch_coarse", _coerce_int, (-48, 48)),
    "warp":       ("warping",    _coerce_bool, None),
    "loop_start": ("loop_start", _coerce_float, None),
    "loop_end":   ("loop_end",   _coerce_float, None),
    "muted":      ("muted",      _coerce_bool, None),
    "color":      ("color",      _coerce_int,  None),
}


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

    Audio-only properties (gain, pitch, warp) raise a teaching error on
    MIDI clips. Loop properties are in beats; ``muted`` is a clip-level
    mute (orthogonal to track-level mute).
    """
    if property not in _CLIP_PROPERTIES:
        raise ValueError(
            f"set_property: property {property!r} is not supported; "
            f"valid values are {sorted(_CLIP_PROPERTIES)}"
        )
    attr, coercer, bounds = _CLIP_PROPERTIES[property]
    coerced = coercer(value)
    if bounds is not None and not (bounds[0] <= float(coerced) <= bounds[1]):
        raise ValueError(
            f"set_property: value {value} for {property!r} is out of range "
            f"{list(bounds)}"
        )
    clip = _resolve_clip(
        context, track_index=track_index, location=location, clip_index=clip_index
    )
    if not hasattr(clip, attr):
        raise NotImplementedError(
            f"clip at (track={track_index}, {location}, {clip_index}) does not "
            f"expose attribute {attr!r}; property {property!r} likely doesn't "
            f"apply to this clip's kind (audio-only properties: gain, pitch, warp)"
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
    stays meter-agnostic. Returns the new arrangement clip's 1-based index.
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
    duplicate_fn(source_clip, dest_beats)
    # The new arrangement clip is whichever one starts at dest_beats.
    # Break on first hit — under unlikely overlap (two clips at the same
    # beat) we don't want to silently pick the wrong one; first-hit-then-stop
    # is the closest-to-deterministic behavior the API gives us.
    new_index: int | None = None
    for i, c in enumerate(track.arrangement_clips, start=1):
        if abs(float(c.start_time) - dest_beats) < 1e-6:
            new_index = i
            break
    if new_index is None:
        raise RuntimeError(
            "duplicate_to_arrangement: could not locate the new arrangement "
            "clip after Live's duplicate call"
        )
    return {
        "track_index": track_index,
        "source_clip_index": clip_index,
        "arrangement_clip_index": new_index,
        "start_beats": dest_beats,
    }


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
    clip.set_notes(coerced)
    return {
        "track_index": track_index,
        "location": location,
        "notes_written": len(coerced),
    }


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
# The Hallucinote-side quantize/groove module is tracked in `.prawduct/backlog.md`.


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
