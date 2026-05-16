"""``ableton_session`` action schema.

The tool covers global state, master-strip, transport, view, tempo / signature,
the arrangement-loop region, and snapshot/revert (deferred — design doc §14.6).

Mostly declarative — the dispatcher reads each ``LiveOp`` and walks the
``Live.Song.Song`` graph. The handler functions (``info``,
``set_master_property``, ``set_arrangement_loop``, ``seek``, ``set_signature``,
plus the snapshot trio) live in ``handlers/session.py``.

Importing this module registers all actions; happens once at server boot
via ``actions/__init__.py``.
"""
from __future__ import annotations

from ..handlers import session as session_handlers
from ..schema import Action, LiveOp, ParamSpec, register


# ---------------------------------------------------------------------------
# Help (metadata-only; the dispatcher generates the menu from this registry)
# ---------------------------------------------------------------------------

register(
    Action(
        tool="ableton_session",
        name="help",
        description=(
            "List all actions on ableton_session, with required/optional "
            "params, examples, and tips."
        ),
        example="ableton_session(action='help')",
    )
)


# ---------------------------------------------------------------------------
# Read: info
# ---------------------------------------------------------------------------

register(
    Action(
        tool="ableton_session",
        name="info",
        description=(
            "Read a structured snapshot of session-global state: tempo, "
            "signature, transport, loop, master mixer, plus track / return / "
            "scene counts."
        ),
        handler=session_handlers.info_handler,
        example="ableton_session(action='info')",
        tips=(
            "Returns a single dict — use ableton_track(action='list') / "
            "ableton_return(action='list') for per-element detail.",
        ),
    )
)


# ---------------------------------------------------------------------------
# Master strip
# ---------------------------------------------------------------------------

register(
    Action(
        tool="ableton_session",
        name="set_master_property",
        description="Write a master-strip mixer property (volume / panning / mute).",
        params=(
            ParamSpec(
                name="property",
                type="str",
                enum=("volume", "panning", "mute"),
                description="Which master-strip property to write.",
            ),
            ParamSpec(
                name="value",
                type="float",
                description=(
                    "Volume: 0.0-1.0 (normalized — NOT dB). "
                    "Panning: -1.0..1.0 (-1 = hard left). "
                    "Mute: 0.0 = unmuted, 1.0 = muted (float for schema "
                    "uniformity; coerced to bool internally)."
                ),
            ),
        ),
        handler=session_handlers.set_master_property_handler,
        example=(
            "ableton_session(action='set_master_property', "
            "property='volume', value=0.85)"
        ),
        tips=(
            "Volume is 0.0-1.0 (Live's normalized scale), NOT decibels.",
            "Use ableton_session(action='info') to read current master values.",
        ),
    )
)


# ---------------------------------------------------------------------------
# View
# ---------------------------------------------------------------------------

register(
    Action(
        tool="ableton_session",
        name="set_view",
        description="Switch the focused Live view.",
        params=(
            ParamSpec(
                name="view",
                type="str",
                enum=("arranger", "session", "detail", "browser"),
                description="Which top-level view to focus.",
            ),
        ),
        handler=session_handlers.set_view_handler,
        example="ableton_session(action='set_view', view='arranger')",
        tips=(
            "Lowercase names — the handler maps them to Live's exact view "
            "labels (Session / Arranger / Detail/Clip / Browser).",
        ),
    )
)


# ---------------------------------------------------------------------------
# Tempo and signature
# ---------------------------------------------------------------------------

register(
    Action(
        tool="ableton_session",
        name="set_tempo",
        description="Set the global song tempo.",
        params=(
            ParamSpec(
                name="bpm",
                type="float",
                minimum=20.0,
                maximum=999.0,
                description="Tempo in BPM. Live's allowed range is 20-999.",
            ),
        ),
        declarative_op=LiveOp(
            kind="property_write",
            target="song",
            property="tempo",
            value_param="bpm",
        ),
        example="ableton_session(action='set_tempo', bpm=132.0)",
        tips=(
            "This sets the GLOBAL tempo. For per-bar tempo automation, use "
            "ableton_automation(action='write_envelope', target_kind='song_tempo').",
        ),
    )
)


register(
    Action(
        tool="ableton_session",
        name="set_signature",
        description="Set the global time signature.",
        params=(
            ParamSpec(
                name="numerator",
                type="int",
                minimum=1,
                maximum=99,
                description="Beats per bar (the top number).",
            ),
            ParamSpec(
                name="denominator",
                type="int",
                minimum=1,
                maximum=32,
                description=(
                    "Beat unit (the bottom number). Must be a power of two "
                    "between 1 and 32; the handler validates."
                ),
            ),
        ),
        handler=session_handlers.set_signature_handler,
        example="ableton_session(action='set_signature', numerator=7, denominator=8)",
        tips=(
            "For per-bar meter changes (a song that goes 4/4 then 6/8), use "
            "ableton_automation(action='write_envelope', target_kind='song_signature').",
        ),
    )
)


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------

register(
    Action(
        tool="ableton_session",
        name="play",
        description="Start playback from the current song position.",
        declarative_op=LiveOp(
            kind="method_call", target="song", method="start_playing"
        ),
        example="ableton_session(action='play')",
    )
)

register(
    Action(
        tool="ableton_session",
        name="stop",
        description="Stop playback. The playhead does not reset.",
        declarative_op=LiveOp(
            kind="method_call", target="song", method="stop_playing"
        ),
        example="ableton_session(action='stop')",
    )
)

register(
    Action(
        tool="ableton_session",
        name="seek",
        description="Move the playhead to (bar, beat). 1-based bar, 0-based-within-bar beat.",
        params=(
            ParamSpec(name="bar", type="int", minimum=1),
            ParamSpec(name="beat", type="float", required=False, minimum=0.0),
        ),
        handler=session_handlers.seek_handler,
        example="ableton_session(action='seek', bar=5, beat=2.0)",
        tips=(
            "Bar 1 is the song's start. Beats inside a bar count from 0 "
            "(0 = downbeat, 1 = beat 2, etc.).",
            "Live counts a beat as a quarter note regardless of meter — "
            "in 6/8, bar 1 has 3 beats (0.0, 1.0, 2.0).",
        ),
    )
)


# ---------------------------------------------------------------------------
# Arrangement loop region
# ---------------------------------------------------------------------------

register(
    Action(
        tool="ableton_session",
        name="set_arrangement_loop",
        description=(
            "Toggle the arrangement loop on or off; optionally set the "
            "(start_bar, end_bar) region at the same time."
        ),
        params=(
            ParamSpec(name="enabled", type="bool"),
            ParamSpec(name="start_bar", type="int", required=False, minimum=1),
            ParamSpec(name="end_bar", type="int", required=False, minimum=2),
        ),
        handler=session_handlers.set_arrangement_loop_handler,
        example=(
            "ableton_session(action='set_arrangement_loop', enabled=True, "
            "start_bar=9, end_bar=17)"
        ),
        tips=(
            "Pass start_bar AND end_bar together, or neither. Live stores "
            "the loop as (loop_start, loop_length); we compute length from "
            "(end_bar - start_bar) using the current signature.",
        ),
    )
)


# ---------------------------------------------------------------------------
# Snapshot / revert / list_snapshots — schema stable, execution deferred
# ---------------------------------------------------------------------------

register(
    Action(
        tool="ableton_session",
        name="snapshot",
        description=(
            "Save a named snapshot of the current session state. "
            "(Schema stable; implementation deferred — see design doc §14.6.)"
        ),
        params=(ParamSpec(name="name", type="str"),),
        handler=session_handlers.snapshot_handler,
        example="ableton_session(action='snapshot', name='before-chorus-tweak')",
        tips=(
            "Snapshot semantics are under design — the choice between "
            "lightweight Live undo-history checkpoints and full .als save-as "
            "is an open question. Action is registered for surface stability; "
            "calling it currently returns a deferred-implementation error.",
        ),
    )
)

register(
    Action(
        tool="ableton_session",
        name="revert",
        description=(
            "Restore a previously-saved snapshot by name. "
            "(Schema stable; implementation deferred — see design doc §14.6.)"
        ),
        params=(ParamSpec(name="name", type="str"),),
        handler=session_handlers.revert_handler,
        example="ableton_session(action='revert', name='before-chorus-tweak')",
    )
)

register(
    Action(
        tool="ableton_session",
        name="list_snapshots",
        description=(
            "List all saved snapshot names. "
            "(Schema stable; implementation deferred — see design doc §14.6.)"
        ),
        handler=session_handlers.list_snapshots_handler,
        example="ableton_session(action='list_snapshots')",
    )
)


__all__: list[str] = []  # registry side-effects only
