"""``ableton_scene`` action schema.

Nine actions covering session-view scenes (rows of clip slots + per-scene
tempo + signature):

  - **Read**: list, info
  - **Lifecycle**: create (with optional position), delete, rename
  - **Transport**: fire (plays all clips in the row)
  - **Per-scene state**: set_tempo, set_signature
  - **Help**: dispatcher-special

Design doc reconciliation: the doc lists `insert_at` as a separate action
from `create`. Live's API exposes ONE primitive (``song.create_scene(index)``)
that handles both append (index=-1) and insert (index>=0). We collapse the
two action surfaces into one — `create` accepts an optional `position`
param. The design doc table will be updated in M-5's audit step to remove
the `insert_at` row.
"""
from __future__ import annotations

from ..handlers import scene as scene_handlers
from ..schema import Action, ParamSpec, register


# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------

register(
    Action(
        tool="ableton_scene",
        name="help",
        description=(
            "List all actions on ableton_scene, with required/optional "
            "params, examples, and tips."
        ),
        example="ableton_scene(action='help')",
    )
)


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

register(
    Action(
        tool="ableton_scene",
        name="list",
        description=(
            "Index of all session scenes: scene_index (1-based), name, "
            "color, tempo (null when scene has no local tempo override), "
            "time_signature."
        ),
        handler=scene_handlers.list_handler,
        example="ableton_scene(action='list')",
        tips=(
            "Lightweight — use action='info' on a scene_index for the "
            "per-track clip count.",
        ),
    )
)

register(
    Action(
        tool="ableton_scene",
        name="info",
        description=(
            "Scene identity + clip_count (number of non-empty clip slots in "
            "the row)."
        ),
        params=(
            ParamSpec(name="scene_index", type="int", minimum=1),
        ),
        handler=scene_handlers.info_handler,
        example="ableton_scene(action='info', scene_index=3)",
    )
)


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

register(
    Action(
        tool="ableton_scene",
        name="create",
        description=(
            "Create a new scene. position (1-based) inserts before that "
            "index; if omitted, Live appends. Optional name renames the "
            "scene post-create. (Design doc note: this action absorbs "
            "the doc's `insert_at` — Live's create_scene primitive handles "
            "both append and insert via its index arg.)"
        ),
        params=(
            ParamSpec(name="name", type="str", required=False),
            ParamSpec(
                name="position", type="int", required=False, minimum=1,
                description="1-based insert position. Omit to append.",
            ),
        ),
        handler=scene_handlers.create_handler,
        example=(
            "ableton_scene(action='create', name='Chorus', position=8)"
        ),
        tips=(
            "Returns {scene_index, name} — capture scene_index for "
            "subsequent calls.",
        ),
    )
)

register(
    Action(
        tool="ableton_scene",
        name="delete",
        description="Delete a scene by 1-based scene_index.",
        params=(
            ParamSpec(name="scene_index", type="int", minimum=1),
        ),
        handler=scene_handlers.delete_handler,
        example="ableton_scene(action='delete', scene_index=5)",
        tips=(
            "Scene indices after the deleted one shift down by 1; "
            "recompute between calls or delete in descending order.",
        ),
    )
)

register(
    Action(
        tool="ableton_scene",
        name="rename",
        description="Set a scene's display name.",
        params=(
            ParamSpec(name="scene_index", type="int", minimum=1),
            ParamSpec(name="name", type="str"),
        ),
        handler=scene_handlers.rename_handler,
        example=(
            "ableton_scene(action='rename', scene_index=3, name='Bridge')"
        ),
    )
)


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------

register(
    Action(
        tool="ableton_scene",
        name="fire",
        description=(
            "Fire a scene — plays every non-empty clip in the row "
            "simultaneously."
        ),
        params=(
            ParamSpec(name="scene_index", type="int", minimum=1),
        ),
        handler=scene_handlers.fire_handler,
        example="ableton_scene(action='fire', scene_index=2)",
    )
)


# ---------------------------------------------------------------------------
# Per-scene tempo + signature
# ---------------------------------------------------------------------------

register(
    Action(
        tool="ableton_scene",
        name="set_tempo",
        description=(
            "Set the scene's local tempo override. When the scene is fired, "
            "this tempo takes effect. Pass bpm=-1 to clear the override "
            "(scene falls through to song tempo)."
        ),
        params=(
            ParamSpec(name="scene_index", type="int", minimum=1),
            ParamSpec(
                name="bpm", type="float", minimum=-1.0, maximum=999.0,
                description="-1 clears; otherwise must be in Live's range [20, 999].",
            ),
        ),
        handler=scene_handlers.set_tempo_handler,
        example=(
            "ableton_scene(action='set_tempo', scene_index=2, bpm=140.0)"
        ),
    )
)

register(
    Action(
        tool="ableton_scene",
        name="set_signature",
        description=(
            "Set the scene's local time signature. Denominator must be a "
            "power of 2 in [1, 32]."
        ),
        params=(
            ParamSpec(
                name="scene_index", type="int", minimum=1,
            ),
            ParamSpec(name="numerator", type="int", minimum=1, maximum=99),
            ParamSpec(
                name="denominator", type="int", minimum=1, maximum=32,
                description="Must be a power of 2 (1, 2, 4, 8, 16, or 32).",
            ),
        ),
        handler=scene_handlers.set_signature_handler,
        example=(
            "ableton_scene(action='set_signature', scene_index=2, "
            "numerator=7, denominator=8)"
        ),
    )
)


__all__: list[str] = []  # registry side-effects only
