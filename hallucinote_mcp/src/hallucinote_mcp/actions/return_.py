"""``ableton_return`` action schema.

Seven actions: help, list, info, create, rename, delete, set_property.
W3-H (2026-05-18) added ``rename`` — the recovery path when Live's
slot-letter auto-prefix clobbers a name at create time. Mirrors
``ableton_track`` but against ``song.return_tracks`` and without
``arm`` (returns can't be record-armed) or ``set_send`` (return-to-
return sends are out of scope for V1).
"""
from __future__ import annotations

from ..handlers import return_ as return_handlers
from ..schema import Action, ParamSpec, register


# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------

register(
    Action(
        tool="ableton_return",
        name="help",
        description=(
            "List all actions on ableton_return, with required/optional "
            "params, examples, and tips."
        ),
        example="ableton_return(action='help')",
    )
)


# ---------------------------------------------------------------------------
# Read: list, info
# ---------------------------------------------------------------------------

register(
    Action(
        tool="ableton_return",
        name="list",
        description="Index of all return tracks: return_index (1-based), name, color.",
        handler=return_handlers.list_handler,
        example="ableton_return(action='list')",
    )
)

register(
    Action(
        tool="ableton_return",
        name="info",
        description="Read identity + mixer state for one return track.",
        params=(
            ParamSpec(name="return_index", type="int", minimum=1, description="1-based"),
        ),
        handler=return_handlers.info_handler,
        example="ableton_return(action='info', return_index=2)",
    )
)


# ---------------------------------------------------------------------------
# Lifecycle: create, delete
# ---------------------------------------------------------------------------

register(
    Action(
        tool="ableton_return",
        name="create",
        description=(
            "Create a new return track (Live appends to the end of "
            "song.return_tracks). Optionally name it."
        ),
        params=(
            ParamSpec(
                name="name",
                type="str",
                required=False,
                description="Display name. Live picks a default if omitted.",
            ),
        ),
        handler=return_handlers.create_handler,
        example="ableton_return(action='create', name='Reverb')",
        tips=(
            "Returns {return_index, name}. Live 11+ supports this directly; "
            "older builds raise a teaching error.",
            "**Live rewrites every name write to '<slot-letter>-<value>'** "
            "unconditionally (e.g. slot C + name='Reverb' → 'C-Reverb'; "
            "slot C + name='C-Reverb' → 'C-C-Reverb'). Pass the SUFFIX "
            "only — Live produces the full prefixed form. When Live "
            "mutates the input, the result carries a 'requested_name' "
            "field showing what you asked for.",
        ),
    )
)

register(
    Action(
        tool="ableton_return",
        name="rename",
        description=(
            "Set a return track's display name. W3-H (2026-05-18) — "
            "previously there was no MCP path to rename a return after "
            "create. Useful as the recovery path when Live's slot-letter "
            "auto-prefix clobbered the name at create time (see the "
            "create action). ``ReturnTrack.name`` is a directly-writable "
            "property on Live's LOM, so this is a synchronous one-call rename."
        ),
        params=(
            ParamSpec(name="return_index", type="int", minimum=1),
            ParamSpec(name="name", type="str"),
        ),
        handler=return_handlers.rename_handler,
        example="ableton_return(action='rename', return_index=2, name='Plate')",
        tips=(
            "Subject to Live's unconditional slot-letter prefix on every "
            "name write (same rule as create). Pass the SUFFIX only — "
            "Live produces the full '<slot>-<value>' form. The result "
            "carries 'requested_name' when Live mutates your input.",
        ),
    )
)


register(
    Action(
        tool="ableton_return",
        name="delete",
        description="Delete a return track by 1-based index.",
        params=(
            ParamSpec(name="return_index", type="int", minimum=1),
        ),
        handler=return_handlers.delete_handler,
        example="ableton_return(action='delete', return_index=2)",
        tips=(
            "Send indices on every track shift after a return is deleted — "
            "recompute return_index between calls if your plan deletes "
            "multiple returns.",
        ),
    )
)


# ---------------------------------------------------------------------------
# Mixer state
# ---------------------------------------------------------------------------

_RETURN_PROPERTIES_ENUM = ("volume", "panning", "mute", "solo", "color")


register(
    Action(
        tool="ableton_return",
        name="set_property",
        description=(
            "Write a single mixer property on a return: volume, panning, "
            "mute, solo, or color. NO 'arm' — returns can't be record-armed."
        ),
        params=(
            ParamSpec(name="return_index", type="int", minimum=1),
            ParamSpec(
                name="property", type="str", enum=_RETURN_PROPERTIES_ENUM
            ),
            ParamSpec(
                name="value",
                type="float",
                description=(
                    "volume: 0.0-1.0. panning: -1.0..1.0. "
                    "mute / solo: 0 / 1 (truthy). color: int palette index."
                ),
            ),
        ),
        handler=return_handlers.set_property_handler,
        example=(
            "ableton_return(action='set_property', return_index=1, "
            "property='volume', value=0.85)"
        ),
    )
)


__all__: list[str] = []  # registry side-effects only
