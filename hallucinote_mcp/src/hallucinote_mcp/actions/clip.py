"""``ableton_clip`` action schema.

Nine actions covering the full session + arrangement clip lifecycle:

  - **Lifecycle**: create, delete, rename, duplicate_to_arrangement
  - **Transport (session)**: fire, stop
  - **Mix-state**: set_property (gain / pitch / warp / loop_start / loop_end /
    muted / color)
  - **Notes**: replace_notes (gap #1's renamed action — see design doc §8.2)
  - **Help**: dispatcher-special, generated from this registry

All non-help actions are handlers because they branch on ``location``
(``session`` vs ``arrangement``) — the Live Object Model exposes the two
contexts through different navigation paths (clip_slots vs arrangement_clips).
A pure declarative op would need two ``target`` shapes per action; a handler
keeps it readable.

**Quantize / swing / groove are deliberately NOT actions here.** The
Hallucinote DB is the source of truth for note timing; quantize, swing, and
groove templates are pure-math transforms computed in Python/SQL space and
pushed via ``replace_notes`` already-grooved. See design doc §6.2 for the
rationale (testability, cross-DAW portability, DB-row groove templates).
"""
from __future__ import annotations

from ..handlers import clip as clip_handlers
from ..schema import Action, ParamSpec, register


_LOCATION_ENUM = ("session", "arrangement")
_KIND_ENUM = ("midi", "audio")
_CLIP_PROPERTIES = (
    "gain", "pitch", "warp", "loop_start", "loop_end", "muted", "color",
)


# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------

register(
    Action(
        tool="ableton_clip",
        name="help",
        description=(
            "List all actions on ableton_clip, with required/optional "
            "params, examples, and tips."
        ),
        example="ableton_clip(action='help')",
    )
)


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

register(
    Action(
        tool="ableton_clip",
        name="create",
        description=(
            "Create a clip in session or arrangement view. Session: pick a "
            "slot via clip_index (1-based). Arrangement: place at start_beats "
            "(Live counts arrangement time in beats; the Hallucinote planner "
            "converts from bar-based song positions). Pass notes for atomic "
            "create-and-populate (single round-trip). Pass replace=True "
            "(session only) to delete the existing slot's clip before "
            "creating, in one call."
        ),
        params=(
            ParamSpec(name="track_index", type="int", minimum=1),
            ParamSpec(name="location", type="str", enum=_LOCATION_ENUM),
            ParamSpec(name="kind", type="str", enum=_KIND_ENUM),
            ParamSpec(
                name="length",
                type="float",
                minimum=0.0,
                description="Clip length in beats. Must be > 0.",
            ),
            ParamSpec(
                name="clip_index",
                type="int",
                required=False,
                minimum=1,
                description="Required for location='session' (the 1-based slot).",
            ),
            ParamSpec(
                name="start_beats",
                type="float",
                required=False,
                minimum=0.0,
                description=(
                    "Required for location='arrangement'. Beats from the "
                    "song's start. The Hallucinote planner converts from "
                    "bar-based positions using the song's time-signature "
                    "map; MCP stays meter-agnostic."
                ),
            ),
            ParamSpec(
                name="name",
                type="str",
                required=False,
                description="Display name. Live picks a default if omitted.",
            ),
            ParamSpec(
                name="notes",
                type="list",
                required=False,
                description=(
                    "Optional list of note dicts: "
                    "[{pitch, start_time, duration, velocity?, mute?}, ...]. "
                    "If provided, written via clip.set_notes() after create."
                ),
            ),
            ParamSpec(
                name="audio_path",
                type="str",
                required=False,
                description=(
                    "Reserved for future audio-ingest story. Schema-stable; "
                    "today it round-trips in the result as "
                    "'audio_path_deferred' but no file is loaded."
                ),
            ),
            ParamSpec(
                name="replace",
                type="bool",
                required=False,
                description=(
                    "Session-only. If True and the slot is occupied, delete "
                    "the existing clip before creating. The atomic resolution "
                    "for Hallucinote gap #2."
                ),
            ),
        ),
        handler=clip_handlers.create_handler,
        example=(
            "ableton_clip(action='create', track_index=2, location='session', "
            "clip_index=1, kind='midi', length=16.0, "
            "notes=[{pitch:60, start_time:0.0, duration:1.0, velocity:100}])"
        ),
        tips=(
            "Pass notes to create-and-populate in one call.",
            "Pass replace=True (session only) for atomic delete-and-recreate.",
            "Audio clips: session creation is not supported in V1; use "
            "location='arrangement' with audio_path (deferred), or drag "
            "from Live's browser.",
        ),
    )
)

register(
    Action(
        tool="ableton_clip",
        name="delete",
        description=(
            "Delete a clip. Session: clears the slot, slot remains. "
            "Arrangement: removes the clip and subsequent arrangement_clips "
            "indices shift down."
        ),
        params=(
            ParamSpec(name="track_index", type="int", minimum=1),
            ParamSpec(name="location", type="str", enum=_LOCATION_ENUM),
            ParamSpec(name="clip_index", type="int", minimum=1),
        ),
        handler=clip_handlers.delete_handler,
        example=(
            "ableton_clip(action='delete', track_index=2, "
            "location='session', clip_index=1)"
        ),
    )
)

register(
    Action(
        tool="ableton_clip",
        name="rename",
        description="Set a clip's display name.",
        params=(
            ParamSpec(name="track_index", type="int", minimum=1),
            ParamSpec(name="location", type="str", enum=_LOCATION_ENUM),
            ParamSpec(name="clip_index", type="int", minimum=1),
            ParamSpec(name="name", type="str"),
        ),
        handler=clip_handlers.rename_handler,
        example=(
            "ableton_clip(action='rename', track_index=2, "
            "location='session', clip_index=1, name='Verse')"
        ),
    )
)


# ---------------------------------------------------------------------------
# Transport (session-only)
# ---------------------------------------------------------------------------

register(
    Action(
        tool="ableton_clip",
        name="fire",
        description=(
            "Fire (play) a session-view clip. Arrangement clips aren't fired "
            "— use ableton_session(action='play') for arrangement playback."
        ),
        params=(
            ParamSpec(name="track_index", type="int", minimum=1),
            ParamSpec(name="clip_index", type="int", minimum=1),
        ),
        handler=clip_handlers.fire_handler,
        example="ableton_clip(action='fire', track_index=2, clip_index=1)",
    )
)

register(
    Action(
        tool="ableton_clip",
        name="stop",
        description=(
            "Stop a session-view clip. The slot's clip is unchanged; only "
            "playback halts."
        ),
        params=(
            ParamSpec(name="track_index", type="int", minimum=1),
            ParamSpec(name="clip_index", type="int", minimum=1),
        ),
        handler=clip_handlers.stop_handler,
        example="ableton_clip(action='stop', track_index=2, clip_index=1)",
    )
)


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------

register(
    Action(
        tool="ableton_clip",
        name="set_property",
        description=(
            "Write one clip property. Audio-only properties (gain, pitch, "
            "warp) error on MIDI clips. Loop properties are in beats; "
            "'muted' is a clip-level mute (orthogonal to track mute)."
        ),
        params=(
            ParamSpec(name="track_index", type="int", minimum=1),
            ParamSpec(name="location", type="str", enum=_LOCATION_ENUM),
            ParamSpec(name="clip_index", type="int", minimum=1),
            ParamSpec(name="property", type="str", enum=_CLIP_PROPERTIES),
            ParamSpec(
                name="value",
                type="float",
                description=(
                    "gain: -1.0..1.0 (audio only). pitch: -48..48 semitones "
                    "(audio only). warp: 0/1 truthy (audio only). "
                    "loop_start / loop_end: beats. muted: 0/1 truthy. "
                    "color: int palette index."
                ),
            ),
        ),
        handler=clip_handlers.set_property_handler,
        example=(
            "ableton_clip(action='set_property', track_index=2, "
            "location='session', clip_index=1, property='muted', value=1)"
        ),
    )
)


# ---------------------------------------------------------------------------
# Duplicate to arrangement
# ---------------------------------------------------------------------------

register(
    Action(
        tool="ableton_clip",
        name="duplicate_to_arrangement",
        description=(
            "Copy a session clip into the arrangement at start_beats. The "
            "source clip stays in the session; a new arrangement clip "
            "appears at the given beat. The Hallucinote planner converts "
            "from bar-based song positions; MCP stays meter-agnostic."
        ),
        params=(
            ParamSpec(name="track_index", type="int", minimum=1),
            ParamSpec(
                name="clip_index",
                type="int",
                minimum=1,
                description="1-based session slot of the source clip.",
            ),
            ParamSpec(name="start_beats", type="float", minimum=0.0),
        ),
        handler=clip_handlers.duplicate_to_arrangement_handler,
        example=(
            "ableton_clip(action='duplicate_to_arrangement', track_index=2, "
            "clip_index=1, start_beats=16.0)"
        ),
        tips=(
            "Returns {arrangement_clip_index} — capture for subsequent "
            "arrangement-side property writes.",
        ),
    )
)


# ---------------------------------------------------------------------------
# Notes (gap #1 — renamed)
# ---------------------------------------------------------------------------

register(
    Action(
        tool="ableton_clip",
        name="replace_notes",
        description=(
            "REPLACE the clip's entire note array. The legacy fork's "
            "'add_notes_to_clip' had this same destructive semantic but the "
            "name lied (Hallucinote gap #1). To preserve manual edits, pull "
            "the existing notes, mutate, then call this action."
        ),
        params=(
            ParamSpec(name="track_index", type="int", minimum=1),
            ParamSpec(name="location", type="str", enum=_LOCATION_ENUM),
            ParamSpec(name="clip_index", type="int", minimum=1),
            ParamSpec(
                name="notes",
                type="list",
                description=(
                    "List of note dicts: "
                    "[{pitch: 0-127, start_time: beats, duration: beats, "
                    "velocity?: 1-127, mute?: bool}, ...]"
                ),
            ),
        ),
        handler=clip_handlers.replace_notes_handler,
        example=(
            "ableton_clip(action='replace_notes', track_index=2, "
            "location='session', clip_index=1, "
            "notes=[{pitch:60, start_time:0.0, duration:1.0, velocity:100}])"
        ),
        tips=(
            "This REPLACES the entire note array — there is no append. "
            "True per-note operations are gated on MCP gap #4 (see "
            "ableton_note).",
        ),
    )
)


__all__: list[str] = []  # registry side-effects only
