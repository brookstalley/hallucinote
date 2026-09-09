"""``ableton_device`` action schema.

Actions covering devices on tracks and return tracks:

  - **Read**: list, info, get_parameters
  - **Lifecycle**: load, delete, assign_sample (hand a sampler its file)
  - **Activation**: enable, disable
  - **Parameters**: set_parameter (continuous via raw ``value`` or display-unit
    ``value_display``; enum via ``value_type``)
  - **Capability probing**: capabilities (W6-E-2)
  - **Routing**: set_input_routing, get_input_routing, set_sidechain,
    get_routing (W6-E-2 — replaced the prior Compressor-class whitelist
    with capability-probing primitives that work uniformly on native +
    third-party devices)
  - **Preset**: navigate_preset
  - **Drum rack**: pad_info
  - **Nested racks**: get_device_chains (recursive probe). DEEP-RACK-ADDR
    folded the one-level ``load_in_rack`` / ``set_parameter_in_rack`` actions
    into ``load`` (``device_path`` + ``chain_index``) and ``set_parameter``
    (``device_path``) — one canonical address shape at every depth.
  - **Help**: dispatcher-special

The node-addressed actions (get_parameters / set_parameter / load /
set_sidechain) take a single ``node`` object (NODE-ADDR design §1c) — the
frozen addressing unit — replacing the retired flat combo
(``track_index``/``return_index``/``master`` + ``device_index`` +
``device_path``). The same object is the as-value shape (set_sidechain's
``source``). The shallow navigation surfaces (list / info / get_routing /
navigate_preset / pad_info / set_input_routing) keep flat
``track_index``/``return_index``/``master`` — they address a track/return/
device directly without the chain terminal or as-value need.
"""
from __future__ import annotations

from ..handlers import device as device_handlers
from ..schema import Action, ParamSpec, node_addr_spec, register


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


def _device_path_spec() -> ParamSpec:
    """The canonical optional address into a nested rack device (DEEP-RACK-ADDR).

    Shared by ``get_parameters`` / ``set_parameter`` / ``load`` so the nested
    address shape is identical everywhere.
    """
    return ParamSpec(
        name="device_path",
        type="list",
        required=False,
        description=(
            "Optional address into a NESTED rack device, to any depth. A list "
            "of {chain_index, device_position} steps (both 1-based) from the "
            "top-level device_index device — each step descends one rack "
            "level: pick chain `chain_index`, then device `device_position` in "
            "that chain. Omit for a top-level device. Get the exact path from "
            "ableton_device(action='get_device_chains'), which reports a "
            "`device_path` for every nested device."
        ),
    )


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
        # A large sampled rack (a Brass Ensemble, a 16-pad Drum Rack) walks far
        # past the 15s default with detail='full'; that is what aborted a whole
        # `capture execute` mid-walk. Mirrors client._READ_TIMEOUTS.
        main_thread_timeout=90.0,
        description=(
            "Read a device's parameters with current values. detail='summary' "
            "returns name + value + value_display + default_value (cheap). "
            "detail='full' adds min/max + is_enum + value_items. Address the "
            "device with `node` (terminal 'device', path for nested racks)."
        ),
        params=(
            node_addr_spec(
                description="The device to read (terminal 'device')."
            ),
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
            "ableton_device(action='get_parameters', "
            "node={'parent': {'kind': 'track', 'index': 2}, 'device_index': 1}, "
            "detail='full')"
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
        # A browser load costs whatever the ITEM costs, not what our call costs.
        # Instantiating a Max for Live device is the worst case — the ~490 KB
        # HallucinoteAnalyzer blocks Live's main thread for tens of seconds, and
        # the 15s default turned that into a false failure whose retry queued
        # more work behind the still-running load. Mirrors client._READ_TIMEOUTS.
        main_thread_timeout=120.0,
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
            node_addr_spec(
                description=(
                    "The load DESTINATION. terminal 'track'/'return'/'master' "
                    "(the default for a node-itself address) loads onto that "
                    "node's main device chain; terminal 'chain' (device_index "
                    "+ chain_index, + optional path for a deeper rack) loads "
                    "INTO a nested rack chain — the unified replacement for "
                    "load_in_rack. A 'device' terminal is not a load "
                    "destination."
                )
            ),
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
            "ableton_device(action='load', "
            "node={'parent': {'kind': 'track', 'index': 2}, "
            "'terminal': 'track'}, kind='Compressor')"
        ),
        tips=(
            "Returns {device_index, name, kind} — capture device_index for "
            "subsequent parameter writes.",
            "For portable compose-time selection (cross-machine, no "
            "per-machine FileIds in the snapshot), use preset_query: "
            "{root: 'drums', pattern: 'Late Nite Kit'}.",
            "For an unambiguous per-machine URI, resolve via "
            "ableton_browser(action='at_path', ...) and pass as preset_uri.",
            "To load INTO a rack chain, address it with a 'chain' terminal: "
            "node={parent, device_index (the rack), chain_index (the "
            "destination chain), terminal: 'chain'} — plus path to reach a "
            "deeper rack. Returns nested_device_position.",
        ),
    )
)

register(
    Action(
        tool="ableton_device",
        name="assign_sample",
        description=(
            "Point a sampler instrument (Simpler / Sampler) at an audio file "
            "on disk. Replaces whatever sample the device carried, so calling "
            "it again with the same path is a no-op in effect — the push "
            "devices phase emits it without tracking whether it already ran. "
            "Refuses a device with no sample slot, a relative path, and a path "
            "with no file at it, each with its own reason."
        ),
        params=(
            *_parent_addressing_specs(),
            ParamSpec(name="device_index", type="int", minimum=1),
            _device_path_spec(),
            ParamSpec(
                name="sample_path",
                type="str",
                description=(
                    "ABSOLUTE path to the audio file, on the machine running "
                    "Live. Live resolves nothing relative to a working "
                    "directory."
                ),
            ),
        ),
        handler=device_handlers.assign_sample_handler,
        example=(
            "ableton_device(action='assign_sample', track_index=2, "
            "device_index=1, sample_path='/Users/me/songs/x/assets/vox.wav')"
        ),
        tips=(
            "Returns sample_file_path read back off the device — compare it "
            "with what you sent to confirm the assignment landed.",
            "For a sampler nested in a rack, pass device_path (the same "
            "address ableton_device(action='get_device_chains') reports) "
            "alongside the rack's device_index.",
            "action='list' and action='info' report sample_file_path for any "
            "device that has a sample slot; the key is absent entirely on a "
            "device that cannot hold one.",
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
            "(default): pass EXACTLY ONE of `value` — the RAW float in "
            "[param.min, param.max] (Live's own scale; normalized [0,1] for "
            "many params, so '0.85' not '-3 dB') — or `value_display`, the "
            "display units as a string ('-18 dB', '3:1', '20 ms'), which the "
            "handler inverts to the raw value for you. value_type='enum' "
            "requires a string `value` in the parameter's value_items. Use a "
            "`node` with a `path` to write a parameter on a device nested "
            "inside a rack (any depth) — the unified replacement for "
            "set_parameter_in_rack. Resolves the legacy fork's gap #17b "
            "workaround."
        ),
        params=(
            node_addr_spec(
                description="The device to write (terminal 'device')."
            ),
            ParamSpec(name="parameter_name", type="str"),
            ParamSpec(
                name="value",
                type="str",
                required=False,
                description=(
                    "Schema-permissive string on the wire (enum values "
                    "round-trip cleanly). For value_type='continuous' it is "
                    "the RAW value, coerced to float and range-checked against "
                    "[param.min, param.max] — NOT display units. Use "
                    "`value_display` for dB / ratios / ms. Omit when using "
                    "`value_display`."
                ),
            ),
            ParamSpec(
                name="value_display",
                type="str",
                required=False,
                description=(
                    "Continuous-only: target in display units as a string "
                    "('-18 dB', '3:1', '20 ms', '80 Hz'). Inverted to the raw "
                    "value via the parameter's display curve. Mutually "
                    "exclusive with `value`. Refused for enum params and for "
                    "params whose display can't be addressed numerically "
                    "(e.g. Expansion Ratio's '1 : 1.15')."
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
            "ableton_device(action='set_parameter', "
            "node={'parent': {'kind': 'track', 'index': 2}, 'device_index': 1}, "
            "parameter_name='Threshold', value_display='-18 dB')"
        ),
        tips=(
            "Continuous params: use `value_display` ('-18 dB', '3:1') to hit a "
            "musical target without knowing the normalized mapping, or `value` "
            "for the raw [param.min, param.max] float. The response echoes the "
            "achieved `value_display` so you can confirm the target was hit.",
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
                    "Source name as shown in Live's routing menu: the BARE "
                    "track name ('Drums' / '02 Kit Punk' — NOT index-prefixed "
                    "like '1-Drums', which fails), a return's letter-prefixed "
                    "name ('A-Reverb'), 'Main' (master), or 'No Input' to "
                    "disable."
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
            "device_index=1, type_display_name='Drums', "
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
            node_addr_spec(
                description=(
                    "The sidechained device (terminal 'device', top-level)."
                )
            ),
            ParamSpec(name="enabled", type="bool"),
            node_addr_spec(
                name="source",
                required=False,
                description=(
                    "Sidechain source AS A NODE (the as-value shape): a "
                    "track/return/master-terminal node whose name is the "
                    "routing source (e.g. {parent: {kind: 'track', index: 3}, "
                    "terminal: 'track'} routes from track 3). Resolved to its "
                    "name and applied via the set_input_routing primitive; "
                    "requires the device to expose input_routing_*. For the "
                    "special non-node sources ('No Input' / 'Main'), use "
                    "set_input_routing directly."
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
            "ableton_device(action='set_sidechain', "
            "node={'parent': {'kind': 'track', 'index': 4}, 'device_index': 1}, "
            "enabled=True, "
            "source={'parent': {'kind': 'track', 'index': 1}, "
            "'terminal': 'track'})"
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
# Nested rack chains (W6-I / W6-J; DEEP-RACK-ADDR depth-N generalization)
#
# `load_in_rack` / `set_parameter_in_rack` retired — folded into `load`
# (device_path + chain_index) and `set_parameter` (device_path). One canonical
# address shape (`device_path`) at every depth; `get_device_chains` recurses
# and reports each nested device's path.
# ---------------------------------------------------------------------------

register(
    Action(
        tool="ableton_device",
        name="get_device_chains",
        description=(
            "Probe a rack device's nested chains — RECURSIVELY, to any depth. "
            "Works for InstrumentGroupDevice, AudioEffectGroupDevice, and "
            "DrumGroupDevice — each owns chains[] of nested Devices with their "
            "own parameters and (optionally) mixer state. Every device entry "
            "carries `is_rack` + its full `device_path`; pass that path back "
            "to set_parameter / get_parameters to read or write the nested "
            "device. Devices that are themselves racks carry their own nested "
            "chains, so one call maps the whole tree. detail='summary' returns "
            "identity-only; detail='full' adds mixer state per chain and "
            "nested device."
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
            "whether a device is a rack before calling.",
            "Copy a nested device's reported `device_path` straight into "
            "set_parameter / get_parameters / load (chain_index) — never "
            "hand-count indices.",
        ),
    )
)


register(
    Action(
        tool="ableton_device",
        name="set_chain_property",
        description=(
            "Set a chain's authored properties, addressed by a `chain`-terminal "
            "NodeAddr (device_index = the rack, chain_index = which chain). Pass "
            "at least one; any combination may be set at once. Two families, each "
            "capability-probed (a teaching error points at "
            "ableton://reference/node-feature-matrix): "
            "(1) PER-DRUM, DrumChain only — choke_group (0 = no choke group; "
            "non-zero groups cut each other off, e.g. open/closed hats) and "
            "out_note (MIDI transpose; equal to the pad's in_note = no "
            "transpose). (2) PER-CHAIN MIXER, every chain — mute / solo (bools) "
            "and volume (0..1) / pan (-1..1). Get the chain_index from "
            "ableton_device(action='get_device_chains')."
        ),
        params=(
            node_addr_spec(
                description=(
                    "The chain (terminal 'chain'): device_index = the rack, "
                    "chain_index = which chain on it."
                )
            ),
            ParamSpec(
                name="choke_group",
                type="int",
                required=False,
                minimum=0,
                description=(
                    "DrumChain only. Live choke-group id (0 = no choke group). "
                    "Pads sharing a non-zero group cut each other off."
                ),
            ),
            ParamSpec(
                name="out_note",
                type="int",
                required=False,
                minimum=0,
                maximum=127,
                description=(
                    "DrumChain only. MIDI note the chain emits (transpose "
                    "target). Equal to the pad's in_note means no transpose."
                ),
            ),
            ParamSpec(
                name="mute",
                type="bool",
                required=False,
                description="Mute this chain (every chain; default unmuted).",
            ),
            ParamSpec(
                name="solo",
                type="bool",
                required=False,
                description="Solo this chain (every chain; default unsoloed).",
            ),
            ParamSpec(
                name="volume",
                type="float",
                required=False,
                minimum=0.0,
                maximum=1.0,
                description=(
                    "Chain mixer volume, 0.0..1.0 normalized (the "
                    "ChainMixerDevice volume param; ~0.85 = unity)."
                ),
            ),
            ParamSpec(
                name="pan",
                type="float",
                required=False,
                minimum=-1.0,
                maximum=1.0,
                description=(
                    "Chain mixer pan, -1.0 (hard left) .. 1.0 (hard right); "
                    "0.0 = centre."
                ),
            ),
        ),
        handler=device_handlers.set_chain_property_handler,
        example=(
            "ableton_device(action='set_chain_property', "
            "node={'parent': {'kind': 'track', 'index': 2}, 'terminal': 'chain', "
            "'device_index': 1, 'chain_index': 1}, mute=True, volume=0.7)"
        ),
    )
)


__all__: list[str] = []  # registry side-effects only
