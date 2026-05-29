"""``ableton_device`` action schema.

Actions covering devices on tracks and return tracks:

  - **Read**: list, info, get_parameters
  - **Lifecycle**: load, delete
  - **Activation**: enable, disable
  - **Parameters**: set_parameter (continuous + enum via ``value_type``)
  - **Capability probing**: capabilities (W6-E-2)
  - **Routing**: set_input_routing, get_input_routing, set_sidechain,
    get_routing (W6-E-2 — replaced the prior Compressor-class whitelist
    with capability-probing primitives that work uniformly on native +
    third-party devices)
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


def _parent_addressing_specs() -> tuple[ParamSpec, ParamSpec, ParamSpec]:
    return (
        ParamSpec(
            name="track_index",
            type="int",
            required=False,
            minimum=1,
            description=(
                "1-based track index. Specify EXACTLY ONE of track_index, "
                "return_index, or master=true — devices live on a track, "
                "a return, or the master strip."
            ),
        ),
        ParamSpec(
            name="return_index",
            type="int",
            required=False,
            minimum=1,
            description=(
                "1-based return index. Mutually exclusive with track_index "
                "and master."
            ),
        ),
        ParamSpec(
            name="master",
            type="bool",
            required=False,
            description=(
                "Address the master strip's device chain (master limiters, "
                "master EQs, etc.). Mutually exclusive with track_index and "
                "return_index. Pass `true` to target master; omit otherwise."
            ),
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
            "'kind' is the device's BROWSER DISPLAY NAME (e.g. 'Compressor', "
            "'Operator', 'Reverb', 'Drum Rack', 'Phaser-Flanger'). With "
            "'kind' only, the handler walks the instrument / audio_effect / "
            "midi_effect / drum roots for a loadable node whose display "
            "name equals 'kind' exactly. NOTE: Live's internal class names "
            "(e.g. 'Compressor2', 'PhaserNew', 'DrumGroupDevice') no longer "
            "resolve — pass the display name as seen in Live's browser. "
            "'preset_uri' is the preferred selector for specific presets / "
            "plugins — pass the canonical browser URI captured via "
            "ableton_browser(action='at_path', ...). The device appears at "
            "the END of the destination's device chain; Live 12.4 has no "
            "public reorder API."
        ),
        params=(
            *_parent_addressing_specs(),
            ParamSpec(
                name="kind",
                type="str",
                description=(
                    "Browser display name of the device (e.g. 'Compressor', "
                    "'Operator', 'Drum Rack'). Required even when preset_uri "
                    "is given (used for the response payload)."
                ),
            ),
            ParamSpec(
                name="preset_uri",
                type="str",
                required=False,
                description=(
                    "Canonical Live browser URI for a specific preset / "
                    "instrument / plugin. Per-machine (FileIds differ "
                    "across machines) but unambiguous on this one. Use "
                    "preset_query for cross-machine portability."
                ),
            ),
            ParamSpec(
                name="preset_query",
                type="dict",
                required=False,
                description=(
                    "Compose-time portable preset selection. Dict with "
                    "{root, pattern, mode?, path_prefix?, case_sensitive?} "
                    "resolved at load time via the search primitive. mode "
                    "defaults to 'substring'; use mode='exact' for an "
                    "anchored whole-name match when a precise preset name "
                    "is a substring of another ('Saturated Bass' vs 'Basic "
                    "Saturated Bass'). The composer expresses 'a 909 kit' "
                    "or 'the Late Nite drum rack'; the installed library on "
                    "each machine decides the actual URI. Strict — refuses "
                    "if 0 or 2+ matches. Mutually exclusive with preset_uri."
                ),
            ),
            ParamSpec(
                name="browser_path",
                type="list",
                required=False,
                description=(
                    "W13-A v1.0 fallback identity. List of strings from "
                    "the browser root to the loaded item's name (e.g. "
                    "['plug-ins', 'Native Instruments', 'Massive X', "
                    "'FatBass']). Captured at the original load on the "
                    "authoring machine. When passed alongside preset_uri, "
                    "the handler tries the URI first; if the URI doesn't "
                    "resolve (the FileId differs across machines or the "
                    "plugin moved between catalog versions), falls back "
                    "to a path-scoped browser search by display_name. "
                    "Refuses on 0-match (plugin not installed at the "
                    "captured path) and on multi-match. The path's "
                    "vendor / pack segments discriminate same-display-"
                    "name plugins from different manufacturers."
                ),
            ),
        ),
        handler=device_handlers.load_handler,
        example=(
            "ableton_device(action='load', track_index=2, kind='Compressor')"
        ),
        tips=(
            "Returns {device_index, name, kind} — capture device_index for "
            "subsequent parameter writes.",
            "For portable compose-time selection (cross-machine, no "
            "per-machine FileIds in the snapshot), use preset_query: "
            "{root: 'drums', pattern: 'Late Nite Kit'}.",
            "For an unambiguous per-machine URI, resolve via "
            "ableton_browser(action='at_path', ...) and pass as preset_uri.",
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
        name="capabilities",
        description=(
            "Probe what a device supports — class name, parameter count, "
            "sidechain-shaped param names (substring match for native + "
            "third-party naming), whether it exposes the unified "
            "input_routing_* API, whether it can host chains/drum pads, "
            "third-party plugin flag, active state. Single-call replacement "
            "for firing multiple introspect calls. The structured shape "
            "lets agents decide what action to use without trial and error."
        ),
        params=(
            *_parent_addressing_specs(),
            ParamSpec(name="device_index", type="int", minimum=1),
        ),
        handler=device_handlers.capabilities_handler,
        example=(
            "ableton_device(action='capabilities', track_index=2, "
            "device_index=1)"
        ),
        tips=(
            "Use this BEFORE set_sidechain or set_input_routing on an "
            "unfamiliar device — the response tells you which configuration "
            "paths are available (params vs routing) without poking at "
            "missing APIs.",
        ),
    )
)

register(
    Action(
        tool="ableton_device",
        name="set_input_routing",
        description=(
            "Set a device's input routing (sidechain source) by display_name. "
            "Uniform mechanism: works on any device exposing Live's "
            "input_routing_* API — Compressor / Compressor2, plus third-party "
            "VST3/AU plugins with declared sidechain inputs. Devices without "
            "the API (Glue Compressor, Gate, Multiband Dynamics, older "
            "plugins) raise a teaching error pointing at workarounds."
        ),
        params=(
            *_parent_addressing_specs(),
            ParamSpec(name="device_index", type="int", minimum=1),
            ParamSpec(
                name="type_display_name",
                type="str",
                description=(
                    "Source name as shown in Live's UI: track name "
                    "('1-Drums'), return name ('A-Reverb'), 'Main' "
                    "(master), or 'No Input' to disable."
                ),
            ),
            ParamSpec(
                name="channel_display_name",
                type="str",
                required=False,
                description=(
                    "Optional sub-routing: 'Pre FX' / 'Post FX' / "
                    "'Post Mixer'. Omit to leave the channel unchanged."
                ),
            ),
        ),
        handler=device_handlers.set_input_routing_handler,
        example=(
            "ableton_device(action='set_input_routing', track_index=4, "
            "device_index=1, type_display_name='1-Drums', "
            "channel_display_name='Post FX')"
        ),
    )
)

register(
    Action(
        tool="ableton_device",
        name="get_input_routing",
        description=(
            "Read a device's input routing surface — current type + channel "
            "and the available enums for each. Returns "
            "has_input_routing=False (no raise) for devices that lack the API "
            "— symmetric with capability probing."
        ),
        params=(
            *_parent_addressing_specs(),
            ParamSpec(name="device_index", type="int", minimum=1),
        ),
        handler=device_handlers.get_input_routing_handler,
        example=(
            "ableton_device(action='get_input_routing', track_index=4, "
            "device_index=1)"
        ),
    )
)

register(
    Action(
        tool="ableton_device",
        name="set_sidechain",
        description=(
            "Configure sidechain on any device that exposes the canonical "
            "S/C parameter family (native: Compressor / Compressor2 / Glue "
            "Compressor / Gate / Multiband Dynamics; third-party plugins "
            "matching common naming variants). Convenience bundle: toggles "
            "S/C On, optionally sets source via set_input_routing primitive, "
            "optionally sets S/C Gain. Devices with non-canonical parameter "
            "names should call get_parameters for discovery and set_parameter "
            "directly."
        ),
        params=(
            *_parent_addressing_specs(),
            ParamSpec(name="device_index", type="int", minimum=1),
            ParamSpec(name="enabled", type="bool"),
            ParamSpec(
                name="source_display_name",
                type="str",
                required=False,
                description=(
                    "Sidechain source display_name (e.g. '1-Drums', "
                    "'A-Reverb'). Requires the device to expose "
                    "input_routing_*; otherwise the call raises a teaching "
                    "error after toggling enable."
                ),
            ),
            ParamSpec(
                name="gain_db",
                type="float",
                required=False,
                description=(
                    "Optional S/C Gain in dB. Raises a teaching error if "
                    "the device has no canonical gain param."
                ),
            ),
        ),
        handler=device_handlers.set_sidechain_handler,
        example=(
            "ableton_device(action='set_sidechain', track_index=4, "
            "device_index=1, enabled=True, source_display_name='1-Drums')"
        ),
    )
)

register(
    Action(
        tool="ableton_device",
        name="get_routing",
        description=(
            "Read a device's input routing summary — input_routing_type "
            "display_name (or None if device lacks the API). For the "
            "available enums use get_input_routing; for a fuller capability "
            "report use capabilities."
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


# ---------------------------------------------------------------------------
# Nested rack chains (W6-I / W6-J)
# ---------------------------------------------------------------------------

register(
    Action(
        tool="ableton_device",
        name="get_device_chains",
        description=(
            "Probe a rack device's nested chains. Works for "
            "InstrumentGroupDevice, AudioEffectGroupDevice, and "
            "DrumGroupDevice — each owns chains[] of nested Devices with "
            "their own parameters and (optionally) mixer state. "
            "detail='summary' returns identity-only; detail='full' adds "
            "mixer state per chain and per nested device. Does NOT recurse "
            "into nested-nested racks (filed as backlog)."
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
        handler=device_handlers.get_device_chains_handler,
        example=(
            "ableton_device(action='get_device_chains', track_index=2, "
            "device_index=1, detail='full')"
        ),
        tips=(
            "Pair with `capabilities` (can_have_chains flag) to know "
            "whether a device is a rack before calling. Use "
            "`load_in_rack` to add devices into a specific chain.",
        ),
    )
)

register(
    Action(
        tool="ableton_device",
        name="load_in_rack",
        description=(
            "Load a device into a specific nested chain of a rack. "
            "Uses Live's browser-load mechanism via "
            "`song.view.selected_track` + `rack.view.selected_chain` to "
            "route the load. The new device appears at the end of the "
            "chain's device list. Returns the new device's "
            "nested_device_position for subsequent set_parameter_in_rack "
            "calls."
        ),
        params=(
            *_parent_addressing_specs(),
            ParamSpec(name="device_index", type="int", minimum=1,
                      description="Position of the rack device on its parent's chain (1-based)."),
            ParamSpec(name="chain_index", type="int", minimum=1,
                      description="Position of the destination chain inside the rack (1-based)."),
            ParamSpec(name="kind", type="str",
                      description="Browser display name of the device (e.g. 'Compressor', 'Operator'). Live's internal class names ('Compressor2', etc.) no longer resolve."),
            ParamSpec(
                name="preset_uri",
                type="str",
                required=False,
                description="Optional canonical Live browser URI for a specific preset.",
            ),
        ),
        handler=device_handlers.load_in_rack_handler,
        example=(
            "ableton_device(action='load_in_rack', track_index=2, "
            "device_index=1, chain_index=2, kind='Compressor')"
        ),
    )
)

register(
    Action(
        tool="ableton_device",
        name="set_parameter_in_rack",
        description=(
            "Write a parameter on a device inside a rack's nested chain. "
            "Same continuous/enum value semantics as set_parameter; "
            "address via (rack device_index, chain_index, "
            "nested_device_position, parameter_name)."
        ),
        params=(
            *_parent_addressing_specs(),
            ParamSpec(name="device_index", type="int", minimum=1,
                      description="Position of the rack device on its parent's chain."),
            ParamSpec(name="chain_index", type="int", minimum=1),
            ParamSpec(name="nested_device_position", type="int", minimum=1),
            ParamSpec(name="parameter_name", type="str"),
            ParamSpec(
                name="value",
                type="str",
                description=(
                    "Schema-permissive: a string on the wire so enum "
                    "values round-trip cleanly. The handler coerces to "
                    "float for value_type='continuous' — mirrors "
                    "set_parameter."
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
        handler=device_handlers.set_parameter_in_rack_handler,
        example=(
            "ableton_device(action='set_parameter_in_rack', track_index=2, "
            "device_index=1, chain_index=1, nested_device_position=1, "
            "parameter_name='Threshold', value=0.5)"
        ),
    )
)


__all__: list[str] = []  # registry side-effects only
