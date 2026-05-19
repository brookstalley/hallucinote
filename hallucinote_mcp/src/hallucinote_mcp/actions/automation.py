"""``ableton_automation`` action schema.

Six actions covering automation envelopes across all seven Live target
families:

  - **Write**: write_envelope (the load-bearing collapse — 8 fork tools → 1)
  - **Destroy**: clear (one envelope), clear_all (all on clip OR parent)
  - **Read (gap-blocked)**: list, get_envelope — stubs citing the MCP
    envelope-read surface gap. Hallucinote's pull skill documents this as
    a blocked domain.
  - **Help**: dispatcher-special

write_envelope's ``target_kind`` discriminator selects among seven shapes:

  ``clip_cc``, ``clip_pitch_bend``, ``note_expression``,
  ``device_parameter``, ``mixer_volume``, ``mixer_pan``, ``send_level``.

Each target_kind requires a specific identifier set; the handler validates
per-kind and surfaces a clear teaching error on misuse.

Time is in **beats** on the wire. The Hallucinote planner converts from
bar-based song positions before emit — MCP stays meter-agnostic.
"""
from __future__ import annotations

from ..handlers import automation as automation_handlers
from ..handlers.automation import TARGET_KINDS as _TARGET_KINDS
from ..schema import Action, ParamSpec, register


_LOCATION_ENUM = ("session", "arrangement")
_AXIS_ENUM = ("pitch", "pressure", "timbre")


# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------

register(
    Action(
        tool="ableton_automation",
        name="help",
        description=(
            "List all actions on ableton_automation, with required/optional "
            "params, examples, and tips. The 'write_envelope' action's "
            "required identifier set depends on target_kind — see tips on "
            "that action for the per-kind requirements."
        ),
        example="ableton_automation(action='help')",
    )
)


# ---------------------------------------------------------------------------
# Common parameter spec helpers (one per cross-cutting addressing concern)
# ---------------------------------------------------------------------------


def _envelope_target_params() -> tuple[ParamSpec, ...]:
    """Wide identifier set; write_envelope validates per-kind which subset is
    required. Schema keeps them all optional + the handler enforces
    target_kind-specific requirements — this is cleaner than seven separate
    action signatures since the consumer (planner) writes the discriminator
    once.
    """
    return (
        ParamSpec(name="track_index", type="int", required=False, minimum=1),
        ParamSpec(name="return_index", type="int", required=False, minimum=1),
        ParamSpec(
            name="clip_index", type="int", required=False, minimum=1,
            description=(
                "1-based session slot OR arrangement-clip index. Required "
                "for ALL target_kinds on Live 12.4 — the LOM exposes "
                "envelope creation only through Clip.create_automation_"
                "envelope, so mixer / pan / send / device-parameter "
                "envelopes must address a containing clip just like "
                "clip_cc / clip_pitch_bend / note_expression."
            ),
        ),
        ParamSpec(
            name="location", type="str", required=False, enum=_LOCATION_ENUM,
            description=(
                "'session' or 'arrangement'. Required whenever clip_index "
                "is set."
            ),
        ),
        ParamSpec(name="device_index", type="int", required=False, minimum=1),
        ParamSpec(
            name="parameter_name", type="str", required=False,
            description="Required for target_kind='device_parameter'.",
        ),
        ParamSpec(
            name="cc_number", type="int", required=False, minimum=0,
            maximum=127, description="Required for target_kind='clip_cc'.",
        ),
        ParamSpec(
            name="note_pitch", type="int", required=False, minimum=0,
            maximum=127,
            description=(
                "Required for target_kind='note_expression'. The note is "
                "identified by (pitch, start_beats) — MPE per-note envelopes."
            ),
        ),
        ParamSpec(
            name="note_start_beats", type="float", required=False, minimum=0.0,
            description=(
                "Required for target_kind='note_expression'. The note's "
                "start time in beats."
            ),
        ),
        ParamSpec(
            name="axis", type="str", required=False, enum=_AXIS_ENUM,
            description=(
                "Required for target_kind='note_expression'. The MPE axis: "
                "pitch (semitone offsets — supports microtonal), pressure, "
                "or timbre."
            ),
        ),
    )


# ---------------------------------------------------------------------------
# write_envelope — the load-bearing collapse
# ---------------------------------------------------------------------------

register(
    Action(
        tool="ableton_automation",
        name="write_envelope",
        description=(
            "Write a single automation envelope. target_kind selects among "
            "seven shapes: clip_cc, clip_pitch_bend, note_expression, "
            "device_parameter, mixer_volume, mixer_pan, send_level. The "
            "required identifier set depends on target_kind — the handler "
            "validates and surfaces a teaching error on misuse. breakpoints "
            "is a list of {time_beats, value, curve?} dicts (time in beats; "
            "must be sorted; curve in linear|hold|fast|slow, default linear)."
        ),
        params=(
            ParamSpec(name="target_kind", type="str", enum=_TARGET_KINDS),
            ParamSpec(
                name="breakpoints",
                type="list",
                description=(
                    "[{time_beats: float, value: float, "
                    "curve?: linear|hold|fast|slow}, ...]. Sorted by "
                    "time_beats. Time is in beats (Hallucinote planner "
                    "converts from bar-based song positions)."
                ),
            ),
            *_envelope_target_params(),
        ),
        handler=automation_handlers.write_envelope_handler,
        example=(
            "ableton_automation(action='write_envelope', "
            "target_kind='mixer_volume', track_index=2, "
            "breakpoints=[{time_beats:0.0, value:0.5}, "
            "{time_beats:16.0, value:0.8, curve:'linear'}])"
        ),
        tips=(
            "Per-target_kind required identifiers (Live 12.4 — ALL kinds "
            "require a containing clip; track-level / clip-less paths "
            "are not exposed by the LOM): "
            "clip_cc → track_index + location + clip_index + cc_number; "
            "clip_pitch_bend → track_index + location + clip_index; "
            "note_expression → track_index + location + clip_index + "
            "note_pitch + note_start_beats + axis; "
            "device_parameter → (track_index | return_index) + "
            "device_index + parameter_name + location + clip_index; "
            "mixer_volume / mixer_pan → (track_index | return_index) "
            "+ location + clip_index; "
            "send_level → track_index + return_index + location + "
            "clip_index.",
            "Breakpoints must be sorted by time_beats — the handler "
            "raises with the offending index if not.",
            "Live 12.4's Envelope only exposes insert_step — segments / "
            "curves are not in the LOM. Non-'hold' curve hints are "
            "recorded in the DB but applied as step transitions; the "
            "response carries a 'notes' field describing the fallback.",
            "Time is in beats. The Hallucinote planner converts from "
            "bar-based song positions via the time-signature map. MCP "
            "stays meter-agnostic.",
        ),
    )
)


# ---------------------------------------------------------------------------
# clear / clear_all
# ---------------------------------------------------------------------------

register(
    Action(
        tool="ableton_automation",
        name="clear",
        description=(
            "Clear one specific envelope. Same identifier set as "
            "write_envelope (minus breakpoints). Live 12.4's "
            "`Clip.clear_envelope` is idempotent — no error when the "
            "envelope was absent — and the LOM has no existence probe, "
            "so the response always reports `cleared: True` after a "
            "successful invocation. Pair with `get_envelope` for the "
            "was-it-present signal once the envelope read surface gap "
            "closes. clip-less mixer / pan / send / device_parameter "
            "calls raise the same teaching error as write_envelope; "
            "target_kind='note_expression' is not exposed by Live 12.4's "
            "per-target clear surface — use action='clear_all'."
        ),
        params=(
            ParamSpec(name="target_kind", type="str", enum=_TARGET_KINDS),
            *_envelope_target_params(),
        ),
        handler=automation_handlers.clear_handler,
        example=(
            "ableton_automation(action='clear', target_kind='mixer_volume', "
            "track_index=2, location='arrangement', clip_index=1)"
        ),
    )
)

register(
    Action(
        tool="ableton_automation",
        name="clear_all",
        description=(
            "Clear ALL envelopes on a clip OR all arrangement-level "
            "envelopes on a track/return. Clip-scoped requires "
            "track_index + location + clip_index. Parent-scoped requires "
            "exactly one of track_index / return_index."
        ),
        params=(
            ParamSpec(name="track_index", type="int", required=False, minimum=1),
            ParamSpec(name="return_index", type="int", required=False, minimum=1),
            ParamSpec(name="clip_index", type="int", required=False, minimum=1),
            ParamSpec(
                name="location", type="str", required=False,
                enum=_LOCATION_ENUM,
            ),
        ),
        handler=automation_handlers.clear_all_handler,
        example=(
            "ableton_automation(action='clear_all', track_index=2, "
            "location='session', clip_index=1)"
        ),
        tips=(
            "Destructive — there is no undo via this action. Pair with "
            "Hallucinote's pull to checkpoint envelope state first.",
        ),
    )
)


# ---------------------------------------------------------------------------
# Gap-blocked read surface: list, get_envelope
# ---------------------------------------------------------------------------

register(
    Action(
        tool="ableton_automation",
        name="list",
        description=(
            "[BLOCKED — MCP envelope read surface gap] Enumerate existing "
            "envelopes on a clip / track / return. Once the underlying "
            "read surface lands, returns "
            "[{target_kind, parameter_identifier, breakpoint_count}, ...]."
        ),
        params=(
            ParamSpec(name="track_index", type="int", required=False, minimum=1),
            ParamSpec(name="return_index", type="int", required=False, minimum=1),
            ParamSpec(name="clip_index", type="int", required=False, minimum=1),
            ParamSpec(
                name="location", type="str", required=False,
                enum=_LOCATION_ENUM,
            ),
        ),
        handler=automation_handlers.list_handler,
        example=(
            "ableton_automation(action='list', track_index=2, "
            "location='session', clip_index=1)"
        ),
        tips=(
            "Currently raises a teaching error citing the envelope-read "
            "gap. To write a fresh envelope, use action='write_envelope'.",
        ),
    )
)

register(
    Action(
        tool="ableton_automation",
        name="get_envelope",
        description=(
            "Read a single envelope's reconstructed breakpoints. Alias "
            "for read_envelope — same shape, same params. W6-G/W6-H "
            "(2026-05-19) closed the previous gap-blocked status via a "
            "sampling-based reconstruction (Live's LOM exposes only "
            "value_at_time, not breakpoint enumeration; the handler "
            "samples at resolution_beats and emits a breakpoint at each "
            "step transition)."
        ),
        params=(
            ParamSpec(name="target_kind", type="str", enum=_TARGET_KINDS),
            *_envelope_target_params(),
            ParamSpec(
                name="resolution_beats",
                type="float",
                required=False,
                description=(
                    "Sampling resolution for reconstruction (default "
                    "1/96 beat ≈ 3.1ms at 120BPM). Smaller = finer step "
                    "localization at the cost of more samples."
                ),
            ),
        ),
        handler=automation_handlers.get_envelope_handler,
        example=(
            "ableton_automation(action='get_envelope', "
            "target_kind='device_parameter', track_index=2, "
            "location='session', clip_index=1, device_index=1, "
            "parameter_name='Threshold')"
        ),
    )
)

register(
    Action(
        tool="ableton_automation",
        name="read_envelope",
        description=(
            "Read an envelope's reconstructed breakpoints. Sampling-"
            "based: Live's AutomationEnvelope exposes only "
            "value_at_time(t), not breakpoint enumeration. The handler "
            "samples across the clip's [0, length_beats] range at "
            "resolution_beats and emits a breakpoint at each step "
            "transition. Step changes are localized to within "
            "resolution_beats; pass a smaller value for finer fidelity. "
            "Returns exists=False (no raise) when no envelope is bound "
            "to the target."
        ),
        params=(
            ParamSpec(name="target_kind", type="str", enum=_TARGET_KINDS),
            *_envelope_target_params(),
            ParamSpec(
                name="resolution_beats",
                type="float",
                required=False,
                description=(
                    "Sampling resolution (default 1/96 beat). Smaller = "
                    "finer step localization at the cost of more samples."
                ),
            ),
        ),
        handler=automation_handlers.read_envelope_handler,
        example=(
            "ableton_automation(action='read_envelope', "
            "target_kind='mixer_volume', track_index=2, "
            "location='session', clip_index=1)"
        ),
        tips=(
            "clip_cc and clip_pitch_bend remain blocked by Live 12.4 "
            "LOM (same constraint as write_envelope). Read CC envelopes "
            "indirectly via ableton_clip's note read for the "
            "control-change-note encoding pattern.",
        ),
    )
)


__all__: list[str] = []  # registry side-effects only
