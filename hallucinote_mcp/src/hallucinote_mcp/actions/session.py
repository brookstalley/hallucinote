"""``ableton_session`` action schema.

The tool covers global state, master-strip, transport, view, tempo / signature,
the arrangement-loop region, and snapshot/revert (deferred — design doc §14.6).

Mostly declarative — the dispatcher reads each ``LiveOp`` and walks the
``Live.Song.Song`` graph. The handler functions (``info``,
``set_master_property``, ``seek``, ``play``, ``continue_playing``,
``back_to_arrangement``, ``set_signature``, plus the snapshot trio) live in
``handlers/session.py``.

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
            result_template={"tempo": "$bpm"},
        ),
        example="ableton_session(action='set_tempo', bpm=132.0)",
        tips=(
            "This sets the GLOBAL tempo (bar-1 anchor). Multi-bar tempo "
            "automation is NOT closeable via MCP — Live's LOM doesn't "
            "expose create_automation_envelope from any song-level path "
            "(W6-F 2026-05-19 investigation; see ableton://guides/gaps "
            "'Arrangement-level tempo / signature automation'). For "
            "multi-section tempo changes, use per-scene tempo via "
            "ableton_scene.",
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
            "This sets the GLOBAL meter. Multi-section meter changes are "
            "NOT closeable via MCP — Live's signature_* are plain int "
            "properties (not DeviceParameter objects) and time-signature "
            "automation is unsupported in Live's API per Ableton's forum "
            "(W6-F 2026-05-19). For sections in different meters, use "
            "per-scene time signatures via ableton_scene.",
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
        description=(
            "Start playback (Live's *Start*) — from the Arrangement Start "
            "Marker, NOT from a seeked position. Returns started_from."
        ),
        handler=session_handlers.play_handler,
        example="ableton_session(action='play')",
        tips=(
            "play does NOT honor a preceding seek — it restarts at the Start "
            "Marker. To audition from a specific bar, seek then "
            "continue_playing.",
        ),
    )
)

register(
    Action(
        tool="ableton_session",
        name="continue_playing",
        description=(
            "Resume playback (Live's *Continue*) — from the current playhead. "
            "This is the play call that honors a preceding seek. Returns "
            "started_from."
        ),
        handler=session_handlers.continue_playing_handler,
        example="ableton_session(action='continue_playing')",
        tips=(
            "seek(bar=X) then continue_playing is the 'locate to bar X and "
            "play from there' gesture — plain play would jump back to the "
            "Start Marker.",
        ),
    )
)

register(
    Action(
        tool="ableton_session",
        name="stop",
        description="Stop playback. The playhead does not reset.",
        declarative_op=LiveOp(
            kind="method_call", target="song", method="stop_playing",
            result_template={"is_playing": False},
        ),
        example="ableton_session(action='stop')",
    )
)

register(
    Action(
        tool="ableton_session",
        name="back_to_arrangement",
        description=(
            "Re-engage Arrangement playback after a Session clip overrode a "
            "track (clears the back_to_arranger latch + re-enables overridden "
            "automation). Reports whether Live honored the API clear — in Live "
            "12.x the latch may only clear via the GUI Back to Arrangement "
            "button, in which case the result teaches that instead of failing "
            "silently."
        ),
        handler=session_handlers.back_to_arrangement_handler,
        example="ableton_session(action='back_to_arrangement')",
        tips=(
            "Use this when a pushed Arrangement clip shows greyed/silent while "
            "the transport rolls ('transport moving, no audio') — a leftover "
            "firing Session clip is overriding the Arrangement lane.",
            "If cleared:false comes back, the API could not clear the latch — "
            "click Live's Back to Arrangement button in the transport bar.",
        ),
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
        # W3-F follow-up: seek_handler acquires live_state_lock, which is
        # an RLock shared with worker-thread cue handlers. Pre-fix state
        # (default main-thread wrapping) deadlocked when main-thread seek
        # tried to acquire a lock held by a worker-thread cue_create.
        # Every live_state_lock taker must be on the worker thread.
        runs_on_worker=True,
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
# Arrangement loop region — moved to ableton_arrangement(action='set_loop') in
# Wave M-5. The arrangement-loop concern belongs structurally on the
# arrangement tool; the M-5 home also takes meter-agnostic beats (vs M-1's
# bar-based shape). Per no-unnecessary-backwards-compat, this action is
# dropped — agents should call ableton_arrangement(action='set_loop', ...).
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# introspect (W6-Probe — empirical LOM probing for chunk investigations)
# ---------------------------------------------------------------------------

register(
    Action(
        tool="ableton_session",
        name="introspect",
        description=(
            "Read-only LOM probing — call dir() / type() / value / repr "
            "on a dotted-path target rooted at song / application / view. "
            "Used to investigate Live's API surface from a conversation "
            "when the Live 12 LOM XML isn't published or third-party "
            "references are ambiguous. No side effects on the song."
        ),
        params=(
            ParamSpec(
                name="target",
                type="str",
                description=(
                    "Dotted path from one of three roots: 'song' "
                    "(→ context.song), 'application' (→ context.application), "
                    "'view' (→ context.application.view). Each segment is "
                    "`name` or `name[index]`. Example: "
                    "'song.master_track.mixer_device.tempo' or "
                    "'song.tracks[0].clip_slots[1]'. Index is 0-based RAW "
                    "Python — NOT the 1-based MCP convention used for "
                    "track_index etc."
                ),
            ),
            ParamSpec(
                name="what",
                type="str",
                required=False,
                enum=("dir", "type", "value", "repr"),
                description=(
                    "dir: list of public members (filter `_*` unless "
                    "include_private). type: fully-qualified class name. "
                    "value: primitive value if int/float/bool/str/None, "
                    "else repr() with a note flag. repr: always repr(obj). "
                    "Default 'dir'."
                ),
            ),
            ParamSpec(
                name="include_private",
                type="bool",
                required=False,
                description=(
                    "If True, dir results include leading-underscore names. "
                    "Default False (filters them out)."
                ),
            ),
        ),
        handler=session_handlers.introspect_handler,
        example=(
            "ableton_session(action='introspect', "
            "target='song.master_track.mixer_device', what='dir')"
        ),
        tips=(
            "Use this for empirical LOM investigation when third-party "
            "references are stale or unclear. Read-only by design: walks "
            "via getattr + __getitem__ only — no eval, no method "
            "invocation, no setattr.",
            "Indexing on the wire is 0-based (raw Python). The 1-based "
            "convention only applies to track_index / clip_index / etc. "
            "on agent-facing tool args.",
        ),
    )
)


__all__: list[str] = []  # registry side-effects only
