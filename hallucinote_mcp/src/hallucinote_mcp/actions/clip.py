"""``ableton_clip`` action schema.

Twelve actions covering the full session + arrangement clip lifecycle:

  - **Lifecycle**: create, delete, rename, duplicate_to_arrangement
  - **Transport (session)**: fire, stop
  - **Mix-state**: set_property (gain / pitch / warp / loop_start / loop_end /
    muted / color)
  - **Notes**: replace_notes (gap #1's renamed action — see design doc §8.2)
  - **Timing**: quantize, apply_groove, extract_groove
  - **Help**: dispatcher-special, generated from this registry

All non-help actions are handlers because they branch on ``location``
(``session`` vs ``arrangement``) — the Live Object Model exposes the two
contexts through different navigation paths (clip_slots vs arrangement_clips).
A pure declarative op would need two ``target`` shapes per action; a handler
keeps it readable.
"""
from __future__ import annotations

from ..handlers import clip as clip_handlers
from ..handlers.clip import QUANTIZE_GRIDS as _QUANTIZE_GRIDS
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
            "slot via clip_index (1-based). Arrangement: place at start_bar. "
            "Pass notes for atomic create-and-populate (single round-trip). "
            "Pass replace=True (session only) to delete the existing slot's "
            "clip before creating, in one call."
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
                name="start_bar",
                type="float",
                required=False,
                minimum=1.0,
                description=(
                    "Required for location='arrangement' (1-based bar; "
                    "fractional allowed for mid-bar placement)."
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
            "Copy a session clip into the arrangement at start_bar. The "
            "source clip stays in the session; a new arrangement clip "
            "appears at the bar."
        ),
        params=(
            ParamSpec(name="track_index", type="int", minimum=1),
            ParamSpec(
                name="clip_index",
                type="int",
                minimum=1,
                description="1-based session slot of the source clip.",
            ),
            ParamSpec(name="start_bar", type="float", minimum=1.0),
        ),
        handler=clip_handlers.duplicate_to_arrangement_handler,
        example=(
            "ableton_clip(action='duplicate_to_arrangement', track_index=2, "
            "clip_index=1, start_bar=5.0)"
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


# ---------------------------------------------------------------------------
# Quantize / groove
# ---------------------------------------------------------------------------

register(
    Action(
        tool="ableton_clip",
        name="quantize",
        description=(
            "Snap a clip's notes to a grid. amount=1.0 is full snap; 0.0 is "
            "no change. Optional swing shifts off-grid hits via Live's "
            "global swing_amount (restored after the call)."
        ),
        params=(
            ParamSpec(name="track_index", type="int", minimum=1),
            ParamSpec(name="location", type="str", enum=_LOCATION_ENUM),
            ParamSpec(name="clip_index", type="int", minimum=1),
            ParamSpec(name="grid", type="str", enum=_QUANTIZE_GRIDS),
            ParamSpec(name="amount", type="float", minimum=0.0, maximum=1.0),
            ParamSpec(
                name="swing", type="float", required=False, minimum=0.0,
                maximum=1.0,
                description=(
                    "Optional. Applied via song.swing_amount for the "
                    "duration of the quantize call; restored afterward."
                ),
            ),
        ),
        handler=clip_handlers.quantize_handler,
        example=(
            "ableton_clip(action='quantize', track_index=2, "
            "location='session', clip_index=1, grid='1/16', amount=0.8)"
        ),
    )
)

register(
    Action(
        tool="ableton_clip",
        name="apply_groove",
        description=(
            "Apply a named Groove Pool groove to a clip. Use "
            "ableton_clip(action='extract_groove') first to populate the "
            "pool from another clip."
        ),
        params=(
            ParamSpec(name="track_index", type="int", minimum=1),
            ParamSpec(name="location", type="str", enum=_LOCATION_ENUM),
            ParamSpec(name="clip_index", type="int", minimum=1),
            ParamSpec(name="groove_name", type="str"),
        ),
        handler=clip_handlers.apply_groove_handler,
        example=(
            "ableton_clip(action='apply_groove', track_index=2, "
            "location='session', clip_index=1, groove_name='Verse Swing')"
        ),
    )
)

register(
    Action(
        tool="ableton_clip",
        name="extract_groove",
        description=(
            "Sample a clip's note timing into a new groove in the Groove "
            "Pool. The new groove is renamed to the provided 'name'."
        ),
        params=(
            ParamSpec(name="track_index", type="int", minimum=1),
            ParamSpec(name="location", type="str", enum=_LOCATION_ENUM),
            ParamSpec(name="clip_index", type="int", minimum=1),
            ParamSpec(name="name", type="str"),
        ),
        handler=clip_handlers.extract_groove_handler,
        example=(
            "ableton_clip(action='extract_groove', track_index=2, "
            "location='session', clip_index=1, name='Verse Swing')"
        ),
    )
)


__all__: list[str] = []  # registry side-effects only
