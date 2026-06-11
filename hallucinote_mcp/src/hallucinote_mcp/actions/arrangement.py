"""``ableton_arrangement`` action schema.

Eight actions covering arrangement-view state + cue points:

  - **Read**: info, cue_list
  - **Loop**: set_loop (beats-based, replacing M-1's ableton_session
    set_arrangement_loop which is dropped per no-unnecessary-backwards-compat)
  - **View**: control_view (multi-action via action_kind discriminator)
  - **Cue points**: cue_create, cue_delete, cue_jump
  - **Help**: dispatcher-special

Time positions on the wire are **beats** (Wave M-3/M-4 principle: wire
stays meter-agnostic; the Hallucinote planner converts from bar-based song
positions via its time-signature map before emit).

Cue point names round-trip cleanly in this greenfield server — the legacy
fork's gap #13 (get_cue_points returning numeric-only IDs) is resolved
for hallucinote-mcp's lifetime.
"""
from __future__ import annotations

from ..handlers import arrangement as arrangement_handlers
from ..schema import Action, ParamSpec, register


_VIEW_ACTIONS = (
    "zoom_in", "zoom_out", "scroll_left", "scroll_right",
    "follow_on", "follow_off", "collapse_track", "expand_track",
)
_JUMP_DIRECTIONS = ("next", "previous")


# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------

register(
    Action(
        tool="ableton_arrangement",
        name="help",
        description=(
            "List all actions on ableton_arrangement, with required/optional "
            "params, examples, and tips."
        ),
        example="ableton_arrangement(action='help')",
    )
)


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

register(
    Action(
        tool="ableton_arrangement",
        name="info",
        description=(
            "Arrangement-level snapshot: global tempo + signature, total "
            "length in beats, loop region, cue count."
        ),
        handler=arrangement_handlers.info_handler,
        example="ableton_arrangement(action='info')",
    )
)

register(
    Action(
        tool="ableton_arrangement",
        name="cue_list",
        description=(
            "Read all cue points: [{cue_index (1-based), position_beats, "
            "name}, ...]. Names round-trip cleanly (legacy fork's gap #13 "
            "does not apply to this greenfield server)."
        ),
        handler=arrangement_handlers.cue_list_handler,
        example="ableton_arrangement(action='cue_list')",
    )
)


# ---------------------------------------------------------------------------
# Loop
# ---------------------------------------------------------------------------

register(
    Action(
        tool="ableton_arrangement",
        name="set_loop",
        description=(
            "Toggle the arrangement loop; optionally set the "
            "(start_beats, end_beats) region. Pass start and end together "
            "or neither. Time in beats — the Hallucinote planner converts "
            "bar-based positions before emit (wire stays meter-agnostic)."
        ),
        params=(
            ParamSpec(name="enabled", type="bool"),
            ParamSpec(
                name="start_beats", type="float", required=False, minimum=0.0,
            ),
            ParamSpec(
                name="end_beats", type="float", required=False, minimum=0.0,
            ),
        ),
        handler=arrangement_handlers.set_loop_handler,
        example=(
            "ableton_arrangement(action='set_loop', enabled=True, "
            "start_beats=32.0, end_beats=64.0)"
        ),
        tips=(
            "M-5 dropped ableton_session(action='set_arrangement_loop') — "
            "this is the canonical home for arrangement-loop control.",
        ),
    )
)


# ---------------------------------------------------------------------------
# View
# ---------------------------------------------------------------------------

register(
    Action(
        tool="ableton_arrangement",
        name="control_view",
        description=(
            "Step the arranger view. action_kind selects among 8 affordances: "
            "zoom_in/out, scroll_left/right, follow_on/off, "
            "collapse_track/expand_track. The collapse/expand kinds require "
            "track_index."
        ),
        params=(
            ParamSpec(name="action_kind", type="str", enum=_VIEW_ACTIONS),
            ParamSpec(
                name="track_index", type="int", required=False, minimum=1,
                description=(
                    "Required for collapse_track / expand_track; ignored "
                    "otherwise."
                ),
            ),
        ),
        handler=arrangement_handlers.control_view_handler,
        example=(
            "ableton_arrangement(action='control_view', "
            "action_kind='collapse_track', track_index=2)"
        ),
    )
)


# ---------------------------------------------------------------------------
# Cue points
# ---------------------------------------------------------------------------

register(
    Action(
        tool="ableton_arrangement",
        name="cue_create",
        description=(
            "Create a cue point at position_beats with an optional name. "
            "Returns the new cue_index (1-based). When ``if_exists='skip'`` "
            "(default ``'refuse'``), a same-position same-name cue is a "
            "no-op (the result carries ``skipped=True``) and a same-"
            "position different-name request still raises so name drift "
            "stays visible."
        ),
        params=(
            ParamSpec(name="position_beats", type="float", minimum=0.0),
            ParamSpec(name="name", type="str", required=False),
            ParamSpec(
                name="if_exists", type="str", required=False,
                enum=("refuse", "skip"),
                description=(
                    "Behavior when a cue already exists at position_beats. "
                    "'refuse' (default): raise. 'skip': no-op when names "
                    "match (or name is omitted); raise on name mismatch."
                ),
            ),
        ),
        handler=arrangement_handlers.cue_create_handler,
        # W3-F: see handler docstring. The seek-then-settle window
        # needs WALL-CLOCK wait time while Live's main thread pumps
        # audio-thread propagation events. Running the handler on the
        # worker thread (and bouncing each Live touch through
        # ``run_on_main`` individually) avoids the main-thread deadlock
        # the W2-F implementation hit.
        runs_on_worker=True,
        example=(
            "ableton_arrangement(action='cue_create', position_beats=16.0, "
            "name='Verse')"
        ),
    )
)

register(
    Action(
        tool="ableton_arrangement",
        name="cue_create_batch",
        description=(
            "Create multiple cue points in one call. Each entry is "
            "{position_beats: float, name?: str}. Returns "
            "{cue_count, cues: [...]} in submission order. Each per-cue "
            "result shape matches cue_create's. PREFERRED over multiple "
            "parallel cue_create calls — the underlying Live API has a "
            "~400ms per-cue settle window that doesn't parallelize, so "
            "the batch pays the per-cue cost once across one round trip "
            "instead of N. Indices reported are the position in "
            "song.cue_points at the time of each insert; call cue_list "
            "after the batch for the final mapping. "
            "**Out-of-range policy** (SYN-6B4Q): ``on_out_of_range`` "
            "controls cues past ``last_event_time`` (Live clamps the cue "
            "setter to the arrangement extent). 'refuse' (default, W5-C "
            "atomic): if any cue is past the extent, NO cues are written. "
            "'skip' (the planner path): create the in-extent cues and "
            "return the rest in ``skipped_out_of_range`` (+ "
            "``last_event_time``) — deferred, not failed. **Mid-loop "
            "errors** (e.g. a position collides with a cue Live "
            "acquired between batches) can still leave partial state — "
            "call cue_list afterward to discover what landed if the "
            "response surfaces a per-cue error."
        ),
        params=(
            ParamSpec(
                name="cues", type="list",
                description=(
                    "List of {position_beats: float, name?: str} dicts. "
                    "Positions must be unique within the batch and within "
                    "[0, last_event_time]."
                ),
            ),
            ParamSpec(
                name="if_exists", type="str", required=False,
                enum=("refuse", "skip"),
                description=(
                    "Per-entry behavior when a cue already exists at "
                    "position_beats. 'skip' (default — the planner path): "
                    "no-op when names match; the result carries "
                    "``skipped=True``. 'refuse': raise on any collision."
                ),
            ),
            ParamSpec(
                name="on_out_of_range", type="str", required=False,
                enum=("refuse", "skip"),
                description=(
                    "Behavior for cues past last_event_time. 'refuse' "
                    "(default): atomic — any out-of-range cue aborts the "
                    "whole batch (W5-C). 'skip' (the planner path): create "
                    "the in-extent cues, defer the rest into "
                    "``skipped_out_of_range`` instead of failing."
                ),
            ),
        ),
        handler=arrangement_handlers.cue_create_batch_handler,
        runs_on_worker=True,  # W3-F — same rationale as cue_create.
        example=(
            "ableton_arrangement(action='cue_create_batch', cues=["
            "{'position_beats': 0.0, 'name': 'Intro'}, "
            "{'position_beats': 16.0, 'name': 'Verse'}, "
            "{'position_beats': 48.0, 'name': 'Chorus'}])"
        ),
        tips=(
            "For a 7-cue song this is ~3s end-to-end (each cue's "
            "audio-thread settle is ~400ms) — acceptable for setup-time "
            "pushes, slow for interactive use.",
            "Final cue_index values may differ from those reported in "
            "the per-cue results because Live keeps the list sorted by "
            "position. Use cue_list afterward if you need the stable "
            "index mapping.",
        ),
    )
)

register(
    Action(
        tool="ableton_arrangement",
        name="cue_delete",
        description="Delete a cue point by 1-based cue_index.",
        params=(
            ParamSpec(name="cue_index", type="int", minimum=1),
        ),
        handler=arrangement_handlers.cue_delete_handler,
        runs_on_worker=True,  # W3-F — same rationale as cue_create.
        example="ableton_arrangement(action='cue_delete', cue_index=2)",
        tips=(
            "Subsequent cue_index values shift down after a delete; "
            "recompute between calls or delete in descending order.",
        ),
    )
)

register(
    Action(
        tool="ableton_arrangement",
        name="cue_rename",
        description=(
            "Set a cue point's display name. Useful when ``cue_create`` "
            "completed but the rename step couldn't be applied due to "
            "Live API timing — call ``cue_list`` to find the cue_index "
            "of the cue you want to rename, then this."
        ),
        params=(
            ParamSpec(name="cue_index", type="int", minimum=1),
            ParamSpec(name="name", type="str"),
        ),
        handler=arrangement_handlers.cue_rename_handler,
        example="ableton_arrangement(action='cue_rename', cue_index=2, name='Verse')",
        tips=(
            "Cue.name is a direct writable property on Live's CuePoint "
            "object, so this is a synchronous one-call rename — no "
            "main-thread settle dance needed.",
        ),
    )
)

register(
    Action(
        tool="ableton_arrangement",
        name="cue_jump",
        description=(
            "Jump the playhead to a cue. Provide EXACTLY ONE of "
            "direction ('next'|'previous', relative to current position) "
            "OR name (jumps to the cue with that name)."
        ),
        params=(
            ParamSpec(
                name="direction", type="str", required=False,
                enum=_JUMP_DIRECTIONS,
            ),
            ParamSpec(
                name="name", type="str", required=False,
                description="Cue name (case-sensitive).",
            ),
        ),
        handler=arrangement_handlers.cue_jump_handler,
        # W3-F follow-up: cue_jump_handler acquires live_state_lock,
        # same RLock as the worker-thread cue handlers. Must be on
        # the worker thread to avoid cross-thread deadlock.
        runs_on_worker=True,
        example=(
            "ableton_arrangement(action='cue_jump', direction='next')"
        ),
    )
)


__all__: list[str] = []  # registry side-effects only
