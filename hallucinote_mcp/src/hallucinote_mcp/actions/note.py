"""``ableton_note`` action schema — per-note operations within a clip.

Five actions: help, list, add, update, delete. Every non-help action is a
stub blocked by MCP gap #4 (no stable note IDs from
``clip.get_notes_extended()``). The schema exists so:

  - Agents reading ``ableton_note(action='help')`` see the planned action
    menu — no surprises when the gap lands.
  - The dispatcher returns a structured teaching error from any non-help
    call, citing the gap explicitly.
  - The action signatures stay stable from the moment the surface is
    introduced; gap #4's resolution swaps the implementation, not the
    contract.

To replace ALL notes on a clip today (the only working path), use
``ableton_clip(action='replace_notes')``.
"""
from __future__ import annotations

from ..handlers import note as note_handlers
from ..schema import Action, ParamSpec, register


_LOCATION_ENUM = ("session", "arrangement")


# ---------------------------------------------------------------------------
# Help (dispatcher-special; description signals the gap up front)
# ---------------------------------------------------------------------------

register(
    Action(
        tool="ableton_note",
        name="help",
        description=(
            "Per-note operations within a clip — list, add, update, delete. "
            "ALL non-help actions on this tool are BLOCKED BY MCP GAP #4: "
            "Live's note API doesn't yet expose stable per-note IDs. The "
            "action menu is published for surface stability. To replace "
            "ALL notes on a clip today, use "
            "ableton_clip(action='replace_notes')."
        ),
        example="ableton_note(action='help')",
    )
)


# ---------------------------------------------------------------------------
# Gap-#4 stubs
# ---------------------------------------------------------------------------

register(
    Action(
        tool="ableton_note",
        name="list",
        description=(
            "[BLOCKED — MCP gap #4] Read the clip's notes WITH stable IDs. "
            "Once gap #4 lands, returns "
            "[{id, pitch, start_time, duration, velocity, mute}, ...]."
        ),
        params=(
            ParamSpec(name="track_index", type="int", minimum=1),
            ParamSpec(name="location", type="str", enum=_LOCATION_ENUM),
            ParamSpec(name="clip_index", type="int", minimum=1),
        ),
        handler=note_handlers.list_handler,
        example=(
            "ableton_note(action='list', track_index=2, "
            "location='session', clip_index=1)"
        ),
        tips=(
            "Currently raises a teaching error citing MCP gap #4. To pull "
            "all notes destructively, capture via the Live UI or wait for "
            "gap #4 resolution.",
        ),
    )
)

register(
    Action(
        tool="ableton_note",
        name="add",
        description=(
            "[BLOCKED — MCP gap #4] TRUE APPEND of notes to a clip "
            "(returning new IDs). Once gap #4 lands, returns "
            "[{id: new, ...}, ...] without disturbing existing notes."
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
                    "[{pitch, start_time, duration, velocity?, mute?}, ...]"
                ),
            ),
        ),
        handler=note_handlers.add_handler,
        example=(
            "ableton_note(action='add', track_index=2, location='session', "
            "clip_index=1, notes=[{pitch:60, start_time:0.0, duration:1.0}])"
        ),
        tips=(
            "Currently raises a teaching error. To replace ALL notes today, "
            "use ableton_clip(action='replace_notes').",
        ),
    )
)

register(
    Action(
        tool="ableton_note",
        name="update",
        description=(
            "[BLOCKED — MCP gap #4] Mutate specific notes by ID. Once gap "
            "#4 lands, takes a list of (id, changes) tuples and updates "
            "in-place without touching other notes."
        ),
        params=(
            ParamSpec(name="track_index", type="int", minimum=1),
            ParamSpec(name="location", type="str", enum=_LOCATION_ENUM),
            ParamSpec(name="clip_index", type="int", minimum=1),
            ParamSpec(
                name="note_ids",
                type="list",
                description="List of note IDs (ints) returned by action='list'.",
            ),
            ParamSpec(
                name="changes",
                type="dict",
                description=(
                    "Per-id changes: {pitch?, start_time?, duration?, "
                    "velocity?, mute?}. Same shape applied to every id."
                ),
            ),
        ),
        handler=note_handlers.update_handler,
        example=(
            "ableton_note(action='update', track_index=2, location='session', "
            "clip_index=1, note_ids=[3, 5], changes={velocity: 80})"
        ),
    )
)

register(
    Action(
        tool="ableton_note",
        name="delete",
        description=(
            "[BLOCKED — MCP gap #4] Remove specific notes by ID. Once gap "
            "#4 lands, takes a list of IDs and removes them without "
            "touching other notes."
        ),
        params=(
            ParamSpec(name="track_index", type="int", minimum=1),
            ParamSpec(name="location", type="str", enum=_LOCATION_ENUM),
            ParamSpec(name="clip_index", type="int", minimum=1),
            ParamSpec(
                name="note_ids",
                type="list",
                description="List of note IDs (ints) returned by action='list'.",
            ),
        ),
        handler=note_handlers.delete_handler,
        example=(
            "ableton_note(action='delete', track_index=2, location='session', "
            "clip_index=1, note_ids=[3, 5])"
        ),
    )
)


__all__: list[str] = []  # registry side-effects only
