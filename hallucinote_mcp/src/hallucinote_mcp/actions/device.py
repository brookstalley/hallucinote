"""``ableton_device`` action schema.

Thirteen actions covering devices on tracks and return tracks:

  - **Read**: list, info, get_parameters
  - **Lifecycle**: load, delete
  - **Activation**: enable, disable
  - **Parameters**: set_parameter (continuous + enum via ``value_type``)
  - **Routing**: set_sidechain, get_routing
  - **Preset**: navigate_preset
  - **Drum rack**: pad_info
  - **Help**: dispatcher-special

Devices live on either a track or a return; the schema accepts exactly one
of ``track_index`` / ``return_index`` (both optional in the schema; the
handler validates exactly-one). Nested rack-chain navigation is out of
M-4 scope — tracked in the backlog.
"""
from __future__ import annotations

from ..handlers import device as device_handlers
from ..schema import Action, ParamSpec, register


_VALUE_TYPES = ("continuous", "enum")
_DETAIL = ("summary", "full")
_PRESET_DIRECTIONS = ("next", "previous", "current")


# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------

register(
    Action(
        tool="ableton_device",
        name="help",
        description=(
            "List all actions on ableton_device, with required/optional "
            "params, examples, and tips."
        ),
        example="ableton_device(action='help')",
    )
)


# ---------------------------------------------------------------------------
# Read: list / info / get_parameters
# ---------------------------------------------------------------------------


def _parent_addressing_specs() -> tuple[ParamSpec, ParamSpec]:
    return (
        ParamSpec(
            name="track_index",
            type="int",
            required=False,
            minimum=1,
            description=(
                "1-based track index. Specify EXACTLY ONE of track_index "
                "or return_index — devices live on either."
            ),
        ),
        ParamSpec(
            name="return_index",
            type="int",
            required=False,
            minimum=1,
            description="1-based return index. Mutually exclusive with track_index.",
        ),
    )


register(
    Action(
        tool="ableton_device",
        name="list",
        description=(
            "Index of devices in a track's or return's top-level chain: "
            "device_index (1-based), name, class_name, is_active. Lightweight "
            "— use action='info' for per-device parameter counts and routing."
        ),
        params=_parent_addressing_specs(),
        handler=device_handlers.list_handler,
        example="ableton_device(action='list', track_index=2)",
        tips=(
            "Specify exactly one of track_index / return_index. Nested rack "
            "chains aren't traversed in M-4 — only the top-level chain.",
        ),
    )
)

register(
    Action(
        tool="ableton_device",
        name="info",
        description=(
            "Identity + activation + parameter count for one device. Use "
            "get_parameters for the actual parameter values."
        ),
        params=(
            *_parent_addressing_specs(),
            ParamSpec(name="device_index", type="int", minimum=1),
        ),
        handler=device_handlers.info_handler,
        example=(
            "ableton_device(action='info', track_index=2, device_index=1)"
        ),
    )
)

register(
    Action(
        tool="ableton_device",
        name="get_parameters",
        description=(
            "Read a device's parameters with current values. detail='summary' "
            "returns name + value + value_display (cheap). detail='full' adds "
            "min/max + is_enum + value_items."
        ),
        params=(
            *_parent_addressing_specs(),
            ParamSpec(name="device_index", type="int", minimum=1),
            ParamSpec(
                name="detail",
                type="str",
                required=False,
                enum=_DETAIL,
                description="'summary' (default) or 'full'.",
            ),
        ),
        handler=device_handlers.get_parameters_handler,
        example=(
            "ableton_device(action='get_parameters', track_index=2, "
            "device_index=1, detail='full')"
        ),
        tips=(
            "Enum parameters appear with is_enum=True and a value_items list "
            "when detail='full'. Use action='set_parameter' with "
            "value_type='enum' to write them.",
        ),
    )
)


# ---------------------------------------------------------------------------
# Lifecycle: load / delete
# ---------------------------------------------------------------------------

register(
    Action(
        tool="ableton_device",
        name="load",
        description=(
            "Load a device onto a track or return chain via Live's browser. "
            "'kind' is the Live device class / display name (e.g. "
            "'Compressor2', 'Operator', 'Reverb'). 'preset_uri' is the "
            "preferred selector — pass the canonical browser URI captured "
            "via ableton_browser(action='at_path', ...) to load a specific "
            "preset, instrument, or plugin. With 'kind' only, the handler "
            "walks the instrument / audio_effect / midi_effect / drum roots "
            "for the first loadable node whose display name matches. The "
            "device appears at the END of the destination's device chain; "
            "Live 12.4 has no public reorder API."
        ),
        params=(
            *_parent_addressing_specs(),
            ParamSpec(
                name="kind",
                type="str",
                description=(
                    "Live device class / display name. Required even when "
                    "preset_uri is given (used for the response payload)."
                ),
            ),
            ParamSpec(
                name="preset_uri",
                type="str",
                required=False,
                description=(
                    "Canonical Live browser URI for a specific preset / "
                    "instrument / plugin. Preferred over kind-only matching "
                    "for anything beyond built-in Live device classes."
                ),
            ),
        ),
        handler=device_handlers.load_handler,
        example=(
            "ableton_device(action='load', track_index=2, kind='Compressor2')"
        ),
        tips=(
            "Returns {device_index, name, kind} — capture device_index for "
            "subsequent parameter writes. To target a specific preset, "
            "resolve its URI with ableton_browser(action='at_path', ...) "
            "and pass it as preset_uri.",
        ),
    )
)

register(
    Action(
        tool="ableton_device",
        name="delete",
        description="Remove a device from a track or return chain.",
        params=(
            *_parent_addressing_specs(),
            ParamSpec(name="device_index", type="int", minimum=1),
        ),
        handler=device_handlers.delete_handler,
        example=(
            "ableton_device(action='delete', track_index=2, device_index=3)"
        ),
        tips=(
            "Device indices on the same chain shift down after a delete; "
            "delete in descending order or recompute between calls.",
        ),
    )
)


# ---------------------------------------------------------------------------
# Activation: enable / disable
# ---------------------------------------------------------------------------

register(
    Action(
        tool="ableton_device",
        name="enable",
        description="Activate a device (sets is_active=True).",
        params=(
            *_parent_addressing_specs(),
            ParamSpec(name="device_index", type="int", minimum=1),
        ),
        handler=device_handlers.enable_handler,
        example=(
            "ableton_device(action='enable', track_index=2, device_index=1)"
        ),
    )
)

register(
    Action(
        tool="ableton_device",
        name="disable",
        description="Deactivate a device (sets is_active=False, bypass).",
        params=(
            *_parent_addressing_specs(),
            ParamSpec(name="device_index", type="int", minimum=1),
        ),
        handler=device_handlers.disable_handler,
        example=(
            "ableton_device(action='disable', track_index=2, device_index=1)"
        ),
    )
)


# ---------------------------------------------------------------------------
# Parameters
# ---------------------------------------------------------------------------

register(
    Action(
        tool="ableton_device",
        name="set_parameter",
        description=(
            "Write one device parameter by name. value_type='continuous' "
            "(default) requires a numeric value in [param.min, param.max]. "
            "value_type='enum' requires a string in the parameter's "
            "value_items — resolves the legacy fork's gap #17b workaround."
        ),
        params=(
            *_parent_addressing_specs(),
            ParamSpec(name="device_index", type="int", minimum=1),
            ParamSpec(name="parameter_name", type="str"),
            ParamSpec(
                name="value",
                type="str",
                description=(
                    "Schema-permissive: a string on the wire so enum values "
                    "round-trip cleanly. The handler coerces to float for "
                    "value_type='continuous'."
                ),
            ),
            ParamSpec(
                name="value_type",
                type="str",
                required=False,
                enum=_VALUE_TYPES,
                description="'continuous' (default) or 'enum'.",
            ),
        ),
        handler=device_handlers.set_parameter_handler,
        example=(
            "ableton_device(action='set_parameter', track_index=2, "
            "device_index=1, parameter_name='Threshold', value='-12.0')"
        ),
        tips=(
            "For enum parameters: set value_type='enum' and value to one of "
            "the parameter's value_items (use get_parameters detail='full' "
            "to inspect).",
        ),
    )
)


# ---------------------------------------------------------------------------
# Routing / preset / pad_info
# ---------------------------------------------------------------------------

register(
    Action(
        tool="ableton_device",
        name="set_sidechain",
        description=(
            "Configure a Compressor's sidechain (M-4 supports Compressor / "
            "Compressor2; wider device-class support is a backlog item). "
            "enabled=False bypasses sidechain. enabled=True requires "
            "source_track_index; optional gain_db sets the SC Gain parameter."
        ),
        params=(
            *_parent_addressing_specs(),
            ParamSpec(name="device_index", type="int", minimum=1),
            ParamSpec(name="enabled", type="bool"),
            ParamSpec(
                name="source_track_index",
                type="int",
                required=False,
                minimum=1,
                description="1-based track to use as the sidechain source.",
            ),
            ParamSpec(
                name="gain_db",
                type="float",
                required=False,
                description="Optional SC Gain in dB.",
            ),
        ),
        handler=device_handlers.set_sidechain_handler,
        example=(
            "ableton_device(action='set_sidechain', track_index=4, "
            "device_index=1, enabled=True, source_track_index=2, gain_db=0.0)"
        ),
    )
)

register(
    Action(
        tool="ableton_device",
        name="get_routing",
        description=(
            "Read a device's input routing summary: input_routing name + "
            "sidechain_active flag."
        ),
        params=(
            *_parent_addressing_specs(),
            ParamSpec(name="device_index", type="int", minimum=1),
        ),
        handler=device_handlers.get_routing_handler,
        example=(
            "ableton_device(action='get_routing', track_index=4, device_index=1)"
        ),
    )
)

register(
    Action(
        tool="ableton_device",
        name="navigate_preset",
        description=(
            "Step a device's preset within its browser folder. "
            "direction='current' reads the current preset; 'next'/'previous' "
            "step it. Not all device classes support preset navigation."
        ),
        params=(
            *_parent_addressing_specs(),
            ParamSpec(name="device_index", type="int", minimum=1),
            ParamSpec(name="direction", type="str", enum=_PRESET_DIRECTIONS),
        ),
        handler=device_handlers.navigate_preset_handler,
        example=(
            "ableton_device(action='navigate_preset', track_index=2, "
            "device_index=1, direction='next')"
        ),
    )
)

register(
    Action(
        tool="ableton_device",
        name="pad_info",
        description=(
            "Drum-rack pad layout: returns the non-empty pads as a list of "
            "{note, name, chain_name}. Errors on non-drum-rack devices."
        ),
        params=(
            *_parent_addressing_specs(),
            ParamSpec(name="device_index", type="int", minimum=1),
        ),
        handler=device_handlers.pad_info_handler,
        example=(
            "ableton_device(action='pad_info', track_index=2, device_index=1)"
        ),
    )
)


__all__: list[str] = []  # registry side-effects only
