"""``ableton_track`` action schema.

Eleven actions: help, list, info, create, delete, rename, set_property,
get_property, set_send, get_sends, deletion_status. ``rename`` is the only
declarative one (clean property_write on a navigated target); everything
else is a handler because of property branching, multi-step orchestration,
or aggregated reads.

Importing this module registers all actions via ``actions/__init__.py``.
"""
from __future__ import annotations

from ..handlers import track as track_handlers
from ..schema import Action, LiveOp, ParamSpec, register


# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------

register(
    Action(
        tool="ableton_track",
        name="help",
        description=(
            "List all actions on ableton_track, with required/optional params, "
            "examples, and tips."
        ),
        example="ableton_track(action='help')",
    )
)


# ---------------------------------------------------------------------------
# Read: list, info, deletion_status
# ---------------------------------------------------------------------------

register(
    Action(
        tool="ableton_track",
        name="list",
        description="Index of all tracks: track_index (1-based), name, kind, color.",
        handler=track_handlers.list_handler,
        example="ableton_track(action='list')",
        tips=(
            "Lightweight — use action='info' on a track_index for the mixer / "
            "device detail.",
        ),
    )
)

register(
    Action(
        tool="ableton_track",
        name="info",
        description=(
            "Read identity + mixer state for one track in a single call. "
            "Includes `volume_db` (the fader's dB off Live's own curve; null "
            "when the fader is fully down, volume 0) alongside the raw "
            "normalized `volume`."
        ),
        params=(
            ParamSpec(name="track_index", type="int", minimum=1, description="1-based"),
        ),
        handler=track_handlers.info_handler,
        example="ableton_track(action='info', track_index=5)",
    )
)

register(
    Action(
        tool="ableton_track",
        name="deletion_status",
        description=(
            "Confirm whether 1-based track indices are present in the current "
            "session (and their names). Live does not expose a stable "
            "can-be-deleted predicate; this action reports presence only. "
            "Actual delete failures (master / guarded group layouts) surface "
            "as structured errors at delete time."
        ),
        params=(
            ParamSpec(
                name="track_indices",
                type="list",
                required=False,
                description="List of 1-based indices. If omitted, every track is checked.",
            ),
        ),
        handler=track_handlers.deletion_status_handler,
        example="ableton_track(action='deletion_status', track_indices=[3, 5])",
    )
)


# ---------------------------------------------------------------------------
# Lifecycle: create, delete, rename
# ---------------------------------------------------------------------------

register(
    Action(
        tool="ableton_track",
        name="create",
        description=(
            "Create a MIDI or audio track. Optionally name it. The "
            "instrument_uri param is reserved for the future device-load "
            "story (Wave M-4); pass it now and it round-trips in the result "
            "as `instrument_uri_deferred`, but no device is loaded."
        ),
        params=(
            ParamSpec(
                name="kind",
                type="str",
                enum=("midi", "audio"),
                description="midi or audio. Group-track creation is not supported yet.",
            ),
            ParamSpec(
                name="name",
                type="str",
                required=False,
                description="Display name. Live picks a default if omitted.",
            ),
            ParamSpec(
                name="index",
                type="int",
                required=False,
                minimum=1,
                description="1-based insert position. Omit to append.",
            ),
            ParamSpec(
                name="instrument_uri",
                type="str",
                required=False,
                description=(
                    "Deferred — schema-stable but not loaded in M-2. Use "
                    "ableton_device(action='load') in M-4 to attach an "
                    "instrument."
                ),
            ),
        ),
        handler=track_handlers.create_handler,
        example=(
            "ableton_track(action='create', kind='midi', name='Drums', index=2)"
        ),
        tips=(
            "Returns {track_index, kind, name} — capture track_index for "
            "subsequent set_property / set_send calls.",
        ),
    )
)

register(
    Action(
        tool="ableton_track",
        name="delete",
        description="Delete a track by 1-based index. Cannot be undone via this action.",
        params=(
            ParamSpec(name="track_index", type="int", minimum=1),
        ),
        handler=track_handlers.delete_handler,
        example="ableton_track(action='delete', track_index=7)",
        tips=(
            "Indices of all tracks AFTER the deleted one shift down by 1. "
            "If your plan deletes multiple tracks, delete in descending order "
            "or recompute indices between calls.",
        ),
    )
)

register(
    Action(
        tool="ableton_track",
        name="rename",
        description="Set a track's display name.",
        params=(
            ParamSpec(name="track_index", type="int", minimum=1),
            ParamSpec(name="name", type="str"),
        ),
        declarative_op=LiveOp(
            kind="property_write",
            target="song.tracks[{track_index-1}]",
            property="name",
            value_param="name",
            result_template={
                "track_index": "$track_index",
                "name": "$name",
            },
        ),
        example="ableton_track(action='rename', track_index=5, name='Lead')",
    )
)


# ---------------------------------------------------------------------------
# Mixer state: set_property, get_property
# ---------------------------------------------------------------------------

_MIXER_PROPERTIES = ("volume", "panning", "mute", "solo", "arm", "color")


register(
    Action(
        tool="ableton_track",
        name="set_property",
        description=(
            "Write a single mixer property: volume, panning, mute, solo, arm, "
            "or color. Give the raw `value` — or, for volume, `value_display` in "
            "dB ('-8 dB'). Per-property ranges are enforced (volume 0-1, panning "
            "-1..1); out-of-range writes fail with a teaching error instead "
            "of Live's silent clamp."
        ),
        params=(
            ParamSpec(name="track_index", type="int", minimum=1),
            ParamSpec(name="property", type="str", enum=_MIXER_PROPERTIES),
            ParamSpec(
                name="value",
                type="float",
                required=False,
                description=(
                    "volume: 0.0-1.0 (Live's normalized scale, NOT dB — use "
                    "`value_display` for dB). "
                    "panning: -1.0..1.0 (-1 = hard left). "
                    "mute / solo / arm: 0 / 1 (truthy). "
                    "color: int palette index. "
                    "Omit when using `value_display`."
                ),
            ),
            ParamSpec(
                name="value_display",
                type="str",
                required=False,
                description=(
                    "volume only: target in dB as a string ('-8 dB', '0 dB', "
                    "'+3 dB'), inverted to Live's normalized value via the "
                    "fader's own display curve. Mutually exclusive with `value`. "
                    "Panning has no dB sense, so its value_display is refused."
                ),
            ),
        ),
        handler=track_handlers.set_property_handler,
        example=(
            "ableton_track(action='set_property', track_index=5, "
            "property='volume', value_display='-8 dB')"
        ),
        tips=(
            "Volume's raw `value` is normalized 0.0-1.0, not decibels — pass "
            "`value_display='-8 dB'` to think in dB, or read `volume_db` from "
            "action='info'. The response echoes the achieved `value_display`.",
            "Color is an int palette index — see Live's color picker for the "
            "available codes.",
        ),
    )
)

register(
    Action(
        tool="ableton_track",
        name="get_property",
        description="Read a single mixer property by name.",
        params=(
            ParamSpec(name="track_index", type="int", minimum=1),
            ParamSpec(name="property", type="str", enum=_MIXER_PROPERTIES),
        ),
        handler=track_handlers.get_property_handler,
        example="ableton_track(action='get_property', track_index=5, property='volume')",
    )
)


# ---------------------------------------------------------------------------
# Sends: set_send, get_sends
# ---------------------------------------------------------------------------

register(
    Action(
        tool="ableton_track",
        name="set_send",
        description="Set one send level (track → return).",
        params=(
            ParamSpec(name="track_index", type="int", minimum=1),
            ParamSpec(name="return_index", type="int", minimum=1),
            ParamSpec(name="value", type="float", minimum=0.0, maximum=1.0),
        ),
        handler=track_handlers.set_send_handler,
        example=(
            "ableton_track(action='set_send', track_index=5, return_index=1, "
            "value=0.4)"
        ),
        tips=(
            "Value is normalized 0.0-1.0. Use ableton_return(action='list') to "
            "find the return_index by name.",
        ),
    )
)

register(
    Action(
        tool="ableton_track",
        name="get_sends",
        description=(
            "Read every send level for a track, paired with the destination "
            "return's name."
        ),
        params=(
            ParamSpec(name="track_index", type="int", minimum=1),
        ),
        handler=track_handlers.get_sends_handler,
        example="ableton_track(action='get_sends', track_index=5)",
    )
)


__all__: list[str] = []  # registry side-effects only
