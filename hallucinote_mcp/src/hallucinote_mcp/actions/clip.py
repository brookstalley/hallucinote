"""``ableton_clip`` action schema.

Ten actions covering the full session + arrangement clip lifecycle:

  - **Read**: list (per-track inventory, both locations, with the audio
    conform surface on audio clips)
  - **Lifecycle**: create, delete, rename, duplicate_to_arrangement
  - **Transport (session)**: fire, stop
  - **Mix-state**: set_property (gain / pitch / pitch_fine / warp /
    warp_mode / start_marker / end_marker / loop_start / loop_end /
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
# The write half of the audio conform surface. ``pitch`` and ``warp`` are the
# shipped spellings; ``pitch_coarse`` and ``warping`` are the same two
# properties under the names the read surface (``list``) reports them by, so
# a reader can write back exactly the name it read. Reverse is deliberately
# absent: Live exposes no settable reverse on a Clip, and Simpler has no
# Reverse parameter either — its `reverse()` is a destructive method that
# writes a derived file (`lom-probe-results.md` rows 14 and 19) — so a sample
# plays backwards only by way of a pre-reversed derived asset, never a
# property anywhere.
_CLIP_PROPERTIES = (
    "gain", "pitch", "pitch_coarse", "pitch_fine", "warp", "warping",
    "warp_mode", "start_marker", "end_marker", "loop_start", "loop_end",
    "muted", "color",
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
# Read: list
# ---------------------------------------------------------------------------

register(
    Action(
        tool="ableton_clip",
        name="list",
        description=(
            "Per-track clip inventory. Session: every slot, populated or "
            "empty; the 1-based slot position doubles as clip_index. "
            "Arrangement: every placed clip, with arrangement_clip_index, "
            "name, start_beats, length. Every populated clip carries "
            "is_audio; an audio clip additionally reports its conform "
            "state (file_path, gain, pitch_coarse, pitch_fine, warping, "
            "warp_mode, start_marker, end_marker). Wire stays beats-based; "
            "the Hallucinote sync layer converts to bar-based song "
            "positions."
        ),
        params=(
            ParamSpec(name="track_index", type="int", minimum=1),
            ParamSpec(name="location", type="str", enum=_LOCATION_ENUM),
        ),
        handler=clip_handlers.list_handler,
        example=(
            "ableton_clip(action='list', track_index=2, "
            "location='arrangement')"
        ),
        tips=(
            "Session entries include {empty: True} for unpopulated slots — "
            "the slot itself always exists.",
            "Arrangement returns are dense (no empty positions); use the "
            "1-based 'arrangement_clip_index' for subsequent writes.",
            "is_audio is the kind discriminator. The audio conform fields "
            "are present ONLY when is_audio is true — a MIDI clip omits "
            "them entirely rather than reporting them null, so a missing "
            "file_path always means 'not an audio clip', never 'audio clip "
            "with no file'.",
            "start_marker / end_marker are in BEATS when warping is true "
            "and SECONDS when it is false — read warping from the same "
            "entry before interpreting them.",
        ),
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
            "converts from bar-based song positions). kind='midi' takes "
            "length (beats) and optional notes for atomic "
            "create-and-populate (single round-trip); kind='audio' takes "
            "audio_path (absolute) and gets its length from the file. Pass "
            "replace=True (session only) to delete the existing slot's clip "
            "before creating, in one call. A replace whose kind cannot "
            "match the track REFUSES before deleting, so the existing "
            "clip survives."
        ),
        params=(
            ParamSpec(name="track_index", type="int", minimum=1),
            ParamSpec(name="location", type="str", enum=_LOCATION_ENUM),
            ParamSpec(name="kind", type="str", enum=_KIND_ENUM),
            ParamSpec(
                name="length",
                type="float",
                required=False,
                minimum=0.0,
                description=(
                    "Clip length in beats. Must be > 0. REQUIRED for "
                    "kind='midi'. Ignored for kind='audio' — Live derives an "
                    "audio clip's length from the file (warped to the song "
                    "tempo); trim it with set_property start_marker / "
                    "end_marker."
                ),
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
                    "REQUIRED for kind='audio': an ABSOLUTE path to an audio "
                    "file Live can read. Live resolves nothing — the "
                    "Hallucinote planner turns a song-relative reference "
                    "into an absolute path via paths.resolve_audio_path "
                    "before the call. The created clip's file_path comes "
                    "back in the result."
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
            "Pass notes to create-and-populate in one call (MIDI only — "
            "an audio clip has no note array).",
            "Pass replace=True (session only) for atomic delete-and-recreate; "
            "a kind mismatch refuses before the delete, leaving the clip intact.",
            "Audio clips load for real in BOTH locations: session goes "
            "through ClipSlot.create_audio_clip(path), arrangement through "
            "Track.create_audio_clip(path, start_beats). Live 12.4 is the "
            "floor for both.",
            "An audio clip must land on an audio track (Live refuses it on "
            "a MIDI track) and audio_path must be absolute. Live reports a "
            "missing file and an undecodable one with the same refusal, so "
            "check the file exists before pushing.",
            "Conform the clip after creating it: set_property gain / pitch "
            "/ pitch_fine / warp / warp_mode / start_marker / end_marker.",
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
            "Write one clip property. Audio-only properties (gain, pitch / "
            "pitch_coarse, pitch_fine, warp / warping, warp_mode) error on "
            "MIDI clips. Loop properties are in beats; markers follow the "
            "clip's own unit (see 'value'); 'muted' is a clip-level mute "
            "(orthogonal to track mute)."
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
                    "gain: 0.0..1.0 LINEAR, not dB (audio only). "
                    "pitch / pitch_coarse: "
                    "-48..48 semitones (audio only). pitch_fine: -50.0..50.0 "
                    "cents (audio only). warp / warping: 0/1 truthy (audio "
                    "only). "
                    "warp_mode: Live's warp-algorithm int, 0..6 (audio "
                    "only) — read the clip's own available_warp_modes for "
                    "the authoritative list on your Live build. "
                    "start_marker / end_marker: the clip's playable region, "
                    "in BEATS when the clip is warped and SECONDS when it "
                    "is not. loop_start / loop_end: beats. muted: 0/1 "
                    "truthy. color: int palette index."
                ),
            ),
        ),
        handler=clip_handlers.set_property_handler,
        example=(
            "ableton_clip(action='set_property', track_index=2, "
            "location='session', clip_index=1, property='muted', value=1)"
        ),
        tips=(
            "Conform an audio clip with gain + pitch/pitch_fine + warp / "
            "warp_mode + start_marker/end_marker; that set is exactly what "
            "action='list' reads back off an audio clip, so a conform "
            "round-trips.",
            "There is no 'reverse' property — Live exposes no settable "
            "reverse on a Clip, and Simpler has no Reverse parameter either "
            "(its reverse() writes a derived file). Play a sample backwards "
            "by pointing the clip at a pre-reversed derived asset.",
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
            "May also return spurious_clips_removed and/or "
            "spurious_clips_remaining. Live's duplicate API occasionally "
            "splits an existing arrangement clip that overlaps the "
            "destination (the B-24 side effect — W2-H). The handler "
            "detects these by comparing the arrangement's clips before "
            "and after the duplicate, and deletes a surplus clip only when "
            "its (start, length, name) identifies it as the one the "
            "duplicate added. Deleted clips are reported in "
            "spurious_clips_removed. spurious_clips_remaining carries the "
            "rest: clips the deleter could not remove, AND clips it "
            "deliberately did not try — where two clips share a start and "
            "cannot be told apart, deleting either could destroy authored "
            "work, so both are reported with a `reason` and left in place "
            "for you to resolve by eye. The requested duplicate IS in "
            "place either way, but the agent should follow up on anything "
            "remaining. "
            "Both fields are omitted from the response when the duplicate "
            "produced no spurious side effects (the common case).",
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
